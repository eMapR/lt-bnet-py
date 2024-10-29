#import bnet_mod as bnet
from ltgee import LandTrendr, LandsatComposite, LtCollection
from datetime import date
import json
import os
import rasterio
import geopandas as gpd
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
#-------------------------------------------------------------------
# Initialize the Earth Engine module

ee.Initialize(project="r6-bugnet")


class ParameterHandler:
    def __init__(self,ROI):
        self.ROI = ROI
        self.composite_params = self._initialize_composite_params()
        self.lt_collection_params = self._initialize_lt_collection_params()
        self.lt_params = self._initialize_lt_params()
        self.change_params = self._initialize_change_params()

    def _initialize_composite_params(self):
        """Initialize composite parameters."""
        return {
            "start_date": date(2000, 6, 1),
            "end_date": date(2023, 9, 1),
            "area_of_interest": self.ROI.geometry(),
            "mask_labels": ['cloud', 'shadow', 'snow', 'water'],
            "debug": True
        }

    def _initialize_lt_collection_params(self):
        """Initialize LandTrendr collection parameters."""
        # Assuming `LandsatComposite` is an object that you’ve defined elsewhere
        return {
            "sr_collection": LandsatComposite(**self.composite_params),
            "index": 'NBR',
            "ftv_list": ['TCB', 'TCG', 'TCW', 'NBR'],
        }

    def _initialize_lt_params(self):
        """Initialize LandTrendr parameters."""
        # Assuming `LtCollection` is another object that you’ve defined elsewhere
        return {
            "lt_collection": LtCollection(**self.lt_collection_params),
            "run_params": {
                "maxSegments": 6,
                "spikeThreshold": 0.9,
                "vertexCountOvershoot": 3,
                "preventOneYearRecovery": True,
                "recoveryThreshold": 0.25,
                "pvalThreshold": 0.05,
                "bestModelProportion": 0.75,
                "minObservationsNeeded": 6,
            }
        }

    def _initialize_change_params(self):
        """Initialize change detection parameters."""
        return {
            'delta': 'loss',
            'sort': 'greatest',
            'years': {'start': 2010, 'end': 2012},
            'mag': {'value': 200, 'operator': '>'},
            'dur': {'value': 4, 'operator': '<'},
            'preval': {'value': 300, 'operator': '>'},
            'mmu': {'value': 15}
        }

    def get_composite_params(self):
        return self.composite_params

    def get_lt_collection_params(self):
        return self.lt_collection_params

    def get_lt_params(self):
        return self.lt_params

    def get_change_params(self):
        return self.change_params

    def update_composite_params(self, **kwargs):
        """Update composite parameters dynamically."""
        self.composite_params.update(kwargs)

    def update_lt_collection_params(self, **kwargs):
        """Update LandTrendr collection parameters dynamically."""
        self.lt_collection_params.update(kwargs)

    def update_lt_params(self, **kwargs):
        """Update LandTrendr parameters dynamically."""
        self.lt_params['run_params'].update(kwargs)

    def update_change_params(self, **kwargs):
        """Update change detection parameters dynamically."""
        self.change_params.update(kwargs)

    # Example setter for one specific field (optional)
    def set_lt_start_year(self, year):
        """Update the LandTrendr start year."""
        self.lt_start_year = year
        # Reinitialize dependent parameters
        self.composite_params = self._initialize_composite_params()
        self.lt_collection_params = self._initialize_lt_collection_params()
        self.lt_params = self._initialize_lt_params()



###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################

class ImageProcessor:
    def __init__(self, lt, composite_params, start_year, end_year, change_params, ROI, asset_path,prefix):
        self.lt = lt  # LandTrendr object
        self.composite_params = composite_params
        self.start_year = start_year
        self.end_year = end_year
        self.change_params = change_params
        self.ROI = ROI
        self.asset_path = asset_path
        self.prefix = prefix
        self.selection = 12
        if self.prefix == 'training':
            self.asset_id = prefix + "_img_"+str(change_params['years']['start'])+"_"+str(change_params['years']['end'])
        else:
            self.asset_id = prefix + "_img_"+str(change_params['years']['start'])+"_"+str(change_params['years']['end'])
        self.exists = 0
        self.stack_img = ee.Image([0])
 
        try:
            ee.data.getAsset(self.asset_path+self.asset_id)
            self.exists = 1
            print("Asset Exists: "+self.asset_id)
        except ee.ee_exception.EEException:
            self.exists = 0
            print("Asset Does not Exist: "+self.asset_id+" Creating")

        if self.exists == 0:
            self.change_img = self._change_stack()
            #self.delta_img = 
            self.fitted_img = self._fitted_stack()
            self.stack_img = self.fitted_img.addBands(self.change_img)

    def _rename_bands_by_year(self, image, index):
        """Rename bands in the image by year."""
        num_years = self.end_year - self.start_year+1
        new_band_names = [
            f"{index}_ftv_{self.start_year + i}" for i in range(num_years)
        ]
        if len(image.bandNames().getInfo()) == len(new_band_names):
            return image.rename(new_band_names)
        else:
            print("error in: rename_bands_by_year-different number of band names")
            return 0

    def _calculate_deltas(self, image, indice):
        """Calculate delta values (differences between consecutive years) for the given index."""
        num_years = self.end_year - self.start_year + 1
        band_names = [f"{indice}_ftv_{self.start_year + i}" for i in range(num_years)]

        delta_images = []
        for i in range(num_years - 1):
            band_current = image.select(band_names[i])
            band_next = image.select(band_names[i + 1])
            delta = band_current.subtract(band_next)
            delta_band_name = f"{indice}_delta_{self.start_year + i}_{self.start_year + i + 1}"
            delta_images.append(delta.rename(delta_band_name))

        return ee.Image.cat(delta_images)

    def extract_fitted_data(self, index):
        """Extract fitted data for a given index (e.g., NBR, TCB, TCG, TCW)."""
        if self.exists:
            return 0
        else:
            fitted_data = self.lt.get_fitted_data(
                index, start_date=self.composite_params["start_date"], end_date=self.composite_params["end_date"]
            )
            return self._rename_bands_by_year(fitted_data, index)

    def _change_stack(self):
        """Calculate disturbance/change map using LandTrendr."""
        if self.exists:
            return 0
        else:
            return self.lt.get_change_map(self.change_params).unmask()

    def _fitted_stack(self):
        """Merge all predictor data into one image stack."""
        if self.exists:
            return 0

        else:
            if self.prefix == "training":
                # Extract fitted data for each index
                band_count = ((self.end_year+1) - self.start_year)
                last_bands = ee.List.sequence(band_count - self.selection, band_count - 1)
                # Extract fitted data for each index 8 9 10 11 12
                nbr = self.extract_fitted_data("nbr").select([2,3,4,5,6,7,8,9,10,11,12])
                tcb = self.extract_fitted_data("tcb").select([2,3,4,5,6,7,8,9,10,11,12])
                tcg = self.extract_fitted_data("tcg").select([2,3,4,5,6,7,8,9,10,11,12])
                tcw = self.extract_fitted_data("tcw").select([2,3,4,5,6,7,8,9,10,11,12])

                # Merge all predictor data into a final stack
                stack = nbr.addBands(tcb).addBands(tcg).addBands(tcw)
        
                return stack
            else:    
                # Extract fitted data for each index
                band_count = ((self.end_year+1) - self.start_year)
                last_bands = ee.List.sequence(band_count - self.selection, band_count - 1)
                # Extract fitted data for each index
                nbr = self.extract_fitted_data("nbr").select(last_bands)
                tcb = self.extract_fitted_data("tcb").select(last_bands)
                tcg = self.extract_fitted_data("tcg").select(last_bands)
                tcw = self.extract_fitted_data("tcw").select(last_bands)
    
                # Merge all predictor data into a final stack
                stack = nbr.addBands(tcb).addBands(tcg).addBands(tcw)
        
                return stack

    def delta_stack(self):
        """Merge all predictor data into one image stack."""
        if self.exists:
            return 0
        else:  
            # Calculate deltas
            delta_nbr = self.calculate_deltas(nbr, "nbr")
            delta_tcb = self.calculate_deltas(tcb, "tcb")
            delta_tcg = self.calculate_deltas(tcg, "tcg")
            delta_tcw = self.calculate_deltas(tcw, "tcw")

            # Merge all predictor data into a final stack
            stack = (
                delta_nbr.addBands(delta_tcb)
                .addBands(delta_tcg)
                .addBands(delta_tcw)
            )

            return stack

    def export_image(self, scale=30, max_pixels=1e13):
        """Export the image to Google Earth Engine Assets."""
        if self.exists:
            return 0
        else:  
            # Define export parameters
            img_task = ee.batch.Export.image.toAsset(
                image=self.stack_img.clip(self.ROI),
                description=self.asset_id,  # Task name
                assetId=self.asset_path + self.asset_id,  # Path in your GEE assets
                region=self.ROI.geometry(),  # The area to export
                scale=scale,  # Resolution in meters per pixel
                maxPixels=max_pixels  # Maximum number of pixels allowed to export
            )
            img_task.start() 
            return img_task 


###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################

class PolygonGenerator:
    def __init__(self, lt, composite_params, change_params,asset_path,prefix):
        self.lt = lt  # LandTrendr object
        self.composite_params = composite_params
        self.change_params = change_params
        self.asset_path = asset_path
        self.prefix = prefix
        self.asset_id = prefix + "_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
        self.exists = 0
        try:
            ee.data.getAsset(self.asset_path+self.asset_id)
            self.exists = 1
            print("Asset Exists: "+self.asset_id)
        except ee.ee_exception.EEException:
            self.exists = 0
            print("Asset Does not Exist: "+self.asset_id+" Creating")

    def _find_disturbances(self):
        """Find disturbances based on the change map."""
        change_image = self.lt.get_change_map(self.change_params)
        return change_image

    def _vectorize_disturbance(self, change_image):
        disturbance_polygons = change_image.select('yod').reduceToVectors(
            reducer=ee.Reducer.countEvery(),
            geometry=self.composite_params['area_of_interest'],
            scale=30,
            geometryType="polygon",
            labelProperty='yod',
            maxPixels=1e13,
            tileScale=8
        )
        return disturbance_polygons

    def export_polygons(self):
        if self.exists:
            return 0
        else:
            """Find disturbances, vectorize them, and export the polygons."""
            # Step 1: Find disturbances
            change_image = self._find_disturbances()

            # Step 2: Vectorize the disturbance image
            disturbance_polygons = self._vectorize_disturbance(change_image)

            """Export the disturbance polygons as a FeatureCollection to Google Earth Engine assets."""
            fc_task = ee.batch.Export.table.toAsset(
                collection=disturbance_polygons,
                description=self.asset_id,  # Description for the task
                assetId=self.asset_path + self.asset_id  # The destination asset path
            )

            fc_task.start()
            return fc_task


###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################


class PolygonAttributor:
    def __init__(self,composite_params,change_params,asset_path,prefix, img_type):
        self.composite_params = composite_params
        self.change_params = change_params
        self.asset_path = asset_path
        self.prefix = prefix
        self.img_type = img_type
        self.in_img = ee.Image(self.asset_path + self.img_type + "_img_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])) # HARDCODE -6
        self.in_fc = ee.FeatureCollection(self.asset_path+"disturbance_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end']))
        self.asset_id = prefix + "_polygons_"+str(change_params['years']['start'])+'_'+str(change_params['years']['end'])
        self.cmonster = "/vol/v1/aggregated_attributions.tif" 
        self.exists = 0
        try:
            ee.data.getAsset(self.asset_path+self.asset_id)
            self.exists = 1
            print("Asset Exists: "+self.asset_id)
        except ee.ee_exception.EEException:
            self.exists = 0
            print("Asset Does not Exist: "+self.asset_id+" Creating")

    def attribute_with_reference_data(self):
        """
        Attribute the polygons with reference data from the raster stack.
        """
        #if self.exists:
        #        return
        def process_polygon(polygon):
            yod = ee.Number(polygon.get('yod'))
            years = ee.List.sequence(yod.subtract(5), yod)
            yrs_int = ee.List.sequence(1,6)
            indices = ee.List(['nbr_ftv', 'tcb_ftv', 'tcg_ftv', 'tcw_ftv'])

            def make_band_names(year):
                year = ee.Number(year).format('%d')
                return indices.map(lambda index: ee.String(index).cat('_').cat(year))

            selected_bands = years.map(make_band_names).flatten()
            selected_bands_int = yrs_int.map(make_band_names).flatten()
            special_bands = ee.List(['mag', 'dur', 'preval', 'rate', 'dsnr'])

            selected_bands = selected_bands.cat(special_bands)
            selected_bands_int = selected_bands_int.cat(special_bands)

            raster_filtered = self.in_img.select(selected_bands,selected_bands_int)

            raster_values = raster_filtered.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=polygon.geometry(),
                scale=30,
                maxPixels=1e13
            )
            area = polygon.geometry().area().divide(1000 * 1000)
    
            perimeter = polygon.geometry().perimeter().divide(1000)
    
            return polygon.set(raster_values).set({'area_km2': area,'perimeter_km': perimeter})

        if self.img_type == "training":
            return self.in_fc.filter(ee.Filter.gt('count',75)).map(process_polygon)
        else:       
            return self.in_fc.map(process_polygon)

    def attribute_with_cmonster_data(self, polygon_list):
        """
        Attribute polygons with cMonster data using a local raster (virtual raster).
        """
        def parallel_processing(polygon_list, raster_path):
            with multiprocessing.Pool(processes=30) as pool:
                results = pool.starmap(process_polygon, [(polygon, raster_path) for polygon in polygon_list])
            return [x for x in results if x is not None]

        return parallel_processing(polygon_list, self.cmonster)

    def export_attributed_polygons(self, attributed_polygons, asset_path, asset_id):
        """
        Export the attributed polygons to GEE assets.
        """
        # Create the export task
        fc_task = ee.batch.Export.table.toAsset(
            collection=ee.FeatureCollection(attributed_polygons),
            description=asset_id,
            assetId=asset_path + asset_id
        )

        try:
            ee.data.getAsset(asset_path + asset_id)
            print("Exists: " + asset_path + asset_id)
            return 0
        except ee.ee_exception.EEException:
            if fc_task.status()['state'] in ['READY', 'RUNNING']:
                return fc_task 
            else:
                fc_task.start()
                return fc_task




###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################

class PolygonReprojector:
    def reproject_geojson(self, ft_geojson, src_epsg, target_epsg):
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



###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################

class FeatureClassifier:
    def __init__(self, labeled_fc_path, unlabeled_fc_path, label_property, num_trees=200):
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

    def drop_null_features(self,fc, property_name):
        """
        Drops features from a Feature Collection if they contain null values for a specific property.

        Parameters:
        - fc: ee.FeatureCollection, the feature collection to filter.
        - property_name: str, the name of the property to check for null values.

        Returns:
        - ee.FeatureCollection, the filtered feature collection.
        """
        # Filter out features that have null values for the specified property
        filtered_fc = fc.filter(ee.Filter.notNull([property_name]))
        return filtered_fc

    # Run the check before classification
    def _mutate_predictor_variables_list(self):
        print(self.predictor_variables)
        self.predictor_variables = self.predictor_variables.filter(ee.Filter.neq('item', 'system:index')) 
        return 0

    def train_classifier(self):
        """
        Train a Random Forest classifier using the labeled data.
        """
        self._mutate_predictor_variables_list()

        classifier = ee.Classifier.smileRandomForest(self.num_trees).train(
            features=self.labeled_fc,
            classProperty=self.label_property,
            inputProperties=self.predictor_variables
        )
        return classifier

    def classify_features(self, classifier):
        """
        Classify the unlabeled feature collection.

        :param classifier: The trained classifier to use for classifying features
        :return: The classified feature collection
        """
        classified = self.unlabeled_fc.classify(classifier)
        return classified

    def export_classified(self, classified_fc, asset_path, asset_id='classified_polgyons'):
        """
        Export the classified feature collection to Google Drive.

        :param classified_fc: The classified feature collection to export
        :param description: The description for the export task
        """
        # Create the export task
        fc_task = ee.batch.Export.table.toAsset(
            collection=classified_fc,
            description=asset_id,
            assetId=asset_path + asset_id
        )
        try:
            ee.data.getAsset(asset_path + asset_id)
            return 0
        except ee.ee_exception.EEException:
            if fc_task.status()['state'] in ['READY', 'RUNNING']:
                return fc_task
            else:
                fc_task.start()
                return fc_task



    def print_classified_features(self, classified_fc, limit=5):
        """
        Print the first few classified features.

        :param classified_fc: The classified feature collection
        :param limit: Number of features to display (default: 5)
        """
        print('Classified Features:', classified_fc.limit(limit).getInfo())



###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################
###################################################################################################################



#### Function to convert GeoJSON features to EE Features
def geojson_to_ee_feature(geojson,reprojector,s_crs,t_crs):
    features = []
    for feature in geojson:
        feature = reprojector.reproject_geojson(feature, s_crs, t_crs)
        geometry = feature['geometry']
        properties = feature['properties']

        # Create an Earth Engine feature from GeoJSON geometry and properties
        ee_feature = ee.Feature(ee.Geometry(geometry), properties)
        features.append(ee_feature)

    # Return a FeatureCollection from the list of EE Features
    return ee.FeatureCollection(features)


def process_feature(index, f_list, reprojector, src_epsg, target_epsg):
    # Convert the feature from GEE to a Python dict
    feature = ee.Feature(f_list.get(index)).getInfo()  # Get feature and convert to Python dict
    
    # Use the reprojector to reproject the feature using the provided EPSG codes
    feature = reprojector.reproject_geojson(feature, src_epsg, target_epsg)
    
    return {
        "type": "Feature",
        "geometry": feature['geometry'],
        "properties": feature['properties']
    }

def feature_collection_to_geojson(fc, reprojector, src_epsg, target_epsg):
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
    #print([(i, f_list, reprojector, src_epsg, target_epsg) for i in range(num_features)])

    # Create a pool of worker processes
    with multiprocessing.Pool(processes=30) as pool:
        # Map the process_feature function to each feature index in parallel
        results = pool.starmap(process_feature, [(i, f_list, reprojector, src_epsg, target_epsg) for i in range(num_features)])

    # Collect valid features (filter out None values)
   # geojson['features'] = [res for res in results if res is not None]
    geojson = [res for res in results if res is not None]

    return geojson

# Move the `process_polygon` function to the global scope for multiprocessing compatibility
def process_polygon(polygon, raster_path):
    """
    Process each polygon by extracting cMonster data.
    """
    def calculate_occurrences_proportion(values):
        total_count = len(values)
        occurrences = Counter(values)
        proportions = {key: value / total_count for key, value in occurrences.items()}
        return proportions

    def create_virtual_raster(polygon, raster_path, yod_band):
        with rasterio.open(raster_path) as src:
            band_index = yod_band - 1984 + 1  # Adjust for 1-based indexing
            geom = [shape(polygon['geometry'])]
            out_image, out_transform = mask(src, geom, crop=True, indexes=int(band_index))
            return out_image

    def calculate_mode(virtual_raster):
        flat_pixels = virtual_raster.flatten()
        flat_pixels = flat_pixels[flat_pixels != 0]  # Filter out no-data values if needed
        #print(flat_pixels)
        if len(flat_pixels) == 0:
            return -9999
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


def export_featurecollection_to_asset(feature_collection, asset_id, description):
    """
    Export a FeatureCollection to an Earth Engine asset.

    Parameters:
    feature_collection (ee.FeatureCollection): The FeatureCollection to export.
    asset_id (str): The destination asset path in Earth Engine (e.g., 'users/your_username/asset_name').
    description (str): The description for the export task.
    """
    task = ee.batch.Export.table.toAsset(
        collection=feature_collection,
        description=description,
        assetId=asset_id+description
    )
    task.start()
    print(f"Exporting FeatureCollection to {asset_id} with task ID: {task.id}")

