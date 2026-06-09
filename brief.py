import os
import json
import urllib.request
import urllib.error
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import datetime, timedelta
import pytz

CET = pytz.timezone("Europe/Amsterdam")
ET = pytz.timezone("America/New_York")
UTC = pytz.utc

def polygon_aggs(ticker, from_date, to_date, multiplier=1, timespan="minute"):
    key = os.environ["POLYGON_API_KEY"]
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}?adjusted=true&sort=asc&limit=50000&apiKey={key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("results", [])
    except Exception as e:
        print(f"Polygon error for {ticker}: {e}")
        return []

def get_session_data(ticker, rth_open_et, rth_close_et, overnight_start_et, overnight_end_et, date_str_from, date_str_to):
    bars = polygon_aggs(ticker, date_str_from, date_str_to)
    if not bars:
        return None

    rth_bars = []
    overnight_bars = []

    for b in bars:
        ts = datetime.fromtimestamp(b["t"] / 1000, tz=UTC).astimezone(ET)
        t = ts.time()
        if rth_open_et <= t <= rth_close_et:
            rth_bars.append(b)
        if overnight_start_et <= t or t <= overnight_end_et:
            overnight_bars.append(b)

    result = {"current": bars[-1]["c"] if bars else None}

    if rth_bars:
        result["rth_open"]  = rth_bars[0]["o"]
        result["rth_close"] = rth_bars[-1]["c"]
        result["rth_high"]  = max(b["h"] for b in rth_bars)
        result["rth_low"]   = min(b["l"] for b in rth_bars)
        result["rth_range"] = round(result["rth_high"] - result["rth_low"], 4)

    if overnight_bars:
        result["on_high"]  = max(b["h"] for b in overnight_bars)
        result["on_low"]   = min(b["l"] for b in overnight_bars)
        result["on_range"] = round(result["on_high"] - result["on_low"], 4)

    return result

def fetch_market_data():
    now_cet = datetime.now(CET)
    now_et  = datetime.now(ET)

    today_str     = now_cet.strftime("%Y-%m-%d")
    yesterday_str = (now_cet - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_str  = (now_cet - timedelta(days=2)).strftime("%Y-%m-%d")

    from time import strptime
    from datetime import time as dtime

    # RTH windows
    eu_rth_open  = dtime(9, 0)
    eu_rth_close = dtime(17, 30)
    us_rth_open  = dtime(9, 30)
    us_rth_close = dtime(16, 0)

    # Overnight: market close → 07:00 CET (02:00 ET)
    eu_on_start  = dtime(17, 30)
    eu_on_end    = dtime(2, 0)   # ET equivalent of 07:00 CET (approx)
    us_on_start  = dtime(16, 0)
    us_on_end    = dtime(2, 0)

    contracts = {
        "FDAX":  {"ticker": "C:FDAX",    "rth": (eu_rth_open, eu_rth_close), "on": (eu_on_start, eu_on_end), "label": "FDAX", "name": "DAX futures",     "tz": "EU"},
        "Bund":  {"ticker": "C:FGBL",    "rth": (eu_rth_open, eu_rth_close), "on": (eu_on_start, eu_on_end), "label": "Bund", "name": "Euro bond futures","tz": "EU"},
        "FTSE":  {"ticker": "C:Z",       "rth": (eu_rth_open, eu_rth_close), "on": (eu_on_start, eu_on_end), "label": "FTSE Z","name": "FTSE 100 futures","tz": "EU"},
        "ES":    {"ticker": "C:ES",      "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "ES",   "name": "S&P 500 futures", "tz": "US"},
        "NQ":    {"ticker": "C:NQ",      "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "NQ",   "name": "Nasdaq futures",  "tz": "US"},
        "YM":    {"ticker": "C:YM",      "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "YM",   "name": "Dow futures",     "tz": "US"},
        "EURUSD":{"ticker": "C:EURUSD",  "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "EUR/USD","name": "FX",            "tz": "FX"},
        "GBPUSD":{"ticker": "C:GBPUSD",  "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "GBP/USD","name": "FX",            "tz": "FX"},
        "USDJPY":{"ticker": "C:USDJPY",  "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "USD/JPY","name": "FX",            "tz": "FX"},
        "XAUUSD":{"ticker": "C:XAUUSD",  "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "Gold",  "name": "Commodity",      "tz": "FX"},
        "BRENT": {"ticker": "X:BRENT",   "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "Brent", "name": "Commodity",      "tz": "FX"},
        "BTCUSD":{"ticker": "X:BTCUSD",  "rth": (us_rth_open, us_rth_close), "on": (us_on_start, us_on_end), "label": "BTC/USD","name": "Crypto",        "tz": "FX"},
    }

    results = {}
    for key, cfg in contracts.items():
        data = get_session_data(
            cfg["ticker"],
            cfg["rth"][0], cfg["rth"][1],
            cfg["on"][0],  cfg["on"][1],
            two_days_str, today_str
        )
        results[key] = {**cfg, "data": data or {}}

    return results

def fmt(val, decimals=0):
    if val is None:
        return "—"
    if decimals == 0:
        return f"{int(round(val)):,}"
    return f"{val:,.{decimals}f}"

def chg_pct(current, close):
    if not current or not close:
        return "", ""
    pct = ((current - close) / close) * 100
    sign = "+" if pct >= 0 else ""
    color = "#3B6D11" if pct >= 0 else "#A32D2D"
    return f"{sign}{pct:.2f}%", color

def contract_block_html(cfg, decimals=0):
    d = cfg.get("data", {})
    current = d.get("current")
    rth_close = d.get("rth_close")
    pct, color = chg_pct(current, rth_close)

    def v(key):
        return fmt(d.get(key), decimals)

    return f"""
    <div style="border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 14px;background:#f7f7f5;border-bottom:0.5px solid #e8e8e8;">
        <div>
          <span style="font-size:13px;font-weight:500;color:#111">{cfg['label']}</span>
          <span style="font-size:11px;color:#999;margin-left:6px">{cfg['name']}</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;">
          <span style="font-size:13px;font-weight:500;color:{color}">{pct}</span>
          <span style="font-size:14px;font-weight:500;color:#111">{fmt(current, decimals)}</span>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;padding:10px 14px;gap:8px 16px;background:#fff;">
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH open</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_open')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH close</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_close')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH range</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_range', 0 if decimals==0 else decimals)} pts</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH high / low</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_high')}</div><div style="font-size:11px;color:#999">/ {v('rth_low')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">Overnight H / L</div><div style="font-size:12px;font-weight:500;color:#111">{v('on_high')}</div><div style="font-size:11px;color:#999">/ {v('on_low')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">Overnight range</div><div style="font-size:12px;font-weight:500;color:#111">{v('on_range', 0 if decimals==0 else decimals)} pts</div></div>
      </div>
    </div>"""

def generate_brief(market_data):
    cet = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(cet)
    date_str = today.strftime("%A, %d %B %Y")
    date_iso = today.strftime("%Y-%m-%d")

    prompt = f"""You are a concise pre-market intelligence analyst for an intraday EU index trader (trades FDAX, FTSE, ES/NQ/YM, Bund). Today is {date_iso} and EU markets open in ~2 hours.

Search the web for today's economic calendar, ECB/Fed announcements, macro data releases, and overnight market-moving news.

Return ONLY valid JSON, no markdown, no explanation. Schema:
{{
  "summary": "2-3 sentence overall risk tone for today EU session. Be direct, trader-focused.",
  "overallRisk": "HIGH" or "MEDIUM" or "LOW",
  "riskFactors": [{{"label": "string max 3 words", "level": "HIGH or MEDIUM or LOW"}}],
  "yields": {{
    "us10y": {{"yield": "X.XX%", "change": "+/-Xbp", "note": "brief note"}},
    "bund10y": {{"yield": "X.XX%", "change": "+/-Xbp", "note": "brief note"}}
  }},
  "events": [
    {{
      "time": "HH:MM CET",
      "title": "Event name",
      "description": "One concise sentence: what it is + why it matters for EU indexes today",
      "impact": "HIGH or MEDIUM or LOW",
      "type": "ECB or FED or DATA or EARNINGS or AUCTION or POLITICAL or OTHER"
    }}
  ],
  "weekAhead": [
    {{
      "day": "Day name",
      "date": "DD Mon",
      "event": "Event name",
      "impact": "HIGH or MEDIUM or LOW",
      "note": "One sentence why it matters"
    }}
  ]
}}

Events: 3-7 items max, today only. WeekAhead: 3-5 most important remaining events this week."""

    api_key = os.environ["PERPLEXITY_API_KEY"]
    url = "https://api.perplexity.ai/chat/completions"
    payload = json.dumps({
        "model": "sonar",
        "messages": [
            {"role": "system", "content": "You are a pre-market analyst. Always respond with valid JSON only, no markdown, no explanation."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"]
    clean = text.replace("```json", "").replace("```", "").strip()
    brief = json.loads(clean)
    brief["date_str"] = date_str
    return brief

def format_html(brief, market_data):
    risk_colors = {"HIGH": "#E24B4A", "MEDIUM": "#EF9F27", "LOW": "#639922"}
    risk_bg     = {"HIGH": "#FCEBEB", "MEDIUM": "#FAEEDA", "LOW": "#EAF3DE"}
    badge_txt   = {"HIGH": "#791F1F", "MEDIUM": "#633806", "LOW": "#3B6D11"}
    overall = brief.get("overallRisk", "MEDIUM")

    risk_pills = "".join([
        f'<span style="display:inline-block;margin:3px 4px;padding:4px 12px;border-radius:99px;font-size:12px;font-weight:500;background:{risk_bg.get(rf["level"],"#eee")};color:{badge_txt.get(rf["level"],"#333")};border:1px solid {risk_colors.get(rf["level"],"#ccc")}">{rf["label"]}</span>'
        for rf in brief.get("riskFactors", [])
    ])

    eu_blocks = "".join([contract_block_html(market_data[k], decimals=0) for k in ["FDAX","Bund","FTSE"] if k in market_data])
    us_blocks = "".join([contract_block_html(market_data[k], decimals=2) for k in ["ES","NQ","YM"] if k in market_data])
    fx_blocks = "".join([contract_block_html(market_data[k], decimals=4) for k in ["EURUSD","GBPUSD","USDJPY"] if k in market_data])
    cmdcrypto_blocks = "".join([contract_block_html(market_data[k], decimals=2) for k in ["XAUUSD","BRENT","BTCUSD"] if k in market_data])

    yields = brief.get("yields", {})
    us10y  = yields.get("us10y",  {})
    bund10y = yields.get("bund10y", {})

    events_html = ""
    for ev in brief.get("events", []):
        imp = ev.get("impact","LOW")
        events_html += f"""
        <tr>
          <td style="padding:10px 6px;border-bottom:0.5px solid #f0f0f0;color:#888;font-size:12px;white-space:nowrap;vertical-align:top">{ev['time']}</td>
          <td style="padding:10px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top">
            <div style="font-size:13px;font-weight:500;color:#111;margin-bottom:2px">{ev['title']}</div>
            <div style="font-size:12px;color:#666;line-height:1.5">{ev['description']}</div>
          </td>
          <td style="padding:10px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;text-align:right">
            <span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:4px;background:{risk_bg.get(imp,'#eee')};color:{badge_txt.get(imp,'#333')};border:0.5px solid {risk_colors.get(imp,'#ccc')}">{imp}</span>
          </td>
        </tr>"""

    week_html = ""
    for w in brief.get("weekAhead", []):
        imp = w.get("impact","MEDIUM")
        week_html += f"""
        <tr>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;white-space:nowrap">
            <div style="font-size:13px;font-weight:500;color:#111">{w.get('day','')}</div>
            <div style="font-size:11px;color:#aaa">{w.get('date','')}</div>
          </td>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top">
            <div style="font-size:13px;font-weight:500;color:#111;margin-bottom:2px">{w.get('event','')}</div>
            <div style="font-size:12px;color:#777">{w.get('note','')}</div>
          </td>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;text-align:right">
            <span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:4px;background:{risk_bg.get(imp,'#eee')};color:{badge_txt.get(imp,'#333')};border:0.5px solid {risk_colors.get(imp,'#ccc')}">{imp}</span>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:660px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e8e8e8">

  <div style="padding:18px 24px;border-bottom:3px solid {risk_colors.get(overall,'#ccc')}">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#aaa;margin-bottom:4px">EU Index Trader</div>
    <div style="font-size:22px;font-weight:500;color:#111">Morning Brief</div>
    <div style="font-size:13px;color:#888;margin-top:3px">{brief['date_str']} &middot; Session risk: <strong style="color:{risk_colors.get(overall)}">{overall}</strong></div>
  </div>

  <div style="padding:14px 24px;background:#fafafa;border-bottom:1px solid #f0f0f0">
    <div style="font-size:14px;color:#333;line-height:1.6">{brief.get('summary','')}</div>
    <div style="margin-top:10px">{risk_pills}</div>
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">EU futures &mdash; RTH 09:00&ndash;17:30 CET</div>
    {eu_blocks}
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">US futures &mdash; RTH 09:30&ndash;16:00 ET</div>
    {us_blocks}
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:10px">Fixed income yields</div>
    <table style="width:100%;border-collapse:collapse">
      <tr><th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;letter-spacing:0.05em;padding:4px 6px;text-align:left;width:160px">Instrument</th><th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;letter-spacing:0.05em;padding:4px 6px;text-align:right;width:70px">Yield</th><th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;letter-spacing:0.05em;padding:4px 6px;text-align:right;width:70px">Chg</th><th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;letter-spacing:0.05em;padding:4px 6px;text-align:left">Note</th></tr>
      <tr><td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-weight:500;font-size:13px;color:#111">US 10Y Treasury</td><td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:13px;text-align:right;color:#111">{us10y.get('yield','—')}</td><td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:13px;text-align:right;color:#A32D2D">{us10y.get('change','—')}</td><td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:12px;color:#888">{us10y.get('note','')}</td></tr>
      <tr><td style="padding:8px 6px;font-weight:500;font-size:13px;color:#111">German 10Y Bund</td><td style="padding:8px 6px;font-size:13px;text-align:right;color:#111">{bund10y.get('yield','—')}</td><td style="padding:8px 6px;font-size:13px;text-align:right;color:#A32D2D">{bund10y.get('change','—')}</td><td style="padding:8px 6px;font-size:12px;color:#888">{bund10y.get('note','')}</td></tr>
    </table>
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">FX &mdash; RTH 09:30&ndash;16:00 ET &middot; overnight 16:00 ET&rarr;07:00 CET</div>
    {fx_blocks}
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">Commodities &amp; Crypto</div>
    {cmdcrypto_blocks}
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:10px">Key events today</div>
    <table style="width:100%;border-collapse:collapse">{events_html}</table>
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:10px">Week ahead</div>
    <table style="width:100%;border-collapse:collapse">{week_html}</table>
  </div>

  <div style="padding:12px 24px;background:#fafafa;font-size:11px;color:#bbb;text-align:center">
    Generated at 07:00 CET &middot; EU Morning Brief &middot; jiaweifu2020@gmail.com
  </div>

</div>
</body>
</html>"""

def send_email(html, date_str):
    sg = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    message = Mail(
        from_email=os.environ.get("SENDER_EMAIL"),
        to_emails="jiaweifu2020@gmail.com",
        subject=f"Morning Brief — {date_str}",
        html_content=html
    )
    resp = sg.send(message)
    print(f"Email sent: {resp.status_code}")

if __name__ == "__main__":
    print("Fetching market data from Polygon...")
    market_data = fetch_market_data()
    print("Generating brief from Perplexity...")
    brief = generate_brief(market_data)
    print(f"Risk: {brief.get('overallRisk')} | Events: {len(brief.get('events', []))}")
    html = format_html(brief, market_data)
    send_email(html, brief["date_str"])
    print("Done.")
