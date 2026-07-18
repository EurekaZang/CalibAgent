from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from tests.conftest import observation

from calibagent.backends.replay import OfflineReplayBackend
from calibagent.cli.convert_dataset import convert_csv
from calibagent.data.observations import load_observations, save_observations
from calibagent.interfaces.types import TrialPolicy, VelocityCommand


def test_replay_consumes_each_trial_once(context) -> None:
    observations = [
        observation(np.asarray([0.0, 0.0, 0.0]), np.zeros(3), context),
        observation(np.asarray([0.5, 0.0, 0.0]), np.asarray([0.4, 0, 0]), context),
    ]
    backend = OfflineReplayBackend(observations)
    index, selected = backend.nearest_observation(VelocityCommand(0.45, 0, 0, 2))
    assert index == 1 and selected is observations[1]
    with pytest.raises(RuntimeError, match="already consumed"):
        backend.observation_at(1)


def test_parquet_round_trip(context, tmp_path) -> None:
    observations = [
        observation(np.asarray([0.2, -0.1, 0.3]), np.asarray([0.1, -0.08, 0.25]), context)
    ]
    path = tmp_path / "trials.parquet"
    save_observations(observations, path)
    restored = load_observations(path)
    assert len(restored) == 1
    assert restored[0].to_dict() == observations[0].to_dict()


def test_csv_converter_emits_canonical_parquet(tmp_path) -> None:
    source = tmp_path / "dense.csv"
    destination = tmp_path / "trials.parquet"
    pd.DataFrame(
        {
            "cmd_vx": [0.2],
            "cmd_vy": [0.0],
            "cmd_wz": [-0.3],
            "mean_vx": [0.18],
            "mean_vy": [0.01],
            "mean_wz": [-0.25],
            "var_vx": [0.001],
            "var_vy": [0.001],
            "var_wz": [0.002],
        }
    ).to_csv(source, index=False)
    convert_csv(source, destination, "converted-session")
    restored = load_observations(destination)
    assert restored[0].context.session_id == "converted-session"
    assert destination.with_suffix(".manifest.json").is_file()


def test_replay_protocol_methods(context) -> None:
    item = observation(np.asarray([0.1, 0.0, 0.0]), np.asarray([0.08, 0.0, 0.0]), context)
    backend = OfflineReplayBackend([item])
    backend.reset(context)
    assert backend.get_state().localization_valid
    raw = backend.execute_trial(VelocityCommand(0.1, 0.0, 0.0, 2.0), TrialPolicy())
    assert raw.pose_se2.shape == (101, 3)
    assert raw.metadata["reconstructed_from_aggregate"] is True
    backend.emergency_stop("test")
