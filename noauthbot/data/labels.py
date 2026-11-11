import gzip
from collections.abc import Iterator
from pathlib import Path

import orjson

SUFFIX = ".labels.jsonl.gz"


def label_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*" + SUFFIX))


def stem(path: Path) -> str:
    return path.name.removesuffix(SUFFIX)


def iter_labels(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rb") as f:
        for line in f:
            yield orjson.loads(line)


def skeleton(inchikey: str) -> str:
    return inchikey.split("-")[0]
