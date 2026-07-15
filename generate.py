#!/usr/bin/env python3
"""
Barzo Analytics — static dashboard generator (multi-range).

Pulls results for the 23 insights on PostHog dashboard 1780675 (project 492214) across
several date ranges (24h / 7d / 30d / 90d) and writes a self-contained dark, Barzo-branded
index.html. The page has a date-range picker (defaults to Last 24 hours), a Live badge, and
a Refresh button; switching ranges is instant because every range is baked in.

Env:
    POSTHOG_API_KEY   PostHog personal API key with Insight:Read and Query:Read scopes. (required)
    POSTHOG_HOST      default https://us.posthog.com
    POSTHOG_PROJECT   default 492214
"""

import os, sys, json, copy, datetime, urllib.request, urllib.error

HOST    = os.environ.get("POSTHOG_HOST", "https://us.posthog.com").rstrip("/")
PROJECT = os.environ.get("POSTHOG_PROJECT", "492214")
APIKEY  = os.environ.get("POSTHOG_API_KEY")
if not APIKEY:
    sys.exit("ERROR: set POSTHOG_API_KEY (personal API key with Insight:Read + Query:Read).")

# key, picker label, date_from, interval
RANGES = [
    ("24h", "Last 24 hours", "-24h", "hour"),
    ("7d",  "Last 7 days",   "-7d",  "day"),
    ("30d", "Last 30 days",  "-30d", "day"),
    ("90d", "Last 90 days",  "-90d", "week"),
]
DEFAULT_RANGE = "24h"

# Creator stats snapshot (Barzo admin is login-only, so these are baked in here and
# refreshed by editing this list — the local scheduled task keeps the Desktop copy live).
CREATORS = [
    {"name": "Ezz Marie", "handle": "EzzMariePours", "id": "871f27c2-fd34-4db7-8294-51af28253b23", "img": "https://d1jrh1izqpu5zr.cloudfront.net/users/871f27c2-fd34-4db7-8294-51af28253b23/content/IMG_2268.jpeg", "followers": "137", "following": "308", "posts": "256", "likes": "2.7K"},
    {"name": "Rodney Charelus", "handle": "Rodneyc3", "id": "b739d3c9-27fc-4d30-ada9-5b2e9f247d93", "img": "https://d1jrh1izqpu5zr.cloudfront.net/users/b739d3c9-27fc-4d30-ada9-5b2e9f247d93/content/IMG_7318.jpeg", "followers": "11", "following": "21", "posts": "18", "likes": "48"},
    {"name": "Broderick Scott", "handle": "Buckwheat", "id": "908355d1-134b-4bf7-ac19-96a694129cc3", "img": "", "followers": "4", "following": "3", "posts": "2", "likes": "6"},
    {"name": "AJ Hall", "handle": "AJHALLSELECTS", "id": "2f422da9-5ef7-4aa2-b1ee-a199c2ce9c19", "img": "", "followers": "0", "following": "1", "posts": "0", "likes": "0"},
]

# insight numeric id -> role key
INSIGHTS = {
    9701865: "wau", 9701864: "dau", 9708024: "opens", 9706170: "new_accounts",
    9706236: "free_drinks", 9706228: "sys_signups", 9706230: "smiles_sent",
    9708037: "nearby_alerts", 9709526: "friend_requests", 9709578: "posts",
    9709504: "drinks_sent", 9709484: "vouchers", 9707618: "reg_redemp",
    9706707: "sys_activity", 9707512: "smiles_by_type", 9707950: "top_screens",
    9707840: "top_venues_v", 9708954: "top_events_v", 9709004: "top_venues_c",
    9708390: "perm_denials", 9708054: "alert_int", 9708125: "funnel",
}

def _req(url, data=None):
    headers = {"Authorization": f"Bearer {APIKEY}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)

def get_source(iid):
    """Return (source_query_dict, kind) for an insight."""
    ins = _req(f"{HOST}/api/projects/{PROJECT}/insights/{iid}/")
    q = ins.get("query") or {}
    if q.get("kind") == "InsightVizNode":
        return q.get("source") or {}, (q.get("source") or {}).get("kind")
    return q, q.get("kind")

def run_query(source, date_from, interval):
    """POST the query with an overridden date range/interval; return the results list."""
    src = copy.deepcopy(source)
    src["dateRange"] = {"date_from": date_from, "date_to": None}
    if "interval" in src and src.get("kind") in ("TrendsQuery", "StickinessQuery", "LifecycleQuery"):
        src["interval"] = interval
    resp = _req(f"{HOST}/api/projects/{PROJECT}/query/", {"query": src})
    return resp.get("results") if resp.get("results") is not None else resp.get("result") or []

def fmt_label(iso, interval):
    s = str(iso).replace("Z", "")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return str(iso)
    return dt.strftime("%-I%p") if interval == "hour" else dt.strftime("%b %-d")

def trim_leading_zero(days, series_list):
    n = len(days)
    start = 0
    for i in range(n):
        if any((s[i] or 0) for s in (s2 for s2 in series_list)):
            start = i
            break
    return days[start:], [s[start:] for s in series_list]

def series_name(s):
    a = s.get("action")
    if isinstance(a, dict) and a.get("name"):
        return a["name"]
    return s.get("label", "") or ""

def build_range(raw, interval):
    def res(k): return raw.get(k) or []
    def agg(k):
        r = res(k)
        if not r: return 0
        s = r[0]
        if s.get("aggregated_value") is not None: return round(s["aggregated_value"])
        return round(sum(s.get("data") or []))
    def daily(k):
        r = res(k)
        if not r: return [], []
        s = r[0]
        return [fmt_label(d, interval) for d in (s.get("days") or [])], [round(x) for x in (s.get("data") or [])]
    def by_name(k, name):
        for s in res(k):
            if name.lower() in series_name(s).lower():
                return [round(x) for x in (s.get("data") or [])], [fmt_label(d, interval) for d in (s.get("days") or [])]
        return [], []
    def breakdown(k, top=None, drop=("Other", "None")):
        pairs = []
        for s in res(k):
            nm = s.get("breakdown_value")
            if isinstance(nm, list): nm = ", ".join(map(str, nm))
            nm = str(nm)
            low = nm.lower()
            # normalize PostHog's internal sentinels + empties to friendly labels
            if "posthog_breakdown_other" in low: nm = "Other"
            elif "posthog_breakdown_null" in low or nm.strip() in ("", "null", "None", "nan"): nm = "None"
            val = s.get("aggregated_value")
            if val is None: val = sum(s.get("data") or [])
            if any(d.lower() in nm.lower() for d in drop): continue
            pairs.append((nm, round(val)))
        pairs.sort(key=lambda p: -p[1])
        if top: pairs = pairs[:top]
        return {"labels": [p[0] for p in pairs], "data": [p[1] for p in pairs]}

    dau_days, dau_data = daily("dau")
    opens_days, opens_data = daily("opens")
    if dau_data: dau_days, (dau_data,) = trim_leading_zero(dau_days, [dau_data])
    if opens_data: opens_days, (opens_data,) = trim_leading_zero(opens_days, [opens_data])

    dau_peak = max(dau_data) if dau_data else 0
    kpis = [
        {"label": "Active Users", "value": agg("wau"), "meta": "unique in range"},
        {"label": "Peak Active Users", "value": dau_peak,
         "meta": ("busiest hour" if interval == "hour" else "busiest day")},
        {"label": "App Opens", "value": sum(opens_data) if opens_data else agg("opens")},
        {"label": "New Accounts", "value": agg("new_accounts")},
        {"label": "Smiles Sent", "value": agg("smiles_sent")},
        {"label": "Nearby Alerts Shown", "value": agg("nearby_alerts")},
        {"label": "Free Drinks Redeemed", "value": agg("free_drinks")},
        {"label": "Friend Requests", "value": agg("friend_requests")},
        {"label": "Posts", "value": agg("posts")},
        {"label": "SYS Signups", "value": agg("sys_signups")},
        {"label": "Drinks Sent", "value": agg("drinks_sent")},
        {"label": "Vouchers Purchased", "value": agg("vouchers")},
    ]

    acc, rr_days = by_name("reg_redemp", "account_created")
    fdr, _ = by_name("reg_redemp", "free_drink_redeemed")
    dre, _ = by_name("reg_redemp", "drink_redeemed")
    if rr_days: rr_days, (acc, fdr, dre) = trim_leading_zero(rr_days, [acc, fdr, dre])
    ssent, sys_days = by_name("sys_activity", "smile_sent")
    sreg, _ = by_name("sys_activity", "sys_registration_completed")
    if sys_days: sys_days, (ssent, sreg) = trim_leading_zero(sys_days, [ssent, sreg])

    st_series, st_days = [], []
    for s in res("smiles_by_type"):
        bv = s.get("breakdown_value")
        if isinstance(bv, list):
            try: bv = "–".join(str(round(float(x), 1)) for x in bv)
            except Exception: bv = ", ".join(map(str, bv))
        st_series.append({"label": str(bv), "data": [round(x) for x in (s.get("data") or [])]})
        if not st_days: st_days = [fmt_label(d, interval) for d in (s.get("days") or [])]
    if st_days and st_series:
        st_days, trimmed = trim_leading_zero(st_days, [s["data"] for s in st_series])
        for s, t in zip(st_series, trimmed): s["data"] = t

    fr = res("funnel")
    if fr and isinstance(fr, list) and len(fr) >= 2 and isinstance(fr[0], dict) and "count" in fr[0]:
        f0, f1 = fr[0].get("count", 0), fr[1].get("count", 0)
    else:
        f0 = f1 = 0
    conv = round(100 * f1 / f0, 1) if f0 else 0

    return {
        "kpis": kpis,
        "dau": {"days": dau_days, "data": dau_data},
        "opens": {"days": opens_days, "data": opens_data},
        "reg": {"days": rr_days, "accounts": acc, "free": fdr, "drinks": dre},
        "sys": {"days": sys_days, "smiles": ssent, "signups": sreg},
        "smiles_by_type": {"days": st_days, "series": st_series},
        "top_screens": breakdown("top_screens", top=30, drop=()),
        "top_venues_v": breakdown("top_venues_v", top=30),
        "top_events_v": breakdown("top_events_v", top=30),
        "top_venues_c": breakdown("top_venues_c", top=30),
        "alert_int": breakdown("alert_int", drop=()),
        "perm_denials": breakdown("perm_denials", drop=()),
        "funnel": {"shown": f0, "viewed": f1, "conv": conv},
    }

def parse():
    # fetch each insight's query source once
    sources = {}
    for iid, key in INSIGHTS.items():
        try:
            sources[key] = get_source(iid)
        except Exception as e:
            print(f"WARN source {iid} ({key}): {e}", file=sys.stderr)
            sources[key] = ({}, None)

    ranges_out = {}
    for rkey, rlabel, dfrom, interval in RANGES:
        raw = {}
        for iid, key in INSIGHTS.items():
            src, _kind = sources[key]
            if not src:
                raw[key] = []
                continue
            try:
                raw[key] = run_query(src, dfrom, interval)
            except Exception as e:
                print(f"WARN query {key} @ {rkey}: {e}", file=sys.stderr)
                raw[key] = []
        ranges_out[rkey] = build_range(raw, interval)
        print(f"built range {rkey}: WAU={ranges_out[rkey]['kpis'][0]['value']}", file=sys.stderr)

    return {
        "default": DEFAULT_RANGE,
        "rangeLabels": {k: l for (k, l, _, _) in RANGES},
        "order": [k for (k, _, _, _) in RANGES],
        "ranges": ranges_out,
        "creators": CREATORS,
    }

def render(data):
    return TEMPLATE.replace("/*__DATA__*/{}", json.dumps(data))

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Barzo Analytics</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root{--bg:#000;--panel:#0F0F0F;--panel-2:#161616;--border:#242424;--text:#FFF;--muted:#8C8C8C;--accent:#E4002B;--good:#4ADE80;--radius:14px;--gap:16px}
  *{box-sizing:border-box}html,body{margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;line-height:1.4}
  header{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:16px 28px;background:rgba(0,0,0,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
  .brand{display:flex;align-items:center;gap:14px}.brand img{height:28px;display:block}
  #wordmark{display:none;font-size:22px;font-weight:800;letter-spacing:1px;color:#fff}
  .brand .divider{width:1px;height:26px;background:var(--border)}.brand h1{font-size:16px;font-weight:600;margin:0}
  .brand .sub{font-size:12px;color:var(--muted);margin-top:1px}
  .head-right{display:flex;align-items:center;gap:14px;font-size:12px;color:var(--muted);flex-wrap:wrap}
  select#rangeSel{background:var(--panel-2);color:var(--text);border:1px solid var(--border);border-radius:9px;padding:7px 30px 7px 12px;font-size:12px;font-weight:600;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238C8C8C' stroke-width='3'><path d='M6 9l6 6 6-6'/></svg>");background-repeat:no-repeat;background-position:right 10px center}
  select#rangeSel:hover{border-color:var(--accent)}
  .live{display:flex;align-items:center;gap:7px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--good);animation:pulse 2s infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(74,222,128,.5)}70%{box-shadow:0 0 0 7px rgba(74,222,128,0)}100%{box-shadow:0 0 0 0 rgba(74,222,128,0)}}
  button.refresh{background:var(--panel-2);color:var(--text);border:1px solid var(--border);border-radius:9px;padding:7px 13px;font-size:12px;cursor:pointer;font-weight:500;display:flex;align-items:center;gap:6px}
  button.refresh:hover{border-color:var(--accent);color:var(--accent)}
  main{padding:24px 28px 60px;max-width:1440px;margin:0 auto}
  .section{margin-bottom:32px}.section-head{display:flex;align-items:baseline;gap:12px;margin:0 0 14px}
  .section-head h2{font-size:12px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;color:var(--accent);margin:0}
  .section-head .rule{flex:1;height:1px;background:var(--border)}
  .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:var(--gap)}
  .kpi{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 16px 14px;position:relative;overflow:hidden}
  .kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
  .kpi .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}
  .kpi .value{font-size:30px;font-weight:750;line-height:1;letter-spacing:-.5px}
  .kpi .meta{font-size:11px;color:var(--muted);margin-top:6px;min-height:0}
  .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:var(--gap);align-items:start}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px 14px;min-width:0;display:flex;flex-direction:column}
  .card h3{font-size:14px;font-weight:600;margin:0 0 2px}.card .cdesc{font-size:11px;color:var(--muted);margin:0 0 12px}
  .card .chartbox{position:relative;flex:1;width:100%}
  .viewall{margin-top:12px;align-self:flex-start;background:none;border:1px solid var(--border);color:var(--muted);border-radius:8px;padding:5px 11px;font-size:11px;font-weight:500;cursor:pointer}
  .viewall:hover{border-color:var(--accent);color:var(--accent)}
  .viewall.is-disabled{opacity:.45;cursor:default}
  .viewall.is-disabled:hover{border-color:var(--border);color:var(--muted)}
  .creator .ch{display:flex;align-items:center;gap:12px;margin-bottom:14px}
  .creator .cn{font-size:15px;font-weight:650}
  .creator .cu{font-size:11px;color:var(--muted)}
  .cav{width:46px;height:46px;border-radius:50%;overflow:hidden;flex:0 0 auto;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;color:#fff}
  .cav img{width:100%;height:100%;object-fit:cover;display:block}
  .creator .cstats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  .cstat{background:var(--panel-2);border-radius:9px;padding:10px 6px;text-align:center}
  .cstat .n{font-size:20px;font-weight:750;line-height:1}
  .cstat .l{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-top:4px}
  .modal-overlay{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:24px}
  .modal-panel{background:var(--panel);border:1px solid var(--border);border-radius:16px;width:min(760px,100%);max-height:86vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.6)}
  .modal-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:18px 22px;border-bottom:1px solid var(--border)}
  .modal-head h3{margin:0;font-size:17px;font-weight:650}
  .mcount{font-size:12px;color:var(--muted);margin-top:3px;display:block}
  .modal-x{background:none;border:0;color:var(--muted);font-size:16px;cursor:pointer;padding:4px 9px;border-radius:8px;line-height:1}
  .modal-x:hover{color:#fff;background:var(--panel-2)}
  .modal-body{padding:10px 22px 22px;overflow-y:auto}
  .mrow{display:grid;grid-template-columns:34px 210px 1fr 64px;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05)}
  .mrank{font-size:12px;color:var(--muted);text-align:right}
  .mlabel{font-size:13px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .mbarwrap{background:var(--panel-2);border-radius:6px;height:16px;overflow:hidden}
  .mbar{height:100%;border-radius:6px;min-width:3px}
  .mval{font-size:13px;font-weight:650;text-align:right}
  @media (max-width:640px){.mrow{grid-template-columns:26px 110px 1fr 48px;gap:8px}}
  .s4{grid-column:span 4}.s6{grid-column:span 6}.s8{grid-column:span 8}.s12{grid-column:span 12}
  .funnel{display:flex;align-items:center;justify-content:space-around;gap:16px;padding:8px 0 4px}
  .funnel .step{text-align:center;flex:1}.funnel .step .n{font-size:34px;font-weight:750}
  .funnel .step .l{font-size:12px;color:var(--muted);margin-top:4px}
  .funnel .arrow{text-align:center}.funnel .arrow .pct{font-size:22px;font-weight:750;color:var(--accent)}
  .funnel .arrow .al{font-size:11px;color:var(--muted)}
  footer{padding:22px 28px 40px;color:var(--muted);font-size:12px;text-align:center;border-top:1px solid var(--border);max-width:1440px;margin:0 auto}
  @media (max-width:1080px){.kpis{grid-template-columns:repeat(3,1fr)}.s4{grid-column:span 6}.s6{grid-column:span 12}.s8{grid-column:span 12}}
  @media (max-width:640px){header{padding:12px 16px}main{padding:18px 16px 50px}.kpis{grid-template-columns:repeat(2,1fr)}.s4,.s6,.s8{grid-column:span 12}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <img src="https://images.squarespace-cdn.com/content/v1/6765aef091d13b205284550c/32d7fae7-3c68-4fb1-a822-c6658a90559e/Barzo_white.png?format=300w" alt="Barzo" onerror="this.style.display='none';document.getElementById('wordmark').style.display='inline'">
    <span id="wordmark">BARZO</span>
    <div class="divider"></div>
    <div><h1>Analytics</h1><div class="sub">Product metrics</div></div>
  </div>
  <div class="head-right">
    <select id="rangeSel" title="Date range"></select>
    <div class="live"><span class="dot"></span> Live</div>
    <span id="updated"></span>
    <button class="refresh" onclick="location.reload()">↻ Refresh</button>
  </div>
</header>
<main>
  <section class="section"><div class="section-head"><h2>Key Metrics</h2><div class="rule"></div></div><div class="kpis" id="kpis"></div></section>
  <section class="section" id="creatorsSection" style="display:none"><div class="section-head"><h2>Creators</h2><div class="rule"></div></div>
    <div class="grid" id="creators"></div>
  </section>
  <section class="section"><div class="section-head"><h2>Activity Over Time</h2><div class="rule"></div></div>
    <div class="grid">
      <div class="card s6"><h3>Active Users</h3><p class="cdesc">Unique users over time</p><div class="chartbox" style="height:260px"><canvas id="c_dau"></canvas></div></div>
      <div class="card s6"><h3>App Opens</h3><p class="cdesc">Times the app was opened</p><div class="chartbox" style="height:260px"><canvas id="c_opens"></canvas></div></div>
      <div class="card s6"><h3>Registrations &amp; Redemptions</h3><p class="cdesc">Accounts, free drinks &amp; drinks redeemed</p><div class="chartbox" style="height:260px"><canvas id="c_reg"></canvas></div></div>
      <div class="card s6"><h3>Smiles Activity</h3><p class="cdesc">Smiles sent &amp; SYS signups</p><div class="chartbox" style="height:260px"><canvas id="c_sys"></canvas></div></div>
      <div class="card s12"><h3>Smiles by Type</h3><p class="cdesc">Smiles sent by smile level</p><div class="chartbox" style="height:240px"><canvas id="c_smiletype"></canvas></div></div>
    </div>
  </section>
  <section class="section"><div class="section-head"><h2>Discovery</h2><div class="rule"></div></div>
    <div class="grid">
      <div class="card s6"><h3>Top Screens</h3><p class="cdesc">Screen views</p><div class="chartbox" style="height:340px"><canvas id="c_screens"></canvas></div></div>
      <div class="card s6"><h3>Top Venues — Views</h3><p class="cdesc">Most-viewed venue profiles</p><div class="chartbox" style="height:340px"><canvas id="c_venuesv"></canvas></div></div>
      <div class="card s6"><h3>Top Events — Views</h3><p class="cdesc">Most-viewed event profiles</p><div class="chartbox" style="height:300px"><canvas id="c_events"></canvas></div></div>
      <div class="card s6"><h3>Top Venues — Check-Ins</h3><p class="cdesc">Most checked-into venues</p><div class="chartbox" style="height:300px"><canvas id="c_venuesc"></canvas></div></div>
    </div>
  </section>
  <section class="section"><div class="section-head"><h2>Nearby Alerts &amp; Permissions</h2><div class="rule"></div></div>
    <div class="grid">
      <div class="card s4"><h3>Alert Interactions</h3><p class="cdesc">CTA selected on nearby alerts</p><div class="chartbox" style="height:260px"><canvas id="c_alertint"></canvas></div></div>
      <div class="card s4"><h3>Permission Denials</h3><p class="cdesc">Denied prompts, by type</p><div class="chartbox" style="height:260px"><canvas id="c_perm"></canvas></div></div>
      <div class="card s4"><h3>Alert → Venue Viewed</h3><p class="cdesc">Conversion</p>
        <div class="funnel">
          <div class="step"><div class="n" id="f_shown"></div><div class="l">Alerts shown</div></div>
          <div class="arrow"><div class="pct" id="f_conv"></div><div class="al">converted</div></div>
          <div class="step"><div class="n" id="f_viewed"></div><div class="l">Venue viewed</div></div>
        </div>
      </div>
    </div>
  </section>
</main>
<footer>Barzo Analytics · data from PostHog · rebuilt hourly · showing <span id="gen"></span></footer>
<div id="modal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeModal()">
  <div class="modal-panel">
    <div class="modal-head"><div><h3 id="modalTitle"></h3><span id="modalCount" class="mcount"></span></div><button class="modal-x" onclick="closeModal()" aria-label="Close">✕</button></div>
    <div id="modalBody" class="modal-body"></div>
  </div>
</div>
<script>
const DATA = /*__DATA__*/{};
const RED="#E4002B",WHITE="#EDEDED",AMBER="#F5A623",TEAL="#3BC9B0",BLUE="#5B8DEF",PURPLE="#B58CFF";
const PALETTE=[RED,BLUE,AMBER,TEAL,PURPLE,"#FF6B81","#7DD3FC","#FBBF24","#34D399","#F472B6","#A3A3A3","#5A5A5A"];
Chart.defaults.color="#8C8C8C";Chart.defaults.font.family="-apple-system,BlinkMacSystemFont,Segoe UI,Inter,sans-serif";Chart.defaults.font.size=11;
const GRID="rgba(255,255,255,0.06)";
const axis=(e={})=>Object.assign({grid:{color:GRID},ticks:{color:"#8C8C8C"},border:{color:GRID}},e);
const noLegend={legend:{display:false}};
const legendTop={legend:{position:"top",labels:{boxWidth:10,boxHeight:10,usePointStyle:true,color:"#B5B5B5"}}};
const nf=new Intl.NumberFormat('en-US');
const CHARTS={};
const expanded={};
const DEFAULT_ROWS=8;
const lineDS=(label,data,color,fill)=>({label,data,borderColor:color,backgroundColor:fill?color+"33":color,pointRadius:2,pointHoverRadius:4,borderWidth:2,tension:.35,fill:!!fill});

function mk(id,cfg){ if(CHARTS[id]){CHARTS[id].destroy();} CHARTS[id]=new Chart(document.getElementById(id),cfg); }
function lineChart(id,labels,datasets,plugins){mk(id,{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:plugins||noLegend,scales:{x:axis({grid:{display:false}}),y:axis({beginAtZero:true})}}});}
function barChart(id,labels,data){mk(id,{type:'bar',data:{labels,datasets:[{data,backgroundColor:RED,borderRadius:4,maxBarThickness:26}]},options:{responsive:true,maintainAspectRatio:false,plugins:noLegend,scales:{x:axis({grid:{display:false}}),y:axis({beginAtZero:true})}}});}
function hbar(id,cfg,color){mk(id,{type:'bar',data:{labels:cfg.labels,datasets:[{data:cfg.data,backgroundColor:color||RED,borderRadius:4,maxBarThickness:22}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:noLegend,scales:{x:axis({beginAtZero:true}),y:axis({grid:{display:false}})}}});}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function drawBreakdown(id,cfg,color){
  const canvas=document.getElementById(id); if(!canvas) return;
  const card=canvas.closest('.card');
  const total=(cfg.labels||[]).length;
  const n=Math.min(DEFAULT_ROWS,total);
  hbar(id,{labels:cfg.labels.slice(0,n),data:cfg.data.slice(0,n)},color);
  const title=(card.querySelector('h3')||{}).textContent||'Details';
  let btn=document.getElementById('x_'+id);
  if(!btn){btn=document.createElement('button');btn.id='x_'+id;btn.className='viewall';card.appendChild(btn);}
  btn.textContent='View all '+total+'  ⤢';
  btn.onclick=function(){ openModal(title,cfg,color); };
}
function openModal(title,cfg,color){
  const max=Math.max.apply(null,(cfg.data.length?cfg.data:[1]));
  const rows=cfg.labels.map(function(l,i){
    const v=cfg.data[i]||0, w=Math.max(3,Math.round(100*v/(max||1)));
    return '<div class="mrow"><div class="mrank">'+(i+1)+'</div><div class="mlabel" title="'+esc(l)+'">'+esc(l)+'</div>'
      +'<div class="mbarwrap"><div class="mbar" style="width:'+w+'%;background:'+(color||RED)+'"></div></div>'
      +'<div class="mval">'+nf.format(v)+'</div></div>';
  }).join('');
  document.getElementById('modalTitle').textContent=title;
  document.getElementById('modalCount').textContent=cfg.labels.length+' total · '+(DATA.rangeLabels[sel.value]||sel.value);
  document.getElementById('modalBody').innerHTML=rows||'<div style="color:var(--muted);padding:20px 0">No data.</div>';
  document.getElementById('modal').style.display='flex';
}
function closeModal(){document.getElementById('modal').style.display='none';}
function doughnut(id,cfg){mk(id,{type:'doughnut',data:{labels:cfg.labels,datasets:[{data:cfg.data,backgroundColor:PALETTE,borderColor:"#0F0F0F",borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,cutout:'62%',plugins:{legend:{position:'right',labels:{boxWidth:10,boxHeight:10,usePointStyle:true,color:"#B5B5B5"}}}}});}

function render(key){
  const d=DATA.ranges[key]; if(!d) return;
  document.getElementById('kpis').innerHTML=(d.kpis||[]).map(k=>'<div class="kpi"><div class="label">'+k.label+'</div><div class="value">'+nf.format(k.value)+'</div>'+(k.meta?'<div class="meta">'+k.meta+'</div>':'')+'</div>').join('');
  lineChart('c_dau',d.dau.days,[lineDS('Active users',d.dau.data,RED,true)]);
  barChart('c_opens',d.opens.days,d.opens.data);
  lineChart('c_reg',d.reg.days,[lineDS('Accounts',d.reg.accounts,RED),lineDS('Free drinks',d.reg.free,AMBER),lineDS('Drinks redeemed',d.reg.drinks,TEAL)],legendTop);
  lineChart('c_sys',d.sys.days,[lineDS('Smiles sent',d.sys.smiles,RED),lineDS('SYS signups',d.sys.signups,BLUE)],legendTop);
  const stColors=[RED,BLUE,AMBER,TEAL,PURPLE];
  mk('c_smiletype',{type:'bar',data:{labels:d.smiles_by_type.days,datasets:(d.smiles_by_type.series||[]).map((s,i)=>({label:s.label,data:s.data,backgroundColor:stColors[i%stColors.length]}))},options:{responsive:true,maintainAspectRatio:false,plugins:legendTop,scales:{x:Object.assign(axis({grid:{display:false}}),{stacked:true}),y:Object.assign(axis({beginAtZero:true}),{stacked:true})}}});
  drawBreakdown('c_screens',d.top_screens,RED);
  drawBreakdown('c_venuesv',d.top_venues_v,RED);
  drawBreakdown('c_events',d.top_events_v,BLUE);
  drawBreakdown('c_venuesc',d.top_venues_c,AMBER);
  doughnut('c_alertint',d.alert_int);
  doughnut('c_perm',d.perm_denials);
  document.getElementById('f_shown').textContent=nf.format(d.funnel.shown);
  document.getElementById('f_viewed').textContent=nf.format(d.funnel.viewed);
  document.getElementById('f_conv').textContent=d.funnel.conv+'%';
  document.getElementById('gen').textContent=DATA.rangeLabels[key]||key;
}

// build the range picker
const sel=document.getElementById('rangeSel');
(DATA.order||Object.keys(DATA.ranges)).forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=DATA.rangeLabels[k]||k;sel.appendChild(o);});
let saved=null; try{saved=localStorage.getItem('barzo_range');}catch(e){}
const initial=(saved && DATA.ranges[saved])?saved:(DATA.default||sel.options[0].value);
sel.value=initial;
sel.addEventListener('change',()=>{try{localStorage.setItem('barzo_range',sel.value);}catch(e){}; render(sel.value);});

render(initial);
document.getElementById('updated').textContent='Updated '+new Date().toLocaleString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
if(DATA.creators && DATA.creators.length){
  document.getElementById('creatorsSection').style.display='';
  document.getElementById('creators').innerHTML=DATA.creators.map(function(c){
    const stat=function(n,l){return '<div class="cstat"><div class="n">'+esc(String(c[n]))+'</div><div class="l">'+l+'</div></div>';};
    const ini=(c.name||'?').trim().split(/\s+/).map(function(w){return w[0]||'';}).join('').slice(0,2).toUpperCase();
    const av=c.img?('<div class="cav"><img src="'+esc(c.img)+'" alt="" referrerpolicy="no-referrer" onerror="this.parentNode.textContent=\''+ini+'\'"></div>'):('<div class="cav">'+ini+'</div>');
    return '<div class="card s6"><div class="creator"><div class="ch">'+av+'<div><div class="cn">'+esc(c.name)+'</div><div class="cu">@'+esc(c.handle)+'</div></div></div>'
      +'<div class="cstats">'+stat('followers','Followers')+stat('following','Following')+stat('posts','Posts')+stat('likes','Likes')+'</div></div></div>';
  }).join('');
  if(DATA.creatorsUpdated){ const f=document.getElementById('gen'); }
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    data = parse()
    html = render(data)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote index.html ({len(html)} bytes), ranges: {', '.join(data['ranges'].keys())}")
