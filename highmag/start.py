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
#ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/bugnet_North_Cascades")
#asset_path = "projects/r6-bugnet/assets/north_cascades/"
ROI = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/NorthCascades_ROI")
asset_path = "projects/r6-bugnet/assets/north_cascades/"
mode = 'remove'
#-------------------------------------------------------------------
# Parameter Setup---------------------------------------------------
# Instantiate the ParameterHandler class
params_handler = bnet.ParameterHandler(ROI=ROI)
# Update composite parameters
#params_handler.update_composite_params(start_date=date(2000, 6, 1), end_date=date(2024, 9, 1), area_of_interest=ROI.geometry(), mask_labels=['cloud', 'shadow', 'snow', 'water'], debug=True)
#params_handler.update_composite_params(start_date=date(2000, 6, 1), end_date=date(2024, 9, 1), mask_labels=['cloud', 'shadow', 'snow', 'water'], debug=True)
# Update lt collection parameters
#params_handler.update_lt_collection_params(index='NBR',ftv_list=['TCB', 'TCG', 'TCW', 'NBR'],)
# Update LandTrendr parameters
#params_handler.update_lt_params(maxSegments=6, spikeThreshold=0.9, vertexCountOvershoot=3, preventOneYearRecovery=True, recoveryThreshold=0.25, pvalThreshold=0.05, bestModelProportion=0.75, minObservationsNeeded=6,)
# Update change detection parameters
#params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2008, 'end': 2012}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
# Access parameters
composite_params = params_handler.get_composite_params()
lt_collection_params = params_handler.get_lt_collection_params()
lt_params = params_handler.get_lt_params()
change_params = params_handler.get_change_params()
#---------------------------------------------------------------
if mode == 'generate' or mode == 'all':
    # generate training datasets
    lt = LandTrendr(**lt_params)
    #---------------------------------------------------------------
    params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2008, 'end': 2012}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
    image_processor = bnet.ImageProcessor(lt, composite_params, start_year=composite_params['start_date'].year, end_year=composite_params['end_date'].year, change_params=change_params, ROI=ROI, asset_path=asset_path,prefix="training")
    polygon_generator = bnet.PolygonGenerator(lt, composite_params, change_params,asset_path,"disturbance")
    tasks1and2 = main.generate_training_reference_imagery_and_polygons(lt,image_processor,polygon_generator)
    #---------------------------------------------------------------
    # Update change detection parameters
    params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2019, 'end': 2024}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
    image_processor = bnet.ImageProcessor(lt, composite_params, start_year=composite_params['start_date'].year, end_year=composite_params['end_date'].year, change_params=change_params, ROI=ROI, asset_path=asset_path,prefix="predictor")
    polygon_generator = bnet.PolygonGenerator(lt, composite_params, change_params,asset_path,"disturbance")
    tasks3and4 = main.generate_current_imagery_and_polygons(lt,image_processor,polygon_generator)
    #---------------------------------------------------------------
    tasks = [item for sublist in [tasks1and2,tasks3and4] for item in sublist]
    #---------------------------------------------------------------
    bnet.monitor_tasks(tasks)
#---------------------------------------------------------------
#---------------------------------------------------------------
if mode == 'attribute' or mode == 'all':
    # attribute polygons two with refeance data
    params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2008, 'end': 2012}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
    poly_attr = bnet.PolygonAttributor(composite_params,change_params,asset_path,"disturbance_attributed",'training') 
    main.attribute_training_disturbance_polygons(poly_attr,change_params,asset_path)
    #-------------------------------------------------------------------
    # attribute polygons two with refeance data
    params_handler.update_change_params(delta='loss',sort='greatest', years={'start': 2019, 'end': 2024}, mag={'value': 200, 'operator': '>'}, dur={'value': 4, 'operator': '<'}, preval={'value': 300, 'operator': '>'}, mmu={'value': 15})
    poly_attr = bnet.PolygonAttributor(composite_params,change_params,asset_path,"disturbance_attributed",'predictor') 
    main.attribute_current_disturbance_polygons(poly_attr,change_params,asset_path,composite_params)
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

