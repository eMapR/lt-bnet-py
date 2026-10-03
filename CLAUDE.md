# Notes for Claude (lt-bnet-py)

This file is loaded automatically by Claude Code. It holds operational
context that isn't obvious from the code. The repo is **public**: never
commit credentials, contract/scope documents (e.g. the PDFs in `docs/`),
or anything else not meant for the public.

## Current state (updated 2026-10-03)

### Legacy V2 stakeholder batch (8 regions, `version=2`, target year 2026)

| Region | Fire mask | Status |
|---|---|---|
| North Cascades, Columbia Mts, Eastern Cascades WA, William Sound | `mtbs` | Complete, verified |
| Klamath Mts | `mtbs_wfigs` | All 75 buffer shards done; final merge task `bugnet_polygons_buffered_2026_mag50_10mmu` PENDING in GEE since 2026-10-02 |
| Blue Mts, Cascades | `mtbs_wfigs` | `A_predictor_fitted_img_2021_2026` done; `A_predictor_change_img_2026` PENDING in GEE since 2026-10-01 |
| Coast Range | `mtbs_wfigs` | `A_predictor_fitted_img_2021_2026` RUNNING since 2026-10-01; `A_predictor_change_img_2026` PENDING |

- The local `main.py` processes for the last four **all died** on
  2026-10-01/02 from laptop network errors (DNS failure, dropped
  connections, a token refresh). The GEE tasks kept going server-side.
- Tasks sitting PENDING for ~2 days across all four projects most likely
  means the GEE **noncommercial quota "restricted mode"** (Klamath's
  project warned about it on 2026-10-01). This is unconfirmed for the
  other three projects; check quota in the Cloud console.
- The batch is mixed: four regions used `mtbs`, four use `mtbs_wfigs`. The
  user hasn't decided whether to re-check the first four (suggestion:
  count the WFIGS-only fire overlap first).

### Next steps

1. **Don't relaunch while a region's GEE tasks are PENDING/RUNNING.**
   Resume works by `asset_exists()`, which only sees *finished* assets, so
   a relaunch resubmits duplicate tasks. Check task state first (e.g.
   `ee.Initialize(project="<region>-bugnet"); ee.data.listOperations()`).
   Either wait for them to finish or cancel them, then relaunch.
2. **Make `wait_for_task` (`bugnet/main.py`) survive network errors.** It
   calls `task.status()` with no exception handling, so one failed
   check kills a multi-day run. Retry with backoff on
   `ConnectionError` / transient `EEException`. Proposed, not done yet.
3. **Move long runs off the laptop.** The user wants runs on an always-on
   server (lab server or small GCP VM, under `tmux`/`nohup`; a service
   account avoids expiring user tokens). Not set up yet. When moving:
   - `lt-bnet-py.yml` is pinned for Linux and builds as-is there. (On
     macOS arm64 the env was rebuilt from conda-forge instead.)
   - **Run configs are gitignored** (`bugnet/run_configs/`). Copy them
     over separately, e.g.
     `bugnet/run_configs/2026/r6/v2/<region>-bugnet-2026-v2/<region>-bugnet-2026-v2-config.py`.
   - The server needs Earth Engine auth with access to every
     `<region>-bugnet` GCP project.

## How runs are launched / resumed

```bash
echo 2 | python bugnet/main.py <path-to-config>   # mode 2 = run_mode_2
```

Logs and pids go to `logs/<region>-2026-v2-stakeholder.{log,pid}`
(gitignored). When relaunching, rename the old log to `.runN.log` first.
`main.py` never re-stamps an existing `_run_manifest` asset, so delete it
if the config changed in a way the manifest should record (e.g. fire mask).

## Tests

`python -m pytest -q` from the repo root (105 passing as of 2026-10-03).

## Untracked files (intentionally not committed)

- `docs/*.pdf`: scope-of-work / task documents. Public repo, ask first.
- `tools/abc_disagreement_viewer.js`: GEE Code Editor script, not yet
  smoke-tested.
