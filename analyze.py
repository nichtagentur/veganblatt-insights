#!/usr/bin/env python3
"""
VeganBlatt Google Search Console -> insights data.json
Acts as the "data scientist" layer: clean, aggregate, find the story.
Stdlib only. Reads ~/Data/veganblatt-gsc/*.csv, writes data.json next to this file.
"""
import csv, json, os, re, statistics
from datetime import date

SRC = os.path.expanduser("~/Data/veganblatt-gsc")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

def rd(name):
    with open(os.path.join(SRC, name), newline="") as f:
        return list(csv.DictReader(f))

# ---------- daily series ----------
daily = rd("gsc_daily.csv")
for r in daily:
    r["clicks"] = int(r["clicks"]); r["impressions"] = int(r["impressions"])
    r["ctr"] = r["clicks"] / r["impressions"] if r["impressions"] else 0
clicks = [r["clicks"] for r in daily]
imps   = [r["impressions"] for r in daily]
dates  = [r["date"] for r in daily]

def rolling(vals, w=7):
    out = []
    for i in range(len(vals)):
        lo = max(0, i - w + 1)
        out.append(round(sum(vals[lo:i+1]) / (i - lo + 1), 1))
    return out

first14 = sum(clicks[:14]) / 14
last14  = sum(clicks[-14:]) / 14
growth_mult = round(last14 / first14, 1) if first14 else 0
growth_pct  = round((last14 - first14) / first14 * 100) if first14 else 0

# ---------- totals ----------
summ = rd("gsc_summary.csv")[0]
tot_clicks = int(summ["clicks"]); tot_imps = int(summ["impressions"])
avg_ctr = tot_clicks / tot_imps

# ---------- top queries ----------
q = rd("gsc_top_queries.csv")
for r in q:
    r["clicks"] = int(r["clicks"]); r["impressions"] = int(r["impressions"])
    r["ctr"] = float(r["ctr"]); r["position"] = float(r["position"])
q.sort(key=lambda r: -r["clicks"])
avg_pos = round(statistics.mean(r["position"] for r in q if r["clicks"] > 0), 1)

top_queries = [
    {"query": r["query"], "clicks": r["clicks"], "impressions": r["impressions"],
     "ctr": round(r["ctr"], 4), "position": r["position"]}
    for r in q[:25]
]

# ---------- theme tagging ----------
def theme(query):
    s = query.lower()
    if re.search(r"\be\d{3}\b", s) or "cystein" in s:            return "E-Nummern & Zusatzstoffe"
    if s.startswith("ist ") or "vegan?" in s or re.search(r"\bist\b.*vegan", s): return "Ist X vegan?"
    if any(w in s for w in ["rezept", "suppe", "kuchen", "backen", "selber machen"]): return "Rezepte"
    if any(w in s for w in ["zahnpasta", "kosmetik", "creme", "shampoo", "lippen"]):   return "Beauty & Pflege"
    if "vegan" in s:                                              return "Produkte & Marken"
    return "Sonstige"

theme_tot = {}
for r in q:
    t = theme(r["query"])
    d = theme_tot.setdefault(t, {"clicks": 0, "impressions": 0, "queries": 0})
    d["clicks"] += r["clicks"]; d["impressions"] += r["impressions"]; d["queries"] += 1
themes = sorted(
    [{"theme": k, **v} for k, v in theme_tot.items()],
    key=lambda x: -x["clicks"]
)

# ---------- striking distance (pos 4-15, high impressions, low CTR) ----------
# target CTR per position bucket (typical Google curve) -> estimate uplift if we earn pos 1-3
TARGET = {1: 0.28, 2: 0.16, 3: 0.11}
def target_ctr(pos):  # if moved to top-3 / title fixed, assume ~pos3 CTR floor
    return 0.11
strike = []
for r in q:
    if 4 <= r["position"] <= 15 and r["impressions"] >= 1500:
        monthly_imps = r["impressions"] / 3  # 90d -> ~monthly
        uplift = round(monthly_imps * target_ctr(r["position"]) - r["clicks"] / 3)
        strike.append({
            "query": r["query"], "impressions": r["impressions"],
            "position": r["position"], "ctr": round(r["ctr"], 4),
            "clicks": r["clicks"], "uplift_per_month": max(uplift, 0)
        })
strike.sort(key=lambda x: -x["uplift_per_month"])
strike = strike[:18]

# ---------- zero-click high-impression (content gaps) ----------
zero = [
    {"query": r["query"], "impressions": r["impressions"], "position": r["position"]}
    for r in q if r["clicks"] == 0 and r["impressions"] >= 800
]
zero.sort(key=lambda x: -x["impressions"])
zero = zero[:15]

# ---------- long tail concentration ----------
tot_q_clicks = sum(r["clicks"] for r in q)
cum = 0; n80 = 0
for r in q:
    cum += r["clicks"]; n80 += 1
    if cum >= 0.8 * tot_q_clicks:
        break
zero_click_q = sum(1 for r in q if r["clicks"] == 0)
zero_click_imps = sum(r["impressions"] for r in q if r["clicks"] == 0)

meta = json.load(open(os.path.join(SRC, "fetch_metadata.json")))

data = {
    "meta": {
        "site": "veganblatt.com", "start": meta["start"], "end": meta["end"],
        "days": meta["days"], "generated": date.today().isoformat(),
    },
    "kpi": {
        "clicks": tot_clicks, "impressions": tot_imps,
        "ctr": round(avg_ctr, 4), "avg_position": avg_pos,
        "growth_mult": growth_mult, "growth_pct": growth_pct,
        "first14": round(first14), "last14": round(last14),
    },
    "daily": [
        {"date": d, "clicks": c, "impressions": i, "roll": rc}
        for d, c, i, rc in zip(dates, clicks, imps, rolling(clicks))
    ],
    "top_queries": top_queries,
    "themes": themes,
    "striking_distance": strike,
    "zero_click": zero,
    "longtail": {
        "total_queries": len(q), "queries_for_80pct": n80,
        "zero_click_queries": zero_click_q, "zero_click_impressions": zero_click_imps,
    },
    "data_quality": {
        "branded_tracking_broken": True,
        "note": "Branded-Filter der GSC-Auswertung liefert 0 (obwohl 'veganblatt' 72 Klicks hat) "
                "- Brand/Non-Brand-Split ist unzuverlassig und sollte neu konfiguriert werden.",
    },
}

with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("wrote", OUT)
print(f"clicks={tot_clicks} imps={tot_imps} ctr={avg_ctr:.3f} avg_pos={avg_pos} "
      f"growth={growth_mult}x ({growth_pct}%) strike={len(strike)} zero={len(zero)} "
      f"themes={len(themes)} n80={n80}")
