import argparse
import copy
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch.utils.data import DataLoader

from noauthbot import checkpoint as checkpoints
from noauthbot.data.dataset import EvalStream, TrainStream, collate
from noauthbot.data.split import is_small
from noauthbot.model import build
from noauthbot.paths import DATA, RENDERED, SPLIT
from noauthbot.peaks import cells, peaks

THRESHOLDS = [round(threshold, 2) for threshold in np.arange(0.10, 0.91, 0.05)]
LOSS_NAMES = ("loss", "heat", "off", "star", "amb", "sym")
TARGET_KEYS = ("heat", "weight", "star", "amb", "off_idx", "off", "sym_idx", "sym_img", "sym_cls")
SYM_TEMPERATURE = 0.1
LOG_EVERY = 200


def focal_loss(logits, target, weight=None, alpha=2.0, beta=4.0):
    probability = torch.sigmoid(logits.float()).clamp(1e-4, 1 - 1e-4)
    positive = target.eq(1).float()
    negative = 1 - positive if weight is None else (1 - positive) * weight
    positive_loss = -torch.log(probability) * (1 - probability) ** alpha * positive
    negative_loss = -torch.log(1 - probability) * probability**alpha * (1 - target) ** beta * negative
    return (positive_loss.sum() + negative_loss.sum()) / positive.sum().clamp_min(1)


def offset_loss(offset, index, target):
    if index.numel() == 0:
        return offset.sum() * 0
    per_cell = offset.float().permute(0, 2, 3, 1).reshape(-1, 2)
    return F.l1_loss(per_cell[index], target)


def symmetry_loss(embeddings, pixels, images, colours):
    depths, atoms = colours.shape[1], len(pixels)
    vectors = embeddings.float().permute(0, 2, 3, 1).reshape(-1, embeddings.shape[1])[pixels]
    vectors = F.normalize(vectors.view(atoms, depths, -1), dim=-1).transpose(0, 1)
    logits = vectors @ vectors.transpose(1, 2) / SYM_TEMPERATURE

    not_self = ~torch.eye(atoms, dtype=torch.bool, device=pixels.device)
    same_image = (images[:, None] == images[None, :]) & not_self
    # use a large finite fill instead of -inf, so that an atom alone in its image cannot produce NaN
    log_prob = logits.masked_fill(~same_image, -1e4).log_softmax(-1)
    by_depth = colours.T
    positive = same_image & (by_depth[:, :, None] == by_depth[:, None, :])
    positives = positive.sum(-1)

    per_anchor = -log_prob.masked_fill(~positive, 0).sum(-1) / positives.clamp_min(1)
    anchored = positives > 0
    return per_anchor[anchored].mean() if bool(anchored.any()) else logits.sum() * 0


@dataclass
class Prediction:
    variant: str
    small: bool
    rows: np.ndarray
    width: int
    height: int
    truth: list[str]

    def correct(self, threshold: float) -> bool:
        return cells(self.rows, self.width, self.height, threshold) == self.truth


def prediction(rows: np.ndarray, label: dict) -> Prediction:
    return Prediction(
        label["variant"], is_small(label), rows, label["width"], label["height"], sorted(label["answer_cells"])
    )


def pass_rate(predictions: list[Prediction], threshold: float) -> float | None:
    if not predictions:
        return None
    return float(np.mean([prediction.correct(threshold) for prediction in predictions]))


@torch.no_grad()
def validate(model, loader, device) -> dict[str, Any]:
    model.eval()
    predictions: list[Prediction] = []
    for batch in loader:
        images = batch["image"].to(device, non_blocking=True).to(memory_format=torch.channels_last)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = model(images)
        heat, offset = (out[name].float().cpu().numpy() for name in ("heat", "offset"))
        predictions += map(prediction, peaks(heat, offset, batch["width"], batch["height"]), batch["label"])
    model.train()

    by_threshold = {threshold: pass_rate(predictions, threshold) for threshold in THRESHOLDS}
    best_threshold = max(THRESHOLDS, key=lambda threshold: by_threshold[threshold] or 0.0)
    groups = {
        "all": predictions,
        "star": [entry for entry in predictions if entry.variant == "star"],
        "plain": [entry for entry in predictions if entry.variant == "plain"],
        "small": [entry for entry in predictions if entry.small],
    }
    return {
        "threshold": best_threshold,
        "pass_by_threshold": by_threshold,
        "pass": {name: pass_rate(group, best_threshold) for name, group in groups.items()},
        "images": len(predictions),
    }


def decay_start(cfg: dict) -> int:
    total_steps = cfg["samples"] // cfg["optim"]["batch"]
    return round(total_steps * (1 - cfg["optim"]["decay"]))


@dataclass
class Progress:
    step: int = 0
    samples: int = 0
    best: float = -1.0
    last_val: dict[str, Any] | None = None


class Trainer:
    def __init__(self, cfg: dict, resume: bool):
        self.cfg, self.optim_cfg = cfg, cfg["optim"]
        self.device = torch.device("cuda")
        self.total_steps = cfg["samples"] // self.optim_cfg["batch"]
        self.decay_start = decay_start(cfg)
        self.run_dir = DATA / "runs" / cfg["name"]
        checkpoint = self.checkpoint(resume)
        self.log_file = open(self.run_dir / "log.jsonl", "a", buffering=1)

        self.train_loader, self.val_loader = self.loaders(checkpoint["step"] if checkpoint else 0)
        model = build(cfg["model"], pretrained=checkpoint is None)
        self.model = model.to(self.device).to(memory_format=torch.channels_last)  # pyright: ignore[reportCallIssue]
        self.ema = copy.deepcopy(self.model).eval().requires_grad_(False)
        self.optimizer, self.base_lrs, self.optimizer_names = self.make_optimizer()

        self.progress = Progress()
        if checkpoint is None:
            self.log({"event": "start", "config": cfg, "total_steps": self.total_steps, "passes": self.passes})
        else:
            self.restore(checkpoint)

        self.compiled = torch.compile(self.model)
        self.ema_params, self.model_params = list(self.ema.parameters()), list(self.model.parameters())
        self.ema_buffers, self.model_buffers = list(self.ema.buffers()), list(self.model.buffers())

    def checkpoint(self, resume: bool) -> dict | None:
        if not resume:
            if (self.run_dir / "log.jsonl").exists():
                raise SystemExit(f"{self.run_dir} already has a run! pass --resume or choose another name")
            self.run_dir.mkdir(parents=True, exist_ok=True)
            return None
        checkpoint = checkpoints.load(self.run_dir / "last.safetensors")
        before = checkpoint["config"]
        if {**before, "name": None, "samples": None} != {**self.cfg, "name": None, "samples": None}:
            raise SystemExit("this checkpoint was created under a different config")
        if before["samples"] != self.cfg["samples"] and checkpoint["step"] > min(decay_start(before), self.decay_start):
            raise SystemExit("you cannot resume under a new length with a checkpoint that is past the decay start!")
        return checkpoint

    def loaders(self, skip_batches: int) -> tuple[DataLoader, DataLoader]:
        data_cfg, batch = self.cfg["data"], self.optim_cfg["batch"]
        pools = [(RENDERED / pool["set"], pool["frac"]) for pool in data_cfg["pools"]]
        with open(SPLIT / f"{data_cfg['train']}.txt") as lines:
            stream_items = sum(1 for _ in lines)
        self.passes = self.total_steps * batch * (1 - sum(frac for _, frac in pools)) / stream_items

        train_set = TrainStream(
            RENDERED / data_cfg["train"],
            pools,
            self.cfg["seed"],
            batch,
            skip_batches,
            tuple(self.cfg["model"]["sym_depths"]),
        )
        train_loader = DataLoader(
            train_set,
            batch_size=batch,
            num_workers=data_cfg["workers"],
            collate_fn=collate,
            pin_memory=True,
            prefetch_factor=4,
            drop_last=True,
        )
        val_loader = DataLoader(
            EvalStream(RENDERED / data_cfg["val"]),
            batch_size=16,
            num_workers=min(2, data_cfg["workers"]),
            collate_fn=collate,
            pin_memory=True,
        )
        return train_loader, val_loader

    def make_optimizer(self) -> tuple[torch.optim.Optimizer, list[float], list[str]]:
        lr = self.optim_cfg["lr"]
        base_lrs = [lr * self.optim_cfg["backbone_lr_mult"], lr]
        named = list(self.model.named_parameters())
        groups = [
            [(name, parameter) for name, parameter in named if name.startswith("backbone.") == in_backbone]
            for in_backbone in (True, False)
        ]
        optimizer = torch.optim.AdamW(
            [
                {"params": [parameter for _, parameter in group], "lr": base_lr}
                for group, base_lr in zip(groups, base_lrs)
            ],
            weight_decay=self.optim_cfg["weight_decay"],
        )
        return optimizer, base_lrs, [name for group in groups for name, _ in group]

    def restore(self, checkpoint: dict) -> None:
        self.model.load_state_dict(checkpoint["model"])
        self.ema.load_state_dict(checkpoint["ema"])
        index = {name: position for position, name in enumerate(self.optimizer_names)}
        state: dict[int, dict] = {}
        for key, value in checkpoint["opt"].items():
            field, name = key.split(".", 1)
            state.setdefault(index[name], {})[field] = value
        self.optimizer.load_state_dict(self.optimizer.state_dict() | {"state": state})
        self.progress = Progress(checkpoint["step"], checkpoint["samples"], checkpoint["best"], checkpoint["val"])
        self.log(
            {
                "event": "resume",
                "checkpoint": str(self.run_dir / "last.safetensors"),
                "step": self.progress.step,
                "samples": self.progress.samples,
                "total_steps": self.total_steps,
            }
        )

    def log(self, record: dict) -> None:
        self.log_file.write(json.dumps({**record, "time": time.time()}) + "\n")

    def lr_scale(self, step: int) -> float:
        warmup = self.optim_cfg["warmup"]
        if step < warmup:
            return (step + 1) / warmup
        if step < self.decay_start:
            return 1.0
        return max(0.0, (self.total_steps - step) / max(1, self.total_steps - self.decay_start))

    def save(self, name: str) -> None:
        progress = self.progress
        state = self.optimizer.state_dict()["state"]
        checkpoints.save(
            self.run_dir / name,
            {
                "model": self.model.state_dict(),
                "ema": self.ema.state_dict(),
                "opt": {
                    f"{field}.{self.optimizer_names[index]}": value
                    for index, fields in state.items()
                    for field, value in fields.items()
                },
                "config": self.cfg,
                "step": progress.step,
                "samples": progress.samples,
                "best": progress.best,
                "val": progress.last_val,
            },
        )

    def evaluate(self) -> None:
        progress = self.progress
        started = time.time()
        progress.last_val = validate(self.ema, self.val_loader, self.device) | {"samples": progress.samples}
        self.log({"event": "val", "step": progress.step, "seconds": time.time() - started, **progress.last_val})
        print(json.dumps({key: progress.last_val[key] for key in ("samples", "threshold", "pass")}), flush=True)
        if progress.last_val["pass"]["small"] > progress.best:
            progress.best = progress.last_val["pass"]["small"]
            self.save("best.safetensors")
        self.save("last.safetensors")

    def train_step(self, batch: dict) -> torch.Tensor:
        scale = self.lr_scale(self.progress.step)
        for group, base_lr in zip(self.optimizer.param_groups, self.base_lrs):
            group["lr"] = base_lr * scale
        images = batch["image"].to(self.device, non_blocking=True).to(memory_format=torch.channels_last)
        targets = {name: batch[name].to(self.device, non_blocking=True) for name in TARGET_KEYS}
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = self.compiled(images)

        losses = {
            "heat": focal_loss(out["heat"], targets["heat"], targets["weight"]),
            "off": offset_loss(out["offset"], targets["off_idx"], targets["off"]),
            "star": focal_loss(out["star"], targets["star"]),
            "amb": focal_loss(out["amb"], targets["amb"]),
            "sym": symmetry_loss(out["sym"], targets["sym_idx"], targets["sym_img"], targets["sym_cls"]),
        }
        weights = {"heat": 1.0, "off": 1.0} | self.cfg["loss"]
        loss = sum(weights[name] * value for name, value in losses.items())

        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()  # pyright: ignore[reportAttributeAccessIssue]
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        self.update_ema()
        return torch.stack([loss, *losses.values()]).detach().float()  # pyright: ignore[reportArgumentType]

    @torch.no_grad()
    def update_ema(self) -> None:
        step = self.progress.step
        decay = min(self.optim_cfg["ema"], (1 + step) / (10 + step))
        torch._foreach_lerp_(  # pyright: ignore[reportCallIssue, reportPrivateImportUsage]
            self.ema_params, self.model_params, 1 - decay  # pyright: ignore[reportArgumentType]
        )
        if self.ema_buffers:
            torch._foreach_copy_(self.ema_buffers, self.model_buffers)  # pyright: ignore[reportPrivateImportUsage]

    def log_window(self, loss_sums: torch.Tensor, loss_count: int, window_start: float, window_samples: int) -> None:
        progress = self.progress
        record = {
            "event": "train",
            "step": progress.step,
            "samples": progress.samples,
            **dict(zip(LOSS_NAMES, (loss_sums / loss_count).tolist())),
            "lr": self.optimizer.param_groups[1]["lr"],
            "img_per_s": (progress.samples - window_samples) / (time.time() - window_start),
        }
        self.log(record)
        print(json.dumps(record), flush=True)

    def run(self) -> None:
        progress, eval_every = self.progress, self.cfg["eval_every"]
        next_eval = (progress.samples // eval_every + 1) * eval_every
        # summed on the GPU and read back only when logging, so that steps won't be blocking
        loss_sums, loss_count = torch.zeros(len(LOSS_NAMES), device=self.device), 0
        window_start, window_samples = time.time(), progress.samples

        for batch in self.train_loader:
            if progress.step >= self.total_steps:
                break
            loss_sums += self.train_step(batch)
            loss_count += 1
            progress.step += 1
            progress.samples += self.optim_cfg["batch"]

            if progress.step == self.decay_start:
                # a longer run can continue from here, a checkpoint right before the decay start
                self.save(f"stable-{progress.samples}.safetensors")
                self.log({"event": "stable", "step": progress.step, "samples": progress.samples})

            if progress.step % LOG_EVERY == 0:
                self.log_window(loss_sums, loss_count, window_start, window_samples)
                window_start, window_samples = time.time(), progress.samples
                loss_sums.zero_()
                loss_count = 0

            if progress.samples >= next_eval or progress.step >= self.total_steps:
                next_eval += eval_every
                self.evaluate()
                window_start, window_samples = time.time(), progress.samples

        self.log({"event": "end", "best_small": progress.best, "step": progress.step, "samples": progress.samples})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--resume", action="store_true", help="continue the run from its last.safetensors")
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())

    # Triton 3.10+ will turn FP fusion off by default
    os.environ.setdefault("TRITON_DEFAULT_FP_FUSION", "1")
    torch.manual_seed(cfg["seed"])
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    Trainer(cfg, args.resume).run()


if __name__ == "__main__":
    main()
