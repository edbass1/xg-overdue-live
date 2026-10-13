"""Accesso FotMob + cache partite (condiviso)."""
import json, os, time, urllib.request
BASE = "https://www.fotmob.com/api/data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache", "matches.json")
DELAY = 1.2
LEAGUES = {47: "Premier League", 87: "LaLiga", 54: "Bundesliga", 55: "Serie A", 53: "Ligue 1",
           57: "Eredivisie", 61: "Liga Portugal", 48: "Championship"}

def get(path, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.load(r)
            time.sleep(DELAY); return d
        except Exception:
            if i == tries - 1: raise
            time.sleep(5 * (i + 1))

def load_cache():
    try: return json.load(open(CACHE))
    except Exception: return {}

def save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(c, open(CACHE, "w"), separators=(",", ":"))

def _xg(det, period):
    for g in det["content"]["stats"]["Periods"].get(period, {}).get("stats", []):
        for s in g.get("stats", []):
            if s.get("key") == "expected_goals" and s["stats"][0] is not None:
                return [float(s["stats"][0]), float(s["stats"][1])]
    return None

def summarize(det, lid, m):
    try: xg, xh = _xg(det, "All"), _xg(det, "FirstHalf")
    except Exception: xg = xh = None
    if not xg: return {"noxg": 1}
    gh = [0, 0]; gf = [0, 0]
    for e in det["content"]["matchFacts"]["events"]["events"]:
        if e.get("type") == "Goal":
            k = 0 if e.get("isHome") else 1
            gf[k] += 1
            if (e.get("time") or 99) <= 45: gh[k] += 1
    try: gf = [int(x) for x in m["status"].get("scoreStr", "").split(" - ")]
    except Exception: pass
    return {"l": lid, "t": m["status"]["utcTime"][:16], "h": int(m["home"]["id"]), "a": int(m["away"]["id"]),
            "hn": m["home"]["name"], "an": m["away"]["name"], "xg": xg, "xh": xh, "g": gf, "gh": gh}

def update_cache(cache, max_new=400, log=print):
    fixtures = {}; new = 0
    for lid in LEAGUES:
        try: lg = get(f"/leagues?id={lid}")
        except Exception as e: log("lega", lid, e); continue
        ms = lg["fixtures"]["allMatches"]; fixtures[lid] = ms
        for m in ms:
            st = m["status"]
            if not st.get("finished") or st.get("cancelled") or str(m["id"]) in cache or new >= max_new: continue
            try: cache[str(m["id"])] = summarize(get(f"/matchDetails?matchId={m['id']}"), lid, m); new += 1
            except Exception as e: log("match", m["id"], e)
            if new and new % 50 == 0: save_cache(cache)
    save_cache(cache); log(f"cache: {len(cache)} partite ({new} nuove)")
    return fixtures
