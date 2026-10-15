"""Download an Earth Engine image asset to one GeoTIFF on the asset's own grid.

Pixels are fetched with ee.data.computePixels in fixed blocks of the asset's
native grid (same CRS, pixel size and origin), so nothing is resampled.
Each finished block is cached under <output>.blocks/, so an interrupted run
resumes where it stopped. When all blocks are present they are written to a
tiled, DEFLATE-compressed (lossless) GeoTIFF.

Masked pixels are set to --nodata on the server before download (computePixels
would otherwise fill them with the data type's minimum value).

Usage:
  python tools/download_ee_raster.py ASSET OUTPUT.tif --dtype int16 --nodata -32768
      [--window COL ROW WIDTH HEIGHT] [--block 512] [--workers 4] [--max-blocks N]
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window

MAX_REQUEST_BYTES = 48 * 1024 * 1024  # computePixels response limit


def asset_grid(asset_id):
    bands = ee.Image(asset_id).getInfo()["bands"]
    grids = {(b["crs"], tuple(b["crs_transform"]), tuple(b["dimensions"])) for b in bands}
    if len(grids) != 1:
        raise SystemExit(f"{asset_id}: bands are not on one grid: {grids}")
    crs, transform, (width, height) = grids.pop()
    return crs, list(transform), width, height, [b["id"] for b in bands]


def prepared_image(asset_id, dtype, nodata):
    img = ee.Image(asset_id)
    cast = {"int16": img.toInt16, "uint8": img.toUint8}[dtype]
    return cast().unmask(nodata, False)


def blocks(col0, row0, width, height, size):
    for r in range(row0, row0 + height, size):
        for c in range(col0, col0 + width, size):
            yield c, r, min(size, col0 + width - c), min(size, row0 + height - r)


def fetch_block(image, crs, t, block, path, retries=6):
    c, r, w, h = block
    grid = {
        "dimensions": {"width": w, "height": h},
        "affineTransform": {
            "scaleX": t[0], "shearX": t[1], "translateX": t[2] + c * t[0],
            "shearY": t[3], "scaleY": t[4], "translateY": t[5] + r * t[4],
        },
        "crsCode": crs,
    }
    for attempt in range(retries):
        try:
            arr = ee.data.computePixels(
                {"expression": image, "fileFormat": "NUMPY_NDARRAY", "grid": grid}
            )
            data = np.stack([arr[name] for name in arr.dtype.names])
            tmp = path + ".tmp.npz"
            np.savez_compressed(tmp, data=data)
            os.replace(tmp, path)
            return block
        except Exception as exc:  # network errors, EE rate limits, timeouts
            if attempt == retries - 1:
                raise
            wait = 10 * 2 ** attempt
            print(f"block {block}: {type(exc).__name__}: {exc}; retry in {wait}s", flush=True)
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("asset")
    ap.add_argument("output")
    ap.add_argument("--dtype", required=True, choices=["int16", "uint8"])
    ap.add_argument("--nodata", required=True, type=int)
    ap.add_argument("--window", nargs=4, type=int, metavar=("COL", "ROW", "WIDTH", "HEIGHT"))
    ap.add_argument("--block", type=int, default=512)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-blocks", type=int, help="stop after fetching this many new blocks (for testing resume)")
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    ee.Initialize(project=args.project or args.asset.split("/")[1])
    crs, t, width, height, band_names = asset_grid(args.asset)
    col0, row0, w, h = args.window or (0, 0, width, height)
    itemsize = np.dtype(args.dtype).itemsize
    if args.block * args.block * len(band_names) * itemsize > MAX_REQUEST_BYTES:
        raise SystemExit(f"--block {args.block} exceeds the computePixels size limit for {len(band_names)} bands")

    cache = args.output + ".blocks"
    os.makedirs(cache, exist_ok=True)
    job = {"asset": args.asset, "crs": crs, "transform": t, "window": [col0, row0, w, h],
           "dtype": args.dtype, "nodata": args.nodata, "block": args.block, "bands": band_names}
    job_file = os.path.join(cache, "job.json")
    if os.path.exists(job_file):
        with open(job_file) as f:
            if json.load(f) != job:
                raise SystemExit(f"{cache} was created for different settings; use a new output path")
    else:
        with open(job_file, "w") as f:
            json.dump(job, f, indent=1)

    image = prepared_image(args.asset, args.dtype, args.nodata)
    all_blocks = list(blocks(col0, row0, w, h, args.block))
    path_of = lambda b: os.path.join(cache, f"c{b[0]}_r{b[1]}.npz")
    todo = [b for b in all_blocks if not os.path.exists(path_of(b))]
    print(f"{args.asset}: {len(band_names)} bands, window {w}x{h}, {len(all_blocks)} blocks, "
          f"{len(all_blocks) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    if args.max_blocks is not None:
        todo = todo[: args.max_blocks]

    done = 0
    with ThreadPoolExecutor(args.workers) as pool:
        for fut in as_completed([pool.submit(fetch_block, image, crs, t, b, path_of(b)) for b in todo]):
            fut.result()
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"  fetched {done}/{len(todo)}", flush=True)

    missing = [b for b in all_blocks if not os.path.exists(path_of(b))]
    if missing:
        print(f"stopped with {len(missing)} blocks still to fetch; rerun to resume")
        return 1

    transform = Affine(t[0], t[1], t[2] + col0 * t[0], t[3], t[4], t[5] + row0 * t[4])
    tmp_out = args.output + ".partial.tif"
    profile = dict(driver="GTiff", width=w, height=h, count=len(band_names), dtype=args.dtype,
                   crs=crs, transform=transform, nodata=args.nodata, tiled=True,
                   blockxsize=256, blockysize=256, compress="deflate", predictor=2,
                   zlevel=6, BIGTIFF="IF_SAFER", interleave="band")
    with rasterio.open(tmp_out, "w", **profile) as dst:
        for i, name in enumerate(band_names, start=1):
            dst.set_band_description(i, name)
        dst.update_tags(source_asset=args.asset, nodata=str(args.nodata),
                        grid_origin_col=str(col0), grid_origin_row=str(row0))
        for b in all_blocks:
            data = np.load(path_of(b))["data"]
            dst.write(data, window=Window(b[0] - col0, b[1] - row0, b[2], b[3]))
    os.replace(tmp_out, args.output)
    print(f"wrote {args.output} ({os.path.getsize(args.output) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
