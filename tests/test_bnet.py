import bnet


class TestResolveExclusionClasses:
    """resolve_exclusion_classes decides which classified_fc 'classification'
    codes get carved out of the residual change space (the exclusion mask),
    as distinct from which codes are valid classifier output at all. Covers
    the compatibility contract: legacy_2012 must be untouched, point_labels
    gets the real fix (insectDisease=50 no longer excluded by default), and
    an explicit override always wins regardless of training source."""

    def test_legacy_2012_default_uses_legacy_range(self):
        mode, classes = bnet.resolve_exclusion_classes({"classification_training": "legacy_2012"})
        assert mode == "legacy_range"
        assert classes is None

    def test_missing_classification_training_defaults_to_legacy_range(self):
        # classify_polygons/filter_classes both default classification_training
        # to 'legacy_2012' when absent - this must match that default exactly.
        mode, classes = bnet.resolve_exclusion_classes({})
        assert mode == "legacy_range"
        assert classes is None

    def test_point_labels_default_excludes_competing_agents_only(self):
        mode, classes = bnet.resolve_exclusion_classes({"classification_training": "point_labels"})
        assert mode == "point_labels_default"
        assert classes == [20, 21, 30, 40]

    def test_point_labels_default_does_not_include_insect_disease(self):
        # The actual bug being fixed: insectDisease (50) must never appear
        # in the default exclusion set.
        _, classes = bnet.resolve_exclusion_classes({"classification_training": "point_labels"})
        assert 50 not in classes

    def test_explicit_exclusion_classes_overrides_legacy_default(self):
        mode, classes = bnet.resolve_exclusion_classes(
            {"classification_training": "legacy_2012", "exclusion_classes": [20, 40]}
        )
        assert mode == "explicit"
        assert classes == [20, 40]

    def test_explicit_exclusion_classes_overrides_point_labels_default(self):
        mode, classes = bnet.resolve_exclusion_classes(
            {"classification_training": "point_labels", "exclusion_classes": [20, 21, 30, 40, 50]}
        )
        assert mode == "explicit"
        assert classes == [20, 21, 30, 40, 50]

    def test_explicit_empty_list_falls_back_to_default(self):
        # An empty list is falsy - treated the same as "unset" rather than
        # "explicitly exclude nothing", since a real config would never want
        # a no-op exclusion mask silently disabling the mask entirely.
        mode, classes = bnet.resolve_exclusion_classes(
            {"classification_training": "point_labels", "exclusion_classes": []}
        )
        assert mode == "point_labels_default"
        assert classes == [20, 21, 30, 40]

    def test_returned_list_is_a_copy_not_the_shared_default(self):
        # Mutating the caller's result must not corrupt
        # DEFAULT_POINT_LABELS_EXCLUSION_CLASSES for later calls.
        _, classes = bnet.resolve_exclusion_classes({"classification_training": "point_labels"})
        classes.append(999)
        _, classes2 = bnet.resolve_exclusion_classes({"classification_training": "point_labels"})
        assert classes2 == [20, 21, 30, 40]
