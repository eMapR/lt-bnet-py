#!/usr/bin/env bash
set -euo pipefail

########################################
# SETTINGS (edit these for your env)
########################################
# Output config filename prefix:
OUT_NAME_PREFIX="blue-mts-bugnet-2022-v3"

PARAM_DIR="/vol/v1/bugnet/lt-bnet-py/bugnet/parameters/2022/r6/v3/${OUT_NAME_PREFIX}"
TEMPLATE_CFG="${PARAM_DIR}/${OUT_NAME_PREFIX}-config.py"
PY_RUNNER="/vol/v1/bugnet/lt-bnet-py/bugnet/main.py"

# Iteration sets (tweak if needed)
MAGS=(50 60 70)     # decline thresholds -> {'tcb': MAG, 'tcg': MAG, 'tcw': MAG}
MMUS=(10 20 30)     # polygon MMUs
BASE_MMU=10         # must finish before other MMUs for a given MAG
FIRST_MAG=50        # which MAG to use for the very first bootstrap run


# Concurrency (can override with --jobs)
JOBS=4

# Sentinel file to remember that initial single-job bootstrap has completed
BOOTSTRAP_FLAG="${PARAM_DIR}/.bootstrap_done"

# How to run: pass only the config path; feed "2" to STDIN for the prompt.
RUN_CMD() { printf '2\n' | python3 "$PY_RUNNER" "$1"; }

########################################
# CLI
########################################
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --param-dir) PARAM_DIR="$2"; shift 2 ;;
    --template) TEMPLATE_CFG="$2"; shift 2 ;;
    --runner) PY_RUNNER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

########################################
# Helpers
########################################
log() { printf '%s %s\n' "[$(date +%H:%M:%S)]" "$*"; }

require() {
  [[ -f "$1" ]] || { echo "Missing file: $1" >&2; exit 1; }
}

# throttle background jobs to <= JOBS
throttle() {
  local n
  while true; do
    n=$(jobs -rp | wc -l | tr -d ' ')
    [[ "$n" -lt "$JOBS" ]] && break
    sleep 0.2
  done
}

cfg_path() {
  local mag="$1" mmu="$2"
  echo "${PARAM_DIR}/${OUT_NAME_PREFIX}-mag${mag}-mmu${mmu}.py"
}

# Write edited config (or just print in dry run)
edit_and_write_cfg() {
  local in_cfg="$1" out_cfg="$2" mag="$3" mmu="$4"

  if (( DRY_RUN )); then
    log "DRY: would write ${out_cfg} (MAG=${mag}, MMU=${mmu})"
    return 0
  fi

  python3 - "$in_cfg" "$out_cfg" "$mag" "$mmu" <<'PYEDIT'
import re, sys, os
src, dst, mag_s, mmu_s = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
mag = int(mag_s); mmu = int(mmu_s)

with open(src, 'r', encoding='utf-8') as f:
    txt = f.read()

# Replace decline_thresholds dict (set all three to MAG)
txt, _ = re.subn(
    r"""param\['decline_thresholds'\]\s*=\s*\{[^}]*\}""",
    f"param['decline_thresholds'] = {{'tcb': {mag}, 'tcg': {mag}, 'tcw': {mag}}}",
    txt, count=1, flags=re.S
)

# Replace bnet_polygon_mmu integer
txt, n = re.subn(
    r"""param\['bnet_polygon_mmu'\]\s*=\s*\d+""",
    f"param['bnet_polygon_mmu'] = {mmu}",
    txt, count=1
)
if n == 0:
    # append if missing
    txt = txt.rstrip() + f"\nparam['bnet_polygon_mmu'] = {mmu}\n"

os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, 'w', encoding='utf-8') as f:
    f.write(txt)
PYEDIT
}

# Build + run one variant (or print in dry run)
build_and_run() {
  local mag="$1" mmu="$2"
  local out_cfg
  out_cfg="$(cfg_path "$mag" "$mmu")"

  if (( DRY_RUN )); then
    log "DRY: would create $(basename "$out_cfg")"
    log "DRY: would RUN: python3 $PY_RUNNER $out_cfg   # feeding '2' to stdin"
    return 0
  fi

  edit_and_write_cfg "$TEMPLATE_CFG" "$out_cfg" "$mag" "$mmu"
  log "RUN: MAG=${mag} MMU=${mmu}"
  RUN_CMD "$out_cfg"
}

# For a given MAG: run base MMU sync, then spawn the rest in parallel
chain_for_mag() {
  local mag="$1"
  local mmu
  log "MAG=${mag}: starting base MMU=${BASE_MMU}"

  # base run (synchronous)
  build_and_run "$mag" "$BASE_MMU" || {
    log "MAG=${mag}: base MMU=${BASE_MMU} failed; skipping follow-ups"
    return 1
  }

  # queue the remaining MMUs
  for mmu in "${MMUS[@]}"; do
    [[ "$mmu" -eq "$BASE_MMU" ]] && continue
    if (( DRY_RUN )); then
      log "DRY: (after mag=${mag} mmu=${BASE_MMU} completes) would launch mag=${mag} mmu=${mmu} in background"
      continue
    fi
    throttle
    (
      build_and_run "$mag" "$mmu"
    ) &
    log "MAG=${mag}: queued MMU=${mmu}"
  done

  # Wait for this MAG's followers if not in DRY mode
  if (( ! DRY_RUN )); then
    wait
    log "MAG=${mag}: all MMUs complete"
  fi
}

########################################
# Main
########################################
require "$TEMPLATE_CFG"
mkdir -p "$PARAM_DIR"

log "Starting. DRY_RUN=${DRY_RUN} JOBS=${JOBS}"
log "Template: $TEMPLATE_CFG"
log "Runner:   $PY_RUNNER"
log "Output to: $PARAM_DIR"
log "Plan: MAGS=${MAGS[*]} MMUS=${MMUS[*]} (BASE_MMU=${BASE_MMU})"
[[ -f "$BOOTSTRAP_FLAG" ]] && log "Bootstrap already done (found $BOOTSTRAP_FLAG)" || log "Bootstrap not yet done; will start with a single job."

# --- Bootstrap step: if no .bootstrap_done, run ONLY FIRST_MAG @ BASE_MMU first ---
if [[ ! -f "$BOOTSTRAP_FLAG" ]]; then
  if (( DRY_RUN )); then
    log "DRY: BOOTSTRAP -> run mag${FIRST_MAG}-mmu${BASE_MMU} ONLY, then mark bootstrap done and continue."
  else
    log "BOOTSTRAP: running mag${FIRST_MAG}-mmu${BASE_MMU} ONLY"
    build_and_run "$FIRST_MAG" "$BASE_MMU"
    touch "$BOOTSTRAP_FLAG"
    log "BOOTSTRAP: completed and marked ($BOOTSTRAP_FLAG)"
  fi
fi

# After bootstrap, proceed with the normal plan
if (( DRY_RUN )); then
  for mag in "${MAGS[@]}"; do
    log "DRY: MAG=${mag} -> run mag${mag}-mmu${BASE_MMU} first; then mag${mag}-mmu{others} in parallel"
  done
  log "Dry run complete (no files written, nothing executed)."
  exit 0
fi

# Kick off each MAG chain in parallel (bounded by JOBS).
# Note: FIRST_MAG@BASE_MMU may have already been run during bootstrap.
for mag in "${MAGS[@]}"; do
  throttle
  (
    # If this mag's base was already done during bootstrap, skip re-running it and
    # just queue the remaining MMUs for this MAG.
    if [[ "$mag" -eq "$FIRST_MAG" && -f "$BOOTSTRAP_FLAG" ]]; then
      log "MAG=${mag}: base was done in bootstrap; launching remaining MMUs."
      for mmu in "${MMUS[@]}"; do
        [[ "$mmu" -eq "$BASE_MMU" ]] && continue
        build_and_run "$mag" "$mmu" &
        log "MAG=${mag}: queued MMU=${mmu}"
      done
      wait
      log "MAG=${mag}: all MMUs complete"
    else
      chain_for_mag "$mag"
    fi
  ) &
  log "Queued MAG=${mag} chain"
done

wait
log "All iterations complete."
