import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_deliverable as bd  # noqa: E402
import deliverable_readme as text  # noqa: E402

YEAR_README = """BugNet Region 6 products - 2026
===============================

Regions available
  Bugnet_North_Cascades_v2026-2    complete: polygons, BugNet class raster,
                                   fitted image, classed image, forest mask,
                                   parameters (2026-10-15)

Differences from the 2024 and 2025 products
"""


class TestFormatting:
    @pytest.mark.parametrize("nbytes,expected", [
        (12488704, "12 MB"), (1363071, "1.4 MB"), (3120615865, "3.1 GB"),
        (650929, "0.7 MB"), (4762099, "4.8 MB"), (4866, "5 KB"),
    ])
    def test_human_size_matches_north_cascades_readme(self, nbytes, expected):
        assert text.human_size(nbytes) == expected

    def test_upper_bound_pct_rounds_up(self):
        assert text.upper_bound_pct(2.46e-07) == "0.00003%"
        assert text.upper_bound_pct(0) == "0%"

    def test_wrap_keeps_nbsp_groups_together(self):
        out = text.wrap(f"aaaa buffered by 30{text.NBSP}m and", width=20)
        assert out.splitlines() == ["aaaa buffered by", "30 m and"]


class TestYearReadme:
    def test_entry_matches_north_cascades_layout(self):
        entry = text.region_entry("Bugnet_North_Cascades_v2026-2", "2026-10-15")
        assert entry in YEAR_README

    def test_add_region_inserts_once(self):
        new = text.add_region_to_year(YEAR_README, "Bugnet_Klamath_Mts_v2026-2", "2026-11-01")
        assert new.index("Bugnet_North_Cascades") < new.index("Bugnet_Klamath_Mts") < new.index("Differences")
        assert text.add_region_to_year(new, "Bugnet_Klamath_Mts_v2026-2", "2026-11-01") == new


class TestFittedYears:
    def test_contiguous_years(self):
        names = [f"{i}_ftv_{y}" for i in ("TCB", "NBR") for y in range(2012, 2015)]
        assert bd.fitted_years(names) == (["TCB", "NBR"], [2012, 2013, 2014])

    @pytest.mark.parametrize("names", [
        ["TCB_ftv_2012", "TCB_ftv_2014"],
        ["TCB_ftv_2012", "TCB_ftv_2013", "NBR_ftv_2012"],
        ["TCB_fitted_2012"],
    ])
    def test_irregular_bands_are_rejected(self, names):
        with pytest.raises(bd.StepFailed):
            bd.fitted_years(names)


class TestSameGrid:
    G = ("EPSG:4326", (0.0002694945852358564, 0, -122.35, 0, -0.0002694945852358564, 49.0), 10782, 6891)

    def test_one_ulp_pixel_size_difference_is_the_same_grid(self):
        other = (self.G[0], (0.00026949458523585647, 0, -122.35, 0, -0.00026949458523585647, 49.0), *self.G[2:])
        assert bd.same_grid([self.G, other])

    @pytest.mark.parametrize("change", [
        lambda g: (g[0], (g[1][0], 0, g[1][2] + g[1][0] / 2, 0, g[1][4], g[1][5]), *g[2:]),  # half-pixel shift
        lambda g: (g[0], (g[1][0] * (1 + 1e-6), *g[1][1:]), *g[2:]),  # drifts 1% of a pixel over the grid
        lambda g: (*g[:2], g[2] + 1, g[3]),
        lambda g: ("EPSG:5070", *g[1:]),
    ])
    def test_different_grids(self, change):
        assert not bd.same_grid([self.G, change(self.G)])


def test_wgs84_row_areas_sum_to_ellipsoid_area():
    rows = bd.wgs84_row_areas(Affine(1, 0, 0, 0, -1, 90), 180)
    assert rows.sum() * 360 == pytest.approx(510065621.724e6, rel=1e-9)


def test_read_notes_marks_missing_keys(tmp_path):
    path = tmp_path / "notes.ini"
    path.write_text("[readme]\nregion = Somewhere,\n    continued\n")
    notes = bd.read_notes(path)
    assert notes["region"] == "Somewhere, continued"
    assert notes["contact"].startswith("[[REVIEW:")


def vs_original(n=3, **overrides):
    report = {"n_before": n, "n_after": n, "n_paired": n, "n_with_exactly_one_partner": n,
              "same_geometry": n, "unchanged_fields_matching": {"SURVEY_YEAR": n},
              "n_pct_gt_100_after": 0, "n_bnet_label_null": 0, "n_no_unbuffered_match_after": 0,
              "ACRES_equals_buffered_acres_after": n, "sum_unbuffered_acres_after": 10.0,
              "sum_unbuffered_polygon_acres_direct": 10.0}
    return {**report, **overrides}


class TestVsOriginal:
    def test_passes(self):
        assert bd.vs_original_failures(vs_original()) == []

    @pytest.mark.parametrize("override", [
        {"same_geometry": 2}, {"unchanged_fields_matching": {"SURVEY_YEAR": 2}},
        {"n_pct_gt_100_after": 1}, {"sum_unbuffered_acres_after": 10.1},
    ])
    def test_fails(self, override):
        assert bd.vs_original_failures(vs_original(**override))


class TestAlignment:
    """A 10x10 grid near 45N: one 3x3 detected patch of class 1 inside one buffered polygon."""

    T = Affine(0.001, 0, -120.0, 0, -0.001, 45.0)

    def setup(self, tmp_path, polygon_bounds):
        cls = np.full((10, 10), 255, dtype="uint8")
        cls[2:5, 2:5] = 1
        cls[8, 8] = 0  # a sub-MMU pixel, not in any detection
        tif = tmp_path / "class.tif"
        with rasterio.open(tif, "w", driver="GTiff", width=10, height=10, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=self.T, nodata=255) as ds:
            ds.write(cls, 1)
        x0, y0 = self.T * (2, 5)
        x1, y1 = self.T * (5, 2)
        patch = box(x0, y0, x1, y1)
        rows = bd.wgs84_row_areas(self.T, 10)
        acres = float(rows[2:5].sum() * 3 * bd.pu.ACRES_PER_SQ_M)
        unb = gpd.GeoDataFrame({"label": [1], "count": [9]}, geometry=[patch], crs="EPSG:4326")
        buf = gpd.GeoDataFrame({"unbuffered_acres": [acres], "ACRES": [acres * 2], "bnet_label": [1]},
                               geometry=[box(*polygon_bounds)], crs="EPSG:4326")
        gpkg = tmp_path / "p.gpkg"
        buf.to_file(gpkg, layer="p", driver="GPKG")
        return bd.alignment_report(tif, gpkg, "p", unb, k=3)

    def test_aligned_polygons_pass(self, tmp_path):
        r = self.setup(tmp_path, (-119.9985, 44.9945, -119.9945, 44.9985))
        assert r["unbuffered_pixels_also_in_class_raster"] == 9 == r["unbuffered_pixel_count_sum_from_asset"]
        assert r["class_pixels_not_in_any_detection"] == 1
        assert abs(r["detection_area_raster_vs_gpkg_rel_diff"]) < 1e-12
        assert r["bnet_label_equals_raster_mode"]["equal"] == 1
        assert bd.alignment_failures(r) == []

    def test_polygon_missing_the_patch_fails(self, tmp_path):
        r = self.setup(tmp_path, (-119.995, 44.9945, -119.9945, 44.9985))
        assert r["detection_pixels_outside_all_polygons"] > 0
        assert bd.alignment_failures(r)
