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
        centroid = row["geometry"].centroid
        # Convert each row to a GeoJSON feature
        feature = {
            "type": "Feature",
            "properties": row.drop("geometry").to_dict(),  # Exclude geometry from properties
            #"geometry": mapping(row["geometry"])  # Convert geometry to GeoJSON format
            "geometry": {"type": "MultiPolygon","coordinates": [[[(2, 2), (3, 3), (3, 2), (2, 2)]]]}  # Convert geometry to GeoJSON format
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
	# Create the export task
	fc_task = ee.batch.Export.table.toAsset(
		collection=fc,
		description=asset_id,
		assetId=asset_path + asset_id
	)
	fc_task.start()
	return fc_task

def export_feature_collection_hold(fc,asset_id,asset_path):
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
def _mutate_predictor_variables_list(__predictor_variables):
	__predictor_variables = __predictor_variables.filter(ee.Filter.neq('item', 'system:index')) 
	return __predictor_variables

###########################################################################################################################
## 
###########################################################################################################################
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


###########################################################################################################################
## 
###########################################################################################################################
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


###########################################################################################################################
## 
###########################################################################################################################
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

# Function to make start and end dates for composite time stamps --------------------------------------
def annual_window(start, end):
    year_list = ee.List.sequence(start, end, 1)
    first_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(start_date))
    second_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(end_date))
    dates = first_date.zip(second_date)
    return dates

# Filter a collection function
def filter_collection(year, start_day, end_day, aoi):
    return ee.ImageCollection("NASA/HLS/HLSL30/v002") \
        .filterBounds(aoi) \
        .filterDate(f'{year}-{start_day}', f'{year}-{end_day}') \
        .filter(ee.Filter.lt('CLOUD_COVERAGE', 30))

def get_sr_collection(year, start_day, end_day, aoi):
    sr_collection = filter_collection(year, start_day, end_day, aoi)
    return sr_collection

# Function to combine collections
def get_combined_sr_collection(year, start_day, end_day, aoi):
    hls = get_sr_collection(year, start_day, end_day, aoi)
    return hls

def b2_cloud_mask(image_collection):
    def apply_mask(image):
        cloudMask = image.select('B2').lt(0.02)
        return image.mask(cloudMask)
    # Apply the mask to each image in the collection
    masked_collection = image_collection.map(apply_mask)
    return masked_collection

# Make a medoid composite with equal weight among indices
def mean_mosaic(in_collection, dummy_collection):
    image_count = in_collection.toList(1).length()
    final_collection = ee.ImageCollection(ee.Algorithms.If(image_count.gt(0), in_collection, dummy_collection))
    final_collection = b2_cloud_mask(final_collection)
    return final_collection.mean()

# Function to apply medoid compositing function to a collection
def build_mosaic(year, start_day, end_day, aoi, dummy_collection):
    collection = get_combined_sr_collection(year, start_day, end_day, aoi)
    img = mean_mosaic(collection, dummy_collection).set('system:time_start', ee.Date.fromYMD(year, 8, 1).millis())
    return ee.Image(img).multiply(1000).toUint16()

# Function to build annual mosaic collection
def build_sr_collection(start_year, end_year, start_day, end_day, aoi):
    dummy_collection = ee.ImageCollection([ee.Image([0, 0, 0, 0, 0, 0]).mask(ee.Image(0))])
    imgs = []
    for i in range(start_year, end_year + 1):
        tmp = build_mosaic(i, start_day, end_day, aoi, dummy_collection)
        imgs.append(tmp.set('composite_year', i).set('system:time_start', ee.Date.fromYMD(i, 8, 1).millis()))
    return ee.ImageCollection(imgs)

def get_lt_last_seg_info(lt, idx):
    segInfo = lt.get_segment_data('all', index_flip=True)
    endSeg = segInfo.arraySlice(1, -1, None, 1)
    
    def getLastSeg(img):
        arrRowNames = [['startYear', 'endYear', 'preval', 'postval', 'mag', 'dur', 'rate', 'dsnr']]
        endSegImg = img.arrayProject([0]).arrayFlatten(arrRowNames)
        yod = endSegImg.select('endYear').rename('yod')
        return endSegImg.addBands(yod).select(['yod', 'mag', 'dur', 'preval', 'rate', 'dsnr'])
    
    return getLastSeg(endSeg)

def lcms_forest_mask(start, end, param):
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
    year_list = []
    for year in range(start_year, end_year + 1):
        year_list.append(f"{index}_ftv_{year}")
    return year_list




def filter_ads(agent, severity, defol, ads_col, all):
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
    return ee.Algorithms.Image.Segmentation.SNIC(image=img, size=5, compactness=1)


def SNIC_decline_image(im, std_end_year):
    """
    Restored verbatim from commit d379494 (last version before it was
    commented out, pre-dating the refactor-bugnet-cleanup branch). NOT
    currently called anywhere - modeling_utils.declining_snic raises
    NotImplementedError instead of calling this, because it has not been
    validated against the current SNIC pipeline output.

    Known mismatch: expects bands named 'yr_<year>_nbr_mean' /
    '_tcg_mean' / '_tcw_mean' (bnet.rename_img's output convention), but
    the modeling_utils.snic() stage exports the SNIC-segmented image with
    its original (un-renamed) band names. Needs review/adaptation before
    it can be wired back into declining_snic.
    """
    years = {i: str(std_end_year - i) for i in [0, 1, 2, 5, 9]}
    expression = 'nbr_3 > nbr_4 > nbr_5 && tcg_3 > tcg_4 > tcg_5 && tcw_3 > tcw_4 > tcw_5 && rate > 20 && rate < 100 && dur < 6 && dur > 2'
    return im.mask(im.expression(expression, {
        'nbr_1': im.select('yr_' + years[9] + '_nbr_mean'),
        'nbr_2': im.select('yr_' + years[5] + '_nbr_mean'),
        'nbr_3': im.select('yr_' + years[2] + '_nbr_mean'),
        'nbr_4': im.select('yr_' + years[1] + '_nbr_mean'),
        'nbr_5': im.select('yr_' + years[0] + '_nbr_mean'),
        'tcg_1': im.select('yr_' + years[9] + '_tcg_mean'),
        'tcg_2': im.select('yr_' + years[5] + '_tcg_mean'),
        'tcg_3': im.select('yr_' + years[2] + '_tcg_mean'),
        'tcg_4': im.select('yr_' + years[1] + '_tcg_mean'),
        'tcg_5': im.select('yr_' + years[0] + '_tcg_mean'),
        'tcw_1': im.select('yr_' + years[9] + '_tcw_mean'),
        'tcw_2': im.select('yr_' + years[5] + '_tcw_mean'),
        'tcw_3': im.select('yr_' + years[2] + '_tcw_mean'),
        'tcw_4': im.select('yr_' + years[1] + '_tcw_mean'),
        'tcw_5': im.select('yr_' + years[0] + '_tcw_mean'),
        'rate': im.select('rate_mean'),
        'dur': im.select('dur_mean')
    }))


def decline_image(param):
    """
    Parameters:
        im (ee.Image): Input image.
        std_end_year (int): Latest year in the image series.
        indices (list): List of index names like ['nbr', 'tcg', 'tcw'].
        thresholds (dict): Dict of thresholds per index, e.g., {'nbr': (75, 100)}.
        logic_template (str): Logic string using placeholders, e.g., '{nbr} || ({tcg} && {tcw})'.
        num_years (int): How many years back to include (default = 5).
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

def LTSD_decline_score(param, base_thresholds={'tcb': 70, 'tcg': 50, 'tcw': 50}, taper_step=10, min_years_declining=2, return_score=False):
    im = ee.Image(param.get('sharedAssetDir', param['assetDir']) + param['fitted_img_p'])
    std_end_year = param['target']
    base_thresholds = param['decline_thresholds']
    taper_step= param['decline_step']

    # Generate 5 consecutive years: oldest (1) to most recent (5)
    years = {i: str(std_end_year - (5 - i)) for i in range(1, 6)}

    # Select bands (note: you're using TCB for "nbr" equivalent here)
    bands = {
        f'tcb_{i}': im.select(f'TCB_ftv_{years[i]}') for i in range(1, 6)
    } | {
        f'tcg_{i}': im.select(f'TCG_ftv_{years[i]}') for i in range(1, 6)
    } | {
        f'tcw_{i}': im.select(f'TCW_ftv_{years[i]}') for i in range(1, 6)
    }

    # Ca lculate decline per year-pair with tapered thresholds
    diffs = []
    for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
        taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper
 
        t_tcb = base_thresholds['tcb'] - taper
        t_tcg = base_thresholds['tcg'] - taper
        t_tcw = base_thresholds['tcw'] - taper

        diff_tcb = bands[f'tcb_{i}'].subtract(bands[f'tcb_{i+1}']).gt(t_tcb)
        diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i+1}']).gt(t_tcg)
        diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i+1}']).gt(t_tcw)


        #year_decline = diff_tcb.And(diff_tcg).And(diff_tcw)
        year_decline = diff_tcg.And(diff_tcw)
        diffs.append(year_decline)

    # Sum yearly decline flags into a score
    decline_score = diffs[0]
    for d in diffs[1:]:
        decline_score = decline_score.add(d)

    # Output: either just the score band, or mask + band
    if return_score:
        return decline_score.rename('decline_score')
    else:
        return im.updateMask(decline_score.gte(min_years_declining)) \
                 .addBands(decline_score.rename('decline_score'))


def get_training_points(recovery, disturbances, roi, referImage, ads_in_roi):
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
    tcb_years = generate_year_list(ltstartYear, yer,'tcb')
    fitted_tcb = lt.data.select(['ftv_tcb_fit']).arrayFlatten([tcb_years])
    return fitted_tcb


def tasselCapMask(bnet):

    # Run the LandTrendr algorithm
    targetImage = ee.Image(bnet['LTSDdir']+bnet['fitted_img_p'])
    val = [item.upper() for item in bnet['fit'] if item.lower() == "tcb"]
    tcb = targetImage.select([val[0]+"_ftv_" + str(bnet['target'])])
    
    tcb_mask = tcb.expression('band > '+bnet['brightness_value']+' ? 0 : 1', {'band': tcb}) # 2200

    return tcb_mask

def rename_img(img, target_year):
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    
    return img.select(img.bandNames(), [

        'clusters','yr_9_nbr_mean','yr_8_nbr_mean','yr_7_nbr_mean','yr_6_nbr_mean', 'yr_5_nbr_mean','yr_4_nbr_mean', 'yr_3_nbr_mean','yr_2_nbr_mean', 'yr_1_nbr_mean', 'yr_0_nbr_mean',
        'yr_9_tcb_mean','yr_8_tcb_mean','yr_7_tcb_mean','yr_6_tcb_mean', 'yr_5_tcb','yr_4_tcb_mean', 'yr_3_tcb_mean','yr_2_tcb_mean', 'yr_1_tcb_mean', 'yr_0_tcb_mean',
        'yr_9_tcg_mean','yr_8_tcg_mean','yr_7_tcg_mean','yr_6_tcg_mean', 'yr_5_tcg','yr_4_tcg_mean', 'yr_3_tcg_mean','yr_2_tcg_mean', 'yr_1_tcg_mean', 'yr_0_tcg_mean',
        'yr_9_tcw_mean','yr_8_tcw_mean','yr_7_tcw_mean','yr_6_tcw_mean', 'yr_5_tcw','yr_4_tcw_mean', 'yr_3_tcw_mean','yr_2_tcw_mean', 'yr_1_tcw_mean', 'yr_0_tcw_mean','seeds'

    ])

def rename_img_opt3(img, target_year):
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    return img.select(img.bandNames(), [
        'yr_9_nbr','yr_8_nbr','yr_7_nbr','yr_6_nbr', 'yr_5_nbr','yr_4_nbr', 'yr_3_nbr','yr_2_nbr', 'yr_1_nbr', 'yr_0_nbr',
        'yr_9_tcb','yr_8_tcb','yr_7_tcb','yr_6_tcb', 'yr_5_tcb','yr_4_tcb', 'yr_3_tcb','yr_2_tcb', 'yr_1_tcb', 'yr_0_tcb',
        'yr_9_tcg','yr_8_tcg','yr_7_tcg','yr_6_tcg', 'yr_5_tcg','yr_4_tcg', 'yr_3_tcg','yr_2_tcg', 'yr_1_tcg', 'yr_0_tcg',
        'yr_9_tcw','yr_8_tcw','yr_7_tcw','yr_6_tcw', 'yr_5_tcw','yr_4_tcw', 'yr_3_tcw','yr_2_tcw', 'yr_1_tcw', 'yr_0_tcw'
        #"yod", "mag", "dur", "preval", "rate", "dsnr"
    ])

def rename_ltsd_img(img, target_year):
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
    def calculate_proportion(k):
        top = ads_data.getNumber(k) if ads_data.contains(k) else ee.Number(-1)
        bottom = kmeans_data.getNumber(k)
        return top.divide(bottom).multiply(100)

    return kmeans_data.map(calculate_proportion)

def ltcalc(year, feat):
    target = feat.filter(ee.Filter.eq('yod', year))
    target = target.map(lambda fe: fe.set('area', fe.area(1)))
    target = target.map(lambda fe: fe.set('perimeter', fe.perimeter(1)))
    target = target.map(lambda fe: fe.set('rati', fe.getNumber('area').divide(fe.getNumber('perimeter'))))
    return target.filter(ee.Filter.Or(ee.Filter.gt('rati', 20), ee.Filter.gt('area', 9500000)))
