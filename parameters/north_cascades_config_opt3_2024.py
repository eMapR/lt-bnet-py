import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection
from datetime import date
import datetime 
import bnet as bnet
import pprint
ee.Initialize(project='r6-bugnet')

param = {}

# Config name
param['configName'] = 'option3'

# AOI
param['aoi'] = ee.FeatureCollection("projects/r6-bugnet/assets/north_cascades/NorthCascades_ROI")

# image type 
param["platform"] = 'lS'

# Time parameters
param['start_date'] = '06-01'
param['end_date'] = '09-01'
param['ltstartYear'] = 2000
param['ltendYear'] = 2024
param['target'] = 2024
param['trainingYear'] = 2023
targetPlus5 = param['target']+5
param['maskStartTime'] = int(datetime.datetime(targetPlus5,1,1).timestamp() * 1000)
param['maskEndTime'] = int(datetime.datetime(param['target'],12,30).timestamp() * 1000)


# Initialize variables for LandTrendr algorithm
param['composite_params'] = {
    "start_date": date(param['ltstartYear'], 6,1),
    "end_date": date(param['ltendYear'], 9,1),
    "area_of_interest": param['aoi'],
    "mask_labels": ['cloud', 'shadow', 'snow', 'water'],
    "debug": True
}

# HIGH MAG STUFF 
param['fitted_img_t'] = f"training_fitted_img_2008_2012"
param['fitted_img_p'] = f"predictor_fitted_img_{param['composite_params']['end_date'].year-5}_{param['composite_params']['end_date'].year}"
param['training_change_img'] = f"training_change_img_2012"
param['predictor_change_img'] = f"predictor_change_img_{param['composite_params']['end_date'].year}"
param['disturbance_polygons_training']= f"training_disturbance_polygons_2012"
param['disturbance_polygons_predictor']= f"predictor_disturbance_polygons_{param['composite_params']['end_date'].year}"

param['attributed_polygons_training']= f"attributed_training_polygons_2012"
param['attributed_polygons_predictor']= f"attributed_predictor_polygons_{param['composite_params']['end_date'].year}"

param['source_epsg'] = 'EPSG:4326'
param['target_epsg'] = 'EPSG:5070'

param['cMonster_img_path']= "/vol/v1/lt-bnet-py/assets/aggregated_attributions.tif" 
param['change_params'] = {
                    'delta': 'loss',
                    'sort': 'greatest',
                    'years': {'start': param['composite_params']["start_date"].year, 'end': param['composite_params']["end_date"].year},
                    'mag': {'value': 200, 'operator': '>' },
                    'dur': {'value': 4, 'operator': '<'},
                    'preval': {'value': 300, 'operator': '>'},
                    'mmu': {'value': 5}
                }
param['classified_fc']= f"classified_polygons_{param['composite_params']['end_date'].year}"
param['num_trees']= 200
param['filtered_classes'] = f"classified_polygons_filtered_{param['composite_params']['end_date'].year}"
param['buffered_classes'] = f"classified_polygons_buffered_{param['composite_params']['end_date'].year}"
param['rasterize_classes'] = f"classed_img_{param['composite_params']['end_date'].year}"



# Transformation parameters
param['index'] = "NBR"
param['fit'] = ["NBR", "TCG", "TCW", "TCB"]

# ADS parameters
param['ads'] = ee.FeatureCollection('projects/r6-bugnet/assets/ads-r6-2023')  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
#param['ads_damage'] = 30

# File naming parameters
param['version'] = 'v1'
param['region'] = 'north_cascades'

# Working directories  # if your area is spatially large these should be different locations
param['assetDir'] = "projects/r6-bugnet/assets/north_cascades/"  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
param['LTSDdir'] = "projects/r6-bugnet/assets/north_cascades/"  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# LTSD name
param['LTSDname'] = param['fitted_img_p']

# SNIC parameters
param['snicName'] = f"SNIC_{param['configName']}_{param['target']}"
param['declineName'] = f"Decline_{param['configName']}_{param['target']}"

# KMeans
param['kmeansNameSample'] =  f"KMeans_{param['configName']}_{param['target']}_sample" #KMean$
param['kmeansName'] = f"KMeans_{param['configName']}_{param['target']}"
param['KmeansVector'] = f"KMeans_{param['configName']}_{param['target']}_vector"
param['kmeans_num_sample'] = 5000
param['num_of_clusters'] = 3

# Proportion of Intersection
if param['trainingYear'] == param['target']:
    param['proportionName'] = f"proportions_{param['configName']}_{param['target']}_sample"
else:
    param['proportionName'] = f"proportions_{param['configName']}_{param['trainingYear']}_sample"

# Random Forest Training/Prediction
param['num_of_trainers'] = '1'  # 1 - same year, 2 - all years
param['predicted'] = f"labeled_{param['configName']}_{param['target']}"

# Mask parameters
param['forestMaskName'] = f"bugnet_forest_mask_{param['target']}"
param['maskThese'] = ['cloud', 'shadow']
param['Mask'] = ee.Image(f"{param['assetDir']}{param['forestMaskName']}")
param['buffer'] = 50
param['ltchange'] = ee.Image(f"{param['assetDir']}classed_img_{param['target']}")

# Agent labeling parameters
param['agent_lookback'] = 5
param['agent_distance'] = 10000

param['bnet_polygonized'] = f"bugnet_polygons_{param['target']}"
param['bnet_buffered_polygons'] = f"bugnet_buffered_polygons_{param['target']}"
param['bnet_buffer'] = 100

param['bugnet_polygons'] = f"bugnet_polygons_unlabeled_{param['region']}_{param['target']}_{param['version']}"
param['bugnet_distance_img'] = f"bugnet_distance_image_{param['region']}_{param['target']}_{param['version']}"
param['bugnet_polygons_labeled'] = f"bugnet_polygons_distance_labeled_{param['region']}_{param['target']}_{param['version']}"

param['proportion_strat_sample_size'] = 5000  # three classes to be sampled

if param["platform"] == 'HlS':

    param['lt_collection_params'] = {
        "sr_collection": bnet.build_sr_collection(param["ltstartYear"], param["ltendYear"],param["start_date"],param["end_date"], param["aoi"]),
        "index": param['index'],
        "ftv_list": param['fit'],
    }

    param['lt_params'] = {
        "lt_collection": LtCollection(**param['lt_collection_params']),
        "run_params": {
            'maxSegments': 6,
            'spikeThreshold': 0.9,
            'vertexCountOvershoot': 3,
            'preventOneYearRecovery': True,
            'recoveryThreshold': 0.95,
            'pvalThreshold': 0.05,
            'bestModelProportion': 0.95,
            'minObservationsNeeded': 5
        }
    }

else:
    param['lt_collection_params'] = {
        "sr_collection": LandsatComposite(**param['composite_params']),
        #"sr_collection": composite_params, # - you may also just pass in your own collection or the params directly. Note: in the former, some methods in the class may not work.
        "index": param['index'],
        "ftv_list": param['fit'],
    }

    param['lt_params'] = {
        "lt_collection": param['lt_collection_params'], # - you may also just pass in your own collection or the params directly. Note: in the former, some methods in the class may not work.
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

pprint.pprint(param)
