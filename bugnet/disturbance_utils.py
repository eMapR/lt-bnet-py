import ee

import bnet


# ----------------------------------------------------------------------------
# Fitted imagery
# ----------------------------------------------------------------------------
def CreateTrainingFittedImagery(lt, param, asset_exists):
    exists = asset_exists(param["assetDir_t"] + param['fitted_img_t'])
    if exists:
        return

    fitted_img_t = bnet.get_fitted_stack(lt, 'fitted_training', param)
    task = bnet.export_image(fitted_img_t.int16(), param, param['assetDir_t'], param['fitted_img_t'], param['pixel_scale'])
    return task


def CreatePredictorFittedImagery(lt, param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['fitted_img_p'])
    if exists:
        return

    treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()
    fitted_img_p = bnet.get_fitted_stack(lt, 'fitted_predictor', param).mask(treeMask).int16()
    task = bnet.export_image(fitted_img_p.int16(), param, asset_dir, param['fitted_img_p'], param['pixel_scale'])
    return task


# ----------------------------------------------------------------------------
# Change imagery
# ----------------------------------------------------------------------------
def CreateTrainingChangeImagery(lt, param, asset_exists):
    exists = asset_exists(param["assetDir_t"] + param['training_change_img'])
    if exists:
        return

    param['change_params']['years'] = {'start': 2007, 'end': 2012}
    change_img_t = lt.get_change_map(param['change_params'])
    task = bnet.export_image(change_img_t, param, param['assetDir_t'], param['training_change_img'], param['pixel_scale'])
    return task


def CreatePredictorChangeImagery(lt, param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['predictor_change_img'])
    if exists:
        return

    treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()
    change_img_p = lt.get_change_map(param['change_params']).mask(treeMask)
    task = bnet.export_image(change_img_p, param, asset_dir, param['predictor_change_img'], param['pixel_scale'])
    return task


# ----------------------------------------------------------------------------
# Disturbance polygons
# ----------------------------------------------------------------------------
def CreateTrainingDisturbancePolygons(param, asset_exists):
    exists = asset_exists(param["assetDir_t"] + param['disturbance_polygons_training'])
    if exists:
        return

    change_img_t = ee.Image(param["assetDir_t"] + param['training_change_img'])
    disturbance_polygons_t = bnet.vectorize_disturbance(change_img_t, param)
    task = bnet.export_feature_collection(disturbance_polygons_t, param['disturbance_polygons_training'], param['assetDir_t'])
    return task


# Grid a feature with square cells of `cell_size` meters (uses EPSG:3857)
def grid_over_feature(feature, cell_size_m, proj_epsg='EPSG:3857'):
    """Build a covering grid (square cells ~cell_size_m) over one feature."""
    feature = ee.Feature(feature)
    proj = ee.Projection(proj_epsg).atScale(cell_size_m)

    # Covering grid over the feature's bounds in the chosen projection
    grid = feature.geometry().coveringGrid(proj, cell_size_m)

    # Clip each grid cell to the feature and keep only non-empty pieces
    def _clip(f):
        f = ee.Feature(f)
        clipped = ee.Feature(
            ee.Geometry(f.geometry()).intersection(feature.geometry(), ee.ErrorMargin(1))
        )
        # add area so we can drop empty intersections
        return clipped.set('area_m2', clipped.geometry().area(maxError=1))

    clipped = ee.FeatureCollection(grid.map(_clip)).filter(ee.Filter.gt('area_m2', 0))

    # Add a stable split_id per cell
    size = clipped.size()
    cells = clipped.toList(size)

    def _with_id(i):
        i = ee.Number(i)
        cell = ee.Feature(cells.get(i))
        return cell.set('split_id', ee.String('cell_').cat(i.format('%d')))

    return ee.FeatureCollection(ee.List.sequence(0, size.subtract(1)).map(_with_id))


def split_collection_covering_grid(fc, cell_size_m, proj_epsg='EPSG:3857'):
    """Apply coveringGrid to every feature in a collection and flatten."""
    fc = ee.FeatureCollection(fc)

    def _split(f):
        return grid_over_feature(f, cell_size_m, proj_epsg)

    return ee.FeatureCollection(fc.map(_split).flatten())


# Function to split a feature horizontally into N parts
def split_feature_horizontally_n(feature, n_splits):
    bounds = feature.geometry().bounds()
    coords = bounds.coordinates().get(0)

    ll = ee.List(coords).get(0)  # lower-left
    ul = ee.List(coords).get(3)  # upper-left
    lr = ee.List(coords).get(1)  # lower-right

    min_x = ee.Number(ee.List(ll).get(0))
    max_x = ee.Number(ee.List(lr).get(0))
    min_y = ee.Number(ee.List(ll).get(1))
    max_y = ee.Number(ee.List(ul).get(1))

    height = max_y.subtract(min_y).divide(n_splits)

    def make_split(i):
        i = ee.Number(i)
        y1 = min_y.add(height.multiply(i))
        y2 = y1.add(height)
        box = ee.Geometry.Rectangle([min_x, y1, max_x, y2])
        part = feature.intersection(box, ee.ErrorMargin(1))
        return part.set('split_id', ee.String('split_').cat(i.format('%d')))

    splits = ee.List.sequence(0, n_splits.subtract(1)).map(make_split)
    return ee.FeatureCollection(splits)


# Function to apply horizontal split to a collection and flatten result
def split_collection_horizontally_n(fc, n_splits):
    def split_and_collect(feature):
        return split_feature_horizontally_n(feature, ee.Number(n_splits))

    return fc.map(split_and_collect).flatten()


# Function to split a feature vertically into N parts
def split_feature_vertically_n(feature, n_splits):
    bounds = feature.geometry().bounds()
    coords = bounds.coordinates().get(0)

    ll = ee.List(coords).get(0)  # lower-left
    lr = ee.List(coords).get(1)  # lower-right
    ul = ee.List(coords).get(3)  # upper-left

    min_x = ee.Number(ee.List(ll).get(0))
    max_x = ee.Number(ee.List(lr).get(0))
    min_y = ee.Number(ee.List(ll).get(1))
    max_y = ee.Number(ee.List(ul).get(1))

    width = max_x.subtract(min_x).divide(n_splits)

    def make_split(i):
        i = ee.Number(i)
        x1 = min_x.add(width.multiply(i))
        x2 = x1.add(width)
        box = ee.Geometry.Rectangle([x1, min_y, x2, max_y])
        part = feature.intersection(box, ee.ErrorMargin(1))
        return part.set('split_id', ee.String('split_').cat(i.format('%d')))

    splits = ee.List.sequence(0, n_splits.subtract(1)).map(make_split)
    return ee.FeatureCollection(splits)


# Function to apply split to a collection and flatten result
def split_collection_vertically_n(fc, n_splits):
    def split_and_collect(feature):
        return split_feature_vertically_n(feature, ee.Number(n_splits))

    return fc.map(split_and_collect).flatten()


def CreatePredictorDisturbancePolygons(
    param,
    asset_exists,
    strategy="grid",            # "auto" | "full" | "bucket" | "grid"
    buckets=10,                  # number of attribute buckets when strategy == "bucket"/"auto"
    grid_cell_m=40000,          # grid cell size for "grid"/"auto"
    random_seed=0               # seed for deterministic buckets
):
    """
    Returns:
        dict:
          - mode:        str
          - tasks:       list[ee.batch.Task]
          - asset_paths: list[str]  (full EE asset IDs)
          - subregions:  list[str]  (mirrors asset_paths for convenience)
    """
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['disturbance_polygons_predictor'])
    if exists:
        return 0

    # Helpers
    def _base_name():
        return f"{asset_dir}{param['disturbance_polygons_predictor']}"

    def _asset_path(suffix=""):
        return f"{_base_name()}{suffix}"

    created_paths = []  # track assets created in THIS run

    def _export(fc, suffix=""):
        asset_id = f"{asset_dir}{param['disturbance_polygons_predictor']}{suffix}"
        if asset_exists(asset_id):
            print(f"exists, skipping: {asset_id}")
            return None, asset_id
        desc = param['disturbance_polygons_predictor'] + suffix
        task = bnet.export_feature_collection(fc, desc, asset_dir)  # starts inside your wrapper
        created_paths.append(asset_id)  # record only when we actually create one
        return task, asset_id

    def _vectorize(img):
        # Centralized call in case you want to tune defaults
        # (e.g., tileScale, maxPixels, geometryType, simplification)
        return bnet.vectorize_disturbance(img, param)

    # 0) Short-circuit if a single unsuffixed asset already exists (covers full-case re-runs)
    if strategy in ("auto", "full") and asset_exists(_asset_path()):
        return {"mode": "full", "tasks": [], "asset_paths": [_asset_path()], "created_asset_paths": created_paths, "subregions": [_asset_path()]}

    # 1) Load change image
    change_img = ee.Image(asset_dir + param["predictor_change_img"])

    # ---------- Attempt 1: FULL AOI ----------
    def attempt_full():
        polys = _vectorize(change_img)
        # Preflight: force a tiny evaluation before starting any export
        ee.Number(polys.size()).getInfo()
        task, path = _export(polys, "")
        return {"mode": "full", "tasks": [task], "asset_paths": [path], "created_asset_paths": created_paths, "subregions": [path]}

    # ---------- Attempt 2: ATTRIBUTE BUCKETS (no spatial slicing) ----------
    # Build a deterministic "bucket" band: random integer in [0, buckets-1]
    # Using ee.Image.random(seed) yields deterministic values given the seed.
    def attempt_bucket():
        bucket_band = ee.Image.random(random_seed).multiply(buckets).toInt()
        staged = []  # (suffix, polys)

        # Pass 1: preflight all buckets
        for b in range(buckets):
            masked = change_img.updateMask(bucket_band.eq(b))
            polys = _vectorize(masked)
            ee.Number(polys.size()).getInfo()    # <- preflight
            staged.append((f"_b{b:02d}", polys))

        # Pass 2: start exports only if ALL preflights passed
        tasks, paths = [], []
        for suffix, polys in staged:
            t, p = _export(polys, suffix)
            if t:
                tasks.append(t)
                paths.append(p)
        if not tasks:
            raise RuntimeError("Bucket strategy produced no tasks.")
        return {"mode": "bucket", "tasks": tasks, "asset_paths": paths, "created_asset_paths": created_paths, "subregions": paths}

    # ---------- Attempt 3: SPATIAL GRID (last resort) ----------
    def attempt_grid():
        print('grid')
        split_fc = split_collection_covering_grid(param["aoi"], int(grid_cell_m))
        count = split_fc.size().getInfo()
        feats = split_fc.toList(count)

        staged = []  # (suffix, polys)
        # Pass 1: preflight every cell
        for i in range(count):
            fe = ee.Feature(feats.get(i))
            sid = fe.get('split_id')
            sid = (ee.String(sid).getInfo() if sid is not None else f"cell_{i}")
            polys = _vectorize(change_img.clip(fe))
            ee.Number(polys.size()).getInfo()    # <- preflight
            staged.append((f"_{sid}", polys))

        # Optional: export the grid itself after preflight succeeds
        try:
            _export(split_fc, f"_grid_{int(grid_cell_m)}m")
        except Exception as e:
            print(f"Grid export failed (non-fatal): {e}")

        # Pass 2: start exports
        tasks, paths = [], []
        for suffix, polys in staged:
            t, p = _export(polys, suffix)
            if t:
                tasks.append(t)
                paths.append(p)
        if not tasks:
            raise RuntimeError("Grid strategy produced no tasks.")
        return {"mode": "grid", "tasks": tasks, "asset_paths": paths, "created_asset_paths": created_paths, "subregions": paths}

    # ---------- Strategy selection & cascade ----------
    # You can force a strategy, or let "auto" cascade through them.
    if strategy == "full":
        attempts = [attempt_full]
    elif strategy == "bucket":
        attempts = [attempt_bucket]
    elif strategy == "grid":
        attempts = [attempt_grid]
    elif strategy == "auto":
        attempts = [attempt_full, attempt_bucket, attempt_grid]
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    last_err = None
    for fn in attempts:
        try:
            return fn()
        except Exception as e:
            print(f"{fn.__name__} failed: {e}")
            last_err = e

    # If we reach here, all attempts failed
    raise RuntimeError(f"All strategies failed. Last error: {last_err}")


def merge_selected_feature_collections(asset_folder, id_suffixes, output_asset_id, description="MergedExport"):
    # List assets in the folder
    asset_list = ee.data.listAssets({'parent': asset_folder})['assets']
    # Filter for FeatureCollections whose names end with any suffix in id_suffixes
    fc_ids = []

    for asset in asset_list:
        if asset['type'] == 'TABLE':
            for suffix in id_suffixes:
                # Convert ee.String to Python string
                suffix_str = ee.String(suffix).getInfo() if isinstance(suffix, ee.String) else str(suffix)
                if asset['name'].endswith(suffix_str):
                    fc_ids.append(asset['name'])
                    break  # Stop checking other suffixes once a match is found
    if not fc_ids:
        raise ValueError("No matching FeatureCollections found for the provided suffixes.")

    # Load and merge FeatureCollections
    fc_list = [ee.FeatureCollection(fc_id) for fc_id in fc_ids]
    merged_fc = ee.FeatureCollection(fc_list).flatten()

    # Prepare export task (to asset)
    task = ee.batch.Export.table.toAsset(
        collection=merged_fc,
        description=description,
        assetId=asset_folder + output_asset_id
    )
    task.start()
    return task


# ----------------------------------------------------------------------------
# Attribute disturbance polygons with base imagery
# ----------------------------------------------------------------------------
def attributeTrainingPolygons(param, asset_exists):
    exists = asset_exists(param["assetDir_t"] + param['attributed_polygons_training'])
    if exists:
        return

    gee_attributed_fc = bnet.attribute_with_reference_data(param, 'training')

    # reproject and change feature collecton to json
    reprojected_geojson = bnet.feature_collection_to_geojson(gee_attributed_fc, param['source_epsg'], param['target_epsg'])

    # attribute with Cmonster
    event_polygons_attri1 = bnet.attribute_with_cmonster_data(reprojected_geojson, param['cMonster_img_path'])

    # reproject and convert to feature collection
    reprojected_fc = bnet.geojson_to_ee_feature(event_polygons_attri1, param['target_epsg'], param['source_epsg'])

    task = bnet.export_feature_collection(reprojected_fc, param['attributed_polygons_training'], param['assetDir_t'])
    return task


def attributePredictorPolygons(param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['attributed_polygons_predictor'])
    if exists:
        return

    gee_attributed_fc = bnet.attribute_with_reference_data(param, 'predictor')
    task = bnet.export_feature_collection(gee_attributed_fc, param['attributed_polygons_predictor'], asset_dir)
    return task


def attributeTrainingPoints(param, asset_exists):
    """
    Build and export the point-based attributed training table - the
    opt-in alternative to attributed_polygons_training (see
    bnet.build_attributed_training_points's docstring). Requires:
    - param['training_points_source']: full asset path to the real
      analyst-interpreted points.
    - param['training_points_year']: the year those points were
      interpreted against.
    - param['training_points_b2_asset']/['training_points_fitted_img_asset']/
      ['training_points_change_img_asset']: full asset paths to that
      year's real B2/fitted/change predictor data. Deliberately separate
      from param['assetDir']/['fitted_img_p']/['predictor_change_img'] -
      training_points_year is very often a different, already-real
      historical production year from whatever new run this executes
      during (a real case: columbia-mts-bugnet's training points are
      keyed to 2019, living in the pre-existing 2019-v3/ folder,
      independent of the new folder the current run itself builds).
    - param['attributed_points_training']: output asset name, exported
      under param['assetDir_t'] to match attributed_polygons_training's
      own per-region storage convention.
    """
    exists = asset_exists(param["assetDir_t"] + param['attributed_points_training'])
    if exists:
        return

    points = ee.FeatureCollection(param['training_points_source'])
    gee_attributed_fc = bnet.build_attributed_training_points(
        param,
        points,
        param['training_points_year'],
        param['training_points_b2_asset'],
        param['training_points_fitted_img_asset'],
        param['training_points_change_img_asset'],
    )
    task = bnet.export_feature_collection(gee_attributed_fc, param['attributed_points_training'], param['assetDir_t'])
    return task


# ----------------------------------------------------------------------------
# Classify polygons
# ----------------------------------------------------------------------------
def classify_polygons(param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['classified_fc'])
    if exists:
        return

    # Opt-in (default 'legacy_2012', preserves existing behavior when
    # omitted): 'point_labels' trains on real analyst-interpreted point
    # data (see attributeTrainingPoints/bnet.build_attributed_training_
    # points) instead of the stale, single 2012 polygon set - kept
    # selectable via config, at explicit user request, for direct
    # comparison against the existing training set rather than replacing
    # it outright.
    training_source = param.get('classification_training', 'legacy_2012')
    if training_source == 'point_labels':
        labeled_fc = ee.FeatureCollection(param['assetDir_t'] + param['attributed_points_training'])
    elif training_source == 'legacy_2012':
        labeled_fc = ee.FeatureCollection(param['assetDir_t'] + param['attributed_polygons_training'])
    else:
        raise NotImplementedError(
            f"classify_polygons: unsupported param['classification_training'] = {training_source!r}. "
            "Use 'legacy_2012' (default) or 'point_labels'."
        )

    unlabeled_fc = ee.FeatureCollection(asset_dir + param['attributed_polygons_predictor'])

    # Opt-in (default off, preserves existing behavior when omitted):
    # veto candidate polygons that spatiotemporally overlap a real WFIGS
    # fire perimeter, removing them before classification instead of
    # relying on classify_features'/filter_by_mode_value's indirect
    # size/magnitude/classification-code heuristics to catch fire.
    if param.get('wfigs_fire_veto', False):
        unlabeled_fc = bnet.remove_wfigs_fire_polygons(unlabeled_fc)

    # point_labels only (legacy_2012 stays exactly as before) - see
    # bnet.add_terrain_road_predictors's docstring for why this can't
    # live in the shared attribute_with_reference_data step instead.
    if training_source == 'point_labels':
        labeled_fc = bnet.add_terrain_road_predictors(labeled_fc)
        unlabeled_fc = bnet.add_terrain_road_predictors(unlabeled_fc)

    predictor_variables = unlabeled_fc.first().propertyNames()
    labeled_fc = bnet.drop_null_features(labeled_fc, predictor_variables).filter(ee.Filter.neq('mode_value', 160))
    unlabeled_fc = bnet.drop_null_features(unlabeled_fc, predictor_variables)

    # point_labels only (legacy_2012 stays exactly as before) - see
    # bnet.balance_training_classes's docstring for the real cross-
    # validated recall/precision tradeoff this represents.
    if training_source == 'point_labels':
        labeled_fc = bnet.balance_training_classes(labeled_fc, 'mode_value')

    trained_classifier = bnet.train_classifier(labeled_fc, "mode_value", predictor_variables, param['num_trees'])

    # Opt-in (default off, point_labels only, preserves existing behavior
    # when omitted): use per-feature classifier confidence to resolve
    # low-confidence calls instead of trusting the bare hard label -
    # see bnet.wfigs_confidence_tiebreak/probability_weighted_spatial_
    # smoothing/flag_review_polygons' docstrings. review_flag_thresholds
    # alone (without either override technique) is enough to turn this
    # on too, since exportReviewFlaggedPolygons needs the same real
    # 'confidence' property classify_features() never produces.
    use_confidence = training_source == 'point_labels' and (
        param.get('wfigs_confidence_tiebreak', False)
        or param.get('probability_spatial_smoothing', False)
        or bool(param.get('review_flag_thresholds'))
    )
    if use_confidence:
        class_values = labeled_fc.aggregate_array('mode_value').distinct().getInfo()
        classified_fc = bnet.classify_features_with_confidence(
            unlabeled_fc, trained_classifier, class_values, param['class_heavy']
        )
        if param.get('wfigs_confidence_tiebreak', False):
            classified_fc = bnet.wfigs_confidence_tiebreak(param, classified_fc)
        if param.get('probability_spatial_smoothing', False):
            classified_fc = bnet.probability_weighted_spatial_smoothing(classified_fc, class_values=class_values)
    else:
        classified_fc = bnet.classify_features(unlabeled_fc, trained_classifier, param['class_heavy'])

    task = bnet.export_feature_collection(classified_fc, param['classified_fc'], asset_dir)
    return task


# ----------------------------------------------------------------------------
# Export a QA layer of low-confidence classifications for analyst review
# ----------------------------------------------------------------------------
def exportReviewFlaggedPolygons(param, asset_exists):
    """
    Opt-in (default off, point_labels only): export the subset of
    param['classified_fc'] (C1) whose confidence falls below its own
    predicted class's threshold in param['review_flag_thresholds'] - a
    dict of {class_value_as_string: threshold}, e.g. {'20': 66.0, '21':
    54.9, '30': 82.6, '40': 71.0, '50': 49.9} (real values derived live
    via 5-fold CV, see bnet.flag_review_polygons' docstring for how).

    Supplementary QA export only - does not gate, filter, or otherwise
    change the main classify_polygons/filter_classes/... product path,
    which still carries every candidate regardless of confidence.
    """
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    review_asset_name = param.get('review_flagged_polygons', f"review_flagged_polygons_{param['target']}")
    exists = asset_exists(asset_dir + review_asset_name)
    if exists:
        return

    classified_fc = ee.FeatureCollection(asset_dir + param['classified_fc'])
    flagged = bnet.flag_review_polygons(classified_fc, param['review_flag_thresholds'])
    flagged = flagged.filter(ee.Filter.eq('review_flag', 1))

    task = bnet.export_feature_collection(flagged, review_asset_name, asset_dir)
    return task


# ----------------------------------------------------------------------------
# Create high-disturbance mask from classified polygons
# ----------------------------------------------------------------------------
def filter_classes(param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['filtered_classes'])
    if exists:
        return

    classified_fc = ee.FeatureCollection(asset_dir + param['classified_fc'])

    # See bnet.resolve_exclusion_classes' docstring for the full rationale.
    # This decides which classes get carved out of the residual change
    # space (the exclusion mask), which is NOT the same question as which
    # classes are valid classifier output (classified_fc keeps all of them
    # regardless, as does exportReviewFlaggedPolygons).
    mode, exclusion_classes = bnet.resolve_exclusion_classes(param)
    if mode == 'legacy_range':
        print("filter_classes: legacy numeric-range exclusion, classification in (19,41) or (60,90)")
        fc1 = bnet.filter_by_mode_value(classified_fc, 19, 41, 60, 90)
    else:
        print(f"filter_classes: {mode} exclusion_classes={exclusion_classes}")
        fc1 = classified_fc.filter(ee.Filter.inList('classification', exclusion_classes))

    task = bnet.export_feature_collection(fc1, param['filtered_classes'], asset_dir)
    return task


def buffer_classed_polygons(param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['buffered_classes'])
    if exists:
        return

    fc1 = ee.FeatureCollection(asset_dir + param['filtered_classes'])
    fc2 = bnet.buffer_features(fc1, 100)

    # High Magnitude -- makes a raster mask from vector layer of clear cuts fire etc
    if param['wild_path']["on"]:
        # Build an "intersects" condition using geometry fields
        cond = ee.Filter.intersects(
            leftField='.geo',   # geometry of 'many'
            rightField='.geo'   # geometry of 'few'
        )
        # Inverted join: keep features from 'many' that do NOT intersect anything in 'few'
        many_without_few = ee.Join.inverted().apply(
            primary=fc2,
            secondary=ee.FeatureCollection(param['wild_path']['path']).merge(ee.FeatureCollection(param['wild_path']['path2'])),
            condition=cond
        )

        # Filter to class 40 (fire) and merge with the non-intersecting features
        fire = fc2.filter(ee.Filter.eq('classification', 40))
        out = fire.merge(many_without_few)
    else:
        out = bnet.buffer_features(fc1, 100)

    task = bnet.export_feature_collection(out, param['buffered_classes'], asset_dir)
    return task


def rasterize_classed_polygons(param, asset_exists):
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param['rasterize_classes'])
    if exists:
        return

    fc2 = ee.FeatureCollection(asset_dir + param['buffered_classes'])
    img = bnet.rasterize_polygons(fc2, 'classification', param['pixel_scale'], region=param['aoi'])
    task = bnet.export_image(img, param, asset_dir, param['rasterize_classes'])
    return task
