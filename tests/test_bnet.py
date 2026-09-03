import bnet


def _base_manifest_param(**overrides):
    """Minimal param dict covering every key build_run_manifest reads
    directly (not via .get with a default)."""
    param = {
        "project_name": "north-cascades-bugnet",
        "version": "3",
        "shared_version": "3",
        "change_params": {"mag": {"value": 350, "operator": ">"}},
        "wild_path": {"on": 1},
        "decline_path": "ltsd",
        "configName": "option3",
        "fit": ["TCB", "TCG", "TCW"],
        "assetDir": "projects/north-cascades-bugnet/assets/2025-v3/",
        "sharedAssetDir": "projects/north-cascades-bugnet/assets/2025-v3/",
        "target": 2025,
        "parameter_file": "parameter_file",
    }
    param.update(overrides)
    return param


class TestBuildRunManifest:
    """build_run_manifest assembles the curated, exportable set of
    per-run traceability facts (see project_lt_bnet_py_versioning_naming
    memory for why the bare v1/v2/v3 label alone isn't enough). Pure
    Python - no live GEE credentials needed."""

    def test_manifest_starts_at_startup_stage(self):
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["manifest_stage"] == "startup"

    def test_verified_historical_profile_is_matched(self):
        # north-cascades-bugnet/"3" is a real transcribed row in
        # bnet.HISTORICAL_PROFILES (see project_lt_bnet_py_versioning_naming).
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["historical_profile"] == "V3"
        assert manifest["historical_profile_status"] == "verified"

    def test_unverified_project_version_combo_reports_none_not_a_guess(self):
        # A new-style descriptive version string must never be matched
        # against the historical table by digit-guessing.
        manifest = bnet.build_run_manifest(
            _base_manifest_param(project_name="north-cascades-bugnet", version="pointLabels_terrain_r2")
        )
        assert manifest["historical_profile"] == "none"
        assert manifest["historical_profile_status"] == "unverified"

    def test_unknown_project_reports_none_not_a_guess(self):
        manifest = bnet.build_run_manifest(_base_manifest_param(project_name="brand-new-bugnet"))
        assert manifest["historical_profile"] == "none"
        assert manifest["historical_profile_status"] == "unverified"

    def test_configured_predictors_reflect_fit_and_point_labels_extras(self):
        manifest = bnet.build_run_manifest(
            _base_manifest_param(fit=["TCW", "TCB"], classification_training="point_labels")
        )
        assert manifest["configured_predictors_fit"] == ["TCB", "TCW"]
        assert manifest["configured_predictors_extras"] is True

    def test_legacy_2012_has_no_predictor_extras(self):
        manifest = bnet.build_run_manifest(_base_manifest_param(classification_training="legacy_2012"))
        assert manifest["configured_predictors_extras"] is False

    def test_resolved_predictors_start_pending(self):
        # Only classify_polygons (a later, live-GEE stage) can know this -
        # build_run_manifest must never claim a real value.
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["resolved_predictor_variables"] == "pending"
        assert manifest["resolved_predictor_variables_status"] == "pending"

    def test_exclusion_mode_and_classes_match_resolve_exclusion_classes(self):
        param = _base_manifest_param(classification_training="point_labels")
        manifest = bnet.build_run_manifest(param)
        mode, classes = bnet.resolve_exclusion_classes(param)
        assert manifest["exclusion_mode"] == mode
        assert manifest["exclusion_classes"] == classes

    def test_legacy_range_exclusion_classes_reported_as_empty_list_not_none(self):
        # resolve_exclusion_classes returns None for legacy_range by design
        # (see its own docstring) - the manifest must still be export-safe
        # (no bare None), so it coerces to [] while exclusion_mode keeps
        # the real reason distinguishable from an explicit empty override.
        manifest = bnet.build_run_manifest(_base_manifest_param(classification_training="legacy_2012"))
        assert manifest["exclusion_mode"] == "legacy_range"
        assert manifest["exclusion_classes"] == []

    def test_decline_method_defaults_to_bayesian_when_absent(self):
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["decline_method"] == "bayesian"

    def test_classification_training_defaults_to_legacy_2012_when_absent(self):
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["classification_training"] == "legacy_2012"

    def test_resolved_predictors_asset_prefers_shared_asset_dir(self):
        # classify_polygons exports resolved_predictors_* under
        # sharedAssetDir (falling back to assetDir) for all of its
        # outputs, same as classified_fc - the manifest's pointer has to
        # match that, not assume assetDir.
        param = _base_manifest_param(
            assetDir="projects/p/assets/2025-v9/",
            sharedAssetDir="projects/p/assets/2025-v3/",
        )
        manifest = bnet.build_run_manifest(param)
        assert manifest["resolved_predictors_asset"] == "projects/p/assets/2025-v3/resolved_predictors_2025"

    def test_explicit_mtbs_is_reported_as_mtbs(self):
        # Real configs (e.g. columbia-mts-bugnet's 2026-v1/v4-testing/v5)
        # set this explicitly - the manifest must preserve it, not
        # normalize it to a hardcoded constant.
        manifest = bnet.build_run_manifest(_base_manifest_param(fire_mask_source="mtbs"))
        assert manifest["fire_mask_source"] == "mtbs"

    def test_missing_fire_mask_source_uses_the_runtime_default(self):
        # Must match get_fire_polygons'/rasterize_fire_polygons' own
        # param.get('fire_mask_source', 'wfigs') default exactly.
        manifest = bnet.build_run_manifest(_base_manifest_param())
        assert manifest["fire_mask_source"] == "wfigs"


class TestResolveHistoricalProfile:
    """resolve_historical_profile cross-checks a run's actual mag/wild_path
    against its HISTORICAL_PROFILES table entry before ever reporting
    'verified' - a version-label match alone isn't sufficient, since
    param['version'] is an arbitrary, overloaded string and real
    collisions exist (e.g. columbia-mts-bugnet's real 2026 run labeled
    version "1" collides with the archived historical V1 key but was
    actually run with wild_path on, contradicting V1's real wild_path=off)."""

    def test_true_historical_profile_match_reports_verified(self):
        # north-cascades-bugnet/"3" is mag=350/wild_path_on=True in
        # HISTORICAL_PROFILES - a real config with those same values.
        param = _base_manifest_param()
        profile, status = bnet.resolve_historical_profile(param)
        assert profile == "V3"
        assert status == "verified"

    def test_unknown_version_key_reports_unverified(self):
        param = _base_manifest_param(version="pointLabels_terrain_r2")
        profile, status = bnet.resolve_historical_profile(param)
        assert profile == "none"
        assert status == "unverified"

    def test_version_key_collision_with_mismatched_wild_path_reports_mismatch(self):
        # Same (project, version) key as the true-match case, but
        # wild_path disagrees with the table entry - must not be
        # reported as verified.
        param = _base_manifest_param(wild_path={"on": 0})
        profile, status = bnet.resolve_historical_profile(param)
        assert profile == "none"
        assert status == "mismatch"

    def test_version_key_collision_with_mismatched_mag_reports_mismatch(self):
        param = _base_manifest_param(change_params={"mag": {"value": 250, "operator": ">"}})
        profile, status = bnet.resolve_historical_profile(param)
        assert profile == "none"
        assert status == "mismatch"

    def test_mismatch_never_infers_a_different_profile(self):
        # A mismatch means "not the colliding key's profile", never
        # "guess which other profile this might be".
        param = _base_manifest_param(wild_path={"on": 0})
        profile, _ = bnet.resolve_historical_profile(param)
        assert profile not in {"V1", "V2", "V3"}


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

    def test_explicit_empty_list_means_exclude_nothing(self):
        # [] is present-and-not-None, so it's a real explicit override
        # meaning "exclude nothing" - distinct from the key being absent
        # or explicitly None, which both fall back to the compatibility
        # default instead.
        mode, classes = bnet.resolve_exclusion_classes(
            {"classification_training": "point_labels", "exclusion_classes": []}
        )
        assert mode == "explicit"
        assert classes == []

    def test_explicit_none_falls_back_to_default(self):
        mode, classes = bnet.resolve_exclusion_classes(
            {"classification_training": "point_labels", "exclusion_classes": None}
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
