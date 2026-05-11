import datetime
import re

import ee
from ltgee import LandsatComposite


def flatten_dict(d, parent_key="", sep="_"):
    """
    Recursively flatten a nested dictionary.

    Parameters:
        d (dict): The dictionary to flatten.
        parent_key (str): The base key to prepend to each key.
        sep (str): Separator to use for concatenating keys.

    Returns:
        dict: A flattened dictionary.
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, (ee.FeatureCollection, ee.Image, ee.ImageCollection, LandsatComposite)):
            items.append((new_key, "GEE object"))
        else:
            items.append((new_key, v))

    transformed_list = []
    for key, value in items:
        if isinstance(value, list):
            if value and isinstance(value[0], int):
                value = [str(element) for element in value]
            transformed_list.append((key, ", ".join(value)))
        elif isinstance(value, tuple):
            value = list(value)
            if value and isinstance(value[0], int):
                value = [str(element) for element in value]
            transformed_list.append((key, ", ".join(value)))
        elif isinstance(value, datetime.date):
            transformed_list.append((key, value.strftime("%Y-%m-%d")))
        else:
            transformed_list.append((key, value))

    return dict(transformed_list)


def dict_to_feature_collection(param, asset_exists):
    """
    Converts a dictionary to a Google Earth Engine FeatureCollection and exports it.
    """
    exists = asset_exists(param["assetDir"] + param["parameter_file"])
    if exists:
        return None

    flattened_data = flatten_dict(param)
    feature = ee.Feature(param["aoi"].first().geometry().centroid(1), flattened_data)
    feature_collection = ee.FeatureCollection([feature])

    task = ee.batch.Export.table.toAsset(
        collection=feature_collection,
        description=param["parameter_file"],
        assetId=param["assetDir"] + param["parameter_file"],
    )
    task.start()
    return task


def list_assets(params):
    """Lists all assets in the specified asset directory."""
    asset_list = []
    try:
        assets = ee.data.listAssets({"parent": params["assetDir"]}).get("assets", [])
        for asset in assets:
            asset_list.append({"id": asset["name"], "type": asset["type"]})
    except Exception as e:
        print(f"Error accessing asset directory {params['assetDir']}: {e}")
    return asset_list


def get_user_input(prompt, options):
    """Utility function to get user input with validation."""
    print(prompt)
    for idx, option in enumerate(options):
        print(f"{idx + 1}. {option}")
    choice = input("Enter your choice: ")
    while not choice.isdigit() or int(choice) < 1 or int(choice) > len(options):
        print("Invalid choice. Please try again.")
        choice = input("Enter your choice: ")
    return options[int(choice) - 1]


def remove_duplicate_substrings(filename):
    """
    Removes duplicate substrings in a filename.
    Substrings are defined as components separated by _ or -.
    Keeps the first occurrence of each substring and removes the others.
    Delimiters (_ and -) are preserved.
    """
    parts = re.split(r"([_-])", filename)

    seen = set()
    cleaned_parts = []

    for part in parts:
        if part in ["_", "-"]:
            cleaned_parts.append(part)
        elif part not in seen:
            cleaned_parts.append(part)
            seen.add(part)

    result = "".join(cleaned_parts)
    result = re.sub(r"[_-]+", "_", result)
    result = result.strip("_")
    return result


def _sanitize_shapefile_field_name(name, used_names):
    """Return a unique, SHP-safe field name capped at 10 characters."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name)).strip("_")
    if not cleaned:
        cleaned = "field"
    if cleaned[0].isdigit():
        cleaned = f"f_{cleaned}"

    cleaned = cleaned[:10] or "field"
    candidate = cleaned
    suffix = 1
    while candidate.upper() in used_names:
        suffix_text = str(suffix)
        candidate = f"{cleaned[:max(0, 10 - len(suffix_text))]}{suffix_text}"[:10]
        suffix += 1

    used_names.add(candidate.upper())
    return candidate


def sanitize_feature_collection_for_shapefile(collection):
    """
    Rename properties so SHP exports do not fail on invalid or non-unique
    10-character field names.
    """
    first = collection.first()
    if first is None:
        return collection

    property_names = first.propertyNames().getInfo() or []
    property_names = [name for name in property_names if name != ".geo"]
    if not property_names:
        return collection

    used_names = set()
    rename_map = {}
    changed = False

    for name in property_names:
        safe_name = _sanitize_shapefile_field_name(name, used_names)
        rename_map[name] = safe_name
        if safe_name != name:
            changed = True

    if not changed:
        return collection

    old_names = ee.List(property_names)
    new_names = ee.List([rename_map[name] for name in property_names])

    def rename_feature(feature):
        values = old_names.map(lambda prop_name: feature.get(prop_name))
        return ee.Feature(feature.geometry(), ee.Dictionary.fromLists(new_names, values))

    print("Sanitized SHP field names:", rename_map)
    return collection.map(rename_feature)


def export_to_drive(prefix, asset, folder, param):
    """Exports an asset to Google Drive."""
    if asset["type"] == "TABLE":
        print("table")
        collection = ee.FeatureCollection(asset["id"])
        if "parameter" in asset["id"]:
            print("param")
            print(f"{prefix}_{asset['id'].split('/')[-1]}")
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace("bugnet_", "")
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.table.toDrive(
                collection=collection,
                description=outname3,
                folder=prefix,
                fileFormat="CSV",
            )
        else:
            print("shp")
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace("bugnet_", "")
            outname3 = remove_duplicate_substrings(outname2)
            collection = sanitize_feature_collection_for_shapefile(collection)
            task = ee.batch.Export.table.toDrive(
                collection=collection,
                description=outname3,
                folder=prefix,
                fileFormat="SHP",
            )
    elif asset["type"] == "IMAGE":
        image = ee.Image(asset["id"])
        if "fitted" in asset["id"]:
            band_names = image.bandNames()
            count = band_names.size()
            last_three = band_names.slice(count.subtract(3), count)
            last_three_bands = image.select(last_three)
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace("bugnet_", "")
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.image.toDrive(
                image=last_three_bands,
                description=outname3,
                folder=prefix,
                scale=param["pixel_scale"],
                region=image.geometry().bounds(),
                maxPixels=1e13,
            )
        else:
            outname = f"{prefix}_{asset['id'].split('/')[-1]}"
            outname2 = outname.replace("bugnet_", "")
            outname3 = remove_duplicate_substrings(outname2)
            task = ee.batch.Export.image.toDrive(
                image=image,
                description=outname3,
                folder=prefix,
                scale=param["pixel_scale"],
                region=image.geometry().bounds(),
                maxPixels=1e13,
            )
    else:
        print(f"Unsupported asset type: {asset['type']}")
        return
    task.start()
    print(f"Export task started for asset: {asset['id']} to Google Drive folder: {folder}")


def export_to_cloud_storage(asset, bucket, path, param):
    """Exports an asset to Google Cloud Storage."""
    if asset["type"] == "TABLE":
        collection = ee.FeatureCollection(asset["id"])
        task = ee.batch.Export.table.toCloudStorage(
            collection=collection,
            description=f"Export_{asset['id'].split('/')[-1]}",
            bucket=bucket,
            path=path,
        )
    elif asset["type"] == "IMAGE":
        image = ee.Image(asset["id"])
        task = ee.batch.Export.image.toCloudStorage(
            image=image,
            description=f"Export_{asset['id'].split('/')[-1]}",
            bucket=bucket,
            path=path,
            scale=param["pixel_scale"],
            region=image.geometry().bounds(),
        )
    else:
        print(f"Unsupported asset type: {asset['type']}")
        return
    task.start()
    print(f"Export task started for asset: {asset['id']} to Cloud Storage bucket: {bucket}/{path}")


DEFAULT_PREFIXES = (
    "A_predictor_fitted_img_",
    "C4_classed_img_",
    "D_bugnet_forest_mask_",
    "bugnet_polygons_buffered_",
)

DEFAULT_SUFFIXES = (
    "_mag50_10mmu_parameter_file",
    "_mag50_20mmu_parameter_file",
    "_mag50_30mmu_parameter_file",
    "_mag60_10mmu_parameter_file",
    "_mag60_20mmu_parameter_file",
    "_mag60_30mmu_parameter_file",
    "_mag70_10mmu_parameter_file",
    "_mag70_20mmu_parameter_file",
    "_mag70_30mmu_parameter_file",
)


def _is_default_asset(asset_id: str) -> bool:
    base = asset_id.rsplit("/", 1)[-1]
    return base.startswith(DEFAULT_PREFIXES) or base.endswith(DEFAULT_SUFFIXES)


def export_assets(params, use_defaults=True):
    """Main function to export assets automatically or interactively."""
    location = get_user_input(
        "Where would you like to export your assets?",
        ["Google Drive", "Google Cloud Storage"],
    )

    assets = list_assets(params)

    if use_defaults:
        selected_assets = [a for a in assets if _is_default_asset(a["id"])]
        print(f"Exporting {len(selected_assets)} default assets...")
    else:
        print("\nAvailable assets:")
        for idx, asset in enumerate(assets):
            print(f"{idx + 1}. {asset['id']} ({asset['type']})")
        selected_indices = input(
            "Enter the numbers of the assets you'd like to export (comma-separated): "
        ).split(",")
        selected_indices = [int(idx.strip()) - 1 for idx in selected_indices if idx.strip().isdigit()]
        selected_assets = [assets[idx] for idx in selected_indices]

    if location == "Google Drive":
        folder = input("Enter the Google Drive folder name: ")
        for asset in selected_assets:
            print(params["outputfile_prefix"], folder, params)
            export_to_drive(params["outputfile_prefix"], asset, folder, params)
    elif location == "Google Cloud Storage":
        bucket = input("Enter the Google Cloud Storage bucket name: ")
        path = input("Enter the path within the bucket: ")
        for asset in selected_assets:
            export_to_cloud_storage(asset, bucket, path, params)
    else:
        print("Invalid location. Exiting.")
