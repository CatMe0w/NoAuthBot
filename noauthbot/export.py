import argparse
import tempfile
from pathlib import Path

import onnx
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.quantization.shape_inference import quant_pre_process

from noauthbot import checkpoint as checkpoints
from noauthbot.model import build
from noauthbot.peaks import CANVAS
from noauthbot.runtime import OUTPUTS


class Outputs(torch.nn.Module):
    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, image):
        out = self.net(image)
        return tuple(out[name] for name in OUTPUTS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    checkpoint = checkpoints.load(args.checkpoint)
    net = build(checkpoint["config"]["model"])
    net.load_state_dict(checkpoint["ema"])
    net.eval()
    axes = {"image": {2: "h", 3: "w"}, **{name: {2: "oh", 3: "ow"} for name in OUTPUTS}}
    with tempfile.TemporaryDirectory() as work:
        fp32, pre = Path(work) / "fp32.onnx", Path(work) / "pre.onnx"
        torch.onnx.export(
            Outputs(net),
            (torch.rand(1, 1, CANVAS, CANVAS),),
            str(fp32),
            input_names=["image"],
            output_names=list(OUTPUTS),
            opset_version=17,
            dynamo=False,
            dynamic_axes=axes,
        )
        onnx.checker.check_model(str(fp32))
        quant_pre_process(str(fp32), str(pre))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        quantize_dynamic(
            str(pre), str(args.out), op_types_to_quantize=["MatMul"], per_channel=True, weight_type=QuantType.QInt8
        )


if __name__ == "__main__":
    main()
