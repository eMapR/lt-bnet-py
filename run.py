# import 
#import mod as bnet
#import main
from ltgee import LandTrendr, LandsatComposite, LtCollection
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
ee.Initialize(project="r6-bugnet")
#-------------------------------------------------------------------
# Image processing-------------------------------------------------------------------
def rename_bands_by_year(image, index, start_year, end_year):
	"""Rename bands in the image by year."""
	num_years = end_year - start_year+1
	new_band_names = [f"{index}_ftv_{start_year + i}" for i in range(num_years)]
	if len(image.bandNames().getInfo()) == len(new_band_names):
		return image.rename(new_band_names)
	else:
		print("error in: rename_bands_by_year-different number of band names")
		return 0


def get_fitted_stack(lt,prefix,parameters):

	start_year = parameters['composite_params']['start_date'].year
	end_year = parameters['composite_params']['end_date'].year
	selection = 10
	start_date = parameters['composite_params']['start_date']
	end_date = parameters['composite_params']['end_date']
	if prefix == "fitted_training":

		# Extract fitted data for each index 8 9 10 11 12
		nbr = rename_bands_by_year(lt.get_fitted_data("nbr", start_date=start_date, end_date=end_date),'nbr',start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		tcb = rename_bands_by_year(lt.get_fitted_data("tcb", start_date=start_date, end_date=end_date),'tcb',start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		tcg = rename_bands_by_year(lt.get_fitted_data("tcg", start_date=start_date, end_date=end_date),'tcg',start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])
		tcw = rename_bands_by_year(lt.get_fitted_data("tcw", start_date=start_date, end_date=end_date),'tcw',start_year, end_year).select([3,4,5,6,7,8,9,10,11,12])

		# Merge all predictor data into a final stack
		stack = nbr.addBands(tcb).addBands(tcg).addBands(tcw)

		return stack
	else:
		# Extract fitted data for each index
		band_count = ((end_year+1) - start_year)
		last_bands = ee.List.sequence(band_count - selection, band_count - 1)
		# Extract fitted data for each index
		nbr = rename_bands_by_year(lt.get_fitted_data("nbr", start_date=start_date, end_date=end_date),'nbr',start_year, end_year).select(last_bands)
		tcb = rename_bands_by_year(lt.get_fitted_data("tcb", start_date=start_date, end_date=end_date),'tcb',start_year, end_year).select(last_bands)
		tcg = rename_bands_by_year(lt.get_fitted_data("tcg", start_date=start_date, end_date=end_date),'tcg',start_year, end_year).select(last_bands)
		tcw = rename_bands_by_year(lt.get_fitted_data("tcw", start_date=start_date, end_date=end_date),'tcw',start_year, end_year).select(last_bands)

		# Merge all predictor data into a final stack
		stack = nbr.addBands(tcb).addBands(tcg).addBands(tcw)

		return stack


def export_image(stack, params, asset,scale=30, max_pixels=1e13):
	"""Export the image to Google Earth Engine Assets."""
	# Define export parameters
	img_task = ee.batch.Export.image.toAsset(
		image=stack.clip(params['aoi']),
		description=asset,  # Task name
		assetId=params['assetDir'] + asset,  # Path in your GEE assets
		region=params['aoi'].geometry(),  # The area to export
		scale=scale,  # Resolution in meters per pixel
		maxPixels=max_pixels  # Maximum number of pixels allowed to export
	)
	img_task.start() 
	return img_task 
#<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<here
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------

def vectorize_disturbance(change_image,params):
	disturbance_polygons = change_image.select('yod').reduceToVectors(
		reducer=ee.Reducer.countEvery(),
		geometry=params['aoi'],
		scale=30,
		geometryType="polygon",
		labelProperty='yod',
		maxPixels=1e13,
		tileScale=8
	)
	return disturbance_polygons



#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------


def attribute_with_reference_data(params,who):
	"""
	Attribute the polygons with reference data from the raster stack.
	"""
	def _process_polygon(polygon):
		yod = ee.Number(polygon.get('yod'))
		#count = ee.Number(polygon.get('count')).getInfo()
		years = ee.List.sequence(yod.subtract(3), yod)
		yrs_int = ee.List.sequence(1,4)
		indices = ee.List(['nbr_ftv', 'tcb_ftv', 'tcg_ftv', 'tcw_ftv'])

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

		#if count > 4000:
		#	return polygon.set(raster_values).set({'area_km2': area,'perimeter_km': perimeter,'mode_value': 40})
		#else:
		return polygon.set(raster_values).set({'area_km2': area,'perimeter_km': perimeter, 'mode_value': 0})

	if who == 'training':
                in_img = ee.Image(params['assetDir'] + params['fitted_img_t']).addBands(ee.Image(params['assetDir'] + params['training_change_img']))
                in_fc = ee.FeatureCollection(params['assetDir'] + params['disturbance_polygons_training'])
                return in_fc.filter(ee.Filter.And(ee.Filter.gt('count',75),ee.Filter.lt('count',50000))).map(_process_polygon)
	else:
                in_img = ee.Image(params['assetDir'] + params['fitted_img_p']).addBands(ee.Image(params['assetDir'] + params['predictor_change_img']))
                in_fc = ee.FeatureCollection(params['assetDir'] + params['disturbance_polygons_predictor'])
                return in_fc.map(_process_polygon)


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

		if any(value >= 0.50 for value in proportions.values()):
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
        # Extract features and convert each feature into a row with geometry
        #features = geojson['features']
        #rows = []
        #for feature in features:
        row = feature['properties'].copy()  # Copy properties to a new dictionary
        row['geometry'] = shape(feature['geometry'])  # Convert geometry to shapely object
        gdf_list.append(row)
        
        # Create a GeoDataFrame from the list of rows
    gdf = gpd.GeoDataFrame(gdf_list, geometry='geometry', crs="EPSG:4326")
        #gdf_list.append(gdf)
    # Concatenate all GeoDataFrames into a single DataFrame
    #combined_gdf = pd.concat(gdf, ignore_index=True)
    
    return gdf

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
            "geometry": mapping(row["geometry"])  # Convert geometry to GeoJSON format
        }
        features.append(feature)
    
    return features

def attribute_with_cmonster_data(polygon_list,raster_path):
	"""
	Attribute polygons with cMonster data using a local raster (virtual raster).
	"""
	with multiprocessing.Pool(processes=20) as pool:
		results = pool.starmap(process_polygon, [(polygon, raster_path) for polygon in polygon_list])
	out = [x for x in results if x is not None]
	combined_df = geojsons_to_dataframe(out)
	balanced_df = balance_dataset(combined_df, category_col='mode_value', sample_size=200)
	geojson_features = dataframe_to_geojson_features(balanced_df)

	return geojson_features



def export_feature_collection(fc,asset_id,asset_path):
	# Create the export task
	fc_task = ee.batch.Export.table.toAsset(
		collection=fc,
		description=asset_id,
		assetId=asset_path + asset_id
	)
	fc_task.start()
	return fc_task


#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------


#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
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

# Run the check before classification
def _mutate_predictor_variables_list(__predictor_variables):
	__predictor_variables = __predictor_variables.filter(ee.Filter.neq('item', 'system:index')) 
	return __predictor_variables

def train_classifier(_labeled_fc,_label_property,_predictor_variables,_num_trees):
	"""
	Train a Random Forest classifier using the labeled data.
	"""
	_predictor_variables = _mutate_predictor_variables_list(_predictor_variables)

	classifier = ee.Classifier.smileRandomForest(_num_trees).train(
		features=_labeled_fc,
		classProperty=_label_property,
		inputProperties=_predictor_variables
	)
	return classifier


def classify_features(_unlabeled_fc,_classifier):
	"""
	Classify the unlabeled feature collection.

	:param classifier: The trained classifier to use for classifying features
	:return: The classified feature collection
	"""

	def cast_fire(f):
		#count = f.get('count').getInfo()		
		count = ee.Number(f.get('count'))
		# Use ee.Algorithms.If to perform conditional logic
		_result = ee.Algorithms.If(
			count.gt(4000),    # Condition to check
			f.set({"classification":40}),            # Expression if condition is true
			f      # Expression if condition is false
		)
		return _result

	classified = _unlabeled_fc.classify(_classifier)
	return classified.map(cast_fire)



def print_classified_features(self, classified_fc, limit=5):
	"""
	Print the first few classified features.

	:param classified_fc: The classified feature collection
	:param limit: Number of features to display (default: 5)
	"""
	print('Classified Features:', classified_fc.limit(limit).getInfo())



#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------


#### Function to convert GeoJSON features to EE Features
def geojson_to_ee_feature(geojson,s_crs,t_crs):
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

def process_feature(index, f_list, src_epsg, target_epsg):
	# Convert the feature from GEE to a Python dict
	feature = ee.Feature(f_list.get(index)).getInfo()  # Get feature and convert to Python dict

	# Use the reprojector to reproject the feature using the provided EPSG codes
	feature = reproject_geojson(feature, src_epsg, target_epsg)

	return {
		"type": "Feature",
		"geometry": feature['geometry'],
		"properties": feature['properties']
		}


def feature_collection_to_geojson(fc, src_epsg, target_epsg):
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



# Function to monitor the status of multiple tasks and update in place
def monitor_tasks(tasks):
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



def rasterize_polygons(feature_collection, property_name, scale, region):
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

def filter_by_mode_value(feature_collection, low, lowmed, medhigh, high):
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


def buffer_features(feature_collection, buffer_distance):
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


def list_and_delete_assets(asset_path):
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
	

def export_image_to_asset(image, asset_id, description,scale, region, max_pixels=1e13):
	"""
	Export an image to an Earth Engine asset.

	Parameters:
	image (ee.Image): The image to export.
	asset_id (str): The destination asset path in Earth Engine (e.g., 'users/your_username/asset_name').
	scale (int): The resolution of the export in meters (e.g., 30 for Landsat resolution).
	region (ee.Geometry): The region to export.
	description (str): The description for the export task.
	max_pixels (int): Maximum number of pixels allowed in the export.
	"""
	task = ee.batch.Export.image.toAsset(
		image=image,
		description=description,
		assetId=asset_id+description,
		region=region.geometry(),
		scale=scale,
		maxPixels=max_pixels
	)
	task.start()
	print(f"Exporting image to {asset_id} with task ID: {task.id}")



#------------------------------------------------------------------------------------------
#------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------
# generate training datasets --------------------------------------------------
def generate_training_reference_imagery_and_polygons(lt,image_processor,polygon_generator):
	# Export the image to GEE assets
	task1 = image_processor.export_image()
	# Generate and export disturbance polygons
	task2 = polygon_generator.export_polygons()
	return [task1,task2]
#---------------------------------------------------------------
def generate_current_imagery_and_polygons(lt,image_processor,polygon_generator):
	# Export the image to GEE assets
	task3 = image_processor.export_image()
	# Generate and export disturbance polygons
	task4 = polygon_generator.export_polygons()
	return [task3,task4]
#---------------------------------------------------------------
def attribute_training_disturbance_polygons(poly_attr,change_params,asset_path):
	# attribute polygons one (early) with referance data
	event_polygons_attri = poly_attr.attribute_with_reference_data()              # apply attribution
	# reporject polgyons one 4326 to 5070
	reprojector = bnet.PolygonReprojector()           
	# Convert FeatureCollection to GeoJSON with reprojection
	src_epsg = "EPSG:4326"                                                                                                # define projection
	target_epsg = "EPSG:5070"                                                                                             # define projection
	# Convert FeatureCollection to GeoJSON with reprojection
	reprojected_geojson = bnet.feature_collection_to_geojson(event_polygons_attri, reprojector, src_epsg, target_epsg)    # apply reprojections and feature collection to geojson tranfermation
	# attribute polygon one with disturbance labels (Cmonster)
	event_polygons_attri1 = poly_attr.attribute_with_cmonster_data(reprojected_geojson)                   # apply attribution (cMonster)
	reprojected_geojson = bnet.geojson_to_ee_feature(event_polygons_attri1, reprojector, target_epsg, src_epsg)           # apply re-reprojection and geojson to feature collection transfermation
	fc2_asset_id = "disturbance_attributed_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
	export_result = poly_attr.export_attributed_polygons(reprojected_geojson, asset_path, fc2_asset_id)   # save date in GEE
	return 0 
#-------------------------------------------------------------------
def attribute_current_disturbance_polygons(poly_attr,change_params,asset_path,composite_params):
	img_asset_id = "predictor_img_"+str(composite_params['start_date'].year)+'_'+str(composite_params['end_date'].year)
	raster_stack = ee.Image(asset_path + img_asset_id)
	fc1_asset_id = "disturbance_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
	disturbance_polygons_asset2 = ee.FeatureCollection(asset_path+fc1_asset_id)
	event_polygons_attri = poly_attr.attribute_with_reference_data()
	fc2_asset_id = "disturbance_attributed_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
	poly_attr.export_attributed_polygons(event_polygons_attri, asset_path, fc2_asset_id)
	return 0 
#-------------------------------------------------------------------
def predict(params_handler,change_params,label_property,asset_path):

	params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2008, 'end': 2012}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
	labeled = "disturbance_attributed_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
	params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2019, 'end': 2024}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
	unlabeled = "disturbance_attributed_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
	# Instantiate the classifier
	classifier = bnet.FeatureClassifier(asset_path+labeled, asset_path+unlabeled, label_property)
	# Train the classifier
	trained_classifier = classifier.train_classifier()
	# Classify the features
	classified_fc = classifier.classify_features(trained_classifier)
	# Print the first few classified features
	classifier.print_classified_features(classified_fc)
	# Export the classified FeatureCollection to Google Drive
	classifier.export_classified(classified_fc,asset_path)
	return 0

