import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from noauthbot.data.labels import iter_labels, label_files, skeleton, stem
from noauthbot.paths import LABELS, SPLIT

USES = {"train": (0, 960), "val": (960, 970), "test": (970, 1000)}
PRODUCTION_FILE = "Compound_000000001_000500000"  # production draws from this one file only, as of 2026-11
PRODUCTION_LAST_CID = int(PRODUCTION_FILE.rsplit("_", 1)[1])
VAL_SUB_SIZE = 20_000
TRAIN_SIZE = 7_200_000
LARGE_MOLECULE = 100
LARGE_WEIGHT = 0.25
VAL_AMB_RENDERS = 3
STATS_COLUMNS = ("file", "labelled", "rule_pass", "rule_fail", "no_inchikey", "intractable", "max_cid")


def is_small(label: dict) -> bool:
    return sum(element != "H" for element in label["atoms"]["element"]) <= LARGE_MOLECULE


def digest(skel: str) -> int:
    return int.from_bytes(hashlib.sha256(skel.encode()).digest(), "big")


def use_of(skel: str) -> str:
    bucket = digest(skel) % 1000
    return next(use for use, (low, high) in USES.items() if low <= bucket < high)


def sampling_key(skel: str, large: set[str]) -> float:
    # weighted sampling without replacement (Efraimidis-Spirakis): keep the largest log(u) / weight. u must be
    # uniform among train's skeletons, which were chosen by digest mod 1000, so u comes from the digest's high bits
    uniform = ((digest(skel) >> 64) + 0.5) / 2**192
    return math.log(uniform) / (LARGE_WEIGHT if skel in large else 1.0)


@dataclass
class FileStats:
    file: str
    rule_pass: int = 0
    rule_fail: int = 0
    no_inchikey: int = 0
    intractable: int = 0
    max_cid: int = 0

    @property
    def labelled(self) -> int:
        return self.rule_pass + self.rule_fail + self.no_inchikey

    def row(self) -> str:
        return "\t".join(str(getattr(self, column)) for column in STATS_COLUMNS)


@dataclass
class Findings:
    candidates: list[tuple[int, str]] = field(default_factory=list)
    ambiguous: set[int] = field(default_factory=set)
    production: list[tuple[int, str]] = field(default_factory=list)
    production_skeletons: set[str] = field(default_factory=set)
    large: set[str] = field(default_factory=set)


def scan(path: Path) -> tuple[FileStats, Findings]:
    stats, found = FileStats(stem(path)), Findings()
    in_production = stats.file == PRODUCTION_FILE
    for label in iter_labels(path):
        stats.max_cid = max(stats.max_cid, label["cid"])
        inchikey = label["pubchem"]["iupac_inchikey"]
        if in_production and inchikey:
            found.production_skeletons.add(skeleton(inchikey))
        if not inchikey:
            stats.no_inchikey += 1
            continue
        if not label["rule_pass"]:
            stats.rule_fail += 1
            continue

        stats.rule_pass += 1
        candidate = (label["cid"], skeleton(inchikey))
        found.candidates.append(candidate)
        if not is_small(label):
            found.large.add(candidate[1])
        if in_production:
            found.production.append(candidate)
        if label["chiral_ambiguous"]:
            found.ambiguous.add(label["cid"])

    intractable_list = path.with_name(stem(path) + ".intractable.tsv")
    intractable = [int(line.split("\t", 1)[0]) for line in intractable_list.read_text().splitlines() if line.strip()]
    stats.intractable = len(intractable)
    stats.max_cid = max([stats.max_cid, *intractable])
    return stats, found


@dataclass
class Merged:
    lowest_cid: dict[str, int] = field(default_factory=dict)
    found: Findings = field(default_factory=Findings)

    def add(self, found: Findings) -> None:
        for cid, skel in found.candidates:
            if cid < self.lowest_cid.get(skel, 1 << 62):
                self.lowest_cid[skel] = cid
        self.found.ambiguous |= found.ambiguous
        self.found.production += found.production
        self.found.production_skeletons |= found.production_skeletons
        self.found.large |= found.large


def by_use(merged: Merged) -> dict[str, list[tuple[int, str]]]:
    split: dict[str, list[tuple[int, str]]] = {use: [] for use in USES}
    for skel, cid in merged.lowest_cid.items():
        if skel not in merged.found.production_skeletons:
            split[use_of(skel)].append((cid, skel))
    split["test"] += merged.found.production
    return split


def write_cids(path: Path, cids) -> None:
    path.write_text("".join(f"{cid}\n" for cid in sorted(cids)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--procs", type=int, default=12)
    args = parser.parse_args()

    merged, files = Merged(), []
    with ProcessPoolExecutor(args.procs) as pool:
        for stats, found in pool.map(scan, label_files(LABELS)):
            merged.add(found)
            files.append(stats)
            print(f"{stats.file} {stats.rule_pass}", flush=True)

    split = by_use(merged)
    large, ambiguous = merged.found.large, merged.found.ambiguous
    train_buckets = len(split["train"])
    split["train"] = sorted(split["train"], key=lambda entry: sampling_key(entry[1], large), reverse=True)[:TRAIN_SIZE]
    val_sub = sorted(split["val"], key=lambda entry: digest(entry[1]))[:VAL_SUB_SIZE]
    train_amb = [cid for cid, _ in split["train"] if cid in ambiguous]
    val_amb = sorted(cid for cid, _ in split["val"] if cid in ambiguous)

    SPLIT.mkdir(parents=True, exist_ok=True)
    for use, entries in split.items():
        if use != "test":
            write_cids(SPLIT / f"{use}.txt", (cid for cid, _ in entries))
    # a production group fixes its variant and rendering is random only in where the star goes, so each production
    # CID is rendered in both variants: test then holds every image production can show
    production = {cid for cid, _ in merged.found.production}
    (SPLIT / "test.txt").write_text(
        "".join(
            f"{cid} star\n{cid} plain\n" if cid in production else f"{cid}\n"
            for cid in sorted(cid for cid, _ in split["test"])
        )
    )
    write_cids(SPLIT / "val_sub.txt", (cid for cid, _ in val_sub))
    write_cids(SPLIT / "train_amb.txt", train_amb)
    (SPLIT / "val_amb.txt").write_text("".join(f"{cid} plain\n" for cid in val_amb for _ in range(VAL_AMB_RENDERS)))

    cutoff = max(stats.max_cid for stats in files)
    lines = [f"# cutoff_cid {cutoff}", "\t".join(STATS_COLUMNS), *(stats.row() for stats in files)]
    (SPLIT / "file_stats.tsv").write_text("\n".join(lines) + "\n")
    summary = {
        "cutoff_cid": cutoff,
        "files": len(files),
        "rule_pass": sum(stats.rule_pass for stats in files),
        "no_inchikey": sum(stats.no_inchikey for stats in files),
        "skeletons": len(merged.lowest_cid),
        "counts": {use: len(entries) for use, entries in split.items()}
        | {"val_sub": len(val_sub), "train_amb": len(train_amb), "val_amb": len(val_amb)},
        "train_buckets": train_buckets,
        "train_large": sum(skel in large for _, skel in split["train"]),
        "test_production": len(merged.found.production),
        "production_skeletons": len(merged.found.production_skeletons),
    }
    (SPLIT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
