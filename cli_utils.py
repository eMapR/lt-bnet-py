import importlib.util
import sys

import ee


# Keys every real parameter file in this repo sets directly (confirmed
# against run_configs/2025/r6/v1/*, templates/v3/*, and
# legacy_parameters/2024/v3/* - the current live schemas, not the retired
# legacy_parameters/2024/v1/ one).
# Deliberately excludes:
#   - version/shared_version/logic_version/assetDir/sharedAssetDir/LTSDdir/
#     ltchange/Mask: optional or derived by normalize_parameters().
#   - training-only keys (cMonster_img_path, source_epsg, target_epsg,
#     fitted_img_t, training_change_img, disturbance_polygons_training,
#     trainingMin, trainingMax): absent from every current template, since
#     real runs only ever exercise run_mode_2 against assets a run_mode_1
#     built once, long ago, under the older schema. Not validated here -
#     a config missing them will still fail loudly (KeyError) if someone
#     actually runs mode 1 against it, just not at load time.
#   - ads: unused in every current template (ADS_path['on'] is always
#     False in practice - see docs/parameter_reference_template.py).
REQUIRED_PARAM_KEYS = [
    "project_name", "target", "aoi", "composite_params", "index", "fit",
    "pixel_scale", "num_trees", "class_heavy", "polygon-split-method",
    "study_region", "brightness_value", "configName", "agent_lookback",
    "decline_step", "decline_thresholds", "kmeans_num_sample",
    "num_of_clusters", "bnet_polygon_mmu", "bnet_buffer", "ADS_path",
    "wild_path", "fitted_img_p", "predictor_change_img",
    "disturbance_polygons_predictor", "attributed_polygons_predictor",
    "classified_fc", "assetDir_t", "attributed_polygons_training",
    "filtered_classes", "buffered_classes", "rasterize_classes",
    "forestMaskName", "maskStartTime", "maskEndTime", "declineName",
    "kmeansNameSample", "kmeansName", "predicted", "bnet_polygonized",
    "bnet_buffered_polygons", "parameter_file", "outputfile_prefix",
    "lt_params",
]


def validate_parameters(param):
    """
    Raise a clear ValueError listing every missing/conditionally-missing
    key, instead of letting a real run fail deep inside some stage
    function with a bare KeyError. Call after normalize_parameters() so
    configName/decline_path have their final, resolved values.
    """
    missing = [k for k in REQUIRED_PARAM_KEYS if k not in param]

    # LTSDname/snicName are only read by modeling_utils.snic() /
    # bnet.SNIC_decline_image(), which only run on the SNIC decline path
    # (pipeline_modes.run_mode_1/2 branch on param["decline_path"]).
    # Found missing from every real 2025 SNIC-path config
    # (run_configs/2025/r6/v1/*-config.py and their mag/mmu variants) -
    # this is exactly the gap that let KeyError: 'LTSDname' happen deep
    # inside a live GEE run instead of at load time.
    if param.get("decline_path") == "snic":
        for key in ("LTSDname", "snicName"):
            if key not in param:
                missing.append(key)

    if missing:
        raise ValueError(
            f"Parameter file is missing required key(s): {', '.join(missing)}"
        )


def load_parameters(file_path):
    """Load a parameter module from disk and return its `param` dictionary."""
    spec = importlib.util.spec_from_file_location("dynamic_params", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "param"):
        param = normalize_parameters(module.param)
        validate_parameters(param)
        return param
    raise ValueError("The provided script does not define 'parameters'.")


def normalize_parameters(param):
    """Fill derived version and asset-directory parameters for older configs."""
    version = str(param.get("version", "3")).removeprefix("v")
    has_explicit_logic_version = "logic_version" in param
    logic_version = str(param.get("logic_version", version.split("-", 1)[0])).removeprefix("v")
    shared_version = str(param.get("shared_version", logic_version)).removeprefix("v")

    param["version"] = version
    param["logic_version"] = logic_version
    param["shared_version"] = shared_version
    if has_explicit_logic_version or "-" in version:
        param["configName"] = f"option{logic_version}"
    else:
        param["configName"] = param.get("configName", f"option{logic_version}")

    # Which decline algorithm to run (declining_ltsd vs. declining_snic in
    # pipeline_modes.py) used to be inferred purely from "3" in configName
    # - self-describing configs can now set this explicitly instead
    # (e.g. configName='snic' wouldn't contain "3", so it MUST set
    # decline_path itself; don't rely on the fallback for new-style
    # configName values). Only derived from the legacy option1/option3
    # convention when a config doesn't set it, so every existing config
    # file keeps behaving exactly as it does today.
    param["decline_path"] = param.get("decline_path") or (
        "ltsd" if "3" in param["configName"] else "snic"
    )

    project = param["project_name"]
    target = param["target"]
    param["assetDir"] = f"projects/{project}/assets/{target}-v{version}/"
    param["sharedAssetDir"] = f"projects/{project}/assets/{target}-v{shared_version}/"
    param["LTSDdir"] = param["sharedAssetDir"]

    if "rasterize_classes" in param:
        param["ltchange"] = ee.Image(f"{param['sharedAssetDir']}{param['rasterize_classes']}")
    if "forestMaskName" in param:
        param["Mask"] = ee.Image(f"{param['sharedAssetDir']}{param['forestMaskName']}")

    return param


def walk_assets(parent_id):
    """Yield every child asset below a parent asset, recursively."""
    info = ee.data.getAsset(parent_id)
    for child in ee.data.listAssets({"parent": info["name"]}).get("assets", []):
        asset_type = child["type"]
        name = child["name"]
        if asset_type in ("FOLDER", "IMAGE_COLLECTION"):
            yield from walk_assets(name)
        else:
            yield name


def gui():
    """Prompt for the top-level bugnet action."""
    print("Welcome to bugnet!")
    print("How would you like to continue? Enter ...")
    print("    1 - Run bugnet.")
    print("    2 - Run bugnet no training.")
    print("    3 - Export.")
    print("    4 - Clean.")
    mode = input(":")
    if mode in {"1", "2", "3", "4", "5"}:
        return mode
    print("bye")
    sys.exit()
