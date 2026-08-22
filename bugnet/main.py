import ee
import json
import sys
import time
import bnet as bnet
from cli_utils import gui, load_parameters, walk_assets
from disturbance_utils import (
	CreatePredictorChangeImagery,
	CreatePredictorDisturbancePolygons,
	CreatePredictorFittedImagery,
	CreateTrainingChangeImagery,
	CreateTrainingDisturbancePolygons,
	CreateTrainingFittedImagery,
	attributePredictorPolygons,
	attributeTrainingPoints,
	attributeTrainingPolygons,
	buffer_classed_polygons,
	classify_polygons,
	filter_classes,
	merge_selected_feature_collections,
	rasterize_classed_polygons,
)
from export_utils import dict_to_feature_collection, export_assets
from modeling_utils import (
	build_kmeans_sample,
	create_forest_mask,
	create_forest_mask_vis,
	declining_ltsd,
	declining_snic,
	kmeans_image,
	kmeans_proportions_ads_sample,
	predict,
	proportion_calc,
	snic,
)
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
        error_message = task.status().get('error_message', 'Unknown Earth Engine task error')
        print(f"Task {task.id} failed with error: {error_message}")
        raise RuntimeError(f"Task {task.id} failed: {error_message}")


def ensure_asset_folder(asset_dir):
    """Create a one-level Earth Engine asset folder if it is missing."""
    folder_id = asset_dir.rstrip("/")
    try:
        ee.data.getAsset(folder_id)
        return
    except Exception:
        pass

    print(f"Creating asset folder: {folder_id}")
    ee.data.createAsset({"type": "FOLDER"}, folder_id)


def ensure_output_asset_folders(param):
    """Ensure shared and run-specific output folders exist before exports start."""
    for asset_dir in dict.fromkeys(
        [param.get("sharedAssetDir"), param.get("assetDir")]
    ):
        if asset_dir:
            ensure_asset_folder(asset_dir)


def shared_asset_fingerprint(param):
    """
    A small dict identifying what a shared-upstream-stage folder was
    built for: target year, fit indices, platform, and the AOI's bounds
    (not the AOI asset path - param['aoi'] is sometimes built inline via
    a filter/computation rather than a plain asset reference, so bounds
    is the one thing derivable from any FeatureCollection). One
    getInfo() round-trip, done once at startup.
    """
    aoi_bounds = param["aoi"].geometry().bounds(1).coordinates().getInfo()
    return {
        "target": int(param["target"]),
        "fit": ",".join(sorted(param["fit"])),
        "platform": param.get("platform", "LS"),
        "aoi_bounds": json.dumps(aoi_bounds),
    }


def validate_or_stamp_shared_assets(param, asset_exists):
    """
    Guard against param['shared_version'] pointing sharedAssetDir at a
    folder that was actually built for a different AOI/year/fit/platform.
    GEE gives no protection against this on its own - asset paths are
    just strings, and FOLDER assets don't even support properties (only
    IMAGE/TABLE do) - so this repo's own manifest asset,
    "<sharedAssetDir>_shared_manifest", is the only thing enforcing it.

    The first config to actually populate a given shared_version writes
    the manifest here. Every later config pointed at that same
    shared_version is checked against it and refused with a loud
    RuntimeError on any mismatch, rather than silently building on top
    of upstream assets computed for the wrong study area/year/indices.

    No-op when sharedAssetDir isn't actually distinct from assetDir
    (nothing being shared, nothing to guard).
    """
    shared_dir = param.get("sharedAssetDir", param["assetDir"])
    if shared_dir == param["assetDir"]:
        return

    manifest_id = f"{shared_dir.rstrip('/')}/_shared_manifest"
    fingerprint = shared_asset_fingerprint(param)

    if not asset_exists(manifest_id):
        # Export.table.toAsset refuses features with null geometry - this
        # feature only carries properties, so the geometry itself is a
        # meaningless placeholder point.
        manifest_fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([0, 0]), fingerprint)])
        task = ee.batch.Export.table.toAsset(
            collection=manifest_fc,
            description="shared_manifest",
            assetId=manifest_id,
        )
        task.start()
        wait_for_task(task)
        print(f"Stamped shared-asset manifest at {manifest_id}: {fingerprint}")
        return

    existing = ee.FeatureCollection(manifest_id).first().toDictionary().getInfo()
    mismatches = {k: (existing.get(k), v) for k, v in fingerprint.items() if existing.get(k) != v}
    if mismatches:
        raise RuntimeError(
            f"shared_version={param.get('shared_version')!r} points sharedAssetDir at "
            f"{shared_dir}, but its manifest doesn't match this config's "
            f"target/fit/platform/AOI: {mismatches}. Refusing to build on top of "
            "upstream assets from a different run - use a different shared_version."
        )
    print(f"Shared-asset manifest at {manifest_id} matches this config.")

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


def build_mode_dependencies():
	return {
		"ee": ee,
		"wait_for_task": wait_for_task,
		"delete_assets": delete_assets,
		"asset_exists": asset_exists,
		"walk_assets": walk_assets,
		"CreateTrainingFittedImagery": lambda lt, param: CreateTrainingFittedImagery(lt, param, asset_exists),
		"CreatePredictorFittedImagery": lambda lt, param: CreatePredictorFittedImagery(lt, param, asset_exists),
		"CreateTrainingChangeImagery": lambda lt, param: CreateTrainingChangeImagery(lt, param, asset_exists),
		"CreatePredictorChangeImagery": lambda lt, param: CreatePredictorChangeImagery(lt, param, asset_exists),
		"CreateTrainingDisturbancePolygons": lambda param: CreateTrainingDisturbancePolygons(param, asset_exists),
		"CreatePredictorDisturbancePolygons": lambda param, strategy="grid", **kwargs: CreatePredictorDisturbancePolygons(param, asset_exists, strategy, **kwargs),
		"merge_selected_feature_collections": merge_selected_feature_collections,
		"attributeTrainingPolygons": lambda param: attributeTrainingPolygons(param, asset_exists),
		"attributeTrainingPoints": lambda param: attributeTrainingPoints(param, asset_exists),
		"attributePredictorPolygons": lambda param: attributePredictorPolygons(param, asset_exists),
		"classify_polygons": lambda param: classify_polygons(param, asset_exists),
		"filter_classes": lambda param: filter_classes(param, asset_exists),
		"buffer_classed_polygons": lambda param: buffer_classed_polygons(param, asset_exists),
		"rasterize_classed_polygons": lambda param: rasterize_classed_polygons(param, asset_exists),
		"CreateForestMask": lambda param: create_forest_mask(param, asset_exists),
		"CreateForestMaskVis": lambda param: create_forest_mask_vis(param, asset_exists),
		"DecliningLTSD": lambda param: declining_ltsd(param, asset_exists),
		"SNIC": lambda param: snic(param, asset_exists),
		"DecliningSNIC": lambda param: declining_snic(param, asset_exists),
		"buildKMeansSample": lambda param, poll_seconds=20, timeout_minutes=180, overwrite=False, progress_cb=None: build_kmeans_sample(
			param,
			asset_exists,
			poll_seconds=poll_seconds,
			timeout_minutes=timeout_minutes,
			overwrite=overwrite,
			progress_cb=progress_cb,
		),
		"kMeansImage": lambda param: kmeans_image(param, asset_exists),
		"kMeansProporitonsADSsample": lambda param: kmeans_proportions_ads_sample(param, asset_exists),
		"proportionCalc": lambda param: proportion_calc(param, asset_exists),
		"predict": lambda param: predict(param, asset_exists),
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
		print("Usage: python bugnet/main.py <parameter script path>")
		sys.exit(1)

	param_file = sys.argv[1]

	try:
		param = load_parameters(param_file)
	except Exception as e:
		print(f"Error loading parameters: {e}")
		sys.exit(1)

	ee.Initialize(project=param["project_name"])
	ensure_output_asset_folders(param)
	validate_or_stamp_shared_assets(param, asset_exists)

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
