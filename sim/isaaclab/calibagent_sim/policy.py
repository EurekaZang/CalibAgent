"""Pure-Torch loader for published RSL-RL actor weights."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

import torch


def load_actor(path: Path, device: str) -> torch.nn.Module:
    checkpoint: dict[str, Any] = torch.load(
        path,
        map_location=device,
        weights_only=False,
    )
    state: dict[str, torch.Tensor] = checkpoint["model_state_dict"]
    weight_keys = sorted(
        (key for key in state if key.startswith("actor.") and key.endswith(".weight")),
        key=lambda key: int(key.split(".")[1]),
    )
    if not weight_keys:
        raise ValueError("checkpoint does not contain actor weights")
    layers: OrderedDict[str, torch.nn.Module] = OrderedDict()
    for layer_index, weight_key in enumerate(weight_keys):
        source_index = weight_key.split(".")[1]
        weight = state[weight_key]
        bias = state[f"actor.{source_index}.bias"]
        linear = torch.nn.Linear(weight.shape[1], weight.shape[0])
        linear.weight.data.copy_(weight)
        linear.bias.data.copy_(bias)
        layers[f"linear_{layer_index}"] = linear
        if layer_index < len(weight_keys) - 1:
            layers[f"elu_{layer_index}"] = torch.nn.ELU()
    actor = torch.nn.Sequential(layers).to(device)
    actor.eval()
    return actor
