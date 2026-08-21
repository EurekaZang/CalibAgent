"""DCLP policy backend helpers for real-robot deployment.

Two backends are supported:

* ``pth`` for the real-world PyTorch DCLP checkpoints under
  ``real_world_eval_models/dclp/11``.
* ``legacy_tf`` for the original TensorFlow checkpoint used by DCLP eval.

Both backends return DCLP normalized actions in [-1, 1]. Conversion to physical
cmd_vel belongs in ``dclp_deploy_core``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np

from dclp_deploy.dclp_schema import ACT_DIM, OBS_DIM


_CKPT_DATA_SUFFIX_RE = re.compile(r"\.data-\d+-of-\d+$")


def resolve_dclp_checkpoint_prefix(model_path: str) -> str:
    raw = os.path.abspath(os.path.expanduser(str(model_path)))

    if _CKPT_DATA_SUFFIX_RE.search(raw):
        raw = _CKPT_DATA_SUFFIX_RE.sub("", raw)
    elif raw.endswith(".meta"):
        raw = raw[:-5]
    elif raw.endswith(".index"):
        raw = raw[:-6]

    if os.path.isfile(raw + ".index"):
        return raw

    if os.path.isdir(raw):
        index_files = []
        for root, _dirs, files in os.walk(raw):
            for name in files:
                if name.endswith(".index"):
                    index_files.append(os.path.join(root, name))
        if index_files:
            index_files.sort(key=os.path.getmtime, reverse=True)
            return index_files[0][:-6]

    raise FileNotFoundError("no TensorFlow checkpoint prefix found for DCLP model_path: %s" % model_path)


def _tf_v1(tf_module: Any) -> Any:
    compat = getattr(tf_module, "compat", None)
    v1 = getattr(compat, "v1", None)
    return v1 or tf_module


def patch_tensorflow_v1_symbols(tf_module: Any) -> Any:
    tf1 = _tf_v1(tf_module)
    disable = getattr(tf1, "disable_v2_behavior", None)
    if disable is not None:
        disable()
    for name in (
        "ConfigProto",
        "Session",
        "disable_v2_behavior",
        "global_variables_initializer",
        "layers",
        "log",
        "multinomial",
        "placeholder",
        "random_normal",
        "trainable_variables",
        "variable_scope",
    ):
        if not hasattr(tf_module, name) and hasattr(tf1, name):
            setattr(tf_module, name, getattr(tf1, name))
    if not hasattr(tf_module, "log"):
        setattr(tf_module, "log", tf_module.math.log)
    if not hasattr(tf_module, "random_normal"):
        setattr(tf_module, "random_normal", tf_module.random.normal)
    if not hasattr(tf_module, "multinomial"):
        setattr(tf_module, "multinomial", tf_module.random.categorical)
    train = getattr(tf_module, "train", None)
    train_v1 = getattr(tf1, "train", None)
    if train is not None and train_v1 is not None and not hasattr(train, "Saver"):
        setattr(train, "Saver", getattr(train_v1, "Saver"))
    return tf1


class DclpLegacyTfPolicy:
    def __init__(
        self,
        *,
        model_path: str,
        gpu_mem_frac: float = 0.1,
        deterministic: bool = True,
        tf_module: Any = None,
        core_module: Any = None,
    ):
        if tf_module is None:
            import tensorflow as tf_module  # type: ignore[no-redef]
        if core_module is None:
            try:
                from offline_dvst.data_collection.dclp_utils import core_gmm as core_module
            except ImportError as exc:
                raise ImportError(
                    "legacy_tf backend requires offline_dvst.data_collection.dclp_utils.core_gmm, "
                    "which is not available in this workspace"
                ) from exc

        tf1 = patch_tensorflow_v1_symbols(tf_module)
        checkpoint = resolve_dclp_checkpoint_prefix(model_path)
        obs_ph, act_ph, obs2_ph, reward_ph, done_ph = core_module.placeholders(
            OBS_DIM,
            ACT_DIM,
            OBS_DIM,
            None,
            None,
        )
        del obs2_ph, reward_ph, done_ph
        with tf1.variable_scope("main"):
            mu, pi, logp_pi, q1, q2, q1_pi, q2_pi = core_module.mlp_actor_critic(
                obs_ph,
                act_ph,
            )
        del logp_pi, q1, q2, q1_pi, q2_pi

        config = tf1.ConfigProto()
        config.gpu_options.per_process_gpu_memory_fraction = float(gpu_mem_frac)
        sess = tf1.Session(config=config)
        sess.run(tf1.global_variables_initializer())
        saver = tf1.train.Saver(tf1.trainable_variables(), max_to_keep=None)
        saver.restore(sess, checkpoint)

        self.session = sess
        self.obs_ph = obs_ph
        self.action_op = mu if bool(deterministic) else pi
        self.model_path = os.path.abspath(os.path.expanduser(model_path))
        self.checkpoint = checkpoint
        self.policy_id = os.path.basename(checkpoint) or checkpoint

    def act(self, obs: Sequence[float]) -> np.ndarray:
        arr = np.asarray(obs, dtype=np.float32).reshape(-1)
        if arr.shape != (OBS_DIM,):
            raise ValueError("DCLP legacy TF policy expects %d-D obs, got %r" % (OBS_DIM, arr.shape))
        action = self.session.run(self.action_op, feed_dict={self.obs_ph: arr.reshape(1, -1)})
        action = np.asarray(action, dtype=np.float32).reshape(-1)
        if action.shape[0] < ACT_DIM:
            raise ValueError("DCLP legacy TF policy returned %d-D action" % action.shape[0])
        return np.clip(action[:ACT_DIM], -1.0, 1.0).astype(np.float32, copy=False)

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if close is not None:
            close()

    def summary(self) -> Dict[str, object]:
        return {
            "backend_type": "legacy_tf",
            "model_path": self.model_path,
            "checkpoint": self.checkpoint,
            "policy_id": self.policy_id,
            "obs_dim": OBS_DIM,
            "action_dim": ACT_DIM,
        }


def _require_torch():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    return torch, nn, F


def _build_pth_actor_classes():
    torch, nn, F = _require_torch()

    class _DclpPthCnn(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv1d(6, 32, kernel_size=1)
            self.conv2 = nn.Conv1d(32, 64, kernel_size=1)
            self.conv3 = nn.Conv1d(64, 128, kernel_size=1)

        def forward(self, x):
            x = F.leaky_relu(self.conv1(x), negative_slope=0.2)
            x = F.leaky_relu(self.conv2(x), negative_slope=0.2)
            x = F.leaky_relu(self.conv3(x), negative_slope=0.2)
            return torch.max(x, dim=2).values

    class _DclpPthMlp(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = nn.ModuleList(
                [
                    nn.Linear(136, 128),
                    nn.Linear(128, 128),
                    nn.Linear(128, 128),
                    nn.Linear(128, 128),
                ]
            )

        def forward(self, x):
            for layer in self.layers:
                x = torch.tanh(layer(x))
            return x

    return torch, nn, _DclpPthCnn, _DclpPthMlp


torch, nn, _DclpPthCnn, _DclpPthMlp = (None, None, None, None)
try:
    torch, nn, _DclpPthCnn, _DclpPthMlp = _build_pth_actor_classes()
except ImportError:
    pass


if nn is not None:

    class DclpPthPolicyActor(nn.Module):
        """PyTorch DCLP actor matching ``main_model_state_dict`` policy keys."""

        def __init__(self):
            super().__init__()
            self.alpha_actv1 = nn.Parameter(torch.tensor(0.0, dtype=torch.float32))
            self.cnn = _DclpPthCnn()
            self.mlp = _DclpPthMlp()
            self.gmm_layer = nn.Linear(128, 20)

        def gmm_params(self, obs):
            if obs.ndim == 1:
                obs = obs.reshape(1, -1)
            if obs.shape[-1] != OBS_DIM:
                raise ValueError("DCLP pth actor expects %d-D obs, got %r" % (OBS_DIM, tuple(obs.shape)))
            scan = obs[:, : 90 * 6].reshape(-1, 90, 6)
            distance = torch.clamp(scan[:, :, 2] + self.alpha_actv1, min=1e-8).reciprocal()
            scan = torch.cat(
                [
                    scan[:, :, 0:2],
                    distance.reshape(-1, 90, 1),
                    scan[:, :, 3:6],
                ],
                dim=-1,
            )
            cnn_in = scan.permute(0, 2, 1).contiguous()
            scan_feat = self.cnn(cnn_in)
            tail = obs[:, 90 * 6 : 90 * 6 + 8]
            net = self.mlp(torch.cat([scan_feat, tail], dim=-1))
            raw = self.gmm_layer(net).reshape(-1, 4, 5)
            logits = raw[:, :, 0]
            mu = raw[:, :, 1:3]
            log_std = raw[:, :, 3:5]
            return logits, mu, log_std

        def deterministic_action(self, obs):
            logits, mu, _log_std = self.gmm_params(obs)
            component = torch.argmax(logits, dim=1)
            batch = torch.arange(mu.shape[0], device=mu.device)
            selected_mu = mu[batch, component, :]
            return torch.tanh(selected_mu)

        def forward(self, obs):
            return self.deterministic_action(obs)

else:

    class DclpPthPolicyActor:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise ImportError("torch is required for DclpPthPolicyActor")


_EXPECTED_POLICY_SHAPES = {
    "alpha_actv1": (),
    "cnn.conv1.weight": (32, 6, 1),
    "cnn.conv1.bias": (32,),
    "cnn.conv2.weight": (64, 32, 1),
    "cnn.conv2.bias": (64,),
    "cnn.conv3.weight": (128, 64, 1),
    "cnn.conv3.bias": (128,),
    "mlp.layers.0.weight": (128, 136),
    "mlp.layers.0.bias": (128,),
    "mlp.layers.1.weight": (128, 128),
    "mlp.layers.1.bias": (128,),
    "mlp.layers.2.weight": (128, 128),
    "mlp.layers.2.bias": (128,),
    "mlp.layers.3.weight": (128, 128),
    "mlp.layers.3.bias": (128,),
    "gmm_layer.weight": (20, 128),
    "gmm_layer.bias": (20,),
}


def _extract_policy_state_dict(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    if "main_model_state_dict" not in checkpoint:
        raise ValueError("DCLP pth checkpoint missing main_model_state_dict")
    state = checkpoint["main_model_state_dict"]
    policy = {}
    for key, value in state.items():
        if key.startswith("policy."):
            policy[key[len("policy.") :]] = value
    missing = sorted(set(_EXPECTED_POLICY_SHAPES) - set(policy))
    extra = sorted(set(policy) - set(_EXPECTED_POLICY_SHAPES))
    if missing or extra:
        raise ValueError("DCLP pth policy keys mismatch missing=%s extra=%s" % (missing, extra))
    for key, expected in _EXPECTED_POLICY_SHAPES.items():
        actual = tuple(policy[key].shape)
        if actual != expected:
            raise ValueError("DCLP pth policy key %s shape %s != %s" % (key, actual, expected))
    return policy


class DclpPthPolicy:
    def __init__(self, *, model_path: str, device: str = "cpu"):
        torch_mod, _nn, _F = _require_torch()
        self.torch = torch_mod
        self.model_path = os.path.abspath(os.path.expanduser(model_path))
        self.device = torch_mod.device(device)
        checkpoint = torch_mod.load(self.model_path, map_location=self.device)
        policy_state = _extract_policy_state_dict(checkpoint)
        self.actor = DclpPthPolicyActor().to(self.device)
        self.actor.load_state_dict(policy_state, strict=True)
        self.actor.eval()
        self.policy_id = os.path.basename(self.model_path)
        self.checkpoint_meta = {
            "episode": checkpoint.get("episode"),
            "T": checkpoint.get("T"),
            "test_time": checkpoint.get("test_time"),
        }

    def act(self, obs: Sequence[float]) -> np.ndarray:
        arr = np.asarray(obs, dtype=np.float32).reshape(-1)
        if arr.shape != (OBS_DIM,):
            raise ValueError("DCLP pth policy expects %d-D obs, got %r" % (OBS_DIM, arr.shape))
        with self.torch.no_grad():
            tensor = self.torch.as_tensor(arr.reshape(1, -1), dtype=self.torch.float32, device=self.device)
            action = self.actor.deterministic_action(tensor).detach().cpu().numpy()[0]
        return np.clip(np.asarray(action, dtype=np.float32).reshape(-1)[:ACT_DIM], -1.0, 1.0)

    def close(self) -> None:
        return None

    def summary(self) -> Dict[str, object]:
        return {
            "backend_type": "pth",
            "model_path": self.model_path,
            "policy_id": self.policy_id,
            "device": str(self.device),
            "obs_dim": OBS_DIM,
            "action_dim": ACT_DIM,
            "deterministic_rule": "highest_weight_component_tanh_mu",
            "checkpoint_meta": dict(self.checkpoint_meta),
        }


@dataclass
class DclpPolicyBackend:
    model_path: str
    backend_type: str = "pth"
    gpu_mem_frac: float = 0.1
    device: str = "cpu"
    deterministic: bool = True

    def __post_init__(self):
        backend_type = str(self.backend_type or "pth").strip().lower()
        if backend_type in ("torch", "pytorch"):
            backend_type = "pth"
        if backend_type in ("tf", "tensorflow"):
            backend_type = "legacy_tf"
        self.backend_type = backend_type
        if not self.model_path:
            raise ValueError("model_path is required for DCLP policy backend")
        if backend_type == "pth":
            self.policy = DclpPthPolicy(model_path=self.model_path, device=self.device)
        elif backend_type == "legacy_tf":
            self.policy = DclpLegacyTfPolicy(
                model_path=self.model_path,
                gpu_mem_frac=self.gpu_mem_frac,
                deterministic=self.deterministic,
            )
        else:
            raise ValueError("unsupported DCLP backend_type=%r" % self.backend_type)

    def act(self, obs: Sequence[float]) -> np.ndarray:
        return self.policy.act(obs)

    def close(self) -> None:
        close = getattr(self.policy, "close", None)
        if close is not None:
            close()

    def summary(self) -> Dict[str, object]:
        summary = dict(self.policy.summary())
        summary["backend_type"] = self.backend_type
        return summary
