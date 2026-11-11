import io
import itertools
import math
import random
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import torch
import zstandard
from PIL import Image
from torch.utils.data import IterableDataset, get_worker_info

from noauthbot.data.graph import MoleculeGraph, atom_colours
from noauthbot.peaks import CANVAS, STRIDE

OUT = CANVAS // STRIDE
SIGMA = 1.0
IGNORE_RADIUS = 2
JPEG_QUALITY = 87
SHUFFLE_BUFFER = 512
SYM_MAX_ATOMS = 192

Item = tuple[str, bytes, dict]


def shard_files(directory: Path) -> list[Path]:
    return sorted([*directory.glob("*.tar"), *directory.glob("*.tar.zst")])


def iter_shard(path: Path) -> Iterator[Item]:
    with open(path, "rb") as raw:
        stream = zstandard.ZstdDecompressor().stream_reader(raw) if path.suffix == ".zst" else raw
        pending: dict[str, dict] = {}
        with tarfile.open(fileobj=stream, mode="r|") as tar:
            for member in tar:
                content = tar.extractfile(member)
                if content is None:
                    continue
                key, extension = member.name.rsplit(".", 1)
                parts = pending.setdefault(key, {})
                parts[extension] = content.read()
                if "png" in parts and "json" in parts:
                    del pending[key]
                    yield key, parts["png"], orjson.loads(parts["json"])


def jpeg_roundtrip(gray: Image.Image) -> Image.Image:
    buffer = io.BytesIO()
    gray.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, subsampling=2, progressive=True)
    buffer.seek(0)
    return Image.open(buffer).convert("L")


def to_input(gray: Image.Image) -> torch.Tensor:
    pixels = np.asarray(gray, dtype=np.uint8)
    canvas = np.full((CANVAS, CANVAS), 255, dtype=np.uint8)
    canvas[: pixels.shape[0], : pixels.shape[1]] = pixels
    return torch.from_numpy(canvas).float().div_(255.0).unsqueeze(0)


def to_output(position: float) -> float:
    return position / STRIDE - 0.5


def atom_output(label: dict, atom: int) -> tuple[float, float]:
    return to_output(label["atoms"]["x"][atom]), to_output(label["atoms"]["y"][atom])


def splat(target: np.ndarray, column: float, row: float) -> tuple[int, int]:
    radius = int(math.ceil(3 * SIGMA))
    grid = np.arange(OUT, dtype=np.float32)
    nearest_column, nearest_row = int(round(column)), int(round(row))
    left, right = max(0, nearest_column - radius), min(OUT, nearest_column + radius + 1)
    top, bottom = max(0, nearest_row - radius), min(OUT, nearest_row + radius + 1)

    distance = (grid[None, left:right] - column) ** 2 + (grid[top:bottom, None] - row) ** 2
    target[top:bottom, left:right] = np.maximum(target[top:bottom, left:right], np.exp(-distance / (2 * SIGMA**2)))
    if 0 <= nearest_column < OUT and 0 <= nearest_row < OUT:
        target[nearest_row, nearest_column] = 1.0
    return nearest_column, nearest_row


def targets(label: dict) -> dict[str, torch.Tensor]:
    heat, star, amb = (np.zeros((OUT, OUT), dtype=np.float32) for _ in range(3))
    weight = np.ones((OUT, OUT), dtype=np.float32)

    offset_index, offset = [], []
    for atom in label["chiral_atoms"]:
        column, row = atom_output(label, atom)
        nearest_column, nearest_row = splat(heat, column, row)
        offset_index.append(nearest_row * OUT + nearest_column)
        offset.append((column - nearest_column, row - nearest_row))

    chiral = set(label["chiral_atoms"])
    for atom, _ in label["chiral_ambiguous"]:
        column, row = atom_output(label, atom)
        splat(amb, column, row)
        # an uncounted order-dependent atom is neither a positive nor a negative
        if atom not in chiral:
            nearest_column, nearest_row = round(column), round(row)
            weight[
                max(0, nearest_row - IGNORE_RADIUS) : nearest_row + IGNORE_RADIUS + 1,
                max(0, nearest_column - IGNORE_RADIUS) : nearest_column + IGNORE_RADIUS + 1,
            ] = 0

    for drawn in label.get("stars", []):
        column, row = to_output(drawn["center_x"]), to_output(drawn["center_y"])
        if 0 <= round(column) < OUT and 0 <= round(row) < OUT:
            splat(star, column, row)

    maps = {"heat": heat, "weight": weight, "star": star, "amb": amb}
    return {name: torch.from_numpy(values).unsqueeze(0) for name, values in maps.items()} | {
        "idx": torch.tensor(offset_index, dtype=torch.long),
        "off": torch.tensor(offset, dtype=torch.float32).reshape(-1, 2),
    }


def output_pixel(label: dict, atom: int) -> int:
    column, row = (min(OUT - 1, max(0, round(position))) for position in atom_output(label, atom))
    return row * OUT + column


def symmetry_targets(label: dict, depths: tuple[int, ...]) -> dict[str, torch.Tensor]:
    atoms, colours = atom_colours(MoleculeGraph.from_label(label), depths)
    if len(atoms) > SYM_MAX_ATOMS:
        kept = np.linspace(0, len(atoms) - 1, SYM_MAX_ATOMS).round().astype(int)
        atoms, colours = [atoms[position] for position in kept], colours[kept]
    pixels = [output_pixel(label, atom) for atom in atoms]
    return {"sym_idx": torch.tensor(pixels, dtype=torch.long), "sym_cls": torch.from_numpy(colours)}


def eval_sample(item: Item) -> dict:
    key, png, label = item
    image = to_input(jpeg_roundtrip(Image.open(io.BytesIO(png)).convert("L")))
    return {"key": key, "label": label, "image": image, "width": label["width"], "height": label["height"]}


def train_sample(item: Item, sym_depths: tuple[int, ...]) -> dict:
    label = item[2]
    return eval_sample(item) | targets(label) | symmetry_targets(label, sym_depths)


def worker_slice() -> tuple[int, int]:
    info = get_worker_info()
    return (info.id, info.num_workers) if info else (0, 1)


class TrainStream(IterableDataset):
    def __init__(
        self,
        shard_dir: Path,
        pools: list[tuple[Path, float]],
        seed: int,
        batch: int,
        skip_batches: int,
        sym_depths: tuple[int, ...],
    ):
        self.shards = shard_files(shard_dir)
        self.pools = [(shard_files(directory), frac) for directory, frac in pools if frac > 0]
        if not self.shards or not all(files for files, _ in self.pools):
            raise FileNotFoundError(f"no shards in {shard_dir} or in a pool of {pools}")
        self.pool_frac = sum(frac for _, frac in self.pools)
        self.seed, self.batch, self.skip_batches, self.sym_depths = seed, batch, skip_batches, sym_depths

    def items(self, worker: int, workers: int) -> Iterator[Item]:
        pools = [
            [item for shard in files[worker::workers] or files[:1] for item in iter_shard(shard)]
            for files, _ in self.pools
        ]
        # pass n is shuffled with seed + n - 1, so the first pass is the order of a run that reads the stream once
        for seed in itertools.count(self.seed):
            yield from self.one_pass(seed, worker, workers, pools)

    def one_pass(self, seed: int, worker: int, workers: int, pools: list[list[Item]]) -> Iterator[Item]:
        shards = list(self.shards)
        random.Random(seed).shuffle(shards)
        rng = random.Random(seed * 100003 + worker)
        weights = [frac for _, frac in self.pools]

        buffer: list[Item] = []
        for shard in shards[worker::workers]:
            for item in iter_shard(shard):
                buffer.append(item)
                while pools and rng.random() < self.pool_frac:
                    pool = rng.choices(pools, weights)[0]
                    buffer.append(pool[rng.randrange(len(pool))])
                while len(buffer) >= SHUFFLE_BUFFER:
                    yield buffer.pop(rng.randrange(len(buffer)))
        rng.shuffle(buffer)
        yield from buffer

    def __iter__(self):
        worker, workers = worker_slice()
        # a new loader takes its first batch from worker 0, so after k batches
        # worker 0 continues what worker k % workers would have handed out next
        role = (worker + self.skip_batches) % workers
        handed_out = self.skip_batches // workers + (role < self.skip_batches % workers)
        for position, item in enumerate(self.items(role, workers)):
            if position >= handed_out * self.batch:
                yield train_sample(item, self.sym_depths)


class EvalStream(IterableDataset):
    def __init__(self, shard_dir: Path):
        self.shards = shard_files(shard_dir)
        if not self.shards:
            raise FileNotFoundError(f"no shards in {shard_dir}")

    def __iter__(self):
        worker, workers = worker_slice()
        for shard in self.shards[worker::workers]:
            yield from map(eval_sample, iter_shard(shard))


def collate(batch: list[dict]) -> dict[str, Any]:
    def stacked(name: str) -> torch.Tensor:
        return torch.stack([sample[name] for sample in batch])

    def indices(name: str) -> torch.Tensor:
        return torch.cat([sample[name] + position * OUT * OUT for position, sample in enumerate(batch)])

    out = {
        "key": [sample["key"] for sample in batch],
        "label": [sample["label"] for sample in batch],
        "width": torch.tensor([sample["width"] for sample in batch]),
        "height": torch.tensor([sample["height"] for sample in batch]),
        "image": stacked("image"),
    }
    if "heat" not in batch[0]:
        return out
    return (
        out
        | {name: stacked(name) for name in ("heat", "weight", "star", "amb")}
        | {
            "off_idx": indices("idx"),
            "off": torch.cat([sample["off"] for sample in batch]),
            "sym_idx": indices("sym_idx"),
            "sym_img": torch.cat(
                [torch.full_like(sample["sym_idx"], position) for position, sample in enumerate(batch)]
            ),
            "sym_cls": torch.cat([sample["sym_cls"] for sample in batch]),
        }
    )
