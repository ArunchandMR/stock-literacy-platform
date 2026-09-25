#!/usr/bin/env python3
"""
Institutional Momentum Squeeze Scanner — Dynamic NSE Universe
--------------------------------------------------------------
Mentor's framework (criteria-driven, NOT hardcoded):
  The 7 mentor stocks are the SEED watchlist.
  Every run the scanner ALSO screens the full NSE Nifty 500 universe
  and adds any stock that currently meets the mentor's squeeze criteria.

Squeeze criteria:
  1. EMA 20/50 spread  ≤ 1.5%  (coiled spring)
  2. Today's volume    < 75% of 20-day avg (selling exhaustion)
  3. RSI (14)          40 – 55 (neutral zone, entry window open)
  → All three = 🎯 CRITICAL
  → #1 + #2 only = ⚡ SETUP (RSI outside zone)
  → #1 only       = 🔄 WATCH
  → RSI > 70       = 🚫 OVEREXTENDED

NSE ticker source:
  A. niftyindices.com Nifty 500 CSV (public, no auth)
  B. Hardcoded backup of 80 liquid NSE stocks

API: ONE batch yf.download() per chunk — single Yahoo session, no per-ticker delays.
Output: data/swing_scanner.json  +  swing-dashboard.html (always regenerated)
"""

import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent.parent
DATA_DIR       = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SCANNER_JSON   = DATA_DIR / "swing_scanner.json"
DASHBOARD_HTML = ROOT / "swing-dashboard.html"

# ── Thresholds (mentor's parameters) ─────────────────────────────────────────
EMA_SPREAD_MAX    = 1.5    # % — EMAs must be pinched tighter than this
VOLUME_DRYUP_MAX  = 0.75   # ratio — today's vol < 75% of 20-day avg
RSI_LOW           = 40     # RSI floor for safe entry
RSI_HIGH          = 55     # RSI ceiling before FOMO
RSI_OVERBOUGHT    = 70     # overextended warning

# ── Mentor's seed watchlist (always included, used as anchor) ─────────────────
SEED_WATCHLIST = [
    {"ticker": "LT.NS",         "name": "Larsen & Toubro",    "sector": "Infra/Capital Goods"},
    {"ticker": "ACMESOLAR.NS",  "name": "Acme Solar",         "sector": "Renewable Energy"},
    {"ticker": "CYIENTDLM.NS",  "name": "Cyient DLM",         "sector": "Electronics/Defence"},
    {"ticker": "TECHNOE.NS",    "name": "Techno Electric",     "sector": "Power/EPC"},
    {"ticker": "SRF.NS",        "name": "SRF Limited",        "sector": "Chemicals/Films"},
    {"ticker": "COALINDIA.NS",  "name": "Coal India",         "sector": "Mining/PSU"},
    {"ticker": "HINDCOPPER.NS", "name": "Hindustan Copper",   "sector": "Metals/PSU"},
]
SEED_TICKERS = {s["ticker"] for s in SEED_WATCHLIST}
SEED_META    = {s["ticker"]: s for s in SEED_WATCHLIST}

# ── Backup NSE tickers (used when live CSV fetch fails) ───────────────────────
BACKUP_TICKERS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "BHARTIARTL.NS","KOTAKBANK.NS","HINDUNILVR.NS","AXISBANK.NS","BAJFINANCE.NS",
    "WIPRO.NS","ULTRACEMCO.NS","MARUTI.NS","TITAN.NS","SUNPHARMA.NS",
    "NTPC.NS","COALINDIA.NS","LT.NS","SRF.NS","HINDCOPPER.NS",
    "TECHM.NS","ASIANPAINT.NS","TATAMOTORS.NS","BAJAJ-AUTO.NS","BEL.NS",
    "ADANIENT.NS","ONGC.NS","POWERGRID.NS","ITC.NS","SBIN.NS",
    "ACMESOLAR.NS","CYIENTDLM.NS","TECHNOE.NS","APARINDS.NS","IRFC.NS",
    "RVNL.NS","HUDCO.NS","SJVN.NS","NHPC.NS","TATAPOWER.NS",
    "TORNTPOWER.NS","CESC.NS","JSL.NS","TIINDIA.NS","FINEORG.NS",
    "ALKYLAMINE.NS","CLEAN.NS","HARIOMPIPE.NS","KOPRAN.NS","ADANIPOWER.NS",
    "NESTLEIND.NS","BRITANNIA.NS","DABUR.NS","MARICO.NS","COLPAL.NS",
    "DIVISLAB.NS","DRREDDY.NS","CIPLA.NS","LUPIN.NS","AUROPHARMA.NS",
    "TATACONSUM.NS","GODREJCP.NS","PIDILITIND.NS","BERGEPAINT.NS","KANSAINER.NS",
    "HAVELLS.NS","VOLTAS.NS","BLUESTARCO.NS","ABB.NS","SIEMENS.NS",
    "CUMMINSIND.NS","BHEL.NS","TITAGARH.NS","RAILVIKAS.NS","GRSE.NS",
    "ZOMATO.NS","NYKAA.NS","PAYTM.NS","POLICYBZR.NS","DELHIVERY.NS",
    "HCLTECH.NS","MPHASIS.NS","LTIM.NS","PERSISTENT.NS","COFORGE.NS",
]


# ── Step 1: Fetch live NSE tickers ────────────────────────────────────────────
def get_nse_tickers() -> list[str]:
    if not _HAS_REQUESTS:
        print("  ℹ requests not available, using backup list")
        return BACKUP_TICKERS

    urls = [
        "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.nseindia.com/",
    }
    for url in urls:
        try:
            r = _req.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                df = pd.read_csv(StringIO(r.text))
                sym_col = next((c for c in df.columns if "symbol" in c.lower()), None)
                if sym_col:
                    tickers = [f"{s.strip()}.NS" for s in df[sym_col].dropna() if str(s).strip()]
                    if len(tickers) > 100:
                        print(f"  ✅ Live NSE: {len(tickers)} tickers loaded")
                        return tickers
        except Exception as e:
            print(f"  ⚠ NSE fetch failed ({url}): {e}")

    print(f"  ℹ Using backup list ({len(BACKUP_TICKERS)} tickers)")
    return BACKUP_TICKERS


# ── Step 2: RSI ───────────────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta    = series.diff().dropna()
    avg_gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    rsi      = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


# ── Step 3: Batch download — handles both 1-ticker and multi-ticker output ────
def batch_download(tickers: list[str], period: str = "90d") -> dict[str, pd.DataFrame]:
    """
    Single yf.download() call. Returns {ticker: df(close, volume)}.
    Handles yfinance column naming quirks robustly.
    """
    if not tickers:
        return {}

    print(f"  📡 Downloading {len(tickers)} tickers ({period})…", end=" ", flush=True)
    out: dict[str, pd.DataFrame] = {}

    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            period=period,
            auto_adjust=False,
            progress=False,
            threads=True,
            multi_level_index=False,
        )
        if raw.empty:
            print("empty!")
            return out

        print(f"got {len(raw)} rows, cols: {list(raw.columns)[:8]}")

        for ticker in tickers:
            try:
                # yfinance with multi_level_index=False uses different naming
                # depending on whether 1 or >1 ticker was requested:
                #   >1 tickers → "Close_LT.NS", "Volume_LT.NS"
                #   1 ticker   → "Close", "Volume"
                c_col = f"Close_{ticker}"
                v_col = f"Volume_{ticker}"

                if c_col not in raw.columns:
                    # single-ticker response or fallback
                    c_col = "Close"
                    v_col = "Volume"

                if c_col not in raw.columns:
                    continue

                df = pd.DataFrame({
                    "close":  raw[c_col],
                    "volume": raw.get(v_col, pd.Series(0.0, index=raw.index)),
                }).dropna(subset=["close"])

                if len(df) >= 55:   # need 50 for EMA-50 + RSI warmup
                    out[ticker] = df

            except Exception:
                pass

    except Exception as e:
        print(f"\n  ✗ Batch failed: {e}")

    return out


# ── Step 4: Analyse single stock ─────────────────────────────────────────────
def analyse(ticker: str, df: pd.DataFrame, meta: dict) -> dict:
    result = {
        "ticker":       ticker,
        "name":         meta.get("name", ticker.replace(".NS", "")),
        "sector":       meta.get("sector", "NSE"),
        "isSeed":       ticker in SEED_TICKERS,
        "status":       "error",
        "alert":        "⚠️ Insufficient data",
        "alertLevel":   "error",
        "currentPrice": None,
        "ema20":        None,
        "ema50":        None,
        "emaSpread":    None,
        "rsi":          None,
        "volume":       None,
        "avgVolume":    None,
        "volumeRatio":  None,
        "isCompressed":  False,
        "isVolumeDryUp": False,
        "isRsiInZone":   False,
    }

    try:
        df = df.copy()
        df["ema20"]   = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]   = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]

        price      = round(float(latest["close"]), 2)
        ema20      = round(float(latest["ema20"]), 2)
        ema50      = round(float(latest["ema50"]), 2)
        spread     = round(abs(ema20 - ema50) / ema50 * 100, 3)
        vol        = int(latest["volume"])
        avg_vol    = int(latest["avg_vol"]) if latest["avg_vol"] > 0 else 1
        vol_ratio  = round(vol / avg_vol, 3)
        rsi        = compute_rsi(df["close"])

        compressed   = spread <= EMA_SPREAD_MAX
        vol_dry_up   = vol < avg_vol * VOLUME_DRYUP_MAX
        rsi_in_zone  = RSI_LOW <= rsi <= RSI_HIGH
        rsi_over     = rsi > RSI_OVERBOUGHT

        if rsi_over:
            alert, level = f"🚫 RSI Overextended ({rsi}) — wait for pullback.", "overextended"
        elif compressed and vol_dry_up and rsi_in_zone:
            alert, level = f"🎯 CRITICAL: All 3 conditions met! Spread {spread:.2f}% | RSI {rsi}", "critical"
        elif compressed and vol_dry_up:
            alert, level = f"⚡ Setup: EMA compressed ({spread:.2f}%) + vol dry-up. RSI {rsi} outside zone.", "setup"
        elif compressed:
            alert, level = f"🔄 Watch: EMA spread {spread:.2f}% (compressed). Awaiting vol dry-up.", "watch"
        else:
            alert, level = f"⏳ Normal consolidation. Spread {spread:.2f}% | RSI {rsi}", "normal"

        result.update({
            "status":       "ok",
            "alert":        alert,
            "alertLevel":   level,
            "currentPrice": price,
            "ema20":        ema20,
            "ema50":        ema50,
            "emaSpread":    spread,
            "rsi":          rsi,
            "volume":       vol,
            "avgVolume":    avg_vol,
            "volumeRatio":  vol_ratio,
            "isCompressed":  compressed,
            "isVolumeDryUp": vol_dry_up,
            "isRsiInZone":   rsi_in_zone,
        })

    except Exception as e:
        result["alert"] = f"⚠️ Error: {e}"

    return result


# ── Step 5: Build HTML ────────────────────────────────────────────────────────
def build_html(results: list[dict], run_time: str) -> str:

    LEVEL_BORDER = {
        "critical":    "border-l-4 border-green-500 bg-green-50",
        "setup":       "border-l-4 border-yellow-400 bg-yellow-50",
        "watch":       "border-l-4 border-blue-400 bg-blue-50",
        "overextended":"border-l-4 border-red-400 bg-red-50",
        "normal":      "border-l-4 border-gray-200 bg-white",
        "error":       "border-l-4 border-gray-200 bg-gray-50",
    }
    LEVEL_ICON = {
        "critical":"🎯","setup":"⚡","watch":"🔄",
        "overextended":"🚫","normal":"⏳","error":"⚠️",
    }

    def badge(ok, yes, no, yc="bg-green-100 text-green-800", nc="bg-gray-100 text-gray-400"):
        return f'<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold {yc if ok else nc}">{yes if ok else no}</span>'

    n_critical = sum(1 for r in results if r["alertLevel"] == "critical")
    n_setup    = sum(1 for r in results if r["alertLevel"] == "setup")
    n_watch    = sum(1 for r in results if r["alertLevel"] == "watch")
    n_seed     = sum(1 for r in results if r.get("isSeed"))
    n_universe = len(results) - n_seed

    cards = ""
    for r in results:
        lvl   = r.get("alertLevel", "normal")
        icon  = LEVEL_ICON.get(lvl, "⏳")
        cls   = LEVEL_BORDER.get(lvl, LEVEL_BORDER["normal"])
        p     = lambda v, d="—": f"₹{v:,.2f}" if v is not None else d
        sp    = f"{r['emaSpread']:.2f}%" if r["emaSpread"] is not None else "—"
        rsi_s = str(r["rsi"]) if r["rsi"] is not None else "—"
        vr_s  = f"{r['volumeRatio']:.2f}×" if r["volumeRatio"] is not None else "—"
        seed_pill = '<span class="ml-1 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Mentor watchlist</span>' if r.get("isSeed") else '<span class="ml-1 text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">Universe find</span>'

        cards += f"""
        <div class="rounded-lg shadow-sm p-5 {cls} mb-4">
          <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
            <div class="flex-1">
              <div class="flex flex-wrap items-center gap-2 mb-1">
                <span class="text-xl">{icon}</span>
                <h3 class="text-base font-bold text-gray-900">{r['name']}</h3>
                <span class="text-xs text-gray-400 font-mono">{r['ticker'].replace('.NS','')}</span>
                <span class="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">{r['sector']}</span>
                {seed_pill}
              </div>
              <p class="text-sm text-gray-700 font-medium">{r['alert']}</p>
            </div>
            <div class="text-right flex-shrink-0">
              <p class="text-2xl font-bold text-gray-900">{p(r['currentPrice'])}</p>
              <p class="text-xs text-gray-400">Current Price</p>
            </div>
          </div>
          <div class="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 text-sm">
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA 20</p>
              <p class="font-semibold">{p(r['ema20'])}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA 50</p>
              <p class="font-semibold">{p(r['ema50'])}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA Spread</p>
              <p class="font-semibold {'text-green-700' if r['isCompressed'] else 'text-gray-700'}">{sp}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">RSI (14)</p>
              <p class="font-semibold {'text-green-700' if r['isRsiInZone'] else 'text-red-600' if r['rsi'] and r['rsi'] > RSI_OVERBOUGHT else 'text-gray-700'}">{rsi_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Vol Ratio</p>
              <p class="font-semibold {'text-green-700' if r['isVolumeDryUp'] else 'text-gray-700'}">{vr_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center text-xs space-y-1">
              <p class="text-gray-400 mb-1">Conditions</p>
              {badge(r['isCompressed'],  '✅ Compressed',  '❌ Spread wide')}
              {badge(r['isVolumeDryUp'], '✅ Vol dry-up',  '❌ Normal vol')}
              {badge(r['isRsiInZone'],   '✅ RSI 40-55',   '⚠️ RSI outside', 'bg-green-100 text-green-800', 'bg-orange-100 text-orange-700')}
            </div>
          </div>
        </div>"""

    if not results:
        cards = """<div class="bg-white rounded-lg shadow-sm p-12 text-center">
          <div class="text-5xl mb-4">⏳</div>
          <h3 class="text-xl font-bold text-gray-700 mb-2">No data yet</h3>
          <p class="text-gray-400 text-sm">Run the workflow manually: Actions → Daily Swing Squeeze Scanner → Run workflow</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Swing Squeeze Scanner — Mentor's Framework</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">

  <div class="bg-yellow-50 border-b border-yellow-300 py-2 px-4 text-xs text-yellow-800 text-center">
    <i class="fas fa-exclamation-triangle mr-1"></i><strong>Educational use only.</strong>
    Not investment advice. <a href="disclaimer.html" class="underline ml-1">Full Disclaimer</a>
  </div>

  <nav class="bg-white shadow sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="index.html" class="flex items-center gap-2 text-gray-800 font-bold text-lg">
        <i class="fas fa-chart-line text-blue-600"></i> Financial Literacy Hub
      </a>
      <div class="hidden md:flex items-center gap-6 text-sm">
        <a href="index.html"           class="text-gray-600 hover:text-blue-600">Home</a>
        <a href="dashboard.html"       class="text-gray-600 hover:text-blue-600">Dashboard</a>
        <a href="swing-dashboard.html" class="text-blue-600 font-semibold border-b-2 border-blue-600 pb-0.5">Swing Scanner</a>
        <a href="box-dashboard.html"   class="text-gray-600 hover:text-blue-600">Box Scanner</a>
        <a href="discussions.html"     class="text-gray-600 hover:text-blue-600">Discussions</a>
      </div>
    </div>
  </nav>

  <section class="bg-gradient-to-r from-slate-800 to-blue-900 text-white py-10">
    <div class="max-w-6xl mx-auto px-4">
      <h1 class="text-3xl font-bold mb-2">
        <i class="fas fa-compress-arrows-alt mr-2 text-yellow-400"></i>
        Institutional Squeeze Scanner
      </h1>
      <p class="text-blue-200 text-sm max-w-2xl mb-4">
        Scans the <strong class="text-white">full NSE universe</strong> every trading day. Finds stocks where
        EMA 20/50 are compressed (≤ 1.5%), volume is drying up, and RSI is in the 40–55 neutral zone.
        Mentor's 7 seed stocks are always included for tracking.
      </p>
      <div class="flex flex-wrap gap-5 text-xs text-blue-300">
        <span><i class="fas fa-clock mr-1"></i>Scan: <strong class="text-white">{run_time}</strong></span>
        <span><i class="fas fa-database mr-1"></i>Universe: <strong class="text-white">{len(results)}</strong> stocks analysed</span>
        <span class="text-green-400"><i class="fas fa-fire mr-1"></i>{n_critical} Critical</span>
        <span class="text-yellow-400"><i class="fas fa-bolt mr-1"></i>{n_setup} Setup</span>
        <span class="text-blue-300"><i class="fas fa-eye mr-1"></i>{n_watch} Watch</span>
        <span class="text-blue-200"><i class="fas fa-seedling mr-1"></i>{n_seed} seed stocks | {n_universe} universe finds</span>
      </div>
    </div>
  </section>

  <section class="max-w-6xl mx-auto px-4 py-4">
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-green-500 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🎯 Critical</p><p class="text-gray-500">EMA compressed + vol dry-up + RSI 40–55 — all 3 conditions met.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-yellow-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">⚡ Setup</p><p class="text-gray-500">EMAs pinched + vol dry-up. Monitor RSI for zone entry.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-blue-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🔄 Watch</p><p class="text-gray-500">EMAs compressing. Awaiting volume exhaustion.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-red-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🚫 Overextended</p><p class="text-gray-500">RSI &gt; 70. Entry window closed — wait for pullback.</p></div>
      </div>
    </div>
  </section>

  <main class="max-w-6xl mx-auto px-4 py-2 pb-12">
    {cards}
  </main>

  <section class="max-w-6xl mx-auto px-4 pb-10">
    <div class="bg-slate-800 text-white rounded-lg p-6 text-sm">
      <h3 class="font-bold text-yellow-400 mb-3"><i class="fas fa-graduation-cap mr-2"></i>Mentor's Framework</h3>
      <div class="grid md:grid-cols-2 gap-4 text-gray-300">
        <div><p class="font-semibold text-white mb-1">Why no hard stop-loss?</p>
        <p>Cash equity only — no leverage, no F&O. Fundamentally strong businesses. A 5% global shock is temporary noise; the business value doesn't change overnight.</p></div>
        <div><p class="font-semibold text-white mb-1">The positional safety net</p>
        <p>If a swing trade hits volatility, it converts to a short-term positional hold (1–3 weeks). Strong fundamentals + historical support absorb the drawdown naturally.</p></div>
      </div>
    </div>
  </section>

  <footer class="bg-gray-800 text-gray-400 text-center py-6 text-xs">
    <p>© 2026 Financial Literacy Platform — Educational only, not SEBI advice.</p>
  </footer>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ist      = ZoneInfo("Asia/Kolkata")
    run_time = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    print(f"🔍 Squeeze Scanner — {run_time}")
    print(f"   EMA spread ≤{EMA_SPREAD_MAX}% | Vol ratio <{VOLUME_DRYUP_MAX} | RSI {RSI_LOW}–{RSI_HIGH}")
    print()

    # ── 1. Build full ticker universe (seed + live NSE) ───────────────────────
    live_tickers = get_nse_tickers()
    all_tickers  = list({*live_tickers, *SEED_TICKERS})   # deduplicated
    print(f"  Total universe: {len(all_tickers)} tickers\n")

    # ── 2. Batch download in chunks of 80 ────────────────────────────────────
    CHUNK = 80
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(all_tickers), CHUNK):
        chunk = all_tickers[i:i + CHUNK]
        chunk_data = batch_download(chunk, period="90d")
        all_data.update(chunk_data)

    print(f"\n  Downloaded: {len(all_data)} tickers with sufficient history\n")

    # ── 3. Analyse every downloaded ticker ───────────────────────────────────
    results: list[dict] = []
    for ticker, df in all_data.items():
        meta = SEED_META.get(ticker, {"ticker": ticker, "name": ticker.replace(".NS",""), "sector": "NSE"})
        r    = analyse(ticker, df, meta)
        results.append(r)

    # ── 4. Sort: critical first, then setup, watch; within each by RSI ────────
    ORDER = {"critical":0,"setup":1,"watch":2,"overextended":3,"normal":4,"error":5}
    results.sort(key=lambda r: (ORDER.get(r["alertLevel"],5), -(r["rsi"] or 0)))

    # ── 5. Summary ────────────────────────────────────────────────────────────
    counts = {}
    for r in results:
        counts[r["alertLevel"]] = counts.get(r["alertLevel"], 0) + 1
    print("── Scan Summary ──")
    for lvl, n in sorted(counts.items(), key=lambda x: ORDER.get(x[0],9)):
        print(f"  {lvl:15s}: {n}")

    # ── 6. Save JSON ──────────────────────────────────────────────────────────
    out = {
        "lastUpdated":  datetime.utcnow().isoformat() + "Z",
        "runTimeIST":   run_time,
        "totalScanned": len(results),
        "summary":      counts,
        "thresholds":   {"emaSpreadMax": EMA_SPREAD_MAX, "volumeDryUpRatio": VOLUME_DRYUP_MAX,
                         "rsiLow": RSI_LOW, "rsiHigh": RSI_HIGH, "rsiOverbought": RSI_OVERBOUGHT},
        "results":      results,
    }
    with open(SCANNER_JSON, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n✅ {SCANNER_JSON}")

    # ── 7. Save HTML (always regenerated — replaces placeholder) ─────────────
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(results, run_time))
    print(f"✅ {DASHBOARD_HTML}")

    return 0


if __name__ == "__main__":
    main()
