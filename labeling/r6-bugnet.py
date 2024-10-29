# Import the Earth Engine library
import ee

# Import the LandTrendr, LandsatComposite, and LtCollection modules from the ltgee package
from ltgee import LandTrendr, LandsatComposite, LtCollection

# Import the geemap package, which provides a convenient interface for using GEE with Python
#import geemap

# Import a custom configuration module named config as bnet_config
#import blue_mt_config_opt2_2023 as bnet_config
#import blue_mt_config_opt2_2024 as bnet_config
#import blue_mt_config_opt3_2023 as bnet_config
#import blue_mt_config_opt3_2024 as bnet_config

#import cascades_config_opt3_2023 as bnet_config
#import cascades_config_opt2_2023 as bnet_config
#import cascades_config_opt2_2024 as bnet_config
#import cascades_config_opt3_2024 as bnet_config

#import coast_range_config_opt2_2023 as bnet_config
#import coast_range_config_opt2_2024 as bnet_config
#import coast_range_config_opt3_2023 as bnet_config
#import coast_range_config_opt3_2024 as bnet_config

#import eastern_cascades_config_opt2_2023 as bnet_config
#import eastern_cascades_config_opt2_2024 as bnet_config
#import eastern_cascades_config_opt3_2023 as bnet_config
#import eastern_cascades_config_opt3_2024 as bnet_config

#import klamath_mts_config_opt2_2023 as bnet_config
#import klamath_mts_config_opt2_2024 as bnet_config
#import klamath_mts_config_opt3_2023 as bnet_config
#import klamath_mts_config_opt3_2024 as bnet_config

#import north_cascades_config_opt2_2023 as bnet_config
#import north_cascades_config_opt2_2024 as bnet_config
import params.north_cascades_config_opt3_2023 as bnet_config
#import params.north_cascades_config_opt3_2024 as bnet_config

#import northern_rockies_config_opt2_2023 as bnet_config
#import northern_rockies_config_opt2_2024 as bnet_config
#import northern_rockies_config_opt3_2023 as bnet_config
#import northern_rockies_config_opt3_2024 as bnet_config

import os

import sys

import time

# Get the current script's directory
#current_dir = os.path.dirname(os.path.abspath("./"))

# Add the parent directory to sys.path
#sys.path.append(current_dir)

# Import a custom module named bnet
import bnet as bnet

# Import the date class from the datetime module for handling dates
from datetime import date

# Authenticate the Earth Engine API (uncomment if needed for authentication)
#ee.Authenticate(force=True)

# Initialize the Earth Engine API with a specific project
ee.Initialize(project="r6-bugnet")


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
# Create LTSD Image
##############################################################################
def CreateLTSDimage(lt_,params_):
    # check to see if output asset exists
    exists = asset_exists(params_["assetDir"]+params_["LTSDname"])
    
    if exists:

        return

    # Get LandTrendr Segment info
    last_seg = bnet.get_lt_last_seg_info(lt_, 'nbr').selfMask()

    # Forests Height
    canopy_ht_img = ee.ImageCollection("projects/meta-forest-monitoring-okw37/assets/CanopyHeight").mean().gt(5)

    # Forest locations Alaska
    forestMask = canopy_ht_img.reproject(crs='EPSG:4326', scale=30).clip(bnet_config.param['aoi']).selfMask()

    # Generate LandTrendr standardized imagery and add the LandTrendr segment info as an additional band then mask non-forest regions
    ltsd = bnet.standardized_lt_image(lt_, params_["ltstartYear"], params_["ltendYear"], params_["index"], params_["ltendYear"]).addBands(last_seg).mask(forestMask)

    # Export imagery
    task_ltsd = ee.batch.Export.image.toAsset(
        image=ltsd.toInt16(),
        description=params_["LTSDname"],
        assetId=params_["assetDir"]+params_["LTSDname"],
        region=params_["aoi"].geometry(),
        scale=30,
        maxPixels=1e9
    )
    task_ltsd.start()

    return task_ltsd


##############################################################################
# Create forest mask
##############################################################################
def CreateForestMask():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param["assetDir"]+bnet_config.param['forestMaskName'])
	
	if exists:

		return

	mtbs = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")
	
	# LCMS forest mask
	lcms_mask = bnet.lcms_forest_mask(bnet_config.param['target']-5,bnet_config.param['target']).clip(bnet_config.param['aoi'])
	
	#reflectance mask
	tassMap = bnet.tasselCapMask(bnet_config) # <<<<<<<<<<<<<< need to find a better way. WorldViews canopy cover?
	
	#High Magnitude -- makes a raster mask from vector layer of clear cuts fire etc 
	#highMagChange_img = bnet_config.param['ltchange'].lte(bnet_config.param['target']).unmask().Not()
	highMagChange_img = bnet_config.param['ltchange'].gt(0).unmask().Not()
	#highMagChange_img = (
	#	bnet.ltcalc(bnet_config.param['target'], bnet_config.param['ltchange'])
	#	.reduceToImage(properties=["yod"], reducer=ee.Reducer.mean())
	#	.gt(0)
	#	.unmask()
	#	.Not()
	#)
	
	#Fire mask - filter MTBS dataset by date 
	fires = mtbs.filter(
		ee.Filter.And(
			ee.Filter.gte("Ig_Date", bnet_config.param['maskStartTime']),
			ee.Filter.lte("Ig_Date", bnet_config.param['maskEndTime'])
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
			.clip(bnet_config.param['aoi'])
		
	# export image mask
	task_mask = ee.batch.Export.image.toAsset(
		#image=ee.Image(bnet_config.param['LTSDdir'] + bnet_config.param['LTSDname']).select([0]).multiply(0).add(1).byte(),
		image=mask.byte(),
 		description=bnet_config.param['forestMaskName'],
		assetId=bnet_config.param["assetDir"]+bnet_config.param['forestMaskName'],
		region=bnet_config.param['aoi'].geometry(),
		scale=30,
		maxPixels=1e13
	)
	task_mask.start()
	
	return task_mask

##############################################################################
# SNIC
##############################################################################
def SNIC():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['snicName'])
	if exists:

		return

	# Get LTSD image
	ltsd = ee.Image(bnet_config.param['LTSDdir'] + bnet_config.param['LTSDname'])

	# Generate a SNIC image from the LTSD image and then mask with non-forest mask
	ltsd_snic = bnet.snic_image(ltsd).mask(bnet_config.param['Mask'])

	# Export image
	export_params = {
		'image': ltsd_snic.toInt16(),
		'description': bnet_config.param['snicName'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['snicName'],
		'region': bnet_config.param['aoi'].geometry(),
		'scale': 30,
		'maxPixels': 1e13
	}

	task_snic = ee.batch.Export.image.toAsset(**export_params)

	task_snic.start()

	return task_snic

##############################################################################
# Declining SNIC
##############################################################################
def DecliningSNIC():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['declineName'])

	if exists:

		return

	# Apply the function
	snic_decline = bnet.SNIC_decline_image(ee.Image(bnet_config.param['assetDir'] + bnet_config.param['snicName']))#.updateMask(bnet_config.param['Mask'])

	# Export the image
	export_params = {
		'image': snic_decline.toInt16(),
		'description': bnet_config.param['declineName'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['declineName'],
		'region': bnet_config.param['aoi'].geometry(),
		'scale': 30,
		'maxPixels': 1e13
	}

	task_decline_snic = ee.batch.Export.image.toAsset(**export_params)

	task_decline_snic.start()

	return task_decline_snic

##############################################################################
# Declining LTSD
##############################################################################
def DecliningLTSD():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['declineName'])

	if exists:

		return

	# Apply the function
	ltsd_decline = bnet.LTSD_decline_image(ee.Image(bnet_config.param['assetDir'] + bnet_config.param['LTSDname']),bnet_config.param['ltendYear']).updateMask(bnet_config.param['Mask'])

	# Export the image
	export_params = {
		'image': ltsd_decline.toInt16(),
		'description': bnet_config.param['declineName'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['declineName'],
		'region': bnet_config.param['aoi'].geometry(),
		'scale': 30,
		'maxPixels': 1e13
	}

	task_decline_snic = ee.batch.Export.image.toAsset(**export_params)

	task_decline_snic.start()

	return task_decline_snic
	

##############################################################################
# Sample for Kmeans build 
##############################################################################
def buildKMeansSample():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['kmeansName']+"_sample")

	if exists:
		return

	# Import SNIC decline image
	snic_decline_path = bnet_config.param['assetDir'] + bnet_config.param['declineName']
	snic_decline = ee.Image(snic_decline_path)

	# Get band names from the SNIC decline image -- slice first and last (SNIC seed and cluster bands)
	snic_bands = snic_decline.bandNames().slice(1, -1)


	# Get random sample of point attributes for KMeans
	sample = ee.FeatureCollection(
		snic_decline.sample(region=
			bnet_config.param['aoi'], 
			scale=30, 
			numPixels=bnet_config.param['kmeans_num_sample'], 
			tileScale=12, 
			geometries=True)
		.randomColumn().sort('random')
	)
	
	if sample.size().getInfo() < 10:

		# Get random sample of point attributes for KMeans	
		sample = ee.FeatureCollection(
			snic_decline.sampleRegions(
				collection=bnet_config.param['aoi'],
				scale=30,
				tileScale=12,
				geometries=True
			).randomColumn().sort('random').toList(bnet_config.param['kmeans_num_sample'])
		)


	export_params = {
		'collection': sample,
		'description': bnet_config.param['kmeansName']+"_sample",
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['kmeansName']+"_sample"
	}

	task_kmeans_sample = ee.batch.Export.table.toAsset(**export_params)
	task_kmeans_sample.start()
	return task_kmeans_sample

##############################################################################
# make KMEANS iamge 
##############################################################################
def kMeansImage():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['kmeansName'])

	if exists:
		return

	# Import SNIC decline image
	snic_decline_path = bnet_config.param['assetDir'] + bnet_config.param['declineName']
	snic_decline = ee.Image(snic_decline_path)

	# Get band names from the SNIC decline image -- slice first and last (SNIC seed and cluster bands)
	snic_bands = snic_decline.bandNames().slice(1, -1)


	# Train KMeans on random sample across selected bands and number of clusters
	training = ee.Clusterer.wekaCascadeKMeans(
		bnet_config.param['num_of_clusters'],
		bnet_config.param['num_of_clusters'],
		10,
		False,
		True
	).train(
		ee.FeatureCollection(bnet_config.param['assetDir'] +bnet_config.param['kmeansNameSample']),
		snic_bands
	)

	# Apply KMeans clustering to the SNIC decline image and clip to AOI
	snic_decline_kmeans = snic_decline.cluster(training).clip(bnet_config.param['aoi'])

	# Export image to assets
	export_params = {
		'image': snic_decline_kmeans.toInt16(),
		'description': bnet_config.param['kmeansName'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['kmeansName'],
		'region': bnet_config.param['aoi'].geometry(),
		'scale': 30,
		'maxPixels': 1e13
	}

	task_kmeans = ee.batch.Export.image.toAsset(**export_params)
	task_kmeans.start()
	return task_kmeans

##############################################################################
# Kmeans Proportion of Intersection with ADS sample
##############################################################################
def kMeansProporitonsADSsample():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['KmeansVector'])

	if exists:
		return

	# ADS filtering
	ads = bnet_config.param['ads'].filterBounds(bnet_config.param['aoi']) #.filter(ee.Filter.eq('SURVEY_YEA', 2022))

	# Define AOI
	aoi = bnet_config.param['aoi']

	# KMeans image histogram
	kmeans = ee.Image(bnet_config.param['assetDir'] + bnet_config.param['kmeansName']).rename(['kmeans_clusters'])

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
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['KmeansVector']
		#'maxVertices': 100000000
	}

	task_sample = ee.batch.Export.table.toAsset(**export_params)

	task_sample.start()

	return task_sample

##############################################################################
# Calculation of proportion of intersection
##############################################################################
def proportionCalc():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['proportionName'])

	if exists:
		return

	proportion_attri = ee.FeatureCollection(bnet_config.param['assetDir'] + bnet_config.param['KmeansVector'] )

	intersect_std = proportion_attri.filter(ee.Filter.eq('touch', 1)).aggregate_stats('label').get('total_sd')

	# Add proportions to clusters
	def add_proportions(f):
		cluster = f.get('label')
		clusters_that_touch = ee.Number(
			proportion_attri.filter(
				ee.Filter.And(
					ee.Filter.eq('label', cluster), 
					ee.Filter.eq('touch', 1)
				)
			).size()
		)
		bnet_value = ee.Algorithms.If(clusters_that_touch.gte(ee.Number(intersect_std).multiply(3)), 3, ee.Algorithms.If(clusters_that_touch.gte(ee.Number(intersect_std).multiply(2)), 2, 1))
		return f.set("prop_count", clusters_that_touch).set("bnet", bnet_value)

	add_k_proportions = proportion_attri.map(add_proportions)

	feat_label = add_k_proportions.aggregate_array("label")
	feat_bnet = add_k_proportions.aggregate_array("bnet")
	feat_zip = feat_label.zip(feat_bnet).distinct().unzip()

	corrected_label = ee.List(feat_zip.get(0)).map(lambda e: ee.String(e))
	corrected_bnet = feat_zip.get(1)
	diclist = ee.Dictionary.fromLists(corrected_label, corrected_bnet)

	kmeans = ee.Image(bnet_config.param['assetDir'] + bnet_config.param['kmeansName']).rename(['kmeans_clusters'])

	def label_img_function(k):
		return kmeans.eq(ee.Number.parse(k)).multiply(ee.Number(diclist.get(k))).byte()

	label_img = diclist.keys().map(label_img_function)
	sample_img = ee.ImageCollection(label_img).sum().selfMask().rename(['label'])

	# Reference image
	ref_img = ee.Image(bnet_config.param['assetDir'] + bnet_config.param['declineName'])

	if '2' in bnet_config.param['configName']:

		ref_img = bnet.rename_img(ref_img, bnet_config.param['target']).addBands(kmeans).addBands(sample_img)

	else:

		ref_img = bnet.rename_img_opt3(ref_img, bnet_config.param['target']).addBands(kmeans).addBands(sample_img)

	# Stratified sample
	sample = ref_img.stratifiedSample(
		numPoints=bnet_config.param['proportion_strat_sample_size'],
		classBand='label',
		region= bnet_config.param['aoi'],
		scale=30,
		tileScale=4,
		geometries=True
	)

	# Export to asset
	export_params = {
		'collection': sample,
		'description': bnet_config.param['proportionName']+"_sample",
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['proportionName']+"_sample",
		#'maxVertices': 100000000
	}

	task_sample = ee.batch.Export.table.toAsset(**export_params)

	task_sample.start()

	export_params2 = {
		'image': sample_img,
		'description':bnet_config.param['proportionName'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['proportionName'],
		'region': bnet_config.param['aoi'].geometry(),
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
def predict():
	# check to see if output asset exists
	exists = asset_exists(bnet_config.param['assetDir'] + bnet_config.param['predicted'])

	if exists:
		return

	# Define variables
	states = bnet_config.param['aoi']
	snic_decline = ee.Image(bnet_config.param['assetDir'] + bnet_config.param['declineName'])
	kmeans_decline = ee.Image(bnet_config.param['assetDir'] + bnet_config.param['kmeansName'])
	sample = ee.FeatureCollection(bnet_config.param['assetDir'] + bnet_config.param['proportionName']+'_sample')

	# Rename the bands in the reference image
	if '2' in bnet_config.param['configName']:
		refer_image = bnet.rename_img(snic_decline, bnet_config.param['target'])
	else:
		refer_image = bnet.rename_img_opt3(snic_decline, bnet_config.param['target'])


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
	rf_model = refer_image.classify(random_forest).selfMask().clip(states).rename('bugnet_{}_{}_{}'.format(bnet_config.param['region'], bnet_config.param['target'], bnet_config.param['version']))

	export_params = {
		'image': rf_model,
		'description': bnet_config.param['predicted'],
		'assetId': bnet_config.param['assetDir'] + bnet_config.param['predicted'],
		'region': states.geometry(),
		'scale': 30,
		'maxPixels': 1e13
	}

	# Export the classified image to assets
	export_task = ee.batch.Export.image.toAsset(**export_params)
	export_task.start()

	return export_task 

##############################################################################
# MAIN
##############################################################################
def main():

	# Run the LandTrendr algorithm
	#lt_params = bnet_config.param['lt_params']

	#lt = LandTrendr(**lt_params)

	# Configuration parameters
	params = {
		"ltstartYear": bnet_config.param['ltstartYear'],
		"ltendYear": bnet_config.param['ltendYear'],
		#"startDay": bnet_config.param['startDay'],
		#"endDay": bnet_config.param['endDay'],
		"aoi": bnet_config.param['aoi'],
		"index": bnet_config.param['index'],
		"fit": bnet_config.param['fit'],
		"runParams": bnet_config.param['lt_params']['run_params'],
		"maskThese": bnet_config.param['maskThese'],
		"LTSDname": bnet_config.param['LTSDname'],
		"assetDir": bnet_config.param['assetDir']
	}


	#taskltsd = CreateLTSDimage(lt, params)
	#wait_for_task(taskltsd)

	task_mask = CreateForestMask()	
	wait_for_task(task_mask)

	if '3' in bnet_config.param['configName']:

		task_decline = DecliningLTSD()
		wait_for_task(task_decline)

	else:

		task_snic = SNIC()
		wait_for_task(task_snic)

		task_decline_snic = DecliningSNIC()
		wait_for_task(task_decline_snic)

	task_kmeans_sample = buildKMeansSample()
	wait_for_task(task_kmeans_sample)

	task_kmeans = kMeansImage()
	wait_for_task(task_kmeans)

	task_sample = kMeansProporitonsADSsample()
	wait_for_task(task_sample)

	task_proportion = proportionCalc()
	wait_for_task(task_proportion)

	export_task = predict()
	wait_for_task(export_task)

if __name__ == "__main__":
    main()
