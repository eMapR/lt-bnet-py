import datetime

import ee


def get_unique_pixel_values(param, asset_exists, region=None, scale=30):
    """Return a list of unique cluster pixel values."""
    exists = asset_exists(param["assetDir"] + param["predicted"])
    if exists:
        return

    image = ee.Image(param["assetDir"] + param["kmeansName"])
    if region is None:
        region = image.geometry()

    histogram_dict = image.select("cluster").reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=region,
        scale=scale,
        maxPixels=1e13,
    ).get("cluster")

    histogram = ee.Dictionary(histogram_dict).getInfo()
    unique_values = list(histogram.keys())
    try:
        unique_values = [int(v) for v in unique_values]
    except ValueError:
        pass
    return unique_values


def prompt_reclassification_mapping(unique_values, new_values=None, interactive=False, value_type=int):
    """Build a mapping from original pixel values to new values."""
    orig = list(dict.fromkeys(unique_values))

    if new_values is None and not interactive:
        mapped = list(orig)
    elif new_values is None and interactive:
        print("Original values found in image:", orig)
        print(f"Enter {len(orig)} new values (in order), separated by commas.")
        while True:
            input_str = input("New values: ").strip()
            if not input_str:
                mapped = list(orig)
                break
            parts = [p.strip() for p in input_str.split(",")]
            if len(parts) != len(orig):
                print(f"Error: expected {len(orig)} values, got {len(parts)}. Try again.")
                continue
            try:
                mapped = [value_type(p) if value_type is not None else p for p in parts]
                break
            except Exception:
                print("Error: please enter valid values.")
                continue
    elif isinstance(new_values, (list, tuple)):
        if len(new_values) != len(orig):
            raise ValueError(f"Length mismatch: got {len(new_values)}, expected {len(orig)}.")
        mapped = list(new_values)
    elif isinstance(new_values, dict):
        mapped = [new_values.get(v, v) for v in orig]
    else:
        raise TypeError("new_values must be None, list/tuple, or dict.")

    if value_type is not None:
        try:
            mapped = [value_type(v) for v in mapped]
        except Exception as e:
            raise ValueError(f"Failed to coerce mapped values with {value_type}: {e}")

    return orig, mapped


def reclassify_image(params, from_values, to_values):
    """Reclassify KMeans cluster values and export the result."""
    image = ee.Image(params["assetDir"] + params["kmeansName"])
    outimg = image.select("cluster").remap(from_values, to_values).rename("classified")
    task = ee.batch.Export.image.toAsset(
        image=outimg.toInt8(),
        description=params["predicted"],
        assetId=params["assetDir"] + params["predicted"],
        region=params["aoi"].geometry(),
        scale=params["pixel_scale"],
        maxPixels=1e13,
    )
    task.start()
    return task


def polygonize_bnet(param, asset_exists):
    """Vectorize the predicted image into polygons."""
    exists = asset_exists(param["assetDir"] + param["bnet_polygonized"])
    if exists:
        return
    img = ee.Image(param["assetDir"] + param["predicted"])
    polygons = img.reduceToVectors(
        reducer=ee.Reducer.countEvery(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    ).filter(ee.Filter.gt("count", param["bnet_polygon_mmu"]))

    task = ee.batch.Export.table.toAsset(
        collection=polygons,
        description=param["bnet_polygonized"],
        assetId=param["assetDir"] + param["bnet_polygonized"],
    )
    task.start()
    return task


def extract_zonal_stats(image, feature_collection, stat_type, output_field_name, param):
    """Reduce image values over features and write the chosen statistic to a field."""
    if stat_type == "mean":
        reducer = ee.Reducer.mean()
    elif stat_type == "sum":
        reducer = ee.Reducer.sum()
    elif stat_type == "min":
        reducer = ee.Reducer.min()
    elif stat_type == "max":
        reducer = ee.Reducer.max()
    elif stat_type == "mode":
        reducer = ee.Reducer.mode()
    else:
        raise ValueError("Unsupported stat_type: " + stat_type)

    zonal_stats = image.reduceRegions(
        collection=feature_collection,
        reducer=reducer,
        scale=param["pixel_scale"],
    )

    def set_stat_value(feature):
        stat_value = feature.get(stat_type)
        return feature.set(output_field_name, stat_value)

    return zonal_stats.map(set_stat_value)


def split_multi_polygon_ss(feature):
    """Split a (multi)polygon Feature into single-part polygons on the server."""
    geom = ee.Geometry(feature.geometry())
    parts = ee.List(geom.geometries())
    props = feature.toDictionary()
    return ee.FeatureCollection(
        parts.map(lambda g: ee.Feature(ee.Geometry(g)).set(props))
    )


def calc_attri_fields(param):
    """Build the standard output attribute fields for buffered polygons."""
    today = datetime.datetime.today()
    formatted_date = today.strftime("%m-%d-%Y")
    return {
        "ACRES": 0,
        "CREATED_DATE": formatted_date,
        "DAMAGE_TYPE": "null",
        "DAMAGE_TYPE_CODE": 0,
        "DCA": "null",
        "DCA_CODE": 0,
        "FEATURE_USER_ID": "clarype@oregonstate.edu",
        "HOST": "null",
        "HOST_CODE": 0,
        "HOST_GROUP": "null",
        "HOST_GROUP_CODE": 0,
        "NOTES": "null",
        "REGION_ID": param["study_region"],
        "US_AREA": "CONUS",
        "MODIFIED_DATE": "na",
        "SURVEY_YEAR": param["target"],
        "buffered_acres": 0,
        "pct_affected": 0,
        "unbuffered_acres": 0,
    }


def add_area_and_pct_affected_by_pixel_count(
    fc_buffered,
    fc_unbuffered,
    count_field="count",
    pixel_size_meters=30,
):
    """Add buffered/unbuffered acres and percent affected to buffered polygons."""
    acres_per_sq_m = 0.00024710538146717
    acres_per_pixel = ee.Number(pixel_size_meters).multiply(pixel_size_meters).multiply(acres_per_sq_m)

    join = ee.Join.saveAll(matchesKey="matches")
    filt = ee.Filter.contains(leftField=".geo", rightField=".geo")
    joined = ee.FeatureCollection(join.apply(fc_buffered, fc_unbuffered, filt))

    def per_buffer(buf):
        buf = ee.Feature(buf)
        buffer_area_acres = ee.Number(buf.geometry().area(1)).multiply(acres_per_sq_m)
        matches = ee.FeatureCollection(ee.List(buf.get("matches")))
        pixel_count_sum = ee.Number(
            ee.Algorithms.If(matches.size().gt(0), matches.aggregate_sum(count_field), 0)
        )
        affected_acres = pixel_count_sum.multiply(acres_per_pixel)
        pct_affected = ee.Number(
            ee.Algorithms.If(
                buffer_area_acres.gt(0),
                affected_acres.divide(buffer_area_acres).multiply(100),
                0,
            )
        )
        return (
            buf.set("buffered_acres", buffer_area_acres)
            .set("unbuffered_acres", affected_acres)
            .set("pct_affected", pct_affected)
            .set("matches", None)
        )

    return joined.map(per_buffer)


def buffer_bnet_polygons(param, asset_exists):
    """Buffer polygonized BugNet polygons in shards and export them."""
    exists = asset_exists(param["assetDir"] + param["bnet_buffered_polygons"])
    if exists:
        return 0, 0

    asset_dir = param["assetDir"]
    base_name = param["bnet_buffered_polygons"]
    buckets = int(param.get("buckets", 75))
    buffer_m = float(param["bnet_buffer"])
    max_err = float(param.get("buffer_max_error", 10))
    mmu = float(param["bnet_polygon_mmu"])

    fc = ee.FeatureCollection(asset_dir + param["bnet_polygonized"]).filter(ee.Filter.gt("count", mmu))
    fc = fc.randomColumn("rand", 42).map(
        lambda f: f.set("bucket", ee.Number(f.get("rand")).multiply(buckets).floor())
    )

    tasks = []
    asset_ids = []
    for bucket in range(buckets):
        sub = fc.filter(ee.Filter.eq("bucket", bucket)).map(
            lambda ft: ft.setGeometry(ft.geometry().buffer(buffer_m, max_err))
        )
        size = ee.Number(sub.size())
        shard_id = f"{asset_dir}{base_name}_shard_{bucket:03d}"
        asset_ids.append(shard_id)
        if size.getInfo() > 0:
            task = ee.batch.Export.table.toAsset(
                collection=sub,
                description=f"{base_name}_shard_{bucket:03d}",
                assetId=shard_id,
            )
            task.start()
            tasks.append(task)

    return tasks, asset_ids


def merge_buffer_buckets_and_finish(param, asset_ids, asset_exists):
    """Merge buffered shards, rebuild attributes, and export the final output."""
    exists = asset_exists(param["assetDir"] + param["bnet_buffered_polygons"])
    if exists:
        return

    asset_dir = param["assetDir"]
    max_err = float(param.get("buffer_max_error", 10))

    if hasattr(asset_ids, "getInfo"):
        asset_ids = asset_ids.getInfo()
    asset_ids = [str(a) for a in asset_ids]

    merged = ee.FeatureCollection([])
    for aid in asset_ids:
        try:
            fc = ee.FeatureCollection(aid)
            size = fc.size().getInfo()
            if size and size > 0:
                merged = merged.merge(fc)
        except Exception as e:
            print(f"Skipping shard {aid}: {e}")

    if merged.size().getInfo() == 0:
        raise RuntimeError("No shard data found. Check shard exports and asset_ids.")

    dissolved_geom = merged.geometry().dissolve(max_err)
    dissolved_fc = ee.FeatureCollection([ee.Feature(dissolved_geom)])
    polygons_fc = split_multi_polygon_ss(dissolved_fc.first())

    img = ee.Image(asset_dir + param["predicted"])
    fc_bnet = extract_zonal_stats(img, polygons_fc, "mode", "bnet_label", param)

    def rebuild_feature(feature):
        feature = ee.Feature(feature)
        new_props = ee.Dictionary(calc_attri_fields(param))
        return ee.Feature(feature.geometry()).set(new_props)

    fc_attri = fc_bnet.map(rebuild_feature)
    result = add_area_and_pct_affected_by_pixel_count(
        fc_buffered=fc_attri,
        fc_unbuffered=param["assetDir"] + param["bnet_polygonized"],
        count_field="count",
        pixel_size_meters=param["pixel_scale"],
    )

    task = ee.batch.Export.table.toAsset(
        collection=result,
        description=param["bnet_buffered_polygons"],
        assetId=param["assetDir"] + param["bnet_buffered_polygons"],
    )
    task.start()
    return task
