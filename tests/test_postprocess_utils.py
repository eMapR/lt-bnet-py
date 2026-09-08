from unittest.mock import patch

import postprocess_utils as pu


def make_param(buckets=3):
    return {
        "assetDir": "projects/proj/assets/2026-vX/",
        "bnet_buffered_polygons": "bugnet_polygons_buffered_2026_mag50_10mmu",
        "bnet_polygonized": "bugnet_polygons_2026_mag50_10mmu",
        "bnet_buffer": 60,
        "bnet_polygon_mmu": 10,
        "buckets": buckets,
    }


def make_asset_exists(existing_ids):
    return lambda asset_id: asset_id in existing_ids


class TestBufferBnetPolygonsResume:
    @patch("postprocess_utils.ee")
    def test_existing_shard_is_skipped(self, mock_ee, capsys):
        param = make_param(buckets=1)
        shard_id = f"{param['assetDir']}{param['bnet_buffered_polygons']}_shard_000"
        asset_exists = make_asset_exists({shard_id})

        tasks, asset_ids = pu.buffer_bnet_polygons(param, asset_exists)

        assert tasks == []
        assert asset_ids == [shard_id]
        mock_ee.batch.Export.table.toAsset.assert_not_called()
        assert f"reusing: {shard_id}" in capsys.readouterr().out

    @patch("postprocess_utils.ee")
    def test_missing_shard_is_submitted(self, mock_ee):
        mock_ee.Number.return_value.getInfo.return_value = 5
        param = make_param(buckets=1)
        shard_id = f"{param['assetDir']}{param['bnet_buffered_polygons']}_shard_000"
        asset_exists = make_asset_exists(set())

        tasks, asset_ids = pu.buffer_bnet_polygons(param, asset_exists)

        assert asset_ids == [shard_id]
        mock_ee.batch.Export.table.toAsset.assert_called_once()
        assert mock_ee.batch.Export.table.toAsset.call_args.kwargs["assetId"] == shard_id
        started_task = mock_ee.batch.Export.table.toAsset.return_value
        started_task.start.assert_called_once()
        assert tasks == [started_task]

    @patch("postprocess_utils.ee")
    def test_mixed_existing_and_missing_resumes_correctly(self, mock_ee, capsys):
        mock_ee.Number.return_value.getInfo.return_value = 5
        param = make_param(buckets=3)
        base = f"{param['assetDir']}{param['bnet_buffered_polygons']}"
        shard_ids = [f"{base}_shard_{i:03d}" for i in range(3)]
        # buckets 0 and 2 already completed; bucket 1 is the only one missing.
        asset_exists = make_asset_exists({shard_ids[0], shard_ids[2]})

        tasks, asset_ids = pu.buffer_bnet_polygons(param, asset_exists)

        assert asset_ids == shard_ids
        mock_ee.batch.Export.table.toAsset.assert_called_once()
        assert mock_ee.batch.Export.table.toAsset.call_args.kwargs["assetId"] == shard_ids[1]
        assert len(tasks) == 1

        out = capsys.readouterr().out
        assert f"reusing: {shard_ids[0]}" in out
        assert f"reusing: {shard_ids[2]}" in out
        assert f"reusing: {shard_ids[1]}" not in out
