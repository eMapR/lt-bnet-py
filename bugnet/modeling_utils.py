import time

import ee

import bnet


def create_forest_mask(param, asset_exists):
    """Create and export the forest mask."""
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param["forestMaskName"])
    if exists:
        return

    mtbs = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")
    lcms_mask = bnet.lcms_forest_mask(2024, param["target"], param).clip(param["aoi"])
    tass_map = bnet.tasselCapMask(param)
    high_mag_change_img = param["ltchange"].gt(0).unmask().Not()

    fires = mtbs.filter(
        ee.Filter.And(
            ee.Filter.gte("Ig_Date", param["maskStartTime"]),
            ee.Filter.lte("Ig_Date", param["maskEndTime"]),
        )
    )
    fire_img = (
        fires.reduceToImage(properties=["Map_ID"], reducer=ee.Reducer.mean())
        .gt(0)
        .unmask()
        .Not()
    )

    mask = (
        lcms_mask.clip(param["aoi"])
        .multiply(high_mag_change_img)
        .multiply(fire_img)
        .multiply(tass_map)
        .updateMask(ee.ImageCollection("JRC/GFC2020/V2").mosaic())
    )

    task_mask = ee.batch.Export.image.toAsset(
        image=mask.byte(),
        description=param["forestMaskName"],
        assetId=asset_dir + param["forestMaskName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_mask.start()
    return task_mask


def create_forest_mask_vis(param, asset_exists):
    """Create and export a diagnostic labeled forest mask."""
    asset_dir = param.get("sharedAssetDir", param["assetDir"])
    exists = asset_exists(asset_dir + param["forestMaskName"] + "_label")
    if exists:
        return

    mtbs = ee.FeatureCollection("USFS/GTAC/MTBS/burned_area_boundaries/v1")
    lcms = bnet.lcms_forest_mask(2024, param["target"], param).unmask(0).toInt()
    tass = bnet.tasselCapMask(param).unmask(0).toInt()
    high = param["ltchange"].gt(0).unmask(0).toInt()
    fire = (
        mtbs.filter(
            ee.Filter.And(
                ee.Filter.gte("Ig_Date", param["maskStartTime"]),
                ee.Filter.lte("Ig_Date", param["maskEndTime"]),
            )
        )
        .reduceToImage(["Map_ID"], ee.Reducer.mean())
        .gt(0)
        .unmask(0)
        .toInt()
    )

    mask_code = (
        lcms.bitwiseOr(high.leftShift(1))
        .bitwiseOr(fire.leftShift(2))
        .bitwiseOr(tass.leftShift(3))
        .toInt16()
        .clip(param["aoi"])
        .updateMask(ee.ImageCollection("JRC/GFC2020/V2").mosaic())
    )

    task_mask = ee.batch.Export.image.toAsset(
        image=mask_code.int16(),
        description=param["forestMaskName"] + "_label",
        assetId=asset_dir + param["forestMaskName"] + "_label",
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_mask.start()
    return task_mask


def snic(param, asset_exists):
    """Create and export the SNIC image."""
    exists = asset_exists(param["assetDir"] + param["snicName"])
    if exists:
        return

    ltsd = ee.Image(param["LTSDdir"] + param["LTSDname"])
    ltsd_snic = bnet.snic_image(ltsd).mask(param["Mask"])
    task_snic = ee.batch.Export.image.toAsset(
        image=ltsd_snic.toInt16(),
        description=param["snicName"],
        assetId=param["assetDir"] + param["snicName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_snic.start()
    return task_snic


def declining_snic(param, asset_exists):
    """Create and export the SNIC decline image."""
    exists = asset_exists(param["assetDir"] + param["declineName"])
    if exists:
        return

    decline = bnet.SNIC_decline_image(param).updateMask(param["Mask"])
    task_decline = ee.batch.Export.image.toAsset(
        image=decline.toInt16(),
        description=param["declineName"],
        assetId=param["assetDir"] + param["declineName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_decline.start()
    return task_decline


def declining_ltsd(param, asset_exists):
    """Create and export the LTSD decline image."""
    exists = asset_exists(param["assetDir"] + param["declineName"])
    if exists:
        return

    decline = bnet.LTSD_decline_score(param).updateMask(param["Mask"])
    task_decline = ee.batch.Export.image.toAsset(
        image=decline.toInt16(),
        description=param["declineName"],
        assetId=param["assetDir"] + param["declineName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_decline.start()
    return task_decline


def _asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except Exception:
        return False


def _wait_for_task(task: ee.batch.Task, poll_seconds=20, timeout_minutes=180, on_update=None):
    """Poll a task until terminal state and return its final status."""
    start = time.time()
    last_state = None
    while True:
        status = task.status()
        state = status.get("state")
        if state != last_state and on_update:
            on_update(f"[GEE task {task.id}] state={state}")
            last_state = state

        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            return status

        if timeout_minutes and (time.time() - start) > timeout_minutes * 60:
            try:
                task.cancel()
            except Exception:
                pass
            status["state"] = "CANCELLED"
            status["error_message"] = f"Timed out after {timeout_minutes} minutes."
            return status

        time.sleep(poll_seconds)


def build_kmeans_sample(
    param,
    asset_exists,
    poll_seconds=20,
    timeout_minutes=180,
    overwrite=False,
    progress_cb=None,
):
    """Build and export a KMeans sample asset, trying several fallback methods."""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    asset_id = f"{param['assetDir']}{param['kmeansName']}_sample"
    desc_base = f"{param['kmeansName']}_sample"

    if _asset_exists(asset_id):
        if not overwrite:
            return {"final_state": "ALREADY_EXISTS", "assetId": asset_id, "attempts": []}

    decline = ee.Image(param["assetDir"] + param["declineName"])
    aoi = param["aoi"]
    scale = param["pixel_scale"]
    n = int(param["kmeans_num_sample"])

    attempts = [
        (
            "stratifiedSample",
            lambda: decline.stratifiedSample(
                numPoints=200,
                classBand="decline_score",
                region=aoi,
                scale=scale,
                geometries=True,
            ),
        ),
        (
            "reduceToVectors-centroids",
            lambda: decline.reduceToVectors(
                geometry=aoi,
                scale=scale,
                geometryType="centroid",
                labelProperty="zone",
                maxPixels=1e13,
                reducer=ee.Reducer.first(),
            ),
        ),
        (
            "sample",
            lambda: ee.FeatureCollection(
                decline.sample(
                    region=aoi,
                    scale=scale,
                    numPixels=n,
                    tileScale=12,
                    geometries=True,
                ).randomColumn().sort("random")
            ),
        ),
        (
            "sampleRegions",
            lambda: ee.FeatureCollection(
                decline.sampleRegions(
                    collection=aoi,
                    scale=scale,
                    geometries=True,
                ).randomColumn().sort("random").toList(n)
            ),
        ),
    ]

    attempt_logs = []
    for name, builder in attempts:
        if asset_exists(asset_id):
            return {"final_state": "COMPLETED", "assetId": asset_id, "attempts": attempt_logs}

        try:
            fc = builder()
        except Exception as e:
            attempt_logs.append({"name": name, "build_error": str(e)})
            continue

        task = ee.batch.Export.table.toAsset(
            collection=fc,
            description=f"{desc_base}__{name}",
            assetId=asset_id,
        )
        task.start()

        status = _wait_for_task(
            task,
            poll_seconds=poll_seconds,
            timeout_minutes=timeout_minutes,
            on_update=log,
        )
        attempt_logs.append({"name": name, "task_id": task.id, "status": status})
        state = status.get("state")
        if state == "COMPLETED" or asset_exists(asset_id):
            return {"final_state": "COMPLETED", "assetId": asset_id, "attempts": attempt_logs}

    return {"final_state": "FAILED", "assetId": asset_id, "attempts": attempt_logs}


def kmeans_image(param, asset_exists):
    """Create and export the clustered KMeans image."""
    exists = asset_exists(param["assetDir"] + param["kmeansName"])
    if exists:
        return

    decline = ee.Image(param["assetDir"] + param["declineName"])
    snic_bands = decline.bandNames().slice(1, -1)
    training = ee.Clusterer.wekaCascadeKMeans(
        param["num_of_clusters"],
        param["num_of_clusters"],
        10,
        False,
        True,
    ).train(ee.FeatureCollection(param["assetDir"] + param["kmeansNameSample"]), snic_bands)

    snic_decline_kmeans = decline.cluster(training).clip(param["aoi"])
    task_kmeans = ee.batch.Export.image.toAsset(
        image=snic_decline_kmeans.toInt16(),
        description=param["kmeansName"],
        assetId=param["assetDir"] + param["kmeansName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_kmeans.start()
    return task_kmeans


def kmeans_proportions_ads_sample(param, asset_exists):
    """Create and export the KMeans/ADS intersection vector."""
    exists = asset_exists(param["assetDir"] + param["KmeansVector"])
    if exists:
        return

    ads = param["ads"].filterBounds(param["aoi"])
    aoi = param["aoi"]
    kmeans = ee.Image(param["assetDir"] + param["kmeansName"]).rename(["kmeans_clusters"])
    kmeans_v = kmeans.reduceToVectors(
        reducer=ee.Reducer.countEvery(),
        geometry=aoi.geometry(),
        tileScale=12,
        maxPixels=1e13,
    )

    def calculate_proportion_attri(feature):
        ads_g = ads.geometry()
        feature_geometry = feature.geometry()
        return ee.Feature(
            ee.Algorithms.If(
                ads_g.intersects(feature_geometry, 1),
                feature.set("touch", 1),
                feature.set("touch", 0),
            )
        )

    proportion_attri = kmeans_v.map(calculate_proportion_attri)
    task_sample = ee.batch.Export.table.toAsset(
        collection=proportion_attri,
        description="kmeansVectorAttr",
        assetId=param["assetDir"] + param["KmeansVector"],
    )
    task_sample.start()
    return task_sample


def proportion_calc(param, asset_exists):
    """Create and export the proportion raster and sample table."""
    exists = asset_exists(param["assetDir"] + param["proportionName"])
    if exists:
        return

    proportion_attri = ee.FeatureCollection(param["assetDir"] + param["KmeansVector"])
    clusters_that_touch_0 = ee.Number(
        proportion_attri.filter(ee.Filter.And(ee.Filter.eq("label", 0), ee.Filter.eq("touch", 1))).size()
    )
    clusters_that_touch_1 = ee.Number(
        proportion_attri.filter(ee.Filter.And(ee.Filter.eq("label", 1), ee.Filter.eq("touch", 1))).size()
    )
    clusters_that_touch_2 = ee.Number(
        proportion_attri.filter(ee.Filter.And(ee.Filter.eq("label", 2), ee.Filter.eq("touch", 1))).size()
    )
    median_value = ee.Array(
        [ee.Number(clusters_that_touch_0), ee.Number(clusters_that_touch_1), ee.Number(clusters_that_touch_2)]
    ).reduce(ee.Reducer.median(), [0]).get([0])

    def add_proportions(feature):
        cluster = feature.get("label")
        clusters_that_touch = ee.Number(
            proportion_attri.filter(ee.Filter.And(ee.Filter.eq("label", cluster), ee.Filter.eq("touch", 1))).size()
        )
        bnet_value = ee.Algorithms.If(
            clusters_that_touch.gte(ee.Number(median_value)),
            3,
            ee.Algorithms.If(clusters_that_touch.eq(ee.Number(median_value)), 2, 1),
        )
        return feature.set("prop_count", clusters_that_touch).set("bnet", bnet_value)

    add_k_proportions = proportion_attri.map(add_proportions)
    feat_label = add_k_proportions.aggregate_array("label")
    feat_bnet = add_k_proportions.aggregate_array("bnet")
    feat_zip = feat_label.zip(feat_bnet).distinct().unzip()
    corrected_label = [str(int(num)) for num in feat_zip.get(0).getInfo()]
    corrected_bnet = feat_zip.get(1)
    diclist = ee.Dictionary.fromLists(corrected_label, corrected_bnet)

    kmeans = ee.Image(param["assetDir"] + param["kmeansName"]).rename(["kmeans_clusters"])

    def label_img_function(k):
        return kmeans.eq(ee.Number.parse(k)).multiply(ee.Number(diclist.get(k))).byte()

    label_img = diclist.keys().map(label_img_function)
    sample_img = ee.ImageCollection(label_img).sum().selfMask().rename(["label"])
    ref_img = ee.Image(param["assetDir"] + param["declineName"])
    ref_img = bnet.select_decline_predictor_bands(ref_img, param["target"], param["fit"], param["decline_path"]).addBands(kmeans).addBands(sample_img)

    sample = ref_img.stratifiedSample(
        numPoints=param["proportion_strat_sample_size"],
        classBand="label",
        region=param["aoi"],
        scale=param["pixel_scale"],
        tileScale=4,
        geometries=True,
    )

    task_sample = ee.batch.Export.table.toAsset(
        collection=sample,
        description=param["proportionName"] + "_sample",
        assetId=param["assetDir"] + param["proportionName"] + "_sample",
    )
    task_sample.start()

    task_proportion = ee.batch.Export.image.toAsset(
        image=sample_img,
        description=param["proportionName"],
        assetId=param["assetDir"] + param["proportionName"],
        region=param["aoi"].geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    task_proportion.start()
    return task_proportion


def predict(param, asset_exists):
    """Train the RF classifier and export the predicted image."""
    exists = asset_exists(param["assetDir"] + param["predicted"])
    if exists:
        return

    states = param["aoi"]
    decline = ee.Image(param["assetDir"] + param["declineName"])
    sample = ee.FeatureCollection(param["assetDir"] + param["proportionName"] + "_sample")

    refer_image = bnet.select_decline_predictor_bands(decline, param["target"], param["fit"], param["decline_path"])

    ref_bands = refer_image.bandNames()
    sample = sample.randomColumn()
    split = 0.70
    test = sample.filter(ee.Filter.gte("random", split))

    random_forest = ee.Classifier.smileRandomForest(500).train(
        features=test,
        classProperty="label",
        inputProperties=ref_bands,
    )

    rf_model = refer_image.classify(random_forest).selfMask().clip(states).rename(f"bugnet_{param['target']}")
    export_task = ee.batch.Export.image.toAsset(
        image=rf_model,
        description=param["predicted"],
        assetId=param["assetDir"] + param["predicted"],
        region=states.geometry(),
        scale=param["pixel_scale"],
        maxPixels=1e13,
    )
    export_task.start()
    return export_task
