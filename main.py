import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
import os
import sys
import re
import time
#from datetime import date
import datetime
#from parameters import blue_mt_config_opt3_2023 as bnet_config
import bnet as bnet
import importlib.util


# Authenticate the Earth Engine API (uncomment if needed for authentication)
#ee.Authenticate(force=True)

# Initialize the Earth Engine API with a specific project

##############################################################################
# export parameter file to assets
##############################################################################
def flatten_dict(d, parent_key='', sep='_'):
    """
    Recursively flatten a nested dictionary.

    Parameters:
        d (dict): The dictionary to flatten.
        parent_key (str): The base key to prepend to each key.
        sep (str): Separator to use for concatenating keys.

    Returns:
        dict: A flattened dictionary.
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, (ee.FeatureCollection, ee.Image, ee.ImageCollection ,LandsatComposite)):
            items.append((new_key, "GEE object"))
        else:
            items.append((new_key, v))


    transformed_list = []
    for key, value in items:
        if isinstance(value, list):  # Convert list to comma-separated string
            if isinstance(value[0], int):
                value = [str(element) for element in value]
            transformed_list.append((key, ', '.join(value)))
        elif isinstance(value, tuple):  # Convert tuple to list then string
            value = list(value)
            if isinstance(value[0], int):
                value = [str(element) for element in value]
            transformed_list.append((key, ', '.join(value)))

        elif isinstance(value, datetime.date):  # Convert date object to string
            transformed_list.append((key, value.strftime('%Y-%m-%d')))
        else:  # Keep other types as they are
            transformed_list.append((key, value))


    return dict(transformed_list)

##############################################################################
# 
##############################################################################
def dict_to_feature_collection(param):
    #(data_dict, asset_path)
    """
    Converts a dictionary to a Google Earth Engine FeatureCollection and exports it.

    Parameters:
        data_dict (dict): The input dictionary to convert.
        asset_path (str): The asset path to save the FeatureCollection.

    Returns:
        None
    """
    # check to see if output asset exists
    exists = asset_exists(param["assetDir"]+param['parameter_file'])

    if exists:

        return

    else:

        # Flatten the dictionary
        flattened_data = flatten_dict(param)

        # Create a single feature with the flattened data
        feature = ee.Feature(param['aoi'].first().geometry().centroid(1), flattened_data)

        # Create a FeatureCollection
        feature_collection = ee.FeatureCollection([feature])

        # Export the FeatureCollection to the specified asset path
        task = ee.batch.Export.table.toAsset(
            collection=feature_collection,
            description=param['parameter_file'],
            assetId=param['assetDir']+param['parameter_file']
        )
        task.start()

        return task



##############################################################################
# export assets to location gdrive gbucket
##############################################################################
def list_assets(params):
    """
    Lists all assets in the specified asset directory.
    
    Parameters:
        asset_directory (str): The full path to the asset directory.
        
    Returns:
        list: A list of dictionaries with asset ID and type.
    """
    asset_list = []
    try:
        assets = ee.data.listAssets({'parent': params['assetDir']}).get('assets', [])
        for asset in assets:
            asset_list.append({'id': asset['name'], 'type': asset['type']})
    except Exception as e:
        print(f"Error accessing asset directory {asset_directory}: {e}")
    return asset_list


##############################################################################
# 
##############################################################################
def get_user_input(prompt, options):
    """Utility function to get user input with validation."""
    for idx, option in enumerate(options):
        print(f"{idx + 1}. {option}")
    choice = input("Enter your choice: ")
    while not choice.isdigit() or int(choice) < 1 or int(choice) > len(options):
        print("Invalid choice. Please try again.")
        choice = input("Enter your choice: ")
    return options[int(choice) - 1]


##############################################################################
# 
#######################remove_duplicate_substrings#######################################################
def remove_duplicate_substrings(filename):
    """
    Removes duplicate substrings in a filename.
    Substrings are defined as components separated by _ or -.
    Keeps the first occurrence of each substring and removes the others.
    Delimiters (_ and -) are preserved.
    """
    # Split into tokens AND keep delimiters
    parts = re.split(r'([_-])', filename)

    seen = set()
    cleaned_parts = []

    for part in parts:
        if part in ['_', '-']:
            # Keep delimiters exactly as they appear
            cleaned_parts.append(part)
        else:
            # Keep only first occurrence of each substring
            if part not in seen:
                cleaned_parts.append(part)
                seen.add(part)

    result = "".join(cleaned_parts)

    # 2. Collapse any mixed sequences of hyphens/underscores → single underscore
    result = re.sub(r'[_-]+', '_', result)

    # 3. Remove leading/trailing underscores if any appear
    result = result.strip('_')

    return result

##############################################################################
# 
##############################################################################
def export_to_drive(prefix, asset, folder,param):
    """Exports an asset to Google Drive."""
    if asset['type'] == 'TABLE':
        print('table')
        collection = ee.FeatureCollection(asset['id'])
        if "parameter" in asset['id']:
            print("param")
            print(f"{prefix}_{asset['id'].split('/')[-1]}")
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace('bugnet_','')
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.table.toDrive(
                collection=collection,
                description=outname3,
                folder=prefix,
                fileFormat="CSV"
            )
        else:
            print('shp')
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace('bugnet_','')
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.table.toDrive(
                collection=collection,
                description=outname3,
                folder=prefix,
                fileFormat="SHP"
            )
    elif asset['type'] == 'IMAGE':
        image = ee.Image(asset['id'])
        if "fitted" in asset['id']:
            band_names = image.bandNames()
            count = band_names.size()
            last_three = band_names.slice(count.subtract(3), count)
            last_three_bands = image.select(last_three)
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace('bugnet_','')
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.image.toDrive(
                image=last_three_bands,
                description=outname3,
                folder=prefix,
                scale=param['pixel_scale'],
                region=image.geometry().bounds(),
                maxPixels=1e13
            )
        else:
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace('bugnet_','')
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.image.toDrive(
                image=image,
                description=outname3,
                folder=prefix,
                scale=param['pixel_scale'],
                region=image.geometry().bounds(),
                maxPixels=1e13
            )
    else:
        print(f"Unsupported asset type: {asset['type']}")
        return
    task.start()
    print(f"Export task started for asset: {asset['id']} to Google Drive folder: {folder}")


##############################################################################
# 
##############################################################################
def export_to_cloud_storage(asset, bucket, path):
    """Exports an asset to Google Cloud Storage."""
    if asset['type'] == 'TABLE':
        collection = ee.FeatureCollection(asset['id'])
        task = ee.batch.Export.table.toCloudStorage(
            collection=collection,
            description=f"Export_{asset['id'].split('/')[-1]}",
            bucket=bucket,
            path=path
        )
    elif asset['type'] == 'IMAGE':
        image = ee.Image(asset['id'])
        task = ee.batch.Export.image.toCloudStorage(
            image=image,
            description=f"Export_{asset['id'].split('/')[-1]}",
            bucket=bucket,
            path=path,
            scale=param['pixel_scale'],
            region=image.geometry().bounds()
        )
    else:
        print(f"Unsupported asset type: {asset['type']}")
        return
    task.start()
    print(f"Export task started for asset: {asset['id']} to Cloud Storage bucket: {bucket}/{path}")


##############################################################################
# 
##############################################################################
# Stable tails (region-agnostic) for items that include a varying region prefix
DEFAULT_PREFIXES = (
    "A_predictor_fitted_img_",
    "C4_classed_img_",
    "D_bugnet_forest_mask_",
    "bugnet_polygons_buffered_",
)

DEFAULT_SUFFIXES = (
    "_mag50_10mmu_parameter_file",
    "_mag50_20mmu_parameter_file",
    "_mag50_30mmu_parameter_file",
    "_mag60_10mmu_parameter_file",
    "_mag60_20mmu_parameter_file",
    "_mag60_30mmu_parameter_file",
    "_mag70_10mmu_parameter_file",
    "_mag70_20mmu_parameter_file",
    "_mag70_30mmu_parameter_file",
)

def _is_default_asset(asset_id: str) -> bool:
    base = asset_id.rsplit("/", 1)[-1]
    return base.startswith(DEFAULT_PREFIXES) or base.endswith(DEFAULT_SUFFIXES)

def export_assets(params, use_defaults=True):
    """Main function to export assets automatically or interactively."""
    location = get_user_input(
        "Where would you like to export your assets?",
        ['Google Drive', 'Google Cloud Storage']
    )

    assets = list_assets(params)

    if use_defaults:
        selected_assets = [a for a in assets if _is_default_asset(a['id'])]
        print(f"Exporting {len(selected_assets)} default assets...")
    else:
        print("\nAvailable assets:")
        for idx, asset in enumerate(assets):
            print(f"{idx + 1}. {asset['id']} ({asset['type']})")
        selected_indices = input(
            "Enter the numbers of the assets you'd like to export (comma-separated): "
        ).split(',')
        selected_indices = [int(idx.strip()) - 1 for idx in selected_indices if idx.strip().isdigit()]
        selected_assets = [assets[idx] for idx in selected_indices]

    if location == 'Google Drive':
        folder = input("Enter the Google Drive folder name: ")
        for asset in selected_assets:
            print(params['outputfile_prefix'], folder, params)
            export_to_drive(params['outputfile_prefix'], asset, folder, params)
    elif location == 'Google Cloud Storage':
        bucket = input("Enter the Google Cloud Storage bucket name: ")
        path = input("Enter the path within the bucket: ")
        for asset in selected_assets:
            export_to_cloud_storage(asset, bucket, path)
    else:
        print("Invalid location. Exiting.")


##############################################################################
# Load Parameter dictionary
##############################################################################
def load_parameters(file_path):
    # Dynamically load the module from the file path
    spec = importlib.util.spec_from_file_location("dynamic_params", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Check for the dictionary and return it
    if hasattr(module, "param"):
        return module.param
    else:
        raise ValueError("The provided script does not define 'parameters'.")


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
		task = bnet.export_image(fitted_img_t,param, param['assetDir_t'],param['fitted_img_t'],param['pixel_scale'])
		return task

def CreatePredictorFittedImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['fitted_img_p'])

	if exists:

		return

	else:
		treeMask = ee.ImageCollection('JRC/GFC2020/V3').mosaic().unmask()		
		fitted_img_p = bnet.get_fitted_stack(lt,'fitted_predictor',param).mask(treeMask).int16()
		task = bnet.export_image(fitted_img_p,param, param['assetDir'],param['fitted_img_p'],param['pixel_scale'])
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
		treeMask = ee.ImageCollection('JRC/GFC2020/V3').mosaic().unmask()		
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
			.updateMask(ee.ImageCollection('JRC/GFC2020/V3').mosaic()) \


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
	mask_code = (lcms.bitwiseOr(high.leftShift(1)).bitwiseOr(fire.leftShift(2)).bitwiseOr(tass.leftShift(3)).toInt16().clip(param['aoi']).updateMask(ee.ImageCollection('JRC/GFC2020/V3').mosaic()))

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
# Reclass Kmeans 
##############################################################################
def get_unique_pixel_values(param, region=None, scale=30):
    """
    Returns a list of unique pixel values in a given image band.

    Args:
        image (ee.Image): The input image.
        band_name (str): The name of the band to analyze.
        region (ee.Geometry, optional): The region to analyze. Defaults to image geometry.
        scale (int): The scale in meters for the reducer. Defaults to 30.

    Returns:
        List of unique pixel values.
    """
    # check to see if output asset exists
    exists = asset_exists(param['assetDir'] + param['predicted'])

    if exists:
        return


    # check to see if output asset exists
    image = ee.Image(param['assetDir'] + param['kmeansName'])
    if region is None:
        region = image.geometry()

    # Reduce the region to get a histogram of pixel values
    histogram_dict = image.select('cluster').reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=region,
        scale=scale,
        maxPixels=1e13
    ).get('cluster')

    # Convert to client-side dictionary and extract keys
    histogram = ee.Dictionary(histogram_dict).getInfo()
    unique_values = list(histogram.keys())

    # Convert keys to the appropriate type (e.g., int if they’re numbers)
    try:
        unique_values = [int(v) for v in unique_values]
    except ValueError:
        pass  # If not convertible to int, leave as strings

    return unique_values


##############################################################################
# 
##############################################################################
##############################################################################
# 
##############################################################################
def prompt_reclassification_mapping(unique_values, new_values=None, interactive=False, value_type=int):
    """
    Build a mapping from original pixel values to new values.

    Args:
        unique_values (iterable): Unique pixel values (any order).
        new_values (None | list | dict): 
            - None  -> identity mapping (default, no interaction)
            - list  -> must match length of unique_values (order-aligned)
            - dict  -> keys are originals; missing keys map to identity
        interactive (bool): If True and new_values is None, prompt user.
        value_type (callable|None): Coerce outputs (e.g., int). Use None to skip.

    Returns:
        (orig_list, mapped_list)
    """
    # Normalize & preserve first-seen order
    orig = list(dict.fromkeys(unique_values))

    # Case 1: default identity (no interaction)
    if new_values is None and not interactive:
        mapped = list(orig)

    # Case 2: interactive prompt
    elif new_values is None and interactive:
        print("Original values found in image:", orig)
        print(f"Enter {len(orig)} new values (in order), separated by commas.")
        while True:
            input_str = input("New values: ").strip()
            if not input_str:
                # Empty input => identity
                mapped = list(orig)
                break
            parts = [p.strip() for p in input_str.split(",")]
            if len(parts) != len(orig):
                print(f"Error: expected {len(orig)} values, got {len(parts)}. Try again.")
                continue
            try:
                mapped = [value_type(p) if value_type is not None else p for p in parts]
                break
            except Exception:
                print("Error: please enter valid values.")
                continue

    # Case 3: explicit list
    elif isinstance(new_values, (list, tuple)):
        if len(new_values) != len(orig):
            raise ValueError(f"Length mismatch: got {len(new_values)}, expected {len(orig)}.")
        mapped = list(new_values)

    # Case 4: explicit dict
    elif isinstance(new_values, dict):
        mapped = [new_values.get(v, v) for v in orig]

    else:
        raise TypeError("new_values must be None, list/tuple, or dict.")

    # Optional coercion
    if value_type is not None:
        try:
            mapped = [value_type(v) for v in mapped]
        except Exception as e:
            raise ValueError(f"Failed to coerce mapped values with {value_type}: {e}")

    return orig, mapped


##############################################################################
# 
##############################################################################
def reclassify_image(params, from_values, to_values):
    """
    Reclassifies pixel values in a band using remap().

    Args:
        image (ee.Image): Input image.
        band_name (str): Name of band to reclassify.
        from_values (list): Original values.
        to_values (list): New values.

    Returns:
        ee.Image: Reclassified image.
    """
    image = ee.Image(params['assetDir'] + params['kmeansName'])

    outimg = image.select('cluster').remap(from_values, to_values).rename(f'classified')
    task = ee.batch.Export.image.toAsset(
            image=outimg.toInt8(),
            description=params['predicted'],
            assetId=params['assetDir'] + params['predicted'],
            region=params['aoi'].geometry(),
            scale=params['pixel_scale'],
            maxPixels=1e13
    )
    task.start()
    return task

##############################################################################
# Polygonize
##############################################################################
def polygonize_bnet(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['bnet_polygonized'])

	if exists:
		return
	img = ee.Image(param['assetDir'] + param['predicted'])
	polygons = img.reduceToVectors(reducer=ee.Reducer.countEvery(), scale=param['pixel_scale'], maxPixels=1e13).filter(ee.Filter.gt('count',param['bnet_polygon_mmu']))

	export_params = {
		'collection': polygons,
		'description': param['bnet_polygonized'],
		'assetId': param['assetDir'] + param['bnet_polygonized']
	}

	task = ee.batch.Export.table.toAsset(**export_params)
	task.start()
	return task
##############################################################################
# buffer Bnet  Polygon
##############################################################################

def extract_zonal_stats(image, feature_collection, stat_type, output_field_name,param):
    # Define the reducer based on the desired statistic type
    if stat_type == 'mean':
        reducer = ee.Reducer.mean()
    elif stat_type == 'sum':
        reducer = ee.Reducer.sum()
    elif stat_type == 'min':
        reducer = ee.Reducer.min()
    elif stat_type == 'max':
        reducer = ee.Reducer.max()
    elif stat_type == 'mode':
        reducer = ee.Reducer.mode()
    else:
        raise ValueError('Unsupported stat_type: ' + stat_type)

    # Apply the reducer to the feature collection
    zonal_stats = image.reduceRegions(
        collection=feature_collection,
        reducer=reducer,
        scale=param['pixel_scale']  # Adjust the scale as needed
    )

    # Rename the output field to the desired name
    def set_stat_value(feature):
        stat_value = feature.get(stat_type)
        return feature.set(output_field_name, stat_value)

    zonal_stats = zonal_stats.map(set_stat_value)

    return zonal_stats

# Define the function to split multi-polygon into individual polygons
def split_multi_polygon_ss(feature):
    """Split a (multi)polygon Feature into single-part polygons on the server."""
    geom  = ee.Geometry(feature.geometry())
    parts = ee.List(geom.geometries())  # stays server-side
    props = feature.toDictionary()
    fc    = ee.FeatureCollection(parts.map(
        lambda g: ee.Feature(ee.Geometry(g)).set(props)
    ))
    return fc


##############################################################################
# 
##############################################################################
def calc_attri_fields(param):
    today = datetime.datetime.today()
    formatted_date = today.strftime("%m-%d-%Y")

    fields = {
      'ACRES': 0,
      'CREATED_DATE': formatted_date,
      'DAMAGE_TYPE': "null",
      'DAMAGE_TYPE_CODE': 0,
      'DCA': "null",
      'DCA_CODE': 0,
      'FEATURE_USER_ID': 'clarype@oregonstate.edu',
      'HOST': "null",
      'HOST_CODE': 0,
      'HOST_GROUP': "null",
      'HOST_GROUP_CODE': 0,
      'NOTES': "null",
      'REGION_ID': param['study_region'],
      'US_AREA': 'CONUS',
      'MODIFIED_DATE': 'na',
      'SURVEY_YEAR': param['target'],
      'buffered_acres': 0,
      'pct_affected': 0,
      'unbuffered_acres': 0,
    };

    return fields

##############################################################################
# 
##############################################################################
def add_area_and_pct_affected_by_pixel_count(fc_buffered,
                                             fc_unbuffered,
                                             count_field='count',
                                             pixel_size_meters=30):
    """
    Args:
      fc_buffered (ee.FeatureCollection): buffered polygons
      fc_unbuffered (ee.FeatureCollection): unbuffered polygons w/ pixel count field
      count_field (str): property name holding per-feature pixel counts
      pixel_size_meters (int|float): pixel size in meters (e.g., 30 for Landsat)

    Returns:
      ee.FeatureCollection: buffered features with added properties:
        - buffered_acres
        - pixel_count_sum
        - unbuffered_acres
        - pct_affected
    """
    ACRES_PER_SQ_M = 0.00024710538146717

    acres_per_pixel = (ee.Number(pixel_size_meters)
        .multiply(pixel_size_meters)
        .multiply(ACRES_PER_SQ_M))

    join = ee.Join.saveAll(matchesKey='matches')
    filt = ee.Filter.contains(leftField='.geo', rightField='.geo')

    joined = ee.FeatureCollection(join.apply(fc_buffered, fc_unbuffered, filt))

    def _per_buffer(buf):
        buf = ee.Feature(buf)

        buffer_area_acres = ee.Number(buf.geometry().area(1)).multiply(ACRES_PER_SQ_M)

        matches = ee.FeatureCollection(ee.List(buf.get('matches')))

        pixel_count_sum = ee.Number(
            ee.Algorithms.If(matches.size().gt(0),
                             matches.aggregate_sum(count_field),
                             0)
        )

        affected_acres = pixel_count_sum.multiply(acres_per_pixel)

        pct_affected = ee.Number(
            ee.Algorithms.If(buffer_area_acres.gt(0),
                             affected_acres.divide(buffer_area_acres).multiply(100),
                             0)
        )

        return (buf
            .set('buffered_acres', buffer_area_acres)
            .set('unbuffered_acres', affected_acres)  # same name as your JS
            .set('pct_affected', pct_affected)
            .set('matches', None))

    return joined.map(_per_buffer)
##############################################################################
# 
##############################################################################
def buffer_bnet_polygons(param):
    # check to see if output asset exists
    exists = asset_exists(param['assetDir'] + param['bnet_buffered_polygons'])

    if exists:
        return 0, 0

    asset_dir   = param['assetDir']
    base_name   = param['bnet_buffered_polygons']          # e.g., "bnet_buffers_2025"
    buckets     = int(param.get('buckets', 75))            # tune to stay below 10MB/payload
    buffer_m    = float(param['bnet_buffer'])
    max_err     = float(param.get('buffer_max_error', 10)) # meters
    mmu         = float(param['bnet_polygon_mmu'])

    # Source features (filter your mmu as before)
    fc = (ee.FeatureCollection(asset_dir + param['bnet_polygonized'])
            .filter(ee.Filter.gt('count', mmu)))

    # Deterministic partition 0..buckets-1
    fc = (fc.randomColumn('rand', 42)
            .map(lambda f: f.set('bucket', ee.Number(f.get('rand')).multiply(buckets).floor())))

    tasks = []
    asset_ids = []
    for b in range(buckets):
        sub = fc.filter(ee.Filter.eq('bucket', b)).map(
            lambda ft: ft.setGeometry(
                ft.geometry().buffer(buffer_m, max_err)  # OK to add .geodesic(False) if you want planar
            )
        )
        # Skip empty buckets (prevents "empty collection" export errors)
        size = ee.Number(sub.size())
        # Create a per-bucket asset name
        shard_id = f"{asset_dir}{base_name}_shard_{b:03d}"
        asset_ids.append(shard_id)

        # Gate on size > 0 server-side
        # NB: Export.table.toAsset must be constructed client-side, so we wrap with getInfo() guard:
        if size.getInfo() > 0:
            task = ee.batch.Export.table.toAsset(
                collection=sub,
                description=f"{base_name}_shard_{b:03d}",
                assetId=shard_id
            )
            task.start()
            tasks.append(task)
        # else: nothing to export for this shard

    return tasks, asset_ids

##############################################################################
# 
##############################################################################
def merge_buffer_buckets_and_finish(param, asset_ids):
    # check to see if output asset exists
    exists = asset_exists(param['assetDir'] + param['bnet_buffered_polygons'])

    if exists:
        return

    asset_dir = param['assetDir']
    base_name = param['bnet_buffered_polygons']
    max_err   = float(param.get('buffer_max_error', 10))

    # Ensure Python list of str (NOT ee.List)
    if hasattr(asset_ids, 'getInfo'):           # defensive: someone passed ee.List
        asset_ids = asset_ids.getInfo()
    asset_ids = [str(a) for a in asset_ids]

    merged = ee.FeatureCollection([])

    # Load each shard with a constant string and merge client-side
    for aid in asset_ids:
        try:
            fc = ee.FeatureCollection(aid)
            sz = fc.size().getInfo()            # tiny compute to confirm existence
            if sz and sz > 0:
                merged = merged.merge(fc)
        except Exception as e:
            print(f"Skipping shard {aid}: {e}")

    # Guard: nothing merged
    if merged.size().getInfo() == 0:
        raise RuntimeError("No shard data found. Check shard exports and asset_ids.")

    # (Optional) dissolve all shard buffers
    dissolved_geom = merged.geometry().dissolve(max_err)
    dissolved_fc   = ee.FeatureCollection([ee.Feature(dissolved_geom)])

    # Split multi-polygons server-side (no getInfo)
    polygons_fc = split_multi_polygon_ss(dissolved_fc.first())

    # Continue your pipeline
    img     = ee.Image(asset_dir + param['predicted'])
    fc_bnet = extract_zonal_stats(img, polygons_fc, "mode", "bnet_label", param)
    #fc_bnet = extract_zonal_stats(img, merged, "mode", "bnet_label", param)

    #def add_fields(feature):
    #    return feature.set(calc_attri_fields(param))
    #fc_attri = fc_bnet.map(add_fields)

    def rebuild_feature(feature):
        feature = ee.Feature(feature)

        new_props = ee.Dictionary(calc_attri_fields(param))  # must be a dict/ee.Dictionary

        # New feature with SAME geometry, NO old properties
        return ee.Feature(feature.geometry()).set(new_props)

    fc_attri = fc_bnet.map(rebuild_feature)

    result = add_area_and_pct_affected_by_pixel_count(
        fc_buffered=fc_attri,
        fc_unbuffered=param['assetDir'] + param['bnet_polygonized'],
        count_field='count',      # property holding pixel counts
        pixel_size_meters=param['pixel_scale']      # Landsat; use 10 for Sentinel-2
    )


    # Export final
    task = ee.batch.Export.table.toAsset(
        collection=result,
        description=param['bnet_buffered_polygons'],
        assetId=param['assetDir'] + param['bnet_buffered_polygons']

    )

    task.start()
    return task



##############################################################################
# set access 
##############################################################################

def walk(parent_id):
    """Yield every child asset (recursively)."""
    info = ee.data.getAsset(parent_id)                     # e.g., 'projects/your-project/assets/folder'
    for child in ee.data.listAssets({'parent': info['name']}).get('assets', []):
        t = child['type']
        name = child['name']
        if t in ('FOLDER', 'IMAGE_COLLECTION'):
            for x in walk(name):
                yield x
        else:
            yield name

##############################################################################
# export metadata
##############################################################################
def export_parameter_file(param):
	return 0
##############################################################################
# Wait for Task to complete
##############################################################################
def gui():
	print("Welcome to bugnet!")
	print("How would you like to continue? Enter ...")
	print("    1 - Run bugnet.")
	print("    2 - Run bugnet no training.")
	print("    3 - Export.")
	print("    4 - Clean.")
	mode = input(':')
	if mode == '2':
		return mode
	elif mode == '5':
		return mode
	elif mode == '4':
		return mode
	elif mode == '3':
		return mode
	elif mode == '1':
		return mode
	else:
		print('bye')
		sys.exit()

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
		# Example: make everything under a folder publicly readable
		parent = param['assetDir']
		acl_update = {'all_users_can_read': True}  # public-read
		for asset in walk(parent):
			print('Updating:', asset)
			ee.data.setAssetAcl(asset, acl_update)


	elif mode == '1':

		lt = LandTrendr(**param['lt_params'])

		task1 = CreateTrainingFittedImagery(lt,param)
		task2 = CreatePredictorFittedImagery(lt,param)
		task3 = CreateTrainingChangeImagery(lt,param)
		task4 = CreatePredictorChangeImagery(lt,param)
		wait_for_task(task1)
		wait_for_task(task2)
		wait_for_task(task3)
		wait_for_task(task4)

		task5 = CreateTrainingDisturbancePolygons(param)
		task6 = CreatePredictorDisturbancePolygons(param)
		wait_for_task(task5)

		if isinstance(task6, list):
			for t in task6[1]:
				wait_for_task(t)
			task66 = merge_selected_feature_collections(param['assetDir'],task6[2],param['disturbance_polygons_predictor'],"testing")
			wait_for_task(task66)
		else:
			wait_for_task(task6)

		task7 = attributeTrainingPolygons(param)
		task8 = attributePredictorPolygons(param)
		wait_for_task(task7)
		wait_for_task(task8)

		task9 = classify_polygons(param)
		wait_for_task(task9)

		task10 = filter_classes(param)
		wait_for_task(task10)

		task11 = buffer_classed_polygons(param)
		wait_for_task(task11)

		task12 = rasterize_classed_polygons(param)
		wait_for_task(task12)

		task_mask = CreateForestMask(param)	
		wait_for_task(task_mask)

		if '3' in param['configName']:

			task_decline = DecliningLTSD(param)
			wait_for_task(task_decline)

		else:

			task_snic = SNIC(param)
			wait_for_task(task_snic)

			task_decline_snic = DecliningSNIC(param)
			wait_for_task(task_decline_snic)

		task_kmeans_sample = buildKMeansSample(param)
		wait_for_task(task_kmeans_sample)

		task_kmeans = kMeansImage(param)
		wait_for_task(task_kmeans)

		task_sample = kMeansProporitonsADSsample(param)
		wait_for_task(task_sample)

		task_proportion = proportionCalc(param)
		wait_for_task(task_proportion)

		task_predict = predict(param)
		wait_for_task(task_predict)

		task_poly = polygonize_bnet(param)

		wait_for_task(task_poly)

		task_buffer = buffer_bnet_polygons(param)
		wait_for_task(task_buffer)

		task_params = dict_to_feature_collection(param)
		wait_for_task(task_params)

	elif mode == '2':

		lt = LandTrendr(**param['lt_params'])

		task2 = CreatePredictorFittedImagery(lt,param)
		task4 = CreatePredictorChangeImagery(lt,param)
		wait_for_task(task2)
		wait_for_task(task4)

		res = CreatePredictorDisturbancePolygons(param,param['polygon-split-method'])  # returns {'mode','tasks','asset_paths','subregions'}
		if res !=0:

			# 1) Wait for all started exports (skip Nones from "exists, skipping")
			tasks = [t for t in res.get('tasks', []) if t is not None]
			for t in tasks:
				wait_for_task(t)

			# 2) Merge shards only if there’s more than one asset
			asset_paths = res.get('asset_paths', [])
			if len(asset_paths) > 1:
				base_name  = param['disturbance_polygons_predictor']
				asset_dir  = param['assetDir']
				merged_name = f"{base_name}"
				merged_task = merge_selected_feature_collections(asset_dir, asset_paths, merged_name, "merged predictor shards")
				wait_for_task(merged_task)

				# ---- CLEANUP (delete shards) ----
				merged_path = f"{asset_dir}{merged_name}"
	
				def looks_like_shard(aid: str) -> bool:
					name = aid.split('/')[-1]
					# keep only pieces like "<base_name>_*" but not the merged or any grid export you want to keep
					if name == merged_name:
						return False
					if name.startswith(f"{base_name}_grid_"):   # keep the grid index asset if you export it
						return False
					return name.startswith(base_name + "_")
	
				# Prefer deleting only shards created in THIS run; fall back to all shards if list is empty
				candidates = res['created_asset_paths'] if res['created_asset_paths'] else asset_paths
				to_delete  = [a for a in candidates if looks_like_shard(a)]

				# Dry-run first if you want to preview
				#delete_assets(to_delete, dry_run=True)

				delete_assets(to_delete, dry_run=False, pause_sec=0.2)

			else:
				# Single asset (full AOI) — nothing to merge
				pass

		task8 = attributePredictorPolygons(param)
		wait_for_task(task8)

		task9 = classify_polygons(param)
		wait_for_task(task9)

		task10 = filter_classes(param)
		wait_for_task(task10)

		task11 = buffer_classed_polygons(param)
		wait_for_task(task11)

		task12 = rasterize_classed_polygons(param)
		wait_for_task(task12)

		task_mask = CreateForestMaskVis(param)	
		task_mask = CreateForestMask(param)	
		wait_for_task(task_mask)

		if '3' in param['configName']:

			task_decline = DecliningLTSD(param)
			wait_for_task(task_decline)

		else:

			task_snic = SNIC(param)
			wait_for_task(task_snic)

			task_decline_snic = DecliningSNIC(param)
			wait_for_task(task_decline_snic)

		buildKMeansSample(param)
		#wait_for_task(task_kmeans_sample)

		task_kmeans = kMeansImage(param)
		wait_for_task(task_kmeans)

		# if ADS exists do this
		if param['ADS_path']["on"]:
			task_sample = kMeansProporitonsADSsample(param)
			wait_for_task(task_sample)

			task_proportion = proportionCalc(param)
			wait_for_task(task_proportion)

			task_predict = predict(param)
			wait_for_task(task_predict)
		
			task_poly = polygonize_bnet(param)
			wait_for_task(task_poly)

			task_buffer, assets_ids = buffer_bnet_polygons(param)
			wait_for_task(task_buffer)

			task_buffer2 = merge_buffer_buckets_and_finish(param, assets_ids)
			wait_for_task(task_buffer2)

			task_params = dict_to_feature_collection(param)
			wait_for_task(task_params)
		else:
			
			unique_vals = get_unique_pixel_values(param)

			if unique_vals:  

				from_vals, to_vals = prompt_reclassification_mapping(unique_vals)

				task_p = reclassify_image(param, from_vals, to_vals)
				wait_for_task(task_p)

				task_poly = polygonize_bnet(param)
				wait_for_task(task_poly)

			task_poly = polygonize_bnet(param)
			wait_for_task(task_poly)

			task_buffer, assets_ids = buffer_bnet_polygons(param)

			if isinstance(task_buffer, list):

				for t in task_buffer:
					wait_for_task(t)

				task_buffer2 = merge_buffer_buckets_and_finish(param, assets_ids)
				wait_for_task(task_buffer2)
				delete_assets(assets_ids, dry_run=False)

			exists = asset_exists(param["assetDir"]+param['bnet_buffered_polygons'])
			if not exists:
				print(1)

			task_params = dict_to_feature_collection(param)
			wait_for_task(task_params)

			# Example: make everything under a folder publicly readable
			parent = param['assetDir']
			acl_update = {'all_users_can_read': True}  # public-read
			for asset in walk(parent):
				print('Updating:', asset)
				ee.data.setAssetAcl(asset, acl_update)

	else:
		print('bye')

if __name__ == "__main__":
    main()
