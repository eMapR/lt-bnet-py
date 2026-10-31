import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite
from datetime import date
import datetime

# BugNet run config template: the "legacy V2" method used for the 2026
# products (v2026-2) in USFS Region 6 and Region 10 (Alaska).
#
# Copy this file to
#   bugnet/run_configs/<region>-bugnet-<target>-v2/<region>-bugnet-<target>-v2-config.py
# (run_configs/ is gitignored), change every line marked CHANGE ME, then run
#   echo 2 | python bugnet/main.py <that file>
# Mode 2 (predictor only) is how every 2026 region was run: it uses
# existing training polygons (attributed_polygons_training below) instead of
# building them.
#
# Built from the cascades-bugnet (Region 6) and nse-alaska-bugnet (Region 10)
# 2026 configs. Where the two differed, both values are given. Every key is
# described in docs/parameter_reference_template.py.

param = {}

# --- Earth Engine projects --------------------------------------------------
param['project_name'] = 'my-region-bugnet'  # CHANGE ME: holds the assets and names the run
# Optional: run Earth Engine work (and its quota) in another project; assets
# still go to project_name. Delete the line to compute in project_name.
param['compute_project'] = param['project_name']
ee.Initialize(project=param['compute_project'])

# --- Years -------------------------------------------------------------------
param["platform"] = 'LS'
param['ltstartYear'] = 2000
param['ltendYear'] = 2026  # CHANGE ME
param['target'] = 2026     # CHANGE ME: the survey year mapped

# --- Area of interest ---------------------------------------------------------
# CHANGE ME. Region 6 used EPA Level III ecoregions clipped to states, e.g.
#   EPA/Ecoregions/2013/L3 na_l3name 'Cascades' intersected with OR + WA;
# Region 10 used USGS HUC6 basins clipped to Alaska (example below).
param['aoi'] = ee.FeatureCollection(
    ee.FeatureCollection("USGS/WBD/2017/HUC06").filter(ee.Filter.eq('huc6', '190103')).geometry()
    .intersection(ee.FeatureCollection("TIGER/2018/States").filter(ee.Filter.eq('NAME', 'Alaska')).geometry(), ee.ErrorMargin(1))
)

# --- Annual Landsat composites and LandTrendr ---------------------------------
param['composite_params'] = {
    "start_date": date(param['ltstartYear'], 7, 1),
    # CHANGE ME. A fixed date keeps the composite window recorded correctly.
    # The 2026 run configs used date.today(), so a resumed run's parameter
    # file shows the relaunch date instead of the composite date.
    "end_date": date(2026, 9, 15),
    "area_of_interest": param['aoi'],
    "mask_labels": ['cloud', 'shadow', 'snow', 'water'],
}
param['index'] = "NBR"
param['fit'] = ["TCB", "TCG", "TCW", "NBR"]
param['version'] = '2'
param['pixel_scale'] = 30

# --- High-magnitude (abrupt) disturbance ---------------------------------------
param['change_params'] = {
    'delta': 'loss',
    'sort': 'greatest',
    'years': {'start': param['composite_params']['end_date'].year - 6, 'end': param['composite_params']['end_date'].year},
    'mag': {'value': 250, 'operator': '>'},
    'dur': {'value': 3, 'operator': '<'},    # Region 10 runs used 4
    'preval': {'value': 300, 'operator': '>'},
    'mmu': {'value': 8}                       # Region 10 runs used 10
}

param['subregion'] = 'my-region'  # CHANGE ME: label used in output file names
param['sub_region'] = param['subregion']

param['num_trees'] = 200
param['class_heavy'] = 0
param['polygon-split-method'] = 'auto'  # 'grid' splits large AOIs into cells

param['study_region'] = "AK"  # CHANGE ME: "CONUS" (Region 6) or "AK" (Region 10)
param['brightness_value'] = '2500'
param['configName'] = 'option3'
param['agent_lookback'] = 5

# --- Gradual decline, clustering and final polygons ----------------------------
param['decline_step'] = 10
param['decline_thresholds'] = {'tcb': 70, 'tcg': 50, 'tcw': 50}
param['kmeans_num_sample'] = 1000
param['num_of_clusters'] = 3
param['bnet_polygon_mmu'] = 10  # final polygons must have more than 10 pixels
param['bnet_buffer'] = 30       # meters

# --- Ancillary layers ---------------------------------------------------------------
param['ADS_path'] = {"on": 0, "path": f"projects/{param['project_name']}/assets/adsplaceholder"}
# Wilderness and National Park boundaries (lab assets, not public; see the
# README's "Earth Engine inputs"). Set "on" to 0 if you can't read them.
param['wild_path'] = {"on": 1, "path": "projects/bnet-main/assets/BdyDesg_LSRS_Wilderness",
                      "path2": "projects/north-cascades-bugnet/assets/nps_boundary"}

param['decline_method'] = 'persistence'
param['fire_mask_source'] = 'mtbs_wfigs'  # or 'mtbs' (MTBS lags recent fires)

# Classifier labels that are masked out before decline detection. Leave
# unset for the default (fire, harvest, development). [] masks nothing; use
# it where those labels can't be right (Prince William Sound: no harvest and
# no fire on record).
# param['exclusion_classes'] = []

# --- Training polygons for the high-magnitude classifier -------------------------
param['assetDir_t'] = f"projects/{param['project_name']}/assets/"
# CHANGE ME if needed. Region 6 projects have their own
# attributed_training_polygons_2012; the 2026 Alaska runs used a copy of
# Coast Range's set (attributed_training_polygons_2012_from_coast_range).
param['attributed_polygons_training'] = "attributed_training_polygons_2012"

#################### automated parameters (normally unchanged) ####################

param['assetDir'] = f"projects/{param['project_name']}/assets/{param['target']}-v{param['version']}/"
param['fitted_img_p'] = f"A_predictor_fitted_img_{param['composite_params']['end_date'].year - 5}_{param['composite_params']['end_date'].year}"
param['predictor_change_img'] = f"A_predictor_change_img_{param['composite_params']['end_date'].year}"

param['disturbance_polygons_predictor'] = f"B1_predictor_disturbance_polygons_{param['composite_params']['end_date'].year}"
param['attributed_polygons_predictor'] = f"B2_attributed_predictor_polygons_{param['composite_params']['end_date'].year}"

param['classified_fc'] = f"C1_classified_polygons_{param['composite_params']['end_date'].year}"
param['filtered_classes'] = f"C2_classified_polygons_filtered_{param['composite_params']['end_date'].year}"
param['buffered_classes'] = f"C3_classified_polygons_buffered_{param['composite_params']['end_date'].year}"
param['rasterize_classes'] = f"C4_classed_img_{param['composite_params']['end_date'].year}"

param['forestMaskName'] = f"D_bugnet_forest_mask_{param['target']}"
param['LTSDdir'] = param['assetDir']
param['ltchange'] = ee.Image(f"{param['assetDir']}{param['rasterize_classes']}")
targetPlus5 = param['target'] - 5
param['maskStartTime'] = int(datetime.datetime(targetPlus5, 1, 1).timestamp() * 1000)
param['maskEndTime'] = int(datetime.datetime(param['target'], 12, 30).timestamp() * 1000)

param['declineName'] = f"Decline_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"
param['Mask'] = ee.Image(f"{param['assetDir']}{param['forestMaskName']}")

param['kmeansNameSample'] = f"KMeans_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}_sample"
param['kmeansName'] = f"KMeans_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"

param['predicted'] = f"labeled_{param['configName']}_{param['target']}_mag{param['decline_thresholds']['tcw']}"

param['bnet_polygonized'] = f"bugnet_polygons_{param['target']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu"
param['bnet_buffered_polygons'] = f"bugnet_polygons_buffered_{param['target']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu"

param['parameter_file'] = f"{param['project_name']}_mag{param['decline_thresholds']['tcw']}_{param['bnet_polygon_mmu']}mmu_parameter_file"

param['outputfile_prefix'] = f"Bugnet_{param['subregion']}_v{param['target']}-{param['version']}_Annual_Change"

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
