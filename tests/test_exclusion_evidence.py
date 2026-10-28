from unittest.mock import MagicMock, patch

import pytest

import bnet
import disturbance_utils as du
import exclusion_evidence as xe

ASSET_DIR = "projects/x-bugnet/assets/2026-v2/"


def _param(**gate):
    param = {
        "assetDir": ASSET_DIR,
        "classified_fc": "C1_classified_polygons_2026",
        "filtered_classes": "C2_classified_polygons_filtered_2026_d2",
    }
    if gate:
        param["exclusion_evidence"] = gate
    return param


class TestResolveEvidenceGate:
    def test_absent_is_off(self):
        assert xe.resolve_evidence_gate(_param()) is None

    def test_on_zero_is_off(self):
        assert xe.resolve_evidence_gate(_param(on=0, released_name="QA")) is None

    def test_defaults_use_hansen_2025(self):
        gate = xe.resolve_evidence_gate(_param(on=1, released_name="C2r_released_2026"))
        assert gate["gfc_asset"] == "UMD/hansen/global_forest_change_2025_v1_13"
        assert gate["harvest_classes"] == [20, 21, 30, 31]
        assert gate["qa_flag_from_year"] == 2025
        assert gate["facts_path"] == ""
        assert "on" not in gate

    def test_overrides_are_kept(self):
        gate = xe.resolve_evidence_gate(_param(on=1, released_name="QA", firms_buffer_m=500))
        assert gate["firms_buffer_m"] == 500

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="unknown keys"):
            xe.resolve_evidence_gate(_param(on=1, released_name="QA", gfc_min_fracton=0.4))

    def test_missing_released_name_raises(self):
        with pytest.raises(ValueError, match="released_name"):
            xe.resolve_evidence_gate(_param(on=1))

    def test_released_name_cannot_overwrite_pipeline_assets(self):
        with pytest.raises(ValueError, match="clashes"):
            xe.resolve_evidence_gate(_param(on=1, released_name="C2_classified_polygons_filtered_2026_d2"))

    def test_bad_fraction_raises(self):
        with pytest.raises(ValueError, match="gfc_min_fraction"):
            xe.resolve_evidence_gate(_param(on=1, released_name="QA", gfc_min_fraction=0))


def _run_filter(param, existing=(), qa_state="COMPLETED"):
    """Run filter_classes with EE mocked; return (result, export mock, split mock)."""
    exported = []

    def export(fc, name, asset_dir):
        exported.append((fc, name, asset_dir))
        task = MagicMock(name=name)
        task.status.return_value = {"state": qa_state if name == "QA" else "COMPLETED"}
        return task

    masked, released = MagicMock(name="masked"), MagicMock(name="released")
    with patch.object(du, "ee"), \
            patch.object(du.bnet, "resolve_exclusion_classes", return_value=("legacy_range", None)), \
            patch.object(du.bnet, "filter_by_mode_value", return_value="candidates"), \
            patch.object(du.bnet, "export_feature_collection", side_effect=export), \
            patch.object(du.exclusion_evidence, "tag_evidence", return_value="tagged") as tag, \
            patch.object(du.exclusion_evidence, "split_by_evidence", return_value=(masked, released)), \
            patch.object(du.time, "sleep"):
        res = du.filter_classes(param, lambda a: a in existing)
    return res, exported, tag, masked, released


def test_gate_off_exports_the_class_filter_unchanged():
    res, exported, tag, _, _ = _run_filter(_param())
    assert [(fc, name) for fc, name, _ in exported] == [("candidates", "C2_classified_polygons_filtered_2026_d2")]
    tag.assert_not_called()


def test_gate_on_masks_evidence_and_exports_released_qa():
    res, exported, tag, masked, released = _run_filter(_param(on=1, released_name="QA"))
    assert tag.call_args.args[0] == "candidates"
    assert [(fc, name) for fc, name, _ in exported] == [(released, "QA"), (masked, "C2_classified_polygons_filtered_2026_d2")]
    assert res is not None


def test_failed_qa_export_fails_the_step():
    with pytest.raises(RuntimeError, match="QA export QA ended FAILED"):
        _run_filter(_param(on=1, released_name="QA"), qa_state="FAILED")


def test_existing_outputs_are_not_reexported():
    res, exported, _, _, _ = _run_filter(
        _param(on=1, released_name="QA"),
        existing={ASSET_DIR + "C2_classified_polygons_filtered_2026_d2", ASSET_DIR + "QA"})
    assert exported == [] and res is None


def test_missing_qa_is_backfilled_without_touching_c2():
    res, exported, _, _, released = _run_filter(
        _param(on=1, released_name="QA"), existing={ASSET_DIR + "C2_classified_polygons_filtered_2026_d2"})
    assert [(fc, name) for fc, name, _ in exported] == [(released, "QA")]
    assert res is None


def _manifest_param(**overrides):
    param = {
        "project_name": "william-sound-bugnet", "version": "2", "shared_version": "2",
        "change_params": {"mag": {"value": 250, "operator": ">"}}, "wild_path": {"on": 1},
        "decline_path": "ltsd", "configName": "option3", "fit": ["TCB", "TCG", "TCW"],
        "assetDir": ASSET_DIR, "sharedAssetDir": ASSET_DIR, "target": 2026,
        "parameter_file": "parameter_file", "agent_lookback": 5,
    }
    param.update(overrides)
    return param


def test_manifest_records_gate_off_by_default():
    m = bnet.build_run_manifest(_manifest_param())
    assert m["exclusion_evidence_on"] is False
    assert m["exclusion_evidence_released_asset"] == ""


def test_manifest_records_gate_settings():
    m = bnet.build_run_manifest(_manifest_param(exclusion_evidence={"on": 1, "released_name": "QA"}))
    assert m["exclusion_evidence_on"] is True
    assert m["exclusion_evidence_released_asset"] == ASSET_DIR + "QA"
    assert m["exclusion_evidence_gfc_asset"].endswith("2025_v1_13")
