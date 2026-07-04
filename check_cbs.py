# -*- coding: utf-8 -*-
"""
Cross-check the map's hectares-per-category against CBS StatLine.

Table 80780ned: "Landbouw; gewassen, dieren en grondgebruik naar regio".
Compares the BRP-derived categories (data/province.js META.stats) with the
CBS agricultural census for Overijssel, same year, with the category
definitions aligned as closely as the CBS breakdown allows.

Usage:  python check_cbs.py
"""

import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).parent
API = "https://opendata.cbs.nl/ODataApi/odata/80780ned"

# CBS topic keys (area block, hectares) -> how they map onto our categories.
# Aligned with build_data.py RULES: all maize except sweet corn counts as
# livestock on the map, so grain maize / CCM are moved from cereals to L here.
CBS_L = ["GraslandEnGroenvoedergewassenTotaal_446", "MaisKorrel_60",
         "MaisCorncobMix_59"]
CBS_H = ["ConsumptieaardappelenTotaal_26", "PootaardappelenTotaal_29",
         "AkkerbouwgroentenTotaal_33", "UienTotaal_44",
         "FruitOpenGrondTotaal_195", "TuinbouwgroentenTotaal_211",
         "GlasgroentenTotaal_359", "FruitOnderGlasTotaal_355",
         "BruineBonen_83", "KapucijnersEnGrauweErwten_84",
         "TuinbonenDroogTeOogsten_86"]
CBS_M = ["GranenTotaal_53", "Suikerbieten_89", "Zetmeelaardappelen_32",
         "KoolEnRaapzaadTotaal_73", "Lijnzaad_77", "Sojabonen_78",
         "Zonnebloemen_80", "NietBittereLupinen_85",
         ("MaisKorrel_60", -1), ("MaisCorncobMix_59", -1)]
CBS_TOTAL = ["CultuurgrondTotaal_3"]


TO_HA = {"are": 0.01, "m2": 0.0001, "ha": 1.0}


def cbs_value(row, spec, units):
    key, sign = spec if isinstance(spec, tuple) else (spec, 1)
    v = row.get(key)
    if not isinstance(v, (int, float)):
        return 0.0
    return sign * v * TO_HA[units[key]]


def main():
    meta = json.loads(re.search(
        r"const META = (\{.*\});",
        (ROOT / "data" / "province.js").read_text(encoding="utf-8")).group(1))
    year = meta["year"]

    regios = requests.get(f"{API}/RegioS", timeout=30).json()["value"]
    ov = next(r["Key"] for r in regios
              if r["Title"].startswith("Overijssel"))

    # units differ per topic (open ground in are, glasshouse in m2)
    props = requests.get(f"{API}/DataProperties", timeout=30).json()["value"]
    units = {p["Key"]: p.get("Unit") for p in props if p.get("Key")}

    url = (f"{API}/TypedDataSet?$filter=RegioS eq '{ov}' "
           f"and Perioden eq '{year}JJ00'")
    rows = requests.get(url, timeout=60).json()["value"]
    if not rows:
        raise SystemExit(f"CBS has no {year} data for Overijssel yet")
    row = rows[0]

    cbs = {"L": sum(cbs_value(row, s, units) for s in CBS_L),
           "H": sum(cbs_value(row, s, units) for s in CBS_H),
           "M": sum(cbs_value(row, s, units) for s in CBS_M)}
    cbs_tot = sum(cbs_value(row, s, units) for s in CBS_TOTAL)
    map_tot = sum(meta["stats"][c]["ha"] for c in "LHMO")

    print(f"\nVergelijking kaart (BRP {year}) vs CBS landbouwtelling {year}, "
          f"Overijssel\n")
    print(f"{'categorie':<28}{'kaart (ha)':>12}{'CBS (ha)':>12}{'verschil':>10}")
    for c in "LHM":
        m = meta["stats"][c]["ha"]
        d = 100 * (m - cbs[c]) / cbs[c] if cbs[c] else float("nan")
        print(f"{meta['stats'][c]['label']:<28}{m:>12,.0f}{cbs[c]:>12,.0f}"
              f"{d:>+9.1f}%")
    o = meta["stats"]["O"]["ha"]
    cbs_o = cbs_tot - cbs["L"] - cbs["H"] - cbs["M"]
    print(f"{'Overig agrarisch (restpost)':<28}{o:>12,.0f}{cbs_o:>12,.0f}")
    d = 100 * (map_tot - cbs_tot) / cbs_tot
    print(f"{'TOTAAL cultuurgrond':<28}{map_tot:>12,.0f}{cbs_tot:>12,.0f}"
          f"{d:>+9.1f}%")

    print("""
Bekende definitieverschillen (verklaren afwijkingen van enkele procenten):
- CBS telt per bedrijf (hoofdvestiging) incl. grond buiten de provincie;
  de kaart telt per perceellocatie binnen de provincie.
- Kaart gebruikt bruto polygoonoppervlak; CBS de opgegeven beteelde
  oppervlakte.
- CBS cultuurgrond telt alleen geregistreerde landbouwbedrijven boven de
  registratiedrempel; BRP bevat ook percelen van kleinere grondgebruikers
  en natuurbeherende organisaties (vooral zichtbaar in grasland/overig).""")


if __name__ == "__main__":
    main()
