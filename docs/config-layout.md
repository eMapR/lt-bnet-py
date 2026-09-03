# Config layout

Three directories under `bugnet/` hold parameter files (all Python
source and its config trees moved under `bugnet/` on 2026-08-15 - see
the repo-layout table in the root README). They're not peers — each has
a different role, and (as of 2026-09-03) a different git status to match:

| Directory | Role | Hand-edited? | Git status |
|---|---|---|---|
| `bugnet/templates/` | Source of truth. One file per ecoregion (`bugnet/templates/v3/blue-mts-template.py`, etc.), with placeholder `target`/`ltendYear`/`version`/`configName` values. | Yes — edit these when something structural changes. | **Tracked.** This is canonical source, not build output - no secrets, no generated content, no reason to keep it gitignored (see the 2026-09-03 assessment that led to this). |
| `bugnet/run_configs/` | Generated output. `batch_bugnet.sh` reads a template and materializes real, run-ready parameter files here (one per year/region/version, plus one per mag/mmu variant). This is what you actually pass to `bugnet/main.py`. | No — regenerate via `batch_bugnet.sh`, don't hand-edit (edits get silently overwritten on the next generation pass since `OVERWRITE_BASE`/`OVERWRITE_VARIANTS` default to on). | Gitignored - this is derived build output (868+ files, regenerated wholesale), not source. |
| `bugnet/legacy_parameters/` | Retired. Hand-authored parameter files from before `batch_bugnet.sh` existed - one-off, no generation step. The oldest tier in here (`2024/v1/`) predates the current `main.py`/`cli_utils.py` schema entirely and will fail `cli_utils.validate_parameters()` if you try to run it - it's not a bug, it's genuinely incompatible. | Frozen history - don't add new files here. | Gitignored - frozen archive, not source going forward. |

Named `parameters/` and `params_new/` before 2026-08-15; renamed because
neither name signaled which one was current, and `parameters/2024/v1/`'s
"v1" collided in meaning with `run_configs/.../v1/`'s "v1" (see below).

## Flow

```
bugnet/templates/v3/<ecoregion>-template.py
        │  batch_bugnet.sh materializes: target, ltendYear, version,
        │  configName, decline_thresholds, bnet_polygon_mmu
        ▼
bugnet/run_configs/<year>/<region>/<version>/<ecoregion>-bugnet-<year>-<version>/
        ├── <...>-config.py            (base, per year)
        └── <...>-mag<MAG>-mmu<MMU>.py (variant, per sweep point)
        │
        ▼
python bugnet/main.py <path-to-one-of-these>
```

## The "version" overload — why "v1" used to mean two different things

`--version` (and `param['version']`) used to be overloaded for two
unrelated purposes at once: *which decline algorithm to run* and *which
run-variant this is*. That's why a version label like `v1` used to look
like a schema-generation label the way `legacy_parameters/2024/v1/` is -
even though `run_configs/2025/r6/v1/`'s "v1" really meant "SNIC path,"
nothing about schema era. This is exactly what let three 2025 SNIC-path
configs go missing `LTSDname`/`snicName` in the first place - the naming
made it easy to assume "v1" meant "just an older/simpler variant," not
"a materially different pipeline path with its own required keys."

**Fixed 2026-08-15** with an explicit `param['decline_path']` key
(`'snic'` or `'ltsd'`), decoupled from `version`:

- `cli_utils.normalize_parameters()` sets `decline_path` from whatever a
  config sets explicitly, falling back to the legacy `"3" in configName`
  convention only when a config doesn't set it - so every existing
  config file (`option1`/`option3`, no `decline_path` key) keeps
  behaving exactly as before. `pipeline_modes.py` reads
  `param["decline_path"]` directly instead of pattern-matching
  `configName`.
- `cli_utils.validate_parameters()` requires `LTSDname`/`snicName` based
  on `decline_path == "snic"`, not a `configName` substring check.
- `batch_bugnet.sh` gained `--decline-path {snic,ltsd}`: pass it to pick
  the algorithm explicitly (this also switches generated `configName`
  values to the self-describing `'snic'`/`'ltsd'` convention, changing
  what *new* GEE assets get named - existing assets are untouched).
  Omit it to keep the legacy `--version`-derived behavior byte-for-byte.

**`bugnet/templates/v1/` added 2026-08-15** for the three real SNIC-path
regions (coast-range, williams-sound, columbia-mts) - built from their
now-fixed `bugnet/run_configs/2025/r6/v1/*` files, keeping
`configName='option1'` (the legacy convention, not the new
self-describing one) deliberately: these three already have real GEE
asset history under that naming, and switching to `configName='snic'`
would produce different future asset names than what's already there.
Verified by materializing each new template through `batch_bugnet.sh`'s
embedded transform in legacy mode (`--version v1`, no `--decline-path`)
and diffing against the real existing config for that region - only
cosmetic differences (a comment, where `LTSDname`/`snicName` land in the
file). `batch_bugnet.sh --ecos coast-range,williams-sound,columbia-mts
--version v1 --templates-dir bugnet/templates/v1 ...` now has a real
template to generate from, closing the original gap (these three were
hand-authored directly into `run_configs/`, bypassing the template flow,
which is how they went unnoticed in the first place).

New regions on the SNIC path going forward should use `--decline-path
snic` (self-describing `configName`) instead of copying this `v1`
convention - `bugnet/templates/v1/` exists only to match the three
regions' existing asset-naming history, not as the recommended pattern
for new work.
