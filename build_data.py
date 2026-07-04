# -*- coding: utf-8 -*-
"""
Build the data files for the Overijssel land-use / Natura 2000 map.

Downloads open data from PDOK (Dutch national geodata portal):
  - BRP Gewaspercelen (RVO)          -> agricultural parcels with crop
  - Natura 2000 (RVO)                -> protected areas
  - Bestuurlijke Gebieden (Kadaster) -> Overijssel province boundary

Classifies every parcel as livestock / human food / mixed / other,
buffers the Natura 2000 areas by 1 km (true metres, EPSG:28992) and
flags parcels inside that zone. Writes the results as .js files in
data/ so index.html works straight from disk (file://, no server).

Usage:  python build_data.py
Re-runs use the cached raw download in data/raw/ (delete it to force
a fresh download).
"""

import json
import math
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely.geometry import mapping

# ---------------------------------------------------------------- config

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW = DATA / "raw"

WFS_BRP = "https://service.pdok.nl/rvo/brpgewaspercelen/wfs/v1_0"
WFS_N2K = "https://service.pdok.nl/rvo/natura2000/wfs/v1_0"
WFS_BG = "https://service.pdok.nl/kadaster/bestuurlijkegebieden/wfs/v1_0"
# NNN has no WFS; only this INSPIRE ATOM download (GML, whole NL, ~185 MB)
NNN_GML = ("https://service.pdok.nl/provincies/natuurnetwerk-nederland/"
           "atom/downloads/inspire-pv-ps.nlps-nnn.gml")

RD = "EPSG:28992"  # Dutch national grid, metres
WGS = "EPSG:4326"

BUFFER_M = 1000          # nitrogen zone distance around Natura 2000
SIMPLIFY_PARCEL_M = 5    # geometry simplification for export
SIMPLIFY_AREA_M = 10
COORD_DECIMALS = 5       # ~1 m in WGS84

PAGE_SIZE = 1000

# Crop classification: ordered rules, first match wins.
# Keyword is matched case-insensitively inside the BRP crop name ("gewas").
# L = livestock (keeping/feeding animals), H = human food,
# M = mixed / dual-use, O = other (non-food agriculture, nature, fallow)
RULES = [
    # --- other: nature management, fallow, ornamentals, fibre, turf -----
    ("O", ["natuurmengsel", "natuurterrein", "natuurvriendelijke", "braak",
           "bufferstrook", "rand, ", "randen", "akkerrand", "vogelakker",
           "wintervoedsel", "bijen", "kruidenrijk", "graszoden", "graszaad",
           "japanse haver", "groenbemester", "tagetes", "bloembollen",
           "lelie", "tulp", "gladiool", "narcis", "hyacint", "krokus",
           "sier", "boomkwekerij", "bomen", "kerstbomen", "bos", "heide",
           "vezel", "miscanthus", "olifantsgras", "zonnepan", "onbeteeld",
           "wandelpad", "verhard", "overige akkerbouwgewassen", "fruit, overig",
           "zwarte aarde", "landschapselement", "sloot", "houtwal",
           "struweel", "poel", "riet", "wilg", "populieren"]),
    # --- human food specifics that must beat broader rules --------------
    ("H", ["mais, suiker", "suikermais", "bieten, rode", "consumptie"]),
    # --- mixed / dual-use: cereals, sugar, starch, oil seeds ------------
    ("M", ["zetmeel", "suiker", "koolzaad", "raapzaad", "lijnzaad",
           "tarwe", "gerst", "haver", "rogge", "triticale", "spelt",
           "boekweit", "gierst", "sorghum", "quinoa", "granen",
           "zonnebloem", "soja", "lupine", "olie"]),
    # --- livestock: grass, fodder maize, fodder crops -------------------
    ("L", ["grasland", "mais", "maiskolven", "corncob", "luzerne",
           "voeder", "klaver", "veldbonen", "bonen, veld", "esparcette",
           "raaigras", "weide"]),
    # --- human food ------------------------------------------------------
    ("H", ["aardappel", "uien", "sjalot", "knoflook", "peen", "wortel",
           "witlof", "sla", "spinazie", "andijvie", "kool", "prei",
           "asperge", "aardbei", "courgette", "pompoen", "broccoli",
           "selderij", "knolvenkel", "venkel", "radijs", "rammenas",
           "pastinaak", "schorseneren", "rabarber", "erwten", "bonen",
           "kapucijners", "linzen", "appel", "peren", "kersen", "pruimen",
           "druiven", "bessen", "framboos", "frambozen", "bramen",
           "blauwe bes", "noten", "walnoten", "hazelnoten", "boomgaard",
           "fruit", "groente", "kruiden", "tomaat", "paprika", "komkommer",
           "meloen", "artisjok", "knolraap", "koolraap", "cichorei",
           "kroten", "paksoi", "maanzaad", "bladgewassen"]),
]

CAT_LABEL = {"L": "Veehouderij (gras/voer)", "H": "Menselijke voeding",
             "M": "Gemengd / dual-use", "O": "Overig agrarisch"}

session = requests.Session()
session.headers["User-Agent"] = "overijssel-landuse-map (hobby project)"


# ---------------------------------------------------------------- helpers

def log(msg):
    print(msg, flush=True)


def wfs_get(url, params, tries=4):
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            wait = 2 ** attempt
            log(f"  retry in {wait}s ({e})")
            time.sleep(wait)


def wfs_all(url, typename, extra=None):
    """Download every feature of a WFS layer with startIndex paging."""
    frames, start, seen = [], 0, set()
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": typename, "outputFormat": "application/json",
            "srsName": RD, "count": PAGE_SIZE, "startIndex": start,
        }
        if extra:
            params.update(extra)
        fc = wfs_get(url, params)
        feats = [f for f in fc.get("features", []) if f.get("id") not in seen]
        seen.update(f.get("id") for f in feats)
        if feats:
            for f in feats:  # keep the feature id (from_features drops it)
                f["properties"]["_fid"] = f.get("id")
            frames.append(gpd.GeoDataFrame.from_features(feats, crs=RD))
        n = len(fc.get("features", []))
        start += n
        if start % 20000 < PAGE_SIZE:
            log(f"  ...{start} features")
        if n < PAGE_SIZE:
            break
    if not frames:
        raise RuntimeError(f"no features from {typename}")
    return pd.concat(frames, ignore_index=True)


def fes_bbox_no_landscape(bounds):
    """FES 2.0 filter: inside bbox AND category != Landschapselement.

    (cql_filter is silently ignored by this PDOK service, FES is honored.)
    """
    x1, y1, x2, y2 = (math.floor(bounds[0]), math.floor(bounds[1]),
                      math.ceil(bounds[2]), math.ceil(bounds[3]))
    return (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" '
        'xmlns:gml="http://www.opengis.net/gml/3.2"><fes:And>'
        '<fes:PropertyIsNotEqualTo><fes:ValueReference>category</fes:ValueReference>'
        '<fes:Literal>Landschapselement</fes:Literal></fes:PropertyIsNotEqualTo>'
        '<fes:BBOX><fes:ValueReference>geom</fes:ValueReference>'
        f'<gml:Envelope srsName="urn:ogc:def:crs:EPSG::28992">'
        f'<gml:lowerCorner>{x1} {y1}</gml:lowerCorner>'
        f'<gml:upperCorner>{x2} {y2}</gml:upperCorner>'
        '</gml:Envelope></fes:BBOX></fes:And></fes:Filter>'
    )


def classify(gewas):
    g = str(gewas).lower()
    for cat, keywords in RULES:
        for kw in keywords:
            if kw in g:
                return cat
    return None  # unmatched -> logged, becomes "O"


def round_coords(obj, nd=COORD_DECIMALS):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [round_coords(v, nd) for v in obj]
    return obj


def write_js(path, **named_fcs):
    parts = []
    for name, obj in named_fcs.items():
        parts.append(f"const {name} = " +
                     json.dumps(obj, ensure_ascii=False,
                                separators=(",", ":")) + ";")
    path.write_text("\n".join(parts), encoding="utf-8")
    log(f"  wrote {path.name} ({path.stat().st_size / 1e6:.1f} MB)")


def plain(v):
    """numpy scalar -> native Python so json.dumps accepts it"""
    return v.item() if hasattr(v, "item") else v


def to_fc(gdf, props):
    feats = []
    for row in gdf.itertuples():
        geom = round_coords(mapping(row.geometry))
        feats.append({"type": "Feature",
                      "properties": {k: plain(getattr(row, v))
                                     for k, v in props.items()},
                      "geometry": geom})
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------- pipeline

def get_province():
    cache = RAW / "province.gpkg"
    if cache.exists():
        return gpd.read_file(cache)
    log("Downloading province boundaries...")
    gdf = wfs_all(WFS_BG, "bestuurlijkegebieden:Provinciegebied")
    ov = gdf[gdf["naam"] == "Overijssel"].to_crs(RD)
    if ov.empty:
        raise RuntimeError("Overijssel not found in Provinciegebied")
    ov = ov[["naam", "geometry"]].reset_index(drop=True)
    ov.to_file(cache, driver="GPKG")
    return ov


def get_natura():
    cache = RAW / "natura2000.gpkg"
    if cache.exists():
        return gpd.read_file(cache)
    log("Downloading Natura 2000 areas (whole NL, ~160 areas)...")
    gdf = wfs_all(WFS_N2K, "natura2000:natura2000")
    gdf = gdf[["naamN2K", "beschermin", "geometry"]]
    gdf.to_file(cache, driver="GPKG")
    return gdf


def get_nnn(prov_geom):
    """Natuurnetwerk Nederland, clipped to the province, dissolved (RD)."""
    cache = RAW / "nnn_overijssel.gpkg"
    if cache.exists():
        return gpd.read_file(cache).geometry.union_all()
    gml = RAW / "nnn.gml"
    if not gml.exists():
        log("Downloading NNN (INSPIRE GML, ~185 MB, one-off)...")
        with session.get(NNN_GML, stream=True, timeout=120) as r:
            r.raise_for_status()
            tmp = gml.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.rename(gml)
    log("Reading NNN GML (whole NL, takes a few minutes)...")
    nnn = gpd.read_file(gml)
    if nnn.crs is None:
        nnn = nnn.set_crs(RD)
    nnn = nnn.to_crs(RD)
    nnn["geometry"] = shapely.make_valid(nnn.geometry.values)
    idx = nnn.sindex.query(prov_geom, predicate="intersects")
    clipped = nnn.iloc[sorted(idx)].geometry.union_all().intersection(prov_geom)
    out = gpd.GeoDataFrame({"id": [1]}, geometry=[clipped], crs=RD)
    out.to_file(cache, driver="GPKG")
    log(f"NNN in Overijssel: {clipped.area / 1e4:.0f} ha")
    return clipped


def get_parcels(bounds):
    cache = RAW / "brp_bbox.gpkg"
    if cache.exists():
        log("Using cached BRP parcels (data/raw/brp_bbox.gpkg)")
        return gpd.read_file(cache)
    # PDOK WFS refuses startIndex beyond 50000, so fetch in a grid of
    # sub-bboxes and de-duplicate parcels that straddle tile edges (fuuid).
    x1, y1, x2, y2 = bounds
    n = 4
    xs = [x1 + (x2 - x1) * i / n for i in range(n + 1)]
    ys = [y1 + (y2 - y1) * i / n for i in range(n + 1)]
    log(f"Downloading BRP parcels (~275k features in {n * n} tiles, "
        "10-15 min, one-off)...")
    frames = []
    for i in range(n):
        for j in range(n):
            tile = (xs[i], ys[j], xs[i + 1], ys[j + 1])
            log(f"  tile {i * n + j + 1}/{n * n}")
            frames.append(wfs_all(
                WFS_BRP, "brpgewaspercelen:BrpGewas",
                {"filter": fes_bbox_no_landscape(tile)}))
    gdf = pd.concat(frames, ignore_index=True)
    before = len(gdf)
    gdf = gdf.drop_duplicates("_fid").reset_index(drop=True)
    log(f"  {before} downloaded, {len(gdf)} unique parcels")
    gdf = gdf[["category", "gewas", "gewascode", "jaar", "geometry"]]
    gdf.to_file(cache, driver="GPKG")
    return gdf


def main():
    DATA.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)

    province = get_province()
    prov_geom = province.geometry.union_all()
    log(f"Province OK, bbox {[round(b) for b in province.total_bounds]}")

    natura = get_natura()
    parcels = get_parcels(province.total_bounds)
    log(f"Raw parcels in bbox: {len(parcels)}")

    # keep the latest BRP year only
    year = int(parcels["jaar"].max())
    parcels = parcels[parcels["jaar"] == year].copy()

    # parcels intersecting the province
    idx = parcels.sindex.query(prov_geom, predicate="intersects")
    parcels = parcels.iloc[sorted(idx)].copy()
    parcels = parcels[~parcels.geometry.is_empty & parcels.geometry.notna()]
    parcels["geometry"] = shapely.make_valid(parcels.geometry.values)
    log(f"Parcels in Overijssel (BRP {year}): {len(parcels)}")

    # classify
    crops = parcels[["gewascode", "gewas"]].drop_duplicates("gewascode")
    cat_by_code, unmatched = {}, []
    for row in crops.itertuples():
        cat = classify(row.gewas)
        if cat is None:
            unmatched.append(row.gewas)
            cat = "O"
        cat_by_code[int(row.gewascode)] = cat
    parcels["cat"] = parcels["gewascode"].astype(int).map(cat_by_code)
    parcels["ha"] = (parcels.geometry.area / 10000).round(2)

    if unmatched:
        ha = (parcels[parcels["gewas"].isin(unmatched)]
              .groupby("gewas")["ha"].sum().sort_values(ascending=False))
        log(f"\nUNMATCHED crop names -> 'other' ({len(unmatched)}):")
        for name, area in ha.head(30).items():
            log(f"  {area:9.1f} ha  {name}")
        log("")

    # Natura 2000 near the province + 1 km buffer zone
    near = natura.iloc[natura.sindex.query(
        prov_geom.buffer(BUFFER_M), predicate="intersects")].copy()
    log(f"Natura 2000 areas within 1 km of Overijssel: {len(near)} "
        f"({sorted(near['naamN2K'].unique())})")
    n2k_union = shapely.make_valid(near.geometry.union_all())
    zone_full = n2k_union.buffer(BUFFER_M)          # N2000 + 1 km
    ring = zone_full.difference(n2k_union)          # the 1 km band itself
    ring_clip = ring.intersection(prov_geom)

    # flag parcels within 1 km of (or inside) Natura 2000
    hit = parcels.sindex.query(zone_full, predicate="intersects")
    parcels["z"] = 0
    parcels.iloc[sorted(hit), parcels.columns.get_loc("z")] = 1
    log(f"Parcels in nitrogen zone: {int(parcels['z'].sum())} of {len(parcels)}")

    # stats (ha per category, total vs in-zone)
    stats = {}
    for cat in "LHMO":
        sub = parcels[parcels["cat"] == cat]
        stats[cat] = {"label": CAT_LABEL[cat],
                      "ha": round(float(sub["ha"].sum())),
                      "ha_zone": round(float(sub.loc[sub["z"] == 1, "ha"].sum())),
                      "n": int(len(sub)),
                      "n_zone": int(sub["z"].sum())}

    # ---------- export ----------
    log("Simplifying and exporting...")
    parcels["geometry"] = parcels.geometry.simplify(SIMPLIFY_PARCEL_M)
    parcels = parcels[~parcels.geometry.is_empty]
    parcels_w = parcels.to_crs(WGS)
    fc = to_fc(parcels_w, {"g": "gewascode", "c": "cat", "h": "ha", "z": "z"})
    write_js(DATA / "parcels.js", PARCELS=fc)

    near["geometry"] = near.geometry.simplify(SIMPLIFY_AREA_M)
    natura_w = near.to_crs(WGS)
    natura_fc = to_fc(natura_w, {"naam": "naamN2K", "bescherming": "beschermin"})

    zone_gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[
        shapely.simplify(ring_clip, SIMPLIFY_AREA_M)], crs=RD).to_crs(WGS)
    zone_fc = to_fc(zone_gdf, {"id": "id"})

    nnn_geom = get_nnn(prov_geom)
    nnn_gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[
        shapely.simplify(nnn_geom, SIMPLIFY_AREA_M)], crs=RD).to_crs(WGS)
    nnn_fc = to_fc(nnn_gdf, {"id": "id"})
    write_js(DATA / "natura2000.js", NATURA=natura_fc, ZONE=zone_fc, NNN=nnn_fc)

    prov_gdf = gpd.GeoDataFrame({"naam": ["Overijssel"]}, geometry=[
        shapely.simplify(prov_geom, SIMPLIFY_AREA_M)], crs=RD).to_crs(WGS)
    prov_fc = to_fc(prov_gdf, {"naam": "naam"})

    crop_names = {int(r.gewascode): r.gewas for r in crops.itertuples()}
    meta = {"year": year,
            "built": time.strftime("%Y-%m-%d"),
            "buffer_m": BUFFER_M,
            "stats": stats,
            "crops": crop_names}
    write_js(DATA / "province.js", PROVINCE=prov_fc, META=meta)

    log("\nDone. Open index.html in your browser.")
    for cat in "LHMO":
        s = stats[cat]
        log(f"  {s['label']:<26} {s['ha']:>8} ha total, {s['ha_zone']:>7} ha in 1 km zone")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
