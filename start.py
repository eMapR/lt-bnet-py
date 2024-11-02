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
#-------------------------------------------------------------------
import params.north_cascades_config_opt3_2023 as access
ee.Initialize(project="r6-bugnet")
#-------------------------------------------------------------------
#ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/bugnet_North_Cascades")
#asset_path = "projects/r6-bugnet/assets/north_cascades/"
#ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/NorthCascades_ROI")
#asset_path = "projects/r6-bugnet/assets/north_cascades/"
mode = 'generate'
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

    # attribute polygons two with refeance data
    #params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2008, 'end': 2012}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
    #poly_attr = run.PolygonAttributor(composite_params,change_params,asset_path,"disturbance_attributed",'training') 
    #run.attribute_training_disturbance_polygons(poly_attr,change_params,asset_path)

    # attribute with gee methods
    run.attribute_with_reference_data()
    # reproject and change feature collecton to json
    run.feature_collection_to_geojson()
    # attribute with Cmonster
    run.attribute_with_cmonster_data()
    # reproject and convert to featrue collection
    reprojected_geojson = bnet.geojson_to_ee_feature(event_polygons_attri1, reprojector, target_epsg, src_epsg)           # apply re-reprojection and geojson to feature collection>
    # export 

    #-------------------------------------------------------------------
    # attribute polygons two with refeance data
#    params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2019, 'end': 2024}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
#    poly_attr = bnet.PolygonAttributor(composite_params,change_params,asset_path,"disturbance_attributed",'predictor') 
#    main.attribute_current_disturbance_polygons(poly_attr,change_params,asset_path,composite_params)

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

