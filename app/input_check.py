from pathlib import Path

import numpy as np
from PIL import Image

MIN_LONG, MAX_LONG = 725, 810
GRID_TOLERANCE = 1.5  # px, checkerboard edge vs i * W / 5
CHROMA_MAX = 6.0  # 99.9th percentile of |Cb - 128| + |Cr - 128|
TELEGRAM_TABLE = (4, 3, 3, 4)
MIN_RUN = 4  # px


def edges(profile: np.ndarray) -> list[float]:
    white = profile > 0
    while True:
        cuts = [0] + [i + 1 for i in np.nonzero(white[1:] != white[:-1])[0]] + [len(white)]
        runs = list(zip(cuts[:-1], cuts[1:]))
        short = [k for k, (start, end) in enumerate(runs) if end - start < MIN_RUN and 0 < k < len(runs) - 1]
        if not short:
            return [float(cut) for cut in cuts[1:-1]]
        k = min(short, key=lambda k: runs[k][1] - runs[k][0])
        white[runs[k][0] : runs[k][1]] = not white[runs[k][0]]


def grid_problem(gray: np.ndarray) -> str | None:
    height, width = gray.shape
    vote = (gray > 247).astype(np.float32) - (np.abs(gray - 224) < 10)
    row_parity = np.where((np.arange(height) * 3 // height) % 2 == 0, 1.0, -1.0)
    column_parity = np.where((np.arange(width) * 5 // width) % 2 == 0, 1.0, -1.0)
    for name, profile, count, size in (
        ("column", row_parity @ vote, 5, width),
        ("row", vote @ column_parity, 3, height),
    ):
        expected = [k * size / count for k in range(1, count)]
        found = edges(profile)
        if profile[: max(1, int(size / count) - 2)].sum() <= 0:
            return f"{name} checkerboard phase"
        if len(found) != len(expected) or any(abs(x - y) > GRID_TOLERANCE for x, y in zip(found, expected)):
            return f"{name} checkerboard edges {[round(x, 1) for x in found]} != {[round(y, 1) for y in expected]}"
    return None


def check(path: Path | str) -> dict:
    image = Image.open(path)
    problems, notes = [], []
    width, height = image.size
    if not MIN_LONG <= max(width, height) <= MAX_LONG:
        problems.append(f"size {width}x{height}: the long side of an original is {MIN_LONG}..{MAX_LONG} px")
    if image.mode not in ("L", "1"):
        ycc = np.asarray(image.convert("YCbCr"), dtype=np.float32)
        chroma = np.percentile(np.abs(ycc[..., 1] - 128) + np.abs(ycc[..., 2] - 128), 99.9)
        if chroma > CHROMA_MAX:
            problems.append(f"colour content (chroma {chroma:.1f})")
    problem = grid_problem(np.asarray(image.convert("L"), dtype=np.float32))
    if problem:
        problems.append(f"{problem}: cropped or bordered")
    if image.format == "JPEG":
        progressive = bool(image.info.get("progressive") or image.info.get("progression"))
        table = tuple(getattr(image, "quantization", {}).get(0, [])[:4])
        if not progressive or table != TELEGRAM_TABLE:
            notes.append(f"JPEG not as Telegram sends it (progressive={progressive}, table {table})")
    return {"original": not problems, "problems": problems, "notes": notes}
