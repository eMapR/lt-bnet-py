# import 
import mod as bnet
import main
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
ee.Initialize(project="r6-bugnet")
#-------------------------------------------------------------------
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
    print(1)
    # reporject polgyons one 4326 to 5070
    reprojector = bnet.PolygonReprojector()           
    # Convert FeatureCollection to GeoJSON with reprojection
    src_epsg = "EPSG:4326"                                                                                                # define projection
    target_epsg = "EPSG:5070"                                                                                             # define projection
    # Convert FeatureCollection to GeoJSON with reprojection
    reprojected_geojson = bnet.feature_collection_to_geojson(event_polygons_attri, reprojector, src_epsg, target_epsg)    # apply reprojections and feature collection to geojson tranfermation
    print(2)
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




