#!/usr/bin/env python3
"""
Organize BugNet exports:
- Builds a single root: Project_Region_Version_Annual_Change (underscores, no spaces)
- Moves:
    * GeoTIFFs (and sidecars) -> root
    * Shapefiles -> root/Shapefiles/<basename>/
    * Parameter CSVs -> root/Parameters/
- Merges chunked rasters in root with gdal_merge.py (both -00000 and -##########-########## styles)
- Writes metadata AFTER merges:
    * One overall METADATA.txt in root
    * One METADATA.txt in Parameters/
    * One per-image <basename>_METADATA.txt in root (merged output name if merged)
    * One METADATA.txt in each Shapefiles/<basename>/ folder
"""

import argparse, re, shutil, sys, datetime, subprocess
from pathlib import Path

# ---------------- Config ----------------
SHAPE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx", ".fix"}
TIF_SIMPLE = {".tif", ".tiff"}

# Common lead (non-parameter files)
LEAD = r"^(?P<project>[A-Za-z0-9]+)_(?P<region>[a-z0-9\-]+)_(?P<ver>v(?P<year>\d{4})-(?P<vernum>\d+))_Annual_Change_"
PATTERNS = {
    "fitted": re.compile(LEAD + r"A_predictor_fitted_img_(?P<y1>\d{4})_(?P<y2>\d{4})$", re.I),
    "classed": re.compile(LEAD + r"C4_classed_img_(?P<prod_year>\d{4})$", re.I),
    "mask":   re.compile(LEAD + r"D_bugnet_forest_mask_(?P<prod_year>\d{4})$", re.I),
    "polys":  re.compile(LEAD + r"bugnet_polygons_buffered_(?P<prod_year>\d{4})_mag(?P<mag>\d+)_(?P<mmu>\d+)mmu$", re.I),
}
# Parameter CSVs: region is before "-bugnet"
PARAMS = re.compile(
    LEAD + r"(?P<region2>[a-z0-9\-]+)-bugnet_mag(?P<mag>\d+)_(?P<mmu>\d+)mmu_parameter_file$", re.I
)

# Chunk suffix patterns on STEM (no extension): -00000 or -##########-##########
CHUNK_STEM_RE = re.compile(r"-(\d{5,})(?:-(\d{5,}))?$", re.IGNORECASE)

# ---------------- Helpers ----------------
def pretty_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()

def clean_component(s: str) -> str:
    s = s.strip().replace(" ", "_")
    return re.sub(r"__+", "_", s)

def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf = p.stem, p.suffix
    i = 1
    while True:
        cand = p.with_name(f"{stem}__{i}{suf}")
        if not cand.exists():
            return cand
        i += 1

def write_text(path: Path, text: str, overwrite: bool, dry: bool):
    if path.exists() and not overwrite:
        return
    if dry:
        print(f"[DRY] write {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

def move(src: Path, dst: Path, dry: bool):
    dst = unique_path(dst)
    if dry:
        print(f"[DRY] mv {src} -> {dst}")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

def strip_compound_tif(name: str) -> str:
    ln = name.lower()
    if ln.endswith(".tif.aux.xml"):
        return name[:-len(".tif.aux.xml")]
    if ln.endswith(".tif.ovr"):
        return name[:-len(".tif.ovr")]
    return name

def is_tif_like(p: Path) -> bool:
    pl = str(p).lower()
    return (p.suffix.lower() in TIF_SIMPLE) or pl.endswith(".tif.aux.xml") or pl.endswith(".tif.ovr")

def parse_params_tokens(stem: str):
    m = PARAMS.match(stem)
    if not m:
        return None
    gd = m.groupdict()
    region_slug = gd.get("region2") or gd.get("region")
    return {
        "project": gd.get("project"),
        "region_slug": region_slug,
        "region_pretty": pretty_from_slug(region_slug),
        "ver": gd.get("ver"),
        "year": gd.get("year"),
        "vernum": gd.get("vernum"),
    }

def parse_general_tokens(stem: str):
    for rx in PATTERNS.values():
        m = rx.match(stem)
        if m:
            gd = m.groupdict()
            region_slug = gd.get("region")
            return {
                "project": gd.get("project"),
                "region_slug": region_slug,
                "region_pretty": pretty_from_slug(region_slug),
                "ver": gd.get("ver"),
                "year": gd.get("year"),
                "vernum": gd.get("vernum"),
            }
    return None

def classify_kind(stem: str):
    m = PARAMS.match(stem)
    if m: return "params", m.groupdict()
    for kind, rx in PATTERNS.items():
        mm = rx.match(stem)
        if mm: return kind, mm.groupdict()
    if re.search(r"polygons_buffered_\d{4}_mag\d+_\d+mmu$", stem, re.I):
        return "polys", {}
    return None, {}

def overall_metadata(tokens: dict) -> str:
    return f"""=== BugNet Workflow Metadata ===
Project: {tokens.get('project','')}
Region: {tokens.get('region_pretty','')}
Version: {tokens.get('ver','')}

General Description:
The BugNet workflow generates raster and vector products to detect and characterize insect and disease disturbances in forests. Using Landsat (30 m) and LandTrendr temporal segmentation, it produces fitted spectral data, masked/classified imagery, and polygon products representing potential disturbance.

Versioning (typical):
- V1: Baseline
- V2: Boundary layer applied; suppress harvest in non-harvest zones
- V3: Same boundary layer; higher high-magnitude threshold (e.g., 350)

Core Data Sources:
- Landsat 2020–2025
- LandTrendr temporal segmentation

"""

def per_image_metadata(filename: str, kind: str) -> str:
    base = f"File: {filename}\n"
    if kind == "fitted":
        body = """Description:
Base spectral dataset derived from LandTrendr temporal segmentation. Includes bands such as NBR, TCW, TCG, and TCB.

Role in Workflow:
Forms the foundation for disturbance detection and classification by capturing spectral change trajectories.
"""
    elif kind == "classed":
        body = """Description:
Disturbance classification (C4) derived from the fitted image. Removes high-magnitude events (e.g., fire, clearcuts, partial harvests).

Purpose:
Ensures the workflow focuses on subtle, non-stand-replacing disturbances associated with insect/disease activity.
"""
    elif kind == "mask":
        body = """Description:
Binary forest mask combining the classed image and other layers to retain forested pixels uninfluenced by high-magnitude change.

Purpose:
Restricts analysis to forest areas where insect/disease processes are relevant and reduces the pixel search space.
"""
    else:
        body = """Description:
Image produced by the BugNet workflow.
"""
    tail = "See also: root metadata for overview and versioning notes.\n"
    return "=== Image Metadata ===\n" + base + "\n" + body + tail

def shapefile_folder_metadata(foldername: str) -> str:
    return f"""=== Shapefile Bundle Metadata ===
Folder: {foldername}

Description:
Polygons represent areas of forest decline retained after masking high-magnitude events (fire/harvest). The basename encodes magnitude (e.g., mag70) and minimum mapping unit (MMU) (e.g., 10/20/30).

"""

def params_folder_metadata(tokens: dict) -> str:
    return f"""=== Parameters Metadata ===
Project: {tokens.get('project','')}
Region: {tokens.get('region_pretty','')}
Version: {tokens.get('ver','')}

Description:
This folder contains CSV files with the exact configuration used for each run (e.g., magnitude thresholds 50/60/70 and MMU 10/20/30). Use for reproducibility and traceability.
"""

def root_folder_name(tokens: dict) -> str:
    proj = clean_component(tokens.get("project",""))
    region = clean_component(tokens.get("region_pretty",""))
    ver = clean_component(tokens.get("ver",""))
    return f"{proj}_{region}_{ver}_Annual_Change"

def is_chunk_stem(stem: str) -> bool:
    return bool(CHUNK_STEM_RE.search(stem))

def base_stem_without_chunk(stem: str) -> str:
    m = CHUNK_STEM_RE.search(stem)
    return stem[:m.start()] if m else stem

# ---- GDAL merge helpers ----
def check_gdal_merge_available() -> bool:
    try:
        subprocess.run(["gdal_merge.py", "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except FileNotFoundError:
        return False

def find_chunk_groups(root: Path):
    """Return dict: base_out_name.tif -> [chunk filenames] for chunked rasters in root."""
    tifs = [p for p in root.glob("*.tif")]
    groups = {}
    for p in tifs:
        stem = p.stem
        if is_chunk_stem(stem):
            base = base_stem_without_chunk(stem) + ".tif"
            groups.setdefault(base, []).append(p.name)
    for k in list(groups.keys()):
        groups[k] = sorted(groups[k])
    return groups

def run_gdal_merge(root: Path, out_name: str, members: list[str], dry: bool, extra_args=None) -> bool:
    """Run gdal_merge.py -o out_name [extra_args] members... in 'root'. Returns True on success."""
    extra_args = extra_args or []
    cmd = ["gdal_merge.py", "-o", out_name] + extra_args + members
    if dry:
        print("[DRY] " + " ".join(cmd))
        return True
    try:
        subprocess.run(cmd, cwd=str(root), check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERR] gdal_merge.py failed for {out_name}: {e}", file=sys.stderr)
        return False

# ---------------- Main ----------------
def main():
    ap = argparse.ArgumentParser(description="Organize BugNet exports, merge chunked rasters with gdal_merge.py, then write metadata.")
    ap.add_argument("--src", required=True, help="Folder with unzipped files")
    ap.add_argument("--dest", required=True, help="Destination parent folder")
    ap.add_argument("--dry-run", action="store_true", help="Preview without moving/writing/merging")
    ap.add_argument("--overwrite-metadata", action="store_true", help="Overwrite existing metadata txt files")
    ap.add_argument("--no-merge", action="store_true", help="Do not run gdal_merge.py even if chunked tiles exist")
    ap.add_argument("--clean-chunks", action="store_true", help="Delete chunk parts after a successful merge")
    # Optional GDAL args (e.g., -n -9999 -a_nodata -9999 -co COMPRESS=LZW)
    ap.add_argument("--gdal-args", nargs="*", default=[], help="Extra arguments passed to gdal_merge.py")
    args = ap.parse_args()

    src = Path(args.src).expanduser().resolve()
    dst_parent = Path(args.dest).expanduser().resolve()
    if not src.is_dir():
        print(f"[ERR] --src is not a directory: {src}", file=sys.stderr)
        sys.exit(2)
    dst_parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in src.iterdir() if p.is_file()]
    if not files:
        print("[INFO] No files found.")
        return

    # -------- Derive tokens (favor parameter CSVs) --------
    tokens = None
    for f in files:
        nm = strip_compound_tif(f.name); stem = Path(nm).stem
        if f.suffix.lower() == ".csv":
            t = parse_params_tokens(stem)
            if t: tokens = t; break
    if not tokens:
        for f in files:
            nm = strip_compound_tif(f.name); stem = Path(nm).stem
            t = parse_general_tokens(stem)
            if t: tokens = t; break
    if not tokens:
        print("[ERR] Could not infer project/region/version from filenames.", file=sys.stderr)
        sys.exit(3)

    root = dst_parent / root_folder_name(tokens)
    shp_root = root / "Shapefiles"
    prm_root = root / "Parameters"

    if args.dry_run:
        print(f"[DRY] mkdir -p {root}")
        print(f"[DRY] mkdir -p {shp_root}")
        print(f"[DRY] mkdir -p {prm_root}")
    else:
        root.mkdir(parents=True, exist_ok=True)
        shp_root.mkdir(parents=True, exist_ok=True)
        prm_root.mkdir(parents=True, exist_ok=True)

    # Root + Parameters metadata (global only; image metadata comes AFTER merges)
    write_text(root / "METADATA.txt", overall_metadata(tokens), args.overwrite_metadata, args.dry_run)
    write_text(prm_root / "METADATA.txt", params_folder_metadata(tokens), args.overwrite_metadata, args.dry_run)

    # -------- Move files (no image metadata here) --------
    by_stem = {}
    for f in files:
        nm = strip_compound_tif(f.name)
        stem = Path(nm).stem
        by_stem.setdefault(stem, []).append(f)

    for stem, flist in sorted(by_stem.items()):
        kind, _ = classify_kind(stem)
        is_shape = any(p.suffix.lower() in SHAPE_EXTS for p in flist)
        has_tif = any(is_tif_like(p) for p in flist)
        is_param = any(p.suffix.lower() == ".csv" for p in flist)

        if is_shape:
            dst = shp_root / stem
            write_text(dst / "METADATA.txt", shapefile_folder_metadata(stem), args.overwrite_metadata, args.dry_run)
            for f in flist:
                move(f, dst / f.name, args.dry_run)

        elif is_param and not has_tif and not is_shape:
            for f in flist:
                move(f, prm_root / f.name, args.dry_run)

        else:
            for f in flist:
                move(f, root / f.name, args.dry_run)

    # -------- GDAL MERGE PHASE (in root) --------
    if not args.no_merge:
        if not check_gdal_merge_available():
            print("[WARN] gdal_merge.py not found in PATH; skipping merges. Install GDAL or use --no-merge to silence.", file=sys.stderr)
        else:
            groups = find_chunk_groups(root)
            if groups:
                print(f"[INFO] Found {len(groups)} chunked raster group(s); merging with gdal_merge.py ...")
                for out_name, members in groups.items():
                    out_path = unique_path(root / out_name)  # avoid overwriting if a single-file already exists
                    ok = run_gdal_merge(root, out_path.name, members, args.dry_run, extra_args=args.gdal_args)
                    if ok and args.clean_chunks and not args.dry_run:
                        for fn in members:
                            try:
                                (root / fn).unlink()
                            except Exception as e:
                                print(f"[WARN] Could not remove chunk {fn}: {e}", file=sys.stderr)

    # -------- IMAGE METADATA PHASE (after merges) --------
    # Build targets: prefer merged outputs; otherwise one intended base per chunked set; plus all non-chunked tifs
    tifs_now = list(root.glob("*.tif"))
    names_now = {p.name for p in tifs_now}
    final_targets = {}  # base_stem -> output_name.tif

    # From any chunk parts present, decide merged targets
    for p in tifs_now:
        if is_chunk_stem(p.stem):
            base_name = base_stem_without_chunk(p.stem) + ".tif"
            final_targets[base_stem_without_chunk(p.stem)] = base_name  # merged may or may not exist

    # Add all non-chunked tifs not already included
    for p in tifs_now:
        if not is_chunk_stem(p.stem):
            if p.stem not in final_targets:
                final_targets[p.stem] = p.name

    # If merge actually created outputs, they exist in names_now; otherwise we still document intended base
    for base_stem, out_name in sorted(final_targets.items()):
        kind, _ = classify_kind(base_stem)
        meta_name = f"{base_stem}_METADATA.txt"
        write_text(
            root / meta_name,
            per_image_metadata(out_name, kind or "image"),
            args.overwrite_metadata,
            args.dry_run
        )

    print("[OK] Done." if not args.dry_run else "[DRY] Done (no changes).")

if __name__ == "__main__":
    main()
