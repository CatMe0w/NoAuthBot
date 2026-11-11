import argparse
import io
import json
import math
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader

from noauthbot import checkpoint as checkpoints
from noauthbot.data.dataset import EvalStream, collate, iter_shard, jpeg_roundtrip, shard_files
from noauthbot.data.split import PRODUCTION_LAST_CID, is_small
from noauthbot.decode import AMBIGUOUS_MATCH, Grid, Peak, ambiguous_cells, answer, as_peaks, distance, is_star_variant
from noauthbot.model import build
from noauthbot.paths import RENDERED
from noauthbot.peaks import cell_of, cells, peaks

AMBIGUITY_SET = "val_amb"
TOP = 10
CONFIDENCE = 0.95
GROUPS = {
    "all": lambda label: True,
    "star": lambda label: label["variant"] == "star",
    "plain": lambda label: label["variant"] == "plain",
    "small": is_small,
    "production": lambda label: label["cid"] <= PRODUCTION_LAST_CID,
    "production star": lambda label: label["cid"] <= PRODUCTION_LAST_CID and label["variant"] == "star",
    "production plain": lambda label: label["cid"] <= PRODUCTION_LAST_CID and label["variant"] == "plain",
}
VERDICTS = ("normal", "pseudo_unsolvable", "true_unsolvable", "unsure", "lost")  # the order the counts are listed in
REFUSALS = {"none": set(), "lost": {"lost"}, "app": {"unsure", "lost"}}
ANSWERS = {
    "threshold": lambda entry: entry["thresholded"],
    "top1": lambda entry: entry["first"],
    "top1_hinted": lambda entry: entry["hinted_rank"] == 1,
    f"top{TOP}": lambda entry: entry["rank"] is not None,
    f"top{TOP}_hinted": lambda entry: entry["hinted_rank"] is not None,
}
TABLE_COLUMNS = ("cid", "inchikey", "variant", "seed", "heavy_atoms", "cells", "rank", "hinted_rank", "verdict")


@torch.no_grad()
def predict(checkpoint: dict, sets: tuple[str, ...]) -> list[dict]:
    model = build(checkpoint["config"]["model"])
    model.load_state_dict(checkpoint["ema"])
    model = model.cuda().eval().to(memory_format=torch.channels_last)

    def batch_records(name: str, batch: dict) -> list[dict]:
        images = batch["image"].cuda(non_blocking=True).to(memory_format=torch.channels_last)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = model(images)
        sizes = batch["width"], batch["height"]
        heat, offset, star, amb = (out[name].float().cpu().numpy() for name in ("heat", "offset", "star", "amb"))
        found = zip(
            batch["key"],
            batch["label"],
            peaks(heat, offset, *sizes),
            peaks(star, None, *sizes),
            peaks(amb, offset, *sizes),
        )
        return [
            {
                "set": name,
                "key": key,
                "label": label,
                "heat": centres.tolist(),
                "star": stars.tolist(),
                "amb": atoms.tolist(),
            }
            for key, label, centres, stars, atoms in found
        ]

    return [
        record
        for name in sets
        for batch in DataLoader(EvalStream(RENDERED / name), batch_size=16, num_workers=2, collate_fn=collate)
        for record in batch_records(name, batch)
    ]


onnx_model = None


def start_onnx_worker(path: Path) -> None:
    from noauthbot.runtime import Model

    global onnx_model
    onnx_model = Model(path, threads=1)


def shard_records(job: tuple[str, Path]) -> list[dict]:
    name, shard = job
    records = []
    for key, png, label in iter_shard(shard):
        found = onnx_model(jpeg_roundtrip(Image.open(io.BytesIO(png)).convert("L")))  # type: ignore
        channels = dict(zip(("heat", "star", "amb"), (rows.tolist() for rows in found)))
        records.append({"set": name, "key": key, "label": label} | channels)
    return records


def predict_onnx(path: Path, sets: tuple[str, ...], workers: int) -> list[dict]:
    jobs = [(name, shard) for name in sets for shard in shard_files(RENDERED / name)]
    with ProcessPoolExecutor(workers, initializer=start_onnx_worker, initargs=(path,)) as pool:
        return [record for part in pool.map(shard_records, jobs) for record in part]


def load_or_predict(model_path: Path, predict_sets: Callable, sets: tuple[str, ...]) -> list[dict]:
    cache = model_path.with_name(model_path.stem + "_peaks.jsonl")
    fresh = cache.exists() and cache.stat().st_mtime > model_path.stat().st_mtime
    records = [json.loads(line) for line in open(cache)] if fresh else []
    missing = tuple(name for name in sets if name not in {record["set"] for record in records})
    if missing:
        predicted = predict_sets(missing)
        with open(cache, "a" if fresh else "w") as out:
            out.writelines(json.dumps(record) + "\n" for record in predicted)
        records += predicted
    return [record for record in records if record["set"] in sets]


def rows(values: list) -> np.ndarray:
    return np.asarray(values, np.float32).reshape(-1, 3)


def ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def rank_of(truth: list[str], candidates: list[list[str]]) -> int | None:
    return candidates.index(truth) + 1 if truth in candidates else None


def outcome(record: dict, threshold: float) -> dict:
    label = record["label"]
    truth = sorted(label["answer_cells"])
    channels = rows(record["heat"]), rows(record["star"]), rows(record["amb"]), label["width"], label["height"]
    result = answer(*channels, threshold, max_candidates=TOP)
    hinted = answer(*channels, threshold, max_candidates=TOP, hint=len(truth))
    return {
        "label": label,
        "key": record["key"],
        "verdict": result.verdict.name,
        "thresholded": cells(rows(record["heat"]), label["width"], label["height"], threshold) == truth,
        "first": result.cells == truth,
        "rank": rank_of(truth, result.candidates),
        "hinted_rank": rank_of(truth, hinted.candidates),
    }


def binomial_cdf(k: int, n: int, p: float) -> float:
    log_p, log_q = math.log(p), math.log1p(-p)
    return sum(
        math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * log_p + (n - i) * log_q)
        for i in range(k + 1)
    )


# one-sided Clopper-Pearson upper bound on a miss rate
def upper(misses: int, n: int) -> float:
    if misses >= n:
        return 1.0
    low, high = misses / n, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        low, high = (middle, high) if binomial_cdf(misses, n, middle) > 1 - CONFIDENCE else (low, middle)
    return high


def matrix_cell(group: list[dict], refused: set[str], correct) -> dict:
    answered = [entry for entry in group if entry["verdict"] not in refused]
    misses = sum(not correct(entry) for entry in answered)
    missed_or_refused = misses + len(group) - len(answered)
    return {
        "answered": len(answered),
        "misses": misses,
        "miss_rate": misses / len(answered) if answered else None,
        "miss_upper_95": upper(misses, len(answered)) if answered else None,
        "miss_or_refused_rate": missed_or_refused / len(group),
        "miss_or_refused_upper_95": upper(missed_or_refused, len(group)),
    }


def matrix(outcomes: list[dict]) -> dict:
    result = {}
    for name, member in GROUPS.items():
        group = [entry for entry in outcomes if member(entry["label"])]
        if group:
            result[name] = {
                "images": len(group),
                "verdicts": dict(Counter(entry["verdict"] for entry in group)),
                "matrix": {
                    refusal: {answer: matrix_cell(group, refused, correct) for answer, correct in ANSWERS.items()}
                    for refusal, refused in REFUSALS.items()
                },
            }
    return result


def missed_keys(outcomes: list[dict]) -> dict:
    return {
        f"{refusal} / {answer}": [
            entry["key"] for entry in outcomes if entry["verdict"] not in refused and not ANSWERS[answer](entry)
        ]
        for refusal, refused in REFUSALS.items()
        for answer in (f"top{TOP}", f"top{TOP}_hinted")
    }


def percent(rate: float | None) -> str:
    return "-" if rate is None else f"{100 * rate:.4f}%"


def cell_text(cell: dict) -> str:
    return f"{cell['misses']:,}/{cell['answered']:,} ({percent(cell['miss_rate'])}, <={percent(cell['miss_upper_95'])})"


def matrix_text(groups: dict) -> str:
    width = 37
    lines = [
        "Legend:",
        "each cell: misses / answered (miss rate, one-sided 95% upper bound)",
        'rows: none = nothing is refused | lost = verdict "lost" is refused | '
        'app = verdicts "unsure" and "lost" are refused (app UI/UX)',
        "columns: threshold = the cells over the threshold | top1 = decode's first answer | "
        f"top{TOP} = among the first {TOP} candidates | _hinted = given the number of cells",
        "",
    ]
    for name, group in groups.items():
        counts = group["verdicts"]
        verdicts = ", ".join(f"{verdict} {counts[verdict]:,}" for verdict in VERDICTS if verdict in counts)
        lines.append(f"{name}: {group['images']:,} images ({verdicts})")
        lines.append(" " * 8 + "".join(f"{answer:>{width}}" for answer in ANSWERS))
        for refusal, row in group["matrix"].items():
            lines.append(f"  {refusal:<6}" + "".join(f"{cell_text(cell):>{width}}" for cell in row.values()))
        lines.append("")
    return "\n".join(lines)


def table_row(entry: dict) -> str:
    label = entry["label"]
    values = (
        label["cid"],
        label["pubchem"]["iupac_inchikey"],
        label["variant"],
        label["seed"],
        sum(element != "H" for element in label["atoms"]["element"]),
        len(label["answer_cells"]),
        entry["rank"] or "",
        entry["hinted_rank"] or "",
        entry["verdict"],
    )
    return "\t".join(map(str, values)) + "\n"


def atom_cell(label: dict, atom: int) -> str:
    return cell_of(label["atoms"]["x"][atom], label["atoms"]["y"][atom], label["width"], label["height"])


def deciding_cells(label: dict) -> set[str]:
    def alone(atom: int) -> bool:
        return atom_cell(label, atom) not in {
            atom_cell(label, other) for other in label["chiral_atoms"] if other != atom
        }

    return {atom_cell(label, atom) for atom, _ in label["chiral_ambiguous"] if alone(atom)}


def matched_atoms(found: list[Peak], truth: list[Peak]) -> int:
    used: set[int] = set()
    for atom in found:
        nearest = min(range(len(truth)), key=lambda index: distance(atom, truth[index]), default=None)
        if nearest is not None and nearest not in used and distance(atom, truth[nearest]) <= AMBIGUOUS_MATCH:
            used.add(nearest)
    return len(used)


def ambiguity_counts(record: dict, threshold: float, min_score: float) -> Counter:
    label = record["label"]
    centres, stars, atoms = (as_peaks(rows(record[channel])) for channel in ("heat", "star", "amb"))
    in_ambiguity_set = record["set"] == AMBIGUITY_SET
    counts: Counter = Counter()
    if in_ambiguity_set:
        truth = [
            Peak(1.0, label["atoms"]["x"][atom], label["atoms"]["y"][atom]) for atom, _ in label["chiral_ambiguous"]
        ]
        found = [atom for atom in atoms if atom.score >= min_score]
        counts.update(atoms_found=len(found), atoms_true=len(truth), atoms_matched=matched_atoms(found, truth))
    if label["variant"] != "plain":
        return counts

    grid = Grid(label["width"], label["height"])
    flagged = bool(ambiguous_cells(centres, atoms, grid, threshold, is_star_variant(stars), min_score))
    decides = bool(deciding_cells(label))
    if in_ambiguity_set and decides:
        counts.update(deciding_images=1, deciding_flagged=flagged)
    elif not in_ambiguity_set and not decides:
        counts.update(plain_images=1, plain_flagged=flagged)
    return counts


def ambiguity_metrics(records: list[dict], threshold: float, min_score: float) -> dict:
    counts = sum((ambiguity_counts(record, threshold, min_score) for record in records), Counter())
    return {
        "atom_precision": ratio(counts["atoms_matched"], counts["atoms_found"]),
        "atom_recall": ratio(counts["atoms_matched"], counts["atoms_true"]),
        "image_recall": ratio(counts["deciding_flagged"], counts["deciding_images"]),
        "false_alarm": ratio(counts["plain_flagged"], counts["plain_images"]),
        "deciding_images": counts["deciding_images"],
        "plain_images": counts["plain_images"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path, help="a checkpoint (.safetensors, GPU) or an exported model (.onnx, CPU)")
    parser.add_argument("--set", default="val_sub", choices=["val_sub", "val", "test"])
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--amb-min", type=float, nargs="*", default=[0.3, 0.4, 0.5], help="none: skip val_amb")
    parser.add_argument("--workers", type=int, default=12, help="onnxruntime processes")
    args = parser.parse_args()

    if args.model.suffix == ".onnx":
        from noauthbot.runtime import THRESHOLD

        default_threshold = THRESHOLD
        predict_sets = lambda sets: predict_onnx(args.model, sets, args.workers)
    else:
        checkpoint = checkpoints.load(args.model)
        default_threshold = float(checkpoint["val"]["threshold"])
        predict_sets = lambda sets: predict(checkpoint, sets)
    threshold = args.threshold if args.threshold is not None else default_threshold
    sets = (args.set, AMBIGUITY_SET) if args.amb_min else (args.set,)
    records = load_or_predict(args.model, predict_sets, sets)
    outcomes = [outcome(record, threshold) for record in records if record["set"] == args.set]
    result = {
        "set": args.set,
        "threshold": threshold,
        "groups": matrix(outcomes),
        "missed_keys": missed_keys(outcomes),
        "ambiguity": {str(min_score): ambiguity_metrics(records, threshold, min_score) for min_score in args.amb_min},
    }
    output = args.model.with_name(f"{args.model.stem}_eval_{args.set}")
    output.with_suffix(".json").write_text(json.dumps(result, indent=1))
    ordered = sorted(outcomes, key=lambda entry: (entry["label"]["cid"], entry["key"]))
    output.with_suffix(".tsv").write_text("\t".join(TABLE_COLUMNS) + "\n" + "".join(map(table_row, ordered)))
    text = matrix_text(result["groups"])
    if result["ambiguity"]:
        text += "\nambiguity (by minimum atom score):\n" + json.dumps(result["ambiguity"], indent=1) + "\n"
    output.with_suffix(".txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
