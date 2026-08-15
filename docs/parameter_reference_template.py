"""
Annotated reference for BugNet parameter files.

This is NOT loaded by main.py - it's documentation. A real parameter file
is a .py script that defines a module-level `param` dict (see any file
under templates/ or params_new/) and gets passed as
`python main.py <path-to-that-file>`.

Every key below was found by reading how it's actually consumed across
main.py, cli_utils.py, pipeline_modes.py, disturbance_utils.py,
modeling_utils.py, postprocess_utils.py, export_utils.py, and bnet.py as
of the refactor-bugnet-cleanup branch (2026-08-14) - not copied from an
existing template, since templates/, parameters/, and params_new/ are all
gitignored and empty in this checkout. Two spots are marked TODO because
the code that builds them lives in your per-run template files, not in
this repo: confirm against a real template before trusting those two.

Keys are grouped by what stage of the pipeline reads them, not
alphabetically, so you can find "everything the classifier stage needs"
in one place.
"""

import datetime

param = {

    # ------------------------------------------------------------------
    # Identity, versioning, asset layout
    # ------------------------------------------------------------------
    # GEE Cloud Project this run's assets live under. Passed straight to
    # ee.Initialize(project=...) in main.py.
    "project_name": "r6-bugnet",

    # Short slug for the disturbance-year product, e.g. "blue-mts-bugnet".
    # Combined with version to build assetDir (see below).
    "target": "blue-mts-bugnet",

    # Run-specific version suffix. cli_utils.normalize_parameters() strips
    # a leading "v" if present, so "3" and "v3" are equivalent. Used to
    # build the run-specific assetDir - bump this for a variant you want
    # kept fully separate (e.g. sweeping MAG/MMU via batch_bugnet.sh).
    "version": "3",

    # Optional. Version key for assets SHARED across variants of the same
    # ecoregion/year (fitted imagery, change image, forest mask, decline
    # image, etc.) - lets mode-2 sweeps (different MAG/MMU) reuse one set
    # of expensive shared assets instead of rebuilding them per variant.
    # Defaults to logic_version (below) if omitted.
    "shared_version": "3",

    # Optional. Controls which branch of the pipeline logic runs, NOT
    # just a label. Both branches still feed into the same downstream
    # KMeans-clustering -> ADS-proportion-labeling -> RF-classifier chain
    # (build_kmeans_sample/kmeans_image/kmeans_ads_sample/proportion_calc/
    # predict all run either way) - what differs is how the decline image
    # they cluster on gets built:
    #   - anything WITHOUT "3" -> snic() + declining_snic(): this is the
    #     canonical BugNet method (SNIC-segments the fitted imagery into
    #     spectrally-similar patches first, "honing"/denoising the
    #     landscape, THEN scores decline on those patches - see the
    #     project writeup). As of this branch it's BROKEN:
    #     declining_snic() raises NotImplementedError because the
    #     restored bnet.SNIC_decline_image() expects renamed bands
    #     ('yr_<year>_nbr_mean' etc.) that snic()'s current output
    #     doesn't have. This is the primary documented algorithm, not a
    #     minor unused branch - fixing the band-naming mismatch is real
    #     work, not optional cleanup.
    #   - configName containing "3" (e.g. "option3") -> declining_ltsd():
    #     a continuous decline-score variant that skips SNIC
    #     patchification entirely and scores decline directly off the
    #     fitted imagery (bnet.LTSD_decline_score). This is the only path
    #     that currently runs end-to-end.
    #   - configName containing "2" also switches modeling_utils.py's
    #     proportion_calc()/predict() between bnet.rename_img (opt2) and
    #     bnet.rename_img_opt3 (everything else).
    # Defaults to f"option{logic_version}" if omitted - you usually don't
    # need to set this explicitly unless logic_version doesn't match the
    # branch you want.
    "configName": "option3",

    # --- Everything below this line in this section is DERIVED, not set
    #     by you. cli_utils.normalize_parameters() computes these from
    #     project_name/target/version/shared_version on every load:
    #       assetDir       = projects/{project_name}/assets/{target}-v{version}/
    #       sharedAssetDir = projects/{project_name}/assets/{target}-v{shared_version}/
    #       LTSDdir        = sharedAssetDir
    #       logic_version  = version's numeric part if not set explicitly
    #     Setting them yourself in a template is harmless (they get
    #     overwritten) but pointless - don't bother.

    # ------------------------------------------------------------------
    # Study area
    # ------------------------------------------------------------------
    # ee.FeatureCollection or ee.Geometry - the AOI every stage clips/
    # exports/samples against. Read almost everywhere (fitted imagery,
    # change detection, forest mask, KMeans sampling, final export
    # region, ...).
    "aoi": None,  # e.g. ee.FeatureCollection("projects/.../assets/blue_mts_boundary")

    # String key matched against LCMS's 'study_area' property in
    # bnet.lcms_forest_mask() (e.g. "R6", "PNW" - whatever your LCMS
    # collection uses). Also written verbatim into the final buffered
    # polygons' REGION_ID field (postprocess_utils.calc_attri_fields).
    "study_region": "PNW",

    # Export/attribution scale in meters. Read by nearly every
    # ee.batch.Export.image.toAsset call and every reduceRegion/
    # reduceToVectors/stratifiedSample scale= argument.
    "pixel_scale": 30,

    # Source/target EPSG codes used only when reprojecting training
    # polygons through bnet.feature_collection_to_geojson /
    # geojson_to_ee_feature (attributeTrainingPolygons, to attribute
    # against the cMonster reference raster below).
    "source_epsg": "EPSG:4326",
    "target_epsg": "EPSG:5070",

    # ------------------------------------------------------------------
    # LandTrendr / composite construction
    # ------------------------------------------------------------------
    # TODO: confirm against a real template - the code that BUILDS
    # lt_collection lives in your per-run template files, not in this
    # repo, so this is inferred from ltgee.LandTrendr's constructor
    # signature rather than seen in use here.
    # Unpacked directly as LandTrendr(**param["lt_params"]) in
    # pipeline_modes.run_mode_1/2, so its keys must match
    # ltgee.landtrendr.LandTrendr.__init__ exactly:
    #   lt_collection: ltgee.LtCollection | ee.ImageCollection | dict
    #       (built from LandsatComposite/Sentinel2Composite - see ltgee's
    #       own docs/examples for how to construct one)
    #   run_params: dict, LandTrendr segmentation tuning - defaults to
    #       {"maxSegments": 6, "spikeThreshold": 0.9,
    #        "vertexCountOvershoot": 3, "preventOneYearRecovery": False,
    #        "recoveryThreshold": 0.25, "pvalThreshold": 0.1,
    #        "bestModelProportion": 1.25, "minObservationsNeeded": 6}
    #   run: bool = True - whether to run LandTrendr immediately
    "lt_params": {
        "lt_collection": None,
        "run_params": {
            "maxSegments": 6,
            "spikeThreshold": 0.9,
            "vertexCountOvershoot": 3,
            "preventOneYearRecovery": False,
            "recoveryThreshold": 0.25,
            "pvalThreshold": 0.1,
            "bestModelProportion": 1.25,
            "minObservationsNeeded": 6,
        },
    },

    # TODO: confirm against a real template - only start_date/end_date
    # are actually read in THIS repo (bnet.get_fitted_stack, to compute
    # start_year/end_year for band naming). It's plausible your templates
    # pack more into this dict to also build lt_collection above, but
    # nothing here reads more than these two keys.
    "composite_params": {
        "start_date": datetime.date(1985, 6, 1),
        "end_date": datetime.date(2025, 9, 1),
    },

    # List of spectral index names LandTrendr was fit on, in a FIXED
    # order that get_fitted_stack relies on positionally (index_list[0:4]
    # each get selected into the training/predictor stack). Every index
    # here also needs an entry in decline_thresholds below except the one
    # matching `index` (excluded from attribution as redundant - see
    # bnet.attribute_with_reference_data). Case matters: bnet.py compares
    # values like "tcb" case-sensitively/case-insensitively in different
    # places (e.g. tasselCapMask does `.lower() == "tcb"`), so keep this
    # consistent with what your decline_thresholds/decline_template use.
    "fit": ["NBR", "TCB", "TCG", "TCW"],

    # The single index LandTrendr change-detection/vectorization is keyed
    # on (the "yod" band's source index). Excluded from the attributed
    # predictor set since it's already captured via the change image.
    "index": "NBR",

    # ------------------------------------------------------------------
    # Training / classification (run_mode_1 only - trains from scratch)
    # ------------------------------------------------------------------
    # Polygon area/count bounds (in "count" pixels from
    # vectorize_disturbance) used to filter which disturbance polygons
    # become training examples - see
    # bnet.attribute_with_reference_data -> filter(gt(trainingMin) &
    # lt(trainingMax)).
    "trainingMin": 5,
    "trainingMax": 5000,

    # Path to the reference/ground-truth raster used to attribute
    # training polygons (bnet.attribute_with_cmonster_data), e.g. a
    # digitized disturbance-cause raster ("cMonster").
    "cMonster_img_path": "projects/.../assets/cmonster_reference",

    # ee.Classifier.smileRandomForest tree count (classify_polygons).
    "num_trees": 500,

    # Passed to bnet.classify_features(..., heavy=param['class_heavy']).
    # 0/False = normal classification. 1/True = also force-reclassify
    # high-magnitude/high-count polygons as fire/clearcut (mag>400 ->
    # class 21, count>4000 -> class 40) before the RF classifier sees
    # them - use when you're seeing obvious stand-replacing disturbance
    # leaking into the "subtle decline" classes.
    "class_heavy": 0,

    # Optional high-magnitude exclusion layer, read by
    # disturbance_utils.buffer_classed_polygons. When "on" is True,
    # buffered polygons that spatially intersect either path/path2 (e.g.
    # known fire/harvest perimeters) are dropped in favor of keeping only
    # the fire-classified (classification==40) ones - a belt-and-braces
    # filter on top of class_heavy. When "on" is False, path/path2 are
    # never read.
    "wild_path": {
        "on": False,
        "path": "projects/.../assets/known_fire_perimeters",
        "path2": "projects/.../assets/known_harvest_perimeters",
    },

    # ------------------------------------------------------------------
    # Decline scoring (declining_ltsd / declining_snic stage)
    # ------------------------------------------------------------------
    # How many years back from `target` to pull _ftv bands for the
    # decline-score band dictionary (bnet.decline_image /
    # LTSD_decline_score both read this).
    "agent_lookback": 5,

    # Per-index (t1, t2) magnitude thresholds used to build the
    # decline-detection boolean expression - keys must match entries in
    # `fit` (bnet.decline_image's decline_expr, LTSD_decline_score).
    "decline_thresholds": {
        "TCB": (70, 40),
        "TCG": (50, 30),
        "TCW": (50, 30),
    },

    # Taper step used by LTSD_decline_score's continuous decline-score
    # variant (bnet.py). Only meaningful on the declining_ltsd
    # (configName contains "3") path.
    "decline_step": 10,

    # String.format() template combining each index's decline_expr(...)
    # into one boolean expression - e.g. "({TCB}) || ({TCG} && {TCW})".
    # Only used by bnet.decline_image, which itself isn't currently
    # wired into either pipeline path (dead code as of this branch - see
    # bnet.py; both declining_ltsd and declining_snic use their own
    # hardcoded expressions instead). Keep it in your template for now in
    # case that changes, but don't expect it to affect a real run.
    "decline_template": "({TCB}) || ({TCG} && {TCW})",

    # Date bounds (as ee.Date-compatible strings, e.g. "2015-01-01")
    # for excluding MTBS-documented fire from the forest mask -
    # modeling_utils.create_forest_mask/_vis filter MTBS fire perimeters
    # to this Ig_Date range.
    "maskStartTime": "2015-01-01",
    "maskEndTime": "2025-12-31",

    # NOTE: stored/used as a STRING, not an int - bnet.tasselCapMask
    # builds its ee.Image.expression via Python string concatenation
    # ('band > ' + param['brightness_value'] + ' ? 0 : 1'), so an int
    # here raises a TypeError at run time. Threshold on the target year's
    # TCB (brightness) fitted band; pixels above it are masked OUT of the
    # forest mask (bright/non-forest).
    "brightness_value": "2200",

    # ------------------------------------------------------------------
    # SNIC / KMeans clustering + ADS proportion sampling
    # ------------------------------------------------------------------
    # ee.FeatureCollection of Aerial Detection Survey ground-truth
    # polygons, filtered to the AOI in kmeans_proportions_ads_sample.
    "ads": None,  # e.g. ee.FeatureCollection("projects/.../assets/ads_2025")

    # Gates whether run_mode_2 does the full ADS-proportion/predict/
    # buffer chain or falls back to the interactive reclassification path
    # (pipeline_modes.run_mode_2). Keep "on": False for a first pass on a
    # region with no ADS coverage yet.
    "ADS_path": {
        "on": True,
    },

    # wekaCascadeKMeans cluster count (both min and max - modeling_utils
    # passes this value twice), used to cluster the SNIC/decline image.
    "num_of_clusters": 20,

    # Target sample size for build_kmeans_sample's "sample"/"sampleRegions"
    # fallback attempts (modeling_utils.build_kmeans_sample). The first
    # two fallback strategies (stratifiedSample, reduceToVectors) ignore
    # this and use their own fixed numbers.
    "kmeans_num_sample": 2000,

    # stratifiedSample numPoints for the labeled proportion-calc sample
    # (modeling_utils.proportion_calc).
    "proportion_strat_sample_size": 4000,

    # ------------------------------------------------------------------
    # Final polygon output (buffering, MMU filtering)
    # ------------------------------------------------------------------
    # Buffer distance in meters applied to final predicted polygons
    # (postprocess_utils.buffer_bnet_polygons) - float() cast at read
    # time, so an int is fine.
    "bnet_buffer": 30,

    # Minimum polygon pixel "count" (from reduceToVectors) to keep when
    # polygonizing (postprocess_utils.polygonize_bnet) and when filtering
    # before buffering (buffer_bnet_polygons) - this is the "MMU" (min
    # mapping unit) referenced throughout filenames/batch_bugnet.sh, e.g.
    # "mag60_20mmu".
    "bnet_polygon_mmu": 20,

    # Optional. Number of random buckets buffer_bnet_polygons/
    # merge_buffer_buckets_and_finish shard the final buffer+dissolve
    # into (avoids one giant geometry op timing out server-side). Default
    # 75 if omitted.
    "buckets": 75,

    # Optional. ee.Geometry error margin (meters) for buffer/dissolve
    # operations in postprocess_utils. Default 10 if omitted.
    "buffer_max_error": 10,

    # Which strategy CreatePredictorDisturbancePolygons uses to vectorize
    # the (potentially huge) change image for run_mode_2:
    #   "full"   - vectorize the whole AOI in one call (cheapest, can
    #              time out on large AOIs / high disturbance years)
    #   "bucket" - split by a random attribute bucket (no spatial
    #              slicing) - good when the failure is polygon COUNT, not
    #              geometry complexity
    #   "grid"   - split spatially into a covering grid (last resort,
    #              slowest, most reliable for genuinely huge AOIs)
    #   "auto"   - try full, then bucket, then grid, keeping whichever
    #              succeeds first
    # run_mode_1 always uses "grid" internally (hardcoded default arg,
    # not read from param) - this key only affects run_mode_2.
    "polygon-split-method": "auto",

    # ------------------------------------------------------------------
    # Export / bookkeeping
    # ------------------------------------------------------------------
    # Prefix used when exporting finished assets to Drive/Cloud Storage
    # (export_utils.export_to_drive, mode 3).
    "outputfile_prefix": "BugNet_blue-mts_v2020_3_Annual_Change",

    # ------------------------------------------------------------------
    # Asset name suffixes
    # ------------------------------------------------------------------
    # Every key below is just a filename fragment appended to assetDir or
    # sharedAssetDir (normalize_parameters() derives both from
    # project_name/target/version above) - the pipeline stage functions
    # each check asset_exists(assetDir + this_key) before doing work, so
    # renaming one of these between runs forces that stage to redo work
    # even if the underlying data hasn't changed. Keep them stable across
    # a MAG/MMU sweep (batch_bugnet.sh) and only bump `version` for that.
    "fitted_img_t": "A_training_fitted_img",
    "fitted_img_p": "A_predictor_fitted_img",
    "training_change_img": "B_training_change_img",
    "predictor_change_img": "B_predictor_change_img",
    "disturbance_polygons_training": "training_disturbance_polygons",
    "disturbance_polygons_predictor": "predictor_disturbance_polygons",
    "attributed_polygons_training": "training_attributed_polygons",
    "attributed_polygons_predictor": "predictor_attributed_polygons",
    "classified_fc": "C_classified_polygons",
    "filtered_classes": "C2_filtered_classes",
    "buffered_classes": "C3_buffered_classes",
    "rasterize_classes": "C4_classed_img",
    "forestMaskName": "D_forest_mask",
    "LTSDname": "E_LTSD_decline_img",
    "declineName": "E_decline_img",
    "snicName": "F_snic_img",
    "kmeansName": "G_kmeans_img",
    "kmeansNameSample": "G_kmeans_img_sample",
    "KmeansVector": "H_kmeans_vector",
    "proportionName": "I_proportion_img",
    "predicted": "J_predicted_img",
    "bnet_polygonized": "K_bnet_polygons",
    "bnet_buffered_polygons": "polygons_buffered",
    "parameter_file": "parameter_file",
}
