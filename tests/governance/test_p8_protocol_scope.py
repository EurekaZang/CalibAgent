"""Keep the reduced P8 hardware scope distinct from the six-map P7 evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parents[2]
P8_MAPS = ("real_offset_slalom", "real_weighted_arc")
MULTIPLY = chr(0xD7)
EN_DASH = chr(0x2013)


def test_p8_documents_freeze_two_map_nav_cardinality() -> None:
    guide = (WORKSPACE / "docs/p8_go2_implementation_guide_zh.md").read_text(
        encoding="utf-8"
    )
    handoff = (WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md").read_text(
        encoding="utf-8"
    )

    for document in (guide, handoff):
        assert all(map_id in document for map_id in P8_MAPS)
        assert "3,060" in document
        assert "1,920" in document
        assert "| navigation episodes | 1,440 |" not in document
        assert '"navigation_episodes": 1440' not in document
        assert "navigation  = 1,440 episodes" not in document

    assert '"navigation_episodes": 480' in guide
    assert "navigation episodes | 480" in handoff
    assert f"| `30 + 6{MULTIPLY}12` | 102 |" in guide
    assert f"| `8{MULTIPLY}8` | 64 |" in guide
    assert f"| `8{MULTIPLY}2` | 16 |" in guide
    assert f"`30 + 6{MULTIPLY}12 = 102`" in handoff
    assert f"`8 methods {MULTIPLY} 8 commands = 64`" in handoff
    assert f"`8 methods {MULTIPLY} 2 maps = 16`" in handoff

    for document in (guide, handoff):
        assert f"8 methods {MULTIPLY} 6 maps = 48" not in document
    assert "navigation episodes | 480" in handoff
    assert "map coverage | 2/2" in handoff
    assert "planned_map_order_by_method_json" in handoff
    assert "entry.schedule_id == schedule_id" in handoff


def test_readmes_separate_p8_hardware_scope_from_p7_simulation() -> None:
    readme_en = (WORKSPACE / "README.md").read_text(encoding="utf-8")
    readme_zh = (WORKSPACE / "README_zh-CN.md").read_text(encoding="utf-8")

    for document in (readme_en, readme_zh):
        assert all(map_id in document for map_id in P8_MAPS)
        assert "P8-SHIFT" in document
        assert "P7" in document

    assert "real-robot scope decision is fixed at two P8-NAV routes" in readme_en
    assert "P8-NAV 只执行" in readme_zh
    assert "six-map results above remain the completed P7 simulator" in readme_en
    assert "上文六地图结果仍是已完成的 P7" in readme_zh


def test_completion_semantics_names_the_reduced_p8_scope() -> None:
    completion = (WORKSPACE / "docs/completion_semantics.md").read_text(
        encoding="utf-8"
    )

    assert "P8 | L0 protocol only" in completion
    assert all(map_id in completion for map_id in P8_MAPS)
    assert f"P8-SHIFT R1{EN_DASH}R4" in completion
    assert "P7 | L3" in completion
    assert "six new maps" in completion


def test_p8_shift_scope_remains_complete() -> None:
    guide = (WORKSPACE / "docs/p8_go2_implementation_guide_zh.md").read_text(
        encoding="utf-8"
    )
    handoff = (WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md").read_text(
        encoding="utf-8"
    )
    for shift_id in (
        "R1_command_gain_coupling",
        "R2_payload_com",
        "R3_surface_friction",
        "R4_mixed_context",
    ):
        assert shift_id in guide
        assert shift_id in handoff
    for document in (guide, handoff):
        assert "10,800" in document
        assert "11,280" in document
        assert "nominal_restore_sentinel_metrics.csv" in document
        assert "changeover_evidence_index.csv" in document
    assert "240 sequences" in guide
    assert "initial_planned_restore_sentinel_units" in guide
    assert "480 个 nominal-restore" in handoff
    assert f"P8-SHIFT R1{EN_DASH}R4 全部完成" in handoff
    assert "共 47 个" in guide
    assert "RECOVER_NOMINAL" in guide
    assert "RECOVER_NOMINAL" in handoff


def test_p8_runtime_contracts_remain_unambiguous() -> None:
    guide = (WORKSPACE / "docs/p8_go2_implementation_guide_zh.md").read_text(
        encoding="utf-8"
    )
    handoff = (WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md").read_text(
        encoding="utf-8"
    )

    assert "`safety_abort / COLLISION`" in guide
    assert "`safety_abort / COLLISION`" in handoff
    assert "`complete / COLLISION`" not in handoff
    assert "ScopeAuthorization" in guide
    assert "RegisterScopeAuthorization.srv" in guide
    assert "conditional_context_return_unit_ids" in guide
    assert "p8.schedule-manifest.v1" in guide
    assert "p8.schedule-manifest.v1" in handoff
    assert "`CONFIRM_READY` 是采集前" in handoff
    assert "`P8_EVIDENCE_GO` 条件" in handoff
    assert "只有采完、delivery validation" in guide


def test_p7_six_map_simulator_evidence_is_unchanged() -> None:
    config = yaml.safe_load(
        (
            WORKSPACE
            / "configs/experiments/p7_navigation_strong_confirmatory_v2.yaml"
        ).read_text(encoding="utf-8")
    )
    assert len(config["maps"]) == 6
    assert {item["id"] for item in config["maps"]} >= {
        "replicate_offset_slalom",
        "replicate_weighted_arc",
    }


def test_p8_release_provenance_and_gate_a_evidence_are_frozen() -> None:
    guide = (WORKSPACE / "docs/p8_go2_implementation_guide_zh.md").read_text(
        encoding="utf-8"
    )
    handoff = (WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md").read_text(
        encoding="utf-8"
    )

    for document in (guide, handoff):
        assert "third_party_robot_dependencies.yaml" in document
        assert "unitree_sdk.LICENSE.txt" in document
        assert "command_bridge.LICENSE.txt" in document
        assert "reference_stack.LICENSE.txt" in document
        assert "UNSET-P8-NOT-INTEGRATED" in document
        assert "gate_a/" in document
    assert "test_reports/p8_gate_evidence/gate_a" in guide
    assert "--evidence-dir ABS_NEW_PATH" in guide
    assert "src/calibagent/hardware/go2/" in guide
    assert "audit_p8_source.py" in guide
    assert "audit_p8_cli_help.py" in guide
    assert "tests/hil/p8/" in guide
    assert "logical_role" in guide
    assert "不存在未定义的" in guide
    assert "ValidatedReleaseRoot / PurePosixPath(ref.path)" in guide
    assert "ValidatedStageRoleView(stage, role)" in guide
    assert "RepositorySourceMap" in guide
    assert "schedules/schedule_manifest.json" in guide
    assert "maps/evidence/<map_id>/survey.csv" in guide
    assert "--cov=calibagent --cov-branch --cov-fail-under=85" in guide
    assert "P8 aggregate line coverage ≥90.0%" in guide
    assert "P8 aggregate branch coverage ≥80.0%" in guide
    assert "每个 executable P8 file line coverage ≥70.0%" in guide
    assert "required_p8_test_count=120" in guide
    assert "tests/governance/test_p8_protocol_scope.py" in guide
    assert "相对 config 文件解析" not in guide
    assert "相对该 map YAML" not in guide
    for document in (guide, handoff):
        assert "static_preflight_report.schema.json" in document
    assert "p8.static-preflight-report.v1" in guide
    assert "static preflight/review/reset/sign/analyze" in guide
    assert (
        "--repository-root PATH --integration-stage PATH --gate-b PATH\n"
        "  --gate-approval-root PATH --hil-evidence-dir NEW_DIR --output NEW_FILE"
        in guide
    )
    assert "`build-gate-c` 入口只有" in guide
    assert "signed Gate A+Gate B 引用集" in guide

    attributes = (WORKSPACE / ".gitattributes").read_text(encoding="utf-8")
    for pattern in ("*.md", "*.py", "*.yaml", "*.json", "*.csv", "*.cpp"):
        assert f"{pattern} text eol=lf" in attributes
    assert "evidence/p1_real/raw_trials.csv binary" in attributes


def test_p8_analysis_plan_matches_the_reduced_scope_and_power_design() -> None:
    handoff = (WORKSPACE / "docs/p8_go2_real_deployment_data_handoff_zh.md").read_text(
        encoding="utf-8"
    )
    marker = "```yaml\nschema_version: p8.analysis-plan.v1\n"
    start = handoff.index(marker) + len("```yaml\n")
    end = handoff.index("\n```", start)
    plan = yaml.safe_load(handoff[start:end])

    assert plan["nav"]["map_ids"] == list(P8_MAPS)
    assert plan["primary_gates"]["nav"]["required_map_ids"] == list(P8_MAPS)
    assert len(plan["shift"]["shift_ids"]) == 4
    assert plan["nav"]["planned_blocks"] == 30
    assert plan["shift"]["planned_blocks_per_shift"] == 20

    power = plan["power_plan"]
    assert power["pilot_cardinality"]["nav_blocks"] == 5
    assert power["pilot_cardinality"]["shift_blocks_per_shift"] == 5
    assert power["continuous_family"]["expected_cell_count"] == 22
    assert power["discrete_family"]["expected_check_count"] == 62
    assert power["zero_or_nonfinite_sd_policy"] == "FAIL_CELL_POWER_NULL"
    assert power["interpretation"] == "MARGINAL_CELL_READINESS_NOT_JOINT_FAMILY_POWER"

    estimands = plan["estimands"]
    assert estimands["expected_primary_hypothesis_id_count"] == 116
    assert estimands["expected_secondary_hypothesis_id_count"] == 142
    assert estimands["expected_total_hypothesis_id_count"] == 258
