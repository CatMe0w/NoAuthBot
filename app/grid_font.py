import numpy as np

# The technique: the molecule's font size is read from the grid labels. A label on a gray cell is white, and the
# molecule's black strokes can only darken a pixel, so every pixel brighter than the cell belongs to the label.

GRAY, WHITE = 224, 255
SLOPE, OFFSET = 0.7026, 0.835  # label height = SLOPE * font size + OFFSET, fitted on val images after JPEG
CAP_TOLERANCE = 1.0  # px; a size this close to half the cell may be the cap


def label_height(region: np.ndarray) -> float | None:
    # per row, how far the brightest pixel goes from the cell's gray towards white
    level = np.clip((region.max(axis=1) - GRAY) / (WHITE - GRAY), 0, 1)
    rows = np.nonzero(level > 0.5)[0]
    if len(rows) < 2:
        return None
    runs = np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1)
    first, last = max(((run[0], run[-1]) for run in runs), key=lambda run: run[1] - run[0])
    # sub-pixel height: the rows just outside the run are partly covered by the label
    edge = (level[first - 1] if first > 0 else 0.0) + (level[last + 1] if last + 1 < len(level) else 0.0)
    return float(last - first + 1 + edge)


def font_size(gray: np.ndarray) -> float | None:
    height, width = gray.shape
    unit_x, unit_y = width / 5, height / 3
    heights = []
    for column in range(5):
        for row in range(3):
            if (column + row) % 2 == 0:
                continue  # skip white cell gray label, as they are not separable from the strokes' antialiased edges
            top, left = int(np.ceil(row * unit_y)) + 1, int(np.ceil(column * unit_x)) + 1
            region = gray[top : int((row + 0.5) * unit_y), left : int((column + 0.7) * unit_x)].astype(np.float32)
            if region.size and (found := label_height(region)) is not None:
                heights.append(found)
    if not heights:
        return None
    size = (float(np.median(heights)) - OFFSET) / SLOPE
    return None if size > min(unit_x, unit_y) / 2 - CAP_TOLERANCE else size
