import math

import numpy as np
import onnxruntime as ort
from PIL import Image

from noauthbot.peaks import CANVAS, peaks

THRESHOLD = 0.5
OUTPUTS = ("heat", "offset", "star", "amb")


def fitted(size: int) -> int:
    return min(CANVAS, math.ceil(size / 32) * 32)


def to_canvas(gray: Image.Image) -> np.ndarray:
    pixels = np.asarray(gray, dtype=np.uint8)
    canvas = np.full((fitted(pixels.shape[0]), fitted(pixels.shape[1])), 255, dtype=np.uint8)
    canvas[: pixels.shape[0], : pixels.shape[1]] = pixels
    return (canvas.astype(np.float32) / 255.0)[None, None]


class Model:
    def __init__(self, path, threads: int = 1):
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])

    def __call__(self, gray: Image.Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        heat, offset, star, amb = self.session.run(list(OUTPUTS), {"image": to_canvas(gray)})
        size = [gray.width], [gray.height]
        return peaks(heat, offset, *size)[0], peaks(star, None, *size)[0], peaks(amb, offset, *size)[0]  # type: ignore
