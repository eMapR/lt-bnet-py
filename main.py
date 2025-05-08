
import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
import os
import sys
import time
#from datetime import date
import datetime
#from parameters import blue_mt_config_opt3_2023 as bnet_config
import bnet as bnet
import run as run
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
        elif isinstance(v, (ee.FeatureCollection, ee.Image, LandsatComposite)):
            items.append((new_key, "GEE object"))
        else:
            items.append((new_key, v))


    transformed_list = []
    for key, value in items:
        if isinstance(value, list):  # Convert list to comma-separated string
            transformed_list.append((key, ', '.join(value)))
        elif isinstance(value, datetime.date):  # Convert date object to string
            transformed_list.append((key, value.strftime('%Y-%m-%d')))
        else:  # Keep other types as they are
            transformed_list.append((key, value))


    return dict(transformed_list)

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
        feature = ee.Feature(ee.Geometry.Point([-119.018359375, 44.60978736008787]), flattened_data)

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


def get_user_input(prompt, options):
    """Utility function to get user input with validation."""
    print(prompt)
    for idx, option in enumerate(options):
        print(f"{idx + 1}. {option}")
    choice = input("Enter your choice: ")
    while not choice.isdigit() or int(choice) < 1 or int(choice) > len(options):
        print("Invalid choice. Please try again.")
        choice = input("Enter your choice: ")
    return options[int(choice) - 1]


def export_to_drive(prefix, asset, folder):
    """Exports an asset to Google Drive."""
    if asset['type'] == 'TABLE':
        collection = ee.FeatureCollection(asset['id'])
        task = ee.batch.Export.table.toDrive(
            collection=collection,
            description=f"{prefix}_{asset['id'].split('/')[-1]}",
            folder=prefix
        )
    elif asset['type'] == 'IMAGE':
        image = ee.Image(asset['id'])
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=f"{prefix}_{asset['id'].split('/')[-1]}",
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


def export_assets(params):
    """Main function to guide the user through exporting assets."""
    # Ask the user for export location
    location = get_user_input(
        "Where would you like to export your assets?",
        ['Google Drive', 'Google Cloud Storage']
    )

    # List all assets
    assets = list_assets(params)
    print("\nAvailable assets:")
    for idx, asset in enumerate(assets):
        print(f"{idx + 1}. {asset['id']} ({asset['type']})")

    # Get user selection
    selected_indices = input(
        "Enter the numbers of the assets you'd like to export (comma-separated): "
    ).split(',')
    selected_indices = [int(idx.strip()) - 1 for idx in selected_indices if idx.strip().isdigit()]
    selected_assets = [assets[idx] for idx in selected_indices]

    # Perform export based on location
    if location == 'Google Drive':
        folder = input("Enter the Google Drive folder name: ")
        for asset in selected_assets:
            export_to_drive(params['outputfile_prefix'],asset, folder)
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
        return
    while task.status()['state'] in ['READY', 'RUNNING']:
        print(f"\rTask {task.id} is still running...{counter} min", end='', flush=True)
        time.sleep(60)  # Wait for 30 seconds before checking again
        counter+=1
    if task.status()['state'] == 'COMPLETED':
        print(f"Task {task.id} completed successfully!")
    else:
        print(f"Task {task.id} failed with error: {task.status()['error_message']}")


##############################################################################
# Wait for Task to complete
##############################################################################
def asset_exists(asset_id):
    try:
        # Attempt to get information about the asset.
        asset_info = ee.data.getAsset(asset_id)
        if asset_info:
            print(f"Asset exists: {asset_id}")
            return True
    except ee.EEException as e:
        # If the asset does not exist, an exception will be raised.
        print(f"Asset does not exist: {asset_id}")
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
		fitted_img_t = run.get_fitted_stack(lt,'fitted_training',param)
		task = run.export_image(fitted_img_t,param, param['assetDir_t'],param['fitted_img_t'],param['pixel_scale'])
		return task

def CreatePredictorFittedImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['fitted_img_p'])

	if exists:

		return

	else:
		treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()		
		fitted_img_p = run.get_fitted_stack(lt,'fitted_predictor',param).mask(treeMask)
		task = run.export_image(fitted_img_p,param, param['assetDir'],param['fitted_img_p'],param['pixel_scale'])
		return task

def CreateTrainingChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['training_change_img'])

	if exists:

		return

	else:

		param['change_params']['years'] = {'start': 2007, 'end': 2012}
		change_img_t = lt.get_change_map(param['change_params'])
		task = run.export_image(change_img_t, param, param['assetDir_t'],param['training_change_img'],param['pixel_scale'])
		return task

def CreatePredictorChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['predictor_change_img'])

	if exists:

		return

	else:
		param['change_params']['years'] = {'start': param['composite_params']['end_date'].year-6, 'end': param['composite_params']['end_date'].year}
		treeMask = ee.ImageCollection('JRC/GFC2020/V2').mosaic().unmask()		
		change_img_p = lt.get_change_map(param['change_params']).mask(treeMask)
		task = run.export_image(change_img_p,param, param['assetDir'],param['predictor_change_img'],param['pixel_scale'])

		return task

def CreateTrainingDisturbancePolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['disturbance_polygons_training'])

	if exists:

		return

	else:

		change_img_t = ee.Image(param["assetDir_t"]+param['training_change_img']) #.unmask().clip(param['aoi'])
		disturbance_polygons_t = run.vectorize_disturbance(change_img_t,param)
		task = run.export_feature_collection(disturbance_polygons_t,param['disturbance_polygons_training'],param['assetDir_t'])
		return task

def CreatePredictorDisturbancePolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['disturbance_polygons_predictor'])

	if exists:

		return

	else:
		change_img_p = ee.Image(param["assetDir"]+param['predictor_change_img'])
		go = 1
		while go:
			try:
				raise Exception("Forcing exception for testing")
				disturbance_polygons_p = run.vectorize_disturbance(change_img_p,param)
				print(disturbance_polygons_p.size().getInfo())
				go = 0

			except:
				print('error: dataset to large. Decrease area or increase magnitude parameter.')
				print("    1: exit to adjust")
				print("    2: add elevation mask (to find elelvation value go here:)")
				print("    3: splite up region")
				track = input('    :')
				if track == '1':
					sys.exit()
				elif track == '2':
					newmag = input('enter elevation meters (keep under this value) : ')
					eleMask = ee.Image('COPERNICUS/DEM/GLO30').select('DEM').mean().lt(int(newmag))
					new_change_image = change_img_p.mask(eleMask).unmask().clip(param['aoi'])
					disturbance_polygons_p = run.vectorize_disturbance(new_change_image,param)
					try:
						#print(disturbance_polygons_p.size().getInfo())
						go = 0
					except:
						go = 1
				elif track == '3':
					hucid = param['huc6-id']
					fc8 = ee.FeatureCollection('USGS/WBD/2017/HUC08')
					fc6 = ee.FeatureCollection('USGS/WBD/2017/HUC06')
					#huc6code = fc6.getString('huc6')
					f8 = fc8.filter(ee.Filter.stringStartsWith('huc8', hucid))
					number_of_features = f8.size().getInfo()
					features_list = f8.toList(number_of_features)
					subregions = []
					for f in range(number_of_features): 
						fe = ee.Feature(features_list.get(f))
						huc8code = fe.getString('huc8');
						subregions.append(huc8code)
						new_image_clipped = change_img_p.clip(fe)
						disturbance_polygons_p = run.vectorize_disturbance(new_image_clipped, param)
						task = run.export_feature_collection(disturbance_polygons_p,param['disturbance_polygons_predictor']+huc8code.getInfo(),param['assetDir'])
						# Do something with disturbance_polygons_p (e.g., export or merge)
					try:
						#print(disturbance_polygons_p.size().getInfo())
						go = 0
					except:
						go = 1
				else:
					sys.exit()
		if track != '3':
			task = run.export_feature_collection(disturbance_polygons_p,param['disturbance_polygons_predictor'],param['assetDir'])
			return task
		else:
			return [task, subregions]


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

		gee_attributed_fc = run.attribute_with_reference_data(param,'training')

		# reproject and change feature collecton to json
		reprojected_geojson = run.feature_collection_to_geojson(gee_attributed_fc, param['source_epsg'], param['target_epsg'])    # apply reprojections and feature collectio>

		# attribute with Cmonster
		event_polygons_attri1 = run.attribute_with_cmonster_data(reprojected_geojson,param['cMonster_img_path'])                   # apply attribution (cMonster)

		# reproject and convert to featrue collection
		reprojected_fc = run.geojson_to_ee_feature(event_polygons_attri1, param['target_epsg'], param['source_epsg'])           # apply re-reprojection and geojson to featur>

		# export
		task = run.export_feature_collection(reprojected_fc,param['attributed_polygons_training'],param['assetDir_t'] )

		return task


def attributePredictorPolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['attributed_polygons_predictor'])

	if exists:

		return

	else:
		gee_attributed_fc = run.attribute_with_reference_data(param,'predictor')
		task = run.export_feature_collection(gee_attributed_fc,param['attributed_polygons_predictor'],param['assetDir'] )
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
		labeled_fc = run.drop_null_features(labeled_fc,predictor_variables)
		unlabeled_fc = run.drop_null_features(unlabeled_fc,predictor_variables)

		trained_classifier = run.train_classifier(labeled_fc,"mode_value",predictor_variables,param['num_trees'])
		classified_fc = run.classify_features(unlabeled_fc, trained_classifier)

		task = run.export_feature_collection(classified_fc,param['classified_fc'],param['assetDir'])
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
		fc1 = run.filter_by_mode_value(ee.FeatureCollection(param['assetDir'] + param['classified_fc']), 19, 41, 60, 90)

		task = run.export_feature_collection(fc1, param['filtered_classes'], param['assetDir'])

		return task

def buffer_classed_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['buffered_classes'])
	if exists:

		return

	else:
		fc1 = ee.FeatureCollection(param["assetDir"]+param['filtered_classes'])
		fc2 = run.buffer_features(fc1, 100)
		task = run.export_feature_collection(fc2, param['buffered_classes'], param['assetDir'])
		return task

def rasterize_classed_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['rasterize_classes'])

	if exists:

		return

	else:
		fc2 = ee.FeatureCollection(param["assetDir"]+param['buffered_classes'])
		img = run.rasterize_polygons(fc2, 'classification', param['pixel_scale'], region=param['aoi'])
		task = run.export_image(img, param, param['assetDir'],param['rasterize_classes'])

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
	lcms_mask = bnet.lcms_forest_mask( param['target']-5, param['target'], param).clip(param['aoi'])

	#reflectance mask
	tassMap = bnet.tasselCapMask(param)

	#High Magnitude -- makes a raster mask from vector layer of clear cuts fire etc 
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
	mask = lcms_mask.multiply(highMagChange_img) \
			.multiply(fire_img) \
			.multiply(tassMap) \
			.clip(param['aoi'])

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
	decline = bnet.decline_image(param).updateMask(param['Mask'])

	# Export the image
	export_params = {
		'image': decline.toInt16(),
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
# Sample for Kmeans build 
##############################################################################
def buildKMeansSample(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['kmeansName']+"_sample")

	if exists:
		return

	# Import SNIC decline image
	snic_decline_path = param['assetDir'] + param['declineName']
	snic_decline = ee.Image(snic_decline_path)

	# Get band names from the SNIC decline image -- slice first and last (SNIC seed and cluster bands)
	snic_bands = snic_decline.bandNames().slice(1, -1)


	# Get random sample of point attributes for KMeans
	sample = ee.FeatureCollection(
		snic_decline.sample(region=
			param['aoi'], 
			scale=param['pixel_scale'], 
			numPixels=param['kmeans_num_sample'], 
			tileScale=12, 
			geometries=True)
		.randomColumn().sort('random')
	)
	
	if sample.size().getInfo() < 10:

		# Get random sample of point attributes for KMeans	
		sample = ee.FeatureCollection(
			snic_decline.sampleRegions(
				collection=param['aoi'],
				scale=param['pixel_scale'],
				tileScale=12,
				geometries=True
			).randomColumn().sort('random').toList(param['kmeans_num_sample'])
		)


	export_params = {
		'collection': sample,
		'description': param['kmeansName']+"_sample",
		'assetId': param['assetDir'] + param['kmeansName']+"_sample"
	}


	task_kmeans_sample = ee.batch.Export.table.toAsset(**export_params)
	task_kmeans_sample.start()
	return task_kmeans_sample

##############################################################################
# make KMEANS iamge 
##############################################################################
def kMeansImage(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['kmeansName'])

	if exists:
		return

	# Import SNIC decline image
	snic_decline_path = param['assetDir'] + param['declineName']
	snic_decline = ee.Image(snic_decline_path)

	# Get band names from the SNIC decline image -- slice first and last (SNIC seed and cluster bands)
	snic_bands = snic_decline.bandNames().slice(1, -1)


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
	snic_decline_kmeans = snic_decline.cluster(training).clip(param['aoi'])

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
	snic_decline = ee.Image(param['assetDir'] + param['declineName'])
	kmeans_decline = ee.Image(param['assetDir'] + param['kmeansName'])
	sample = ee.FeatureCollection(param['assetDir'] + param['proportionName']+'_sample')

	# Rename the bands in the reference image
	if '2' in param['configName']:
		refer_image = bnet.rename_img(snic_decline, param['target'])
	else:
		refer_image = bnet.rename_img_opt3(snic_decline, param['target'])


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
# Polygonize
##############################################################################
def polygonize_bnet(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['bnet_polygonized'])

	if exists:
		return
	img = ee.Image(param['assetDir'] + param['predicted'])
	polygons = img.reduceToVectors(reducer=ee.Reducer.countEvery(), scale=param['pixel_scale'], maxPixels=1e13).filter(ee.Filter.gt('count',10))

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
def split_multi_polygon(feature):
    geometries = feature.geometry().geometries()
    geometries_list = geometries.getInfo()  # Convert to a list
    features = [ee.Feature(ee.Geometry(geometry)) for geometry in geometries_list]
    return ee.FeatureCollection(features)

def calc_attri_fields():

    fields = {
      'ACRES': 0,
      'CREATED_DATE': '11-27-2024',
      'DAMAGE_TYPE_CODE': 0,
      'DCA_CODE': 0,
      'HOST_CODE': 0,
      'HOST_GROUP_CODE': 0,
      'IDS_DATA_SOURCE': 91,
      'KEY': 'clarype@oregonstate.edu',
      'LABEL': 'Default Label',
      'MODIFIED_DATE': '',
      'NOTES': '',
      'PERCENT_AFFECTED_CODE': 2,
      'REGION_ID': 'Region_06',
      'SURVEY_YEAR': 2024,
      'US_AREA': 'CONUS',
      'count': 14,
      'label': 1
    };

    return fields

def buffer_bnet_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['bnet_buffered_polygons'])

	if exists:
		return
	fc = ee.FeatureCollection(param['assetDir'] + param['bnet_polygonized'])

	def buffer_f(ft):
		polygon = ft.buffer(param['bnet_buffer'])
		return polygon;

	fc_buffered = fc.map(buffer_f)

	buffer_dissovled = ee.FeatureCollection(fc_buffered.geometry().dissolve())

	# Apply the function to split the multi-polygon feature
	polygons_fc = split_multi_polygon(buffer_dissovled.first())

	img = ee.Image(param['assetDir'] + param['predicted'])
	fc_bnet = extract_zonal_stats(img, polygons_fc, "max", "label")

	# Define the function to add fields to each feature
	def add_fields(feature):
		return feature.set(calc_attri_fields())

	# Apply the function to each feature in the collection
	fc_attri = fc_bnet.map(add_fields)

	export_params = {
		'collection':fc_attri,
		'description': param['bnet_buffered_polygons'],
		'assetId': param['assetDir'] + param['bnet_buffered_polygons']
	}

	task = ee.batch.Export.table.toAsset(**export_params)
	task.start()
	return task
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
		run.list_and_delete_assets(param['assetDir'])
		sys.exit()

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

		task6 = CreatePredictorDisturbancePolygons(param)
		print(task6)
		if isinstance(task6, list):
			wait_for_task(task6[0])
			task66 = merge_selected_feature_collections(param['assetDir'],task6[1],param['disturbance_polygons_predictor'],"testing")
			print(task66)
			wait_for_task(task66)
		else:
			wait_for_task(task6)


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
	else:
		print('bye')

if __name__ == "__main__":
    main()
