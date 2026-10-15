"""Validate a GeoTIFF written by download_ee_raster.py against its Earth Engine asset.

Checks the grid (CRS, pixel size, origin, dimensions), data type, nodata, band
descriptions, and pixel values at random pixel centres. The values are read
from Earth Engine with reduceRegions, a different path from the download's
computePixels. Optionally (--counts) it compares per-band valid-pixel counts
with Earth Engine.

Usage:
  python tools/validate_ee_raster.py ASSET FILE.tif [--points 1000] [--counts] [--seed 1]
"""
import argparse
import json
import sys

import ee
import numpy as np
import rasterio

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from download_ee_raster import asset_grid  # noqa: E402


def ee_values(asset_id, crs, t, pixels, band_names, batch=500):
    """Asset values at pixel centres via reduceRegions; None where masked."""
    img = ee.Image(asset_id)
    out = []
    for i in range(0, len(pixels), batch):
        feats = []
        for k, (c, r) in enumerate(pixels[i:i + batch]):
            x = t[2] + (c + 0.5) * t[0]
            y = t[5] + (r + 0.5) * t[4]
            feats.append(ee.Feature(ee.Geometry.Point([x, y], crs), {"k": i + k}))
        fc = img.reduceRegions(ee.FeatureCollection(feats), ee.Reducer.first(), crs=crs, crsTransform=t)
        rows = fc.getInfo()["features"]
        rows.sort(key=lambda f: f["properties"]["k"])
        for f in rows:
            p = f["properties"]
            key = band_names if len(band_names) > 1 else ["first"]
            out.append([p.get(b) for b in key])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument("file")
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--counts", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    ee.Initialize(project=args.asset.split("/")[1])

    crs, t, width, height, band_names = asset_grid(args.asset)
    report = {"file": args.file.rsplit("/", 1)[-1], "asset": args.asset}
    with rasterio.open(args.file) as ds:
        col0 = round((ds.transform.c - t[2]) / t[0])
        row0 = round((ds.transform.f - t[5]) / t[4])
        report["grid"] = {
            "crs_file": ds.crs.to_string(), "crs_asset": crs,
            "pixel_size_matches": (ds.transform.a, ds.transform.e) == (t[0], t[4]),
            "origin_offset_from_asset_px": [col0, row0],
            "origin_on_asset_grid": ds.transform.c == t[2] + col0 * t[0] and ds.transform.f == t[5] + row0 * t[4],
            "size_file": [ds.width, ds.height], "size_asset": [width, height],
        }
        report["dtype"] = ds.dtypes[0]
        report["nodata"] = ds.nodata
        report["compression"] = ds.compression.name if ds.compression else None
        report["band_descriptions_match_asset"] = list(ds.descriptions) == band_names
        report["band_count"] = ds.count

        rng = np.random.default_rng(args.seed)
        pixels = list(zip(rng.integers(0, ds.width, args.points).tolist(),
                          rng.integers(0, ds.height, args.points).tolist()))
        local = [ds.read(window=((r, r + 1), (c, c + 1)))[:, 0, 0].tolist() for c, r in pixels]
        remote = ee_values(args.asset, crs, t, [(c + col0, r + row0) for c, r in pixels], band_names)
        mismatches, n_nodata, n_valid = [], 0, 0
        for (c, r), lv, rv in zip(pixels, local, remote):
            expected = [ds.nodata if v is None else v for v in rv]
            if expected != lv:
                mismatches.append({"col": c, "row": r, "file": lv[:6], "earth_engine": expected[:6]})
            if all(v is None for v in rv):
                n_nodata += 1
            else:
                n_valid += 1
        report["pixel_check"] = {"points": len(pixels), "valid_in_ee": n_valid, "masked_in_ee": n_nodata,
                                 "values_compared": len(pixels) * ds.count,
                                 "mismatching_points": len(mismatches), "examples": mismatches[:5]}

        if args.counts:
            local_counts = [int((ds.read(i) != ds.nodata).sum()) for i in range(1, ds.count + 1)]
            region = ee.Geometry.Rectangle(
                [t[2] + col0 * t[0], t[5] + (row0 + ds.height) * t[4],
                 t[2] + (col0 + ds.width) * t[0], t[5] + row0 * t[4]], crs, False)
            counts = ee.Image(args.asset).mask().gt(0).reduceRegion(
                ee.Reducer.sum().unweighted(), region, crs=crs, crsTransform=t, maxPixels=1e11, tileScale=4
            ).getInfo()
            ee_counts = [int(counts[b]) for b in band_names]
            report["valid_pixel_counts"] = {
                "bands_equal": sum(a == b for a, b in zip(local_counts, ee_counts)),
                "bands": len(band_names),
                "first_bands": list(zip(band_names, local_counts, ee_counts))[:4],
                "max_abs_difference": max(abs(a - b) for a, b in zip(local_counts, ee_counts)),
            }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
