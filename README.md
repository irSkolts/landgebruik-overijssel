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
- De **stikstofzone** rond Natura 2000, waar strengere stikstofrestricties
  gaan gelden. De breedte volgt het kabinetsvoornemen (Verdiepingsbijlage
  Hoofdlijn 3, 2025, Bijlage 1): **500 m** rond de meeste stikstofgevoelige
  gebieden en **1 km** rond enkele. In Overijssel krijgen alleen *Springendal
  & Dal van de Mosbeek* en *Vecht- en Beneden-Reggegebied* een zone van 1 km;
  grote wateren (Zwarte Meer, Ketelmeer & Vossemeer, Veluwerandmeren) krijgen
  geen zone. Percelen in een zone worden gearceerd weergegeven (500 m oranje,
  1 km rood).

## Gebruik

Dubbelklik op `index.html` — de kaart opent in de browser. Internet is alleen
nodig voor de achtergrondkaart (PDOK) en de MapLibre-bibliotheek; alle
perceeldata staat lokaal in `data/`.

- Vink lagen aan/uit in het paneel linksboven.
- Klik op een perceel voor gewas, oppervlakte en zonestatus.
- De tabel onderin het paneel toont hectares per categorie, totaal en
  binnen de stikstofzone.

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

- De stikstofzones zijn een **geometrische benadering**: een buffer van 500 m
  of 1 km rond de officiële Natura 2000-begrenzing (incl. gebieden net buiten
  de provincie), volgens de zonebreedtes uit het kabinetsvoornemen. Dat
  voornemen is voorlopig — de lijst gebieden en de definitieve juridische
  begrenzing kunnen nog wijzigen. De zonebreedte per gebied staat in de tabel
  `ZONE_WIDTH` bovenin `build_data.py` en is daar aan te passen.
- Granen e.d. zijn als "gemengd" ingedeeld omdat het merendeel van het
  Nederlandse graan als veevoer wordt gebruikt.
- Bron: BRP Gewaspercelen & Natura 2000 (RVO), Bestuurlijke Gebieden
  (Kadaster), via PDOK. Achtergrondkaart: BRT (Kadaster).
