#!/usr/bin/env python3
"""Scanner metodo xG Overdue (FotMob). Scrive data.json + storico.csv."""
import argparse, csv, datetime as dt, json, math, os, time, urllib.request
from zoneinfo import ZoneInfo
BASE = "https://www.fotmob.com/api/data"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
DELAY = 1.5  # secondi tra richieste (rate limit cortese)

def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    time.sleep(DELAY)
    return data

def is_ht(m):
    st = m.get("status", {})
    lt = (st.get("liveTime") or {}).get("short", "")
    rs = (st.get("reason") or {}).get("short", "")
    return st.get("started") and not st.get("finished") and ("HT" in (lt, rs) or lt.upper() in ("PAUSE", "INT"))

def live_minute(m):
    lt = ((m.get("status") or {}).get("liveTime") or {}).get("short", "")
    try: return int(lt.split("+")[0].strip("'’ "))
    except ValueError: return None

def details_at(det, minute):
    """xG e gol fino a `minute` (45 = fine primo tempo)."""
    hid = det["general"]["homeTeam"]["id"]
    if minute == 45:  # xG ufficiale del primo tempo
        xg = None
        for g in det["content"]["stats"]["Periods"].get("FirstHalf", {}).get("stats", []):
            for s in g.get("stats", []):
                if s.get("key") == "expected_goals" and s["stats"][0] is not None:
                    xg = [float(s["stats"][0]), float(s["stats"][1])]
        first = lambda sh: sh.get("period") == "FirstHalf"
    else:
        first = lambda sh: (sh.get("min") or 0) <= minute
        xg = None
    shots = (det["content"].get("shotmap") or {}).get("shots") or []
    if xg is None and shots:
        xg = [0.0, 0.0]
        for sh in shots:
            if first(sh) and sh.get("expectedGoals") is not None:
                xg[0 if sh["teamId"] == hid else 1] += sh["expectedGoals"]
        xg = [round(x, 2) for x in xg]
    goals = [0, 0]
    for e in det["content"]["matchFacts"]["events"]["events"]:
        if e.get("type") == "Goal" and (e.get("time") or 0) <= minute:
            goals[0 if e.get("isHome") else 1] += 1
    return xg, goals

def method(xg, goals, minute=45, soglia=0.30):
    f = 1 + 0.5 * (90 - minute) / 45  # 45' -> 1.5
    r = {"fattore": round(f, 3)}
    proj = [round(x * f, 2) for x in xg]
    xs = [round(p - g, 2) for p, g in zip(proj, goals)]
    r.update(proj=proj, punteggio=[math.floor(p) for p in proj], xsxg=xs,
             overdue=[max(0, math.floor(x)) for x in xs], totale=math.floor(sum(xs)))
    d = proj[0] - proj[1]
    r["esito"] = "Pareggio" if abs(d) < soglia else ("1 Casa" if d > 0 else "2 Ospite")
    return r

def load_json(p, default):
    try: return json.load(open(p))
    except Exception: return default

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD (default oggi, Europe/Rome)")
    ap.add_argument("--minute", type=int, default=None, help="modalità minuto N (default 45 = intervallo)")
    ap.add_argument("--test", action="store_true", help="analizza anche partite finite (backtest)")
    ap.add_argument("--match", type=int, help="solo questo matchId")
    ap.add_argument("--leagues", help="id campionati separati da virgola")
    a = ap.parse_args()
    now = dt.datetime.now(ZoneInfo("Europe/Rome"))
    date = a.date or now.strftime("%Y%m%d")
    minute = a.minute or 45
    seen_p, csv_p, out_p = (os.path.join(HERE, n) for n in ("seen.json", "storico.csv", "data.json"))
    seen = set(load_json(seen_p, []))
    data = load_json(out_p, {})
    if data.get("date") != date: data = {"date": date, "matches": {}}
    leagues = set(map(int, a.leagues.split(","))) if a.leagues else None
    day = get(f"/matches?date={date}")
    cand = []
    for lg in day.get("leagues", []):
        if leagues and lg.get("primaryId") not in leagues: continue
        for m in lg["matches"]:
            if a.match and m["id"] != a.match: continue
            st = m["status"]
            key = f"{m['id']}@{minute}"
            if key in data["matches"] and st.get("finished"):  # aggiorna risultato finale
                data["matches"][key]["finale"] = st.get("scoreStr"); continue
            ok = (a.test and st.get("finished")) or is_ht(m) if a.minute is None else \
                 (a.test and st.get("finished")) or ((live_minute(m) or 0) >= minute and not st.get("finished"))
            if ok and key not in data["matches"]:
                cand.append((lg.get("name"), m))
    nuovi = []
    for lgname, m in cand:
        try: det = get(f"/matchDetails?matchId={m['id']}")
        except Exception as e: print("errore", m["id"], e); continue
        xg, goals = details_at(det, minute)
        if not xg: continue
        r = method(xg, goals, minute)
        rec = {"id": m["id"], "campionato": lgname, "casa": m["home"]["name"], "ospite": m["away"]["name"],
               "minuto": minute, "punteggio_live": f"{goals[0]}-{goals[1]}", "xg": xg, **r,
               "finale": m["status"].get("scoreStr") if m["status"].get("finished") else None,
               "scansione": now.strftime("%d/%m/%Y %H:%M")}
        data["matches"][f"{m['id']}@{minute}"] = rec
        new = not os.path.exists(csv_p)
        with open(csv_p, "a", newline="") as f:
            w = csv.writer(f, delimiter=";")
            if new: w.writerow(["data","matchId","campionato","casa","ospite","minuto","punteggio","xg_casa","xg_ospite","totale_overdue","esito","finale"])
            w.writerow([date, m["id"], lgname, rec["casa"], rec["ospite"], minute, rec["punteggio_live"], xg[0], xg[1], r["totale"], r["esito"], rec["finale"] or ""])
        sk = f"{m['id']}@{minute}"
        if r["totale"] > 0 and sk not in seen:
            seen.add(sk); nuovi.append(rec)
    data["aggiornato"] = now.strftime("%d/%m/%Y %H:%M")
    json.dump(data, open(out_p, "w"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen), open(seen_p, "w"))
    for r in nuovi:
        print(f"🟢 [{r['campionato']}] {r['casa']} - {r['ospite']}  {r['punteggio_live']} al {minute}'  "
              f"xG {r['xg'][0]:.2f}-{r['xg'][1]:.2f}  proiez. {r['proj'][0]:.2f}-{r['proj'][1]:.2f}  "
              f"TOTALE OVERDUE {r['totale']}  esito {r['esito']}" + (f"  (finale {r['finale']})" if r['finale'] else ""))
    print(f"Scansionate {len(cand)} partite, {len(nuovi)} nuove da metodo.")

if __name__ == "__main__": main()
