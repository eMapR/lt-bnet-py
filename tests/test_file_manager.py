import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("file_manager", _REPO_ROOT / "bugnet" / "file-manager.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

PARAMS_STEM = "BugNet_blue-mts_v2020_3_Annual_Change_mag60_20mmu_parameter_file"
FITTED_STEM = "BugNet_blue-mts_v2020_3_Annual_Change_A_predictor_fitted_img_2015_2020"
CLASSED_STEM = "BugNet_blue-mts_v2020_3_Annual_Change_C4_classed_img_2020"
MASK_STEM = "BugNet_blue-mts_v2020_3_Annual_Change_D_forest_mask_2020"
POLYS_STEM = "BugNet_blue-mts_v2020_3_Annual_Change_polygons_buffered_2020_mag60_20mmu"

EXPECTED_TOKENS = {
    "project": "BugNet",
    "region_slug": "blue-mts",
    "region_pretty": "Blue Mts",
    "ver": "v2020_3",
    "year": "2020",
    "vernum": "3",
}


class TestParseParamsTokens:
    def test_matches_parameter_csv_stem(self):
        result = fm.parse_params_tokens(PARAMS_STEM)
        assert result == EXPECTED_TOKENS

    def test_non_matching_stem_returns_none(self):
        assert fm.parse_params_tokens("not_a_matching_stem") is None


class TestParseGeneralTokens:
    @pytest.mark.parametrize("stem", [FITTED_STEM, CLASSED_STEM, MASK_STEM, POLYS_STEM])
    def test_known_product_stems_extract_common_tokens(self, stem):
        assert fm.parse_general_tokens(stem) == EXPECTED_TOKENS

    def test_non_matching_stem_returns_none(self):
        assert fm.parse_general_tokens("nope") is None


class TestClassifyKind:
    def test_params_stem(self):
        kind, groups = fm.classify_kind(PARAMS_STEM)
        assert kind == "params"
        assert groups["mag"] == "60" and groups["mmu"] == "20"

    def test_fitted_stem(self):
        kind, groups = fm.classify_kind(FITTED_STEM)
        assert kind == "fitted"
        assert groups["y1"] == "2015" and groups["y2"] == "2020"

    def test_loose_polys_fallback_pattern(self):
        kind, groups = fm.classify_kind("loose_polygons_buffered_2020_mag60_20mmu")
        assert kind == "polys"
        assert groups == {}

    def test_unrecognized_stem_returns_none_kind(self):
        kind, groups = fm.classify_kind("totally_unrelated")
        assert kind is None
        assert groups == {}


class TestSmallStringHelpers:
    def test_pretty_from_slug(self):
        assert fm.pretty_from_slug("blue-mts") == "Blue Mts"

    def test_clean_component_collapses_spaces_and_underscores(self):
        assert fm.clean_component("  a  b  ") == "a_b"

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("foo.tif.aux.xml", "foo"),
            ("foo.tif.ovr", "foo"),
            ("foo.tif", "foo.tif"),
            ("foo.shp", "foo.shp"),
        ],
    )
    def test_strip_compound_tif(self, name, expected):
        assert fm.strip_compound_tif(name) == expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("foo.tif", True),
            ("foo.tiff", True),
            ("foo.tif.aux.xml", True),
            ("foo.tif.ovr", True),
            ("foo.shp", False),
        ],
    )
    def test_is_tif_like(self, name, expected):
        assert fm.is_tif_like(Path(name)) is expected

    def test_root_folder_name(self):
        tokens = {"project": "BugNet", "region_pretty": "Blue Mts", "ver": "v2020_3"}
        assert fm.root_folder_name(tokens) == "BugNet_Blue_Mts_v2020_3_Annual_Change"


class TestChunkStemHelpers:
    def test_five_digit_suffix_is_a_chunk(self):
        assert fm.is_chunk_stem("foo-00000") is True
        assert fm.base_stem_without_chunk("foo-00000") == "foo"

    def test_double_ten_digit_suffix_is_a_chunk(self):
        stem = "foo-0000000001-0000000005"
        assert fm.is_chunk_stem(stem) is True
        assert fm.base_stem_without_chunk(stem) == "foo"

    def test_no_suffix_is_not_a_chunk(self):
        assert fm.is_chunk_stem("foo") is False
        assert fm.base_stem_without_chunk("foo") == "foo"

    def test_short_numeric_suffix_below_five_digits_is_not_a_chunk(self):
        # CHUNK_STEM_RE requires >=5 digits, so this looks like a chunk
        # suffix but isn't treated as one.
        assert fm.is_chunk_stem("foo-123") is False
        assert fm.base_stem_without_chunk("foo-123") == "foo-123"


class TestUniquePath:
    def test_returns_same_path_when_not_taken(self, tmp_path):
        candidate = tmp_path / "out.tif"
        assert fm.unique_path(candidate) == candidate

    def test_appends_counter_when_taken(self, tmp_path):
        existing = tmp_path / "out.tif"
        existing.write_text("x")
        result = fm.unique_path(existing)
        assert result == tmp_path / "out__1.tif"

    def test_increments_past_multiple_collisions(self, tmp_path):
        (tmp_path / "out.tif").write_text("x")
        (tmp_path / "out__1.tif").write_text("x")
        (tmp_path / "out__2.tif").write_text("x")
        result = fm.unique_path(tmp_path / "out.tif")
        assert result == tmp_path / "out__3.tif"
