# Config layout

Three gitignored directories hold parameter files. They're not peers —
each has a different role:

| Directory | Role | Hand-edited? |
|---|---|---|
| `templates/` | Source of truth. One file per ecoregion (`templates/v3/blue-mts-template.py`, etc.), with placeholder `target`/`ltendYear`/`version`/`configName` values. | Yes — edit these when something structural changes. |
| `run_configs/` | Generated output. `batch_bugnet.sh` reads a template and materializes real, run-ready parameter files here (one per year/region/version, plus one per mag/mmu variant). This is what you actually pass to `main.py`. | No — regenerate via `batch_bugnet.sh`, don't hand-edit (edits get silently overwritten on the next generation pass since `OVERWRITE_BASE`/`OVERWRITE_VARIANTS` default to on). |
| `legacy_parameters/` | Retired. Hand-authored parameter files from before `batch_bugnet.sh` existed - one-off, no generation step. The oldest tier in here (`2024/v1/`) predates the current `main.py`/`cli_utils.py` schema entirely and will fail `cli_utils.validate_parameters()` if you try to run it - it's not a bug, it's genuinely incompatible. | Frozen history - don't add new files here. |

Named `parameters/` and `params_new/` before 2026-08-15; renamed because
neither name signaled which one was current, and `parameters/2024/v1/`'s
"v1" collided in meaning with `run_configs/.../v1/`'s "v1" (see below).

## Flow

```
templates/v3/<ecoregion>-template.py
        │  batch_bugnet.sh materializes: target, ltendYear, version,
        │  configName, decline_thresholds, bnet_polygon_mmu
        ▼
run_configs/<year>/<region>/<version>/<ecoregion>-bugnet-<year>-<version>/
        ├── <...>-config.py            (base, per year)
        └── <...>-mag<MAG>-mmu<MMU>.py (variant, per sweep point)
        │
        ▼
python main.py <path-to-one-of-these>
```

## The "version" overload — why "v1" means two different things

`--version` (and `param['version']`) is used for two unrelated purposes
at once:

1. **Which decline algorithm to run.** `cli_utils.normalize_parameters()`
   derives `logic_version` from `version`'s leading digit, then sets
   `configName = f"option{logic_version}"`. `pipeline_modes.py` reads
   `configName` via `"3" in configName` to pick `declining_ltsd`
   (LTSD path) vs `declining_snic` (SNIC path) - see
   `docs/parameter_reference_template.py`'s `configName` entry for what
   each path needs.
2. **Which run-variant this is** — the folder-name suffix
   (`run_configs/.../v1/`, `.../v3/`), used to keep sweeps/experiments
   separate on disk.

These are orthogonal (which algorithm vs. which run-iteration) but one
CLI flag controls both, so a version label like `v1` unavoidably *looks*
like a schema-generation label the way `legacy_parameters/2024/v1/` is -
even though `run_configs/2025/r6/v1/`'s "v1" really means "SNIC path,"
nothing about schema era. This is exactly what let three 2025 SNIC-path
configs go missing `LTSDname`/`snicName` (fixed 2026-08-15,
`cli_utils.validate_parameters()` now catches it, and `batch_bugnet.sh`
now auto-injects both keys when generating a non-LTSD config) - the
naming made it easy to assume "v1" meant "just an older/simpler
variant," not "a materially different pipeline path with its own
required keys."

Untangling this properly - an explicit `--decline-path {snic,ltsd}` flag
independent of the run-variant label, and renaming `configName` values
from `option1`/`option3` to something self-describing - is a larger,
deferred change (it touches `pipeline_modes.py`'s path-selection logic
and what future GEE assets get named). Not done as part of this pass.
