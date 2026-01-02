#!/usr/bin/env bash
set -euo pipefail

########################################
# DEFAULT SETTINGS (edit for your env)
########################################
# “Ecoregion key” list (must match template filenames like <PRO>-template.py)
ECOS=(blue-mts east-cascades coast-range)

# Region(s) (folder dimension). You said: for now just r6.
REGIONS=(r6)

# Years to run (can be "2015-2025" or CSV "2015,2016,...")
YEARS_SPEC="2015-2025"

VERSION="v3"

# Canonical templates live here:
TEMPLATES_DIR="/vol/v1/bugnet/lt-bnet-py/bugnet/templates/v3"

# Where run instance folders live:
PARAM_ROOT="/vol/v1/bugnet/lt-bnet-py/bugnet/params_new"

# Program runner:
PY_RUNNER="/vol/v1/bugnet/lt-bnet-py/bugnet/main.py"

# Variant sweep
MAGS=(50 60 70)
MMUS=(10 20 30)
BASE_MMU=10
FIRST_MAG=50

# Concurrency (bounded for background jobs)
JOBS=2

# Overwrite behavior (generated configs)
OVERWRITE_BASE=1       # overwrite <...>-config.py
OVERWRITE_VARIANTS=1   # overwrite <...>-magXX-mmuYY.py

# How to run: pass only the config path; feed "2" to STDIN for the prompt.
RUN_CMD() { printf '2\n' | python3 "$PY_RUNNER" "$1"; }

########################################
# CLI
########################################
DRY_RUN=0

parse_csv_to_array() {
  local csv="$1"
  local -n arr_ref="$2"
  IFS=',' read -r -a arr_ref <<<"$csv"
}

expand_years_spec() {
  # Accepts "2015-2025" or "2015,2016,2017"
  local spec="$1"
  local -n out_arr="$2"
  out_arr=()

  if [[ "$spec" == *","* ]]; then
    parse_csv_to_array "$spec" out_arr
    return 0
  fi

  if [[ "$spec" =~ ^([0-9]{4})-([0-9]{4})$ ]]; then
    local start="${BASH_REMATCH[1]}"
    local end="${BASH_REMATCH[2]}"
    local y
    for ((y=start; y<=end; y++)); do
      out_arr+=("$y")
    done
    return 0
  fi

  # single year
  if [[ "$spec" =~ ^[0-9]{4}$ ]]; then
    out_arr+=("$spec")
    return 0
  fi

  echo "Bad YEARS spec: '$spec' (use 2015-2025 or 2015,2016,... or 2015)" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --ecos) parse_csv_to_array "$2" ECOS; shift 2 ;;          # e.g. --ecos blue-mts,east-cascades
    --regions) parse_csv_to_array "$2" REGIONS; shift 2 ;;     # e.g. --regions r6,r10
    --years) YEARS_SPEC="$2"; shift 2 ;;                       # e.g. --years 2015-2025 or 2015,2016
    --version) VERSION="$2"; shift 2 ;;
    --templates-dir) TEMPLATES_DIR="$2"; shift 2 ;;
    --param-root) PARAM_ROOT="$2"; shift 2 ;;
    --runner) PY_RUNNER="$2"; shift 2 ;;
    --no-overwrite-base) OVERWRITE_BASE=0; shift ;;
    --no-overwrite-variants) OVERWRITE_VARIANTS=0; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
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

max_of_years() {
  local max=0 y
  for y in "$@"; do
    (( y > max )) && max=$y
  done
  echo "$max"
}

# Context (set per eco/region/year)
PRO=""
REGION=""
YEAR=""
OUT_NAME_PREFIX=""
PARAM_DIR=""
TEMPLATE_CANON=""
BASE_CFG=""
BOOTSTRAP_FLAG=""

set_context() {
  PRO="$1"
  REGION="$2"
  YEAR="$3"

  OUT_NAME_PREFIX="${PRO}-bugnet-${YEAR}-${VERSION}"
  PARAM_DIR="${PARAM_ROOT}/${YEAR}/${REGION}/${VERSION}/${OUT_NAME_PREFIX}"
  TEMPLATE_CANON="${TEMPLATES_DIR}/${PRO}-template.py"
  BASE_CFG="${PARAM_DIR}/${OUT_NAME_PREFIX}-config.py"
  BOOTSTRAP_FLAG="${PARAM_DIR}/.bootstrap_done"
}

cfg_path_variant() {
  local mag="$1" mmu="$2"
  echo "${PARAM_DIR}/${OUT_NAME_PREFIX}-mag${mag}-mmu${mmu}.py"
}

########################################
# Config writing
########################################
# 1) Materialize year-specific base config from canonical template:
#    - copy template -> BASE_CFG
#    - set param['target'] = YEAR
#    - set param['ltendYear'] = min(YEAR+2, MAX_YEAR)
materialize_base_cfg() {
  local year="$1" ltend="$2"

  if (( DRY_RUN )); then
    log "DRY: would mkdir -p '$PARAM_DIR'"
    log "DRY: would create base config: $BASE_CFG (target=$year, ltendYear=$ltend) from $TEMPLATE_CANON"
    return 0
  fi

  mkdir -p "$PARAM_DIR"

  if [[ -f "$BASE_CFG" && "$OVERWRITE_BASE" -eq 0 ]]; then
    log "Base config exists; not overwriting: $BASE_CFG"
    return 0
  fi

  python3 - "$TEMPLATE_CANON" "$BASE_CFG" "$year" "$ltend" <<'PYBASE'
import re, sys, os

src, dst, year_s, ltend_s = sys.argv[1:5]
year = int(year_s)
ltend = int(ltend_s)

with open(src, "r", encoding="utf-8") as f:
    txt = f.read()

def set_int_param(txt, key, value):
    # Match param['key'] = 123 or param["key"] = 123
    pat = rf"""param\[\s*['"]{re.escape(key)}['"]\s*\]\s*=\s*\d+"""
    if re.search(pat, txt):
        return re.sub(pat, f"param['{key}'] = {value}", txt, count=1), True
    # If missing, append
    return txt.rstrip() + f"\nparam['{key}'] = {value}\n", False

txt, _ = set_int_param(txt, "target", year)
txt, _ = set_int_param(txt, "ltendYear", ltend)

os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, "w", encoding="utf-8") as f:
    f.write(txt)
PYBASE
}

# 2) Create variant config from the year-base config:
#    - set decline_thresholds (all to MAG)
#    - set bnet_polygon_mmu (MMU)
write_variant_cfg() {
  local in_cfg="$1" out_cfg="$2" mag="$3" mmu="$4"

  if (( DRY_RUN )); then
    log "DRY: would write variant $(basename "$out_cfg") (MAG=$mag, MMU=$mmu) from $(basename "$in_cfg")"
    return 0
  fi

  if [[ -f "$out_cfg" && "$OVERWRITE_VARIANTS" -eq 0 ]]; then
    log "Variant exists; not overwriting: $out_cfg"
    return 0
  fi

  python3 - "$in_cfg" "$out_cfg" "$mag" "$mmu" <<'PYVAR'
import re, sys, os
src, dst, mag_s, mmu_s = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
mag = int(mag_s); mmu = int(mmu_s)

with open(src, "r", encoding="utf-8") as f:
    txt = f.read()

# decline_thresholds dict (set all three to MAG)
# Accept either single- or double-quote key form in source; replace using single quotes.
txt, n1 = re.subn(
    r"""param\[\s*['"]decline_thresholds['"]\s*\]\s*=\s*\{[^}]*\}""",
    f"param['decline_thresholds'] = {{'tcb': {mag}, 'tcg': {mag}, 'tcw': {mag}}}",
    txt, count=1, flags=re.S
)
if n1 == 0:
    txt = txt.rstrip() + f"\nparam['decline_thresholds'] = {{'tcb': {mag}, 'tcg': {mag}, 'tcw': {mag}}}\n"

# bnet_polygon_mmu integer
txt, n2 = re.subn(
    r"""param\[\s*['"]bnet_polygon_mmu['"]\s*\]\s*=\s*\d+""",
    f"param['bnet_polygon_mmu'] = {mmu}",
    txt, count=1
)
if n2 == 0:
    txt = txt.rstrip() + f"\nparam['bnet_polygon_mmu'] = {mmu}\n"

os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, "w", encoding="utf-8") as f:
    f.write(txt)
PYVAR
}

########################################
# Build + run
########################################
build_and_run_variant() {
  local mag="$1" mmu="$2"
  local out_cfg
  out_cfg="$(cfg_path_variant "$mag" "$mmu")"

  if (( DRY_RUN )); then
    log "DRY: would create $(basename "$out_cfg")"
    log "DRY: would RUN: python3 $PY_RUNNER $out_cfg   # feeding '2' to stdin"
    return 0
  fi

  write_variant_cfg "$BASE_CFG" "$out_cfg" "$mag" "$mmu"
  log "RUN: PRO=${PRO} YEAR=${YEAR} REGION=${REGION} MAG=${mag} MMU=${mmu}"
  RUN_CMD "$out_cfg"
}

chain_for_mag() {
  local mag="$1"

  log "PRO=${PRO} YEAR=${YEAR} REGION=${REGION} MAG=${mag}: starting base MMU=${BASE_MMU}"

  # base run (synchronous)
  build_and_run_variant "$mag" "$BASE_MMU" || {
    log "PRO=${PRO} YEAR=${YEAR} REGION=${REGION} MAG=${mag}: base MMU=${BASE_MMU} failed; skipping follow-ups"
    return 1
  }

  # queue remaining MMUs
  local mmu
  for mmu in "${MMUS[@]}"; do
    [[ "$mmu" -eq "$BASE_MMU" ]] && continue

    if (( DRY_RUN )); then
      log "DRY: (after mag=${mag} mmu=${BASE_MMU}) would launch mmu=${mmu} in background"
      continue
    fi

    throttle
    (
      build_and_run_variant "$mag" "$mmu"
    ) &
    log "PRO=${PRO} YEAR=${YEAR} REGION=${REGION} MAG=${mag}: queued MMU=${mmu}"
  done

  if (( ! DRY_RUN )); then
    wait
    log "PRO=${PRO} YEAR=${YEAR} REGION=${REGION} MAG=${mag}: all MMUs complete"
  fi
}

run_one_context() {
  local max_year="$1"

  # Compute ltendYear for this YEAR under your rule:
  # ltendYear = min(target+2, max_year)
  local ltend=$(( YEAR + 2 ))
  (( ltend > max_year )) && ltend="$max_year"

  log "----------------------------------------"
  log "CONTEXT: PRO=${PRO} YEAR=${YEAR} REGION=${REGION} VERSION=${VERSION}"
  log "Template: $TEMPLATE_CANON"
  log "Out dir:  $PARAM_DIR"
  log "Base cfg: $BASE_CFG"
  log "Rule: ltendYear=min(target+2, max_year) => ${ltend} (max_year=${max_year})"
  log "Plan: MAGS=${MAGS[*]} MMUS=${MMUS[*]} (BASE_MMU=${BASE_MMU}, FIRST_MAG=${FIRST_MAG})"

  require "$TEMPLATE_CANON"

  # Create base cfg for this year
  materialize_base_cfg "$YEAR" "$ltend"

  # Bootstrap behavior per folder
  if [[ ! -f "$BOOTSTRAP_FLAG" ]]; then
    if (( DRY_RUN )); then
      log "DRY: BOOTSTRAP -> run mag${FIRST_MAG}-mmu${BASE_MMU} ONLY, then touch $BOOTSTRAP_FLAG"
    else
      log "BOOTSTRAP: running mag${FIRST_MAG}-mmu${BASE_MMU} ONLY"
      build_and_run_variant "$FIRST_MAG" "$BASE_MMU"
      touch "$BOOTSTRAP_FLAG"
      log "BOOTSTRAP: completed and marked ($BOOTSTRAP_FLAG)"
    fi
  else
    log "Bootstrap already done (found $BOOTSTRAP_FLAG)"
  fi

  if (( DRY_RUN )); then
    for mag in "${MAGS[@]}"; do
      log "DRY: MAG=${mag} -> run mag${mag}-mmu${BASE_MMU} first; then other MMUs in parallel"
    done
    return 0
  fi

  # Kick off each MAG chain in parallel (bounded by JOBS).
  # Note: FIRST_MAG@BASE_MMU may have already been run in bootstrap.
  local mag
  for mag in "${MAGS[@]}"; do
    throttle
    (
      if [[ "$mag" -eq "$FIRST_MAG" && -f "$BOOTSTRAP_FLAG" ]]; then
        log "MAG=${mag}: base was done in bootstrap; launching remaining MMUs."
        local mmu
        for mmu in "${MMUS[@]}"; do
          [[ "$mmu" -eq "$BASE_MMU" ]] && continue
          build_and_run_variant "$mag" "$mmu" &
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
  log "DONE: PRO=${PRO} YEAR=${YEAR} REGION=${REGION}"
}

########################################
# Main
########################################
expand_years_spec "$YEARS_SPEC" YEARS
MAX_YEAR_GLOBAL="$(max_of_years "${YEARS[@]}")"

log "Starting. DRY_RUN=${DRY_RUN} JOBS=${JOBS}"
log "ECOS=${ECOS[*]}"
log "REGIONS=${REGIONS[*]}"
log "YEARS=${YEARS[*]} (max=${MAX_YEAR_GLOBAL})"
log "VERSION=${VERSION}"
log "TEMPLATES_DIR=${TEMPLATES_DIR}"
log "PARAM_ROOT=${PARAM_ROOT}"
log "Runner=${PY_RUNNER}"
log "Overwrite: base=${OVERWRITE_BASE} variants=${OVERWRITE_VARIANTS}"

# Run contexts sequentially (eco x region x year), with parallelism inside each context.
# This keeps concurrency sane while still using your MAG/MMU parallel plan.
for PRO in "${ECOS[@]}"; do
  for REGION in "${REGIONS[@]}"; do
    for YEAR in "${YEARS[@]}"; do
      set_context "$PRO" "$REGION" "$YEAR"
      run_one_context "$MAX_YEAR_GLOBAL"
    done
  done
done

log "All iterations complete."
