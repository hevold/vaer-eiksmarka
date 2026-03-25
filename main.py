#!/usr/bin/env python3
"""
Eiksmarka Værvarsel

Henter daglig værvarsling time for time fra MET Norway Locationforecast API
og sender til e-post kl. 07:00 hver morgen.

Miljøvariabler:
- GMAIL_USER: Gmail-adresse for avsender
- GMAIL_APP_PASSWORD: App-spesifikt passord fra Google (16 tegn)
- EMAIL_RECIPIENTS: Kommaseparert liste med mottaker-adresser
"""

import os
import sys
import smtplib
import requests
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

load_dotenv()

# Eiksmarka, Oslo
LAT = 59.9333
LON = 10.5833
ALTITUDE = 150  # meter over havet

# MET Locationforecast API
MET_API_URL = (
    f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
    f"?lat={LAT}&lon={LON}&altitude={ALTITUDE}"
)
USER_AGENT = "EiksmarkaVaervarsel/1.0 hevold@gmail.com"

# Miljøvariabler
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_RECIPIENTS = [r.strip() for r in os.getenv("EMAIL_RECIPIENTS", "").split(",") if r.strip()]
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Norske værbeskrivelser
WEATHER_SYMBOLS = {
    "clearsky": "Klarvær",
    "fair": "Lettskyet",
    "partlycloudy": "Delvis skyet",
    "cloudy": "Skyet",
    "fog": "Tåke",
    "lightrain": "Lett regn",
    "rain": "Regn",
    "heavyrain": "Kraftig regn",
    "lightrainshowers": "Lette regnbyger",
    "rainshowers": "Regnbyger",
    "heavyrainshowers": "Kraftige regnbyger",
    "lightsleet": "Lett sludd",
    "sleet": "Sludd",
    "heavysleet": "Kraftig sludd",
    "lightsnow": "Lett snø",
    "snow": "Snø",
    "heavysnow": "Kraftig snø",
    "lightsnowshowers": "Lette snøbyger",
    "snowshowers": "Snøbyger",
    "heavysnowshowers": "Kraftige snøbyger",
    "thunder": "Torden",
    "lightrainandthunder": "Lett regn og torden",
    "rainandthunder": "Regn og torden",
    "heavyrainandthunder": "Kraftig regn og torden",
    "lightsnowandthunder": "Lett snø og torden",
    "snowandthunder": "Snø og torden",
}

NORWEGIAN_DAYS = {
    "Monday": "Mandag", "Tuesday": "Tirsdag", "Wednesday": "Onsdag",
    "Thursday": "Torsdag", "Friday": "Fredag", "Saturday": "Lørdag", "Sunday": "Søndag",
}
NORWEGIAN_MONTHS = {
    "January": "januar", "February": "februar", "March": "mars",
    "April": "april", "May": "mai", "June": "juni",
    "July": "juli", "August": "august", "September": "september",
    "October": "oktober", "November": "november", "December": "desember",
}


def get_weather_description(symbol_code):
    """Oversett MET symbol_code til norsk tekst"""
    if not symbol_code:
        return "–"
    base = symbol_code.split("_")[0]
    return WEATHER_SYMBOLS.get(base, symbol_code)


def wind_direction_text(degrees):
    """Konverter grader til norsk retningsbeskrivelse"""
    if degrees is None:
        return ""
    dirs = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]
    return dirs[round(degrees / 45) % 8]


def fetch_weather():
    """Hent værdata fra MET Norway Locationforecast API"""
    response = requests.get(
        MET_API_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_todays_hourly(data):
    """
    Ekstraher timesdata for dagens dato (norsk tid, UTC+1/+2).
    GitHub Actions kjører i UTC – vi bruker UTC+1 som konservativt valg.
    """
    oslo_offset = timedelta(hours=1)
    now_utc = datetime.now(timezone.utc)
    today_oslo = (now_utc + oslo_offset).date()

    hourly = []
    for entry in data["properties"]["timeseries"]:
        time_utc = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
        time_oslo = time_utc + oslo_offset

        if time_oslo.date() != today_oslo:
            continue

        instant = entry["data"]["instant"]["details"]
        next_1h = entry["data"].get("next_1_hours", {})

        hourly.append({
            "time": time_oslo.strftime("%H:%M"),
            "temp": instant.get("air_temperature"),
            "wind_speed": instant.get("wind_speed"),
            "wind_dir": instant.get("wind_from_direction"),
            "humidity": instant.get("relative_humidity"),
            "symbol": next_1h.get("summary", {}).get("symbol_code", ""),
            "precipitation": next_1h.get("details", {}).get("precipitation_amount", 0),
        })

    return hourly


def format_date_norwegian(dt):
    """Formater dato på norsk"""
    day = NORWEGIAN_DAYS.get(dt.strftime("%A"), dt.strftime("%A"))
    month = NORWEGIAN_MONTHS.get(dt.strftime("%B"), dt.strftime("%B"))
    return f"{day} {dt.day}. {month} {dt.year}"


def format_email_html(today_str, hourly):
    """Lag HTML-email med timesvis værtabell"""
    rows = ""
    for h in hourly:
        desc = get_weather_description(h["symbol"])
        wind = (
            f"{h['wind_speed']:.0f} m/s {wind_direction_text(h['wind_dir'])}"
            if h["wind_speed"] is not None else "–"
        )
        temp_str = f"{h['temp']:.0f}°C" if h["temp"] is not None else "–"
        temp_color = (
            "#e74c3c" if h["temp"] and h["temp"] > 20
            else "#3498db" if h["temp"] and h["temp"] < 0
            else "#2c3e50"
        )
        precip_str = f"{h['precipitation']:.1f} mm" if h["precipitation"] else "–"

        rows += f"""
        <tr>
          <td style="padding:9px 14px;border-bottom:1px solid #eee;font-weight:bold;color:#555;">{h['time']}</td>
          <td style="padding:9px 14px;border-bottom:1px solid #eee;font-weight:bold;color:{temp_color};">{temp_str}</td>
          <td style="padding:9px 14px;border-bottom:1px solid #eee;color:#444;">{desc}</td>
          <td style="padding:9px 14px;border-bottom:1px solid #eee;color:#2980b9;">{precip_str}</td>
          <td style="padding:9px 14px;border-bottom:1px solid #eee;color:#555;">{wind}</td>
        </tr>"""

    return f"""<html>
  <body style="font-family:Arial,sans-serif;background:#f0f4f8;padding:20px;margin:0;">
    <div style="max-width:580px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.1);">
      <div style="background:linear-gradient(135deg,#1a6fa3,#56b4e9);padding:28px 30px;color:white;">
        <h1 style="margin:0;font-size:22px;font-weight:700;">Daglig værvarsling</h1>
        <p style="margin:6px 0 0;font-size:16px;opacity:0.9;">Eiksmarka, Oslo</p>
        <p style="margin:4px 0 0;font-size:14px;opacity:0.75;">{today_str}</p>
      </div>
      <div style="padding:10px 0;">
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f7f9fc;">
              <th style="padding:10px 14px;text-align:left;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Kl.</th>
              <th style="padding:10px 14px;text-align:left;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Temp</th>
              <th style="padding:10px 14px;text-align:left;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Vær</th>
              <th style="padding:10px 14px;text-align:left;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Nedbør</th>
              <th style="padding:10px 14px;text-align:left;color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;">Vind</th>
            </tr>
          </thead>
          <tbody>{rows}
          </tbody>
        </table>
      </div>
      <div style="padding:14px 20px;background:#f7f9fc;text-align:center;color:#aaa;font-size:11px;">
        Kilde: MET Norway Locationforecast 2.0 &nbsp;·&nbsp; {LAT}°N, {LON}°Ø, {ALTITUDE} moh.
      </div>
    </div>
  </body>
</html>"""


def format_email_plain(today_str, hourly):
    """Plain text fallback"""
    lines = [f"Værvarsling Eiksmarka – {today_str}", "=" * 55, ""]
    lines.append(f"{'Kl.':<6} {'Temp':>6}  {'Vær':<24} {'Nedbør':>8}  Vind")
    lines.append("-" * 55)
    for h in hourly:
        desc = get_weather_description(h["symbol"])
        temp = f"{h['temp']:.0f}°C" if h["temp"] is not None else "–"
        precip = f"{h['precipitation']:.1f}mm" if h["precipitation"] else "–"
        wind = (
            f"{h['wind_speed']:.0f}m/s {wind_direction_text(h['wind_dir'])}"
            if h["wind_speed"] is not None else "–"
        )
        lines.append(f"{h['time']:<6} {temp:>6}  {desc:<24} {precip:>8}  {wind}")
    lines += ["", "Kilde: MET Norway Locationforecast 2.0"]
    return "\n".join(lines)


def send_slack(today_str, hourly):
    """Send værvarsling til Slack via Incoming Webhook"""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL ikke satt – hopper over Slack")
        return

    lines = [f"*Værvarsling Eiksmarka – {today_str}*", "```"]
    lines.append(f"{'Kl.':<6} {'Temp':>6}  {'Vær':<22} {'Nedbør':>8}  Vind")
    lines.append("-" * 53)
    for h in hourly:
        desc = get_weather_description(h["symbol"])
        temp = f"{h['temp']:.0f}°C" if h["temp"] is not None else "–"
        precip = f"{h['precipitation']:.1f}mm" if h["precipitation"] else "–"
        wind = (
            f"{h['wind_speed']:.0f}m/s {wind_direction_text(h['wind_dir'])}"
            if h["wind_speed"] is not None else "–"
        )
        lines.append(f"{h['time']:<6} {temp:>6}  {desc:<22} {precip:>8}  {wind}")
    lines.append("```")

    payload = {"text": "\n".join(lines)}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    response.raise_for_status()
    print("Slack-melding sendt")


def send_email(subject, plain_body, html_body):
    """Send e-post via Gmail SMTP"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(EMAIL_RECIPIENTS)
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    print(f"E-post sendt til: {', '.join(EMAIL_RECIPIENTS)}")


def main():
    print("=" * 60)
    print(f"Eiksmarka Værvarsel – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Valider miljøvariabler
    missing = [n for v, n in [(GMAIL_USER, "GMAIL_USER"), (GMAIL_APP_PASSWORD, "GMAIL_APP_PASSWORD")] if not v]
    if missing:
        print(f"FEIL: Mangler miljøvariabler: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    if not EMAIL_RECIPIENTS:
        print("FEIL: EMAIL_RECIPIENTS er ikke satt", file=sys.stderr)
        sys.exit(1)

    # Hent værdata
    print("Henter data fra MET Norway Locationforecast...")
    data = fetch_weather()

    hourly = get_todays_hourly(data)
    print(f"Hentet {len(hourly)} timespunkter for i dag")

    if not hourly:
        print("Ingen timesdata for i dag – avslutter.", file=sys.stderr)
        sys.exit(1)

    # Lag og send e-post
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    today_str = format_date_norwegian(now)
    subject = f"Vær Eiksmarka – {now.strftime('%-d. %b')}"

    send_email(
        subject=subject,
        plain_body=format_email_plain(today_str, hourly),
        html_body=format_email_html(today_str, hourly),
    )
    send_slack(today_str, hourly)

    print("=" * 60)
    print("Ferdig!")
    print("=" * 60)


if __name__ == "__main__":
    main()
