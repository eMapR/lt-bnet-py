"""Write schema-corrected copies of final BugNet polygon assets, and validate them.

The original buffered-polygon asset is never modified. The corrected copy is
written next to it as ``<bnet_buffered_polygons><suffix>``.

Corrections (see postprocess_utils):
  - ACRES, buffered_acres, unbuffered_acres, pct_affected: polygon geometry
    areas in an equal-area projection, replacing pixel count x 900 m2 (pixels
    are on an EPSG:4326 grid, so their true area is ~900*cos(lat) m2).
  - FEATURE_USER_ID: a non-personal identifier.
  - US_AREA / REGION_ID: IDS values ("CONUS"/"Alaska", integer USFS region).
  - MODIFIED_DATE: the correction date.
  - bnet_label: restored as the mode of the predicted raster over each
    polygon, the same reduction merge_buffer_buckets_and_finish computes.

Usage (from the repo root; configs are the run configs used for the run):
  python tools/correct_polygon_schema.py <config.py> submit
  python tools/correct_polygon_schema.py <config.py> validate
  python tools/correct_polygon_schema.py <config.py> annotate
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bugnet"))

import postprocess_utils as pu  # noqa: E402
from cli_utils import load_parameters  # noqa: E402

SUFFIX = "_corrected"
RECOMPUTED = ["ACRES", "buffered_acres", "unbuffered_acres", "pct_affected"]
RESET = ["FEATURE_USER_ID", "US_AREA", "REGION_ID", "MODIFIED_DATE"]
ADDED = ["bnet_label"]


def asset_ids(param):
    src = param["assetDir"] + param["bnet_buffered_polygons"]
    return src, src + SUFFIX


def build_corrected(param, modified_date):
    src, _ = asset_ids(param)
    buffered = ee.FeatureCollection(src)
    unbuffered = ee.FeatureCollection(param["assetDir"] + param["bnet_polygonized"])
    predicted = ee.Image(param["assetDir"] + param["predicted"])

    labeled = predicted.reduceRegions(
        collection=buffered,
        reducer=ee.Reducer.mode().setOutputs(["bnet_label"]),
        scale=param["pixel_scale"],
    )
    with_areas = pu.add_area_and_pct_affected(
        labeled, unbuffered, crs=pu.EQUAL_AREA_CRS[pu.us_area(param)]
    )
    fixed = {
        "FEATURE_USER_ID": param.get("feature_user_id", pu.DEFAULT_FEATURE_USER_ID),
        "US_AREA": pu.us_area(param),
        "REGION_ID": pu.usfs_region_id(param),
        "MODIFIED_DATE": modified_date,
    }
    return with_areas.map(lambda f: f.set(fixed))


def submit(param):
    _, dst = asset_ids(param)
    try:
        ee.data.getAsset(dst)
        print(f"Already exists, not overwriting: {dst}")
        return
    except ee.EEException:
        pass
    corrected = build_corrected(param, datetime.date.today().strftime("%m-%d-%Y"))
    task = ee.batch.Export.table.toAsset(
        collection=corrected, description=dst.rsplit("/", 1)[-1], assetId=dst
    )
    task.start()
    print(f"Submitted {task.id} -> {dst}")


def _git_revision():
    repo = Path(__file__).resolve().parent.parent
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout.strip()
    dirty = "+uncommitted" if run("status", "--porcelain") else ""
    return f"{run('rev-parse', '--abbrev-ref', 'HEAD')}@{run('rev-parse', '--short', 'HEAD')}{dirty}"


def annotate(param):
    """Record the schema corrections as properties on the corrected asset."""
    src, dst = asset_ids(param)
    crs = pu.EQUAL_AREA_CRS[pu.us_area(param)]
    properties = {
        "correction_source_asset": src,
        "correction_tool": f"tools/correct_polygon_schema.py ({_git_revision()})",
        "correction_date": datetime.date.today().isoformat(),
        "schema_change_REGION_ID": (
            "TYPE CHANGE: REGION_ID is now an integer USFS region as in the IDS schema "
            "(6 = Region 6, 10 = Region 10/Alaska). The original asset stored a string "
            "('CONUS' or 'AK'); scripts that compare REGION_ID to those strings must be updated."
        ),
        "schema_change_areas": (
            f"ACRES = buffered_acres = polygon area in {crs} (equal-area). unbuffered_acres = "
            f"sum of the contained unbuffered polygons' areas in {crs}. pct_affected = "
            "unbuffered_acres / buffered_acres * 100. The original asset used pixel count x 900 m2 "
            "for unbuffered_acres (EPSG:4326 pixels are ~900*cos(lat) m2), ACRES = 0, and "
            "EE spherical area for buffered_acres."
        ),
        "schema_change_US_AREA": "IDS values: 'CONUS' or 'Alaska'.",
        "schema_change_FEATURE_USER_ID": "Set to 'BugNet' (was a personal email).",
        "schema_change_MODIFIED_DATE": "Date of this correction (MM-DD-YYYY); was 'na'.",
        "schema_change_bnet_label": (
            f"Restored: mode of {param['predicted']} over each polygon at "
            f"{param['pixel_scale']} m (dropped from the original asset)."
        ),
    }
    ee.data.updateAsset(dst, {"properties": properties}, ["properties"])
    print(json.dumps(ee.data.getAsset(dst)["properties"], indent=2))


def _stats(fc, field):
    return fc.aggregate_stats(field)


def validation_report(param):
    """Compare a corrected asset against its original; return a report dict."""
    src, dst = asset_ids(param)
    before = ee.FeatureCollection(src)
    after = ee.FeatureCollection(dst)
    unbuffered = ee.FeatureCollection(param["assetDir"] + param["bnet_polygonized"])
    crs = pu.EQUAL_AREA_CRS[pu.us_area(param)]

    props_before = set(before.first().propertyNames().getInfo()) - {"system:index"}
    props_after = set(after.first().propertyNames().getInfo()) - {"system:index"}
    unchanged = sorted(props_before - set(RECOMPUTED) - set(RESET))

    # Export renumbers system:index, so pair features spatially. The buffered
    # polygons are dissolved and disjoint, so each should have one partner.
    pairs = ee.FeatureCollection(ee.Join.saveAll("matches").apply(
        after, before, ee.Filter.intersects(leftField=".geo", rightField=".geo")
    ))

    def compare(pair):
        matches = ee.List(pair.get("matches"))
        a = ee.Feature(pair).set("matches", None)
        b = ee.Feature(matches.get(0))
        flags = {
            f"same_{p}": ee.Algorithms.If(ee.Algorithms.IsEqual(b.get(p), a.get(p)), 1, 0)
            for p in unchanged
        }
        flags["n_matches"] = matches.size()
        flags["same_geometry"] = ee.Algorithms.If(
            ee.Algorithms.IsEqual(b.geometry(), a.geometry()), 1, 0
        )
        flags["symdiff_m2"] = b.geometry().symmetricDifference(a.geometry(), 1).area(1)
        flags["ratio_unbuffered"] = ee.Number(b.get("unbuffered_acres")).divide(a.get("unbuffered_acres"))
        flags["pct_before"] = b.get("pct_affected")
        flags["pct_after"] = a.get("pct_affected")
        return ee.Feature(None, flags)

    cmp = ee.FeatureCollection(pairs.map(compare))
    unbuffered_total = unbuffered.map(
        lambda f: f.set("a", ee.Number(f.geometry().area(1, crs)).multiply(pu.ACRES_PER_SQ_M))
    ).aggregate_sum("a")

    report = ee.Dictionary({
        "n_before": before.size(),
        "n_after": after.size(),
        "n_paired": cmp.size(),
        "n_with_exactly_one_partner": cmp.filter(ee.Filter.eq("n_matches", 1)).size(),
        "same_geometry": cmp.aggregate_sum("same_geometry"),
        "max_symmetric_difference_m2": cmp.aggregate_max("symdiff_m2"),
        "unchanged_fields_matching": ee.Dictionary({p: cmp.aggregate_sum(f"same_{p}") for p in unchanged}),
        "ratio_old_to_new_unbuffered_acres": _stats(cmp, "ratio_unbuffered"),
        "pct_affected_before": _stats(cmp, "pct_before"),
        "pct_affected_after": _stats(cmp, "pct_after"),
        "n_pct_gt_100_before": before.filter(ee.Filter.gt("pct_affected", 100)).size(),
        "n_pct_gt_100_after": after.filter(ee.Filter.gt("pct_affected", 100)).size(),
        "n_no_unbuffered_match_after": after.filter(ee.Filter.eq("unbuffered_acres", 0)).size(),
        "sum_unbuffered_acres_before": before.aggregate_sum("unbuffered_acres"),
        "sum_unbuffered_acres_after": after.aggregate_sum("unbuffered_acres"),
        "sum_unbuffered_polygon_acres_direct": unbuffered_total,
        "sum_buffered_acres_before": before.aggregate_sum("buffered_acres"),
        "sum_buffered_acres_after": after.aggregate_sum("buffered_acres"),
        "ACRES_equals_buffered_acres_after": after.filter(
            ee.Filter.equals(leftField="ACRES", rightField="buffered_acres")
        ).size(),
        "bnet_label_histogram": after.aggregate_histogram("bnet_label"),
        "n_bnet_label_null": after.filter(ee.Filter.notNull(["bnet_label"]).Not()).size(),
        **{f"values_{p}_before": before.aggregate_histogram(p) for p in RESET},
        **{f"values_{p}_after": after.aggregate_histogram(p) for p in RESET},
    }).getInfo()
    report["fields_only_before"] = sorted(props_before - props_after)
    report["fields_only_after"] = sorted(props_after - props_before)
    report["unchanged_fields_checked"] = unchanged
    return report


def validate(param):
    """Compare a corrected asset against its original; print a JSON report."""
    print(json.dumps(validation_report(param), indent=2, sort_keys=True, default=str))


def main():
    commands = {"submit": submit, "validate": validate, "annotate": annotate}
    if len(sys.argv) != 3 or sys.argv[2] not in commands:
        print(__doc__)
        sys.exit(1)
    param = load_parameters(sys.argv[1])
    ee.Initialize(project=param["project_name"])
    commands[sys.argv[2]](param)


if __name__ == "__main__":
    main()
