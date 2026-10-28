"""
Optional evidence gate on the stage-one exclusion mask ("rule D2").

filter_classes normally masks every high-magnitude patch the classifier
labels as a competing agent (harvest, development, fire). In Alaska that
removes most western blackheaded budworm defoliation, which the classifier
labels fire or partial harvest (see the 2026-10-27 evaluation in
/vol/v1/Bugnet/evaluations/pws-2026-exclusion/README.md).

With the gate on, those labelled patches are only candidates. A candidate
stays masked when independent evidence supports it:
  - fire perimeter (bnet.get_fire_polygons, same source/window as the
    forest mask) or a FIRMS hotspot within firms_buffer_m;
  - WRI drivers-of-forest-loss logging class;
  - optional FACTS harvest unit completed within yod-1 .. yod+2;
  - harvest/development label and Hansen GFC stand loss covering at least
    gfc_min_fraction of the patch within yod +/- gfc_year_tolerance.
Candidates without evidence are released back into the BugNet change space
and exported as a QA layer (released_name), with yod >= qa_flag_from_year
flagged because no independent harvest evidence covers those years yet.

Off unless param['exclusion_evidence']['on'] is truthy, so every existing
config behaves exactly as before.
"""
import ee

import bnet

GATE_DEFAULTS = {
    "harvest_classes": [20, 21, 30, 31],
    "firms_buffer_m": 1000,
    "wri_asset": "projects/landandcarbon/assets/wri_gdm_drivers_forest_loss_1km/v1_2_2001_2024",
    "wri_logging_class": 4,
    "gfc_asset": "UMD/hansen/global_forest_change_2025_v1_13",
    "gfc_min_fraction": 0.5,
    "gfc_year_tolerance": 1,
    "facts_path": "",
    "facts_year_field": "fy_completed",
    "qa_flag_from_year": 2025,
}

EVIDENCE_PROPERTIES = ["ev_perim", "ev_firms", "ev_wri_log", "ev_gfc", "ev_facts", "ev_mask", "qa_late_yod"]


def resolve_evidence_gate(param):
    """
    Gate settings with defaults filled in, or None when the gate is off.
    Pure Python. Raises ValueError for unknown keys or a missing/clashing
    released_name, so a typo can't silently fall back to defaults.
    """
    cfg = param.get("exclusion_evidence")
    if not cfg or not cfg.get("on"):
        return None
    unknown = set(cfg) - set(GATE_DEFAULTS) - {"on", "released_name"}
    if unknown:
        raise ValueError(f"exclusion_evidence: unknown keys {sorted(unknown)}")
    released = cfg.get("released_name")
    if not released:
        raise ValueError("exclusion_evidence: 'released_name' (QA asset for released patches) is required")
    if released in (param.get("filtered_classes"), param.get("classified_fc")):
        raise ValueError(f"exclusion_evidence: released_name {released!r} clashes with an existing pipeline asset name")
    gate = dict(GATE_DEFAULTS)
    gate.update({k: v for k, v in cfg.items() if k != "on"})
    if not 0 < gate["gfc_min_fraction"] <= 1:
        raise ValueError("exclusion_evidence: gfc_min_fraction must be in (0, 1]")
    return gate


def _mean_or_zero(stats, key):
    v = stats.get(key)
    return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(v, None), 0, v))


def evidence_images(param, gate):
    """Static evidence bands (fire perimeter, FIRMS, WRI logging) and the GFC lossyear image."""
    start_ms, end_ms = bnet.compute_fire_mask_window(param)
    perim = ee.Image(0).paint(bnet.get_fire_polygons(param), 1).rename("ev_perim")
    # The fully masked dummy keeps max() valid when no hotspot falls in the AOI.
    hotspots = ee.ImageCollection("FIRMS").filterDate(ee.Date(start_ms), ee.Date(end_ms)) \
        .filterBounds(param["aoi"]).select("T21") \
        .merge(ee.ImageCollection([ee.Image.constant(0).rename("T21")])) \
        .map(lambda i: i.gt(0).selfMask())
    firms = hotspots.max().focalMax(gate["firms_buffer_m"], "circle", "meters").gt(0).unmask(0).rename("ev_firms")
    wri = ee.Image(gate["wri_asset"]).select("classification").eq(gate["wri_logging_class"]) \
        .unmask(0).rename("ev_wri_log")
    lossyear = ee.Image(gate["gfc_asset"]).select("lossyear").unmask(0)
    return ee.Image.cat([perim, firms, wri]), lossyear


def tag_evidence(candidates, param, gate):
    """
    Add EVIDENCE_PROPERTIES to every candidate patch. ev_mask is 1 when the
    patch stays in the exclusion mask, 0 when it is released.
    """
    static, lossyear = evidence_images(param, gate)
    proj = lossyear.projection()  # native Hansen grid, valid in any region
    tol = gate["gfc_year_tolerance"]
    harvest = ee.List(gate["harvest_classes"])
    facts = ee.FeatureCollection(gate["facts_path"]) if gate["facts_path"] else None

    def tag(f):
        yod = ee.Number(f.get("yod"))
        y = yod.subtract(2000)
        gfc = lossyear.gte(y.subtract(tol)).And(lossyear.lte(y.add(tol))).rename("ev_gfc")
        stats = static.addBands(gfc).reduceRegion(ee.Reducer.mean(), f.geometry(), crs=proj, maxPixels=1e9)
        perim, firms = _mean_or_zero(stats, "ev_perim"), _mean_or_zero(stats, "ev_firms")
        wri, gfc_frac = _mean_or_zero(stats, "ev_wri_log"), _mean_or_zero(stats, "ev_gfc")
        if facts is None:
            in_facts = ee.Number(0)
        else:
            in_facts = facts.filterBounds(f.geometry()) \
                .filter(ee.Filter.rangeContains(gate["facts_year_field"], yod.subtract(1), yod.add(2))) \
                .size().gt(0)
        fire_ev = perim.gt(0).Or(firms.gt(0))
        harvest_ev = wri.gt(0).Or(in_facts)
        cls = ee.Number(f.get("classification"))
        # Numeric comparison: labels can come back as 21 or 21.0.
        is_harvest = ee.Number(harvest.map(lambda c: ee.Number(c).eq(cls)).reduce(ee.Reducer.max()))
        gfc_hit = is_harvest.And(gfc_frac.gte(gate["gfc_min_fraction"]))
        return f.set({
            "ev_perim": perim, "ev_firms": firms, "ev_wri_log": wri, "ev_gfc": gfc_frac,
            "ev_facts": in_facts,
            "ev_mask": fire_ev.Or(harvest_ev).Or(gfc_hit),
            "qa_late_yod": yod.gte(gate["qa_flag_from_year"]),
        })

    return candidates.map(tag)


def split_by_evidence(tagged):
    """(masked, released) halves of a tag_evidence() collection."""
    return tagged.filter(ee.Filter.eq("ev_mask", 1)), tagged.filter(ee.Filter.eq("ev_mask", 0))
