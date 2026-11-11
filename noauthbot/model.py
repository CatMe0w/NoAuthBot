import timm
import torch
import torch.nn as nn
import torch.nn.functional as F

PRIOR_BIAS = -4.6


def conv_block(in_channels: int, channels: int) -> nn.Sequential:
    # using LayerNorm over the channels of each position instead of GroupNorm: GroupNorm's statistics include the white
    # padding, so its output changes when inference crops the 832 x 832 canvas to the image
    return nn.Sequential(
        nn.Conv2d(in_channels, channels, 3, padding=1),
        timm.layers.LayerNorm2d(channels),  # pyright: ignore[reportPrivateImportUsage]
        nn.GELU(),
        nn.Conv2d(channels, channels, 3, padding=1),
        timm.layers.LayerNorm2d(channels),  # pyright: ignore[reportPrivateImportUsage]
        nn.GELU(),
    )


class FPN(nn.Module):
    def __init__(self, in_channels: list[int], channels: int):
        super().__init__()
        self.lateral = nn.ModuleList(nn.Conv2d(width, channels, 1) for width in in_channels)
        self.smooth = conv_block(channels, channels)

    def forward(self, features: list[torch.Tensor]) -> torch.Tensor:
        merged = self.lateral[-1](features[-1])
        for lateral, feature in zip(reversed(self.lateral[:-1]), reversed(features[:-1])):
            merged = F.interpolate(merged, size=feature.shape[-2:], mode="nearest") + lateral(feature)
        return self.smooth(merged)


class UNet(nn.Module):
    def __init__(self, in_channels: list[int], channels: int):
        super().__init__()
        widths = [channels, channels * 3 // 2, channels * 2][: len(in_channels) - 1]
        coarser = [in_channels[-1]] + widths[:0:-1]
        self.blocks = nn.ModuleList(
            conv_block(skip + below, width) for skip, below, width in zip(in_channels[-2::-1], coarser, widths[::-1])
        )

    def forward(self, features: list[torch.Tensor]) -> torch.Tensor:
        merged = features[-1]
        for block, feature in zip(self.blocks, reversed(features[:-1])):
            merged = block(torch.cat([F.interpolate(merged, size=feature.shape[-2:], mode="nearest"), feature], 1))
        return merged


NECKS = {"fpn": FPN, "unet": UNet}


class GradScale(torch.autograd.Function):
    @staticmethod
    def forward(ctx, features, scale):
        ctx.scale = scale
        return features.view_as(features)

    @staticmethod
    def backward(ctx, grad):  # pyright: ignore[reportIncompatibleMethodOverride]
        return grad * ctx.scale, None


def head(channels: int, out_channels: int, prior: bool) -> nn.Sequential:
    layers = nn.Sequential(nn.Conv2d(channels, channels, 3, padding=1), nn.GELU(), nn.Conv2d(channels, out_channels, 1))
    if prior:
        nn.init.constant_(layers[-1].bias, PRIOR_BIAS)  # pyright: ignore[reportArgumentType]
    return layers


class Net(nn.Module):
    def __init__(
        self,
        backbone: str,
        neck: str,
        neck_channels: int,
        amb_trunk_grad: float,
        sym_depths: int,
        sym_dim: int,
        pretrained: bool,
    ):
        super().__init__()
        self.backbone = timm.create_model(
            backbone, pretrained=pretrained, features_only=True, out_indices=(0, 1, 2, 3), in_chans=1
        )
        self.neck = NECKS[neck](
            self.backbone.feature_info.channels(),  # pyright: ignore[reportCallIssue, reportAttributeAccessIssue]
            neck_channels,
        )
        self.heat = head(neck_channels, 1, prior=True)
        self.offset = head(neck_channels, 2, prior=False)
        self.star = head(neck_channels, 1, prior=True)
        self.amb = head(neck_channels, 1, prior=True)
        self.amb_trunk_grad = amb_trunk_grad
        # training only
        self.sym = head(neck_channels, sym_depths * sym_dim, prior=False)

    def forward(self, images: torch.Tensor) -> dict[str, torch.Tensor]:
        # MambaOut returns its features channels-last
        shared = self.neck([feature.permute(0, 3, 1, 2) for feature in self.backbone(images)])
        out = {
            "heat": self.heat(shared),
            "offset": self.offset(shared),
            "star": self.star(shared),
            "amb": self.amb(GradScale.apply(shared, self.amb_trunk_grad)),
        }
        if self.training:
            out["sym"] = self.sym(shared)
        return out


def build(cfg: dict, pretrained: bool = False) -> Net:
    return Net(
        cfg["backbone"],
        cfg["neck"],
        cfg["neck_channels"],
        cfg["amb_trunk_grad"],
        len(cfg["sym_depths"]),
        cfg["sym_dim"],
        pretrained,
    )
