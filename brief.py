import os
import json
import urllib.request
import urllib.error
import sendgrid
from sendgrid.helpers.mail import Mail
from datetime import datetime
import pytz

def generate_brief():
    cet = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(cet)
    date_str = today.strftime("%A, %d %B %Y")
    date_iso = today.strftime("%Y-%m-%d")

    prompt = f"""You are a concise pre-market intelligence analyst for an intraday EU index trader (trades DAX, CAC40, AEX, FTSE, ES/NQ). It is {date_iso} and EU markets open in ~2 hours.

Based on your knowledge of the economic calendar and typical market patterns for this date, provide a morning brief.

Return ONLY valid JSON, no markdown, no explanation. Schema:
{{
  "summary": "2-3 sentence overall risk tone for today EU session. Be direct, trader-focused.",
  "overallRisk": "HIGH" or "MEDIUM" or "LOW",
  "riskFactors": [{{"label": "string max 3 words", "level": "HIGH or MEDIUM or LOW"}}],
  "events": [
    {{
      "time": "HH:MM CET",
      "title": "Event name",
      "description": "One concise sentence: what it is + why it matters for EU indexes today",
      "impact": "HIGH or MEDIUM or LOW",
      "type": "ECB or FED or DATA or EARNINGS or AUCTION or POLITICAL or OTHER"
    }}
  ],
  "indexWatch": [
    {{
      "index": "DAX or CAC40 or FTSE100 or AEX or ES",
      "note": "One sharp observation: key level, overnight move, or session bias to watch"
    }}
  ]
}}

Focus ONLY on events with real potential to move EU indexes today. Include: ECB/Fed speakers, CPI/PPI/PMI/GDP/NFP releases, major earnings if market-moving, geopolitical or macro tail risks. Omit noise. Events list: 3-7 items max."""

    api_key = os.environ["GROQ_API_KEY"]
    url = "https://api.groq.com/openai/v1/chat/completions"

    payload = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
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

def format_html(brief):
    risk_colors = {"HIGH": "#E24B4A", "MEDIUM": "#EF9F27", "LOW": "#639922"}
    risk_bg    = {"HIGH": "#FCEBEB", "MEDIUM": "#FAEEDA", "LOW": "#EAF3DE"}
    badge_txt  = {"HIGH": "#791F1F", "MEDIUM": "#633806", "LOW": "#3B6D11"}

    overall = brief.get("overallRisk", "MEDIUM")

    risk_pills = ""
    for rf in brief.get("riskFactors", []):
        lvl = rf["level"]
        risk_pills += (
            f'<span style="display:inline-block;margin:3px 4px;padding:4px 12px;'
            f'border-radius:99px;font-size:12px;font-weight:500;'
            f'background:{risk_bg.get(lvl,"#eee")};color:{badge_txt.get(lvl,"#333")};'
            f'border:1px solid {risk_colors.get(lvl,"#ccc")}">{rf["label"]}</span>'
        )

    events_html = ""
    for ev in brief.get("events", []):
        imp = ev.get("impact", "LOW")
        events_html += f"""
        <tr>
          <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;color:#666;font-size:13px;white-space:nowrap;vertical-align:top">{ev['time']}</td>
          <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top">
            <div style="font-size:14px;font-weight:500;color:#111;margin-bottom:3px">{ev['title']}</div>
            <div style="font-size:13px;color:#555;line-height:1.5">{ev['description']}</div>
          </td>
          <td style="padding:12px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top;text-align:right">
            <span style="font-size:11px;font-weight:500;padding:3px 8px;border-radius:4px;background:{risk_bg.get(imp,"#eee")};color:{badge_txt.get(imp,"#333")};border:1px solid {risk_colors.get(imp,"#ccc")}">{imp}</span>
          </td>
        </tr>"""

    watch_html = ""
    for w in brief.get("indexWatch", []):
        watch_html += f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #f0f0f0;font-weight:500;font-size:13px;color:#111;white-space:nowrap;vertical-align:top">{w['index']}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #f0f0f0;font-size:13px;color:#444;line-height:1.5">{w['note']}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <div style="max-width:600px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e8e8e8">
    <div style="padding:20px 24px;border-bottom:3px solid {risk_colors.get(overall,'#ccc')}">
      <div style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#999;margin-bottom:4px">EU Index Trader</div>
      <div style="font-size:22px;font-weight:500;color:#111">Morning Brief</div>
      <div style="font-size:13px;color:#777;margin-top:2px">{brief['date_str']} &middot; Session risk: <strong style="color:{risk_colors.get(overall)}">{overall}</strong></div>
    </div>
    <div style="padding:16px 24px;background:#fafafa;border-bottom:1px solid #f0f0f0">
      <div style="font-size:14px;color:#333;line-height:1.6">{brief.get('summary','')}</div>
      <div style="margin-top:10px">{risk_pills}</div>
    </div>
    <div style="padding:16px 24px">
      <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:10px">Key events today</div>
      <table style="width:100%;border-collapse:collapse">{events_html}</table>
    </div>
    <div style="padding:16px 24px;border-top:1px solid #f0f0f0">
      <div style="font-size:11px;font-weight:500;letter-spacing:0.07em;text-transform:uppercase;color:#aaa;margin-bottom:10px">Index watch</div>
      <table style="width:100%;border-collapse:collapse">{watch_html}</table>
    </div>
    <div style="padding:14px 24px;background:#fafafa;border-top:1px solid #f0f0f0;font-size:11px;color:#bbb;text-align:center">
      Generated at 07:00 CET &middot; EU Morning Brief
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
    print("Generating brief...")
    brief = generate_brief()
    print(f"Risk: {brief.get('overallRisk')} | Events: {len(brief.get('events', []))}")
    html = format_html(brief)
    send_email(html, brief["date_str"])
    print("Done.")
