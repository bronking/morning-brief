import os
import json
import urllib.request
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import datetime, timedelta, time as dtime
import pytz
import yfinance as yf
import pandas as pd

CET = pytz.timezone("Europe/Amsterdam")
ET  = pytz.timezone("America/New_York")
UTC = pytz.utc

# Ticker map: label -> (yf_ticker, name, group, tz, decimals)
CONTRACTS = {
    "FDAX":   ("FDAX=F",  "DAX futures",       "EU",    "CET", 0),
    "Bund":   ("FGBL=F",  "Euro bond futures",  "EU",    "CET", 2),
    "FTSE":   ("Z=F",     "FTSE 100 futures",   "EU",    "CET", 0),
    "ES":     ("ES=F",    "S&P 500 futures",    "US",    "ET",  2),
    "NQ":     ("NQ=F",    "Nasdaq futures",     "US",    "ET",  2),
    "YM":     ("YM=F",    "Dow futures",        "US",    "ET",  0),
    "EURUSD": ("EURUSD=X","EUR/USD",            "FX",    "ET",  4),
    "GBPUSD": ("GBPUSD=X","GBP/USD",            "FX",    "ET",  4),
    "USDJPY": ("JPY=X",   "USD/JPY",            "FX",    "ET",  2),
    "Gold":   ("GC=F",    "Gold",               "CMD",   "ET",  2),
    "Brent":  ("BZ=F",    "Brent Oil",          "CMD",   "ET",  2),
    "BTC":    ("BTC-USD", "Bitcoin",            "CRYPTO","ET",  0),
}

def get_session_data(ticker_sym, group, decimals):
    try:
        tk = yf.Ticker(ticker_sym)
        # Pull 5 days of 1-minute data
        df = tk.history(period="5d", interval="1m")
        if df.empty:
            return {}

        df.index = df.index.tz_convert(ET)

        now_et   = datetime.now(ET)
        now_cet  = datetime.now(CET)

        # Find last completed trading day
        # For EU futures: RTH = 09:00-17:30 CET
        # For US/FX/CMD:  RTH = 09:30-16:00 ET
        if group == "EU":
            tz      = CET
            df_tz   = df.copy()
            df_tz.index = df.index.tz_convert(CET)
            rth_open  = dtime(9, 0)
            rth_close = dtime(17, 30)
        else:
            tz      = ET
            df_tz   = df.copy()
            rth_open  = dtime(9, 30)
            rth_close = dtime(16, 0)

        # Get yesterday's date in the right tz
        today_local = now_cet.date() if group == "EU" else now_et.date()
        yest_local  = today_local - timedelta(days=1)
        # Skip weekends
        while yest_local.weekday() >= 5:
            yest_local -= timedelta(days=1)

        # RTH bars for yesterday
        rth_bars = df_tz[
            (df_tz.index.date == yest_local) &
            (df_tz.index.time >= rth_open) &
            (df_tz.index.time <= rth_close)
        ]

        # Overnight: from market close yesterday until 07:00 CET today
        # Convert 07:00 CET to ET for comparison
        seven_cet = CET.localize(datetime.combine(today_local, dtime(7, 0))).astimezone(ET)

        if group == "EU":
            on_start_cet = CET.localize(datetime.combine(yest_local, dtime(17, 30)))
            on_start_et  = on_start_cet.astimezone(ET)
        else:
            on_start_et  = ET.localize(datetime.combine(yest_local, dtime(16, 0)))

        on_bars = df[
            (df.index >= on_start_et) &
            (df.index <= seven_cet)
        ]

        # Current price
        current_bars = df.tail(1)
        current = float(current_bars["Close"].iloc[0]) if not current_bars.empty else None

        result = {"current": current}

        if not rth_bars.empty:
            result["rth_open"]  = round(float(rth_bars["Open"].iloc[0]),  decimals)
            result["rth_close"] = round(float(rth_bars["Close"].iloc[-1]), decimals)
            result["rth_high"]  = round(float(rth_bars["High"].max()),     decimals)
            result["rth_low"]   = round(float(rth_bars["Low"].min()),      decimals)
            result["rth_range"] = round(result["rth_high"] - result["rth_low"], decimals)

        if not on_bars.empty:
            result["on_high"]  = round(float(on_bars["High"].max()),  decimals)
            result["on_low"]   = round(float(on_bars["Low"].min()),   decimals)
            result["on_range"] = round(result["on_high"] - result["on_low"], decimals)

        return result

    except Exception as e:
        print(f"Error fetching {ticker_sym}: {e}")
        return {}

def fetch_all_market_data():
    data = {}
    for key, (ticker, name, group, tz, decimals) in CONTRACTS.items():
        print(f"  Fetching {key} ({ticker})...")
        d = get_session_data(ticker, group, decimals)
        data[key] = {"label": key, "name": name, "group": group, "decimals": decimals, "data": d}
    return data

def fmt(val, decimals=0):
    if val is None:
        return "—"
    if decimals == 0:
        return f"{int(round(val)):,}"
    return f"{val:,.{decimals}f}"

def chg_pct(current, close):
    if not current or not close or close == 0:
        return "", "#888"
    pct = ((current - close) / close) * 100
    sign = "+" if pct >= 0 else ""
    color = "#3B6D11" if pct >= 0 else "#A32D2D"
    return f"{sign}{pct:.2f}%", color

def contract_block_html(cfg):
    d   = cfg.get("data", {})
    dec = cfg.get("decimals", 2)
    current   = d.get("current")
    rth_close = d.get("rth_close")
    pct, color = chg_pct(current, rth_close)

    def v(key):
        return fmt(d.get(key), dec)

    rth_range_str = f"{fmt(d.get('rth_range'), dec)} pts" if d.get("rth_range") is not None else "—"
    on_range_str  = f"{fmt(d.get('on_range'),  dec)} pts" if d.get("on_range")  is not None else "—"

    return f"""
    <div style="border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 14px;background:#f7f7f5;border-bottom:0.5px solid #e8e8e8;">
        <div>
          <span style="font-size:13px;font-weight:500;color:#111">{cfg['label']}</span>
          <span style="font-size:11px;color:#999;margin-left:6px">{cfg['name']}</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px;">
          <span style="font-size:13px;font-weight:500;color:{color}">{pct}</span>
          <span style="font-size:14px;font-weight:500;color:#111">{fmt(current, dec)}</span>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;padding:10px 14px;gap:8px 16px;background:#fff;">
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH open</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_open')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH close</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_close')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH range</div><div style="font-size:12px;font-weight:500;color:#111">{rth_range_str}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">RTH high / low</div><div style="font-size:12px;font-weight:500;color:#111">{v('rth_high')}</div><div style="font-size:11px;color:#999">/ {v('rth_low')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">Overnight H / L</div><div style="font-size:12px;font-weight:500;color:#111">{v('on_high')}</div><div style="font-size:11px;color:#999">/ {v('on_low')}</div></div>
        <div><div style="font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.04em">Overnight range</div><div style="font-size:12px;font-weight:500;color:#111">{on_range_str}</div></div>
      </div>
    </div>"""

def generate_brief():
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
    "us10y":   {{"yield": "X.XX%", "change": "+/-Xbp", "note": "brief note"}},
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

    eu_blocks     = "".join([contract_block_html(market_data[k]) for k in ["FDAX","Bund","FTSE"]     if k in market_data])
    us_blocks     = "".join([contract_block_html(market_data[k]) for k in ["ES","NQ","YM"]           if k in market_data])
    fx_blocks     = "".join([contract_block_html(market_data[k]) for k in ["EURUSD","GBPUSD","USDJPY"] if k in market_data])
    other_blocks  = "".join([contract_block_html(market_data[k]) for k in ["Gold","Brent","BTC"]     if k in market_data])

    yields  = brief.get("yields", {})
    us10y   = yields.get("us10y", {})
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
          <td style="padding:10px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;text-align:right;width:68px">
            <span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:4px;background:{risk_bg.get(imp,'#eee')};color:{badge_txt.get(imp,'#333')};border:0.5px solid {risk_colors.get(imp,'#ccc')}">{imp}</span>
          </td>
        </tr>"""

    week_html = ""
    for w in brief.get("weekAhead", []):
        imp = w.get("impact","MEDIUM")
        week_html += f"""
        <tr>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;white-space:nowrap;width:85px">
            <div style="font-size:13px;font-weight:500;color:#111">{w.get('day','')}</div>
            <div style="font-size:11px;color:#aaa">{w.get('date','')}</div>
          </td>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top">
            <div style="font-size:13px;font-weight:500;color:#111;margin-bottom:2px">{w.get('event','')}</div>
            <div style="font-size:12px;color:#777">{w.get('note','')}</div>
          </td>
          <td style="padding:9px 6px;border-bottom:0.5px solid #f0f0f0;vertical-align:top;text-align:right;width:68px">
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
      <tr>
        <th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;padding:4px 6px;text-align:left;width:160px">Instrument</th>
        <th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;padding:4px 6px;text-align:right;width:70px">Yield</th>
        <th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;padding:4px 6px;text-align:right;width:70px">Chg</th>
        <th style="font-size:11px;font-weight:500;color:#aaa;text-transform:uppercase;padding:4px 6px;text-align:left">Note</th>
      </tr>
      <tr>
        <td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-weight:500;font-size:13px;color:#111">US 10Y Treasury</td>
        <td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:13px;text-align:right;color:#111">{us10y.get('yield','—')}</td>
        <td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:13px;text-align:right;color:#A32D2D">{us10y.get('change','—')}</td>
        <td style="padding:8px 6px;border-bottom:0.5px solid #f0f0f0;font-size:12px;color:#888">{us10y.get('note','')}</td>
      </tr>
      <tr>
        <td style="padding:8px 6px;font-weight:500;font-size:13px;color:#111">German 10Y Bund</td>
        <td style="padding:8px 6px;font-size:13px;text-align:right;color:#111">{bund10y.get('yield','—')}</td>
        <td style="padding:8px 6px;font-size:13px;text-align:right;color:#A32D2D">{bund10y.get('change','—')}</td>
        <td style="padding:8px 6px;font-size:12px;color:#888">{bund10y.get('note','')}</td>
      </tr>
    </table>
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">FX &mdash; RTH 09:30&ndash;16:00 ET &middot; overnight 16:00 ET&rarr;07:00 CET</div>
    {fx_blocks}
  </div>

  <div style="padding:14px 24px;border-bottom:1px solid #f0f0f0">
    <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:12px">Commodities &amp; Crypto</div>
    {other_blocks}
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
    print("Fetching market data from Yahoo Finance...")
    market_data = fetch_all_market_data()
    print("Generating brief from Perplexity...")
    brief = generate_brief()
    print(f"Risk: {brief.get('overallRisk')} | Events: {len(brief.get('events', []))}")
    html = format_html(brief, market_data)
    send_email(html, brief["date_str"])
    print("Done.")
