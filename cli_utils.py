import importlib.util
import sys

import ee


def load_parameters(file_path):
    """Load a parameter module from disk and return its `param` dictionary."""
    spec = importlib.util.spec_from_file_location("dynamic_params", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "param"):
        return normalize_parameters(module.param)
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
