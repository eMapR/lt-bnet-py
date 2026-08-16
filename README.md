# BugNet (lt-bnet-py)

BugNet is a Google Earth Engine (GEE) pipeline that maps forest disturbance
caused by insects and disease. It combines Landsat time series, LandTrendr
temporal segmentation (via the `ltgee` package), and a Random Forest
classifier to distinguish subtle, non-stand-replacing decline (bugs/disease)
from stand-replacing disturbance (fire, harvest) across a set of Pacific
Northwest ecoregions.

For each ecoregion/year/version run, the pipeline builds fitted spectral
imagery, detects change, attributes disturbance polygons against reference
data, classifies and filters them, derives a forest mask, computes a decline
score, clusters it (SNIC + KMeans), samples training points against ADS
(Aerial Detection Survey) data, trains/​applies a classifier, and exports
final polygons — all as GEE assets.

## Repo layout

| Path | Purpose |
|---|---|
| `main.py` | CLI entry point. Loads a parameter file, initializes EE, presents the mode menu, and wires the stage functions (from `disturbance_utils.py`/`modeling_utils.py`/`postprocess_utils.py`) into `build_mode_dependencies()` for `pipeline_modes.py` to call. |
| `disturbance_utils.py` | Fitted-imagery and change-imagery creation (training + predictor), disturbance-polygon vectorization (with grid/bucket fallback splitting for large AOIs), attribution, and the classify → filter → buffer → rasterize chain. |
| `pipeline_modes.py` | Orchestrates the stage functions into `run_mode_1` (full training + predictor run) and `run_mode_2` (predictor-only run against an existing trained classifier), plus `apply_public_read_acl`. |
| `bnet.py` | Core GEE logic: fitted-stack construction, change vectorization, attribution against reference/cMonster data, classifier training/inference, decline scoring (LTSD/SNIC), masks, geometry helpers, asset cleanup. |
| `modeling_utils.py` | Forest mask, SNIC/decline image, KMeans sampling/clustering, proportion calc, and final `predict()` (Random Forest classify) stage functions. |
| `postprocess_utils.py` | Polygonizing the predicted raster, zonal stats, area/percent-affected fields, buffering bnet polygons (with bucketed reclassification fallback), reclassification prompts. |
| `export_utils.py` | Interactive/​default export of finished assets to Google Drive or Cloud Storage; SHP-safe field-name sanitizing. |
| `cli_utils.py` | Parameter-file loading (`load_parameters`), `normalize_parameters` (derives `assetDir`/`sharedAssetDir`/versioning from a param file), the mode-selection prompt (`gui`), and `walk_assets`. |
| `batch_bugnet.sh` | Batch-generates per-year/per-variant parameter files from a template and runs `main.py` across an ecoregion × region × year × magnitude × MMU sweep, with bounded parallelism. |
| `file-manager.py` | Standalone post-export script: organizes downloaded/exported files into a folder structure, merges chunked GeoTIFFs with `gdal_merge.py`, and writes metadata sidecars. |
| `trashGEE.py` | Standalone CLI to recursively delete a GEE asset subtree (dry-run by default). |
| `templates/v3/`, `templates/v1/` | Canonical per-ecoregion parameter templates used by `batch_bugnet.sh` to materialize run configs. `v3/` is the LTSD decline path; `v1/` (coast-range, williams-sound, columbia-mts) is the SNIC path - see `docs/config-layout.md`. |
| `run_configs/` | Generated, run-specific parameter files (by year/region/version) - what `batch_bugnet.sh` writes and `main.py` actually runs. Was named `params_new/` before 2026-08-15. |
| `legacy_parameters/` | Retired, hand-authored parameter files from before `batch_bugnet.sh` existed - some predate the current schema and won't load. Was named `parameters/` before 2026-08-15. See `docs/config-layout.md`. |
| `logs/` | Historical run logs (text dumps of stdout). |
| `lt-bnet-py.yml` | Conda environment spec (Python 3.12, Earth Engine API, geopandas, rasterio, scikit-learn, etc.). |

## Setup

```bash
conda env create -f lt-bnet-py.yml
conda activate lt-bnet-py
python -c "import ee; ee.Authenticate()"   # one-time GEE auth
```

## Parameter reference

`docs/parameter_reference_template.py` documents every key a parameter
file's `param` dict can/must define - what it controls, which pipeline
stage reads it, and how it interacts with `configName` (which picks
between the SNIC-based and LTSD-based decline paths). This file is
documentation, not a runnable config - see `docs/config-layout.md` for
where the templates/configs you actually run from live
(`templates/`/`run_configs/`, gitignored) and how they relate.

## Running a single job

```bash
python main.py <path-to-parameter-file.py>
```

The parameter file must define a module-level `param` dict (see
`templates/v3/*-template.py` for the schema). `main.py` normalizes it via
`cli_utils.normalize_parameters`, which derives:

- `assetDir` — run-specific output folder: `projects/<project>/assets/<target>-v<version>/`
- `sharedAssetDir` — folder for assets reused across variants of the same
  ecoregion/year (fitted predictor imagery, change image, forest mask, etc.),
  keyed off `shared_version` instead of `version`
- `logic_version`, `configName`

After parameters load, you're prompted for a mode:

1. **Run bugnet** — full pipeline (`run_mode_1`): builds training *and*
   predictor assets, trains the classifier from scratch.
2. **Run bugnet no training** — predictor-only pipeline (`run_mode_2`):
   reuses an already-trained classifier's shared assets, useful for
   sweeping magnitude/MMU variants without rebuilding training data.
3. **Export** — push finished assets to Drive/Cloud Storage
   (`export_utils.export_assets`).
4. **Clean** — delete all assets under `assetDir`.
5. **Apply public ACL** — recursively mark assets under `assetDir` as
   publicly readable.

Every stage function checks whether its output asset already exists before
recomputing, so re-running a param file resumes from where it left off.

## Batch sweeps

`batch_bugnet.sh` drives many runs at once — ecoregions × regions × years ×
disturbance-magnitude thresholds (`MAGS`) × minimum-mapping-units (`MMUS`) —
by materializing parameter files from a template and invoking `main.py`
(feeding `2` to stdin to select predictor-only mode). It seeds the shared
predictor assets once per ecoregion/year (`ensure_shared_predictor_assets`)
before fanning out the MAG/MMU variants in parallel, bounded by `--jobs`.

```bash
./batch_bugnet.sh --ecos williams-sound --regions r6 --years 2025 --dry-run
```

See the flags block at the top of the script for all overrides
(`--version`, `--shared-version`, `--templates-dir`, `--param-root`, etc.).
`--decline-path {snic,ltsd}` picks the decline algorithm explicitly,
independent of `--version` (which then only labels the run-variant) -
omit it to keep the legacy behavior of deriving the decline path from
`--version`'s logic-version digit. See `docs/config-layout.md`.

## Post-processing

- `file-manager.py --src <exported_dir> --dest <organized_dir>` sorts a raw
  export dump into a per-run folder tree, merges chunked GeoTIFFs, and
  writes `METADATA.txt` sidecars.
- `trashGEE.py --root <asset_path> [--delete] [--delete-containers]` removes
  a GEE asset subtree; dry-run unless `--delete` is passed.

## Testing

`tests/` covers the pure, non-GEE helper functions — string/regex parsing
in `export_utils.py` (`remove_duplicate_substrings`,
`_sanitize_shapefile_field_name`) and `file-manager.py` (stem parsing,
chunk-suffix detection, `unique_path`'s collision handling). Anything that
builds an `ee.*` object (e.g. `disturbance_utils.grid_over_feature`) is out
of scope here — it's a server-side computation graph, not a pure function,
and would need live GEE credentials or heavy mocking to exercise for real.

```bash
conda activate lt-bnet-py
pip install pytest   # not in lt-bnet-py.yml yet
pytest
```

## Cleanup notes (for the upcoming pass)

Observations from the initial review, to work through incrementally:

- **Git hygiene**: `__pycache__/*.pyc` (4 files) and the legacy
  `legacy_parameters/` tree (477 files, named `parameters/` before
  2026-08-15) were tracked in git despite being covered by `.gitignore` —
  they were committed before the ignore rules existed. Already untracked
  via `git rm --cached` (see `docs/config-layout.md` for how this tree
  relates to `run_configs/`). `logs/` (8 files) is tracked too and is pure
  run output.
- **Untracked root-level `.log` files** (`case_study*.log`,
  `coast_range_2025_v1.log`, `williams_sound.log`) are batch-run output
  redirected to the repo root instead of `logs/`. `.gitignore` doesn't
  currently exclude `*.log`, so these show up as untracked clutter.
- **`main.py` is thinned out** (758 → ~227 lines): the per-stage pipeline
  functions now live in `disturbance_utils.py`, `modeling_utils.py`, and
  `postprocess_utils.py`; `main.py` is down to `wait_for_task`, the
  asset-folder/asset-exists/delete helpers, `build_mode_dependencies()`,
  and `main()`.
- **Mixed indentation**: `bnet.py` still mixes tabs and spaces
  between functions (visible as inconsistent indent width when viewing
  diffs) — worth a pass with a formatter.
- **`bnet.py` scope**: at ~1000 lines it mixes GEE compositing, ADS/agent
  filtering, classifier training, geometry helpers, and image renaming —
  a good next target for splitting once `main.py` is thinned out.
- **Duplicate asset-deletion logic**: `main.py:delete_assets` and
  `bnet.list_and_delete_assets` overlap with `trashGEE.py`; worth picking
  one implementation.
- **No automated tests** — all validation today is running an actual GEE
  job end-to-end. Even lightweight unit tests around the pure-Python
  helpers (`cli_utils.normalize_parameters`, filename/regex helpers in
  `export_utils.py`, `file-manager.py` filename parsing) would help catch
  regressions like the ones the `sharedAssetDir` consistency pass and the
  `main.py` extraction just fixed by hand.
- **`file-manager.py`** uses a hyphenated filename (not importable as a
  module) — fine as a standalone script, but worth renaming to
  `file_manager.py` if it's ever imported elsewhere.
