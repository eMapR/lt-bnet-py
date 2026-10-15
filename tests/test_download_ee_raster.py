import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import download_ee_raster as dl  # noqa: E402

GRID = ("EPSG:4326", [0.1, 0, -120.0, 0, -0.1, 49.0], 10, 7, ["b1", "b2"])


class TestBlocks:
    @pytest.mark.parametrize("window,size", [((0, 0, 10, 7), 4), ((3, 2, 5, 4), 2), ((0, 0, 4, 4), 4)])
    def test_blocks_tile_window_exactly_once(self, window, size):
        col0, row0, w, h = window
        cover = np.zeros((row0 + h, col0 + w), dtype=int)
        for c, r, bw, bh in dl.blocks(col0, row0, w, h, size):
            assert bw <= size and bh <= size
            cover[r:r + bh, c:c + bw] += 1
        assert (cover[row0:, col0:] == 1).all()
        assert cover.sum() == w * h


def run_main(tmp_path, *extra):
    out = tmp_path / "out.tif"
    argv = ["download_ee_raster.py", "projects/p/assets/x", str(out), "--dtype", "int16", "--nodata", "-32768", *extra]
    with patch.object(sys, "argv", argv), patch.object(dl, "ee"), \
            patch.object(dl, "asset_grid", return_value=GRID), \
            patch.object(dl, "fetch_block") as fetch:
        return dl.main(), out, fetch


class TestMain:
    def test_rejects_block_over_request_limit(self, tmp_path):
        with pytest.raises(SystemExit, match="size limit"):
            run_main(tmp_path, "--block", "4096")

    def test_max_blocks_stops_and_reports_missing(self, tmp_path, capsys):
        rc, out, fetch = run_main(tmp_path, "--block", "4", "--max-blocks", "1")
        assert rc == 1
        assert fetch.call_count == 1
        assert "rerun to resume" in capsys.readouterr().out
        assert not out.exists()

    def test_cached_blocks_are_not_refetched(self, tmp_path):
        run_main(tmp_path, "--block", "4", "--max-blocks", "0")
        cache = tmp_path / "out.tif.blocks"
        np.savez_compressed(cache / "c0_r0.npz", data=np.zeros((2, 4, 4), dtype="int16"))
        rc, _, fetch = run_main(tmp_path, "--block", "4", "--max-blocks", "10")
        fetched = {call.args[3] for call in fetch.call_args_list}
        assert (0, 0, 4, 4) not in fetched
        assert len(fetched) == 5  # 3 x 2 blocks, one cached

    def test_changed_settings_refuse_existing_cache(self, tmp_path):
        run_main(tmp_path, "--block", "4", "--max-blocks", "0")
        job = json.loads((tmp_path / "out.tif.blocks" / "job.json").read_text())
        assert job["nodata"] == -32768
        with pytest.raises(SystemExit, match="different settings"):
            run_main(tmp_path, "--block", "2", "--max-blocks", "0")
