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

**Not done**: there's still no actual `snic`-path template under
`templates/` for `batch_bugnet.sh --decline-path snic` to generate from
- `templates/v3/` is entirely LTSD-path. The three real 2025 SNIC-path
configs (coast-range/williams-sound/columbia-mts) were hand-authored
directly into `run_configs/`, bypassing the template flow, which is how
they went unnoticed. Creating real templates for those regions using the
new convention would change their asset names going forward, so that's
deliberately left as a separate decision rather than done here.
