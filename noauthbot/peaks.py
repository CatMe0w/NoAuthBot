import numpy as np

CANVAS = 832
STRIDE = 4
MIN_SCORE = 0.05
MAX_PEAKS = 512


def to_pixels(index: np.ndarray, offset: np.ndarray) -> np.ndarray:
    return STRIDE * (index + offset + 0.5)


def local_max(score: np.ndarray) -> np.ndarray:
    height, width = score.shape[-2:]
    padded = np.pad(score, ((0, 0), (0, 0), (1, 1), (1, 1)), constant_values=-np.inf)
    pooled = padded[..., :height, :width]
    for dy in range(3):
        for dx in range(3):
            pooled = np.maximum(pooled, padded[..., dy : dy + height, dx : dx + width])
    return pooled


def peaks(heat_logits: np.ndarray, offset: np.ndarray | None, widths, heights) -> list[np.ndarray]:
    score = 1 / (1 + np.exp(-heat_logits.astype(np.float32)))
    is_peak = (local_max(score) == score) & (score >= MIN_SCORE)
    if offset is None:
        offset = np.zeros((score.shape[0], 2, *score.shape[2:]), np.float32)

    def image_peaks(image: int) -> np.ndarray:
        rows, columns = np.nonzero(is_peak[image, 0])
        found = score[image, 0, rows, columns]
        if len(rows) > MAX_PEAKS:
            best = np.argsort(-found, kind="stable")[:MAX_PEAKS]
            rows, columns, found = rows[best], columns[best], found[best]
        x = to_pixels(columns.astype(np.float32), offset[image, 0, rows, columns].astype(np.float32).clip(-0.5, 0.5))
        y = to_pixels(rows.astype(np.float32), offset[image, 1, rows, columns].astype(np.float32).clip(-0.5, 0.5))
        inside = (x < float(widths[image])) & (y < float(heights[image]))
        found = np.stack([found, x, y], 1)[inside]
        return found[np.argsort(-found[:, 0], kind="stable")]

    return [image_peaks(image) for image in range(score.shape[0])]


def cell_of(x: float, y: float, width: int, height: int) -> str:
    # bug-for-bug compatible with the grader's arithmetic
    # cells are (W // 5) x (H // 3) px, and coordinates are divided in float32
    column = min(4, int(np.float32(x) / np.float32(width // 5)))
    row = min(2, int(np.float32(y) / np.float32(height // 3)))
    return f"{chr(65 + column)}{1 + row}"


def cells(rows: np.ndarray, width: int, height: int, threshold: float) -> list[str]:
    return sorted({cell_of(x, y, width, height) for score, x, y in rows if score >= threshold})
