import ee
import os
import sys
import re
import time
#from datetime import date
import datetime
#from parameters import blue_mt_config_opt3_2023 as bnet_config
import bnet as bnet
from cli_utils import gui, load_parameters, walk_assets
from export_utils import dict_to_feature_collection, export_assets
from pipeline_modes import apply_public_read_acl, run_mode_1, run_mode_2
from postprocess_utils import (
	add_area_and_pct_affected_by_pixel_count,
	buffer_bnet_polygons,
	calc_attri_fields,
	extract_zonal_stats,
	get_unique_pixel_values,
	merge_buffer_buckets_and_finish,
	polygonize_bnet,
	prompt_reclassification_mapping,
	reclassify_image,
	split_multi_polygon_ss,
)


# Authenticate the Earth Engine API (uncomment if needed for authentication)
#ee.Authenticate(force=True)

# Initialize the Earth Engine API with a specific project

##############################################################################
# Wait for Task to complete
##############################################################################
def wait_for_task(task):
    counter = 0
    if not task:
        return 0
    while task.status()['state'] in ['READY', 'RUNNING']:
        print(f"\rTask {task.id} is still running...{counter} min", end='', flush=True)
        time.sleep(60)  # Wait for 30 seconds before checking again
        counter+=1
    if task.status()['state'] == 'COMPLETED':
        print(f"Task {task.id} completed successfully!")
        return 1
    else:
        print(f"Task {task.id} failed with error: {task.status()['error_message']}")
        return 0

##############################################################################
# delete assets
##############################################################################

def delete_assets(asset_ids, dry_run=False, pause_sec=0.2):
    """
    Delete a list of Earth Engine assets.
    - dry_run=True: only prints what would be deleted.
    - pause_sec: tiny pause between deletions to avoid rate limits.
    """
    # Ensure plain Python strings
    asset_ids = [str(a) for a in asset_ids]

    for aid in asset_ids:
        try:
            # Check existence first (avoids noisy 404s)
            ee.data.getAsset(aid)  # raises if missing
            if dry_run:
                print(f"[dry-run] would delete: {aid}")
            else:
                ee.data.deleteAsset(aid)
                print(f"deleted: {aid}")
                time.sleep(pause_sec)
        except Exception as e:
            print(f"skip {aid}: {e}")


##############################################################################
# Wait for Task to complete
##############################################################################
def asset_exists(asset_id):
    try:
        # Attempt to get information about the asset.
        asset_info = ee.data.getAsset(asset_id)
        if asset_info:
            print(f"Asset exists: {asset_id}", flush=False)
            return True
    except ee.EEException as e:
        # If the asset does not exist, an exception will be raised.
        print(f"Asset does not exist: {asset_id}", flush=False)
        return False


##############################################################################
# Create Base Imagery and disturbance Polygons
##############################################################################
def CreateTrainingFittedImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['fitted_img_t'])

	if exists:

		return

	else:
		fitted_img_t = bnet.get_fitted_stack(lt,'fitted_training',param)
		task = bnet.export_image(fitted_img_t.int16(),param, param['assetDir_t'],param['fitted_img_t'],param['pixel_scale'])
		return task

def CreatePredictorFittedImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['fitted_img_p'])

	if exists:

		return

	else:
		treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()		
		fitted_img_p = bnet.get_fitted_stack(lt,'fitted_predictor',param).mask(treeMask).int16()
		task = bnet.export_image(fitted_img_p.int16(),param, param['assetDir'],param['fitted_img_p'],param['pixel_scale'])
		return task

##############################################################################
# 
##############################################################################
def CreateTrainingChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['training_change_img'])

	if exists:

		return

	else:

		param['change_params']['years'] = {'start': 2007, 'end': 2012}
		change_img_t = lt.get_change_map(param['change_params'])
		task = bnet.export_image(change_img_t, param, param['assetDir_t'],param['training_change_img'],param['pixel_scale'])
		return task

##############################################################################
# 
##############################################################################
def CreatePredictorChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['predictor_change_img'])

	if exists:

		return

	else:
		#param['change_params']['years'] = {'start': param['composite_params']['end_date'].year-6, 'end': param['composite_params']['end_date'].year}
		treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()		
		change_img_p = lt.get_change_map(param['change_params']).mask(treeMask)
		task = bnet.export_image(change_img_p,param, param['assetDir'],param['predictor_change_img'],param['pixel_scale'])

		return task

##############################################################################
# 
##############################################################################
def CreateTrainingDisturbancePolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['disturbance_polygons_training'])

	if exists:

		return

	else:

		change_img_t = ee.Image(param["assetDir_t"]+param['training_change_img']) #.unmask().clip(param['aoi'])
		disturbance_polygons_t = bnet.vectorize_disturbance(change_img_t,param)
		task = bnet.export_feature_collection(disturbance_polygons_t,param['disturbance_polygons_training'],param['assetDir_t'])
		return task

##############################################################################
# 
##############################################################################
# Grid a feature with square cells of `cell_size` meters (uses EPSG:3857)
def grid_over_feature(feature, cell_size_m, proj_epsg='EPSG:3857'):
    """Build a covering grid (square cells ~cell_size_m) over one feature."""
    feature = ee.Feature(feature)
    proj = ee.Projection(proj_epsg).atScale(cell_size_m)

    # Covering grid over the feature’s bounds in the chosen projection
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

##############################################################################
# 
##############################################################################
def split_collection_covering_grid(fc, cell_size_m, proj_epsg='EPSG:3857'):
    """Apply coveringGrid to every feature in a collection and flatten."""
    fc = ee.FeatureCollection(fc)
    def _split(f):
        return grid_over_feature(f, cell_size_m, proj_epsg)
    return ee.FeatureCollection(fc.map(_split).flatten())


##############################################################################
# 
##############################################################################
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

##############################################################################
# 
##############################################################################
# Function to apply horizontal split to a collection and flatten result
def split_collection_horizontally_n(fc, n_splits):
    def split_and_collect(feature):
        return split_feature_horizontally_n(feature, ee.Number(n_splits))
    return fc.map(split_and_collect).flatten()

##############################################################################
# 
##############################################################################
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

##############################################################################
# 
##############################################################################
# Function to apply split to a collection and flatten result
def split_collection_vertically_n(fc, n_splits):
    def split_and_collect(feature):
        return split_feature_vertically_n(feature, ee.Number(n_splits))
    return fc.map(split_and_collect).flatten()


##############################################################################
# 
##############################################################################
def CreatePredictorDisturbancePolygons(
    param,
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
    # check to see if output asset exists
    exists = asset_exists(param["assetDir"]+param['disturbance_polygons_predictor'])

    if exists:
        return 0
    # Helpers
    def _base_name():
        return f"{param['assetDir']}{param['disturbance_polygons_predictor']}"

    def _asset_path(suffix=""):
        return f"{_base_name()}{suffix}"

    created_paths = []  # track assets created in THIS run

    def _export(fc, suffix=""):
        asset_id = f"{param['assetDir']}{param['disturbance_polygons_predictor']}{suffix}"
        if asset_exists(asset_id):
            print(f"exists, skipping: {asset_id}")
            return None, asset_id
        desc = param['disturbance_polygons_predictor'] + suffix
        task = bnet.export_feature_collection(fc, desc, param['assetDir'])  # starts inside your wrapper
        created_paths.append(asset_id)  # record only when we actually create one
        return task, asset_id

    def _vectorize(img):
        # Centralized call in case you want to tune defaults
        # (e.g., tileScale, maxPixels, geometryType, simplification)
        return bnet.vectorize_disturbance(img, param)

    # 0) Short-circuit if a single unsuffixed asset already exists (covers full-case re-runs)
    if strategy in ("auto", "full") and asset_exists(_asset_path()):
        return {"mode": "full", "tasks": [], "asset_paths": [_asset_path()], "created_asset_paths": created_paths,"subregions": [_asset_path()]}

    # 1) Load change image
    change_img = ee.Image(param["assetDir"] + param["predictor_change_img"])

    # ---------- Attempt 1: FULL AOI ----------
    def attempt_full():
        polys = _vectorize(change_img)
        # Preflight: force a tiny evaluation before starting any export
        ee.Number(polys.size()).getInfo()
        task, path = _export(polys, "")
        return {"mode": "full", "tasks": [task], "asset_paths": [path], "created_asset_paths": created_paths,"subregions": [path]}

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
            if t: tasks.append(t); paths.append(p)
        if not tasks:
            raise RuntimeError("Bucket strategy produced no tasks.")
        return {"mode": "bucket", "tasks": tasks, "asset_paths": paths, "created_asset_paths": created_paths,"subregions": paths}

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
            if t: tasks.append(t); paths.append(p)
        if not tasks:
            raise RuntimeError("Grid strategy produced no tasks.")
        return {"mode": "grid", "tasks": tasks, "asset_paths": paths,"created_asset_paths": created_paths, "subregions": paths}

    # ---------- Strategy selection & cascade ----------
    # You can force a strategy, or let "auto" cascade through them.
    attempts = []
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


##############################################################################
# 
##############################################################################
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
        assetId=asset_folder+output_asset_id
    )
    task.start()
    return task
##############################################################################
# Attribute Disturbance Polygons with Base Imagery 
##############################################################################
def attributeTrainingPolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['attributed_polygons_training'])

	if exists:

		return

	else:

		gee_attributed_fc = bnet.attribute_with_reference_data(param,'training')

		# reproject and change feature collecton to json
		reprojected_geojson = bnet.feature_collection_to_geojson(gee_attributed_fc, param['source_epsg'], param['target_epsg'])    # apply reprojections and feature collectio>

		# attribute with Cmonster
		event_polygons_attri1 = bnet.attribute_with_cmonster_data(reprojected_geojson,param['cMonster_img_path'])                   # apply attribution (cMonster)

		# reproject and convert to featrue collection
		reprojected_fc = bnet.geojson_to_ee_feature(event_polygons_attri1, param['target_epsg'], param['source_epsg'])           # apply re-reprojection and geojson to featur>

		# export
		task = bnet.export_feature_collection(reprojected_fc,param['attributed_polygons_training'],param['assetDir_t'] )

		return task


def attributePredictorPolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['attributed_polygons_predictor'])

	if exists:

		return

	else:
		gee_attributed_fc = bnet.attribute_with_reference_data(param,'predictor')
		task = bnet.export_feature_collection(gee_attributed_fc,param['attributed_polygons_predictor'],param['assetDir'] )
		return task

##############################################################################
# Classify Polygons 
##############################################################################
def classify_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['classified_fc'])

	if exists:

		return

	else:

		labeled_fc = ee.FeatureCollection(param['assetDir_t']+param['attributed_polygons_training']) #.filter(ee.Filter.lt('mode_value',101))
		unlabeled_fc = ee.FeatureCollection(param['assetDir']+param['attributed_polygons_predictor'])

		predictor_variables = unlabeled_fc.first().propertyNames()
		labeled_fc = bnet.drop_null_features(labeled_fc,predictor_variables).filter(ee.Filter.neq('mode_value', 160))
		unlabeled_fc = bnet.drop_null_features(unlabeled_fc,predictor_variables)

		trained_classifier = bnet.train_classifier(labeled_fc,"mode_value",predictor_variables,param['num_trees'])
		classified_fc = bnet.classify_features(unlabeled_fc, trained_classifier,param['class_heavy'])

		task = bnet.export_feature_collection(classified_fc,param['classified_fc'],param['assetDir'])
		return task

##############################################################################
# Create High Disturbance Mask From Polygons 
##############################################################################
def filter_classes(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['filtered_classes'])

	if exists:

		return

	else:
		fc1 = bnet.filter_by_mode_value(ee.FeatureCollection(param['assetDir'] + param['classified_fc']), 19, 41, 60, 90)

		task = bnet.export_feature_collection(fc1, param['filtered_classes'], param['assetDir'])

		return task

##############################################################################
# 
##############################################################################
def buffer_classed_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['buffered_classes'])
	if exists:

		return

	else:
		fc1 = ee.FeatureCollection(param["assetDir"]+param['filtered_classes'])
		fc2 = bnet.buffer_features(fc1, 100)

		#High Magnitude -- makes a raster mask from vector layer of clear cuts fire etc 
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

		task = bnet.export_feature_collection(out, param['buffered_classes'], param['assetDir'])
		return task

##############################################################################
# 
##############################################################################
def rasterize_classed_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['rasterize_classes'])

	if exists:

		return

	else:
		fc2 = ee.FeatureCollection(param["assetDir"]+param['buffered_classes'])
		img = bnet.rasterize_polygons(fc2, 'classification', param['pixel_scale'], region=param['aoi'])
		task = bnet.export_image(img, param, param['assetDir'],param['rasterize_classes'])

		return task



##############################################################################
# Create forest mask
##############################################################################
def CreateForestMask(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['forestMaskName'])

	if exists:

		return

	mtbs = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")

	# LCMS forest mask
	#lcms_mask = bnet.lcms_forest_mask( param['target']-5, param['target'], param).clip(param['aoi'])
	lcms_mask = bnet.lcms_forest_mask( 2024, param['target'], param).clip(param['aoi'])

	#reflectance mask
	tassMap = bnet.tasselCapMask(param)

	highMagChange_img = param['ltchange'].gt(0).unmask().Not()


	#Fire mask - filter MTBS dataset by date 
	fires = mtbs.filter(
		ee.Filter.And(
			ee.Filter.gte("Ig_Date", param['maskStartTime']),
			ee.Filter.lte("Ig_Date", param['maskEndTime'])
		)
	)

	# change MTBS dataset to raster binary
	fire_img = fires.reduceToImage(properties=["Map_ID"], reducer=ee.Reducer.mean()) \
                	.gt(0) \
                	.unmask() \
                	.Not()

	# takes the product of all the  mask
	mask = lcms_mask.clip(param['aoi']) \
			.multiply(highMagChange_img) \
			.multiply(fire_img) \
			.multiply(tassMap) \
			.updateMask(ee.ImageCollection('JRC/GFC2020/V2').mosaic()) \


	# export image mask
	task_mask = ee.batch.Export.image.toAsset(
		#image=ee.Image(param['LTSDdir'] + param['LTSDname']).select([0]).multiply(0).add(1).byte(),
		image=mask.byte(),
 		description=param['forestMaskName'],
		assetId=param["assetDir"]+param['forestMaskName'],
		region=param['aoi'].geometry(),
		scale=param['pixel_scale'],
		maxPixels=1e13
	)
	task_mask.start()

	return task_mask
##############################################################################
# Create forest mask
##############################################################################
def CreateForestMaskVis(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['forestMaskName']+"_label")

	if exists:

		return

	mtbs = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")

	lcms  = bnet.lcms_forest_mask(2024, param['target'], param).unmask(0).toInt()      # 0/1
	tass  = bnet.tasselCapMask(param).unmask(0).toInt()                                 # 0/1
	high  = param['ltchange'].gt(0).unmask(0).toInt()                                   # 0/1
	fire  = mtbs.filter(ee.Filter.And(ee.Filter.gte("Ig_Date", param['maskStartTime']),ee.Filter.lte("Ig_Date", param['maskEndTime']))).reduceToImage(["Map_ID"], ee.Reducer.mean()).gt(0).unmask(0).toInt()      # 0/1

	# code = (tass<<3) | (fire<<2) | (high<<1) | (lcms<<0)
	mask_code = (lcms.bitwiseOr(high.leftShift(1)).bitwiseOr(fire.leftShift(2)).bitwiseOr(tass.leftShift(3)).toInt16().clip(param['aoi']).updateMask(ee.ImageCollection('JRC/GFC2020/V2').mosaic()))

	# export image mask
	task_mask = ee.batch.Export.image.toAsset(
		#image=ee.Image(param['LTSDdir'] + param['LTSDname']).select([0]).multiply(0).add(1).byte(),
		image=mask_code.int16(),
 		description=param['forestMaskName']+"_label",
		assetId=param["assetDir"]+param['forestMaskName']+"_label",
		region=param['aoi'].geometry(),
		scale=param['pixel_scale'],
		maxPixels=1e13
	)
	task_mask.start()

	return task_mask

##############################################################################
# SNIC
##############################################################################
def SNIC(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['snicName'])

	if exists:

		return

	# Get LTSD image
	ltsd = ee.Image(param['LTSDdir'] + param['LTSDname'])

	# Generate a SNIC image from the LTSD image and then mask with non-forest mask
	ltsd_snic = bnet.snic_image(ltsd).mask(param['Mask'])

	# Export image
	export_params = {
		'image': ltsd_snic.toInt16(),
		'description': param['snicName'],
		'assetId': param['assetDir'] + param['snicName'],
		'region': param['aoi'].geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13
	}

	task_snic = ee.batch.Export.image.toAsset(**export_params)

	task_snic.start()

	return task_snic

##############################################################################
# Declining SNIC
##############################################################################
def DecliningSNIC(param):

	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['declineName'])

	if exists:

		return

	# Apply the function
	snic_decline = bnet.SNIC_decline_image(ee.Image(param['assetDir'] + param['snicName']),param['target'])#.updateMask(param['Mask'])

	# Export the image
	export_params = {
		'image': snic_decline.toInt16(),
		'description': param['declineName'],
		'assetId': param['assetDir'] + param['declineName'],
		'region': param['aoi'].geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13
	}

	task_decline_snic = ee.batch.Export.image.toAsset(**export_params)

	task_decline_snic.start()

	return task_decline_snic

##############################################################################
# Declining LTSD
##############################################################################
def DecliningLTSD(param):

	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['declineName'])

	if exists:

		return

	# Apply the function
	#decline = bnet.LTSD_decline_image(ee.Image(param['assetDir'] + param['fitted_img_p']),param['ltendYear']).updateMask(param['Mask'])
	#decline = bnet.decline_image(param).updateMask(param['Mask'])
	decline = bnet.LTSD_decline_score(param).updateMask(param['Mask'])

	# Export the image
	export_params = {
		'image': decline.toInt16(),
		'description': param['declineName'],
		'assetId': param['assetDir'] + param['declineName'],
		'region': param['aoi'].geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13
	}

	task_decline = ee.batch.Export.image.toAsset(**export_params)

	task_decline.start()

	return task_decline


##############################################################################
# Sample for Kmeans build 
##############################################################################
# Keep your own implementation if you already have one.
def _asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except Exception:
        return False

def _wait_for_task(task: ee.batch.Task, poll_seconds=20, timeout_minutes=180, on_update=None):
    """
    Polls until terminal state. Returns the final status dict.
    No prints; uses on_update(str) if provided.
    """
    start = time.time()
    last_state = None
    while True:
        status = task.status()
        state = status.get('state')
        if state != last_state and on_update:
            on_update(f"[GEE task {task.id}] state={state}")
            last_state = state

        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            return status

        if timeout_minutes and (time.time() - start) > timeout_minutes * 60:
            try:
                task.cancel()
            except Exception:
                pass
            status["state"] = "CANCELLED"
            status["error_message"] = f"Timed out after {timeout_minutes} minutes."
            return status

        time.sleep(poll_seconds)

def buildKMeansSample(param,
                      poll_seconds=20,
                      timeout_minutes=180,
                      overwrite=False,
                      progress_cb=None):
    """
    Tries methods in order; for each:
      - build FC (lazy)
      - start Export.table.toAsset
      - wait for completion
      - on failure/timeout => try next method
    No printing. Returns {'final_state', 'assetId', 'attempts'}.
    """
    def log(msg):
        if progress_cb:  # caller controls any output
            progress_cb(msg)

    asset_id = f"{param['assetDir']}{param['kmeansName']}_sample"
    desc_base = f"{param['kmeansName']}_sample"

    if _asset_exists(asset_id):
        if not overwrite:
            return {'final_state': 'ALREADY_EXISTS', 'assetId': asset_id, 'attempts': []}
        # else continue to overwrite

    decline = ee.Image(param['assetDir'] + param['declineName'])
    aoi = param['aoi']
    scale = param['pixel_scale']
    n = int(param['kmeans_num_sample'])
    class_band = param.get('class_band')

    attempts = [

        ("stratifiedSample", lambda: decline.stratifiedSample(
            numPoints=200,
            classBand="decline_score",   # if missing/invalid, this attempt will fail and we move on
            region=aoi,
            scale=scale,
            geometries=True
        )),

        ("reduceToVectors-centroids", lambda: decline.reduceToVectors(
            geometry=aoi,
            scale=scale,
            geometryType='centroid',
            labelProperty='zone',
            maxPixels=1e13,
            reducer=ee.Reducer.first(),
        )),

        ("sample", lambda: ee.FeatureCollection(
            decline.sample(
                region=aoi,
                scale=scale,
                numPixels=n,
                tileScale=12,
                geometries=True
            ).randomColumn().sort('random')
        )),

        ("sampleRegions", lambda: ee.FeatureCollection(
            decline.sampleRegions(
                collection=aoi,   # must be a FeatureCollection
                scale=scale,
                geometries=True
            ).randomColumn().sort('random').toList(n)
        )),
    ]

    attempt_logs = []

    for name, builder in attempts:
        if asset_exists(asset_id):
            return {'final_state': 'COMPLETED', 'assetId': asset_id, 'attempts': attempt_logs}

        try:
            fc = builder()
        except Exception as e:
            attempt_logs.append({'name': name, 'build_error': str(e)})
            continue

        desc = f"{desc_base}__{name}"
        task = ee.batch.Export.table.toAsset(
            collection=fc,
            description=desc,
            assetId=asset_id
        )
        task.start()

        status = _wait_for_task(task,
                               poll_seconds=poll_seconds,
                               timeout_minutes=timeout_minutes,
                               on_update=log)
        attempt_logs.append({'name': name, 'task_id': task.id, 'status': status})
        state = status.get('state')

        if state == 'COMPLETED' or asset_exists(asset_id):
            return {'final_state': 'COMPLETED', 'assetId': asset_id, 'attempts': attempt_logs}
        # else try next attempt

    return {'final_state': 'FAILED', 'assetId': asset_id, 'attempts': attempt_logs}
##############################################################################
# make KMEANS iamge 
##############################################################################
def kMeansImage(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['kmeansName'])

	if exists:
		return

	# Import SNIC decline image
	decline_path = param['assetDir'] + param['declineName']
	decline = ee.Image(decline_path)

	# Get band names from the SNIC decline image -- slice first and last (SNIC seed and cluster bands)
	snic_bands = decline.bandNames().slice(1, -1)


	# Train KMeans on random sample across selected bands and number of clusters
	training = ee.Clusterer.wekaCascadeKMeans(
		param['num_of_clusters'],
		param['num_of_clusters'],
		10,
		False,
		True
	).train(
		ee.FeatureCollection(param['assetDir'] +param['kmeansNameSample']),
		snic_bands
	)

	# Apply KMeans clustering to the SNIC decline image and clip to AOI
	snic_decline_kmeans = decline.cluster(training).clip(param['aoi'])

	# Export image to assets
	export_params = {
		'image': snic_decline_kmeans.toInt16(),
		'description': param['kmeansName'],
		'assetId': param['assetDir'] + param['kmeansName'],
		'region': param['aoi'].geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13
	}

	task_kmeans = ee.batch.Export.image.toAsset(**export_params)
	task_kmeans.start()
	return task_kmeans

##############################################################################
# Kmeans Proportion of Intersection with ADS sample
##############################################################################
def kMeansProporitonsADSsample(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['KmeansVector'])

	if exists:
		return

	# ADS filtering
	ads = param['ads'].filterBounds(param['aoi']) #.filter(ee.Filter.eq('SURVEY_YEA', 2022))

	# Define AOI
	aoi = param['aoi']

	# KMeans image histogram
	kmeans = ee.Image(param['assetDir'] + param['kmeansName']).rename(['kmeans_clusters'])

	# ADS image histogram
	kmeansV = kmeans.reduceToVectors(reducer=ee.Reducer.countEvery(), geometry=aoi.geometry(),tileScale=12 ,maxPixels=1e13)

	# Calculate proportion attributes
	def calculate_proportion_attri(p):
		ads_g = ads.geometry()
		p_geometry = p.geometry()
		p = ee.Feature(ee.Algorithms.If(ads_g.intersects(p_geometry, 1), p.set('touch', 1), p.set('touch', 0)))
		return p

	proportion_attri = kmeansV.map(calculate_proportion_attri)

	# Export to asset
	export_params = {
		'collection': proportion_attri,
		'description': 'kmeansVectorAttr',
		'assetId': param['assetDir'] + param['KmeansVector'],

		#'maxVertices': 100000000
	}

	task_sample = ee.batch.Export.table.toAsset(**export_params)

	task_sample.start()

	return task_sample

##############################################################################
# Calculation of proportion of intersection
##############################################################################
def proportionCalc(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['proportionName'])

	if exists:
		return

	proportion_attri = ee.FeatureCollection(param['assetDir'] + param['KmeansVector'] )

	intersect_std = proportion_attri.filter(ee.Filter.eq('touch', 1)).aggregate_stats('label').get('total_sd')
	clusters_that_touch_0 = ee.Number(proportion_attri.filter(ee.Filter.And(ee.Filter.eq('label', 0), ee.Filter.eq('touch', 1))).size())
	clusters_that_touch_1 = ee.Number(proportion_attri.filter(ee.Filter.And(ee.Filter.eq('label', 1), ee.Filter.eq('touch', 1))).size())
	clusters_that_touch_2 = ee.Number(proportion_attri.filter(ee.Filter.And(ee.Filter.eq('label', 2), ee.Filter.eq('touch', 1))).size())
	median_value = ee.Array([ee.Number(clusters_that_touch_0),ee.Number(clusters_that_touch_1),ee.Number(clusters_that_touch_2)]).reduce(ee.Reducer.median(),[0]).get([0])
	# Add proportions to clusters
	def add_proportions(f):
		cluster = f.get('label')
		clusters_that_touch = ee.Number(proportion_attri.filter(ee.Filter.And(ee.Filter.eq('label', cluster), ee.Filter.eq('touch', 1))).size())
		#bnet_value = ee.Algorithms.If(clusters_that_touch.gte(ee.Number(intersect_std).multiply(3)), 3, ee.Algorithms.If(clusters_that_touch.gte(ee.Number(intersect_std).multiply(2)), 2, 1))
		bnet_value = ee.Algorithms.If(clusters_that_touch.gte(ee.Number(median_value)), 3, ee.Algorithms.If(clusters_that_touch.eq(ee.Number(median_value)), 2, 1))
		return f.set("prop_count", clusters_that_touch).set("bnet", bnet_value)

	add_k_proportions = proportion_attri.map(add_proportions)
	feat_label = add_k_proportions.aggregate_array("label")
	feat_bnet = add_k_proportions.aggregate_array("bnet")
	feat_zip = feat_label.zip(feat_bnet).distinct().unzip()
	#corrected_label = ee.List(feat_zip.get(0)).map(lambda e: ee.String(ee.Number(e).int()))
	corrected_label = [str(int(num)) for num in feat_zip.get(0).getInfo()] 
	corrected_bnet = feat_zip.get(1)
	diclist = ee.Dictionary.fromLists(corrected_label, corrected_bnet) 

	kmeans = ee.Image(param['assetDir'] + param['kmeansName']).rename(['kmeans_clusters'])

	def label_img_function(k):
		return kmeans.eq(ee.Number.parse(k)).multiply(ee.Number(diclist.get(k))).byte()

	label_img = diclist.keys().map(label_img_function)
	sample_img = ee.ImageCollection(label_img).sum().selfMask().rename(['label'])

	# Reference image
	ref_img = ee.Image(param['assetDir'] + param['declineName'])

	if '2' in param['configName']:

		ref_img = bnet.rename_img(ref_img, param['target']).addBands(kmeans).addBands(sample_img)

	else:

		ref_img = bnet.rename_img_opt3(ref_img, param['target']).addBands(kmeans).addBands(sample_img)

	# Stratified sample
	sample = ref_img.stratifiedSample(
		numPoints=param['proportion_strat_sample_size'],
		classBand='label',
		region= param['aoi'],
		scale=param['pixel_scale'],
		tileScale=4,
		geometries=True
	)

	# Export to asset
	export_params = {
		'collection': sample,
		'description': param['proportionName']+"_sample",
		'assetId': param['assetDir'] + param['proportionName']+"_sample"
		#'maxVertices': 100000000
	}

	task_sample = ee.batch.Export.table.toAsset(**export_params)

	task_sample.start()

	export_params2 = {
		'image': sample_img,
		'description':param['proportionName'],
		'assetId': param['assetDir'] + param['proportionName'],
		'region': param['aoi'].geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13
	}

	task_proportion = ee.batch.Export.image.toAsset(**export_params2) 

	task_proportion.start()

	return task_proportion
	#return task_sample

##############################################################################
# Predict 
##############################################################################
def predict(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['predicted'])

	if exists:
		return

	# Define variables
	states = param['aoi']
	decline = ee.Image(param['assetDir'] + param['declineName'])
	kmeans_decline = ee.Image(param['assetDir'] + param['kmeansName'])
	sample = ee.FeatureCollection(param['assetDir'] + param['proportionName']+'_sample')

	# Rename the bands in the reference image
	if '2' in param['configName']:
		refer_image = bnet.rename_img(decline, param['target'])
	else:
		refer_image = bnet.rename_img_opt3(decline, param['target'])


	# Get property names and band names
	sample_fields = sample.first().propertyNames()

	ref_bands = refer_image.bandNames()

	# Split the training points by 70%/30%
	sample = sample.randomColumn()
	split = 0.70  # Roughly 70% training, 30% testing
	training = sample.filter(ee.Filter.lt('random', split))

	test = sample.filter(ee.Filter.gte('random', split))

	# Build the Random Forest classifier
	random_forest = ee.Classifier.smileRandomForest(500).train(
		features=test,
		classProperty= 'label',
		inputProperties= ref_bands.remove('clusters').remove('seeds')
	)

	# Classify using Random Forest
	#rf_model = refer_image.classify(random_forest).selfMask().clip(states).rename('bugnet_{}_{}_{}'.format(param['region'], param['target'], param['version']))
	rf_model = refer_image.classify(random_forest).selfMask().clip(states).rename('bugnet_{}'.format(param['target']))

	export_params = {
		'image': rf_model,
		'description': param['predicted'],
		'assetId': param['assetDir'] + param['predicted'],
		'region': states.geometry(),
		'scale': param['pixel_scale'],
		'maxPixels': 1e13,

	}

	# Export the classified image to assets
	export_task = ee.batch.Export.image.toAsset(**export_params)
	export_task.start()

	return export_task 

##############################################################################
# export metadata
##############################################################################
def export_parameter_file(param):
	return 0


def build_mode_dependencies():
	return {
		"ee": ee,
		"wait_for_task": wait_for_task,
		"delete_assets": delete_assets,
		"asset_exists": asset_exists,
		"walk_assets": walk_assets,
		"CreateTrainingFittedImagery": CreateTrainingFittedImagery,
		"CreatePredictorFittedImagery": CreatePredictorFittedImagery,
		"CreateTrainingChangeImagery": CreateTrainingChangeImagery,
		"CreatePredictorChangeImagery": CreatePredictorChangeImagery,
		"CreateTrainingDisturbancePolygons": CreateTrainingDisturbancePolygons,
		"CreatePredictorDisturbancePolygons": CreatePredictorDisturbancePolygons,
		"merge_selected_feature_collections": merge_selected_feature_collections,
		"attributeTrainingPolygons": attributeTrainingPolygons,
		"attributePredictorPolygons": attributePredictorPolygons,
		"classify_polygons": classify_polygons,
		"filter_classes": filter_classes,
		"buffer_classed_polygons": buffer_classed_polygons,
		"rasterize_classed_polygons": rasterize_classed_polygons,
		"CreateForestMask": CreateForestMask,
		"CreateForestMaskVis": CreateForestMaskVis,
		"DecliningLTSD": DecliningLTSD,
		"SNIC": SNIC,
		"DecliningSNIC": DecliningSNIC,
		"buildKMeansSample": buildKMeansSample,
		"kMeansImage": kMeansImage,
		"kMeansProporitonsADSsample": kMeansProporitonsADSsample,
		"proportionCalc": proportionCalc,
		"predict": predict,
		"polygonize_bnet": lambda param: polygonize_bnet(param, asset_exists),
		"buffer_bnet_polygons": lambda param: buffer_bnet_polygons(param, asset_exists),
		"merge_buffer_buckets_and_finish": lambda param, asset_ids: merge_buffer_buckets_and_finish(param, asset_ids, asset_exists),
		"get_unique_pixel_values": lambda param, region=None, scale=30: get_unique_pixel_values(param, asset_exists, region=region, scale=scale),
		"prompt_reclassification_mapping": prompt_reclassification_mapping,
		"reclassify_image": reclassify_image,
		"dict_to_feature_collection": dict_to_feature_collection,
	}

##############################################################################
# MAIN
##############################################################################
def main():

	if len(sys.argv) != 2:
		print("Usage: python main.py <parameter script path>")
		sys.exit(1)

	param_file = sys.argv[1]

	try:
		param = load_parameters(param_file)
	except Exception as e:
		print(f"Error loading parameters: {e}")
		sys.exit(1)

	ee.Initialize(project=param["project_name"])

	mode = gui()

	if mode == '3':
		export_assets(param)
		sys.exit()
	if mode == '4':
		bnet.list_and_delete_assets(param['assetDir'])
		sys.exit()


	if mode == '5':
		apply_public_read_acl(param, ee, walk_assets)

	elif mode == '1':
		run_mode_1(param, build_mode_dependencies())

	elif mode == '2':
		run_mode_2(param, build_mode_dependencies())

	else:
		print('bye')

if __name__ == "__main__":
    main()
