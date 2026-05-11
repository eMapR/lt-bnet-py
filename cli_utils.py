import importlib.util
import sys

import ee


def load_parameters(file_path):
    """Load a parameter module from disk and return its `param` dictionary."""
    spec = importlib.util.spec_from_file_location("dynamic_params", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "param"):
        return module.param
    raise ValueError("The provided script does not define 'parameters'.")


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
