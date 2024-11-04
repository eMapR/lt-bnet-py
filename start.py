# import 
#import mod as bnet
import run
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
import time

#-------------------------------------------------------------------
import params.north_cascades_config_opt3_2023 as access
ee.Initialize(project="r6-bugnet")
#-------------------------------------------------------------------
#ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/bugnet_North_Cascades")
#asset_path = "projects/r6-bugnet/assets/north_cascades/"
#ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/NorthCascades_ROI")
#asset_path = "projects/r6-bugnet/assets/north_cascades/"
mode = 'attribute'
#-------------------------------------------------------------------
# Parameter Setup---------------------------------------------------
#---------------------------------------------------------------
if mode == 'generate' or mode == 'all':
    lt = LandTrendr(**access.param['lt_params'])

    fitted_img_t = run.get_fitted_stack(lt,'fitted_training',access.param)
    run.export_image(fitted_img_t,access.param, access.param['fitted_img_t'])

    fitted_img_p = run.get_fitted_stack(lt,'fitted_predictor',access.param)
    run.export_image(fitted_img_p,access.param, access.param['fitted_img_p'])

    access.param['change_params']['years'] = {'start': 2007, 'end': 2012}
    change_img_t = lt.get_change_map(access.param['change_params'])
    run.export_image(change_img_t, access.param, access.param['training_change_img'])

    access.param['change_params']['years'] = {'start': access.param['composite_params']['end_date'].year-6, 'end': access.param['composite_params']['end_date'].year}
    change_img_p = lt.get_change_map(access.param['change_params'])
    run.export_image(change_img_p,access.param, access.param['predictor_change_img'])

    disturbance_polygons_t = run.vectorize_disturbance(change_img_t,access.param)
    run.export_polygons(disturbance_polygons_t,access.param,access.param['disturbance_polygons_training'])

    disturbance_polygons_p = run.vectorize_disturbance(change_img_p,access.param)
    run.export_polygons(disturbance_polygons_p,access.param,access.param['disturbance_polygons_predictor'])

#---------------------------------------------------------------
#---------------------------------------------------------------
if mode == 'attribute' or mode == 'all':

    # Start the timer
    start_time = time.time()
    # attribute with gee methods
    this_time = time.time()
    gee_attributed_fc = run.attribute_with_reference_data(access.param,'training')
    print("attributed with reference data "+str((this_time-start_time)/60)) 

    # reproject and change feature collecton to json
    this_time = time.time()
    reprojected_geojson = run.feature_collection_to_geojson(gee_attributed_fc, access.param['source_epsg'], access.param['target_epsg'])    # apply reprojections and feature collection to geojson t>
    print("feature collection to geojson and reproject "+str((this_time-start_time)/60)) 
    #print(reprojected_geojson) # <<<<<<   look in to fc_list in run.py passing a whole list of features could we just pass a single feature?

    # attribute with Cmonster
    this_time = time.time()
    event_polygons_attri1 = run.attribute_with_cmonster_data(reprojected_geojson,access.param['cMonster_img_path'])                   # apply attribution (cMonster)
    print("attribute geojson with cmonster data "+str((this_time-start_time)/60)) 

    # reproject and convert to featrue collection
    this_time = time.time()
    reprojected_geojson = run.geojson_to_ee_feature(event_polygons_attri1, access.param['target_epsg'], access.param['source_epsg'])           # apply re-reprojection and geojson to feature collection>
    print("geojson to gee feature collection and reproject "+str((this_time-start_time)/60)) 

    # export
    this_time = time.time()
    run.export_fearture_collection(reprojected_geojson,access.param['attributed_polygons_training'],access.param['assetDir'] )
    print("export "+str((this_time-start_time)/60)) 
    #-------------------------------------------------------------------
    # attribute polygons two with refeance data
    # attribute with gee methods
    print("attribute_with_reference_data (predictor)") 
    gee_attributed_fc = run.attribute_with_reference_data(access.param,'predictor')
    # exportt 
    print("export") 
    run.export_fearture_collection(gee_attributed_fc,access.param['attributed_polygons_predictor'],access.param['assetDir'] )
    

#---------------------------------------------------------------
#-------------------------------------------------------------------
if mode == 'predict' or mode == 'all':
    label_property = 'mode_value'
    main.predict(params_handler,change_params,label_property,asset_path)
#---------------------------------------------------------------
#-------------------------------------------------------------------
if mode == 'post' or mode == 'all':
    fc1 = bnet.filter_by_mode_value(ee.FeatureCollection(asset_path + 'classified_polgyons_'+str(composite_params['end_date'].year)), 19, 41, 60, 90)
    fc2 = bnet.buffer_features(fc1, 100)
    #img = bnet.rasterize_polygons(fc2, 'classification', 30, region=ROI)
    img = bnet.rasterize_polygons(ee.FeatureCollection('projects/r6-bugnet/assets/north_cascades/classed_buffer_2024'), 'classification', 30, region=ROI)
    bnet.export_featurecollection_to_asset(fc1, asset_path,'classed_filtered_'+str(composite_params['end_date'].year))
    bnet.export_featurecollection_to_asset(fc2, asset_path,'classed_buffer_'+str(composite_params['end_date'].year))
    bnet.export_image_to_asset(img, asset_path,"classed_img_"+str(composite_params['end_date'].year), 30, ROI)
#---------------------------------------------------------------
#-------------------------------------------------------------------
if mode == 'remove':
    bnet.list_and_delete_assets(asset_path)

