#!/usr/bin/env python3
"""
Overlay Austrian + German holidays / school vacations / seasonal events on the
VeganBlatt daily GSC curve and measure their real impact.

Method: the site is in strong growth, so raw numbers can't be compared across time.
We DETREND by dividing each day's clicks by a 15-day centered rolling average
(the local "expected" level). ratio>1 = better than trend, <1 = worse.
Then we aggregate that ratio over holiday windows and by weekday.
Writes seasonal.json next to this file.
"""
import csv, json, os, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
daily = list(csv.DictReader(open(os.path.expanduser("~/Data/veganblatt-gsc/gsc_daily.csv"))))
for r in daily:
    r["clicks"] = int(r["clicks"]); r["impressions"] = int(r["impressions"])
    r["d"] = date.fromisoformat(r["date"])
clicks = [r["clicks"] for r in daily]
N = len(daily)

# ---- detrend: centered rolling avg, window 15 ----
def centered_avg(vals, i, w=15):
    half = w // 2
    lo, hi = max(0, i - half), min(len(vals), i + half + 1)
    return sum(vals[lo:hi]) / (hi - lo)
for i, r in enumerate(daily):
    base = centered_avg(clicks, i)
    r["expected"] = round(base, 1)
    r["ratio"] = round(r["clicks"] / base, 3) if base else 1.0
    r["dev_pct"] = round((r["ratio"] - 1) * 100, 1)

by_date = {r["d"]: r for r in daily}

# ---- public holidays in window (2026-03-08 .. 06-05) ----
# AT = Austria, DE = Germany (most/all Bundeslaender)
HOLIDAYS = [
    ("2026-04-03", "Karfreitag (Good Friday)", "DE"),
    ("2026-04-05", "Ostersonntag (Easter Sunday)", "AT+DE"),
    ("2026-04-06", "Ostermontag (Easter Monday)", "AT+DE"),
    ("2026-05-01", "Staatsfeiertag / Tag der Arbeit", "AT+DE"),
    ("2026-05-10", "Muttertag (Mother's Day)", "AT+DE"),
    ("2026-05-14", "Christi Himmelfahrt (Ascension)", "AT+DE"),
    ("2026-05-24", "Pfingstsonntag (Pentecost)", "AT+DE"),
    ("2026-05-25", "Pfingstmontag (Whit Monday)", "AT+DE"),
    ("2026-06-04", "Fronleichnam (Corpus Christi)", "AT+DE(t)"),
]
holidays = []
for ds, name, scope in HOLIDAYS:
    d = date.fromisoformat(ds)
    if d in by_date:
        r = by_date[d]
        holidays.append({"date": ds, "name": name, "scope": scope,
                         "clicks": r["clicks"], "expected": r["expected"],
                         "dev_pct": r["dev_pct"], "weekday": d.strftime("%a")})

# ---- school-vacation windows (approx; vary by Bundesland) ----
VACATIONS = [
    ("Osterferien (AT)", "2026-03-28", "2026-04-06", "AT"),
    ("Osterferien (DE, gemittelt)", "2026-03-23", "2026-04-11", "DE"),
    ("Pfingstferien (Teil DE/Bayern)", "2026-05-26", "2026-06-05", "DE"),
]
def window_stats(start, end):
    rs = [by_date[d] for d in by_date if date.fromisoformat(start) <= d <= date.fromisoformat(end)]
    if not rs: return None
    return round(statistics.mean(r["ratio"] for r in rs), 3), len(rs)
vacations = []
for name, s, e, scope in VACATIONS:
    st = window_stats(s, e)
    if st:
        vacations.append({"name": name, "start": s, "end": e, "scope": scope,
                          "avg_ratio": st[0], "dev_pct": round((st[0]-1)*100,1), "days": st[1]})

# ---- weekday effect ----
dow_order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
dow = {k: [] for k in dow_order}
for r in daily:
    dow[r["d"].strftime("%a")].append(r["ratio"])
weekday = [{"day": k, "avg_ratio": round(statistics.mean(v),3),
            "dev_pct": round((statistics.mean(v)-1)*100,1)} for k, v in dow.items()]

# ---- holiday aggregate: are public holidays good or bad for traffic? ----
hol_dates = {date.fromisoformat(h[0]) for h in HOLIDAYS}
hol_ratios = [by_date[d]["ratio"] for d in hol_dates if d in by_date]
nonhol_ratios = [r["ratio"] for r in daily if r["d"] not in hol_dates]
hol_avg = round(statistics.mean(hol_ratios), 3)
nonhol_avg = round(statistics.mean(nonhol_ratios), 3)

# ---- Easter zoom (window around Easter) ----
easter_window = [{"date": r["date"], "clicks": r["clicks"], "dev_pct": r["dev_pct"],
                  "weekday": r["d"].strftime("%a")}
                 for r in daily if date(2026,3,30) <= r["d"] <= date(2026,4,12)]

out = {
    "method": "Detrending: clicks / 15-Tage zentrierter gleitender Mittelwert. Ratio 1,00 = exakt im Trend; >1 ueberdurchschnittlich, <1 darunter. So wird das starke Gesamtwachstum herausgerechnet.",
    "daily": [{"date": r["date"], "clicks": r["clicks"], "expected": r["expected"],
               "ratio": r["ratio"], "dev_pct": r["dev_pct"]} for r in daily],
    "holidays": holidays,
    "vacations": vacations,
    "weekday": weekday,
    "holiday_summary": {"holiday_avg_ratio": hol_avg, "normal_avg_ratio": nonhol_avg,
                        "holiday_effect_pct": round((hol_avg/nonhol_avg-1)*100,1)},
    "easter_window": easter_window,
    "seasonal_themes": [
        {"event":"Ostern (5. Apr)","note":"Backen & Festtagsrezepte: 'veganer marillenkuchen', 'vegane hochzeitstorte', 'salzburger nockerl', 'veganes erdbeer tiramisu' - klassische Oster-/Fruehlingsbacknachfrage."},
        {"event":"Muttertag (10. Mai)","note":"Torten & Desserts: 'vegane tortencreme', 'vegane hochzeitstorte rezept' - Anlass-Backen, ideal fuer terminierte Artikel."},
        {"event":"Fruehling -> Sommer","note":"Eis & leichte Kueche steigen: 'ninja creami vegane rezepte', 'kaktus eis vegan', 'juice cleanse', 'vegane tapas' - Saisonshift Richtung kalte/leichte Gerichte."},
        {"event":"Pfingsten/Feiertage","note":"Lange Wochenenden = Grill- & Ausflugskueche; Produkt-Checks ('haribo vegan','skittles vegan') laufen ganzjaehrig stabil."},
    ],
}
json.dump(out, open(os.path.join(HERE,"seasonal.json"),"w"), ensure_ascii=False, indent=2)
print("wrote seasonal.json")
print("holiday avg ratio", hol_avg, "vs normal", nonhol_avg, "=> effect", out["holiday_summary"]["holiday_effect_pct"],"%")
print("weekday:", [(w["day"], w["dev_pct"]) for w in weekday])
print("vacations:", [(v["name"], v["dev_pct"]) for v in vacations])
print("holidays detail:")
for h in holidays: print(f"  {h['date']} {h['weekday']} {h['name'][:30]:30} dev {h['dev_pct']:+.1f}%")
