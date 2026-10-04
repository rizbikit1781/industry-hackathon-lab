# Data Guide - Neighbourhood Hail Flags (Case 4)

One small table is in this folder for now. The air-quality (AQHI/PM2.5) seed
has been removed; the starter and web app currently flag on hail data only.

---

## Bundled seeds

| File | What it is |
|---|---|
| `neighbourhoods_hail_scenario.csv` | Community centroids plus a `hail_track` band for an **Aug 2024-style** north-Calgary hail path |

`hail_track` values: `high` (named in public coverage of the 5 Aug 2024 north / airport corridor), `medium` (adjacent north / northeast / inner-north), `low` (sample of the rest of the city).

This is **not** a CatIQ claims file and **not** an official City hail map. Treat it as a labelled scenario.

Community centroids are vertex averages of Open Calgary community polygons.

---

## Primary sources

- **Community boundaries - Open Calgary** (centroids only in this seed)
- Hail path: reconstructed from public reporting of the 5 August 2024 Calgary hailstorm (north city / airport corridor). Do not claim you have insurer microdata.

---

## Loading example

```python
import pandas as pd

neigh = pd.read_csv("data/neighbourhoods_hail_scenario.csv")
print(neigh["hail_track"].value_counts())
```
