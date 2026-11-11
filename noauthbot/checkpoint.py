import json
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import load_file, save_file

PARTS = ("model", "ema", "opt")


def save(path: Path, checkpoint: dict) -> None:
    tensors = {
        f"{part}.{name}": tensor.contiguous()
        for part in PARTS
        if part in checkpoint
        for name, tensor in checkpoint[part].items()
    }
    metadata = {key: json.dumps(value) for key, value in checkpoint.items() if key not in PARTS}
    save_file(tensors, path, metadata=metadata)


def load(path: Path) -> dict:
    with safe_open(path, "pt") as file:
        checkpoint: dict = {key: json.loads(value) for key, value in file.metadata().items()}
    tensors: dict[str, torch.Tensor] = load_file(path)
    for key, tensor in tensors.items():
        part, name = key.split(".", 1)
        checkpoint.setdefault(part, {})[name] = tensor
    return checkpoint
