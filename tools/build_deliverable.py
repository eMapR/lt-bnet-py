"""Build a region's Box deliverable from its run config and Earth Engine assets.

Produces the layout of the North Cascades 2026 delivery:

  <staging>/Bugnet_Region_<R>/Data/<target>/
    README.txt                                     year index (entry added)
    Bugnet_<Name>_v<target>-<version>/
      README.txt
      <prefix>_polygons_<variant>.gpkg              corrected polygon asset
      <prefix>_bugnet_class_img_<target>.tif        predicted
      <prefix>_fitted_img_<first>_<last>.tif        fitted_img_p (years from its bands)
      <prefix>_classed_img_<target>.tif             rasterize_classes
      <prefix>_forest_mask_<target>.tif             forestMaskName
      <prefix>_parameters_<variant>.csv             parameter_file
      validation/<prefix>_validation_*, <prefix>_gee_asset_metadata.json

where <prefix> = Bugnet_<Name>_v<target>-<version> and <variant> =
mag<TCW threshold>_<mmu>mmu. Asset names come from the config and must match
the names the run recorded in its parameter-file asset.

Steps, in order. Each checks its own output and exits non-zero if a check
fails; files are built in the work directory and moved into the staging
folder only after their checks pass.
  plan        print sources, outputs and checks of the inputs; writes nothing
  polygons    GeoPackage from <bnet_buffered_polygons>_corrected, plus checks
              against Earth Engine and against the original asset
  parameters  one-row CSV of the parameter-file asset, re-read and compared
  rasters     download (resumable) and validate the four rasters
  align       area-weighted check of the polygons against the class raster
  readme      region README (and year README entry) from the delivered files,
              the parameter file, the validation reports and a notes file
  check       final check of the folder; prints the rclone commands to
              upload it (it does not run them)
  all         polygons through check, stopping at the first failure

Nothing is overwritten: a step whose outputs all exist is skipped, and one
with only some of them refuses to run. Nothing is uploaded and no cache is
deleted.

The notes file (default <work>/readme_notes.ini) holds the text that needs a
person: [readme] keys contact, region, class_summary, class_notes. Missing
keys become [[REVIEW: ...]] markers, and `check` fails while any remain.

Usage (from the repo root, with the run config used for the run):
  python tools/build_deliverable.py CONFIG.py --name North_Cascades STEP
      [--staging DIR] [--work DIR] [--notes FILE]
"""
import argparse
import configparser
import csv
import datetime
import inspect
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import ee
import numpy as np

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO / "bugnet"))
sys.path.insert(0, str(TOOLS))

import bnet  # noqa: E402
import correct_polygon_schema as cps  # noqa: E402
import deliverable_readme as text  # noqa: E402
import postprocess_utils as pu  # noqa: E402
from cli_utils import compute_project, load_parameters  # noqa: E402

DEFAULT_STAGING = "/vol/v1/Bugnet/deliverables/box_staging"
DEFAULT_WORK_ROOT = "/vol/v1/Bugnet/deliverables/work"
BOX_ROOT = "osu_box:Bugnet Products"
RCLONE = "~/.local/bin/rclone"
LCMS_YEAR = 2024  # bnet.lcms_forest_mask's hardcoded LCMS end year (modeling_utils.create_forest_mask)

POLYGON_FIELDS = [
    "ACRES", "buffered_acres", "unbuffered_acres", "pct_affected", "bnet_label", "SURVEY_YEAR",
    "REGION_ID", "US_AREA", "CREATED_DATE", "MODIFIED_DATE", "FEATURE_USER_ID", "DAMAGE_TYPE",
    "DAMAGE_TYPE_CODE", "DCA", "DCA_CODE", "HOST", "HOST_CODE", "HOST_GROUP", "HOST_GROUP_CODE", "NOTES",
]
INTEGER_FIELDS = ["bnet_label", "SURVEY_YEAR", "REGION_ID", "DAMAGE_TYPE_CODE", "DCA_CODE", "HOST_CODE",
                  "HOST_GROUP_CODE"]
NAME_KEYS = ["assetDir", "fitted_img_p", "predicted", "rasterize_classes", "forestMaskName",
             "bnet_polygonized", "bnet_buffered_polygons", "parameter_file"]
# Report order matches the North Cascades validation_rasters.txt.
RASTERS = {
    "classed": {"key": "rasterize_classes", "product": "classed_img_{target}", "dtype": "uint8",
                "nodata": 255, "block": 1024, "label": "classed image"},
    "forest_mask": {"key": "forestMaskName", "product": "forest_mask_{target}", "dtype": "uint8",
                    "nodata": 255, "block": 1024, "label": "forest mask"},
    "bugnet_class": {"key": "predicted", "product": "bugnet_class_img_{target}", "dtype": "uint8",
                     "nodata": 255, "block": 1024, "label": "class raster"},
    "fitted": {"key": "fitted_img_p", "product": "fitted_img_{first}_{last}", "dtype": "int16",
               "nodata": -32768, "block": 512, "label": "fitted image"},
}
REPORTS = {
    "vs_original": ("validation_vs_original_asset", "json"),
    "metadata": ("gee_asset_metadata", "json"),
    "gpkg_checks": ("validation_gpkg_checks", "txt"),
    "rasters": ("validation_rasters", "txt"),
    "alignment": ("validation_alignment", "json"),
}
BAND_RE = re.compile(r"^([A-Z]{3})_ftv_(\d{4})$")


class StepFailed(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def committed_revision(*paths):
    """Short hash of the last commit touching paths, or None if they have local changes."""
    if git("status", "--porcelain", "--", *paths):
        return None
    return git("log", "-1", "--format=%h", "--", *paths) or None


def is_pushed(rev):
    return bool(git("branch", "-r", "--contains", rev))


def repo_url():
    url = git("remote", "get-url", "origin")
    m = re.match(r"git@([^:]+):(.+?)(\.git)?$", url)
    return f"https://{m.group(1)}/{m.group(2)}" if m else url.removesuffix(".git")


def require(failed, ok, message):
    if not ok:
        failed.append(message)
    return ok


def finish(step, failed):
    if failed:
        print(f"{step}: FAILED")
        for f in failed:
            print(f"  - {f}")
        raise StepFailed(step)
    print(f"{step}: all checks passed")


def deliver(src, dst):
    if dst.exists():
        raise StepFailed(f"{dst} already exists; not overwriting")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    print(f"  -> {dst}")


def outputs_state(*paths):
    present = [p for p in paths if p.exists()]
    if len(present) == len(paths):
        return "done"
    if present:
        raise StepFailed("some outputs already exist; resolve by hand before rerunning: "
                         + ", ".join(str(p) for p in present))
    return "todo"


def rel(a, b):
    return abs(a / b - 1) if b else abs(a - b)


def wgs84_row_areas(transform, height):
    """Exact WGS84-ellipsoid area (m2) of one pixel in each row of an EPSG:4326 grid."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    e = math.sqrt(e2)

    def q(lat_deg):
        s = np.sin(np.radians(lat_deg))
        return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * np.log((1 - e * s) / (1 + e * s)))

    top = transform.f + np.arange(height) * transform.e
    return a * a / 2 * math.radians(transform.a) * np.abs(q(top) - q(top + transform.e))


def pixel_sides_m(lat, deg):
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    s2 = math.sin(math.radians(lat)) ** 2
    meridional = a * (1 - e2) / (1 - e2 * s2) ** 1.5
    normal = a / math.sqrt(1 - e2 * s2)
    return meridional * math.radians(deg), normal * math.cos(math.radians(lat)) * math.radians(deg)


def same_grid(grids, tol_px=1e-6):
    """True if (crs, transform, width, height) tuples describe one grid to within tol_px pixel.

    Earth Engine assets of one run can store the pixel size with a 1-ulp
    difference (e.g. 0.0002694945852358564 vs ...3585647), so exact equality
    is too strict; this compares where the grids put their pixels.
    """
    grids = list(grids)
    crs0, t0, w0, h0 = grids[0]
    for crs, t, w, h in grids[1:]:
        if (crs, w, h) != (crs0, w0, h0):
            return False
        a, b, c, d, e, f = t[:6]
        a0, b0, c0, d0, e0, f0 = t0[:6]
        drift = max(abs(a - a0) * w + abs(b - b0) * h + abs(c - c0),
                    abs(d - d0) * w + abs(e - e0) * h + abs(f - f0))
        if drift > tol_px * min(abs(a0), abs(e0)):
            return False
    return True


def fitted_years(band_names):
    """Indices (in band order) and the year list of a fitted image; raises if irregular."""
    by_index = {}
    for b in band_names:
        m = BAND_RE.match(b)
        if not m:
            raise StepFailed(f"unexpected fitted band name {b!r}")
        by_index.setdefault(m.group(1), []).append(int(m.group(2)))
    years = list(by_index.values())[0]
    if any(y != years for y in by_index.values()) or years != list(range(years[0], years[-1] + 1)):
        raise StepFailed(f"fitted bands are not the same contiguous years for every index: {by_index}")
    return list(by_index), years


def bit_depth(data_type):
    lo, hi = data_type.get("min"), data_type.get("max")
    if data_type.get("precision") != "int" or lo is None or hi is None:
        return 64
    return math.ceil(math.log2(hi - lo + 1))


# --------------------------------------------------------------------------- region

class Region:
    def __init__(self, config, name, staging, work, notes):
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*", name):
            raise SystemExit(f"--name {name!r}: use words joined by underscores, e.g. North_Cascades")
        self.config = config
        self.options = {"staging": None if staging == DEFAULT_STAGING else staging, "work": work, "notes": notes}
        self.param = p = load_parameters(config)
        ee.Initialize(project=compute_project(p))
        self.name = name
        self.target = int(p["target"])
        self.version = str(p["version"])
        self.tag = f"v{self.target}-{self.version}"
        self.prefix = f"Bugnet_{name}_{self.tag}"
        self.variant = f"mag{p['decline_thresholds']['tcw']}_{p['bnet_polygon_mmu']}mmu"
        self.region_id = pu.usfs_region_id(p)
        self.us_area = pu.us_area(p)
        year_rel = f"Bugnet_Region_{self.region_id}/Data/{self.target}"
        self.year_dir = Path(staging) / year_rel
        self.dir = self.year_dir / self.prefix
        self.box_year_dir = f"{BOX_ROOT}/{year_rel}"
        self.box_dir = f"{self.box_year_dir}/{self.prefix}"
        short = p["project_name"].removesuffix("-bugnet")
        self.work = Path(work) if work else Path(DEFAULT_WORK_ROOT) / f"{short}-{self.target}-v{self.version}"
        self.notes_path = Path(notes) if notes else self.work / "readme_notes.ini"
        self._run = None
        self._bands = {}

    # Earth Engine sources
    def asset(self, key):
        return self.param["assetDir"] + self.param[key]

    @property
    def run_feature(self):
        if self._run is None:
            info = ee.FeatureCollection(self.asset("parameter_file")).getInfo()
            if len(info["features"]) != 1:
                raise StepFailed(f"parameter file has {len(info['features'])} features, expected 1")
            self._run = info["features"][0]
        return self._run

    @property
    def run(self):
        return self.run_feature["properties"]

    def check_names(self):
        bad = [f"{k}: config {self.param[k]!r} vs run {self.run.get(k)!r}"
               for k in NAME_KEYS if str(self.param[k]) != str(self.run.get(k))]
        if bad:
            raise StepFailed("the config's asset names differ from those the run recorded "
                             "(was the config edited, or is it a different year?): " + "; ".join(bad))

    def band_names(self, key):
        if key not in self._bands:
            from download_ee_raster import asset_grid
            self._bands[key] = asset_grid(self.asset(RASTERS[key]["key"]))
        return self._bands[key][4]

    # Output names
    def file_name(self, what):
        if what == "polygons":
            return f"{self.prefix}_polygons_{self.variant}.gpkg"
        if what == "parameters":
            return f"{self.prefix}_parameters_{self.variant}.csv"
        spec = RASTERS[what]
        first = last = None
        if what == "fitted":
            _, years = fitted_years(self.band_names("fitted"))
            first, last = years[0], years[-1]
        return f"{self.prefix}_{spec['product'].format(target=self.target, first=first, last=last)}.tif"

    def path(self, what):
        return self.dir / self.file_name(what)

    def report(self, what):
        stem, ext = REPORTS[what]
        return self.dir / "validation" / f"{self.prefix}_{stem}.{ext}"

    def facts_path(self, step):
        return self.work / f"{step}_facts.json"

    def facts(self, step):
        path = self.facts_path(step)
        if not path.exists():
            raise StepFailed(f"{path} is missing; run the {step} step first")
        return json.loads(path.read_text())

    def write_work(self, name, content):
        self.work.mkdir(parents=True, exist_ok=True)
        path = self.work / name
        path.write_text(content)
        return path


# --------------------------------------------------------------------------- plan

def step_plan(R):
    p = R.param
    print(f"Region            {R.name.replace('_', ' ')}  (config project {p['project_name']}, "
          f"{R.us_area}, USFS region {R.region_id})")
    print(f"Staging folder    {R.dir}")
    print(f"Box folder        {R.box_dir}")
    print(f"Work folder       {R.work}  (downloads, block caches, facts)")
    print(f"Notes file        {R.notes_path}  ({'present' if R.notes_path.exists() else 'MISSING'})")
    failed = []
    R.check_names()
    print("Config asset names match the run's parameter file.")
    src, dst = cps.asset_ids(p)
    try:
        props = ee.data.getAsset(dst).get("properties", {})
        tool = props.get("correction_tool", "")
        require(failed, tool and "uncommitted" not in tool,
                f"{dst} is not annotated from a commit ({tool!r}); run correct_polygon_schema.py annotate")
        print(f"Corrected polygons {dst}\n                  correction_tool: {tool or '(none)'}")
    except ee.EEException:
        failed.append(f"{dst} does not exist; run correct_polygon_schema.py submit/validate/annotate first")
    print("\nOutputs:")
    print(f"  {R.file_name('polygons'):<64} <- {dst.rsplit('/', 1)[-1]}")
    for key, spec in RASTERS.items():
        name = R.file_name(key)
        R.band_names(key)
        crs, t, w, h, bands = R._bands[key]
        mb = w * h * len(bands) * np.dtype(spec["dtype"]).itemsize / 1e6
        print(f"  {name:<64} <- {p[spec['key']]}  ({len(bands)} bands, {w}x{h}, {crs}, "
              f"{spec['dtype']}, ~{mb:,.0f} MB uncompressed)")
    print(f"  {R.file_name('parameters'):<64} <- {p['parameter_file']}")
    for what in REPORTS:
        print(f"  validation/{R.report(what).name}")
    print("  README.txt  (and an entry in the year README)")
    existing = [w for w in ["polygons", "parameters", *RASTERS] if R.path(w).exists()]
    print(f"\nAlready staged: {', '.join(existing) if existing else 'nothing'}")
    args = f"{R.config} --name {R.name}" + "".join(f" --{k} {v}" for k, v in R.options.items() if v)
    print("\nCommands:")
    for step in ["polygons", "parameters", "rasters", "align", "readme", "check"]:
        print(f"  python tools/build_deliverable.py {args} {step}")
    finish("plan", failed)


# --------------------------------------------------------------------------- polygons

def vs_original_failures(report):
    failed = []
    n = report["n_after"]
    require(failed, report["n_before"] == n == report["n_paired"] == report["n_with_exactly_one_partner"]
            == report["same_geometry"], "polygon counts / one-to-one pairing / identical geometries")
    bad = {k: v for k, v in report["unchanged_fields_matching"].items() if v != n}
    require(failed, not bad, f"unchanged fields differ from the original: {bad}")
    require(failed, report["n_pct_gt_100_after"] == 0, "pct_affected > 100 after correction")
    require(failed, report["n_bnet_label_null"] == 0, "null bnet_label")
    require(failed, report["n_no_unbuffered_match_after"] == 0, "polygons with no unbuffered patch")
    require(failed, report["ACRES_equals_buffered_acres_after"] == n, "ACRES != buffered_acres")
    require(failed, rel(report["sum_unbuffered_acres_after"], report["sum_unbuffered_polygon_acres_direct"]) < 1e-6,
            "sum of unbuffered_acres differs from the unbuffered polygons' own area")
    return failed


def step_polygons(R):
    R.check_names()
    gpkg = R.path("polygons")
    outs = [gpkg, R.report("vs_original"), R.report("metadata"), R.report("gpkg_checks")]
    if outputs_state(*outs) == "done":
        print(f"polygons: already staged ({gpkg.name}); skipping")
        return
    import geopandas as gpd
    import pyogrio

    src, dst = cps.asset_ids(R.param)
    meta = ee.data.getAsset(dst)
    tool = meta.get("properties", {}).get("correction_tool", "")
    if not tool or "uncommitted" in tool:
        finish("polygons", [f"{dst} is not annotated from a commit ({tool!r}); "
                            "run correct_polygon_schema.py annotate from a clean checkout"])
    fc = ee.FeatureCollection(dst)
    gdf = ee.data.computeFeatures({"expression": fc, "fileFormat": "GEOPANDAS_GEODATAFRAME"}).set_crs("EPSG:4326")
    fields = set(gdf.columns) - {"geometry"}
    if fields != set(POLYGON_FIELDS):
        finish("polygons", [f"fields differ from the IDS list: extra {sorted(fields - set(POLYGON_FIELDS))}, "
                            f"missing {sorted(set(POLYGON_FIELDS) - fields)}"])
    failed = []
    for f in INTEGER_FIELDS:
        col = gdf[f].astype(float)
        if require(failed, bool((col == col.round()).all()), f"{f} has non-integer values"):
            gdf[f] = col.astype("int64")
    layer = gpkg.stem
    tmp = R.work / gpkg.name
    R.work.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()  # an earlier, unvalidated attempt of this step
    gdf[POLYGON_FIELDS + ["geometry"]].to_file(tmp, layer=layer, driver="GPKG")

    g = gpd.read_file(tmp, layer=layer)
    ref = ee.Dictionary({
        "n": fc.size(), "ACRES": fc.aggregate_sum("ACRES"), "unb": fc.aggregate_sum("unbuffered_acres"),
        "buf": fc.aggregate_sum("buffered_acres"), "pct": fc.aggregate_mean("pct_affected"),
        "label": fc.aggregate_histogram("bnet_label"), "props": fc.first().propertyNames(),
    }).getInfo()
    crs = pu.EQUAL_AREA_CRS[R.us_area]
    acres_local = g.to_crs(crs).area * pu.ACRES_PER_SQ_M
    acres_rel = float((acres_local / g.ACRES - 1).abs().max())
    pct_diff = float((g.unbuffered_acres / g.buffered_acres * 100 - g.pct_affected).abs().max())
    labels = {int(k): int(v) for k, v in g.bnet_label.value_counts().sort_index().items()}
    ee_labels = {int(float(k)): int(v) for k, v in ref["label"].items()}
    cols = sorted(set(g.columns) - {"geometry"})
    layers = [lyr[0] for lyr in pyogrio.list_layers(tmp)]
    geom_types = g.geom_type.value_counts().to_dict()
    bad_geoms = (int((~g.is_valid).sum()), int(g.is_empty.sum()), int(g.geometry.isna().sum()))
    nulls = int(g[cols].isna().sum().sum())
    one = lambda col: g[col].value_counts().to_dict()
    user_id = R.param.get("feature_user_id", pu.DEFAULT_FEATURE_USER_ID)
    n = len(g)

    require(failed, layers == [layer], f"layers {layers}")
    require(failed, n == ref["n"], f"{n} features vs {ref['n']} in Earth Engine")
    require(failed, set(geom_types) <= {"Polygon", "MultiPolygon"}, f"geometry types {geom_types}")
    require(failed, bad_geoms == (0, 0, 0), f"invalid/empty/null geometries {bad_geoms}")
    require(failed, sorted(set(ref["props"]) - {"system:index"}) == cols, "attributes differ from Earth Engine")
    require(failed, nulls == 0, f"{nulls} null attribute values")
    for col, key in (("ACRES", "ACRES"), ("buffered_acres", "buf"), ("unbuffered_acres", "unb")):
        require(failed, rel(g[col].sum(), ref[key]) < 1e-9, f"sum of {col} differs from Earth Engine")
    require(failed, abs(g.pct_affected.mean() - ref["pct"]) < 1e-6, "mean pct_affected differs from Earth Engine")
    require(failed, acres_rel < 1e-5, f"ACRES vs local {crs} area: max relative difference {acres_rel:.2e}")
    require(failed, pct_diff < 1e-6, f"pct_affected inconsistent with the acreages ({pct_diff:.2e})")
    require(failed, labels == ee_labels, f"bnet_label counts {labels} vs Earth Engine {ee_labels}")
    require(failed, one("REGION_ID") == {R.region_id: n}, f"REGION_ID {one('REGION_ID')}")
    require(failed, one("US_AREA") == {R.us_area: n}, f"US_AREA {one('US_AREA')}")
    require(failed, one("FEATURE_USER_ID") == {user_id: n}, f"FEATURE_USER_ID {one('FEATURE_USER_ID')}")
    require(failed, len(one("CREATED_DATE")) == 1 and len(one("MODIFIED_DATE")) == 1, "dates are not uniform")
    require(failed, g.pct_affected.min() > 0 and g.pct_affected.max() <= 100, "pct_affected outside (0, 100]")

    vs = cps.validation_report(R.param)
    failed += [f"vs original asset: {f}" for f in vs_original_failures(vs)]

    lines = [
        f"GeoPackage checks: {gpkg.name}  (layer {layer})",
        f"Checked {datetime.date.today().isoformat()} against Earth Engine asset {dst}", "",
        f"Layers in file:            {layers}",
        f"Features:                  {n}  (Earth Engine: {ref['n']})",
        f"CRS:                       {g.crs.to_string()}",
        f"Geometry types:            {geom_types}",
        f"Invalid / empty / null:    {bad_geoms[0]} / {bad_geoms[1]} / {bad_geoms[2]}",
        f"Attributes match EE:       {sorted(set(ref['props']) - {'system:index'}) == cols}  ({len(cols)} fields)",
        f"Null attribute values:     {nulls}",
        f"Sum ACRES:                 {g.ACRES.sum():.3f}  (EE {ref['ACRES']:.3f})",
        f"Sum buffered_acres:        {g.buffered_acres.sum():.3f}  (EE {ref['buf']:.3f})",
        f"Sum unbuffered_acres:      {g.unbuffered_acres.sum():.3f}  (EE {ref['unb']:.3f})",
        f"Mean pct_affected:         {g.pct_affected.mean():.4f}  (EE {ref['pct']:.4f})",
        f"ACRES vs area recomputed locally from geometry in {crs}: max relative difference {acres_rel:.2e}",
        f"pct_affected vs unbuffered/buffered*100: max abs difference {pct_diff:.2e}",
        f"bnet_label counts:         {labels}  (EE {ref['label']})",
        f"REGION_ID / US_AREA:       {one('REGION_ID')} / {one('US_AREA')}",
        f"FEATURE_USER_ID:           {one('FEATURE_USER_ID')}",
        f"CREATED_DATE / MODIFIED_DATE: {one('CREATED_DATE')} / {one('MODIFIED_DATE')}",
        f"pct_affected range:        {g.pct_affected.min():.2f} - {g.pct_affected.max():.2f}",
        f"Result:                    {'FAIL: ' + '; '.join(failed) if failed else 'PASS'}",
    ]
    reports = {
        "gpkg_checks": R.write_work(R.report("gpkg_checks").name, "\n".join(lines) + "\n"),
        "vs_original": R.write_work(R.report("vs_original").name,
                                    json.dumps(vs, indent=2, sort_keys=True, default=str) + "\n"),
        "metadata": R.write_work(R.report("metadata").name, json.dumps(meta, indent=2) + "\n"),
    }
    print("\n".join(lines))
    finish("polygons", failed)
    R.facts_path("polygons").write_text(json.dumps({
        "n": n, "layer": layer, "acres_max_rel_diff": acres_rel,
        "pct_range": [float(g.pct_affected.min()), float(g.pct_affected.max())],
        "created_date": next(iter(one("CREATED_DATE"))), "modified_date": next(iter(one("MODIFIED_DATE"))),
        "feature_user_id": user_id, "correction_tool": tool,
        "correction_date": meta["properties"].get("correction_date"),
    }, indent=2))
    deliver(tmp, gpkg)
    for what, path in reports.items():
        deliver(path, R.report(what))


# --------------------------------------------------------------------------- parameters

def step_parameters(R):
    R.check_names()
    out = R.path("parameters")
    if outputs_state(out) == "done":
        print(f"parameters: already staged ({out.name}); skipping")
        return
    feature = R.run_feature
    props = feature["properties"]
    geom = feature.get("geometry")
    cols = ["system:index"] + sorted(props) + [".geo"]
    row = {**props, "system:index": feature["id"],
           ".geo": json.dumps(geom, separators=(",", ":")) if geom else ""}
    R.work.mkdir(parents=True, exist_ok=True)
    tmp = R.work / out.name
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow({k: row[k] for k in cols})

    failed = []
    with open(tmp, newline="") as fh:
        back = list(csv.DictReader(fh))
    require(failed, len(back) == 1, f"{len(back)} rows re-read")
    bad = [k for k in props if str(props[k]) != back[0][k]]
    require(failed, not bad, f"values changed on re-read: {bad[:5]}")
    require(failed, list(back[0]) == cols, "column order changed on re-read")
    if geom and geom["type"] == "Point":
        inside = ee.Image(R.asset("rasterize_classes")).geometry().contains(ee.Geometry(geom), 1).getInfo()
        geo_text = "a point inside the region" if inside else "a point (outside the region's footprint)"
    else:
        geo_text = f"the table's {geom['type']} geometry" if geom else "empty (the table has no geometry)"
    print(f"{len(cols)} columns | system:index {feature['id']} | .geo {geo_text}")
    finish("parameters", failed)
    R.facts_path("parameters").write_text(json.dumps({"n_columns": len(cols), "geo_text": geo_text}, indent=2))
    deliver(tmp, out)


# --------------------------------------------------------------------------- rasters

def raster_failures(r, spec):
    g, px, counts = r["grid"], r["pixel_check"], r["valid_pixel_counts"]
    failed = []
    require(failed, g["crs_file"] == g["crs_asset"] and g["pixel_size_matches"] and g["origin_on_asset_grid"]
            and g["origin_offset_from_asset_px"] == [0, 0] and g["size_file"] == g["size_asset"], f"grid {g}")
    require(failed, r["dtype"] == spec["dtype"] and r["nodata"] == spec["nodata"], "dtype/nodata")
    require(failed, r["band_descriptions_match_asset"], "band names differ from the asset")
    require(failed, px["mismatching_points"] == 0, f"{px['mismatching_points']} pixel mismatches: {px['examples']}")
    require(failed, counts["bands_equal"] == counts["bands"], f"valid-pixel counts differ (max {counts['max_abs_difference']})")
    return [f"{r['file']}: {f}" for f in failed]


def step_rasters(R):
    import rasterio

    R.check_names()
    finals = {k: R.path(k) for k in RASTERS}
    if outputs_state(R.report("rasters"), *finals.values()) == "done":
        print("rasters: already staged; skipping")
        return
    tools_rev = committed_revision("tools/download_ee_raster.py", "tools/validate_ee_raster.py")
    if not tools_rev:
        raise StepFailed("tools/download_ee_raster.py or validate_ee_raster.py has local changes; commit first")
    R.work.mkdir(parents=True, exist_ok=True)
    results_path = R.work / "rasters_validation.jsonl"
    results = {}
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            r = json.loads(line)
            results[r["file"]] = r

    local = {}
    for key, spec in RASTERS.items():
        asset, tif = R.asset(spec["key"]), R.work / finals[key].name
        local[key] = tif
        if not tif.exists():
            print(f"== download {asset} -> {tif}", flush=True)
            rc = subprocess.run([sys.executable, str(TOOLS / "download_ee_raster.py"), asset, str(tif),
                                 "--dtype", spec["dtype"], "--nodata", str(spec["nodata"]),
                                 "--block", str(spec["block"]), "--workers", "4",
                                 "--project", compute_project(R.param)]).returncode
            if rc:
                raise StepFailed(f"download of {asset} stopped (exit {rc}); rerun to resume")
        if tif.name not in results:
            print(f"== validate {tif.name}", flush=True)
            out = subprocess.run([sys.executable, str(TOOLS / "validate_ee_raster.py"), asset, str(tif),
                                  "--points", "1000", "--counts", "--project", compute_project(R.param)],
                                 capture_output=True, text=True)
            if out.returncode:
                raise StepFailed(f"validate_ee_raster failed for {tif.name}:\n{out.stderr[-2000:]}")
            r = json.loads(out.stdout[out.stdout.index("{"):])
            results[tif.name] = r
            with open(results_path, "a") as fh:
                fh.write(json.dumps(r) + "\n")

    failed = []
    for key, spec in RASTERS.items():
        failed += raster_failures(results[local[key].name], spec)

    # Footprints and values, read from the files themselves.
    arrays, grids, descriptions = {}, [], {}
    for key, tif in local.items():
        with rasterio.open(tif) as ds:
            grids.append((ds.crs.to_string(), tuple(ds.transform), ds.width, ds.height))
            arrays[key] = ds.read(1)
            descriptions[key] = list(ds.descriptions)
    require(failed, same_grid(grids), f"rasters are not on one grid: {grids}")
    valid = {k: arrays[k] != RASTERS[k]["nodata"] for k in arrays}
    values = {k: sorted(int(v) for v in np.unique(arrays[k][valid[k]])) for k in ("classed", "forest_mask", "bugnet_class")}
    k = int(R.param["num_of_clusters"])
    require(failed, set(values["classed"]) <= {c for c, _ in text.CLASSED_CODES}, f"classed values {values['classed']}")
    require(failed, set(values["forest_mask"]) <= {0, 1}, f"forest mask values {values['forest_mask']}")
    require(failed, set(values["bugnet_class"]) <= set(range(k)), f"class raster values {values['bugnet_class']}")
    nest = {
        "fitted valid outside region": int((valid["fitted"] & ~valid["classed"]).sum()),
        "forest mask valid where fitted NoData": int((valid["forest_mask"] & ~valid["fitted"]).sum()),
        "class pixels outside forest mask": int((valid["bugnet_class"] & (arrays["forest_mask"] != 1)).sum()),
    }
    require(failed, not any(nest.values()), f"footprints do not nest: {nest}")
    counts = {key: int(valid[key].sum()) for key in RASTERS}

    lines = [f"Raster checks: {datetime.date.today().isoformat()}",
             "Each GeoTIFF compared with its Earth Engine asset (tools/validate_ee_raster.py).",
             "Pixel values were read from Earth Engine with reduceRegions at pixel centres,",
             "a separate path from the download (computePixels).", ""]
    for key in RASTERS:
        r = results[local[key].name]
        g, px, c = r["grid"], r["pixel_check"], r["valid_pixel_counts"]
        lines += [r["file"], f"  source asset:        {r['asset']}",
                  f"  CRS:                 {g['crs_file']} (asset {g['crs_asset']})",
                  f"  pixel size matches:  {g['pixel_size_matches']}",
                  f"  origin on asset grid:{' ' if g['origin_on_asset_grid'] else ''}{g['origin_on_asset_grid']} "
                  f"(offset {g['origin_offset_from_asset_px']} px)",
                  f"  size:                {g['size_file']} (asset {g['size_asset']})",
                  f"  data type / NoData:  {r['dtype']} / {r['nodata']:g}   compression: {r['compression']}",
                  f"  bands:               {r['band_count']}, names match asset: {r['band_descriptions_match_asset']}",
                  f"  pixel values:        {px['mismatching_points']} mismatching of {px['points']} random pixels "
                  f"({px['values_compared']} values; {px['masked_in_ee']} masked in EE)",
                  f"  valid-pixel counts:  {c['bands_equal']}/{c['bands']} bands equal to EE "
                  f"(max difference {c['max_abs_difference']}); band 1 {c['first_bands'][0][1]:,}", ""]
    lines += ["Footprints (valid pixels):",
              f"  region (classed image) {counts['classed']:,} >= fitted image {counts['fitted']:,} >= "
              f"forest mask {counts['forest_mask']:,} >= class raster {counts['bugnet_class']:,}",
              "  " + "; ".join(f"{k}: {v}" for k, v in nest.items()),
              f"Values: classed image {values['classed']}; forest mask {values['forest_mask']}; "
              f"class raster {values['bugnet_class']}",
              f"Result: {'FAIL: ' + '; '.join(failed) if failed else 'PASS'}"]
    report = R.write_work(R.report("rasters").name, "\n".join(lines) + "\n")
    print("\n".join(lines))
    finish("rasters", failed)

    classed_type = ee.Image(R.asset("rasterize_classes")).getInfo()["bands"][0]["data_type"]
    rs = [results[local[k].name] for k in RASTERS]
    R.facts_path("rasters").write_text(json.dumps({
        "export_date": datetime.date.today().isoformat(), "tools_revision": tools_rev,
        "valid_counts": counts, "band_names": {k: descriptions[k] for k in RASTERS},
        "points": rs[0]["pixel_check"]["points"],
        "values_compared": sum(r["pixel_check"]["values_compared"] for r in rs),
        "mismatches": sum(r["pixel_check"]["mismatching_points"] for r in rs),
        "bands": sum(r["band_count"] for r in rs),
        "classed_asset_bits": bit_depth(classed_type),
    }, indent=2))
    for key in RASTERS:
        deliver(local[key], finals[key])
    deliver(report, R.report("rasters"))


# --------------------------------------------------------------------------- align

def alignment_failures(r):
    failed = []
    per, lab = r["per_polygon_rel_diff"], r["bnet_label_equals_raster_mode"]
    require(failed, rel(r["unbuffered_pixels_also_in_class_raster"], r["unbuffered_pixel_count_sum_from_asset"]) < 1e-3,
            "rasterized detection pixels differ from the pixel count recorded in Earth Engine by > 0.1%")
    require(failed, rel(r["unbuffered_pixels_label_equals_class"], r["unbuffered_pixels_also_in_class_raster"]) < 1e-3,
            "detection pixels whose class differs from their patch label > 0.1%")
    require(failed, r["detection_pixels_outside_all_polygons"] == 0, "detection pixels outside every polygon")
    require(failed, abs(r["detection_area_raster_vs_gpkg_rel_diff"]) < 1e-3, "detected area differs by > 0.1%")
    require(failed, per["n_within_1pct"] >= 0.99 * per["n"], "fewer than 99% of polygons agree within 1%")
    require(failed, lab["equal"] >= 0.99 * lab["n"], "bnet_label matches the raster mode in < 99% of polygons")
    return failed


def alignment_report(class_tif, gpkg, layer, unbuffered, k):
    """Area-weighted alignment of delivered polygons and their unbuffered patches with the class raster."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    buf = gpd.read_file(gpkg, layer=layer)
    with rasterio.open(class_tif) as ds:
        if ds.crs.to_string() != "EPSG:4326":
            raise StepFailed(f"{class_tif} is not EPSG:4326; the exact-area pixel model assumes it")
        cls, T, nod = ds.read(1), ds.transform, ds.nodata
    H, W = cls.shape
    area = np.broadcast_to(wgs84_row_areas(T, H)[:, None] * pu.ACRES_PER_SQ_M, (H, W))
    valid = cls != nod
    unb_lab = rasterize(((g, int(lab) + 1) for g, lab in zip(unbuffered.geometry, unbuffered["label"])),
                        out_shape=(H, W), transform=T, fill=0, dtype="uint8")
    in_unb = unb_lab > 0
    buf_id = rasterize(((g, i + 1) for i, g in enumerate(buf.geometry)), out_shape=(H, W), transform=T,
                       fill=0, dtype="int32")
    det = in_unb & valid
    r = {
        "class_pixels_total": int(valid.sum()),
        "class_area_acres_total": float(area[valid].sum()),
        "unbuffered_detection_pixels": int(in_unb.sum()),
        "unbuffered_pixels_also_in_class_raster": int(det.sum()),
        "unbuffered_pixels_label_equals_class": int((det & (unb_lab.astype(int) - 1 == cls)).sum()),
        "unbuffered_pixel_count_sum_from_asset": int(unbuffered["count"].sum()),
        "class_pixels_not_in_any_detection": int((valid & ~in_unb).sum()),
        "detection_area_acres_from_raster": float(area[det].sum()),
        "sum_unbuffered_acres_in_gpkg": float(buf.unbuffered_acres.sum()),
    }
    r["detection_area_raster_vs_gpkg_rel_diff"] = r["detection_area_acres_from_raster"] / r["sum_unbuffered_acres_in_gpkg"] - 1
    per = np.bincount(buf_id[det], weights=area[det], minlength=len(buf) + 1)[1:]
    rd = per / buf.unbuffered_acres.values - 1
    r["per_polygon_rel_diff"] = {"median": float(np.median(rd)), "p95_abs": float(np.percentile(np.abs(rd), 95)),
                                 "max_abs": float(np.abs(rd).max()),
                                 "n_within_1pct": int((np.abs(rd) <= 0.01).sum()), "n": len(buf)}
    r["detection_pixels_outside_all_polygons"] = int((in_unb & (buf_id == 0)).sum())
    pa = np.bincount(buf_id.ravel(), weights=area.ravel(), minlength=len(buf) + 1)[1:]
    r["polygon_area_raster_vs_ACRES_total_rel_diff"] = float(pa.sum() / buf.ACRES.sum() - 1)
    m = valid & (buf_id > 0)
    counts = np.bincount(buf_id[m].astype(np.int64) * k + cls[m], minlength=(len(buf) + 1) * k).reshape(-1, k)[1:]
    r["bnet_label_equals_raster_mode"] = {"equal": int((counts.argmax(axis=1) == buf.bnet_label.values).sum()),
                                          "n": len(buf),
                                          "note": "raster mode by pixel centre; EE weights edge pixels by coverage"}
    return r


def step_align(R):
    R.check_names()
    out = R.report("alignment")
    if outputs_state(out) == "done":
        print("align: already staged; skipping")
        return
    for what in ("polygons", "bugnet_class"):
        if not R.path(what).exists():
            raise StepFailed(f"{R.path(what)} is missing; run the polygons and rasters steps first")
    unbuffered = ee.data.computeFeatures({"expression": ee.FeatureCollection(R.asset("bnet_polygonized")),
                                          "fileFormat": "GEOPANDAS_GEODATAFRAME"}).set_crs("EPSG:4326")
    r = alignment_report(R.path("bugnet_class"), R.path("polygons"), R.path("polygons").stem, unbuffered,
                         int(R.param["num_of_clusters"]))
    failed = alignment_failures(r)
    report = R.write_work(out.name, json.dumps(r, indent=2) + "\n")
    print(json.dumps(r, indent=2))
    finish("align", failed)
    deliver(report, out)


# --------------------------------------------------------------------------- readme

def read_notes(path):
    notes = {}
    if path.exists():
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(path)
        if cp.has_section("readme"):
            notes = {k: re.sub(r"\s+", " ", v).strip() for k, v in cp["readme"].items()}
    for key in ("contact", "region", "class_summary", "class_notes"):
        notes.setdefault(key, text.review(f"'{key}' missing from {path}"))
    return notes


def raster_stats(R, k, class_years, target):
    """Pixel geometry, class means and fitted-value ranges, computed from the delivered files."""
    import rasterio

    with rasterio.open(R.path("bugnet_class")) as ds:
        cls, T = ds.read(1), ds.transform
        valid = cls != ds.nodata
    rows = np.nonzero(valid)[0]
    row_area = wgs84_row_areas(T, cls.shape[0])
    mean_area = float(row_area[rows].mean())
    lat = float((T.f + (rows + 0.5) * T.e).mean())
    ns, ew = pixel_sides_m(lat, T.a)
    out = {"grid_width": cls.shape[1], "grid_height": cls.shape[0], "grid_origin": [T.c, T.f],
           "pixel_size_deg": T.a, "pixel_area_m2": int(5 * round(mean_area / 5)),
           "pixel_lat": round(lat * 2) / 2, "pixel_ns_m": round(ns), "pixel_ew_m": round(ew),
           "pixel_area_exact_m2": mean_area}
    with rasterio.open(R.path("fitted")) as ds:
        names = list(ds.descriptions)
        indices, years = fitted_years(names)
        means = {c: {} for c in range(k)}
        p5_p95, nbr_max = {}, None
        for idx in indices:
            pair = []
            for y in class_years:
                b = ds.read(names.index(f"{idx}_ftv_{y}") + 1)
                pair.append([float(b[valid & (cls == c)].mean()) for c in range(k)])
                if y == target:
                    v = b[b != ds.nodata]
                    p5_p95[idx] = [int(round(x)) for x in np.percentile(v, [5, 95])]
                    if idx == "NBR":
                        nbr_max = int(v.max())
            if class_years[1] != target:
                b = ds.read(names.index(f"{idx}_ftv_{target}") + 1)
                v = b[b != ds.nodata]
                p5_p95[idx] = [int(round(x)) for x in np.percentile(v, [5, 95])]
                nbr_max = int(v.max()) if idx == "NBR" else nbr_max
            for c in range(k):
                means[c][idx] = (pair[0][c], pair[1][c])
        out["fitted"] = {"indices": indices, "years": years, "first": years[0], "last": years[-1],
                         "n_bands": len(names), "last_band": names[-1], "p5_p95": p5_p95,
                         "nbr_max": nbr_max if nbr_max is not None else 0,
                         "uncompressed_gb": ds.width * ds.height * ds.count * 2 / 1e9}
    out["classes"] = [{"class": c, "pixels": int((cls == c).sum()), **means[c]} for c in range(k)]
    return out


def readme_facts(R):
    p = R.run
    poly, params, rast = R.facts("polygons"), R.facts("parameters"), R.facts("rasters")
    vs = json.loads(R.report("vs_original").read_text())
    align = json.loads(R.report("alignment").read_text())
    k = int(p["num_of_clusters"])
    target = R.target
    m = re.search(r"_(\d{4})_(\d{4})$", p["fitted_img_p"])
    asset_years = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    class_years = (asset_years[0] or target - int(p["agent_lookback"]), target)
    stats = raster_stats(R, k, class_years, target)
    start = datetime.date.fromisoformat(str(p["composite_params_start_date"]))
    end = datetime.date.fromisoformat(str(p["composite_params_end_date"]))
    git_keys = [key for key in p if "git" in key.lower() or "commit" in key.lower()]
    decline_fn = bnet.LTSD_decline_score if p.get("decline_path", "ltsd") == "ltsd" else bnet.SNIC_decline_image
    m = re.search(r"\((?:lt-bnet-py )?(.+)\)$", poly["correction_tool"])
    build_rev = committed_revision("tools/build_deliverable.py", "tools/deliverable_readme.py")
    if not build_rev:
        build_rev = text.review("tools/build_deliverable.py has uncommitted changes; commit, push and rerun")
    elif not is_pushed(build_rev):
        build_rev = text.review(f"commit {build_rev} is not pushed to GitHub yet")
    files = {w: R.file_name(w) for w in ["polygons", "parameters", *RASTERS]}
    notes = read_notes(R.notes_path)
    # composite_params_end_date is the date of the launch that wrote the parameter file; a resumed run
    # reuses composites built by an earlier launch, so the notes can give the real window.
    composite_window = notes.get("composite_window") or f"{start:%B} {start.day} - {end:%B} {end.day}"
    f = {
        **stats,
        "display": R.name.replace("_", " "), "prefix": R.prefix, "tag": R.tag, "target": target,
        "version": R.version, "variant": R.variant, "region_id": R.region_id, "us_area": R.us_area,
        "equal_area_crs": pu.EQUAL_AREA_CRS[R.us_area], "notes": notes, "run": p,
        "run_date": end.isoformat(), "correction_date": poly["correction_date"],
        "export_date": rast["export_date"], "files": files,
        "sizes": {name: (R.dir / name).stat().st_size for name in files.values()},
        "n_polygons": poly["n"], "layer": poly["layer"], "pct_range": poly["pct_range"],
        "created_date": poly["created_date"], "modified_date": poly["modified_date"],
        "feature_user_id": poly["feature_user_id"], "acres_max_rel_diff": poly["acres_max_rel_diff"],
        "parameters": params, "vs_original": vs, "alignment": align,
        "rasters": {key: rast[key] for key in ("points", "values_compared", "mismatches", "bands", "valid_counts")},
        "band_names": {key: rast["band_names"][key][0] for key in ("classed", "forest_mask", "bugnet_class")},
        "classed_asset_bits": rast["classed_asset_bits"],
        "mmu": int(p["bnet_polygon_mmu"]),
        "mmu_ha": (int(p["bnet_polygon_mmu"]) + 1) * stats["pixel_area_exact_m2"] / 1e4,
        "class_years": class_years,
        "sub_mmu_share": align["class_pixels_not_in_any_detection"] / align["class_pixels_total"],
        "jrc_share": rast["valid_counts"]["fitted"] / rast["valid_counts"]["classed"],
        "composite_window": composite_window,
        "profile": (p.get("run_manifest_historical_profile", "unrecorded"),
                    p.get("run_manifest_historical_profile_status", "unrecorded")),
        "pipeline_revision": ", ".join(f"{key} {p[key]}" for key in git_keys),
        "training_year": (re.findall(r"\d{4}", str(p["attributed_polygons_training"])) or ["?"])[-1],
        "fire_window": (p.get("run_manifest_fire_mask_window_start_year", target - int(p["agent_lookback"])),
                        p.get("run_manifest_fire_mask_window_end_year", target)),
        "lcms_year": LCMS_YEAR,
        "min_years_declining": inspect.signature(decline_fn).parameters["min_years_declining"].default,
        "asset_folder": p["assetDir"].rstrip("/").rsplit("/", 1)[-1],
        "code": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "url": repo_url(),
                 "correction": f"revision {m.group(1)}" if m else poly["correction_tool"],
                 "download": rast["tools_revision"], "build": build_rev},
    }
    f["fitted"]["asset_years"] = asset_years
    if p.get("platform", "LS") != "LS":
        f["notes"]["region"] += " " + text.review(f"platform {p['platform']!r}: README assumes Landsat")
    if p.get("run_manifest_exclusion_mode", "legacy_range") != "legacy_range" and not text.no_exclusion(p):
        f["notes"]["region"] += " " + text.review("exclusion_mode is not legacy_range; check section 9b")
    return f


def step_readme(R):
    R.check_names()
    out = R.dir / "README.txt"
    if outputs_state(out) == "done":
        print("readme: already staged; skipping")
        return
    missing = [str(p) for p in [*(R.path(w) for w in ["polygons", "parameters", *RASTERS]),
                                *(R.report(w) for w in REPORTS)] if not p.exists()]
    if missing:
        raise StepFailed("run the earlier steps first; missing: " + ", ".join(missing))
    f = readme_facts(R)
    readme = text.render_region(f)
    R.write_work("readme_facts.json", json.dumps(f, indent=2, default=str))
    out.write_text(readme)
    print(f"  wrote {out}")

    year = R.year_dir / "README.txt"
    if year.exists():
        old = year.read_text()
        new = text.add_region_to_year(old, R.prefix, f["export_date"])
        if new != old:
            R.write_work("year_README.before.txt", old)
            year.write_text(new)
            print(f"  added {R.prefix} to {year}")
    else:
        year.write_text(text.render_year({**f, "contact": f["notes"]["contact"], "mmu": f["mmu"],
                                          "study_region": f["run"]["study_region"]}))
        print(f"  wrote {year}")
    markers = [line.strip() for doc in (readme, year.read_text()) for line in doc.splitlines() if "[[REVIEW" in line]
    finish("readme", [f"needs review: {m}" for m in markers])


# --------------------------------------------------------------------------- check

def step_check(R):
    import pyogrio
    import rasterio

    failed = []
    products = {w: R.file_name(w) for w in ["polygons", "parameters", *RASTERS]}
    expected = {"README.txt", *products.values(), *(f"validation/{R.report(w).name}" for w in REPORTS)}
    actual = {str(p.relative_to(R.dir)) for p in R.dir.rglob("*") if p.is_file()} if R.dir.exists() else set()
    require(failed, actual == expected, f"files: missing {sorted(expected - actual)}, unexpected {sorted(actual - expected)}")
    if actual != expected:
        finish("check", failed)
    readme = (R.dir / "README.txt").read_text()
    year = (R.year_dir / "README.txt").read_text() if (R.year_dir / "README.txt").exists() else ""
    require(failed, bool(year), "year README.txt is missing")
    for name, doc in (("README.txt", readme), ("year README.txt", year)):
        require(failed, "[[REVIEW" not in doc, f"{name} still has [[REVIEW]] markers")
        require(failed, "uncommitted" not in doc, f"{name} mentions uncommitted code")
    require(failed, f"  {R.prefix} " in year, f"year README does not list {R.prefix}")
    for name in products.values():
        size = "~" + text.human_size((R.dir / name).stat().st_size)
        require(failed, re.search(rf"^  {re.escape(name)} +{re.escape(size)}$", readme, re.M) is not None,
                f"README FILES entry for {name} missing or size is not {size}")
    layers = [lyr[0] for lyr in pyogrio.list_layers(R.path("polygons"))]
    require(failed, layers == [R.path("polygons").stem], f"GeoPackage layers {layers}")
    grids = []
    for key, spec in RASTERS.items():
        with rasterio.open(R.path(key)) as ds:
            grids.append((ds.crs.to_string(), tuple(ds.transform), ds.width, ds.height))
            require(failed, ds.nodata == spec["nodata"] and ds.dtypes[0] == spec["dtype"], f"{key} dtype/nodata")
    require(failed, same_grid(grids), "rasters are not on one grid")
    for what in ("gpkg_checks", "rasters"):
        require(failed, R.report(what).read_text().rstrip().splitlines()[-1].split()[-1] == "PASS",
                f"{R.report(what).name} does not end in PASS")
    failed += vs_original_failures(json.loads(R.report("vs_original").read_text()))
    failed += alignment_failures(json.loads(R.report("alignment").read_text()))
    tool = json.loads(R.report("metadata").read_text())["properties"].get("correction_tool", "")
    require(failed, tool and "uncommitted" not in tool, f"asset metadata correction_tool {tool!r}")
    finish("check", failed)
    total = sum(p.stat().st_size for p in R.dir.rglob("*") if p.is_file())
    print(f"\n{len(expected)} files, {total / 1e9:.2f} GB, ready to upload. Upload (not run by this tool):")
    print(f'  RC={RCLONE}')
    print(f'  $RC copy --dry-run -v --ignore-existing "{R.dir}" "{R.box_dir}"')
    print(f'  $RC copy -v --ignore-existing "{R.dir}" "{R.box_dir}"')
    print(f'  $RC check "{R.dir}" "{R.box_dir}"')
    print("Year README (replaces the Box copy by name; needs approval):")
    print(f'  $RC copyto --dry-run -v "{R.year_dir}/README.txt" "{R.box_year_dir}/README.txt"')


STEPS = {"plan": step_plan, "polygons": step_polygons, "parameters": step_parameters, "rasters": step_rasters,
         "align": step_align, "readme": step_readme, "check": step_check}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("step", choices=[*STEPS, "all"])
    ap.add_argument("--name", required=True, help="region name for file names, e.g. North_Cascades")
    ap.add_argument("--staging", default=DEFAULT_STAGING)
    ap.add_argument("--work", default=None)
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()
    R = Region(args.config, args.name, args.staging, args.work, args.notes)
    steps = ["polygons", "parameters", "rasters", "align", "readme", "check"] if args.step == "all" else [args.step]
    try:
        for step in steps:
            print(f"===== {step}", flush=True)
            STEPS[step](R)
    except StepFailed as exc:
        print(f"stopped: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
