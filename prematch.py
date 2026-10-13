#!/usr/bin/env python3
"""Pre-partita: metodo Overdue al minuto 0 con xG medi + Poisson + Indice Overdue. Scrive prematch.json."""
import argparse, datetime as dt, json, math, os
from zoneinfo import ZoneInfo
import numpy as np
import fm
ROME = ZoneInfo("Europe/Rome"); N = 8; SOGLIA = 0.30
CAL = os.path.join(fm.HERE, "cache", "calibrazione.json")

def history(cache):
    rows = [v for v in cache.values() if not v.get("noxg")]
    return sorted(rows, key=lambda r: r["t"])

def team_avgs(rows, tid, before, venue):
    """medie ultime N: (xGF, xGA, xGF_HT, xGA_HT, n). venue 0=casa,1=trasferta; split se >=3 partite."""
    past = [r for r in rows if r["t"] < before and tid in (r["h"], r["a"])]
    sp = [r for r in past if (r["h"] if venue == 0 else r["a"]) == tid]
    use = sp[-N:] if len(sp) >= 3 else past[-N:]
    if len(use) < 3: return None
    f = []; 
    for r in use:
        k = 0 if r["h"] == tid else 1
        xh = r["xh"] or [r["xg"][0] * .45, r["xg"][1] * .45]
        f.append((r["xg"][k], r["xg"][1 - k], xh[k], xh[1 - k]))
    a = np.mean(f, axis=0)
    return [float(x) for x in a] + [len(use)]

def pois(l, n=11): return np.array([math.exp(-l) * l**i / math.factorial(i) for i in range(n)])

def overdue_index(lh, la, k, sims=6000, rng=None):
    rng = rng or np.random.default_rng(1)
    x = rng.gamma(k, [lh / k, la / k], size=(sims, 2))
    g = rng.poisson(x)
    proj = np.round(x * 1.5, 2)
    return float((np.floor((proj - g).sum(1)) > 0).mean())

def predict(rows, h, a, before, k):
    H, A = team_avgs(rows, h, before, 0), team_avgs(rows, a, before, 1)
    if not H or not A: return None
    xh, xa = round((H[0] + A[1]) / 2, 2), round((A[0] + H[1]) / 2, 2)
    hh, ha = (H[2] + A[3]) / 2, (A[2] + H[3]) / 2
    # Metodo Overdue al minuto 0 (proiezione = xG medio, 0 gol)
    proj = [xh, xa]; pa = [math.floor(p) for p in proj]; xs = proj[:]
    d = xh - xa
    m = {"xg_media": proj, "match_xg": round(xh + xa, 2), "proiezione": proj, "punteggio_atteso": pa,
         "gol_attesi": sum(pa), "xsxg": xs, "team_overdue": [max(0, p) for p in pa],
         "totale_overdue": math.floor(sum(xs)),
         "esito": "Pareggio" if abs(d) < SOGLIA else ("Vittoria Casa" if d > 0 else "Vittoria Ospite")}
    M = np.outer(pois(xh), pois(xa)); n = M.shape[0]
    i, j = np.indices(M.shape); tot = i + j
    top = sorted(((M[a_, b_], f"{a_}-{b_}") for a_ in range(6) for b_ in range(6)), reverse=True)[:3]
    m.update(p1=float(M[i > j].sum()), px=float(M[i == j].sum()), p2=float(M[i < j].sum()),
             o15=float(M[tot > 1].sum()), o25=float(M[tot > 2].sum()), gg=float(M[(i > 0) & (j > 0)].sum()),
             top3=[[s, round(float(p), 3)] for p, s in top], xg_ht=[round(hh, 2), round(ha, 2)],
             proiez_ht=[round(hh * 1.5, 2), round(ha * 1.5, 2)], indice_overdue=overdue_index(hh, ha, k),
             n=[H[4], A[4]])
    return m

def da_metodo(r):
    if not r["xh"]: return None
    return math.floor(sum(round(x * 1.5, 2) - g for x, g in zip(r["xh"], r["gh"]))) > 0

def backtest(rows, ks=(1, 2, 3, 5, 8, 15)):
    data = []
    for r in rows:
        y = da_metodo(r)
        if y is None: continue
        H, A = team_avgs(rows, r["h"], r["t"], 0), team_avgs(rows, r["a"], r["t"], 1)
        if not H or not A: continue
        data.append((r, y, (H[2] + A[3]) / 2, (A[2] + H[3]) / 2, (H[0] + A[1]) / 2, (A[0] + H[1]) / 2))
    if len(data) < 30: return None
    ys = np.array([d[1] for d in data], float); res = {"n": len(data), "base_rate": float(ys.mean())}
    best = None
    for k in ks:
        p = np.array([overdue_index(d[2], d[3], k, 3000) for d in data])
        b = float(((p - ys) ** 2).mean())
        if not best or b < best[1]: best = (k, b, p)
    k, b, p = best
    q = np.quantile(p, [.2, .8])
    res.update(k=k, brier=b, brier_base=float(((ys.mean() - ys) ** 2).mean()), media_pred=float(p.mean()),
               hit_top20=float(ys[p >= q[1]].mean()), hit_bottom20=float(ys[p <= q[0]].mean()))
    # Poisson over 2.5 / 1X2 e metodo minuto 0
    o, ok1x2, tot0 = [], 0, 0
    for d in data:
        r = d[0]; M = np.outer(pois(d[4]), pois(d[5])); i, j = np.indices(M.shape)
        g = sum(r["g"]); o.append((float(M[i + j > 2].sum()), g > 2))
        pr = [M[i > j].sum(), M[i == j].sum(), M[i < j].sum()]
        act = 0 if r["g"][0] > r["g"][1] else (1 if r["g"][0] == r["g"][1] else 2)
        ok1x2 += int(np.argmax(pr) == act)
        tot0 += int(math.floor(d[4] + d[5]) > 0)
    po, yo = np.array([x[0] for x in o]), np.array([x[1] for x in o], float)
    res.update(o25_brier=float(((po - yo) ** 2).mean()), o25_base=float(((yo.mean() - yo) ** 2).mean()),
               o25_rate=float(yo.mean()), acc_1x2=ok1x2 / len(data), quota_overdue0_pos=tot0 / len(data))
    return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--no-update", action="store_true")
    ap.add_argument("--backtest", action="store_true"); a = ap.parse_args()
    cache = fm.load_cache()
    fixtures = {} if a.no_update else fm.update_cache(cache)
    rows = history(cache)
    cal = json.load(open(CAL)) if os.path.exists(CAL) else {}
    if a.backtest or not cal:
        bt = backtest(rows)
        if bt: cal = bt; json.dump(cal, open(CAL, "w"), indent=1); print(json.dumps(cal, indent=1))
    k = cal.get("k", 3)
    now = dt.datetime.now(ROME); days = {now.date(), now.date() + dt.timedelta(days=1)}
    out = []
    for lid, ms in fixtures.items():
        for m in ms:
            st = m["status"]
            if st.get("finished") or st.get("cancelled"): continue
            t = dt.datetime.fromisoformat(st["utcTime"].replace("Z", "+00:00")).astimezone(ROME)
            if t.date() not in days: continue
            p = predict(rows, int(m["home"]["id"]), int(m["away"]["id"]), st["utcTime"][:16], k)
            if not p: continue
            out.append({"id": int(m["id"]), "campionato": fm.LEAGUES[lid], "ora": t.strftime("%d/%m %H:%M"),
                        "casa": m["home"]["name"], "ospite": m["away"]["name"], **p})
    out.sort(key=lambda x: x["ora"])
    json.dump({"aggiornato": now.strftime("%d/%m/%Y %H:%M"), "calibrazione": cal, "matches": out},
              open(os.path.join(fm.HERE, "prematch.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{len(out)} partite pre-match scritte")

if __name__ == "__main__": main()
