#!/usr/bin/env python3
"""
Institutional Momentum Squeeze Scanner
---------------------------------------
Mentor's framework:
  - Fundamentally strong stocks at historical support
  - EMA 20/50 compression (spread <= 1.5%) = coiled spring
  - Volume dry-up (< 75% of 20-day avg) = selling exhaustion
  - RSI between 40-55 = neutral zone, not overextended

Watchlist: LT, ACMESOLAR, CYIENTDLM, TECHNOE, SRF, COALINDIA, HINDCOPPER
Runs daily Mon-Fri after market close (4:00 PM IST via GitHub Actions).
Output: data/swing_scanner.json  +  swing-dashboard.html
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# ── Mentor's Core Watchlist ──────────────────────────────────────────────────
WATCHLIST = [
    {"ticker": "LT.NS",         "name": "Larsen & Toubro",       "sector": "Infra/Capital Goods"},
    {"ticker": "ACMESOLAR.NS",  "name": "Acme Solar Holdings",   "sector": "Renewable Energy"},
    {"ticker": "CYIENTDLM.NS",  "name": "Cyient DLM",            "sector": "Electronics/Defence"},
    {"ticker": "TECHNOE.NS",    "name": "Techno Electric",        "sector": "Power/EPC"},
    {"ticker": "SRF.NS",        "name": "SRF Limited",           "sector": "Chemicals/Films"},
    {"ticker": "COALINDIA.NS",  "name": "Coal India",            "sector": "Mining/PSU"},
    {"ticker": "HINDCOPPER.NS", "name": "Hindustan Copper",      "sector": "Metals/PSU"},
]

# ── Squeeze Thresholds (Mentor's Parameters) ────────────────────────────────
EMA_SPREAD_THRESHOLD = 1.5    # EMAs < 1.5% apart = compressed/coiled
VOLUME_DRYUP_RATIO   = 0.75   # Current vol < 75% of 20-day avg = exhaustion
RSI_ENTRY_LOW        = 40     # RSI floor for safe entry window
RSI_ENTRY_HIGH       = 55     # RSI ceiling before FOMO territory
RSI_OVERBOUGHT       = 70     # Overextended warning level

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent   # stock-literacy-platform/
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

SCANNER_JSON = DATA_DIR / "swing_scanner.json"
DASHBOARD_HTML = ROOT / "swing-dashboard.html"


def compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Standard Wilder RSI calculation."""
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def analyse_stock(item: dict) -> dict:
    """
    Download 60 days of daily data and evaluate mentor's squeeze conditions.
    Returns a result dict with all computed fields.
    """
    ticker = item["ticker"]
    result = {
        "ticker":      ticker,
        "name":        item["name"],
        "sector":      item["sector"],
        "status":      "error",
        "alert":       "⚠️ Data unavailable",
        "alertLevel":  "error",
        "currentPrice": None,
        "ema20":       None,
        "ema50":       None,
        "emaSpread":   None,
        "rsi":         None,
        "volume":      None,
        "avgVolume":   None,
        "volumeRatio": None,
        "isCompressed":    False,
        "isVolumeDryUp":   False,
        "isRsiInZone":     False,
    }

    try:
        df = yf.Ticker(ticker).history(period="90d")   # 90d for RSI warm-up
        if len(df) < 52:
            result["alert"] = "⏭️ Insufficient data (< 52 days)"
            result["alertLevel"] = "warning"
            return result

        # Rename for consistency
        df = df.rename(columns={"Close": "close", "Volume": "volume",
                                 "High": "high", "Low": "low"})

        # ── Indicators ──────────────────────────────────────────────────────
        df["ema20"]    = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]    = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"]  = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]

        current_price  = round(float(latest["close"]), 2)
        ema20_val      = round(float(latest["ema20"]), 2)
        ema50_val      = round(float(latest["ema50"]), 2)
        ema_spread     = round(abs(ema20_val - ema50_val) / ema50_val * 100, 3)
        volume_val     = int(latest["volume"])
        avg_volume_val = int(latest["avg_vol"])
        volume_ratio   = round(volume_val / avg_volume_val, 3) if avg_volume_val > 0 else 1.0
        rsi_val        = compute_rsi(df["close"])

        # ── Condition Flags ─────────────────────────────────────────────────
        is_compressed     = ema_spread <= EMA_SPREAD_THRESHOLD
        is_volume_dry_up  = volume_val < (avg_volume_val * VOLUME_DRYUP_RATIO)
        is_rsi_in_zone    = RSI_ENTRY_LOW <= rsi_val <= RSI_ENTRY_HIGH
        is_rsi_overextended = rsi_val > RSI_OVERBOUGHT

        # ── Signal Determination ────────────────────────────────────────────
        if is_rsi_overextended:
            alert      = f"🚫 RSI Overextended ({rsi_val}) — Entry window closed. Wait for pullback."
            alertLevel = "overextended"
        elif is_compressed and is_volume_dry_up and is_rsi_in_zone:
            alert      = f"🎯 CRITICAL ALERT: Mentor's Squeeze Active! Spread {ema_spread:.2f}% | RSI {rsi_val}"
            alertLevel = "critical"
        elif is_compressed and is_volume_dry_up:
            alert      = f"⚡ Squeeze Setup: EMAs pinched ({ema_spread:.2f}%) + Volume dry-up. Monitor RSI (now {rsi_val})."
            alertLevel = "setup"
        elif is_compressed:
            alert      = f"🔄 EMA Compression ({ema_spread:.2f}%) — Awaiting volume dry-up. RSI: {rsi_val}"
            alertLevel = "watch"
        else:
            alert      = f"⏳ Normal consolidation. Spread {ema_spread:.2f}% | RSI {rsi_val}"
            alertLevel = "normal"

        result.update({
            "status":       "ok",
            "alert":        alert,
            "alertLevel":   alertLevel,
            "currentPrice": current_price,
            "ema20":        ema20_val,
            "ema50":        ema50_val,
            "emaSpread":    ema_spread,
            "rsi":          rsi_val,
            "volume":       volume_val,
            "avgVolume":    avg_volume_val,
            "volumeRatio":  volume_ratio,
            "isCompressed":   is_compressed,
            "isVolumeDryUp":  is_volume_dry_up,
            "isRsiInZone":    is_rsi_in_zone,
        })

    except Exception as e:
        print(f"  ✗ Error scanning {ticker}: {e}")
        result["alert"] = f"⚠️ Fetch error: {e}"

    return result


def build_html(results: list, run_time_ist: str) -> str:
    """Generate the swing-dashboard.html from scan results."""

    def badge(condition: bool, yes_text: str, no_text: str,
              yes_class: str = "bg-green-100 text-green-800",
              no_class: str  = "bg-gray-100 text-gray-500") -> str:
        cls  = yes_class if condition else no_class
        text = yes_text  if condition else no_text
        return f'<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold {cls}">{text}</span>'

    alert_color = {
        "critical":    "border-l-4 border-green-500 bg-green-50",
        "setup":       "border-l-4 border-yellow-400 bg-yellow-50",
        "watch":       "border-l-4 border-blue-400 bg-blue-50",
        "overextended":"border-l-4 border-red-400 bg-red-50",
        "normal":      "border-l-4 border-gray-300 bg-white",
        "warning":     "border-l-4 border-orange-400 bg-orange-50",
        "error":       "border-l-4 border-red-300 bg-red-50",
    }
    alert_icon = {
        "critical":    "🎯",
        "setup":       "⚡",
        "watch":       "🔄",
        "overextended":"🚫",
        "normal":      "⏳",
        "warning":     "⏭️",
        "error":       "⚠️",
    }

    critical_count = sum(1 for r in results if r["alertLevel"] == "critical")
    setup_count    = sum(1 for r in results if r["alertLevel"] == "setup")
    watch_count    = sum(1 for r in results if r["alertLevel"] == "watch")
    normal_count   = sum(1 for r in results if r["alertLevel"] in ("normal", "overextended"))

    rows = ""
    for r in results:
        lvl   = r.get("alertLevel", "normal")
        card_cls = alert_color.get(lvl, alert_color["normal"])
        icon  = alert_icon.get(lvl, "⏳")

        price_str   = f"₹{r['currentPrice']:,.2f}" if r["currentPrice"] else "—"
        ema20_str   = f"₹{r['ema20']:,.2f}"        if r["ema20"]   else "—"
        ema50_str   = f"₹{r['ema50']:,.2f}"        if r["ema50"]   else "—"
        spread_str  = f"{r['emaSpread']:.2f}%"      if r["emaSpread"] is not None else "—"
        rsi_str     = str(r["rsi"])                  if r["rsi"] is not None else "—"
        vol_ratio_str = f"{r['volumeRatio']:.2f}x"  if r["volumeRatio"] is not None else "—"

        compressed_badge = badge(
            r["isCompressed"],
            "✅ Compressed", "❌ Not Yet",
            "bg-green-100 text-green-800", "bg-gray-100 text-gray-500"
        )
        volume_badge = badge(
            r["isVolumeDryUp"],
            "✅ Dry-Up", "❌ Normal",
            "bg-green-100 text-green-800", "bg-gray-100 text-gray-500"
        )
        rsi_badge = badge(
            r["isRsiInZone"],
            "✅ In Zone", "⚠️ Outside",
            "bg-green-100 text-green-800", "bg-orange-100 text-orange-700"
        )

        rows += f"""
        <div class="rounded-lg shadow-sm p-5 {card_cls} mb-4">
          <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">

            <!-- Left: Name + Alert -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xl">{icon}</span>
                <h3 class="text-base font-bold text-gray-900">{r['name']}</h3>
                <span class="text-xs text-gray-400 font-mono">{r['ticker'].replace('.NS','')}</span>
                <span class="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">{r['sector']}</span>
              </div>
              <p class="text-sm text-gray-700 font-medium">{r['alert']}</p>
            </div>

            <!-- Right: Price -->
            <div class="text-right">
              <p class="text-2xl font-bold text-gray-900">{price_str}</p>
              <p class="text-xs text-gray-400">Current Price</p>
            </div>
          </div>

          <!-- Indicators Grid -->
          <div class="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 text-sm">

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA 20</p>
              <p class="font-semibold text-gray-800">{ema20_str}</p>
            </div>

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA 50</p>
              <p class="font-semibold text-gray-800">{ema50_str}</p>
            </div>

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA Spread</p>
              <p class="font-semibold {'text-green-700' if r['isCompressed'] else 'text-gray-800'}">{spread_str}</p>
            </div>

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">RSI (14)</p>
              <p class="font-semibold {'text-green-700' if r['isRsiInZone'] else 'text-red-600' if r.get('rsi') and r['rsi'] > RSI_OVERBOUGHT else 'text-gray-800'}">{rsi_str}</p>
            </div>

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Vol Ratio</p>
              <p class="font-semibold {'text-green-700' if r['isVolumeDryUp'] else 'text-gray-800'}">{vol_ratio_str}</p>
            </div>

            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Conditions</p>
              <div class="space-y-0.5">
                {compressed_badge}
                {volume_badge}
                {rsi_badge}
              </div>
            </div>

          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Swing Squeeze Scanner — Mentor's Watchlist</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @media print {{ .no-print {{ display: none; }} }}
  </style>
</head>
<body class="bg-gray-50 min-h-screen">

  <!-- SEBI Banner -->
  <div class="bg-yellow-50 border-b border-yellow-300 py-2 px-4 text-xs text-yellow-800 text-center">
    <i class="fas fa-exclamation-triangle mr-1"></i>
    <strong>Educational use only.</strong> This scanner is for learning momentum frameworks. Not investment advice. All investments carry risk.
    <a href="disclaimer.html" class="underline ml-1">Full Disclaimer</a>
  </div>

  <!-- Nav -->
  <nav class="bg-white shadow sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="index.html" class="flex items-center gap-2 text-gray-800 font-bold text-lg">
        <i class="fas fa-chart-line text-blue-600"></i>
        Financial Literacy Hub
      </a>
      <div class="hidden md:flex items-center gap-6 text-sm">
        <a href="index.html" class="text-gray-600 hover:text-blue-600 transition">Home</a>
        <a href="dashboard.html" class="text-gray-600 hover:text-blue-600 transition">Dashboard</a>
        <a href="swing-dashboard.html" class="text-blue-600 font-semibold border-b-2 border-blue-600 pb-0.5">Swing Scanner</a>
        <a href="discussions.html" class="text-gray-600 hover:text-blue-600 transition">Discussions</a>
      </div>
    </div>
  </nav>

  <!-- Header -->
  <section class="bg-gradient-to-r from-slate-800 to-blue-900 text-white py-10">
    <div class="max-w-6xl mx-auto px-4">
      <h1 class="text-3xl font-bold mb-2">
        <i class="fas fa-compress-arrows-alt mr-2 text-yellow-400"></i>
        Institutional Squeeze Scanner
      </h1>
      <p class="text-blue-200 text-sm max-w-2xl">
        Mentor's framework: fundamentally strong stocks at historical support with EMA 20/50 compression
        + volume exhaustion + neutral RSI (40–55). No leverage, no stop-loss panic — positional conviction.
      </p>
      <div class="mt-4 flex flex-wrap gap-4 text-xs text-blue-300">
        <span><i class="fas fa-clock mr-1"></i>Last scan: <strong class="text-white">{run_time_ist}</strong></span>
        <span><i class="fas fa-eye mr-1"></i>Watching <strong class="text-white">{len(results)}</strong> stocks</span>
        <span class="text-green-400"><i class="fas fa-fire mr-1"></i>{critical_count} Critical Alert{"s" if critical_count != 1 else ""}</span>
        <span class="text-yellow-400"><i class="fas fa-bolt mr-1"></i>{setup_count} Setup{"s" if setup_count != 1 else ""}</span>
        <span class="text-blue-300"><i class="fas fa-eye mr-1"></i>{watch_count} Watch</span>
        <span class="text-gray-400"><i class="fas fa-minus mr-1"></i>{normal_count} Normal</span>
      </div>
    </div>
  </section>

  <!-- Legend -->
  <section class="max-w-6xl mx-auto px-4 py-4 no-print">
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-green-500 flex-shrink-0 mt-0.5"></span>
        <div><p class="font-bold text-gray-800">🎯 Critical Alert</p><p class="text-gray-500">EMA compressed + vol dry-up + RSI 40–55. All three mentor conditions met.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-yellow-400 flex-shrink-0 mt-0.5"></span>
        <div><p class="font-bold text-gray-800">⚡ Setup</p><p class="text-gray-500">EMAs pinched + vol dry-up. Monitor RSI for confirmation.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-blue-400 flex-shrink-0 mt-0.5"></span>
        <div><p class="font-bold text-gray-800">🔄 Watch</p><p class="text-gray-500">EMAs compressing. Awaiting volume dry-up to complete setup.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-red-400 flex-shrink-0 mt-0.5"></span>
        <div><p class="font-bold text-gray-800">🚫 Overextended</p><p class="text-gray-500">RSI &gt; 70. Entry window closed. Mentor says: wait for pullback.</p></div>
      </div>
    </div>
  </section>

  <!-- Indicator Guide -->
  <section class="max-w-6xl mx-auto px-4 pb-2 no-print">
    <details class="bg-white rounded-lg shadow-sm text-xs text-gray-600">
      <summary class="px-4 py-3 cursor-pointer font-semibold text-gray-700 hover:bg-gray-50 rounded-lg">
        <i class="fas fa-info-circle mr-1 text-blue-500"></i> Indicator Configuration Guide (click to expand)
      </summary>
      <div class="px-4 pb-4 pt-2 grid md:grid-cols-3 gap-4">
        <div>
          <p class="font-bold text-gray-800 mb-1">① VWAP</p>
          <p>If stock stays above VWAP on high volume in the morning session → institutions defending the floor → confirmed breakout.</p>
        </div>
        <div>
          <p class="font-bold text-gray-800 mb-1">② EMA 20 (Green) + EMA 50 (Red)</p>
          <p>When both EMAs flatten and pinch together below 1.5% spread = "Coiled Spring." Explosive multi-percent breakout is loading.</p>
        </div>
        <div>
          <p class="font-bold text-gray-800 mb-1">③ RSI (14-period)</p>
          <p>Safe entry zone: 40–55 (neutral, not overextended). Avoid entry when RSI &gt; 70–75. That window is closed for late retail buyers.</p>
        </div>
      </div>
    </details>
  </section>

  <!-- Stock Cards -->
  <main class="max-w-6xl mx-auto px-4 py-4 pb-12">
    {rows}
  </main>

  <!-- Mentor's Philosophy Note -->
  <section class="max-w-6xl mx-auto px-4 pb-10">
    <div class="bg-slate-800 text-white rounded-lg p-6 text-sm">
      <h3 class="font-bold text-yellow-400 mb-3"><i class="fas fa-graduation-cap mr-2"></i>Mentor's Institutional Framework</h3>
      <div class="grid md:grid-cols-2 gap-4 text-gray-300">
        <div>
          <p class="font-semibold text-white mb-1">Why no hard stop-loss?</p>
          <p>Trades are in cash equity only — no leverage, no F&O. The underlying businesses are fundamentally strong. A 5% global shock is temporary noise; the business value doesn't change overnight.</p>
        </div>
        <div>
          <p class="font-semibold text-white mb-1">The positional safety net</p>
          <p>If a swing trade hits volatility, it quietly converts to a short-term positional hold (1–3 weeks). Strong fundamentals + historical support floor naturally absorb the drawdown and rebound cleanly.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Footer -->
  <footer class="bg-gray-800 text-gray-400 text-center py-6 text-xs">
    <p>© 2026 Financial Literacy Platform — Built by volunteers on GitHub Pages</p>
    <p class="mt-1">Educational platform only. Not SEBI investment advice. <a href="disclaimer.html" class="underline">Disclaimer</a></p>
  </footer>

</body>
</html>"""
    return html


def main():
    ist = ZoneInfo("Asia/Kolkata")
    run_time_ist = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    print(f"🔍 Mentor's Squeeze Scanner starting — {run_time_ist}")
    print(f"   Watchlist: {len(WATCHLIST)} stocks")
    print(f"   Thresholds: EMA spread ≤ {EMA_SPREAD_THRESHOLD}% | Vol ratio < {VOLUME_DRYUP_RATIO} | RSI {RSI_ENTRY_LOW}–{RSI_ENTRY_HIGH}")
    print()

    results = []
    for item in WATCHLIST:
        print(f"  Scanning {item['ticker']} ({item['name']})…")
        result = analyse_stock(item)
        results.append(result)
        print(f"    → {result['alertLevel'].upper()} | {result['alert'][:70]}")
        time.sleep(1.5)   # avoid Yahoo rate-limiting in CI

    # ── Save JSON ────────────────────────────────────────────────────────────
    output = {
        "lastUpdated": datetime.utcnow().isoformat() + "Z",
        "runTimeIST":  run_time_ist,
        "thresholds": {
            "emaSpreadMax":    EMA_SPREAD_THRESHOLD,
            "volumeDryUpRatio": VOLUME_DRYUP_RATIO,
            "rsiEntryLow":     RSI_ENTRY_LOW,
            "rsiEntryHigh":    RSI_ENTRY_HIGH,
            "rsiOverbought":   RSI_OVERBOUGHT,
        },
        "results": results,
    }

    with open(SCANNER_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✅ Saved: {SCANNER_JSON}")

    # ── Save HTML ────────────────────────────────────────────────────────────
    html = build_html(results, run_time_ist)
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Saved: {DASHBOARD_HTML}")

    # ── Summary ──────────────────────────────────────────────────────────────
    critical = [r for r in results if r["alertLevel"] == "critical"]
    setup    = [r for r in results if r["alertLevel"] == "setup"]

    print("\n─── Scan Complete ───")
    if critical:
        print(f"🎯 {len(critical)} CRITICAL SQUEEZE(S) DETECTED:")
        for r in critical:
            print(f"   • {r['name']} ({r['ticker']}) — {r['alert']}")
    elif setup:
        print(f"⚡ {len(setup)} SETUP(S) forming — monitor RSI:")
        for r in setup:
            print(f"   • {r['name']} ({r['ticker']}) — {r['alert']}")
    else:
        print("⏳ All stocks in normal consolidation. No squeeze triggered today.")

    return 0


if __name__ == "__main__":
    main()
