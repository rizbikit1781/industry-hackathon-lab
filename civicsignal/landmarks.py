"""Landmark geocoding for voice tickets: "the bus loop at the University of Calgary" -> a point.

1. Local name index built from layers already on disk (schools incl. post-secondaries,
   community services incl. hospitals/libraries/attractions, CTrain/MAX stations, seniors'
   residences with coordinates).
2. Token-based fuzzy score (stdlib difflib only):
       score = 0.7 * coverage + 0.3 * precision
   coverage  = share of the caller's (non-filler) words found in the place name,
   precision = share of the place name's distinctive words the caller said
   (generic words such as "school", "station", "campus" and quadrants are not counted).
   Words match exactly or by difflib ratio >= 0.85 (catches "MacEwen"/"MacEwan").
   Transit stations get x0.9 unless the caller said station/LRT/CTrain/train; if the caller
   named a kind of place (hospital, school, library, ...) other kinds get x0.9.
3. Best place scoring >= MATCH_MIN wins. If a different place (> MERGE_M away) also scores
   within AMBIG_GAP of it, the result is "ambiguous" with the top candidates instead.
4. If nothing local clears MATCH_MIN: OpenStreetMap Nominatim search bounded to Calgary
   (1 req/s, short timeout, in-memory cache). Any network error -> no match, never raises.
"""
from __future__ import annotations

import math
import re
import threading
import time
from difflib import get_close_matches
from functools import lru_cache

import pandas as pd
import requests

from .ingest import DATA

MATCH_MIN = 0.75      # minimum score for a local match
AMBIG_GAP = 0.2       # a different place this close to the best -> ask the caller
MERGE_M = 700         # candidates closer than this are the same place (station at a campus)
TOKEN_FUZZ = 0.85     # difflib ratio for a misspelled word to count

BBOX = (-114.32, 50.84, -113.85, 51.22)   # lon_min, lat_min, lon_max, lat_max
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT_S = 2.5
USER_AGENT = ("SnowTech-CivicSignal/0.1 (Calgary 311 snow/ice hackathon demo; "
              "https://github.com/rizbikit1781/industry-hackathon-lab)")

# Spoken short forms -> the words the index uses. Applied to the lowercased text.
ALIASES = [
    (r"\bu\s*of\s*c\b", "university of calgary"), (r"\bu ?of ?c\b|\bu ?calgary\b", "university of calgary"),
    (r"\bmru\b", "mount royal university"), (r"\bmt\.?\s+royal\b", "mount royal"),
    (r"\bsouthern alberta institute of technology\b", "sait"), (r"\bs\s*a\s*i\s*t\b", "sait"),
    (r"\bbvc\b", "bow valley college"), (r"\bauarts\b", "alberta university of the arts"),
    (r"\bacad\b", "alberta university of the arts"),
    (r"\bfoothills medical centre\b", "foothills hospital"), (r"\bfmc\b", "foothills hospital"),
    (r"\bplc\b", "peter lougheed"), (r"\bachs?\b", "alberta childrens hospital"),
    (r"\bpeter lougheed (hospital|centre)\b", "peter lougheed medical centre"),
    (r"\b(c-?train|lrt|train)( station)?\b", "station"), (r"\bcentre\b|\bcenter\b", "centre"),
    (r"\bstreet\b", "st"), (r"\bavenue\b|\bav\b", "ave"), (r"\bdrive\b", "dr"),
    (r"\broad\b", "rd"), (r"\btrail\b", "tr"), (r"\bboulevard\b|\bblvd\b", "bv"),
    (r"\bsaint\b", "st"), (r"\b(\d+)(st|nd|rd|th)\b", r"\1"),
    (r"\bnorth\s*west\b", "nw"), (r"\bnorth\s*east\b", "ne"),
    (r"\bsouth\s*west\b", "sw"), (r"\bsouth\s*east\b", "se"),
]
# Words a caller wraps around the place ("heavy snow in front of the bus loop at ...").
FILLER = set("""the a an at of in on by near nearby beside behind outside inside front back side
across from to and or around next close just right by little bit bus loop stop entrance entry exit
door doors parking lot lots sidewalk sidewalks walkway path road street area grounds building main
alberta ab yyc there here
snow snowy snowpack ice icy heavy packed unshovelled unshoveled slippery problem""".split())
# Words that describe the kind of place: matched if said, but not required.
GENERIC = set("""school station lrt ctrain campus centre hospital university college library
community association hall park junior senior high elementary middle academy main
nw ne sw se n s e w nb sb eb wb""".split()) - {"university", "college"}
# Type words a caller may add ("Foothills hospital"): count as matched for places of that
# type, and places of another type get x0.9 (so "Peter Lougheed hospital" beats the school).
TYPE_WORDS = {"hospital": {"hospital"}, "clinic": {"phs clinic", "hospital"},
              "library": {"library"}, "station": {"transit station"},
              "school": {"school", "post-secondary"}, "university": {"post-secondary"},
              "college": {"post-secondary"}}

DISPLAY = {  # nicer read-back for the long inventory names
    "UNIVERSITY OF CALGARY - MAIN CAMPUS - MACEWAN STUDENT CENTRE":
        "University of Calgary - MacEwan Student Centre",
    "MOUNT ROYAL UNIVERSITY - LINCOLN PARK CAMPUS": "Mount Royal University",
}
SMALL = {"of", "the", "and", "de", "la", "du", "at"}


def normalize(text: str) -> str:
    t = str(text).lower().replace("&", " and ").replace("'", "").replace("’", "")
    for pat, rep in ALIASES:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"(?<!of)\s+(in\s+)?calgary(\s+(alberta|ab))?\s*$", "", t)   # "... in Calgary"
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str, drop_filler: bool) -> list[str]:
    toks = normalize(text).split()
    stop = FILLER if drop_filler else {"the", "of", "and", "a", "at"}
    return [w for w in toks if w not in stop]


def pretty(name: str) -> str:
    if name in DISPLAY:
        return DISPLAY[name]
    if not name.isupper():
        return name
    words = name.lower().split(" ")
    return " ".join(w if (i and w in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _station_name(raw: str) -> str | None:
    """'NB Brentwood CTrain Station' / 'Brentwood LRT Station (EB ...)' -> 'Brentwood Station'."""
    s = str(raw)
    if "station" not in s.lower():
        return None
    s = s.split("@")[-1]
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\s+-\s+(Rocky Ridge|Tuscany) Terminal.*$", "", s)
    s = re.sub(r"^\s*(NB|SB|EB|WB)\s+", "", s)
    s = re.sub(r"\s+(NB|SB|EB|WB)\s*$", "", s.strip())
    s = re.sub(r"\b(CTrain|LRT)\s+Station\b", "Station", s, flags=re.I)
    s = re.sub(r"^S\. of\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip() or None


@lru_cache(maxsize=1)
def load_index() -> pd.DataFrame:
    """One row per named place: name, type, lat, lon, toks (distinctive tokens)."""
    rows = []
    lay = DATA / "layers"
    if (lay / "schools.csv").exists():
        sc = pd.read_csv(lay / "schools.csv")
        for r in sc.itertuples():
            kind = "post-secondary" if r.postsecond == "Y" else "school"
            rows.append((r.name, kind, r.lat, r.lon))
    if (lay / "community_services.csv").exists():
        cs = pd.read_csv(lay / "community_services.csv")
        rows += [(r.name, str(r.type).lower(), r.lat, r.lon) for r in cs.itertuples()]
    if (lay / "transit_stops.csv").exists():
        ts = pd.read_csv(lay / "transit_stops.csv", usecols=["stop_name", "lat", "lon"])
        ts["st"] = ts["stop_name"].map(_station_name)
        ts = ts.dropna(subset=["st"])
        g = ts.groupby(ts["st"].str.lower()).agg(name=("st", "first"), lat=("lat", "mean"),
                                                  lon=("lon", "mean"))
        rows += [(r.name, "transit station", r.lat, r.lon) for r in g.itertuples()]
    if (DATA / "seniors_residences.csv").exists():
        sr = pd.read_csv(DATA / "seniors_residences.csv")
        rows += [(r.name, "seniors' residence", r.lat, r.lon) for r in sr.itertuples()]
    df = pd.DataFrame(rows, columns=["name", "type", "lat", "lon"]).dropna(subset=["name", "lat", "lon"])
    df = df[df["lat"].between(BBOX[1], BBOX[3]) & df["lon"].between(BBOX[0], BBOX[2])]
    df = df.drop_duplicates(subset=["name", "type"]).reset_index(drop=True)
    df["toks"] = df["name"].map(lambda n: frozenset(tokens(n, drop_filler=False)))
    return df


@lru_cache(maxsize=1)
def _vocab() -> list[str]:
    return sorted({w for ts in load_index()["toks"] for w in ts})


def _dist_m(a, b) -> float:
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def score_local(query: str, top: int = 5) -> list[dict]:
    """Scored candidates (best first), one per physical place."""
    idx, vocab = load_index(), _vocab()
    q = tokens(query, drop_filler=True)
    vs = set(vocab)
    for i in range(len(q) - 1):                # "rocky view" -> "rockyview" if the index has it
        if q[i] + q[i + 1] in vs:
            q[i], q[i + 1] = q[i] + q[i + 1], ""
    q = [w for w in dict.fromkeys(q) if w]
    if not q:
        return []
    # each query word -> the index words it matches (exact, or a close spelling for words >= 4)
    hits = {w: {w} | (set(get_close_matches(w, vocab, n=4, cutoff=TOKEN_FUZZ)) if len(w) >= 4 else set())
            for w in q}
    allhit = set().union(*hits.values())
    asked = [TYPE_WORDS[w] for w in q if w in TYPE_WORDS]
    wants_station = "station" in q
    out = []
    for r in idx[idx["toks"].map(lambda ts: not allhit.isdisjoint(ts))].itertuples():
        cov = sum(1 for w in q if not hits[w].isdisjoint(r.toks) or
                  r.type in TYPE_WORDS.get(w, ())) / len(q)
        core = [w for w in r.toks if w not in GENERIC] or list(r.toks)
        prec = sum(1 for w in core if w in allhit) / len(core)
        s = 0.7 * cov + 0.3 * prec
        if r.type == "transit station" and not wants_station:
            s *= 0.9
        if asked and not any(r.type in kinds for kinds in asked):
            s *= 0.9
        out.append({"name": pretty(r.name), "type": r.type, "lat": float(r.lat),
                    "lon": float(r.lon), "score": round(s, 3)})
    out.sort(key=lambda c: -c["score"])
    places: list[dict] = []        # merge candidates at the same spot; prefer the facility name
    for c in out:
        same = next((p for p in places if _dist_m((p["lat"], p["lon"]), (c["lat"], c["lon"])) < MERGE_M), None)
        if same is None:
            places.append(c)
        elif same["type"] == "transit station" and c["type"] != "transit station" and \
                c["score"] >= MATCH_MIN:
            same.update({k: c[k] for k in ("name", "type", "lat", "lon")})
        if len(places) >= top:
            break
    return places


# ------------------------------------------------------------------ Nominatim fallback
_cache: dict[str, dict | None] = {}
_lock = threading.Lock()
_last = [0.0]


def nominatim(query: str) -> dict | None:
    """Best OSM hit inside Calgary, or None. Cached; <= 1 request/s; never raises."""
    words = [w for w in re.findall(r"[\w'&.-]+", str(query).lower()) if w not in FILLER - {"of", "and"}]
    while words and words[0] in ("of", "and"):
        words.pop(0)
    q = " ".join(words).strip()
    if not q:
        return None
    if q in _cache:
        return _cache[q]
    with _lock:
        if q in _cache:
            return _cache[q]
        wait = 1.0 - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = requests.get(NOMINATIM_URL, timeout=NOMINATIM_TIMEOUT_S,
                             headers={"User-Agent": USER_AGENT},
                             params={"q": q, "format": "jsonv2", "countrycodes": "ca", "limit": 3,
                                     "bounded": 1, "viewbox": ",".join(map(str, BBOX))})
            r.raise_for_status()
            res = r.json()
        except Exception:
            return None            # network trouble: no match, and don't cache the failure
        hit = None
        for h in res if isinstance(res, list) else []:
            try:
                lat, lon = float(h["lat"]), float(h["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lon <= BBOX[2]:
                name = h.get("name") or str(h.get("display_name", "")).split(",")[0]
                hit = {"name": name or q, "type": h.get("type") or h.get("category") or "place",
                       "lat": lat, "lon": lon, "score": None, "source": "nominatim"}
                break
        if len(_cache) > 500:
            _cache.clear()
        _cache[q] = hit
        return hit


def resolve(text: str | None, use_network: bool = True) -> dict:
    """{'status': 'match', 'match': {...}} | {'status': 'ambiguous', 'candidates': [...]} |
    {'status': 'none'}."""
    if not text or not str(text).strip():
        return {"status": "none"}
    cands = score_local(text)
    good = [c for c in cands if c["score"] >= MATCH_MIN]
    if good:
        best = good[0]
        close = [c for c in good if best["score"] - c["score"] <= AMBIG_GAP]
        if len(close) > 1:
            return {"status": "ambiguous", "candidates": close[:3]}
        return {"status": "match", "match": {**best, "source": "local"}}
    if use_network:
        hit = nominatim(text)
        if hit:
            return {"status": "match", "match": hit}
    return {"status": "none"}
