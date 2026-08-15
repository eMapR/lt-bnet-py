import export_utils as eu


class TestRemoveDuplicateSubstrings:
    def test_no_duplicates_unchanged(self):
        assert eu.remove_duplicate_substrings("abc_def") == "abc_def"

    def test_single_duplicate_removed(self):
        assert eu.remove_duplicate_substrings("abc_abc_def") == "abc_def"

    def test_repeated_duplicate_collapses_to_one(self):
        assert eu.remove_duplicate_substrings("abc_abc_abc_def") == "abc_def"

    def test_mixed_delimiters_and_duplicate_year(self):
        assert eu.remove_duplicate_substrings("proj-2020_2020-v1") == "proj_2020_v1"

    def test_all_parts_duplicate_collapses_to_single_token(self):
        assert eu.remove_duplicate_substrings("a-a-a") == "a"

    def test_leading_delimiter_and_duplicate_stripped(self):
        assert eu.remove_duplicate_substrings("_leading_dup_dup") == "leading_dup"


class TestSanitizeShapefileFieldName:
    def test_truncates_to_ten_chars(self):
        used = set()
        assert eu._sanitize_shapefile_field_name("Description", used) == "Descriptio"

    def test_collision_gets_numeric_suffix_within_ten_chars(self):
        used = {"DESCRIPTIO"}
        result = eu._sanitize_shapefile_field_name("DESCRIPTION_2", used)
        assert result == "DESCRIPTI1"
        assert len(result) <= 10

    def test_leading_digit_gets_prefixed(self):
        result = eu._sanitize_shapefile_field_name("123abc", set())
        assert result == "f_123abc"
        assert not result[0].isdigit()

    def test_invalid_chars_replaced_with_underscore(self):
        assert eu._sanitize_shapefile_field_name("abc!@#def", set()) == "abc___def"

    def test_empty_name_falls_back_to_field(self):
        assert eu._sanitize_shapefile_field_name("", set()) == "field"

    def test_records_uppercased_name_in_used_set(self):
        used = set()
        result = eu._sanitize_shapefile_field_name("lower", used)
        assert result.upper() in used
