"""README text for a region's BugNet deliverable (used by build_deliverable.py).

render_region(f) and render_year(f) turn a dict of facts into README text.
The facts come from the delivered files, the run's parameter file and the
validation reports (see build_deliverable.readme_facts). The layout follows
the North Cascades 2026 README.

Text that needs a person's judgement (the region description, what the
classes look like) comes from the region's notes file. Anything missing is
written as a [[REVIEW: ...]] marker; build_deliverable.py will not move a
README containing a marker into the deliverable.
"""
import re
import textwrap

REVIEW = "[[REVIEW: {}]]"
NBSP = " "  # keeps a number and its unit together when wrapping

INDEX_NAMES = {
    "TCB": "Tasseled Cap Brightness",
    "TCG": "Tasseled Cap Greenness",
    "TCW": "Tasseled Cap Wetness",
    "NBR": "Normalized Burn Ratio",
}
REGION_NAMES = {6: "Pacific Northwest Region", 10: "Alaska Region"}
CRS_NAMES = {"EPSG:5070": "NAD83 / CONUS Albers", "EPSG:3338": "NAD83 / Alaska Albers"}
FIRE_SOURCES = {"mtbs": "MTBS", "wfigs": "WFIGS", "mtbs_wfigs": "MTBS and WFIGS"}
FIRE_LIMITATIONS = {
    "mtbs": "The fire mask uses MTBS only, which can lag the most recent fires.",
    "wfigs": "The fire mask uses WFIGS perimeters only.",
    "mtbs_wfigs": "The fire mask combines MTBS and WFIGS perimeters; WFIGS adds\n"
                  "    recent fires that MTBS has not mapped yet.",
}
CLASSED_CODES = [(0, "no excluded high-magnitude disturbance"), (20, "clearcut"),
                 (21, "partial harvest"), (30, "development"), (40, "fire")]


def review(what):
    return REVIEW.format(what)


def no_exclusion(p):
    """True when the run masked no high-magnitude disturbances (exclusion_classes=[])."""
    return (p.get("run_manifest_exclusion_mode") == "explicit"
            and str(p.get("exclusion_classes", "x")) in ("", "[]"))


def attributes_already_corrected(v):
    """True when the run itself wrote the corrected attributes, so the correction step changed none of them."""
    unb = v["sum_unbuffered_acres_before"] / v["sum_unbuffered_acres_after"]
    buf = v["sum_buffered_acres_after"] / v["sum_buffered_acres_before"]
    return not v["fields_only_before"] and not v["fields_only_after"] and abs(unb - 1) < 1e-3 and abs(buf - 1) < 1e-3


def wrap(text, width=77, indent="", first=None):
    text = re.sub(r"[ \t\n]+", " ", text).strip()  # not str.split(): it would split at NBSP too
    out = textwrap.fill(text, width=width,
                        initial_indent=indent if first is None else first,
                        subsequent_indent=indent, break_on_hyphens=False)
    return out.replace(NBSP, " ")


def heading(text, char="-"):
    return f"{text}\n{char * len(text)}"


def human_size(nbytes):
    for unit, scale in (("GB", 1e9), ("MB", 1e6)):
        if nbytes / scale >= 0.5:
            v = nbytes / scale
            return f"{v:.0f} {unit}" if v >= 10 else f"{v:.1f} {unit}"
    return f"{nbytes / 1e3:.0f} KB"


def pct(x, digits):
    return f"{x * 100:.{digits}f}%"


def upper_bound_pct(x):
    """|x| as a percentage, rounded up to one significant figure (e.g. 0.00003%)."""
    import math
    p = abs(x) * 100
    if p == 0:
        return "0%"
    e = math.floor(math.log10(p))
    v = math.ceil(round(p / 10 ** e, 9)) * 10 ** e
    return f"{v:.{max(0, -e)}f}%"


def _files(f):
    rows = [(f["files"]["polygons"], f"Final product: decline polygons (GeoPackage, {f['n_polygons']:,} polygons)."),
            (f["files"]["bugnet_class"], "Pixel-level decline map with its BugNet class (the raster the\n"
                                         "      polygons were built from)."),
            (f["files"]["fitted"], f"LandTrendr-fitted spectral values, {f['fitted']['n_bands']} bands "
                                   f"({len(f['fitted']['indices'])} indices x {f['fitted']['first']}-{f['fitted']['last']}),\n"
                                   "      for forest pixels."),
            (f["files"]["classed"], "All 0: this version excludes no high-magnitude disturbances\n"
                                    "      (section 6)." if no_exclusion(f["run"]) else
                                    "High-magnitude disturbances excluded from the analysis (fire,\n"
                                    "      harvest, development)."),
            (f["files"]["forest_mask"], "Forest pixels that were analysed for decline."),
            (f["files"]["parameters"], f"Every setting used by the run (one row, {f['parameters']['n_columns']} columns).")]
    sizes = ["~" + human_size(f["sizes"][name]) for name, _ in rows]
    col = max(len(name) for name, _ in rows) + 4 + max(len(s) for s in sizes)
    out = []
    for (name, desc), s in zip(rows, sizes):
        out.append("  " + name + s.rjust(col - len(name)))
        out.append("      " + desc)
    return "\n".join(out)


def _class_table(f):
    widths, header = [7, 14, 15, 16, 14], ["Class", "NBR (x1000)", "TCW", "TCG", "TCB"]
    rows = []
    for c in f["classes"]:
        rows.append([str(c["class"])] + [f"{round(c[i][0])} -> {round(c[i][1])}" for i in ("NBR", "TCW", "TCG", "TCB")]
                    + [f"{c['pixels']:,}"])
    widths = [max(w, max(len(r[i]) for r in rows) + 2) for i, w in enumerate(widths)]
    line = lambda cells: "  " + "".join(c.ljust(w) for c, w in zip(cells, widths)) + cells[-1]
    return "\n".join([line(header + ["pixels"]), line(["-" * (w - 2) for w in widths] + ["-------"])]
                     + [line(r) for r in rows])


def _band_list(f):
    out, start = [], 1
    for idx in f["fitted"]["indices"]:
        n = len(f["fitted"]["years"])
        rng = f"{start}-{start + n - 1}"
        first, last = f["fitted"]["first"], f["fitted"]["last"]
        out.append(f"{rng.rjust(15)}   {idx}_ftv_{first} ... {idx}_ftv_{last}   {INDEX_NAMES.get(idx, review('index ' + idx))}")
        start += n
    return "\n".join(out)


def _ranges(f):
    parts = []
    for idx in f["fitted"]["indices"]:
        lo, hi = f["fitted"]["p5_p95"][idx]
        parts.append(f"{idx}{NBSP}{lo:,}{NBSP}to{NBSP}{hi:,}")
    text = (f"Ranges in this file, {f['fitted']['last']} bands (5th-95th percentile of valid pixels): "
            + "; ".join(parts) + ".")
    if f["fitted"]["nbr_max"] > 1000:
        text += (" Fitted values can fall slightly outside an index's natural range "
                 f"(e.g. NBR up to {f['fitted']['nbr_max']:,}) because they come from LandTrendr's "
                 "line fit, not directly from imagery.")
    return wrap(text, width=76, indent=" " * 9)


def _decline(f):
    p = f["run"]
    if p["decline_method"] != "persistence":
        return "      " + review(f"describe decline_method {p['decline_method']!r}")
    tcg, tcw, step = int(p["decline_thresholds_tcg"]), int(p["decline_thresholds_tcw"]), int(p["decline_step"])
    if tcg != tcw:
        return "      " + review(f"describe persistence thresholds TCG {tcg} / TCW {tcw}")
    t, y = f["target"], f["target"]
    older = ", ".join(str(tcw - step * i) for i in (1, 2, 3))
    return (f"      The last five years, {y - 4}-{y}, form four year-pairs. A pair counts as\n"
            "      declining when BOTH Tasseled Cap Greenness and Wetness drop by more than\n"
            f"      a threshold from one year to the next. The threshold is {tcw} for the\n"
            f"      newest pair ({t - 1}-{t}) and {step} lower for each older pair: {older}.\n"
            f"      A pixel is declining if at least {f['min_years_declining']} of the 4 pairs count. (TCB\n"
            f"      threshold {p['decline_thresholds_tcb']} is configured but not used by this method.)")


def _validation(f):
    v, a, r = f["vs_original"], f["alignment"], f["rasters"]
    per = a["per_polygon_rel_diff"]
    n = f["n_polygons"]
    within = ("Every polygon\n    agrees within 1%" if per["n_within_1pct"] == n
              else f"{per['n_within_1pct']:,} of {n:,}\n    polygons agree within 1%")
    lab = a["bnet_label_equals_raster_mode"]
    if lab["equal"] == n:
        label = f"  - bnet_label equals the class raster's most common value in all {n:,}\n    polygons."
    else:
        label = (f"  - bnet_label equals the class raster's most common value in {lab['equal']:,} of {n:,}\n"
                 "    polygons. Earth Engine weights edge pixels by partial coverage, while\n"
                 "    this check counts pixel centres, so polygons whose classes are nearly\n"
                 "    tied can differ.")
    area = a["polygon_area_raster_vs_ACRES_total_rel_diff"]
    px, px_ee = a["unbuffered_pixels_also_in_class_raster"], a["unbuffered_pixel_count_sum_from_asset"]
    count = ("exactly the pixel count recorded in Earth Engine" if px == px_ee
             else f"vs {px_ee:,} recorded in Earth Engine")
    same = a["unbuffered_pixels_label_equals_class"]
    same = ("Every\n    one has the same class as its patch label." if same == px
            else f"{same:,}\n    of them have the same class as their patch label.")
    counts = r["valid_counts"]
    return f"""Polygons (validation_vs_original_asset.json, validation_gpkg_checks.txt)
  - {n:,} polygons, geometries identical to the original Earth Engine asset.
  - The {len(v['unchanged_fields_checked'])} unchanged attributes match on every polygon.
  - The GeoPackage matches the Earth Engine asset.
  - ACRES matches a local recomputation from geometry (within {upper_bound_pct(f['acres_max_rel_diff'])}).
Rasters (validation_rasters.txt)
  - Each file's grid, data type, NoData value and band names match the asset.
  - Values were compared with Earth Engine at {r['points']:,} random pixels per raster
    (all bands; {r['values_compared']:,} values), read through a separate Earth Engine path
    from the download: {r['mismatches']} mismatches.
  - Valid-pixel counts are identical to Earth Engine for all {r['bands']} bands:
      classed image {counts['classed']:,}; fitted image {counts['fitted']:,} per band;
      forest mask {counts['forest_mask']:,}; class raster {counts['bugnet_class']:,}.
  - Footprints nest as expected: class raster pixels lie within forest mask
    = 1. The forest mask lies within the fitted image, which lies within the
    region.
Polygons vs rasters (validation_alignment.json, area-weighted)
  - Detected pixels (unbuffered patches) rasterized onto the class raster:
    {px:,} pixels, {count}. {same}
  - Detected area: {a['detection_area_acres_from_raster']:,.1f} acres from exact-area pixels vs {a['sum_unbuffered_acres_in_gpkg']:,.1f} acres
    from the polygons' unbuffered_acres (difference {pct(a['detection_area_raster_vs_gpkg_rel_diff'], 3)}). {within} (median {pct(per['median'], 3)}, max {pct(per['max_abs'], 2)}; the small residual is pixel
    outlines vs pixel centres).
  - No detected pixel lies outside the polygons.
{label}
  - Polygon area from pixel centres is {pct(abs(area), 1)} {'above' if area >= 0 else 'below'} ACRES, as expected,
    because the {f['run']['bnet_buffer']} m buffers are not pixel-aligned."""


def render_region(f):
    p, t, fit = f["run"], f["target"], f["fitted"]
    files = f["files"]
    crs = f["equal_area_crs"]
    lt = lambda k: p[f"lt_params_run_params_{k}"]
    ltb = lambda k: str(lt(k)).lower() if isinstance(lt(k), bool) else lt(k)
    wild = str(p.get("wild_path_on")) in ("1", "True", "true")
    fire = FIRE_SOURCES.get(p["fire_mask_source"], review(f"fire_mask_source {p['fire_mask_source']!r}"))
    fy0, fy1 = f["fire_window"]
    v = f["vs_original"]
    unb_ratio = v["sum_unbuffered_acres_before"] / v["sum_unbuffered_acres_after"]
    buf_change = v["sum_buffered_acres_after"] / v["sum_buffered_acres_before"] - 1
    asset_note = ""
    if fit["asset_years"] != (fit["first"], fit["last"]):
        asset_note = wrap(f"The Earth Engine asset is named {p['fitted_img_p']}, but it contains all years "
                          f"{fit['first']}-{fit['last']}. This file is named after what it actually contains.",
                          width=76, indent=" " * 9, first="Note:    ") + "\n"
    classed_note = ""
    if f["classed_asset_bits"] != 8:
        classed_note = (f"Note:    the Earth Engine asset stores this as {f['classed_asset_bits']}-bit integers. It was\n"
                        "         written here as 8-bit; all values (0-40) are preserved exactly.\n")
    wild_sentence = (" Inside wilderness and National Park Service land only fire (40) is excluded." if wild else "")
    wild_b = (f" In wilderness ({p['wild_path_path'].rsplit('/', 1)[-1]})\n"
              "      and National Park Service land, only fire is excluded." if wild else "")
    class_values = ", ".join(str(c["class"]) for c in f["classes"])
    class_list = class_values.rsplit(", ", 1)[0] + " or " + class_values.rsplit(", ", 1)[1]
    git = (f"Pipeline revision: {f['pipeline_revision']}." if f["pipeline_revision"]
           else "The run did not record a git commit.")
    code = f["code"]
    exp = f"(contains {fit['first']}-{fit['last']})" if asset_note else ""
    compute = p.get("compute_project") or p["project_name"]
    compute_note = ("" if compute == p["project_name"] else "\n" + wrap(
        f"The Earth Engine processing ran in project {compute} (compute_project in the "
        f"parameters); every asset was written to {p['project_name']}. Results do not "
        "depend on the compute project.", indent="  ") + "\n")
    fits = [s.strip() for s in str(p["fit"]).split(",")]
    noex = no_exclusion(p)
    intro = ("insects and disease) from the Landsat time series. BugNet normally also\n"
             "excludes abrupt, high-magnitude disturbances classified as fire, harvest\n"
             "or development; THIS VERSION EXCLUDES NONE (sections 6 and 9b)." if noex else
             "insects and disease) from the Landsat time series. It excludes abrupt,\n"
             "high-magnitude disturbances such as fire, harvest and development.")
    version_note = ("\n\n" + wrap(f["notes"]["version_note"])) if f["notes"].get("version_note") else ""
    if f["notes"].get("composite_note"):
        window_lines = wrap(f"imagery, {p['ltstartYear']}-{p['ltendYear']} ({f['notes']['composite_note']}).", indent="      ")
    else:
        window_lines = (f"      imagery, {p['ltstartYear']}-{p['ltendYear']} (the {t} window ended on the run date,\n"
                        f"      {f['run_date']}).")
    if noex:
        classed_heading = "6. CLASSED IMAGE (ALL ZERO IN THIS VERSION)"
        classed_text = wrap(
            f"What it is: in other BugNet versions, abrupt high-magnitude disturbances detected in "
            f"{p['change_params_years_start']}-{p['change_params_years_end']}, classified by a random forest, "
            f"buffered by 100{NBSP}m and excluded from decline detection. This version applies no "
            "classifier-based exclusion (exclusion_classes is empty in the parameters), so every pixel is 0 "
            "and nothing was excluded by this image. It is delivered so the file set matches other regions.",
            width=78)
        step_b = wrap(
            f"{p['change_params_sort'].capitalize()} {p['change_params_delta']} in {p['change_params_years_start']}-"
            f"{p['change_params_years_end']} with magnitude {p['change_params_mag_operator']} {p['change_params_mag_value']} "
            f"were detected and classified by a random forest ({p['num_trees']} trees, trained on "
            f"{f['training_year']} reference polygons), as in other versions, but NO class was excluded: "
            "the classifier output is not used by this version.", indent="      ") + "\n        -> classed image (section 6, all 0)"
        mask_bullet = "  - no excluded high-magnitude disturbance (always true here: none are\n    excluded, section 6);"
    else:
        classed_heading = "6. CLASSED IMAGE (EXCLUDED DISTURBANCES)"
        classed_text = None
        step_b = None
        mask_bullet = "  - no excluded high-magnitude disturbance (classed image = 0);"
    if attributes_already_corrected(v):
        attributes_block = wrap(
            f"This run wrote the corrected IDS attributes itself (equal-area acreage, ACRES, REGION_ID, "
            f"US_AREA, FEATURE_USER_ID, bnet_label). The {f['correction_date']} correction step "
            "recalculated them and found the same values; it only set MODIFIED_DATE.")
    else:
        attributes_block = f"""On {f['correction_date']} the polygon ATTRIBUTES were recalculated:
  - unbuffered_acres was overstated by about {unb_ratio:.1f}x: it was computed as pixel
    count x {int(p['pixel_scale']) ** 2} m2, but pixels here are about {f['pixel_area_m2']} m2. It is now measured from
    geometry.
  - pct_affected followed (mean {v['pct_affected_before']['mean']:.1f} -> {v['pct_affected_after']['mean']:.1f}; none now exceed 100).
  - ACRES was 0; it is now the polygon area.
  - buffered_acres is now computed in an equal-area projection ({buf_change * 100:+.1f}%).
  - REGION_ID, US_AREA, FEATURE_USER_ID and MODIFIED_DATE now use the IDS
    values in section 3.
  - bnet_label had been dropped; it was restored by recomputing it the way
    the run did. The classification was not rerun.
If you used an earlier copy of these polygons, the geometries are the same;
use this version's acreage and pct_affected."""
    step_b_block = (" b) High-magnitude disturbances (NOT excluded in this version)\n" + step_b if noex else
                    f""" b) High-magnitude disturbances to exclude
      {p['change_params_sort'].capitalize()} {p['change_params_delta']} in {p['change_params_years_start']}-{p['change_params_years_end']} with magnitude {p['change_params_mag_operator']} {p['change_params_mag_value']}, duration {p['change_params_dur_operator']} {p['change_params_dur_value']} years,
      pre-disturbance value {p['change_params_preval_operator']} {p['change_params_preval_value']}, at least {p['change_params_mmu_value']} pixels. Classified by a random
      forest ({p['num_trees']} trees, trained on {f['training_year']} reference polygons). Classes 20-40
      excluded and buffered 100 m.{wild_b}
        -> classed image (section 6)""")

    title = f"BugNet {t} - {f['display']} - version {f['tag']}"
    return f"""{heading(title, "=")}

Survey year:     {t}
{wrap(f['notes']['region'], width=77, indent=' ' * 17, first='Region:          ')}
Version:         {f['tag']}. Its settings are listed under RUN SETTINGS; do not
                 assume they match v{t - 1}-{f['version']}.
BugNet run:      {f['run_date']}
Polygon attributes corrected: {f['correction_date']}
Rasters and parameters exported: {f['export_date']}
Contact:         {f['notes']['contact']}

BugNet maps gradual forest decline (the kind of slow canopy loss caused by
{intro}{version_note}


{heading("1. FILES")}
{_files(f)}
  validation/
      Checks of each delivered file against Earth Engine (see section 10).

Start here: open the polygons, or the BugNet class raster, over a basemap.


{heading("2. COMMON PROPERTIES OF ALL RASTERS")}
  CRS               EPSG:4326 (WGS84 longitude/latitude)
{wrap(f"{f['pixel_size_deg']!r} degrees (nominally {p['pixel_scale']}{NBSP}m). At this latitude that is about {f['pixel_ns_m']}{NBSP}m north-south by {f['pixel_ew_m']}{NBSP}m east-west, i.e. about {f['pixel_area_m2']}{NBSP}m2 per pixel, not {int(p['pixel_scale']) ** 2}{NBSP}m2.", indent=' ' * 20, first='  Pixel size        ')}
{wrap(f"{f['grid_width']:,} columns x {f['grid_height']:,} rows; upper-left corner {f['grid_origin'][0]!r}, {f['grid_origin'][1]!r}. All four rasters share this exact grid, which is the grid stored in Earth Engine. Pixels line up one-to-one, with no resampling.", indent=' ' * 20, first='  Grid              ')}
  Format            GeoTIFF, internally tiled 256x256, DEFLATE compression
                    (lossless). Opens directly in QGIS, ArcGIS Pro and GDAL.
  NoData            Declared in each file (see below). It covers pixels
                    outside the region, plus pixels each product does not
                    cover. QGIS and ArcGIS read it automatically.
{wrap(f"Do not measure area in degrees. Reproject to an equal-area CRS (e.g. {crs}, {CRS_NAMES[crs]}), or use about {f['pixel_area_m2']}{NBSP}m2 per pixel at {f['pixel_lat']}{NBSP}N.", indent=' ' * 20, first='  Area              ')}


{heading(f"3. POLYGONS - {files['polygons']}")}
Layer:  {f['layer']} ({f['n_polygons']:,} polygons)
CRS:    EPSG:4326

{wrap(f"How the polygons were made: declining pixels were grouped into connected patches (diagonal neighbours count). Patches of MORE THAN {f['mmu']} pixels (i.e. at least {f['mmu'] + 1}, about {f['mmu_ha']:.2f}{NBSP}ha here) were kept. Each kept patch was buffered by {p['bnet_buffer']}{NBSP}m, and buffers that touched or overlapped were merged. So one polygon can contain several detected patches plus the {p['bnet_buffer']}{NBSP}m margin around them:")}
  - buffered_acres is the whole polygon;
  - unbuffered_acres is the detected pixels inside it;
  - pct_affected is the share of the polygon that was detected.

"{f['variant'].split('_')[0]}" is the TCW decline threshold ({p['decline_thresholds_tcw']}); "{f['variant'].split('_')[1]}" is the {f['mmu']}-pixel minimum
mapping unit.

Field names follow the USFS Insect and Disease Survey (IDS) damage-areas
schema where an equivalent exists.

  Field              Type     Units / values
  -----------------  -------  ----------------------------------------------
  ACRES              real     acres. Polygon area (same as buffered_acres; in
                              IDS, ACRES is the gross polygon area).
  buffered_acres     real     acres. Polygon area in {crs}
                              (equal-area).
  unbuffered_acres   real     acres. Area of the detected pixels inside the
                              polygon, in {crs}.
  pct_affected       real     percent, 0-100. unbuffered_acres /
                              buffered_acres x 100. A geometric ratio; NOT
                              the IDS PERCENT_AFFECTED severity class. Range
                              here {f['pct_range'][0]:.1f}-{f['pct_range'][1]:.1f}.
  bnet_label         integer  {class_list}. BugNet class of the polygon: the
                              most common class of the BugNet class raster
                              within the polygon (section 4).
  SURVEY_YEAR        integer  {t}.
  REGION_ID          integer  USFS region: {f['region_id']} ({REGION_NAMES.get(f['region_id'], review('region name'))}).
                              Earlier BugNet products stored the text "{p['study_region']}"
                              here.
  US_AREA            text     "{f['us_area']}".
  CREATED_DATE       text     MM-DD-YYYY the polygons were produced:
                              {f['created_date']}.
  MODIFIED_DATE      text     MM-DD-YYYY the attributes were corrected:
                              {f['modified_date']}.
  FEATURE_USER_ID    text     "{f['feature_user_id']}".
  DAMAGE_TYPE, DCA, HOST, HOST_GROUP, NOTES
                     text     IDS fields not populated by BugNet: "null".
  DAMAGE_TYPE_CODE, DCA_CODE, HOST_CODE, HOST_GROUP_CODE
                     integer  IDS fields not populated by BugNet: 0.

BugNet does not identify the causal agent or host. The polygons mark where
decline was detected, not what caused it.


{heading(f"4. BUGNET CLASS RASTER - {files['bugnet_class']}")}
Bands:   1, "{f['band_names']['bugnet_class']}"
Type:    unsigned 8-bit integer
Values:  {class_values} = BugNet class of a declining pixel (see below)
         {'255'.ljust(len(class_values))} = NoData: pixel not detected as declining, outside the
         {' ' * len(class_values)}   forest mask, or outside the region

Every non-NoData pixel was detected as declining (method in section 9). The
pixels were then grouped into {p['num_of_clusters']} classes by k-means clustering of their
fitted spectral trajectories (the {fit['n_bands']} bands of the fitted image plus the
decline score). The class numbers are cluster IDs. They are NOT ordered by
severity, and they are not tied to a cause.

{wrap(f"{f['notes']['class_summary']} Mean fitted values per class in this region ({f['class_years'][0]} -> {f['class_years'][1]}):")}

{_class_table(f)}

{wrap(f['notes']['class_notes'], indent='  ')}

{wrap(f"Not every declining pixel is inside a polygon: {f['sub_mmu_share'] * 100:.0f}% of the class pixels are in patches of {f['mmu']} pixels or fewer, which the polygon MMU dropped. Use the raster to see them; use the polygons for the mapped product.")}


{heading(f"5. FITTED IMAGE - {files['fitted']}")}
Bands:   {fit['n_bands']}, named <INDEX>_ftv_<YEAR>, in this order:
{_band_list(f)}
         Band n of each index is year {fit['first'] - 1}+n. Band names are stored in the
         file and shown by QGIS/ArcGIS.
Type:    signed 16-bit integer
NoData:  -32768: not forest in the JRC Global Forest Cover 2020 map, or
         outside the region. The fitted image was computed only for JRC forest
         pixels ({f['jrc_share'] * 100:.0f}% of the region); every pixel analysed by BugNet has values.
Values:  LandTrendr "fitted-to-vertex" (ftv) values: each pixel's annual
         Landsat value, smoothed by LandTrendr's piecewise-linear fit. Each
         band is the fitted value for that year's {f['composite_window']}
         composite.
           TCB, TCG, TCW: Tasseled Cap transform (Crist 1985 coefficients) of
                          surface reflectance scaled x10,000.
           NBR:           (NIR - SWIR2) / (NIR + SWIR2) x 1,000.
{_ranges(f)}
         Decline appears as a drop in NBR, TCW and TCG over time.
{asset_note}Size:    {human_size(f['sizes'][files['fitted']])} compressed (~{fit['uncompressed_gb']:.0f} GB uncompressed). For quick viewing, display one band (e.g. band
         {fit['n_bands']}, {fit['last_band']}) or build pyramids/overviews in QGIS or ArcGIS.


{heading(f"{classed_heading} - {files['classed']}")}
Bands:   1, "{f['band_names']['classed']}"
Type:    unsigned 8-bit integer
Values:  {chr(10).join((' ' * 9 if i else '') + f'{c:<3} = {d}' for i, (c, d) in enumerate(CLASSED_CODES))}
         255 = NoData (outside the region)
{classed_text or wrap(f"What it is: abrupt, high-magnitude disturbances detected in {p['change_params_years_start']}-{p['change_params_years_end']} and classified by a random forest. They were buffered by 100{NBSP}m and EXCLUDED from decline detection.{wild_sentence} This is a mask of what BugNet ignored, not a product of BugNet decline.", width=78)}
{classed_note}

{heading(f"7. FOREST MASK - {files['forest_mask']}")}
Bands:   1, "{f['band_names']['forest_mask']}"
Type:    unsigned 8-bit integer
Values:  1   = forest analysed for decline
         0   = forest (per JRC 2020) but excluded from analysis
         255 = NoData: not forest in the JRC Global Forest Cover 2020 map, or
               outside the region
A pixel is 1 only if ALL of these hold:
  - forest in USFS LCMS (Landscape Change Monitoring System) land use, {f['lcms_year']};
  - forest in JRC Global Forest Cover 2020;
{mask_bullet}
  - outside {fire} fire perimeters, {fy0}-{fy1};
  - {t} fitted Tasseled Cap Brightness <= {p['brightness_value']} (removes bright, non-canopy
    pixels).
Decline detection (section 4) was run only on pixels where this mask is 1.


{heading(f"8. PARAMETERS - {files['parameters']}")}
One row, {f['parameters']['n_columns']} columns: every setting of the run, as recorded by the run
itself (Earth Engine table {p['parameter_file']}).
Columns are sorted by name, after "system:index". Nested settings are
flattened with "_", e.g. change_params_mag_value. "GEE object" marks
settings that were Earth Engine objects (e.g. the region outline). The last
column, ".geo", is {f['parameters']['geo_text']}. The main settings are
summarised in section 9.


{heading("9. HOW BUGNET MADE THESE PRODUCTS (run settings from the parameter file)")}
{wrap(f'Run profile "{f["profile"][0]}" ({f["profile"][1]}); shared version {p.get("shared_version", p["version"])}. {git}')}

 a) Landsat time series and fitting
      Annual Landsat ({p['pixel_scale']} m) medoid composites of {f['composite_window']}
{window_lines}
      LandTrendr {p['ltstartYear']}-{p['ltendYear']}, segmentation index {p['index']}; fitted bands {', '.join(fits[:2])},
      {', '.join(fits[2:])}. Settings: maxSegments {ltb('maxSegments')}, spikeThreshold {ltb('spikeThreshold')},
      vertexCountOvershoot {ltb('vertexCountOvershoot')}, preventOneYearRecovery {ltb('preventOneYearRecovery')},
      recoveryThreshold {ltb('recoveryThreshold')}, pvalThreshold {ltb('pvalThreshold')}, bestModelProportion {ltb('bestModelProportion')},
      minObservationsNeeded {ltb('minObservationsNeeded')}.  -> fitted image (section 5)

{step_b_block}

 c) Forest mask (criteria in section 7). Fire perimeters: {fire}, {fy0}-{fy1}.
        -> forest mask (section 7)

 d) Decline detection: "{p['decline_method']}" method
{_decline(f)}

 e) Classes: k-means, {p['num_of_clusters']} clusters ({p['kmeans_num_sample']}-point sample).
        -> BugNet class raster (section 4)

 f) Polygons: patches > {f['mmu']} pixels, {p['bnet_buffer']} m buffer, overlaps merged.
        -> polygons (section 3)


{heading("10. VALIDATION (files in validation/)")}
{_validation(f)}


{heading("11. DETECTION RESULTS VS. CORRECTED POLYGON ATTRIBUTES")}
The BugNet detection and classification results are UNCHANGED from the
{f['run_date']} run: the declining pixels, all rasters, the polygon geometries,
the polygon count ({f['n_polygons']:,}) and each polygon's class.

{attributes_block}


{heading(f"12. SOURCE EARTH ENGINE ASSETS (project {p['project_name']}, folder {f['asset_folder']})")}
  Polygons (corrected; source of the GeoPackage)
      {p['bnet_buffered_polygons']}_corrected
  Polygons (original, unchanged)
      {p['bnet_buffered_polygons']}
  Unbuffered detected patches (used for unbuffered_acres)
      {p['bnet_polygonized']}
  BugNet class raster      {p['predicted']}
  Fitted image             {p['fitted_img_p']}{' ' + exp if exp else ''}
  Classed image            {p['rasterize_classes']}
  Forest mask              {p['forestMaskName']}
  Parameters               {p['parameter_file']}
  Full path prefix: {p['assetDir']}
{compute_note}
Code (lt-bnet-py, branch {code['branch']}, {code['url']}):
  - tools/correct_polygon_schema.py: polygon attribute correction
    ({code['correction']}).
  - tools/download_ee_raster.py: raster download, on the asset grid via
    Earth Engine computePixels (commit {code['download']}).
  - tools/validate_ee_raster.py: raster checks (commit {code['download']}).
  - tools/build_deliverable.py: GeoPackage, parameter CSV, alignment check
    and this README (commit {code['build']}).


{heading("13. KNOWN LIMITATIONS")}
  - Only one product variant was produced in {t} (TCW decline threshold
    {p['decline_thresholds_tcw']}, {f['mmu']}-pixel MMU).
  - {FIRE_LIMITATIONS.get(p['fire_mask_source'], review('fire mask limitation'))}
  - BugNet classes are k-means clusters, not causes or severity levels.
  - The IDS damage, host and agent fields are placeholders.
  - The rasters are in geographic coordinates (EPSG:4326). Pixel area varies
    with latitude.
"""


def region_entry(prefix, export_date):
    col = max(35, len(prefix) + 6)
    pad = " " * col
    return (f"  {prefix.ljust(col - 2)}complete: polygons, BugNet class raster,\n"
            f"{pad}fitted image, classed image, forest mask,\n"
            f"{pad}parameters ({export_date})")


def render_year(f):
    title = f"BugNet Region {f['region_id']} products - {f['target']}"
    tag = f"v{f['target']}-{f['version']}"
    return f"""{heading(title, "=")}

One folder per region, named Bugnet_<Region>_{tag}. Every file in a folder
starts with the folder name:

  Bugnet_<Region>_{tag}/
    README.txt                          what the region's products are, the
                                        run settings, fields, provenance
    Bugnet_<Region>_{tag}_polygons_{f['variant']}.gpkg
                                        final polygons (GeoPackage)
    Bugnet_<Region>_{tag}_<raster>.tif
                                        raster products (GeoTIFF, one file each)
    Bugnet_<Region>_{tag}_parameters_{f['variant']}.csv
                                        run parameters
    validation/                         checks of the delivered files

Regions available
{region_entry(f['prefix'], f['export_date'])}

Differences from earlier products
  {review("compare with this region's earlier products in Box before delivery")}
  - Polygon attributes follow the USFS IDS schema. ACRES, buffered_acres,
    unbuffered_acres and pct_affected are measured in an equal-area
    projection. REGION_ID is an integer USFS region ({f['region_id']}), not the text
    "{f['study_region']}".
  - The minimum mapping unit (MMU) is in pixels: "{f['mmu']}mmu" keeps detections of
    more than {f['mmu']} pixels.

Contact: {f['contact']}
"""


def add_region_to_year(text, prefix, export_date):
    """Insert a region's entry into an existing year README's region list."""
    if f"  {prefix} " in text:
        return text
    head = "Regions available\n"
    start = text.index(head) + len(head)
    end = text.index("\n\n", start)
    return text[:end] + "\n" + region_entry(prefix, export_date) + text[end:]
