from unittest.mock import MagicMock, patch

import pytest

import disturbance_utils as du

ASSET_DIR = "projects/x-bugnet/assets/2026-v2/"
BASE = "B1_predictor_disturbance_polygons_2026"
GRID = f"{ASSET_DIR}{BASE}_grid_40000m"


def _param():
    return {
        "assetDir": ASSET_DIR,
        "disturbance_polygons_predictor": BASE,
        "predictor_change_img": "A_predictor_change_img_2026",
        "aoi": "aoi",
    }


def _task(state="COMPLETED"):
    task = MagicMock()
    task.status.return_value = {"state": state}
    return task


def _run_grid(existing, grid_state="COMPLETED"):
    """Run the grid strategy with EE mocked; return (result, export mock, ee mock)."""
    ee = MagicMock()
    ee.FeatureCollection.return_value.size.return_value.getInfo.return_value = 2
    ee.String.return_value.getInfo.side_effect = ["cell_0", "cell_1"]
    ee.Number.return_value.getInfo.return_value = 5
    tasks = iter([_task(grid_state), _task(), _task()])
    export = MagicMock(side_effect=lambda fc, desc, d: next(tasks))
    with patch.object(du, "ee", ee), \
            patch.object(du.bnet, "export_feature_collection", export), \
            patch.object(du.bnet, "vectorize_disturbance", return_value=MagicMock()), \
            patch.object(du, "split_collection_covering_grid", return_value="lazy_grid"), \
            patch.object(du.time, "sleep"):
        res = du.CreatePredictorDisturbancePolygons(
            _param(), lambda a: a in existing, strategy="grid", grid_cell_m=40000)
    return res, export, ee


def test_grid_is_exported_once_then_read_from_the_asset():
    res, export, ee = _run_grid(existing=set())
    grid_exports = [c for c in export.call_args_list if c.args[1] == f"{BASE}_grid_40000m"]
    assert len(grid_exports) == 1
    assert grid_exports[0].args[0] == "lazy_grid"
    ee.FeatureCollection.assert_any_call(GRID)
    assert res["asset_paths"] == [f"{ASSET_DIR}{BASE}_cell_0", f"{ASSET_DIR}{BASE}_cell_1"]
    assert GRID in res["created_asset_paths"]


def test_existing_grid_asset_is_reused():
    res, export, _ = _run_grid(existing={GRID})
    assert [c.args[1] for c in export.call_args_list] == [f"{BASE}_cell_0", f"{BASE}_cell_1"]
    assert GRID not in res["created_asset_paths"]


def test_failed_grid_export_fails_the_strategy():
    with pytest.raises(RuntimeError, match="ended FAILED"):
        _run_grid(existing=set(), grid_state="FAILED")


def test_wait_for_export_polls_until_terminal():
    task = MagicMock()
    task.status.side_effect = [{"state": "READY"}, {"state": "RUNNING"}, {"state": "COMPLETED"}]
    sleep = MagicMock()
    assert du._wait_for_export(task, sleep=sleep) == "COMPLETED"
    assert sleep.call_count == 2


def _fc(name):
    """Mock collection whose filter() returns a distinct child per filter."""
    fc = MagicMock(name=name)
    children = {}
    fc.filter.side_effect = lambda f: children.setdefault(f, MagicMock(name=f"{name}[{f}]"))
    return fc


def _wild_ee():
    ee = MagicMock()
    ee.Filter.eq.side_effect = lambda prop, v: f"{prop}=={v}"
    ee.Filter.neq.side_effect = lambda prop, v: f"{prop}!={v}"
    return ee


def test_wilderness_rule_keeps_each_patch_once():
    ee = _wild_ee()
    buffered, wilderness = _fc("buffered"), MagicMock(name="wild")
    with patch.object(du, "ee", ee):
        out = du.drop_nonfire_in_wilderness(buffered, wilderness)
    fire, non_fire = buffered.filter("classification==40"), buffered.filter("classification!=40")
    join_kwargs = ee.Join.inverted.return_value.apply.call_args.kwargs
    # Only non-fire patches go through the join, so fire isn't merged in twice.
    assert join_kwargs["primary"] is non_fire
    assert join_kwargs["secondary"] is wilderness
    fire.merge.assert_called_once_with(ee.Join.inverted.return_value.apply.return_value)
    assert out is fire.merge.return_value


def _run_buffer(wild_on):
    param = {"assetDir": ASSET_DIR, "filtered_classes": "C2", "buffered_classes": "C3",
             "wild_path": {"on": wild_on, "path": "wild1", "path2": "wild2"}}
    with patch.object(du, "ee") as ee, \
            patch.object(du.bnet, "buffer_features", return_value="buffered") as buf, \
            patch.object(du, "drop_nonfire_in_wilderness", return_value="kept") as wild, \
            patch.object(du.bnet, "export_feature_collection") as export:
        du.buffer_classed_polygons(param, lambda a: False)
    return ee, buf, wild, export


def test_buffer_without_wilderness_exports_buffered_patches():
    _, buf, wild, export = _run_buffer(0)
    buf.assert_called_once()
    wild.assert_not_called()
    assert export.call_args.args[:2] == ("buffered", "C3")


def test_buffer_with_wilderness_applies_rule_to_buffered_patches():
    ee, _, wild, export = _run_buffer(1)
    assert wild.call_args.args[0] == "buffered"
    assert wild.call_args.args[1] is ee.FeatureCollection.return_value.merge.return_value
    assert export.call_args.args[:2] == ("kept", "C3")


def _empty_exclusion_param():
    return {"assetDir": ASSET_DIR, "exclusion_classes": [], "classified_fc": "C1",
            "filtered_classes": "C2", "buffered_classes": "C3", "rasterize_classes": "C4",
            "pixel_scale": 30, "aoi": MagicMock(), "wild_path": {"on": 1}}


def test_empty_exclusion_skips_table_stages():
    param = _empty_exclusion_param()
    with patch.object(du, "ee"), patch.object(du.bnet, "export_feature_collection") as export:
        assert du.filter_classes(param, lambda a: False) is None
        assert du.buffer_classed_polygons(param, lambda a: False) is None
    export.assert_not_called()


def test_empty_exclusion_writes_zero_classed_image():
    param = _empty_exclusion_param()
    with patch.object(du, "ee") as ee, \
            patch.object(du.bnet, "rasterize_polygons") as rasterize, \
            patch.object(du.bnet, "export_image") as export:
        du.rasterize_classed_polygons(param, lambda a: False)
    rasterize.assert_not_called()
    ee.Image.constant.assert_called_once_with(0)
    zero = ee.Image.constant.return_value.toInt32.return_value.rename.return_value
    ee.Image.constant.return_value.toInt32.return_value.rename.assert_called_once_with('first')
    assert export.call_args.args[0] is zero
    assert export.call_args.args[3] == "C4"


def test_nonempty_exclusion_still_rasterizes_c3():
    param = dict(_empty_exclusion_param(), exclusion_classes=[20, 21])
    with patch.object(du, "ee"), \
            patch.object(du.bnet, "rasterize_polygons") as rasterize, \
            patch.object(du.bnet, "export_image"):
        du.rasterize_classed_polygons(param, lambda a: False)
    rasterize.assert_called_once()
