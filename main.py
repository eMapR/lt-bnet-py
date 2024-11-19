import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection
import os
import sys
import time
from datetime import date
#from parameters import blue_mt_config_opt3_2023 as bnet_config
import bnet as bnet
import run as run
import importlib.util
# Authenticate the Earth Engine API (uncomment if needed for authentication)
#ee.Authenticate(force=True)

# Initialize the Earth Engine API with a specific project


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
		task = run.export_image(fitted_img_t,param, param['assetDir_t'],param['fitted_img_t'])
		return task

def CreatePredictorFittedImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['fitted_img_p'])

	if exists:

		return

	else:
		fitted_img_p = run.get_fitted_stack(lt,'fitted_predictor',param)
		task = run.export_image(fitted_img_p,param, param['assetDir'],param['fitted_img_p'])
		return task

def CreateTrainingChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['training_change_img'])

	if exists:

		return

	else:

		param['change_params']['years'] = {'start': 2007, 'end': 2012}
		change_img_t = lt.get_change_map(param['change_params'])
		task = run.export_image(change_img_t, param, param['assetDir_t'],param['training_change_img'])
		return task

def CreatePredictorChangeImagery(lt,param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir"]+param['predictor_change_img'])

	if exists:

		return

	else:
		param['change_params']['years'] = {'start': param['composite_params']['end_date'].year-6, 'end': param['composite_params']['end_date'].year}
		change_img_p = lt.get_change_map(param['change_params'])
		task = run.export_image(change_img_p,param, param['assetDir'],param['predictor_change_img'])

		return task

def CreateTrainingDisturbancePolygons(param):
	# check to see if output asset exists
	exists = asset_exists(param["assetDir_t"]+param['disturbance_polygons_training'])

	if exists:

		return

	else:

		change_img_t = ee.Image(param["assetDir"]+param['training_change_img'])
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
		disturbance_polygons_p = run.vectorize_disturbance(change_img_p,param)
		task = run.export_feature_collection(disturbance_polygons_p,param['disturbance_polygons_predictor'],param['assetDir'])
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
		img = run.rasterize_polygons(fc2, 'classification', 30, region=param['aoi'])
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
	lcms_mask = bnet.lcms_forest_mask(param['target']-5,param['target']).clip(param['aoi'])

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
		scale=30,
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
		'scale': 30,
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
		'scale': 30,
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
	ltsd_decline = bnet.LTSD_decline_image(ee.Image(param['assetDir'] + param['fitted_img_p']),param['ltendYear']).updateMask(param['Mask'])

	# Export the image
	export_params = {
		'image': ltsd_decline.toInt16(),
		'description': param['declineName'],
		'assetId': param['assetDir'] + param['declineName'],
		'region': param['aoi'].geometry(),
		'scale': 30,
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
			scale=30, 
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
				scale=30,
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
		'scale': 30,
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
		'assetId': param['assetDir'] + param['KmeansVector']
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
		scale=30,
		tileScale=4,
		geometries=True
	)

	# Export to asset
	export_params = {
		'collection': sample,
		'description': param['proportionName']+"_sample",
		'assetId': param['assetDir'] + param['proportionName']+"_sample",
		#'maxVertices': 100000000
	}

	task_sample = ee.batch.Export.table.toAsset(**export_params)

	task_sample.start()

	export_params2 = {
		'image': sample_img,
		'description':param['proportionName'],
		'assetId': param['assetDir'] + param['proportionName'],
		'region': param['aoi'].geometry(),
		'scale': 30,
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
		'scale': 30,
		'maxPixels': 1e13
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
	polygons = img.reduceToVectors(reducer=ee.Reducer.countEvery(), scale=30, maxPixels=1e13)

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
def buffer_bnet_polygons(param):
	# check to see if output asset exists
	exists = asset_exists(param['assetDir'] + param['bnet_buffered_polygons'])

	if exists:
		return
	fc = ee.FeatureCollection(param['assetDir'] + param['bnet_polygonized'])
	def buffer_f(ft):
		polygon = ft.buffer(param['bnet_buffer'])
		area = polygon.geometry().area().divide(1000 * 1000);
  
		return polygon.set('area_m2', area);
	polygons = fc.map(buffer_f)

	export_params = {
		'collection':ee.FeatureCollection(polygons),
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
	print("    1 - Run all of bugnet.")
	print("    2 - Run individual step.")
	mode = input(':')
	if mode == '2':
		print("    3 - Run high Magnitude base data (step 1-a).")
		print("    4 - Run high magnitude disturbance polygons (step 1-b) .")
		print("    5 - Run high magnitude attribution (step 1-c)")
		print("    6 - Run high magnitude polygon classification (step 1-d)")
		print("    7 - Run high magnitude polygon classification (step 1-d)")
		print("    8 - Run forest mask")
		print("    9 - Run the rest")
		print("    del - clean asset storage.")
		mode = input(':')
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

	if mode == 'del':

		run.list_and_delete_assets(param['assetDir'])
		sys.exit()

	elif mode == '22':

		export_parameter_file()

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

		#task_buffer = buffer_bnet_polygons(param)
		#wait_for_task(task_buffer)

	elif mode == '3':

		lt = LandTrendr(**param['lt_params'])

		task1 = CreateTrainingFittedImagery(lt,param)
		task2 = CreatePredictorFittedImagery(lt,param)
		task3 = CreateTrainingChangeImagery(lt,param)
		task4 = CreatePredictorChangeImagery(lt,param)
		wait_for_task(task1)
		wait_for_task(task2)
		wait_for_task(task3)
		wait_for_task(task4)

	elif mode == '4':

		task5 = CreateTrainingDisturbancePolygons(param)
		task6 = CreatePredictorDisturbancePolygons(param)
		wait_for_task(task5)
		wait_for_task(task6)

	elif mode == '5':

		task7 = attributeTrainingPolygons(param)
		task8 = attributePredictorPolygons(param)
		wait_for_task(task7)
		wait_for_task(task8)

	elif mode == '6':

		task9 = classify_polygons(param)
		wait_for_task(task9)

	elif mode == '7':

		task10 = filter_classes(param)
		wait_for_task(task10)

		task11 = buffer_classed_polygons(param)
		wait_for_task(task11)

		task12 = rasterize_classed_polygons(param)
		wait_for_task(task12)

	elif mode == '8':

		task_mask = CreateForestMask(param)	
		wait_for_task(task_mask)

	elif mode == '9':

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

		task_buffer = buffer_bnet_polygons(param)
		wait_for_task(task_buffer)

	else:
		print('bye')

if __name__ == "__main__":
    main()
