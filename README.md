# Overijssel — landgebruik, veehouderij & Natura 2000

Interactieve kaart van de provincie Overijssel met:

- **Gewaspercelen** (BRP, RVO) ingedeeld in vier categorieën:
  - **Veehouderij** — grasland, snijmaïs, voedergewassen (dieren houden/voeren)
  - **Menselijke voeding** — aardappelen, groenten, fruit, peulvruchten
  - **Gemengd / dual-use** — granen, suikerbieten, zetmeelaardappelen, oliezaden
    (deels voedsel, deels veevoer/industrie)
  - **Overig agrarisch** — bollen, sierteelt, natuurbeheer, braak
- **Natura 2000-gebieden** (RVO)
- **Natuurnetwerk Nederland (NNN)** (provincies, via PDOK) — lichte groene
  waas onder de Natura 2000-gebieden (63.205 ha in Overijssel)
- De **zone binnen 1 km** van Natura 2000, waar volgens de aangekondigde
  plannen de strengste stikstofrestricties gaan gelden. Percelen in die zone
  worden gearceerd weergegeven.

## Gebruik

Dubbelklik op `index.html` — de kaart opent in de browser. Internet is alleen
nodig voor de achtergrondkaart (PDOK) en de MapLibre-bibliotheek; alle
perceeldata staat lokaal in `data/`.

- Vink lagen aan/uit in het paneel linksboven.
- Klik op een perceel voor gewas, oppervlakte en zonestatus.
- De tabel onderin het paneel toont hectares per categorie, totaal en
  binnen de 1 km-zone.

## Data verversen

```
python build_data.py
```

Downloadt de actuele data van PDOK (eenmalig ± 10–15 min) en schrijft
`data/parcels.js`, `data/natura2000.js` en `data/province.js`. De ruwe
download wordt gecachet in `data/raw/` (mag weg om opnieuw te downloaden —
scheelt ook ruimte in OneDrive, het is een paar honderd MB).

De gewasindeling staat bovenin `build_data.py` (`RULES`) en is daar
aan te passen; onbekende gewassen komen in "Overig" en worden bij het
bouwen gelogd.

## Validatie t.o.v. CBS

`python check_cbs.py` vergelijkt de kaartcategorieën met de
CBS-landbouwtelling (StatLine 80780ned, zelfde jaar). Resultaat voor 2025:

| categorie | kaart (ha) | CBS (ha) | verschil |
|---|---:|---:|---:|
| Veehouderij (gras/voer) | 171.194 | 173.441 | −1,3% |
| Menselijke voeding | 5.856 | 7.289 | −19,7% |
| Gemengd / dual-use | 10.969 | 11.455 | −4,2% |
| Totaal cultuurgrond | 196.951 | 195.525 | +0,7% |

Het verschil bij "menselijke voeding" (±1.400 ha op een kleine categorie)
past bij het bekende definitieverschil: CBS telt grond bij de provincie van
de hoofdvestiging van het bedrijf, en Overijsselse aardappel-/uientelers
huren veel wisselgrond in Flevoland en Drenthe. De kaart telt naar
perceellocatie.

## Kanttekeningen

- De 1 km-zone is een **geometrische benadering** (buffer van 1000 m rond de
  officiële Natura 2000-begrenzing, incl. gebieden net buiten de provincie).
  De uiteindelijke juridische begrenzing van stikstofzones kan afwijken.
- Granen e.d. zijn als "gemengd" ingedeeld omdat het merendeel van het
  Nederlandse graan als veevoer wordt gebruikt.
- Bron: BRP Gewaspercelen & Natura 2000 (RVO), Bestuurlijke Gebieden
  (Kadaster), via PDOK. Achtergrondkaart: BRT (Kadaster).
