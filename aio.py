#!/usr/bin/env python3
"""
Scrape 10 high-AIO-probability vegan queries via DataForSEO (live Google DE SERP),
detect AI Overviews, extract what shows up in them (text + cited sources), check if
veganblatt.com is cited, then combine with VeganBlatt's GSC data to estimate the
traffic impact of AI Overviews. Writes aio.json.
"""
import os, json, base64, urllib.request

LOGIN = os.environ["DATAFORSEO_LOGIN"]; PW = os.environ["DATAFORSEO_PASSWORD"]
URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
AUTH = base64.b64encode(f"{LOGIN}:{PW}".encode()).decode()

# 10 informational vegan queries with high AIO probability.
# gsc = {impressions, position} pulled from VeganBlatt's own 90-day GSC export (monthly = /3).
QUERIES = [
    ("juice cleanse",            {"imp": 7759, "pos": 10.5, "clicks": 1}),
    ("ist kakaobutter vegan",    {"imp": 3522, "pos": 5.6,  "clicks": 0}),
    ("ist milchsäure vegan",     {"imp": 4159, "pos": 7.2,  "clicks": 1}),
    ("ist red bull vegan",       {"imp": 3790, "pos": 6.3,  "clicks": 14}),
    ("sind oreos vegan",         {"imp": 3321, "pos": 7.5,  "clicks": 2}),
    ("ist honig vegan",          {"imp": 2214, "pos": 3.2,  "clicks": 0}),
    ("ist agavendicksaft gesund",{"imp": 2044, "pos": 2.5,  "clicks": 0}),
    ("ist tofu gesund",          {"imp": 928,  "pos": 2.2,  "clicks": 0}),
    ("ist margarine vegan",      {"imp": 947,  "pos": 2.5,  "clicks": 0}),
    ("ist skyr vegan",           {"imp": 1205, "pos": 8.3,  "clicks": 0}),
]

def scrape(kw):
    payload = [{"keyword": kw, "location_code": 2276, "language_code": "de",
                "device": "desktop", "load_async_ai_overview": True}]
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Basic {AUTH}", "Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=90))
    items = resp["tasks"][0]["result"][0]["items"] or []
    aio = next((i for i in items if i["type"] == "ai_overview"), None)
    vb_pos = next((i.get("rank_absolute") for i in items
                   if i["type"] == "organic" and "veganblatt" in (i.get("domain") or "")), None)
    refs = []
    text_parts = []
    if aio:
        # references can live at top level and/or inside each markdown element
        def collect_refs(node):
            for ref in (node.get("references") or []):
                dom = ref.get("domain") or ""
                refs.append({"domain": dom, "title": ref.get("title", ""), "url": ref.get("url", "")})
        collect_refs(aio)
        for el in (aio.get("items") or []):
            if el.get("text"): text_parts.append(el["text"])
            collect_refs(el)
    # dedupe refs by domain (keep order)
    seen = set(); uref = []
    for x in refs:
        if x["domain"] and x["domain"] not in seen:
            seen.add(x["domain"]); uref.append(x)
    vb_cited = any("veganblatt" in x["domain"] for x in uref)
    return {
        "has_aio": aio is not None,
        "aio_text": " ".join(text_parts)[:600],
        "ref_count": len(uref),
        "refs": uref[:8],
        "vb_cited": vb_cited,
        "vb_organic_pos": vb_pos,
    }

# ---- CTR model (informational query, desktop). Stated assumptions. ----
# Baseline organic CTR by position WITHOUT an AI Overview.
def base_ctr(pos):
    table = {1:0.27,2:0.15,3:0.10,4:0.073,5:0.053,6:0.040,7:0.030,8:0.024,9:0.020,10:0.018}
    p = max(1, round(pos))
    return table.get(p, 0.012)
AIO_SUPPRESSION = 0.45   # AIO present pushes organic down -> ~45% of organic clicks lost
AIO_CITED_CTR   = 0.025  # a link cited inside the AIO earns ~2.5% CTR (visible source chip)

results = []
for kw, g in QUERIES:
    s = scrape(kw)
    monthly_imp = round(g["imp"] / 3)            # 90d export -> ~monthly
    bctr = base_ctr(g["pos"])
    clicks_no_aio = round(monthly_imp * bctr)    # what the ranking "should" earn without AIO
    if s["has_aio"]:
        if s["vb_cited"]:
            # keep suppressed organic clicks + recover via AIO citation
            clicks_with_aio = round(monthly_imp * bctr * (1 - AIO_SUPPRESSION) + monthly_imp * AIO_CITED_CTR)
        else:
            clicks_with_aio = round(monthly_imp * bctr * (1 - AIO_SUPPRESSION))
    else:
        clicks_with_aio = clicks_no_aio
    impact = clicks_with_aio - clicks_no_aio     # negative = clicks lost to AIO
    results.append({
        "query": kw, **g, "monthly_impressions": monthly_imp,
        "has_aio": s["has_aio"], "ref_count": s["ref_count"], "refs": s["refs"],
        "vb_cited": s["vb_cited"], "vb_organic_pos": s["vb_organic_pos"],
        "aio_text": s["aio_text"],
        "clicks_no_aio": clicks_no_aio, "clicks_with_aio": clicks_with_aio,
        "monthly_impact": impact,
    })
    flag = "AIO" if s["has_aio"] else "no-AIO"
    cite = " [veganblatt CITED]" if s["vb_cited"] else (" [not cited]" if s["has_aio"] else "")
    print(f"{kw:28} {flag:6} refs={s['ref_count']:2} vb_pos={s['vb_organic_pos']}{cite}  impact {impact:+} clk/mo")

n_aio = sum(1 for r in results if r["has_aio"])
n_cited = sum(1 for r in results if r["vb_cited"])
total_impact = sum(r["monthly_impact"] for r in results)
top_domains = {}
for r in results:
    for x in r["refs"]:
        top_domains[x["domain"]] = top_domains.get(x["domain"], 0) + 1
top_domains = sorted(top_domains.items(), key=lambda x:-x[1])[:12]

out = {
    "source": "DataForSEO live Google SERP (location=Germany/2276, lang=de, desktop)",
    "model_assumptions": {
        "aio_suppression": AIO_SUPPRESSION,
        "aio_cited_ctr": AIO_CITED_CTR,
        "note": "Impact = geschaetzte monatliche Klicks MIT AIO minus OHNE AIO, basierend auf "
                "VeganBlatt-Impressionen (GSC) x positionsabhaengiger CTR. Annahmen, keine Messung."
    },
    "summary": {"queries": len(results), "with_aio": n_aio, "vb_cited": n_cited,
                "total_monthly_impact": total_impact},
    "top_cited_domains": [{"domain": d, "count": c} for d, c in top_domains],
    "results": results,
}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"aio.json"),"w"),
          ensure_ascii=False, indent=2)
print(f"\nAIO in {n_aio}/{len(results)} | veganblatt cited in {n_cited} | net impact {total_impact:+} clicks/mo")
print("wrote aio.json")
