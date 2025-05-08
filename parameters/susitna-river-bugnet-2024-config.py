import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
from datetime import date
import datetime 


param = {}
param['study_region'] = "AK" # AK or CONUS
param['huc6-id'] = '190205'

param['project_name'] = 'susitna-river-bugnet'
ee.Initialize(project=param['project_name'])
param['configName'] = 'option3'
param['aoi'] = ee.FeatureCollection("USGS/WBD/2017/HUC06").filter(ee.Filter.eq('name','Susitna River'))
param["platform"] = 'LS'
param['parameter_file'] = f"{param['project_name']}_parameter_file"
param['trainingMin'] = 75
param['trainingMax'] = 50000 
param['start_date'] = '06-01'
param['end_date'] = '09-01'
param['ltstartYear'] = 2000
param['ltendYear'] = 2024

# parameters used in decline 
param['target'] = 2024
param['decline_thresholds'] = {'TCB':(0,0),'TCG':(5,5), 'TCW':(10,10), 'NBR':(15,15)}
param['decline_template'] = '{TCB} && {TCG} || {TCW} && {NBR}'
param['agent_lookback'] = 5

param['trainingYear'] = 2023
param['composite_params'] = {
    "start_date": date(param['ltstartYear'], 5,1),
    "end_date": date(param['ltendYear'], 9,20),
    "area_of_interest": param['aoi'],
    #"mask_labels": ['cloud', 'shadow', 'snow', 'water'],
    #"debug": True
}
param['change_params'] = {
                    'delta': 'loss',
                    'sort': 'greatest',
                    'years': {'start': param['composite_params']["end_date"].year-6, 'end': param['composite_params']["end_date"].year},
                    'mag': {'value': 200, 'operator': '>' },
                    'dur': {'value': 4, 'operator': '<'},
                    'preval': {'value': 300, 'operator': '>'},
                    'mmu': {'value': 10}
                }

param['pixel_scale'] = 10
param['region']= 'or'
param['subregion']= 'bluemts'
param['version'] = "1"
param['outputfile_prefix'] = f"Bugnet_{param['region']}_v{param['target']}-{param['version']}_Annual_Change_{param['target']}_{param['subregion']}" 
param['assetDir_t'] = f"projects/{param['project_name']}/assets/" 
param['assetDir'] = f"projects/{param['project_name']}/assets/{param['target']}/" 
param['LTSDdir'] = param['assetDir']  
targetPlus5 = param['target']-5
param['maskStartTime'] = int(datetime.datetime(targetPlus5,1,1).timestamp() * 1000)
param['maskEndTime'] = int(datetime.datetime(param['target'],12,30).timestamp() * 1000)
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
param['classified_fc']= f"classified_polygons_{param['composite_params']['end_date'].year}"
param['num_trees']= 200
param['filtered_classes'] = f"classified_polygons_filtered_{param['composite_params']['end_date'].year}"
param['buffered_classes'] = f"classified_polygons_buffered_{param['composite_params']['end_date'].year}"
param['rasterize_classes'] = f"classed_img_{param['composite_params']['end_date'].year}"
param['index'] = "NBR"
param['fit'] = ["TCB", "TCG", "TCW","NBR"]
param['direction_disturbance'] = [-1, 1, 1, 1] # -1-flips by multiplying by -1 so if disturbance need to decline with disturbance event use -1 if it already does use 1 
param['ads'] = ee.FeatureCollection('projects/r6-bugnet/assets/ads-r6-2023') 
param['LTSDname'] = param['fitted_img_p']
param['snicName'] = f"SNIC_{param['configName']}_{param['target']}"
param['declineName'] = f"Decline_{param['configName']}_{param['target']}"
param['kmeansNameSample'] =  f"KMeans_{param['configName']}_{param['target']}_sample" 
param['kmeansName'] = f"KMeans_{param['configName']}_{param['target']}"
param['KmeansVector'] = f"KMeans_{param['configName']}_{param['target']}_vector"
param['kmeans_num_sample'] = 5000
param['num_of_clusters'] = 3
if param['trainingYear'] == param['target']:
    param['proportionName'] = f"proportions_{param['configName']}_{param['target']}_sample"
else:
    param['proportionName'] = f"proportions_{param['configName']}_{param['trainingYear']}_sample"
param['num_of_trainers'] = '1' 
param['predicted'] = f"labeled_{param['configName']}_{param['target']}"
param['forestMaskName'] = f"bugnet_forest_mask_{param['target']}"
param['maskThese'] = ['cloud', 'shadow']
param['Mask'] = ee.Image(f"{param['assetDir']}{param['forestMaskName']}")
param['buffer'] = 50
param['ltchange'] = ee.Image(f"{param['assetDir']}classed_img_{param['target']}")
param['bnet_polygonized'] = f"bugnet_polygons_{param['target']}"
param['bnet_buffered_polygons'] = f"bugnet_polygons_buffered_{param['target']}"
param['bnet_buffer'] = 100
param['agent_distance'] = 10000
param['proportion_strat_sample_size'] = 5000
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
elif param["platform"] == 'S2-10':
    param['lt_collection_params'] = {
        "sr_collection": Sentinel2Composite(**param['composite_params']),
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
        "index": param['index'],
        "ftv_list": param['fit'],
    }
    param['lt_params'] = {
        "lt_collection": param['lt_collection_params'], 
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

#print(param)

