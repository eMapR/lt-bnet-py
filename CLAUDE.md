# Notes for Claude (lt-bnet-py)

This file is loaded automatically by Claude Code. It holds operational
context that isn't obvious from the code. The repo is **public**: never
commit credentials, contract/scope documents (e.g. the PDFs in `docs/`),
or anything else not meant for the public.

## Current state (updated 2026-10-30)

- **Branches:** `master` is the only branch. The former `bulc-d` branch
  (deliverable tools, equal-area acreage, `compute_project`, evidence gate,
  no-exclusion support) was fast-forwarded into it and deleted on
  2026-10-30, along with `add-sentinel2` and `refactor-bugnet-cleanup`.
  No BULC-D change-detection code was ever written.
- **2026 products (v2026-2) are delivered** for all 8 Region 6 ecoregions
  and 9 Region 10 (Alaska) regions, in OSU Box under
  `Bugnet Products/Bugnet_Region_{6,10}/Data/2026/Bugnet_<Region>_v2026-2/`.
- **Prince William Sound** uses no classifier-based exclusions
  (`param['exclusion_classes'] = []`): it has no harvest and no fire on
  record, so the classifier's fire/harvest labels were misclassified
  budworm. It was rerun from C1 on 2026-10-30 under the standard asset
  names; the earlier (exclusions on) outputs were deleted.
- **Known issue:** the Tanana README (and possibly other regions resumed
  after a relaunch) has a misleading section 11 and gives the relaunch date
  as the composite end date (`composite_params_end_date` is `date.today()`
  at the launch that wrote the parameter file).
- **Not done:** Gulf of Alaska and `r10-bugnet` (EE projects not
  registered).

## Where runs happen

Long runs go on the lab server islay, under `tmux` or detached.
- Repo: `/vol/v1/Bugnet/lt-bnet-py`; Python:
  `~/.conda/envs/lt-bnet-py/bin/python` (built from `lt-bnet-py.yml`, plus
  pytest).
- Earth Engine user credentials work for every `<region>-bugnet` project.
- **Run configs are gitignored**, flat layout:
  `bugnet/run_configs/<region>-bugnet-2026-v2/<region>-bugnet-2026-v2-config.py`.
- `param['compute_project']` runs Earth Engine in another project (for its
  quota) while assets stay in `project_name`. Only `cascades-bugnet` and
  `eastern-cascades-wa-bugnet` have the Partner tier (100k EECU-h/month);
  most others have 1,000 h, Klamath 150 h. Check tasks in the compute
  project: `python tools/active_tasks.py CONFIG`.

## How runs are launched / resumed

```bash
echo 2 | python bugnet/main.py <path-to-config> 2>&1 | tee logs/<region>-2026-v2-stakeholder.log   # mode 2 = run_mode_2
```

- **Don't relaunch while a region's GEE tasks are PENDING/RUNNING.** Resume
  works by `asset_exists()`, which only sees finished assets, so a relaunch
  resubmits duplicate tasks.
- When relaunching, rename the old log to `.runN.log` first.
- `main.py` never re-stamps an existing `_run_manifest`; delete it if the
  config changed in a way the manifest should record.
- Keep one version per asset folder under the standard names: to change a
  delivered region, edit its standard config, delete the superseded assets
  (with approval) and rerun. Don't leave suffixed side-by-side versions.

## Deliverables (per region, after a run)

1. `python tools/correct_polygon_schema.py CONFIG submit|validate|annotate`
   writes `<bnet_buffered_polygons>_corrected` (equal-area acreage, IDS
   fields, `bnet_label`). Original assets are never modified.
2. `python tools/build_deliverable.py CONFIG --name <Region> all` builds
   `/vol/v1/Bugnet/deliverables/box_staging/...` (GeoPackage, 4 GeoTIFFs,
   parameter CSV, README, validation/). Hand-written README text goes in
   `/vol/v1/Bugnet/deliverables/work/<region>-2026-v2/readme_notes.ini`.
3. Upload with rclone (remote `osu_box`): `copy --dry-run` first, then
   `copy`, then `check`. Never `sync`, `mount` or delete; never print the
   rclone config or tokens.

## Tests

`python -m pytest -q` from the repo root (185 passing as of 2026-10-30).

## Untracked files (intentionally not committed)

- `docs/*.pdf`: scope-of-work / task documents. Public repo, ask first.
- `tools/relaunch_watcher.py`: one-off ops script from the V2 batch.
