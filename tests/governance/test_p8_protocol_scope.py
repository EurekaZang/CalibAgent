"""Keep the P8 real-robot plan concise and executable."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parents[2]
GUIDE = WORKSPACE / "docs/p8_go2_implementation_guide_zh.md"
PLAN = WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p8_documents_are_lean() -> None:
    guide = _text(GUIDE)
    plan = _text(PLAN)
    assert len(guide.splitlines()) < 150
    assert len(plan.splitlines()) < 400

    removed_process_terms = (
        "Gate A",
        "Gate B",
        "Gate C",
        "Gate D",
        "双人 approval",
        "trust_registry",
        "签字表",
        "watchdog",
        "interlock",
        "safety_review",
        "release freeze",
    )
    for term in removed_process_terms:
        assert term not in guide
        assert term not in plan


def test_p8_nav_design_is_preserved() -> None:
    plan = _text(PLAN)
    for method_id in (
        "B0_raw",
        "B1_dense",
        "B2_lhs",
        "B3_sobol",
        "B4_d_opt",
        "B5_active_no_task",
        "B6_random",
        "B8_full",
    ):
        assert method_id in plan
    for map_id in ("real_offset_slalom", "real_weighted_arc"):
        assert map_id in plan
    for value in ("3,060", "1,920", "480 navigation episodes"):
        assert value in plan
    assert "30 个完整 blocks" in plan
    assert "m1_affine" in plan


def test_p8_shift_design_is_preserved() -> None:
    plan = _text(PLAN)
    for method_id in ("frozen", "passive", "full"):
        assert method_id in plan
    for shift_id in (
        "R1_command_gain_coupling",
        "R2_payload_com",
        "R3_surface_friction",
        "R4_mixed_context",
    ):
        assert shift_id in plan
    assert "10,800 motion trials" in plan
    assert "m2_affine_cross_hinge" in plan
    assert "每个 shift 有 20 个完整" in plan


def test_p8_command_path_has_no_extra_locomotion_control() -> None:
    guide = _text(GUIDE)
    plan = _text(PLAN)
    assert "planner desired velocity -> calibration transform -> Go2 command adapter" in guide
    assert "policy/planner 和 calibration transform 外，不增加" in guide  # noqa: RUF001
    assert "不得再增加第三套速度" in plan


def test_p7_six_map_simulator_evidence_is_unchanged() -> None:
    config = yaml.safe_load(
        (
            WORKSPACE
            / "configs/experiments/p7_navigation_strong_confirmatory_v2.yaml"
        ).read_text(encoding="utf-8")
    )
    assert len(config["maps"]) == 6
