from ltgee import LandTrendr


def apply_public_read_acl(param, ee_module, walk_assets):
    """Make every asset below the configured asset directory publicly readable."""
    parent = param["assetDir"]
    acl_update = {"all_users_can_read": True}
    for asset in walk_assets(parent):
        print("Updating:", asset)
        ee_module.data.setAssetAcl(asset, acl_update)


def run_mode_1(param, deps):
    """Run the full training + predictor workflow."""
    wait_for_task = deps["wait_for_task"]
    delete_assets = deps["delete_assets"]
    asset_exists = deps["asset_exists"]
    create_training_fitted_imagery = deps["CreateTrainingFittedImagery"]
    create_predictor_fitted_imagery = deps["CreatePredictorFittedImagery"]
    create_training_change_imagery = deps["CreateTrainingChangeImagery"]
    create_predictor_change_imagery = deps["CreatePredictorChangeImagery"]
    create_training_disturbance_polygons = deps["CreateTrainingDisturbancePolygons"]
    create_predictor_disturbance_polygons = deps["CreatePredictorDisturbancePolygons"]
    merge_selected_feature_collections = deps["merge_selected_feature_collections"]
    attribute_training_polygons = deps["attributeTrainingPolygons"]
    attribute_predictor_polygons = deps["attributePredictorPolygons"]
    classify_polygons = deps["classify_polygons"]
    filter_classes = deps["filter_classes"]
    buffer_classed_polygons = deps["buffer_classed_polygons"]
    rasterize_classed_polygons = deps["rasterize_classed_polygons"]
    create_forest_mask = deps["CreateForestMask"]
    declining_ltsd = deps["DecliningLTSD"]
    snic = deps["SNIC"]
    declining_snic = deps["DecliningSNIC"]
    build_kmeans_sample = deps["buildKMeansSample"]
    kmeans_image = deps["kMeansImage"]
    kmeans_ads_sample = deps["kMeansProporitonsADSsample"]
    proportion_calc = deps["proportionCalc"]
    predict = deps["predict"]
    polygonize_bnet = deps["polygonize_bnet"]
    buffer_bnet_polygons = deps["buffer_bnet_polygons"]
    dict_to_feature_collection = deps["dict_to_feature_collection"]

    lt = LandTrendr(**param["lt_params"])

    task1 = create_training_fitted_imagery(lt, param)
    task2 = create_predictor_fitted_imagery(lt, param)
    task3 = create_training_change_imagery(lt, param)
    task4 = create_predictor_change_imagery(lt, param)
    wait_for_task(task1)
    wait_for_task(task2)
    wait_for_task(task3)
    wait_for_task(task4)

    task5 = create_training_disturbance_polygons(param)
    res6 = create_predictor_disturbance_polygons(param)
    wait_for_task(task5)

    if res6 != 0:
        tasks6 = [task for task in res6.get("tasks", []) if task is not None]
        for task in tasks6:
            wait_for_task(task)

        asset_paths = res6.get("asset_paths", [])
        if len(asset_paths) > 1:
            base_name = param["disturbance_polygons_predictor"]
            asset_dir = param.get("sharedAssetDir", param["assetDir"])
            merged_name = f"{base_name}"
            merged_task = merge_selected_feature_collections(
                asset_dir,
                asset_paths,
                merged_name,
                "merged predictor shards",
            )
            wait_for_task(merged_task)

            def looks_like_shard(asset_id: str) -> bool:
                name = asset_id.split("/")[-1]
                if name == merged_name:
                    return False
                if name.startswith(f"{base_name}_grid_"):
                    return False
                return name.startswith(base_name + "_")

            candidates = res6["created_asset_paths"] if res6["created_asset_paths"] else asset_paths
            to_delete = [asset_id for asset_id in candidates if looks_like_shard(asset_id)]
            delete_assets(to_delete, dry_run=False, pause_sec=0.2)

    task7 = attribute_training_polygons(param)
    task8 = attribute_predictor_polygons(param)
    wait_for_task(task7)
    wait_for_task(task8)

    task9 = classify_polygons(param)
    wait_for_task(task9)

    task10 = filter_classes(param)
    wait_for_task(task10)

    task11 = buffer_classed_polygons(param)
    wait_for_task(task11)

    task12 = rasterize_classed_polygons(param)
    wait_for_task(task12)

    task_mask = create_forest_mask(param)
    wait_for_task(task_mask)

    if param["decline_path"] == "ltsd":
        task_decline = declining_ltsd(param)
        wait_for_task(task_decline)
    else:
        task_snic = snic(param)
        wait_for_task(task_snic)

        task_decline_snic = declining_snic(param)
        wait_for_task(task_decline_snic)

    build_kmeans_sample(param)

    task_kmeans = kmeans_image(param)
    wait_for_task(task_kmeans)

    task_sample = kmeans_ads_sample(param)
    wait_for_task(task_sample)

    task_proportion = proportion_calc(param)
    wait_for_task(task_proportion)

    task_predict = predict(param)
    wait_for_task(task_predict)

    task_poly = polygonize_bnet(param)
    wait_for_task(task_poly)

    task_buffer = buffer_bnet_polygons(param)
    wait_for_task(task_buffer)

    task_params = dict_to_feature_collection(param, asset_exists)
    wait_for_task(task_params)


def run_mode_2(param, deps):
    """Run the predictor-only workflow."""
    wait_for_task = deps["wait_for_task"]
    delete_assets = deps["delete_assets"]
    asset_exists = deps["asset_exists"]
    walk_assets = deps["walk_assets"]
    ee_module = deps["ee"]
    create_predictor_fitted_imagery = deps["CreatePredictorFittedImagery"]
    create_predictor_change_imagery = deps["CreatePredictorChangeImagery"]
    create_predictor_disturbance_polygons = deps["CreatePredictorDisturbancePolygons"]
    merge_selected_feature_collections = deps["merge_selected_feature_collections"]
    attribute_predictor_polygons = deps["attributePredictorPolygons"]
    classify_polygons = deps["classify_polygons"]
    filter_classes = deps["filter_classes"]
    buffer_classed_polygons = deps["buffer_classed_polygons"]
    rasterize_classed_polygons = deps["rasterize_classed_polygons"]
    create_forest_mask_vis = deps["CreateForestMaskVis"]
    create_forest_mask = deps["CreateForestMask"]
    declining_ltsd = deps["DecliningLTSD"]
    snic = deps["SNIC"]
    declining_snic = deps["DecliningSNIC"]
    build_kmeans_sample = deps["buildKMeansSample"]
    kmeans_image = deps["kMeansImage"]
    kmeans_ads_sample = deps["kMeansProporitonsADSsample"]
    proportion_calc = deps["proportionCalc"]
    predict = deps["predict"]
    polygonize_bnet = deps["polygonize_bnet"]
    buffer_bnet_polygons = deps["buffer_bnet_polygons"]
    merge_buffer_buckets_and_finish = deps["merge_buffer_buckets_and_finish"]
    get_unique_pixel_values = deps["get_unique_pixel_values"]
    prompt_reclassification_mapping = deps["prompt_reclassification_mapping"]
    reclassify_image = deps["reclassify_image"]
    dict_to_feature_collection = deps["dict_to_feature_collection"]

    lt = LandTrendr(**param["lt_params"])

    task2 = create_predictor_fitted_imagery(lt, param)
    task4 = create_predictor_change_imagery(lt, param)
    wait_for_task(task2)
    wait_for_task(task4)

    res = create_predictor_disturbance_polygons(param, param["polygon-split-method"])
    if res != 0:
        tasks = [task for task in res.get("tasks", []) if task is not None]
        for task in tasks:
            wait_for_task(task)

        asset_paths = res.get("asset_paths", [])
        if len(asset_paths) > 1:
            base_name = param["disturbance_polygons_predictor"]
            asset_dir = param.get("sharedAssetDir", param["assetDir"])
            merged_name = f"{base_name}"
            merged_task = merge_selected_feature_collections(
                asset_dir,
                asset_paths,
                merged_name,
                "merged predictor shards",
            )
            wait_for_task(merged_task)

            def looks_like_shard(asset_id: str) -> bool:
                name = asset_id.split("/")[-1]
                if name == merged_name:
                    return False
                if name.startswith(f"{base_name}_grid_"):
                    return False
                return name.startswith(base_name + "_")

            candidates = res["created_asset_paths"] if res["created_asset_paths"] else asset_paths
            to_delete = [asset_id for asset_id in candidates if looks_like_shard(asset_id)]
            delete_assets(to_delete, dry_run=False, pause_sec=0.2)

    task8 = attribute_predictor_polygons(param)
    wait_for_task(task8)

    task9 = classify_polygons(param)
    wait_for_task(task9)

    task10 = filter_classes(param)
    wait_for_task(task10)

    task11 = buffer_classed_polygons(param)
    wait_for_task(task11)

    task12 = rasterize_classed_polygons(param)
    wait_for_task(task12)

    create_forest_mask_vis(param)
    task_mask = create_forest_mask(param)
    wait_for_task(task_mask)

    if param["decline_path"] == "ltsd":
        task_decline = declining_ltsd(param)
        wait_for_task(task_decline)
    else:
        task_snic = snic(param)
        wait_for_task(task_snic)

        task_decline_snic = declining_snic(param)
        wait_for_task(task_decline_snic)

    build_kmeans_sample(param)
    task_kmeans = kmeans_image(param)
    wait_for_task(task_kmeans)

    if param["ADS_path"]["on"]:
        task_sample = kmeans_ads_sample(param)
        wait_for_task(task_sample)

        task_proportion = proportion_calc(param)
        wait_for_task(task_proportion)

        task_predict = predict(param)
        wait_for_task(task_predict)

        task_poly = polygonize_bnet(param)
        wait_for_task(task_poly)

        task_buffer, assets_ids = buffer_bnet_polygons(param)
        wait_for_task(task_buffer)

        task_buffer2 = merge_buffer_buckets_and_finish(param, assets_ids)
        wait_for_task(task_buffer2)

        task_params = dict_to_feature_collection(param, asset_exists)
        wait_for_task(task_params)
        return

    unique_vals = get_unique_pixel_values(param)
    if unique_vals:
        from_vals, to_vals = prompt_reclassification_mapping(unique_vals)
        task_p = reclassify_image(param, from_vals, to_vals)
        wait_for_task(task_p)

        task_poly = polygonize_bnet(param)
        wait_for_task(task_poly)

    task_poly = polygonize_bnet(param)
    wait_for_task(task_poly)

    task_buffer, assets_ids = buffer_bnet_polygons(param)
    if isinstance(task_buffer, list):
        for task in task_buffer:
            wait_for_task(task)

        task_buffer2 = merge_buffer_buckets_and_finish(param, assets_ids)
        wait_for_task(task_buffer2)
        delete_assets(assets_ids, dry_run=False)

    exists = asset_exists(param["assetDir"] + param["bnet_buffered_polygons"])
    if not exists:
        print(1)

    task_params = dict_to_feature_collection(param, asset_exists)
    wait_for_task(task_params)
    apply_public_read_acl(param, ee_module, walk_assets)
