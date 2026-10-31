# BugNet (lt-bnet-py)

BugNet maps gradual forest decline, the slow canopy loss caused by insects
and disease, from the Landsat time series in Google Earth Engine (GEE). It
fits each pixel's history with LandTrendr (via the `ltgee` package), finds
pixels whose condition has been declining over recent years, groups them
into classes, and turns them into polygons. Abrupt, high-magnitude
disturbances such as fire, harvest and development are identified by a
Random Forest classifier and kept out of the decline map.

The products are made per region and survey year: polygons that follow the
USFS Insect and Disease Survey (IDS) schema, plus rasters of the fitted
time series, the forest mask and the decline classes. The 2026 products
(v2026-2) cover eight USFS Region 6 ecoregions (Oregon and Washington) and
nine Region 10 (Alaska) basins.

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install](#install)
- [Configure a run](#configure-a-run)
- [Run and resume](#run-and-resume)
- [Make a deliverable](#make-a-deliverable)
- [Earth Engine inputs](#earth-engine-inputs)
- [Tests](#tests)
- [Repo layout](#repo-layout)

## How it works

Every stage writes a GEE asset into the run's folder,
`projects/<project>/assets/<target>-v<version>/`. Asset names start with
the stage letter:

| Stage | Assets | What it does |
|---|---|---|
| A | `A_predictor_fitted_img_*`, `A_predictor_change_img_*` | Annual Landsat composites (July 1 to the composite end date), LandTrendr fit, and the greatest recent loss per pixel |
| B | `B1_*`, `B2_*` | Polygons of abrupt, high-magnitude change, with the attributes the classifier uses |
| C | `C1_*` to `C4_*` | Random Forest labels for those polygons (fire, harvest, insect, ...); the labels to exclude are buffered and rasterized |
| D | `D_bugnet_forest_mask_*` | Forest mask: forest land, minus the excluded patches and fire perimeters (MTBS, optionally WFIGS) |
| Decline | `Decline_*` | Forest pixels whose condition declines persistently over recent years |
| KMeans | `KMeans_*` | Declining pixels grouped into classes (3 by default) |
| Final | `labeled_*`, `bugnet_polygons_*`, `bugnet_polygons_buffered_*` | The class raster, the detected patches, and the buffered polygons with IDS attributes |
| Records | `_run_manifest`, `*_parameter_file` | The run's settings, stamped at startup and at the end |

## Requirements

- A Google Earth Engine account and a Cloud project registered for Earth
  Engine. Noncommercial projects get a monthly compute quota. A whole region
  takes from a few hours to several days, and most of that is stage A.
- Read access to the Earth Engine inputs listed under
  [Earth Engine inputs](#earth-engine-inputs). Some are lab assets that
  aren't public.
- Conda. `lt-bnet-py.yml` is pinned for Linux x86-64; on other platforms,
  install the same packages without the build strings.

## Install

```bash
git clone https://github.com/eMapR/lt-bnet-py.git
cd lt-bnet-py
conda env create -f lt-bnet-py.yml
conda activate lt-bnet-py
earthengine authenticate          # once per machine
python -m pytest -q               # optional check that the install works
```

## Configure a run

A run is described by a Python file that defines a `param` dict. Start from
the template used for the 2026 products:

```bash
mkdir -p bugnet/run_configs/my-region-bugnet-2026-v2
cp bugnet/templates/v2/region-template.py \
   bugnet/run_configs/my-region-bugnet-2026-v2/my-region-bugnet-2026-v2-config.py
```

Then edit every line marked `CHANGE ME`: the Earth Engine project, the
years, the area of interest, the composite end date, `study_region`
(`"CONUS"` or `"AK"`) and the training polygons. `bugnet/run_configs/` is
gitignored, so your configs stay local.

Settings you are most likely to change:

| Key | Meaning |
|---|---|
| `project_name` | Project that holds the assets; also names the run |
| `compute_project` | Optional: project whose Earth Engine quota does the work (assets still go to `project_name`) |
| `aoi` | Area of interest (an `ee.FeatureCollection`) |
| `composite_params['end_date']` | End of each year's July 1 composite window |
| `change_params['mag']` | Minimum loss magnitude for an abrupt disturbance (250 in 2026) |
| `fire_mask_source` | `'mtbs'` or `'mtbs_wfigs'` (WFIGS adds recent fires MTBS hasn't published) |
| `exclusion_classes` | Classifier labels masked before decline detection; unset = fire, harvest and development; `[]` = none |
| `bnet_polygon_mmu`, `bnet_buffer` | Minimum polygon size (pixels) and buffer (meters) |

Every key is documented in `docs/parameter_reference_template.py`.
`docs/config-layout.md` explains the older `v1`/`v3` templates and the
`batch_bugnet.sh` sweep tool, which were used for the 2025 products.

## Run and resume

```bash
mkdir -p logs
echo 2 | python bugnet/main.py bugnet/run_configs/my-region-bugnet-2026-v2/my-region-bugnet-2026-v2-config.py \
  2>&1 | tee logs/my-region-2026-v2.log
```

`main.py` asks for a mode; `echo 2` answers it:

1. Full run, including building training polygons (needs the cMonster
   labeling raster; see below).
2. Run without building training (uses existing training polygons). All
   2026 products were made this way.
3. Export assets to Google Drive or Cloud Storage (older export path; see
   [Make a deliverable](#make-a-deliverable) for the current one).
4. Delete the assets in the run's folder.

When a run finishes, every asset in its folder is made publicly readable.

**Resuming.** Each stage skips its output if the asset already exists, so
rerunning the same command picks up where a run stopped. It only sees
*finished* assets, though: if the run's Earth Engine tasks are still
pending or running, relaunching submits duplicates. Check first:

```bash
python tools/active_tasks.py <config>
```

Long runs should go on a server under `tmux`, not a laptop; a dropped
connection kills the local process (the Earth Engine tasks keep running).

## Make a deliverable

After a run, three steps turn its assets into a delivery folder:

1. **Correct the polygon attributes.** Writes
   `<bnet_buffered_polygons>_corrected` next to the original, which is never
   modified. It recalculates acreage in an equal-area projection, sets the
   IDS field values and restores `bnet_label`.

   ```bash
   python tools/correct_polygon_schema.py <config> submit     # starts the export
   python tools/correct_polygon_schema.py <config> validate   # after it finishes
   python tools/correct_polygon_schema.py <config> annotate   # records provenance on the asset
   ```

2. **Build the folder.** Downloads and checks the GeoPackage, the four
   GeoTIFFs and the parameter CSV, then writes a README with a data
   dictionary and validation reports. Each step checks its own output, and
   nothing is overwritten.

   ```bash
   python tools/build_deliverable.py <config> --name My_Region \
       --staging <output dir> --work <cache dir> all
   ```

   Text that needs a person (contact, region description, what each class
   looks like) goes in `<work>/readme_notes.ini`; until it's filled in the
   README contains `[[REVIEW: ...]]` markers and the build fails its final
   check. Steps can also be run one at a time: `plan`, `polygons`,
   `parameters`, `rasters`, `align`, `readme`, `check`.

3. **Upload.** `build_deliverable.py` prints the `rclone` commands for the
   lab's Box folder but doesn't run them. Do a dry run first, then
   `copy` and `check`.

The raster tools can also be used on their own:
`tools/download_ee_raster.py` (resumable download on the asset's own grid)
and `tools/validate_ee_raster.py`.

## Earth Engine inputs

Public datasets used directly: Landsat Collection 2 surface reflectance,
EPA Level III ecoregions, USGS WBD HUC06, TIGER states, MTBS burned areas,
JRC Global Forest Cover 2020, USFS LCMS, and (optional evidence gate)
WRI drivers of forest loss, FIRMS and Hansen Global Forest Change.

Not public. Ask the lab, or supply your own and change the config:

| Asset | Used for | Without it |
|---|---|---|
| `projects/<project>/assets/attributed_training_polygons_2012` | Training the high-magnitude classifier (mode 2) | Build training polygons with mode 1, or copy another project's set, as the 2026 Alaska runs did with Coast Range's |
| cMonster labeling raster (a local file, `cMonster_img_path`) | Labeling training polygons in mode 1 | Mode 2 with existing training polygons. The raster covers only the Pacific Northwest and California |
| `projects/bnet-main/assets/BdyDesg_LSRS_Wilderness`, `projects/north-cascades-bugnet/assets/nps_boundary` | Wilderness and National Park rule (`wild_path`) | Set `wild_path['on'] = 0` |
| `projects/emaprlab-general/assets/WFIGS` | WFIGS fire perimeters | Use `fire_mask_source = 'mtbs'` |

The Alaska runs use a classifier trained on Pacific Northwest polygons,
because no Alaska reference labels exist. Each product's README states
this.

## Tests

```bash
python -m pytest -q
```

The tests cover the code that runs without Earth Engine: parameter
handling, polygon filtering and exclusion rules, acreage and IDS fields,
the evidence gate, and the deliverable and README builders. Anything that
builds an `ee.*` computation is checked by running a real job.

## Repo layout

| Path | Purpose |
|---|---|
| `bugnet/main.py` | Entry point: loads a config, starts Earth Engine, asks for a mode and runs it |
| `bugnet/pipeline_modes.py` | The order of stages for each mode |
| `bugnet/disturbance_utils.py` | Stages A–C: composites, change, polygons, classification and exclusion |
| `bugnet/modeling_utils.py` | Forest mask, decline, KMeans and the class raster |
| `bugnet/postprocess_utils.py` | Final polygons: polygonizing, buffering, acreage and IDS attributes |
| `bugnet/bnet.py` | Shared Earth Engine helpers, fire masks and the run manifest |
| `bugnet/exclusion_evidence.py` | Optional evidence gate: keep a fire/harvest exclusion only where outside data supports it |
| `bugnet/cli_utils.py`, `bugnet/export_utils.py` | Config loading and validation; Drive/Cloud Storage export |
| `bugnet/templates/v2/` | Config template for the 2026 (v2026-2) method |
| `bugnet/templates/v1/`, `bugnet/templates/v3/` | Older templates used with `batch_bugnet.sh` for the 2025 products |
| `tools/` | Deliverable workflow (above) and `active_tasks.py` |
| `docs/` | Parameter reference and config layout |
| `tests/` | Unit tests |

Older scripts kept for reference: `batch_bugnet.sh` (parameter sweeps on
the 2025 cluster setup), `bugnet/file-manager.py` (organizing Drive
exports; replaced by `tools/build_deliverable.py`) and `bugnet/trashGEE.py`
(deleting an asset tree; dry run unless `--delete`).
