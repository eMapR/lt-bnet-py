import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
from datetime import date
import json
import os
import rasterio
import geopandas as gpd
import pandas as pd
import numpy as np
from rasterio.features import geometry_mask
from scipy import stats
import multiprocessing
from shapely.geometry import shape, mapping
from rasterio.mask import mask
from pyproj import Transformer
import time
from collections import Counter
import ee
import sys
from sklearn.utils import resample

#-------------------------------------------------------------------
#ee.Initialize(project="r6-bugnet")
#-------------------------------------------------------------------
###########################################################################################################################
## 
###########################################################################################################################
def rename_bands_by_year(image, index, start_year, end_year):
	"""Rename bands in the image by year."""
	num_years = end_year - start_year+1
	new_band_names = [f"{index}_ftv_{start_year + i}" for i in range(num_years)]
	return image.rename(new_band_names)


###########################################################################################################################
## 
###########################################################################################################################
def get_fitted_stack(lt,prefix,parameters):
	"""
	Build a multi-index LandTrendr fitted-value stack for training or
	predictor imagery. Assumes exactly 4 indices in parameters['fit'].

	prefix == "fitted_training" selects a fixed 10-band window
	(indices 3-12) per index; any other prefix selects the last 15
	fitted years per index instead. Bands are named "{index}_ftv_{year}"
	via rename_bands_by_year.
	"""
	start_year = parameters['composite_params']['start_date'].year
	end_year = parameters['composite_params']['end_date'].year
	selection = 15
	start_date = parameters['composite_params']['start_date']
	end_date = parameters['composite_params']['end_date']
	index_list = parameters['fit']
	if prefix == "fitted_training":

		# Extract fitted data for each index 8 9 10 11 12
		img1 = rename_bands_by_year(lt.get_fitted_data(index_list[0], start_date=start_date, end_date=end_date),index_list[0],start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		img2 = rename_bands_by_year(lt.get_fitted_data(index_list[1], start_date=start_date, end_date=end_date),index_list[1],start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		img3 = rename_bands_by_year(lt.get_fitted_data(index_list[2], start_date=start_date, end_date=end_date),index_list[2],start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		img4 = rename_bands_by_year(lt.get_fitted_data(index_list[3], start_date=start_date, end_date=end_date),index_list[3],start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])

		# Merge all predictor data into a final stack
		stack = img1.addBands(img2).addBands(img3).addBands(img4)

		return stack
	else:
		# Extract fitted data for each index
		band_count = ((end_year+1) - start_year)
		last_bands = ee.List.sequence(band_count - selection, band_count - 1)
		# Extract fitted data for each index
		img1 = rename_bands_by_year(lt.get_fitted_data(index_list[0], start_date=start_date, end_date=end_date),index_list[0],start_year, end_year).select(last_bands)
		img2 = rename_bands_by_year(lt.get_fitted_data(index_list[1], start_date=start_date, end_date=end_date),index_list[1],start_year, end_year).select(last_bands)
		img3 = rename_bands_by_year(lt.get_fitted_data(index_list[2], start_date=start_date, end_date=end_date),index_list[2],start_year, end_year).select(last_bands)
		img4 = rename_bands_by_year(lt.get_fitted_data(index_list[3], start_date=start_date, end_date=end_date),index_list[3],start_year, end_year).select(last_bands)

		# Merge all predictor data into a final stack
		stack = img1.addBands(img2).addBands(img3).addBands(img4)

		return stack


###########################################################################################################################
## 
###########################################################################################################################
def export_image(stack, params, assetDir, asset,scale=30, max_pixels=1e13):
	"""Export the image to Google Earth Engine Assets."""
	# Define export parameters
	img_task = ee.batch.Export.image.toAsset(
		image=stack.clip(params['aoi']),
		description=asset,  # Task name
		assetId=assetDir + asset,  # Path in your GEE assets
		region=params['aoi'].geometry(),  # The area to export
		scale=scale,  # Resolution in meters per pixel
		maxPixels=max_pixels  # Maximum number of pixels allowed to export
	)
	img_task.start() 
	return img_task 

###########################################################################################################################
## 
###########################################################################################################################
def vectorize_disturbance(change_image,params):
	"""Vectorize a change image's 'yod' band into disturbance polygons."""
	disturbance_polygons = change_image.select('yod').selfMask().reduceToVectors(
		reducer=ee.Reducer.countEvery(),
		geometry=params['aoi'],
		scale=30,
		geometryType="polygon",
		labelProperty='yod',
		maxPixels=1e13,
		tileScale=12
	)
	return disturbance_polygons



###########################################################################################################################
## 
###########################################################################################################################
def attribute_with_reference_data(params,who):
	"""
	Attribute the polygons with reference data from the raster stack.
	"""
	def _process_polygon(polygon):
		yod = ee.Number(polygon.get('yod'))
		years = ee.List.sequence(yod.subtract(3), yod)
		yrs_int = ee.List.sequence(1,4)
		indexList = params['fit']
		indexList2 = [item.lower() for item in indexList if item != params['index']]
		to_append = '_ftv'
		new_list = [item + to_append for item in indexList2]
		indices = ee.List(new_list)

		def make_band_names(year):
			year = ee.Number(year).format('%d')
			return indices.map(lambda index: ee.String(index).cat('_').cat(year))

		selected_bands = years.map(make_band_names).flatten()
		selected_bands_int = yrs_int.map(make_band_names).flatten()
		special_bands = ee.List(['mag', 'dur', 'preval', 'rate', 'dsnr'])
	
		selected_bands = selected_bands.cat(special_bands)
		selected_bands_int = selected_bands_int.cat(special_bands)

		raster_filtered = in_img.select(selected_bands,selected_bands_int)

		raster_values = raster_filtered.reduceRegion(
			reducer=ee.Reducer.mean(),
			geometry=polygon.geometry(),
			scale=30,
			maxPixels=1e13
		)
		area = polygon.geometry().area().divide(1000 * 1000)

		perimeter = polygon.geometry().perimeter().divide(1000)

		return polygon.set(raster_values).set({'area_km2': area,'perimeter_km': perimeter, 'mode_value': 0})

	def renameLower(in_string):
		return ee.String(in_string).toLowerCase()

	if who == 'training':
		in_img = ee.Image(params['assetDir_t'] + params['fitted_img_t']).addBands(ee.Image(params['assetDir_t'] + params['training_change_img']))
		bandnameslower = in_img.bandNames().map(renameLower) 
		in_img = in_img.rename(bandnameslower)
		in_fc = ee.FeatureCollection(params['assetDir_t'] + params['disturbance_polygons_training'])
		out_fc = in_fc.filter(ee.Filter.And(ee.Filter.gt('count',params['trainingMin']),ee.Filter.lt('count',params['trainingMax']))).map(_process_polygon) 
		return out_fc 
	else:
		asset_dir = params.get('sharedAssetDir', params['assetDir'])
		in_img = ee.Image(asset_dir + params['fitted_img_p']).addBands(ee.Image(asset_dir + params['predictor_change_img']))
		bandnameslower = in_img.bandNames().map(renameLower) 
		in_img = in_img.rename(bandnameslower)
		in_fc = ee.FeatureCollection(asset_dir + params['disturbance_polygons_predictor']).filter(ee.Filter.gte('yod', params['target']-6))
		return in_fc.map(_process_polygon)


###########################################################################################################################
## 
###########################################################################################################################
def process_polygon(polygon, raster_path):
	"""
	Process each polygon by extracting cMonster data.
	"""
	def calculate_occurrences_proportion(values):
		total_count = len(values)
		occurrences = Counter(values)
		proportions = {key: value / total_count for key, value in occurrences.items()}
		return proportions

	def create_virtual_raster(_polygon, _raster_path, yod_band):
		with rasterio.open(_raster_path) as src:
			band_index = yod_band - 1984 + 1  # Adjust for 1-based indexing
			geom = [shape(_polygon['geometry'])]
			out_image, out_transform = mask(src, geom, crop=True, indexes=int(band_index))
			return out_image

	def calculate_mode(virtual_raster):
		flat_pixels = virtual_raster.flatten()
		flat_pixels = flat_pixels[flat_pixels != 0]  # Filter out no-data values if needed
		if len(flat_pixels) == 0:
			return -9999
		if len(flat_pixels) > 4000:
			return 40
		proportions = calculate_occurrences_proportion(flat_pixels)

		if any(value >= 0.60 for value in proportions.values()):
			if len(flat_pixels) > 0:
				mode_result = stats.mode(flat_pixels, axis=None)
				mode_value = mode_result.mode.item()
			else:
				mode_value = -9999  # No valid pixels in this polygon
		else:
			mode_value = -9999
		return mode_value

	yod = polygon['properties']['yod']
	virtual_raster = create_virtual_raster(polygon, raster_path, yod)
	mode_value = calculate_mode(virtual_raster)

	if mode_value == -9999:
		return None

	polygon['properties']['mode_value'] = mode_value
	return polygon

###########################################################################################################################
## 
###########################################################################################################################
def geojsons_to_dataframe(geojson_dicts):
    """
    Converts a list of GeoJSON dictionaries into a single DataFrame.
    
    Parameters:
    geojson_dicts (list): A list of dictionaries, each representing GeoJSON data.
    
    Returns:
    pd.DataFrame: A DataFrame containing data from all GeoJSON dictionaries.
    """
    # List to hold GeoDataFrames
    gdf_list = []
    
    # Iterate over each GeoJSON dictionary in the list
    for feature in geojson_dicts:
        row = feature['properties'].copy()  # Copy properties to a new dictionary
        row['geometry'] = shape(feature['geometry'])  # Convert geometry to shapely object
        gdf_list.append(row)
        
        # Create a GeoDataFrame from the list of rows
    gdf = gpd.GeoDataFrame(gdf_list, geometry='geometry', crs="EPSG:4326")
    
    return gdf

###########################################################################################################################
## 
###########################################################################################################################
def balance_dataset(df, category_col, sample_size=100):
    """
    Balances a dataset by downsampling overrepresented categories.
    
    Parameters:
    df (pd.DataFrame): The dataset containing the categories to balance.
    category_col (str): The name of the column with categorical values to balance.
    sample_size (int): Maximum number of samples per category. Default is 100.
    
    Returns:
    pd.DataFrame: A balanced DataFrame.
    """
    # List to hold balanced data
    balanced_data = []
    
    # Iterate over each category in the category column
    for category, group in df.groupby(category_col):
        # Determine the number of samples to keep
        if len(group) > sample_size:
            # Downsample if the group is larger than sample_size
            group_downsampled = resample(group, n_samples=sample_size, random_state=42)
            balanced_data.append(group_downsampled)
        else:
            # Keep the group as is if it's smaller than or equal to sample_size
            balanced_data.append(group)
    
    # Concatenate all the balanced groups
    balanced_df = pd.concat(balanced_data)
    return balanced_df


###########################################################################################################################
## 
###########################################################################################################################
def dataframe_to_geojson_features(df):
    """
    Converts each record in a DataFrame to a GeoJSON feature and appends to a list.
    
    Parameters:
    df (pd.DataFrame or gpd.GeoDataFrame): The DataFrame to convert.
    
    Returns:
    list: A list of GeoJSON features.
    """
    # Ensure the DataFrame is a GeoDataFrame to include geometry
    if not isinstance(df, gpd.GeoDataFrame):
        raise TypeError("The DataFrame must be a GeoDataFrame with a 'geometry' column.")
    
    # List to hold GeoJSON features
    features = []
    
    # Iterate over each row in the DataFrame
    for _, row in df.iterrows():
        # Convert each row to a GeoJSON feature
        feature = {
            "type": "Feature",
            "properties": row.drop("geometry").to_dict(),  # Exclude geometry from properties
            "geometry": mapping(row["geometry"])
        }
        features.append(feature)
    
    return features

###########################################################################################################################
## 
###########################################################################################################################
def attribute_with_cmonster_data(polygon_list,raster_path):
	"""
	Attribute polygons with cMonster data using a local raster (virtual raster).
	"""
	with multiprocessing.Pool(processes=30) as pool:
		results = pool.starmap(process_polygon, [(polygon, raster_path) for polygon in polygon_list])
	out = [x for x in results if x is not None]
	combined_df = geojsons_to_dataframe(out)
	balanced_df = balance_dataset(combined_df, category_col='mode_value', sample_size=500)
	geojson_features = dataframe_to_geojson_features(balanced_df)

	return geojson_features



###########################################################################################################################
## 
###########################################################################################################################
def export_feature_collection(fc,asset_id,asset_path):
	"""Start (and return) an ee.batch export of fc to asset_path + asset_id."""
	# Create the export task
	fc_task = ee.batch.Export.table.toAsset(
		collection=fc,
		description=asset_id,
		assetId=asset_path + asset_id
	)
	fc_task.start()
	return fc_task

def export_feature_collection_hold(fc,asset_id,asset_path):
	"""
	Dead code, not called anywhere in this repo. Identical to
	export_feature_collection but never calls task.start() (commented
	out) - looks like an abandoned dry-run/build-only variant.
	"""
	# Create the export task
	fc_task = ee.batch.Export.table.toAsset(
		collection=fc,
		description=asset_id,
		assetId=asset_path + asset_id
	)
	#fc_task.start()
	return fc_task


###########################################################################################################################
## 
###########################################################################################################################
def classifier(self, labeled_fc_path, unlabeled_fc_path, label_property, num_trees=200):
	"""
	Initialize the FeatureClassifier with the required parameters.

	:param labeled_fc_path: Path to the labeled FeatureCollection
	:param unlabeled_fc_path: Path to the unlabeled FeatureCollection
	:param label_property: The property to use as the label for classification
	:param num_trees: Number of trees in the random forest classifier (default: 50)
	"""
	self.labeled_fc = ee.FeatureCollection(labeled_fc_path).filter(ee.Filter.lt('mode_value',101))
	self.unlabeled_fc = ee.FeatureCollection(unlabeled_fc_path)
	self.label_property = label_property
	self.num_trees = num_trees
	self.predictor_variables = self.unlabeled_fc.first().propertyNames()
	self.labeled_fc = self.drop_null_features(self.labeled_fc,'tcw_ftv_6')
	self.unlabeled_fc = self.drop_null_features(self.unlabeled_fc,'tcw_ftv_6')

###########################################################################################################################
## 
###########################################################################################################################
def drop_null_features(fc, property_name):
	"""
	Drops features from a Feature Collection if they contain null values for a specific property.

	Parameters:
	- fc: ee.FeatureCollection, the feature collection to filter.
	- property_name: str, the name of the property to check for null values.

	Returns:
	- ee.FeatureCollection, the filtered feature collection.
	"""
	# Filter out features that have null values for the specified property
	filtered_fc = fc.filter(ee.Filter.notNull(property_name))
	return filtered_fc

###########################################################################################################################
## 
###########################################################################################################################
def _mutate_predictor_variables_list(__predictor_variables, __label_property=None):
	"""
	Drop 'system:index' and, if given, the classifier's own label property
	from a predictor-variable list. The label property is normally already
	absent from the unlabeled side's schema, but labeled_fc's own property
	list (where the label really does vary) is a common source for
	predictor_variables upstream - leaving it in would let the classifier
	train a trivial split on the label itself, then apply that same split
	structure at inference against whatever constant placeholder value the
	unlabeled side happens to use for that property, actively degrading
	real predictions rather than just being inert.
	"""
	__predictor_variables = __predictor_variables.filter(ee.Filter.neq('item', 'system:index'))
	if __label_property is not None:
		__predictor_variables = __predictor_variables.filter(ee.Filter.neq('item', __label_property))
	return __predictor_variables

###########################################################################################################################
##
###########################################################################################################################
def balance_training_classes(labeled_fc, label_property):
	"""
	Oversample minority classes (by exact duplication) so every class in
	labeled_fc contributes roughly as many training examples as the
	largest class. Earth Engine's Classifier API has no native per-
	example/per-class weighting, so duplication is the practical way to
	bias Random Forest's split search toward separating a class it would
	otherwise treat as rare.

	Verified live via 5-fold cross-validation (columbia-mts-bugnet 2026,
	classification_training='point_labels'): raises insectDisease recall
	53%->67% at a real precision cost (57%->45%), a deliberate recall-
	favoring tradeoff accepted at explicit user request, since the
	alternative (attributed_training_polygons_2012) has zero real
	insectDisease examples to begin with.
	"""
	hist = labeled_fc.aggregate_histogram(label_property).getInfo()
	if not hist:
		return labeled_fc

	target = max(hist.values())
	balanced = None
	for cls_str, n in hist.items():
		cls_fc = labeled_fc.filter(ee.Filter.eq(label_property, int(cls_str)))
		multiplier = max(1, round(target / n))
		replicated = cls_fc
		for _ in range(multiplier - 1):
			replicated = replicated.merge(cls_fc)
		balanced = replicated if balanced is None else balanced.merge(replicated)
	return balanced

###########################################################################################################################
##
###########################################################################################################################
def train_classifier(_labeled_fc,_label_property,_predictor_variables,_num_trees):
	"""
	Train a Random Forest classifier using the labeled data.
	"""
	_predictor_variables = _mutate_predictor_variables_list(_predictor_variables, _label_property)

	classifier = ee.Classifier.smileRandomForest(_num_trees).train(
		features=_labeled_fc,
		classProperty=_label_property,
		inputProperties=_predictor_variables
	)
	return classifier


###########################################################################################################################
## 
###########################################################################################################################
def classify_features(_unlabeled_fc,_classifier,heavy=0):
	"""
	Classify the unlabeled feature collection.

	:param classifier: The trained classifier to use for classifying features
	:return: The classified feature collection
	"""
	if heavy == 1:
		def cast_fire(f):
			count = ee.Number(f.get('count'))
			mag = ee.Number(f.get('mag'))

			# First condition: mag > 400 → classification = 21
			f = ee.Feature(ee.Algorithms.If(
				mag.gt(400),
				f.set({"classification": 21}),
				f
			))

			# Second condition: count > 4000 → classification = 40
			f = ee.Feature(ee.Algorithms.If(
				count.gt(4000),
				f.set({"classification": 40}),
				f
			))

			return f

	else:
		def cast_fire(f):
			count = ee.Number(f.get('count'))

			# Second condition: count > 4000 → classification = 40
			f = ee.Feature(ee.Algorithms.If(
				count.gt(4000),
				f.set({"classification": 40}),
				f
			))

			return f

	classified = _unlabeled_fc.classify(_classifier)
	return classified.map(cast_fire)



###########################################################################################################################
## 
###########################################################################################################################
def print_classified_features(self, classified_fc, limit=5):
	"""
	Print the first few classified features.

	:param classified_fc: The classified feature collection
	:param limit: Number of features to display (default: 5)
	"""
	print('Classified Features:', classified_fc.limit(limit).getInfo())




###########################################################################################################################
## 
###########################################################################################################################
#### Function to convert GeoJSON features to EE Features
def geojson_to_ee_feature(geojson,s_crs,t_crs):
	"""Reproject each GeoJSON feature from s_crs to t_crs and collect into an ee.FeatureCollection."""
	features = []
	for feature in geojson:
		feature = reproject_geojson(feature, s_crs, t_crs)
		geometry = feature['geometry']
		properties = feature['properties']

		# Create an Earth Engine feature from GeoJSON geometry and properties
		ee_feature = ee.Feature(ee.Geometry(geometry), properties)
		features.append(ee_feature)

	# Return a FeatureCollection from the list of EE Features
	return ee.FeatureCollection(features)

###########################################################################################################################
## 
###########################################################################################################################
def reproject_geojson(ft_geojson, src_epsg, target_epsg):
	"""
	Reproject the coordinates of a GeoJSON feature from the source EPSG to the target EPSG.

	Parameters:
	- ft_geojson: The input GeoJSON feature.
	- src_epsg: The EPSG code of the source CRS (e.g., 'EPSG:4326').
	- target_epsg: The EPSG code of the target CRS (e.g., 'EPSG:5070').
	"""
	# Initialize the Transformer from the source CRS to the target CRS
	transformer = Transformer.from_crs(src_epsg, target_epsg, always_xy=True)
	
	# Function to reproject coordinates based on the geometry type
	def reproject_coords(geometry):
		if geometry['type'] == 'Polygon':
			return [[list(transformer.transform(x, y)) for x, y in ring] for ring in geometry['coordinates']]
		elif geometry['type'] == 'MultiPolygon':
			return [[[list(transformer.transform(x, y)) for x, y in ring] for ring in poly] for poly in geometry['coordinates']]
		return geometry

	# Extract the geometry from the feature and reproject it
	geom = ft_geojson['geometry']
	ft_geojson['geometry']['coordinates'] = reproject_coords(geom)

	return ft_geojson

###########################################################################################################################
## 
###########################################################################################################################
def process_feature(index, f_list, src_epsg, target_epsg):
	"""
	Worker for feature_collection_to_geojson's multiprocessing pool:
	pull the feature at `index` out of `f_list` (client-side, via
	getInfo()), reproject it to target_epsg, and return it as a plain
	GeoJSON feature dict.
	"""
	# Convert the feature from GEE to a Python dict
	feature = ee.Feature(f_list.get(index)).getInfo()  # Get feature and convert to Python dict

	# Use the reprojector to reproject the feature using the provided EPSG codes
	feature = reproject_geojson(feature, src_epsg, target_epsg)

	return {
		"type": "Feature",
		"geometry": feature['geometry'],
		"properties": feature['properties']
		}


###########################################################################################################################
## 
###########################################################################################################################
def feature_collection_to_geojson(fc, src_epsg, target_epsg):
	"""
	Pull an entire ee.FeatureCollection client-side and reproject every
	feature from src_epsg to target_epsg in parallel (a 30-process
	pool, one process_feature() call per feature index). Returns a
	plain list of GeoJSON feature dicts, not a FeatureCollection dict.
	"""
	# Convert GEE FeatureCollection to a Python List object
	f_list = fc.toList(fc.size())
	# Create an empty GeoJSON structure
	geojson = {
		"type": "FeatureCollection",
		"features": []
	}
	# Create an empty GeoJSON structure
	geojson = []

	# Get the total number of features
	num_features = f_list.size().getInfo()  # Convert size() from GEE object to Python int

	# Create a pool of worker processes
	with multiprocessing.Pool(processes=30) as pool:

		# Map the process_feature function to each feature index in parallel
		results = pool.starmap(process_feature, [(i, f_list, src_epsg, target_epsg) for i in range(num_features)])

		# Collect valid features (filter out None values)
		# geojson['features'] = [res for res in results if res is not None]
		geojson = [res for res in results if res is not None]

	return geojson



###########################################################################################################################
## 
###########################################################################################################################
# Function to monitor the status of multiple tasks and update in place
def monitor_tasks(tasks):
	"""
	Dead code, not called anywhere in this repo. Would block, printing
	a live-updating one-line status for a list of ee.batch.Task objects
	(skipping any bare 0 placeholders) until every task reaches a
	terminal state, then print a final per-task summary.
	"""
	tasks = [i for i in tasks if i != 0]
	while any([task.status()['state'] in ['READY', 'RUNNING'] for task in tasks]):
		status_updates = []
		for i, task in enumerate(tasks):
			state = task.status()['state']
			status_updates.append(f"Task {i} status: {state}")

		# Print all task statuses on the same line
		sys.stdout.write("\r" + " | ".join(status_updates))
		sys.stdout.flush()  # Flush the output to ensure it's updated immediately

		time.sleep(30)  # Wait for 30 seconds before checking again

		# Final status check
		#print()  # Add a newline after final update
		for i, task in enumerate(tasks):
			state = task.status()['state']
			if state == 'COMPLETED':
				print(f"Task {i} completed successfully!")
			elif state == 'FAILED':
				print(f"Task {i} failed with error: {task.status().get('error_message', 'Unknown error')}")
			else:
				print(f"Task {i} ended with status: {state}")



###########################################################################################################################
## 
###########################################################################################################################
def rasterize_polygons(feature_collection, property_name, scale, region):
	"""Burn property_name into a raster (unmasked areas = 0), clipped to region."""
	# Create an empty image to burn the values into
	#empty_image = ee.Image()#.byte()
	# Rasterize the polygons by reducing them to an image based on the property
	rasterized = feature_collection.reduceToImage(
		properties=ee.List([ee.String(property_name)]),
		reducer=ee.Reducer.first()
	).unmask(0)  # Mask areas with no data (no polygons) as 0
	# Optionally clip the result to the region of interest
	rasterized = rasterized.clip(region.geometry())

	# Return the rasterized image
	return rasterized

###########################################################################################################################
## 
###########################################################################################################################
def filter_by_mode_value(feature_collection, low, lowmed, medhigh, high):
	"""
	Keep only features whose 'classification' falls in (low, lowmed) or
	(medhigh, high), merged into one collection - drops the middle band
	(lowmed..medhigh) entirely.
	"""
	# Filter the collection by the 'classification' property
	filtered_collection_low = feature_collection.filter(
		ee.Filter.And(
			ee.Filter.gt('classification', low),
			ee.Filter.lt('classification', lowmed)
		)
	)

	filtered_collection_high = feature_collection.filter(
		ee.Filter.And(
			ee.Filter.gt('classification', medhigh),
			ee.Filter.lt('classification', high)
		)
	)

	# Merge the two filtered collections
	filtered_collection_out = filtered_collection_low.merge(filtered_collection_high)

	# Return the filtered FeatureCollection
	return filtered_collection_out


def remove_wfigs_fire_polygons(feature_collection, year_property='yod'):
    """
    Direct ground-truth veto: drops any feature from feature_collection
    that spatially intersects a real WFIGS fire perimeter whose ignition
    year matches the feature's own year_property (yod - year of
    disturbance, already present on B1/B2 predictor polygons since
    CreatePredictorDisturbancePolygons).

    Exists to replace guesswork with ground truth for the one disturbance
    cause WFIGS can actually confirm directly, instead of leaving fire
    removal entirely to classify_features' decade-stale trained
    classifier plus its hardcoded count>4000/mag>400 overrides, and
    filter_by_mode_value's classification-code range filter (see that
    function's docstring) - none of which look at real fire data.

    WFIGS field names are Esri-truncated/deduplicated (not literal
    English names) - "attr_Fir_7" was identified empirically as the
    ignition/discovery-date equivalent; see create_forest_mask's
    docstring in modeling_utils.py for how that was confirmed. Every
    feature in feature_collection must already carry year_property
    (raises via GEE if any don't).
    """
    wfigs = ee.FeatureCollection("projects/emaprlab-general/assets/WFIGS")

    def add_fire_year(f):
        return f.set('fire_year', ee.Date(ee.Number(f.get('attr_Fir_7'))).get('year'))

    wfigs_yeared = wfigs.map(add_fire_year)

    join_filter = ee.Filter.And(
        ee.Filter.intersects(leftField='.geo', rightField='.geo'),
        ee.Filter.equals(leftField=year_property, rightField='fire_year'),
    )
    # outer=True is required: ee.Join.saveAll defaults to an INNER join,
    # which would drop every feature with zero fire matches (i.e. nearly
    # everything) instead of keeping them with an empty matches list.
    joined = ee.FeatureCollection(
        ee.Join.saveAll(matchesKey='fire_matches', outer=True)
        .apply(feature_collection, wfigs_yeared, join_filter)
    )

    original_props = feature_collection.first().propertyNames()

    def add_match_count(f):
        return f.set('fire_match_count', ee.List(f.get('fire_matches')).size())

    no_fire_match = joined.map(add_match_count).filter(ee.Filter.eq('fire_match_count', 0))
    return no_fire_match.select(original_props)


def get_fire_polygons(param):
    """
    Real fire perimeters within param['maskStartTime']/maskEndTime, from
    the source selected by param.get('fire_mask_source', 'wfigs'):
    - 'wfigs' (default, current): projects/emaprlab-general/assets/WFIGS,
      ignition-date field 'attr_Fir_7' - empirically identified, not a
      literal name match (WFIGS field names are Esri-truncated/
      deduplicated) - see create_forest_mask's docstring in
      modeling_utils.py for how that was confirmed.
    - 'mtbs' (the original pre-2026-08-19 source):
      USFS/GTAC/MTBS/burned_area_boundaries/v1, ignition-date field
      'Ig_Date'.
    Kept selectable via config, at explicit user request, so the
    pre-WFIGS forest-mask workflow can still be reproduced/compared
    against exactly, not just the current default.
    """
    source = param.get('fire_mask_source', 'wfigs')
    if source == 'wfigs':
        fc = ee.FeatureCollection("projects/emaprlab-general/assets/WFIGS")
        date_field = 'attr_Fir_7'
    elif source == 'mtbs':
        fc = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")
        date_field = 'Ig_Date'
    else:
        raise NotImplementedError(
            f"get_fire_polygons: unsupported param['fire_mask_source'] = {source!r}. "
            "Use 'wfigs' (default) or 'mtbs'."
        )
    return fc.filter(ee.Filter.And(
        ee.Filter.gte(date_field, param["maskStartTime"]),
        ee.Filter.lte(date_field, param["maskEndTime"]),
    ))


def rasterize_fire_polygons(param, fires):
    """
    Rasterize fires (from get_fire_polygons) to an unmasked-where-absent
    boolean fire-presence image, source-appropriate per
    param.get('fire_mask_source', 'wfigs'): 'mtbs' uses
    reduceToImage(properties=["Map_ID"], reducer=mean).gt(0) - kept
    byte-for-byte identical to the pre-2026-08-19 original so that
    workflow reproduces exactly - while 'wfigs' (default) uses paint(),
    which needs no schema-specific numeric property at all.
    """
    if param.get('fire_mask_source', 'wfigs') == 'mtbs':
        return fires.reduceToImage(properties=["Map_ID"], reducer=ee.Reducer.mean()).gt(0)
    return ee.Image().byte().paint(fires, 1)


def sample_predictor_bands_at_geometry(param, geometry, yod, fitted_img_asset, change_img_asset):
    """
    Sample the same predictor bands attribute_with_reference_data computes
    for real candidate polygons (mag/dur/preval/rate/dsnr, plus 4 years of
    each non-index fit band renamed *_ftv_1..4, oldest-to-newest ending at
    yod) - but at an arbitrary geometry/yod pair instead of a real B1/B2
    candidate polygon. Mirrors that function's 'predictor' branch image
    construction exactly (lowercased band names), just generalized to any
    geometry.

    fitted_img_asset/change_img_asset: full GEE asset paths for the real
    predictor fitted/change images matching yod's year - deliberately
    NOT derived from param['fitted_img_p']/param['predictor_change_img'],
    since those name the CURRENT run's own target year, which can differ
    from yod (e.g. attributing training points against an older, already-
    real production year while building a brand new run for a different
    year - confirmed a real case live: columbia-mts-bugnet's training
    points are keyed to 2019, which lives in the separate, pre-existing
    2019-v3/ folder, independent of whatever new folder the current run
    builds).

    Exists to attribute training points that have no matching candidate
    polygon to inherit predictor values from: 'stable' (non-disturbance)
    points, which are never real B1/B2 candidates in the first place, and
    'disturbance' points the automated mag-threshold candidate generation
    missed entirely - a real, valuable training signal (the "gap
    condition" a real disturbance can fail to become a candidate at all).
    """
    in_img = ee.Image(fitted_img_asset).addBands(ee.Image(change_img_asset))
    in_img = in_img.rename(in_img.bandNames().map(lambda s: ee.String(s).toLowerCase()))

    yod = ee.Number(yod)
    years = ee.List.sequence(yod.subtract(3), yod)
    yrs_int = ee.List.sequence(1, 4)
    other_indices = ee.List([item.lower() + '_ftv' for item in param['fit'] if item != param['index']])

    def make_band_names(year):
        year = ee.Number(year).format('%d')
        return other_indices.map(lambda index: ee.String(index).cat('_').cat(year))

    selected_bands = years.map(make_band_names).flatten()
    selected_bands_int = yrs_int.map(make_band_names).flatten()
    special_bands = ee.List(['mag', 'dur', 'preval', 'rate', 'dsnr'])
    selected_bands = selected_bands.cat(special_bands)
    selected_bands_int = selected_bands_int.cat(special_bands)

    raster_filtered = in_img.select(selected_bands, selected_bands_int)
    raster_values = raster_filtered.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=30,
        maxPixels=1e13,
    )

    # mag/dur/preval/rate/dsnr (and by extension the whole selection here)
    # are masked wherever LandTrendr found no change at all - reduceRegion
    # then omits that key entirely rather than returning e.g. 0, which
    # would otherwise silently corrupt the schema for exactly the
    # examples (stable points, missed-disturbance points) this function
    # exists to attribute. Default every expected key to 0 ("no
    # measurable change detected"), overwritten by any real value found.
    defaults = ee.Dictionary.fromLists(
        selected_bands_int, ee.List.repeat(0, selected_bands_int.size())
    )
    return defaults.combine(raster_values, overwrite=True)


def build_attributed_training_points(param, points, target_year, b2_asset, fitted_img_asset,
                                      change_img_asset, label_property='labelId'):
    """
    Build a labeled training FeatureCollection from real analyst-
    interpreted points (label_property values for 'disturbance'-state
    points: 20=clearcut, 21=partialHarvest, 30=development, 40=fire,
    50=insectDisease, which the 2012 set has zero real examples of) for
    one region, at one target_year. Built at explicit user request to
    refresh classify_polygons' stale 2012 training set with real,
    current, comprehensive labels.

    Only 'state'=='disturbance' points are used. The point dataset also
    has 'state'=='stable' points labeled by land-cover type (developed/
    cropland/grassShrub/treecover/water/wetland/barren) rather than
    disturbance type - training one classifier across both label spaces
    was tried and measured empirically to be a mistake: it collapses top-
    class confidence (max ~68% even self-classifying the training points)
    and misclassifies real B2 candidates - which already passed
    LandTrendr's change-magnitude threshold and so are never actually
    "stable" - as one of the stable land-cover classes ~14% of the time,
    including nearly all of the already-scarce insectDisease examples
    getting outvoted. B2 candidates are disturbance candidates by
    construction, so distinguishing them from stable land cover isn't
    this classifier's job.

    b2_asset/fitted_img_asset/change_img_asset: full GEE asset paths to
    target_year's real B2/fitted/change assets. Deliberately explicit
    rather than derived from param['assetDir'] - target_year is the
    training points' own year, which is very often a different, already-
    real historical production year from whatever new run this is called
    during (confirmed a real case live: columbia-mts-bugnet's training
    points are keyed to 2019, in the pre-existing 2019-v3/ folder,
    independent of whatever new folder the calling run itself builds).

    Points that spatially intersect a real b2_asset candidate polygon
    inherit that polygon's already-computed predictor properties directly
    (mag/dur/preval/etc.) - simplest, and guarantees values identical to
    what the real pipeline itself would compute. Points the automated
    candidate generation missed get predictor bands sampled fresh via
    sample_predictor_bands_at_geometry, at the point location, with
    yod=target_year. area_km2/perimeter_km are set to 0 for these
    point-sampled examples (a point has no real extent - a fabricated
    buffer size would be an arbitrary, and arguably more misleading,
    choice).

    Returns a FeatureCollection with the same schema classify_polygons
    expects on labeled_fc (mode_value + the predictor properties).
    """
    b2 = ee.FeatureCollection(b2_asset)

    disturbance_pts = points.filter(ee.Filter.eq('state', 'disturbance'))

    join_filter = ee.Filter.intersects(leftField='.geo', rightField='.geo', maxError=30)
    joined = ee.FeatureCollection(
        ee.Join.saveFirst(matchKey='match', outer=True).apply(disturbance_pts, b2, join_filter)
    )
    matched = joined.filter(ee.Filter.notNull(['match']))
    unmatched_disturbance = joined.filter(ee.Filter.notNull(['match']).Not())

    def from_match(f):
        f = ee.Feature(f)
        match = ee.Feature(f.get('match'))
        return match.set('mode_value', f.get(label_property))

    def from_fresh_sample(f):
        f = ee.Feature(f)
        values = sample_predictor_bands_at_geometry(
            param, f.geometry(), target_year, fitted_img_asset, change_img_asset
        )
        return f.set(values).set({
            'area_km2': 0,
            'perimeter_km': 0,
            'count': 1,
            'yod': target_year,
            'mode_value': f.get(label_property),
        })

    matched_out = matched.map(from_match)
    unmatched_out = unmatched_disturbance.map(from_fresh_sample)

    return matched_out.merge(unmatched_out)


###########################################################################################################################
##
###########################################################################################################################
def add_terrain_road_predictors(fc):
    """
    Append 'elevation'/'slope'/'dist_to_road' predictor properties to
    every feature in fc, zonal-mean reduced over each feature's own real
    geometry (correct whether that's a real B2 candidate polygon, or a
    point - training rows sampled fresh via sample_predictor_bands_at_
    geometry, or matched rows that inherited a real B2 polygon's
    geometry - reduceRegion over a Point at scale=30 just samples the one
    overlapping pixel, same as every other predictor band already
    computed this way).

    point_labels-only: NOT wired into attribute_with_reference_data,
    which is shared with legacy_2012 and must keep producing byte-
    identical B2 output for that path (see build_attributed_training_
    points' docstring). Adding new predictor columns there would
    silently drop every legacy_2012 training row instead of adding a
    feature, since drop_null_features has nothing to match on a property
    attributed_training_polygons_2012 was never given.

    Sources: USGS/SRTMGL1_003 (elevation + ee.Terrain.slope), and
    distance in meters to the nearest TIGER/2016/Roads feature (capped
    at searchRadius; defaulted to searchRadius itself - "at least this
    far" - wherever a polygon falls outside it, rather than silently
    dropping the property or defaulting to 0/"on a road").
    """
    search_radius = 50000

    elevation = ee.Image('USGS/SRTMGL1_003').rename('elevation')
    slope = ee.Terrain.slope(elevation).rename('slope')
    roads = ee.FeatureCollection('TIGER/2016/Roads')
    dist_to_road = roads.distance(searchRadius=search_radius, maxError=30).rename('dist_to_road')
    terrain_road_img = elevation.addBands(slope).addBands(dist_to_road)

    defaults = ee.Dictionary({'elevation': 0, 'slope': 0, 'dist_to_road': search_radius})

    def add_props(f):
        f = ee.Feature(f)
        values = terrain_road_img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=f.geometry(),
            scale=30,
            maxPixels=1e13,
        )
        return f.set(defaults.combine(values, overwrite=True))

    return fc.map(add_props)


###########################################################################################################################
##
###########################################################################################################################
def buffer_features(feature_collection, buffer_distance):
	"""Buffer every feature's geometry in feature_collection by buffer_distance meters."""
	# Define a function to buffer a single feature
	def buffer_feature(feature):
		# Buffer the geometry by the specified distance
		buffered_geometry = feature.geometry().buffer(buffer_distance)

		# Return a new feature with the buffered geometry and original properties
		return feature.setGeometry(buffered_geometry)

	# Apply the buffer to each feature in the collection
	buffered_collection = feature_collection.map(buffer_feature)

	# Return the buffered FeatureCollection
	return buffered_collection


###########################################################################################################################
## 
###########################################################################################################################
def list_and_delete_assets(asset_path):
	"""
	Interactive CLI helper: list every asset directly under asset_path
	and prompt (y/n) to delete them all at once, or one at a time.
	"""
	# List the assets in the specified folder or collection
	asset_list = ee.data.listAssets({'parent': asset_path})['assets']

	# Check if there are any assets
	if not asset_list:
		print(f"No assets found at {asset_path}")
		return

	# Display the number of assets found
	print(f"There are {len(asset_list)} assets in {asset_path}")

	# Ask the user if they want to delete all assets at once
	delete_all = input("Do you want to delete all assets at once? (y/n): ").lower()

	if delete_all == 'y':
		# Delete all assets
		for asset in asset_list:
			ee.data.deleteAsset(asset['name'])
			print(f"Deleted asset: {asset['name']}")
			print("All assets deleted.")
	else:
		# Go through each asset individually
		for asset in asset_list:
			# Ask the user for each asset
			delete_asset = input(f"Do you want to delete {asset['name']}? (y/n): ").lower()
			if delete_asset == 'y':
				ee.data.deleteAsset(asset['name'])
				print(f"Deleted asset: {asset['name']}")
			else:
				print(f"Skipped asset: {asset['name']}")
				print("Finished processing all assets.")

# Function to make start and end dates for composite time stamps --------------------------------------
def annual_window(start, end):
    """
    Dead code, not called anywhere in this repo, and broken as written:
    references start_date/end_date names that aren't parameters or
    locals of this function - would raise NameError if ever called.
    """
    year_list = ee.List.sequence(start, end, 1)
    first_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(start_date))
    second_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(end_date))
    dates = first_date.zip(second_date)
    return dates

# Filter a collection function
def filter_collection(year, start_day, end_day, aoi):
    """Filter the NASA HLS Landsat collection (HLSL30) by AOI, date window, and <30% cloud cover."""
    return ee.ImageCollection("NASA/HLS/HLSL30/v002") \
        .filterBounds(aoi) \
        .filterDate(f'{year}-{start_day}', f'{year}-{end_day}') \
        .filter(ee.Filter.lt('CLOUD_COVERAGE', 30))

def get_sr_collection(year, start_day, end_day, aoi):
    """Thin wrapper around filter_collection."""
    sr_collection = filter_collection(year, start_day, end_day, aoi)
    return sr_collection

# Function to combine collections
def get_combined_sr_collection(year, start_day, end_day, aoi):
    """Thin wrapper around get_sr_collection (a no-op passthrough today - name implies it once merged multiple sensor collections)."""
    hls = get_sr_collection(year, start_day, end_day, aoi)
    return hls

def b2_cloud_mask(image_collection):
    """Mask pixels where the B2 band exceeds 0.02, as a cheap cloud proxy."""
    def apply_mask(image):
        cloudMask = image.select('B2').lt(0.02)
        return image.mask(cloudMask)
    # Apply the mask to each image in the collection
    masked_collection = image_collection.map(apply_mask)
    return masked_collection

# Make a medoid composite with equal weight among indices
def mean_mosaic(in_collection, dummy_collection):
    """
    Build a cloud-masked mean composite of in_collection, falling back
    to dummy_collection if in_collection is empty (keeps a consistent
    band structure downstream even for a year with no imagery).
    """
    image_count = in_collection.toList(1).length()
    final_collection = ee.ImageCollection(ee.Algorithms.If(image_count.gt(0), in_collection, dummy_collection))
    final_collection = b2_cloud_mask(final_collection)
    return final_collection.mean()

# Function to apply medoid compositing function to a collection
def build_mosaic(year, start_day, end_day, aoi, dummy_collection):
    """Build one year's HLS mean-composite mosaic, scaled by 1000 and cast to uint16."""
    collection = get_combined_sr_collection(year, start_day, end_day, aoi)
    img = mean_mosaic(collection, dummy_collection).set('system:time_start', ee.Date.fromYMD(year, 8, 1).millis())
    return ee.Image(img).multiply(1000).toUint16()

# Function to build annual mosaic collection
def build_sr_collection(start_year, end_year, start_day, end_day, aoi):
    """
    Dead code, not called anywhere in this repo. Would build a
    multi-year ImageCollection of annual HLS mosaics (one build_mosaic
    call per year), each tagged with a 'composite_year' property.
    """
    dummy_collection = ee.ImageCollection([ee.Image([0, 0, 0, 0, 0, 0]).mask(ee.Image(0))])
    imgs = []
    for i in range(start_year, end_year + 1):
        tmp = build_mosaic(i, start_day, end_day, aoi, dummy_collection)
        imgs.append(tmp.set('composite_year', i).set('system:time_start', ee.Date.fromYMD(i, 8, 1).millis()))
    return ee.ImageCollection(imgs)

def build_lt_params(param):
    """
    Build (lt_collection_params, lt_params) for LandTrendr from
    param['platform'] - 'LS' (Landsat, default) or 'S2-10' (Sentinel-2,
    10m). Both ltgee.LandsatComposite and ltgee.Sentinel2Composite accept
    the same start_date/end_date/area_of_interest keys already assembled
    in param['composite_params'], so either can be built from it directly.
    Does not mutate param. run_params differs by platform - Sentinel-2's
    tighter revisit cadence tolerates a stricter fit (recoveryThreshold/
    bestModelProportion 0.95 vs 0.25/0.75, minObservationsNeeded 5 vs 6)
    per the existing hand-tuned Sentinel-2 templates this was extracted
    from (bugnet/templates/v3/s2-north-cascades-template.py).
    """
    platform = param.get('platform', 'LS')

    if platform == 'S2-10':
        sr_collection = Sentinel2Composite(**param['composite_params'])
        run_params = {
            'maxSegments': 6,
            'spikeThreshold': 0.9,
            'vertexCountOvershoot': 3,
            'preventOneYearRecovery': True,
            'recoveryThreshold': 0.95,
            'pvalThreshold': 0.05,
            'bestModelProportion': 0.95,
            'minObservationsNeeded': 5,
        }
    elif platform == 'LS':
        sr_collection = LandsatComposite(**param['composite_params'])
        run_params = {
            'maxSegments': 6,
            'spikeThreshold': 0.9,
            'vertexCountOvershoot': 3,
            'preventOneYearRecovery': True,
            'recoveryThreshold': 0.25,
            'pvalThreshold': 0.05,
            'bestModelProportion': 0.75,
            'minObservationsNeeded': 6,
        }
    else:
        raise NotImplementedError(
            f"build_lt_params: unsupported param['platform'] = {platform!r}. "
            "Only 'LS' (Landsat, default) and 'S2-10' (Sentinel-2) are implemented."
        )

    lt_collection_params = {
        "sr_collection": sr_collection,
        "index": param['index'],
        "ftv_list": param['fit'],
    }
    lt_params = {
        "lt_collection": lt_collection_params,
        "run_params": run_params,
    }
    return lt_collection_params, lt_params


def get_lt_last_seg_info(lt, idx):
    """
    Dead code, not called anywhere in this repo. Extracts the final
    LandTrendr segment's stats (year-of-detection plus mag/dur/preval/
    rate/dsnr) from a LandTrendr fit's segment array - was called by the
    original (pre-2024, since removed) CreateLTSDimage() pipeline stage
    to append segment stats onto the LTSD image before SNIC segmentation.
    See select_decline_predictor_bands()'s docstring.
    """
    segInfo = lt.get_segment_data('all', index_flip=True)
    endSeg = segInfo.arraySlice(1, -1, None, 1)
    
    def getLastSeg(img):
        arrRowNames = [['startYear', 'endYear', 'preval', 'postval', 'mag', 'dur', 'rate', 'dsnr']]
        endSegImg = img.arrayProject([0]).arrayFlatten(arrRowNames)
        yod = endSegImg.select('endYear').rename('yod')
        return endSegImg.addBands(yod).select(['yod', 'mag', 'dur', 'preval', 'rate', 'dsnr'])
    
    return getLastSeg(endSeg)

def lcms_forest_mask(start, end, param):
    """
    Build a boolean "was ever forest" mask: for each year from start
    through the hardcoded LCMS end year (2024), test whether that
    year's LCMS Land_Use band equals 3 (forest) for param['study_region'],
    then OR all years together.
    """
    dataset = ee.ImageCollection('USFS/GTAC/LCMS/v2024-10')
    ts = ee.List.sequence(start, 2024) #<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<HARDCODE TO END YEAR OF LCMS DATASET
    def query_year(yr):
        img = dataset.filter(ee.Filter.And(
            ee.Filter.eq('system:time_start', ee.Date(ee.String(ee.Number(yr).int().format()).cat(ee.String("-06-01"))).millis()),
            ee.Filter.eq('study_area', param['study_region'])
        )).first().select('Land_Use')
        return img.expression('band == 3', {'band': img})
    
    lcms_agg = ts.map(query_year)
    col = ee.ImageCollection(lcms_agg).sum().gt(0)
    return col


def generate_year_list(start_year, end_year, index):
    """Build the list of "{index}_ftv_{year}" band names for start_year..end_year inclusive."""
    year_list = []
    for year in range(start_year, end_year + 1):
        year_list.append(f"{index}_ftv_{year}")
    return year_list




def filter_ads(agent, severity, defol, ads_col, all):
    """
    Dead code, not called anywhere in this repo. Would filter an ADS
    FeatureCollection by some combination of agent/severity/defoliation
    (DAMCODE/AGENTCODE), depending on which of severity/defol are set.
    """
    if defol is None and severity is None:
        print("Mortality and defoliation not selected")
        return ads_col
    elif defol is not None and severity is not None:
        print("Both mortality and defoliation selected")
        if all:
            return ads_col.filter(ee.Filter.Or(ee.Filter.eq("DAMCODE", severity), ee.Filter.gt("DAMCODE", defol)))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.Or(ee.Filter.eq("DAMCODE", severity), ee.Filter.gt("DAMCODE", defol))))
    elif defol is None:
        print("Only defoliation selected")
        if all:
            return ads_col.filter(ee.Filter.eq("DAMCODE", severity))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.eq("DAMCODE", severity)))
    elif severity is None:
        print("Only mortality selected")
        if all:
            return ads_col.filter(ee.Filter.gt("DAMCODE", defol))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.gt("DAMCODE", defol)))
    else:
        print("Not sure what happened")

def agg_ads(startyear, focus_year, ads_col):
    """
    Dead code, not called anywhere in this repo. Would sum per-year
    ADS DAMCODE pixel counts (startyear..focus_year) into one
    self-masked aggregated image.
    """
    start_year = startyear
    end_year = focus_year

    def get_year_band_names(startYear, endYear):
        return [str(i) for i in range(startYear, endYear + 1)]

    year = get_year_band_names(start_year, end_year)

    def create_image(yr):
        return ads_col.reduceToImage(properties=['DAMCODE'], reducer=ee.Reducer.count()).rename(["yr_" + yr])

    image_list = [create_image(yr) for yr in year]
    agent_image = ee.Image(image_list)
    return agent_image.reduce(ee.Reducer.sum()).selfMask()

def dNBR(lt, start, end, indx, ftvLt, roi):
    """
    Dead code, not called anywhere in this repo (pre-dates
    refactor-bugnet-cleanup; already broken on master). Also buggy as
    written: `ltgee.getFittedData` doesn't exist - the ltgee package only
    has `LandTrendr.get_fitted_data(self, ...)` as an instance method.
    Left unfixed since nothing calls it; fix or delete if it's ever wired
    up for real.
    """
    def get_year_band_names(start, end):
        return ['yr_' + str(i) for i in range(start, end + 1)]

    yearNames = get_year_band_names(start, end)
    yearly_nbr = ltgee.getFittedData(lt, start, end, indx, ftvLt).clip(roi)
    yearly_nbr_pre = yearly_nbr.select(yearNames[:-1])
    yearly_nbr_post = yearly_nbr.select(yearNames[1:])
    return yearly_nbr_post.subtract(yearly_nbr_pre)


def snic_image(img):
    """
    Run GEE's SNIC segmentation on img (fixed size=5, compactness=1).
    Output bands are named "<input_band>_mean" per input band, plus a
    "clusters" band - see SNIC_decline_image for how those names get
    consumed downstream.
    """
    return ee.Algorithms.Image.Segmentation.SNIC(image=img, size=5, compactness=1)


def bayes_decline_probability(diff, threshold, noise_std, prior):
    """
    Posterior probability that `diff` (an older-minus-newer index value,
    so positive = decline) reflects real disturbance rather than natural
    interannual noise, via Bayes' rule over two equal-variance Gaussians:
    diff ~ N(0, noise_std) under "no disturbance", diff ~ N(threshold,
    noise_std) under "disturbance" - i.e. what used to be a hard cutoff
    (diff > threshold) becomes the mean of the disturbance distribution
    instead. With equal variances the posterior collapses algebraically
    to a logistic function of diff (derivation: the Gaussian normalizing
    constants and the diff**2 term cancel in the likelihood ratio,
    leaving a term linear in diff) - this *is* the Bayesian derivation of
    a sigmoid, not an arbitrary curve choice. `prior` is the assumed base
    rate of real disturbance among all pixels/pairs (before seeing diff).
    """
    log_prior_odds = float(np.log(prior / (1 - prior)))
    logit = diff.multiply(threshold / (noise_std ** 2)) \
                .add(log_prior_odds - (threshold ** 2) / (2 * noise_std ** 2))
    return ee.Image(1).divide(ee.Image(1).add(logit.multiply(-1).exp()))


def decline_probability_to_class_band(decline_probability, n_classes=5):
    """
    Quantize a continuous decline_probability band (0-1) into an integer
    0..n_classes-1 'decline_score' band. Exists only for
    modeling_utils.build_kmeans_sample's stratifiedSample(classBand=
    "decline_score", ...) call, which needs a discrete, low-cardinality
    band to stratify on - a raw float band would give it near-unique
    strata per pixel. n_classes=5 matches the old decline_score's
    cardinality (an integer count 0-4) so stratified-sample behavior
    stays roughly comparable in shape to before.
    """
    return decline_probability.multiply(n_classes).floor().min(n_classes - 1) \
                               .toInt().rename('decline_score')


def SNIC_decline_image(param, noise_std=None, prior_disturbance=0.05, probability_threshold=0.9,
                        min_years_declining=2, single_year_multiplier=1.5, return_score=False):
    """
    Score decline on the SNIC-segmented predictor fitted stack
    (param['snicName']), mirroring LTSD_decline_score's year-over-year
    logic but reading bands the way SNIC actually names them instead of
    the fictional 'yr_<offset>_nbr_mean' convention the old (pre-refactor)
    version of this function assumed.

    bnet.snic_image() runs ee.Algorithms.Image.Segmentation.SNIC on
    param['LTSDdir'] + param['LTSDname'], which every real parameter file
    sets equal to param['fitted_img_p'] (confirmed against templates in
    git history, e.g. commit f72a314^:parameters/2024/v2/
    sw_oregon_bentley_config_opt3_2022.py). SNIC names each output band
    "<input_band>_mean", and fitted_img_p's bands are named
    "{INDEX}_ftv_{year}" (bnet.get_fitted_stack / rename_bands_by_year,
    INDEX matching entries in param['fit'], e.g. "TCG_ftv_2020") - so the
    segmented image's bands are "TCG_ftv_2020_mean" etc., plus a
    "clusters" band.

    Only tests TCG/TCW (not TCB) - doesn't reference NBR, rate, or dur:
    those are LandTrendr change-detection stats that are never merged
    into fitted_img_p, so no band on this image could ever satisfy them.

    param['decline_method'] selects which of three real historical
    scoring approaches to use (default 'bayesian', the live one as of
    2026-08-19) - kept selectable via config, at explicit user request,
    for generating comparison datasets against the currently-live method:

    - 'bayesian': each pair's TCG/TCW diff becomes a posterior
      probability via bayes_decline_probability (param['decline_thresholds']/
      param['decline_step'] still taper the assumed disturbance-mean
      shift older-pairs-need-more, now feeding a probability model
      instead of a hard cutoff). TCG/TCW combine by multiplying
      (independence, mirrors the old .And()); the 4 pairs combine via
      noisy-OR: decline_probability = 1 - prod(1 - p_pair). Returns a
      continuous decline_probability band (0-1, never hard-thresholded
      internally) plus a quantized decline_score companion band (0-4,
      decline_probability_to_class_band) purely so
      modeling_utils.build_kmeans_sample's stratifiedSample(classBand=
      "decline_score", ...) still has a discrete band to stratify on.
      Masked at probability_threshold (default 0.9) for the non-
      return_score output.
    - 'persistence_or_single_year' (same-day predecessor of 'bayesian',
      still hard-cutoff-based): hard tapered .gt() cutoff per pair, pixel
      kept if decline_score (count of passing pairs) >= min_years_declining,
      OR any single pair's diff exceeds an untapered, stricter
      base_thresholds*single_year_multiplier test. Returns integer
      decline_score (0-4) and boolean single_year_decline bands.
    - 'persistence' (the original pre-2026-08-19 logic): same hard
      tapered cutoff per pair, pixel kept only if decline_score >=
      min_years_declining - no single-year handling at all, so a single
      very strong disturbance year that doesn't persist into the next
      pair could be missed entirely (this is the real gap the
      'persistence_or_single_year'/'bayesian' methods were built to
      close).

    If return_score is True: 'bayesian' returns just decline_probability
    (no masking); the two hard-threshold methods return just
    decline_score (no masking).
    """
    method = param.get('decline_method', 'bayesian')
    im = ee.Image(param["assetDir"] + param["snicName"])
    std_end_year = param['target']
    base_thresholds = param['decline_thresholds']
    taper_step = param['decline_step']
    noise_std = noise_std or {k: v / 2 for k, v in base_thresholds.items()}

    # Generate 5 consecutive years: oldest (1) to most recent (5)
    years = {i: str(std_end_year - (5 - i)) for i in range(1, 6)}

    bands = {
        f'tcg_{i}': im.select(f'TCG_ftv_{years[i]}_mean') for i in range(1, 6)
    } | {
        f'tcw_{i}': im.select(f'TCW_ftv_{years[i]}_mean') for i in range(1, 6)
    }

    if method == 'bayesian':
        pair_probs = []
        for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
            taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper
            t_tcg = base_thresholds['tcg'] - taper
            t_tcw = base_thresholds['tcw'] - taper

            diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i + 1}'])
            diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i + 1}'])

            p_tcg = bayes_decline_probability(diff_tcg, t_tcg, noise_std['tcg'], prior_disturbance)
            p_tcw = bayes_decline_probability(diff_tcw, t_tcw, noise_std['tcw'], prior_disturbance)
            pair_probs.append(p_tcg.multiply(p_tcw))

        not_declining = ee.Image(1).subtract(pair_probs[0])
        for p in pair_probs[1:]:
            not_declining = not_declining.multiply(ee.Image(1).subtract(p))
        decline_probability = ee.Image(1).subtract(not_declining).rename('decline_probability')

        if return_score:
            return decline_probability
        return im.updateMask(decline_probability.gte(probability_threshold)) \
                 .addBands(decline_probability) \
                 .addBands(decline_probability_to_class_band(decline_probability))

    elif method in ('persistence', 'persistence_or_single_year'):
        diffs = []
        single_year_flags = []
        for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
            taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper
            t_tcg = base_thresholds['tcg'] - taper
            t_tcw = base_thresholds['tcw'] - taper

            diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i + 1}'])
            diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i + 1}'])

            diffs.append(diff_tcg.gt(t_tcg).And(diff_tcw.gt(t_tcw)))
            if method == 'persistence_or_single_year':
                single_year_flags.append(
                    diff_tcg.gt(base_thresholds['tcg'] * single_year_multiplier)
                    .And(diff_tcw.gt(base_thresholds['tcw'] * single_year_multiplier))
                )

        decline_score = diffs[0]
        for d in diffs[1:]:
            decline_score = decline_score.add(d)

        if method == 'persistence_or_single_year':
            single_year_decline = single_year_flags[0]
            for f in single_year_flags[1:]:
                single_year_decline = single_year_decline.Or(f)
            is_declining = decline_score.gte(min_years_declining).Or(single_year_decline)
        else:
            is_declining = decline_score.gte(min_years_declining)

        if return_score:
            return decline_score.rename('decline_score')
        result = im.updateMask(is_declining).addBands(decline_score.rename('decline_score'))
        if method == 'persistence_or_single_year':
            result = result.addBands(single_year_decline.rename('single_year_decline'))
        return result

    else:
        raise NotImplementedError(
            f"SNIC_decline_image: unsupported param['decline_method'] = {method!r}. "
            "Use 'bayesian' (default), 'persistence_or_single_year', or 'persistence'."
        )


def decline_image(param):
    """
    Dead code, not called anywhere in this repo. This docstring
    previously listed im/std_end_year/indices/thresholds/logic_template/
    num_years as parameters, none of which match the actual signature
    (just `param`) - left over from an earlier version of this function.

    Would build a per-index decline expression from
    param['decline_template'] and param['decline_thresholds'] (keyed by
    UPPERCASE index names matching param['fit'], e.g. "TCB" - contrast
    with the live LTSD_decline_score/SNIC_decline_image, which use fixed
    lowercase keys 'tcb'/'tcg'/'tcw' instead), but the final return
    statement ignores that built expression entirely and uses a
    different, hardcoded TCG/TCW-only expression instead (see the
    commented-out line above it for a third, even earlier variant).
    """
    im = ee.Image(param.get('sharedAssetDir', param['assetDir']) + param['fitted_img_p'])
    # Build band dictionary
    band_dict = {}
    for index in param['fit']:
        for i in range(param['agent_lookback']):
            key = f"{index}_{i+1}"
            year = param['target'] - (param['agent_lookback'] - 1 - i)
            band_dict[key] = im.select(f"{index}_ftv_{year}")

    # Generate expressions for each index using thresholds
    def decline_expr(index):
        t1, t2 = param['decline_thresholds'].get(index, (100, 100))
        if index == "TCB":
            return f"(({index}_3 - {index}_4 > {t1}) && ({index}_4 - {index}_5 > {t2}))"
        elif index == "TCG":
            return f"(({index}_4 - {index}_3 > {t1}) && ({index}_5 - {index}_4 > {t2}))"
        elif index == "TCW":
            return f"(({index}_4 - {index}_3 > {t1}) && ({index}_5 - {index}_4 > {t2}))"

    # Build expression string by filling in the logic template
    expression = param['decline_template'].format(**{index: decline_expr(index) for index in param['fit']})
    #return im.mask(im.expression("((TCW_4 - TCW_5 < 200 ) && (TCW_4 - TCW_5 > 100 )) && ((TCG_4 - TCG_5 < 200 )&&(TCG_4 - TCG_5 > 100 )) || ((TCG_3 - TCG_4 > 100) && (TCG_4 - TCG_5 > 100 )) || ((TCW_3 - TCW_4 > 100) && (TCW_4 - TCW_5 > 100))", band_dict))
    return im.mask(im.expression("((TCG_3 - TCG_4 > 100) && (TCG_4 - TCG_5 > 100 )) || ((TCW_3 - TCW_4 > 100) && (TCW_4 - TCW_5 > 100))", band_dict))

def LTSD_decline_score(param, base_thresholds={'tcb': 70, 'tcg': 50, 'tcw': 50}, taper_step=10,
                        noise_std=None, prior_disturbance=0.05, probability_threshold=0.9,
                        min_years_declining=2, single_year_multiplier=1.5, return_score=False):
    """
    The live decline scorer for the LTSD path (configName/decline_path
    == "ltsd", the only decline algorithm every real historical run has
    exercised end-to-end - see docs/config-layout.md). base_thresholds/
    taper_step keyword defaults are unused in practice: both get
    immediately overwritten from param['decline_thresholds']/
    param['decline_step']. TCB is not used in any method here (this file
    has never used it in the pass/fail test - see the historical
    commented-out diff_tcb.And(...) reference in git history).

    param['decline_method'] selects which of three real historical
    scoring approaches to use (default 'bayesian', the live one as of
    2026-08-19) - kept selectable via config, at explicit user request,
    for generating comparison datasets against the currently-live method.
    See SNIC_decline_image's docstring for the full description of all
    three ('bayesian' / 'persistence_or_single_year' / 'persistence') -
    identical logic here, just reading fitted_img_p's un-suffixed band
    names instead of SNIC's "_mean"-suffixed ones.

    If return_score is True: 'bayesian' returns just decline_probability
    (no masking); the two hard-threshold methods return just
    decline_score (no masking). Otherwise returns fitted_img_p (all
    bands) masked and with the method's score band(s) appended.
    """
    method = param.get('decline_method', 'bayesian')
    im = ee.Image(param.get('sharedAssetDir', param['assetDir']) + param['fitted_img_p'])
    std_end_year = param['target']
    base_thresholds = param['decline_thresholds']
    taper_step= param['decline_step']
    noise_std = noise_std or {k: v / 2 for k, v in base_thresholds.items()}

    # Generate 5 consecutive years: oldest (1) to most recent (5)
    years = {i: str(std_end_year - (5 - i)) for i in range(1, 6)}

    bands = {
        f'tcg_{i}': im.select(f'TCG_ftv_{years[i]}') for i in range(1, 6)
    } | {
        f'tcw_{i}': im.select(f'TCW_ftv_{years[i]}') for i in range(1, 6)
    }

    if method == 'bayesian':
        # Calculate a posterior disturbance probability per year-pair with tapered thresholds
        pair_probs = []
        for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
            taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper
            t_tcg = base_thresholds['tcg'] - taper
            t_tcw = base_thresholds['tcw'] - taper

            diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i+1}'])
            diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i+1}'])

            p_tcg = bayes_decline_probability(diff_tcg, t_tcg, noise_std['tcg'], prior_disturbance)
            p_tcw = bayes_decline_probability(diff_tcw, t_tcw, noise_std['tcw'], prior_disturbance)
            pair_probs.append(p_tcg.multiply(p_tcw))

        # Combine pairs via noisy-OR: P(at least one pair shows real disturbance)
        not_declining = ee.Image(1).subtract(pair_probs[0])
        for p in pair_probs[1:]:
            not_declining = not_declining.multiply(ee.Image(1).subtract(p))
        decline_probability = ee.Image(1).subtract(not_declining).rename('decline_probability')

        if return_score:
            return decline_probability
        return im.updateMask(decline_probability.gte(probability_threshold)) \
                 .addBands(decline_probability) \
                 .addBands(decline_probability_to_class_band(decline_probability))

    elif method in ('persistence', 'persistence_or_single_year'):
        diffs = []
        single_year_flags = []
        for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
            taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper
            t_tcg = base_thresholds['tcg'] - taper
            t_tcw = base_thresholds['tcw'] - taper

            diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i+1}'])
            diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i+1}'])

            diffs.append(diff_tcg.gt(t_tcg).And(diff_tcw.gt(t_tcw)))
            if method == 'persistence_or_single_year':
                single_year_flags.append(
                    diff_tcg.gt(base_thresholds['tcg'] * single_year_multiplier)
                    .And(diff_tcw.gt(base_thresholds['tcw'] * single_year_multiplier))
                )

        decline_score = diffs[0]
        for d in diffs[1:]:
            decline_score = decline_score.add(d)

        if method == 'persistence_or_single_year':
            single_year_decline = single_year_flags[0]
            for f in single_year_flags[1:]:
                single_year_decline = single_year_decline.Or(f)
            is_declining = decline_score.gte(min_years_declining).Or(single_year_decline)
        else:
            is_declining = decline_score.gte(min_years_declining)

        if return_score:
            return decline_score.rename('decline_score')
        result = im.updateMask(is_declining).addBands(decline_score.rename('decline_score'))
        if method == 'persistence_or_single_year':
            result = result.addBands(single_year_decline.rename('single_year_decline'))
        return result

    else:
        raise NotImplementedError(
            f"LTSD_decline_score: unsupported param['decline_method'] = {method!r}. "
            "Use 'bayesian' (default), 'persistence_or_single_year', or 'persistence'."
        )


def get_training_points(recovery, disturbances, roi, referImage, ads_in_roi):
    """
    Dead code, not called anywhere in this repo. ads_in_roi is unused.
    Would sample referImage at disturbances (labeled 1) and recovery
    (labeled 0) point/polygon locations and merge them into one labeled
    training FeatureCollection.
    """
    extract_sample_down = referImage.sampleRegions(collection=disturbances, scale=30, geometries=True, tileScale=10)
    extract_sample_up = referImage.sampleRegions(collection=recovery, scale=30, geometries=True, tileScale=10)
    
    def label_down(feat):
        return feat.set({"label": 1})
    
    def label_up(feat):
        return feat.set({"label": 0})
    
    attri_label_down = extract_sample_down.map(label_down)
    attri_label_up = extract_sample_up.map(label_up)
    return attri_label_down.merge(attri_label_up)


def get_ref_image(lt, ltstartYear, yer, fit, roi):
    """
    Dead code, not called anywhere in this repo. fit/roi are unused.
    Would flatten LandTrendr's raw TCB fitted-value array band
    (lt.data.select(['ftv_tcb_fit'])) into one band per year - a
    different, lower-level API than the ltgee-wrapped
    lt.get_fitted_data() used elsewhere in this file.
    """
    tcb_years = generate_year_list(ltstartYear, yer,'tcb')
    fitted_tcb = lt.data.select(['ftv_tcb_fit']).arrayFlatten([tcb_years])
    return fitted_tcb


def tasselCapMask(bnet):
    """
    Build a bright/non-forest mask (0 = masked out) by thresholding the
    target year's TCB fitted band against bnet['brightness_value'] -
    note that value is read and used as a STRING (concatenated
    directly into the expression), so a non-string there raises a
    TypeError at call time, not at param-load time.
    """
    # Run the LandTrendr algorithm
    targetImage = ee.Image(bnet['LTSDdir']+bnet['fitted_img_p'])
    val = [item.upper() for item in bnet['fit'] if item.lower() == "tcb"]
    tcb = targetImage.select([val[0]+"_ftv_" + str(bnet['target'])])
    
    tcb_mask = tcb.expression('band > '+bnet['brightness_value']+' ? 0 : 1', {'band': tcb}) # 2200

    return tcb_mask

def select_decline_predictor_bands(img, target_year, fit, decline_path):
    """
    Select and rename the RF-classifier predictor bands from a real
    declineName image (LTSD_decline_score's or SNIC_decline_image's
    output - both preserve their source's full band set plus trailing
    decline_probability/decline_score bands). decline_path ('snic' or
    'ltsd', i.e. param['decline_path']) matters because the two paths' source bands
    are named differently: LTSD_decline_score's source (fitted_img_p) is
    "{INDEX}_ftv_{year}", but SNIC_decline_image's source has already
    been through GEE's SNIC op, which appends "_mean" to every band
    name - "{INDEX}_ftv_{year}_mean". Confirmed directly against a real
    SNIC-path decline image (2026-08-16): its bands really do carry the
    "_mean" suffix, this isn't a hypothetical.

    Replaces rename_img/rename_img_opt3 (removed 2026-08-16), which
    positionally renamed a fixed 40/42-band image that hasn't existed
    since this repo's original CreateLTSDimage()/standardized_lt_image()/
    get_lt_last_seg_info() pipeline stage was dropped in favor of
    LTSDname = fitted_img_p directly (see docs/config-layout.md and
    SNIC_decline_image's docstring) - that migration was never carried
    through to proportion_calc/predict, so this had been silently
    unreachable (only exercised when param['ADS_path']['on'] is true,
    which no real run sets) since whenever that migration happened.

    Reimplements the *intent* of the original design instead of
    resurrecting the dropped pipeline stage: for each index in fit and
    each of 5 tapered years (target_year minus 9, 5, 2, 1, 0 - the same
    sparse year selection SNIC_decline_image uses), selects the source
    band by name and also computes a per-pixel, mean-centered
    "standardized" version across those 5 years (the original
    standardized_lt_image's own feature engineering) - 5 * len(fit) raw
    bands renamed "yr_<year>_<index>", plus 5 * len(fit) standardized
    bands renamed "yr_<year>_<index>_ltsd".

    Does not select or require 'clusters'/'seeds' - those are SNIC
    segmentation artifacts (present only on SNIC_decline_image's output,
    absent from LTSD_decline_score's), and were never used as classifier
    predictors even under the old scheme (predict() explicitly drops
    them from inputProperties).
    """
    years = [str(target_year - i) for i in [9, 5, 2, 1, 0]]
    suffix = "_mean" if decline_path == "snic" else ""

    tapered_bands = []
    standardized_bands = []
    for index in fit:
        idx_lower = index.lower()
        raw = img.select(
            [f"{index}_ftv_{year}{suffix}" for year in years],
            [f"yr_{year}_{idx_lower}" for year in years],
        )
        tapered_bands.append(raw)
        mean = raw.reduce(ee.Reducer.mean())
        standardized = raw.subtract(mean).rename(
            [f"yr_{year}_{idx_lower}_ltsd" for year in years]
        )
        standardized_bands.append(standardized)

    out = standardized_bands[0]
    for band in standardized_bands[1:] + tapered_bands:
        out = out.addBands(band)
    return out

def rename_ltsd_img(img, target_year):
    """
    Dead code, not called anywhere in this repo. Matches the exact
    46-band shape the original (pre-2024) CreateLTSDimage() pipeline
    stage produced: standardized_lt_image()'s 40 bands (5 tapered years
    x 4 indices, both raw and mean-centered/"_ltsd") + 6 LandTrendr
    segment stats from get_lt_last_seg_info() (yod/mag/dur/preval/rate/
    dsnr) - both of those functions, and the CreateLTSDimage() stage
    that combined them, are themselves dead/removed. See
    select_decline_predictor_bands()'s docstring and
    docs/config-layout.md for how this repo's architecture moved past
    this scheme.
    """
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    
    return img.select(img.bandNames(), [
        'yr_9_nbr_ltsd', 'yr_5_nbr_ltsd', 'yr_2_nbr_ltsd', 'yr_1_nbr_ltsd', 'yr_0_nbr_ltsd',
        'yr_9_tcb_ltsd', 'yr_5_tcb_ltsd', 'yr_2_tcb_ltsd', 'yr_1_tcb_ltsd', 'yr_0_tcb_ltsd',
        'yr_9_tcg_ltsd', 'yr_5_tcg_ltsd', 'yr_2_tcg_ltsd', 'yr_1_tcg_ltsd', 'yr_0_tcg_ltsd',
        'yr_9_tcw_ltsd', 'yr_5_tcw_ltsd', 'yr_2_tcw_ltsd', 'yr_1_tcw_ltsd', 'yr_0_tcw_ltsd',
        "yr_9_nbr", "yr_5_nbr", "yr_2_nbr", "yr_1_nbr", "yr_0_nbr",
        "yr_9_tcb", "yr_5_tcb", "yr_2_tcb", "yr_1_tcb", "yr_0_tcb",
        "yr_9_tcg", "yr_5_tcg", "yr_2_tcg", "yr_1_tcg", "yr_0_tcg",
        "yr_9_tcw", "yr_5_tcw", "yr_2_tcw", "yr_1_tcw", "yr_0_tcw",
        "yod", "mag", "dur", "preval", "rate", "dsnr"
    ])

def calc_prop(ads_data, kmeans_data):
    """
    Dead code, not called anywhere in this repo. Would compute, per key
    in kmeans_data, the percentage ads_data[k] / kmeans_data[k] * 100
    (-1 if ads_data has no entry for that key).
    """
    def calculate_proportion(k):
        top = ads_data.getNumber(k) if ads_data.contains(k) else ee.Number(-1)
        bottom = kmeans_data.getNumber(k)
        return top.divide(bottom).multiply(100)

    return kmeans_data.map(calculate_proportion)

def ltcalc(year, feat):
    """
    Dead code, not called anywhere in this repo. Would filter feat to
    polygons with the given year-of-detection, then keep only those
    that are long/thin (perimeter-to-area ratio > 20) or very large
    (area > 9,500,000 sq units) - looks like a shape-based filter for
    likely-artifact polygons.
    """
    target = feat.filter(ee.Filter.eq('yod', year))
    target = target.map(lambda fe: fe.set('area', fe.area(1)))
    target = target.map(lambda fe: fe.set('perimeter', fe.perimeter(1)))
    target = target.map(lambda fe: fe.set('rati', fe.getNumber('area').divide(fe.getNumber('perimeter'))))
    return target.filter(ee.Filter.Or(ee.Filter.gt('rati', 20), ee.Filter.gt('area', 9500000)))
