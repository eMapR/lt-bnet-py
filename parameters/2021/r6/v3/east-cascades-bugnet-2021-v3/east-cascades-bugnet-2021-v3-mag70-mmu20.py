import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
from datetime import date
import datetime 
param = {}
param['project_name'] = 'eastern-cascades-bugnet'
ee.Initialize(project=param['project_name'])
param["platform"] = 'LS'
param['ltstartYear'] = 2000
param['ltendYear'] = 2025
param['target'] = 2021
param['aoi'] = ee.FeatureCollection(ee.FeatureCollection("EPA/Ecoregions/2013/L3").filter(ee.Filter.eq('na_l3name', 'Eastern Cascades Slopes and Foothills')).geometry().intersection(ee.FeatureCollection("TIGER/2018/States").filter(ee.Filter.eq('NAME', 'Oregon')).geometry(), ee.ErrorMargin(1)))
param['composite_params'] = {
    "start_date": date(param['ltstartYear'], 7,1),
    "end_date": date(param['ltendYear'], 9,20),
    "area_of_interest": param['aoi'],
}
param['index'] = "NBR"
param['fit'] = ["TCB", "TCG", "TCW","NBR"]
param['version'] = "3"
param['pixel_scale'] = 30
param['change_params'] = {
                    'delta': 'loss',
                    'sort': 'greatest',
                    'years': {'start': param['target']-6, 'end': param['target']},
                    'mag': {'value': 350, 'operator': '>' },
                    'dur': {'value': 3, 'operator': '<'},
                    'preval': {'value': 300, 'operator': '>'},
                    'mmu': {'value': 8}
                }

param['subregion']= 'easternCascadesOR'
param['sub_region']="easternCascadesOR"

#classify high mag polygons
param['num_trees']= 200
param['class_heavy']=0
param['polygon-split-method'] = 'auto'


param['study_region'] = "CONUS" # AK or CONUS
param['brightness_value']='2500' #  higher for ...
param['configName'] = 'option3'
param['agent_lookback'] = 5
param['decline_step'] = 10
param['decline_thresholds'] = {'tcb': 70, 'tcg': 70, 'tcw': 70}

param['kmeans_num_sample'] = 5000
param['num_of_clusters'] = 3

#polygonization
param['bnet_polygon_mmu'] = 20
param['bnet_buffer'] = 100

param['ADS_path'] = {"on":0,"path": f"projects/{param['project_name']}/assets/adsplaceholder"} 
param['wild_path'] = {"on":1,"path": f"projects/bnet-main/assets/BdyDesg_LSRS_Wilderness","path2":f"projects/north-cascades-bugnet/assets/nps_boundary"} 


#################### automated parameters ################################

param['assetDir'] = f"projects/{param['project_name']}/assets/{param['target']}-v{param['version']}/" 
param['fitted_img_p'] = f"A_predictor_fitted_img_{param['composite_params']['end_date'].year-5}_{param['composite_params']['end_date'].year}" # hardcoded -5
param['predictor_change_img'] = f"A_predictor_change_img_{param['target']}"

param['disturbance_polygons_predictor']= f"B1_predictor_disturbance_polygons_{param['target']}"
param['attributed_polygons_predictor']= f"B2_attributed_predictor_polygons_{param['target']}"

# classifcation high mag
param['classified_fc']= f"C1_classified_polygons_{param['target']}"
param['assetDir_t'] = f"projects/{param['project_name']}/assets/" 
param['attributed_polygons_training']= f"attributed_training_polygons_2012"
param['filtered_classes'] = f"C2_classified_polygons_filtered_{param['target']}"
param['buffered_classes'] = f"C3_classified_polygons_buffered_{param['target']}"
param['rasterize_classes'] = f"C4_classed_img_{param['target']}"

# forest masking
param['forestMaskName'] = f"D_bugnet_forest_mask_{param['target']}"
param['LTSDdir'] = param['assetDir']  
#param['ltchange'] = ee.Image(f"{param['assetDir']}C4_classed_img_{param['target']}")
param['ltchange'] = ee.Image(f"{param['assetDir']}{param['rasterize_classes']}")
targetPlus5 = param['target']-5
param['maskStartTime'] = int(datetime.datetime(targetPlus5,1,1).timestamp() * 1000)
param['maskEndTime'] = int(datetime.datetime(param['target'],12,30).timestamp() * 1000)

#decline
param['declineName'] = f"Decline_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"
param['Mask'] = ee.Image(f"{param['assetDir']}{param['forestMaskName']}")

#kmeans
param['kmeansNameSample'] =  f"KMeans_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}_sample" 
param['kmeansName'] = f"KMeans_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"
#param['KmeansVector'] = f"KMeans_{param['configName']}_{param['target']}_vector"

#bugnet labeling
param['predicted'] = f"labeled_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"

#polygonization
param['bnet_polygonized'] = f"bugnet_polygons_{param['target']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu"
param['bnet_buffered_polygons'] = f"bugnet_polygons_buffered_{param['target']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu"

#parameters export
param['parameter_file'] = f"{param['project_name']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu_parameter_file"

param['outputfile_prefix'] = f"Bugnet_{param['subregion']}_v{param['target']}-{param['version']}_Annual_Change" 


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



