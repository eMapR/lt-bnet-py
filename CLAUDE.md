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
| Coast Range | `mtbs_wfigs` | `A_predictor_fitted_img_2021_2026` RUNNING since 2026-10-01 (still heartbeating 2026-10-03 20:42 UTC); `A_predictor_change_img_2026` PENDING |

Task states above re-checked 2026-10-03 ~20:45 UTC: unchanged since 10-02.

- The local `main.py` processes for the last four **all died** on
  2026-10-01/02 from laptop network errors (DNS failure, dropped
  connections, a token refresh). The GEE tasks kept going server-side.
- Tasks sitting PENDING for ~2 days across all four projects most likely
  means the GEE **noncommercial quota "restricted mode"** (Klamath's
  project warned about it on 2026-10-01). This is unconfirmed for the
  other three projects; check quota in the Cloud console. The EE API
  doesn't expose it: `ee.data.getProjectConfig()` only returns
  `registrationState: REGISTERED_NOT_COMMERCIALLY` for all four.
- The batch is mixed: four regions used `mtbs`, four use `mtbs_wfigs`. The
  user hasn't decided whether to re-check the first four (suggestion:
  count the WFIGS-only fire overlap first).

### Next steps

1. **Don't relaunch while a region's GEE tasks are PENDING/RUNNING.**
   Resume works by `asset_exists()`, which only sees *finished* assets, so
   a relaunch resubmits duplicate tasks. Check task state first (e.g.
   `ee.Initialize(project="<region>-bugnet"); ee.data.listOperations()`).
   Either wait for them to finish or cancel them, then relaunch.
2. ~~Make `wait_for_task` survive network errors.~~ Done 2026-10-03:
   `bnet.get_task_status()` retries transient errors (OSError/DNS,
   EEException, google-auth/httplib2) with backoff (30s doubling to 15
   min) and gives up after 6 h of continuous failure. Used by
   `main.wait_for_task` and `modeling_utils._wait_for_task`.
3. **Long runs now go on the lab server islay** (set up 2026-10-03), not
   the laptop. Run under `tmux`. Nothing has been launched there yet.
   - Repo checkout: `/vol/v1/Bugnet/lt-bnet-py`; Python:
     `~/.conda/envs/lt-bnet-py/bin/python` (built from `lt-bnet-py.yml`,
     which is pinned for Linux).
   - Earth Engine user credentials work for every `<region>-bugnet`
     project (no service account yet).
   - **Run configs are gitignored** and were copied over separately. On
     islay they use a flat layout:
     `bugnet/run_configs/<region>-bugnet-2026-v2/<region>-bugnet-2026-v2-config.py`
     (the laptop has an extra `2026/r6/v2/` level).
   - `logs/` must be created before the first launch.
4. **Relaunch watcher running on islay** since 2026-10-04 02:40 UTC (tmux
   session `bugnet-watcher`, log `logs/relaunch_watcher.log`). Every 15 min
   it checks Klamath, Blue Mts, Cascades and Coast Range. When a region has
   no PENDING/RUNNING tasks, it launches `main.py` mode 2 for it once,
   detached, writing `logs/<region>-2026-v2-stakeholder.{log,pid}`. A `.pid`
   file means "already launched": the watcher never relaunches it, so check
   that region's log if its run dies. The watcher exits once all four are
   launched. Script: `tools/relaunch_watcher.py`.

## How runs are launched / resumed

```bash
echo 2 | python bugnet/main.py <path-to-config> 2>&1 | tee logs/<region>-2026-v2-stakeholder.log   # mode 2 = run_mode_2
```

Logs and pids go to `logs/<region>-2026-v2-stakeholder.{log,pid}`
(gitignored). When relaunching, rename the old log to `.runN.log` first.
`main.py` never re-stamps an existing `_run_manifest` asset, so delete it
if the config changed in a way the manifest should record (e.g. fire mask).

## Tests

`python -m pytest -q` from the repo root (108 passing as of 2026-10-03).

## Untracked files (intentionally not committed)

- `docs/*.pdf`: scope-of-work / task documents. Public repo, ask first.
- `tools/relaunch_watcher.py`: one-off ops script for the V2 batch.
- `tools/abc_disagreement_viewer.js`: GEE Code Editor script, not yet
  smoke-tested.
