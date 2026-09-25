#!/usr/bin/env python3
"""
Range Breakout Box Scanner — NSE Universe
------------------------------------------
Strategy (from YouTube Range Breakout / Box Theory):

  1. Trend filter    : Close > EMA-200  (only bull-market structures)
  2. Box detection   : 60-day lookback window; box height >= 20%
  3. Breakout trigger: Today's close > box_high  AND  volume > 1.2× avg volume
  4. Targets         : 50% of box height (partial) + 100% of box height (full)
  5. Stop-loss       : MAX(box_low,  entry – 1.5×ATR)
  6. Quality gate    : Risk:Reward >= 1.5

NSE ticker source (priority order):
  A. Nifty 500 CSV from nseindia.com (public file, no auth)
  B. Hardcoded backup of 50 liquid large/mid-caps

Output:
  data/box_scanner.json   ← consumed by box-dashboard.html (GitHub Pages)
  box-dashboard.html      ← auto-generated full dashboard page

API strategy: ONE batch yf.download() for all tickers, then per-ticker parse.
No per-ticker loop delays.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ── Config ────────────────────────────────────────────────────────────────────
BOX_LOOKBACK_DAYS   = 60        # days for box high/low window
BOX_MIN_HEIGHT_PCT  = 20.0      # box must span ≥ 20%
VOLUME_SURGE_RATIO  = 1.20      # breakout volume > 1.2× avg
MIN_RR_RATIO        = 1.5       # minimum risk:reward
ATR_SL_MULTIPLIER   = 1.5       # stop = entry − 1.5×ATR (floored at box_low)
TOP_N               = 5         # return best N candidates

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent.parent
DATA_DIR       = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_JSON    = DATA_DIR / "box_scanner.json"
OUTPUT_HTML    = ROOT / "box-dashboard.html"

# ── Backup tickers (fired when NSE CSV is unreachable) ────────────────────────
BACKUP_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "KOTAKBANK.NS", "HINDUNILVR.NS", "AXISBANK.NS", "BAJFINANCE.NS",
    "WIPRO.NS", "ULTRACEMCO.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS",
    "NTPC.NS", "COALINDIA.NS", "LT.NS", "SRF.NS", "HINDCOPPER.NS",
    "TECHM.NS", "ASIANPAINT.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS", "BEL.NS",
    "ADANIENT.NS", "ONGC.NS", "POWERGRID.NS", "ITC.NS", "SBIN.NS",
    "ACMESOLAR.NS", "CYIENTDLM.NS", "TECHNOE.NS", "APARINDS.NS", "KOPRAN.NS",
    "HARIOMPIPE.NS", "TIINDIA.NS", "ALKYLAMINE.NS", "FINEORG.NS", "CLEAN.NS",
    "IRFC.NS", "RVNL.NS", "HUDCO.NS", "SJVN.NS", "NHPC.NS",
    "CESC.NS", "TORNTPOWER.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "JSL.NS",
]


# ── Step 1: Get NSE tickers ───────────────────────────────────────────────────
def get_nse_tickers() -> list[str]:
    """
    Try to download Nifty 500 constituents from NSE's public CSV.
    Falls back to BACKUP_TICKERS if blocked/offline.
    """
    urls = [
        # NSE official Nifty 500 index CSV
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
        # Mirror via niftyindices.com
        "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    ]

    if _REQUESTS_OK:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer":    "https://www.nseindia.com/",
        }
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    from io import StringIO
                    df = pd.read_csv(StringIO(resp.text))
                    col = next((c for c in df.columns if "symbol" in c.lower()), None)
                    if col:
                        tickers = [f"{s.strip()}.NS" for s in df[col].dropna() if str(s).strip()]
                        if len(tickers) > 50:
                            print(f"  ✅ Loaded {len(tickers)} NSE tickers from live source")
                            return tickers
            except Exception as e:
                print(f"  ⚠ NSE URL failed ({e})")

    print(f"  ℹ Using backup list of {len(BACKUP_TICKERS)} tickers")
    return BACKUP_TICKERS


# ── Step 2: Indicators ────────────────────────────────────────────────────────
def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, pc = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


# ── Step 3: Batch download ────────────────────────────────────────────────────
def batch_download(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    ONE yf.download() call for all tickers.
    Returns {ticker: OHLCV DataFrame} for tickers with sufficient data.

    Column naming rules (yfinance multi_level_index=False):
      Multiple tickers → "Close_RELIANCE.NS", "High_RELIANCE.NS", …
      Single ticker    → "Close", "High", …
    We handle both cases robustly.
    """
    if not tickers:
        return {}

    print(f"  📡 Batch downloading {len(tickers)} tickers ({period})…", end=" ", flush=True)
    result: dict[str, pd.DataFrame] = {}

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
            return result

        print(f"got {len(raw)} rows | cols sample: {list(raw.columns)[:6]}")

        for ticker in tickers:
            try:
                # Try prefixed columns first (multi-ticker batch)
                c = f"Close_{ticker}"
                h = f"High_{ticker}"
                lo = f"Low_{ticker}"
                v = f"Volume_{ticker}"

                # Fall back to plain names (single-ticker or when batch collapses)
                if c not in raw.columns:
                    c, h, lo, v = "Close", "High", "Low", "Volume"

                if c not in raw.columns:
                    continue

                df = pd.DataFrame({
                    "Close":  raw[c],
                    "High":   raw.get(h,  pd.Series(dtype=float, index=raw.index)),
                    "Low":    raw.get(lo, pd.Series(dtype=float, index=raw.index)),
                    "Volume": raw.get(v,  pd.Series(0.0,         index=raw.index)),
                }).dropna(subset=["Close"])

                # Relax minimum from 210 to 205 — allows slight gaps in data
                if len(df) >= 205:
                    result[ticker] = df

            except Exception:
                pass

        print(f"  ✓ Usable: {len(result)}/{len(tickers)} tickers")
    except Exception as e:
        print(f"\n  ✗ Batch download failed: {e}")

    return result


# ── Step 4: Analyse single ticker ─────────────────────────────────────────────
def analyse_ticker(ticker: str, df: pd.DataFrame) -> dict | None:
    """
    Apply full box strategy rules. Returns candidate dict or None.
    """
    try:
        df = df.copy()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df["RSI"]    = calc_rsi(df["Close"])
        df["ATR"]    = calc_atr(df)

        latest = df.iloc[-1]
        close  = float(latest["Close"])
        vol    = float(latest["Volume"])
        ema200 = float(latest["EMA200"])
        rsi    = float(latest["RSI"])
        atr    = float(latest["ATR"])

        # ── Trend filter ─────────────────────────────────────────────────────
        if close < ema200:
            return None

        # ── Box window ────────────────────────────────────────────────────────
        box_df  = df.iloc[-(BOX_LOOKBACK_DAYS + 1):-1]
        if box_df.empty:
            return None

        box_high = float(box_df["High"].max())
        box_low  = float(box_df["Low"].min())
        avg_vol  = float(box_df["Volume"].mean())

        box_h_pct = (box_high - box_low) / box_low * 100
        if box_h_pct < BOX_MIN_HEIGHT_PCT:
            return None

        # ── Breakout check ────────────────────────────────────────────────────
        if close <= box_high:
            return None
        if avg_vol <= 0 or vol < avg_vol * VOLUME_SURGE_RATIO:
            return None

        # ── Trade levels ──────────────────────────────────────────────────────
        entry         = round(box_high, 2)
        box_depth     = box_high - box_low
        sl_atr        = round(entry - ATR_SL_MULTIPLIER * atr, 2)
        stop_loss     = round(max(box_low, sl_atr), 2)
        target_50     = round(entry + box_depth * 0.50, 2)
        target_100    = round(entry + box_depth, 2)

        risk          = entry - stop_loss
        reward        = target_100 - entry
        rr            = reward / (risk + 1e-10)

        if rr < MIN_RR_RATIO:
            return None

        vol_ratio     = round(vol / avg_vol, 2)

        return {
            "ticker":       ticker,
            "name":         ticker.replace(".NS", ""),
            "currentPrice": round(close, 2),
            "ema200":       round(ema200, 2),
            "rsi":          round(rsi, 2),
            "atr":          round(atr, 2),
            "boxHigh":      round(box_high, 2),
            "boxLow":       round(box_low, 2),
            "boxHeightPct": round(box_h_pct, 2),
            "volumeRatio":  vol_ratio,
            "gttEntry":     entry,
            "stopLoss":     stop_loss,
            "target50":     target_50,
            "target100":    target_100,
            "riskReward":   round(rr, 2),
        }

    except Exception as e:
        print(f"    ⚠ Error analysing {ticker}: {e}")
        return None


# ── Step 5: Build HTML page ───────────────────────────────────────────────────
def build_html(candidates: list[dict], run_time_ist: str, total_scanned: int) -> str:

    def fmt_inr(val):
        return f"₹{val:,.2f}" if val is not None else "—"

    rr_colour = lambda rr: "text-green-700 font-bold" if rr >= 3 else "text-blue-600 font-semibold" if rr >= 2 else "text-gray-700"

    cards = ""
    for i, c in enumerate(candidates):
        rank_badge = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i] if i < 5 else f"#{i+1}"
        box_bar_w  = min(100, int(c["boxHeightPct"] * 2))   # visual bar width %
        vol_bar_w  = min(100, int(c["volumeRatio"] * 40))

        cards += f"""
        <div class="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden mb-5">

          <!-- Card header -->
          <div class="bg-gradient-to-r from-slate-700 to-slate-600 text-white px-5 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-2xl">{rank_badge}</span>
              <div>
                <h3 class="text-lg font-bold">{c['name']}</h3>
                <span class="text-xs text-slate-300 font-mono">{c['ticker']}</span>
              </div>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold">{fmt_inr(c['currentPrice'])}</p>
              <p class="text-xs text-slate-300">Current Price</p>
            </div>
          </div>

          <!-- Key metrics grid -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-0 divide-x divide-y divide-gray-100 border-b border-gray-100">
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">GTT Entry</p>
              <p class="text-lg font-bold text-blue-600">{fmt_inr(c['gttEntry'])}</p>
              <p class="text-xs text-gray-400">Above box breakout</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Stop Loss</p>
              <p class="text-lg font-bold text-red-500">{fmt_inr(c['stopLoss'])}</p>
              <p class="text-xs text-gray-400">Box low / ATR floor</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">50% Target</p>
              <p class="text-lg font-bold text-amber-500">{fmt_inr(c['target50'])}</p>
              <p class="text-xs text-gray-400">Partial profit booking</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">100% Target</p>
              <p class="text-lg font-bold text-green-600">{fmt_inr(c['target100'])}</p>
              <p class="text-xs text-gray-400">Full extension</p>
            </div>
          </div>

          <!-- Secondary metrics -->
          <div class="px-5 py-4 grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">

            <div>
              <p class="text-xs text-gray-400 mb-0.5">Box Height</p>
              <p class="font-semibold text-gray-800">{c['boxHeightPct']:.1f}%</p>
              <div class="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div class="h-full bg-blue-400 rounded-full" style="width:{box_bar_w}%"></div>
              </div>
            </div>

            <div>
              <p class="text-xs text-gray-400 mb-0.5">Volume Surge</p>
              <p class="font-semibold text-gray-800">{c['volumeRatio']}×</p>
              <div class="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div class="h-full bg-green-400 rounded-full" style="width:{vol_bar_w}%"></div>
              </div>
            </div>

            <div>
              <p class="text-xs text-gray-400 mb-0.5">RSI</p>
              <p class="font-semibold {'text-green-600' if 50 <= c['rsi'] <= 70 else 'text-red-500' if c['rsi'] > 75 else 'text-gray-700'}">{c['rsi']}</p>
            </div>

            <div>
              <p class="text-xs text-gray-400 mb-0.5">EMA-200</p>
              <p class="font-semibold text-gray-700">{fmt_inr(c['ema200'])}</p>
            </div>

            <div>
              <p class="text-xs text-gray-400 mb-0.5">Risk : Reward</p>
              <p class="{rr_colour(c['riskReward'])}">1 : {c['riskReward']}</p>
            </div>

          </div>

          <!-- Visual price ladder -->
          <div class="px-5 pb-4">
            <p class="text-xs text-gray-400 mb-2 uppercase tracking-wide">Price Ladder</p>
            <div class="relative h-8 bg-gray-100 rounded-full overflow-hidden text-xs font-mono">
              <div class="absolute inset-y-0 bg-green-100 rounded-full"
                   style="left:0%; right:{100 - int((c['target100']-c['stopLoss'])/(c['target100']-c['stopLoss'])*60 + 40)}%"></div>
              <div class="absolute left-1 inset-y-0 flex items-center text-red-500">SL {fmt_inr(c['stopLoss'])}</div>
              <div class="absolute inset-y-0 flex items-center" style="left:38%">
                <span class="bg-blue-500 text-white px-1 rounded text-xs">Entry {fmt_inr(c['gttEntry'])}</span>
              </div>
              <div class="absolute right-1 inset-y-0 flex items-center text-green-600">T {fmt_inr(c['target100'])}</div>
            </div>
          </div>

        </div>"""

    no_candidates_block = """
        <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center">
          <div class="text-5xl mb-4">⏳</div>
          <h3 class="text-xl font-bold text-gray-700 mb-2">No Breakout Setups Today</h3>
          <p class="text-gray-400 text-sm max-w-md mx-auto">
            No stocks in the NSE universe met all 5 criteria today:
            EMA-200 uptrend, 20%+ box, volume surge breakout, and Risk:Reward ≥ 1.5.
            Check back after next market session.
          </p>
        </div>""" if not candidates else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Range Breakout Box Scanner — NSE</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">

  <!-- SEBI Banner -->
  <div class="bg-yellow-50 border-b border-yellow-300 py-2 px-4 text-xs text-yellow-800 text-center">
    <i class="fas fa-exclamation-triangle mr-1"></i>
    <strong>Educational use only.</strong> Range Breakout signals are for learning — not investment advice.
    <a href="disclaimer.html" class="underline ml-1">Full Disclaimer</a>
  </div>

  <!-- Nav -->
  <nav class="bg-white shadow sticky top-0 z-50">
    <div class="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="index.html" class="flex items-center gap-2 text-gray-800 font-bold text-lg">
        <i class="fas fa-chart-line text-blue-600"></i>
        Financial Literacy Hub
      </a>
      <div class="hidden md:flex items-center gap-6 text-sm">
        <a href="index.html"          class="text-gray-600 hover:text-blue-600 transition">Home</a>
        <a href="dashboard.html"      class="text-gray-600 hover:text-blue-600 transition">Dashboard</a>
        <a href="swing-dashboard.html" class="text-gray-600 hover:text-blue-600 transition">Swing Scanner</a>
        <a href="box-dashboard.html"  class="text-blue-600 font-semibold border-b-2 border-blue-600 pb-0.5">Box Scanner</a>
        <a href="discussions.html"    class="text-gray-600 hover:text-blue-600 transition">Discussions</a>
      </div>
    </div>
  </nav>

  <!-- Header -->
  <section class="bg-gradient-to-r from-slate-800 to-slate-600 text-white py-10">
    <div class="max-w-5xl mx-auto px-4">
      <h1 class="text-3xl font-bold mb-2">
        <i class="fas fa-box-open mr-2 text-amber-400"></i>
        Range Breakout Box Scanner
      </h1>
      <p class="text-slate-300 text-sm max-w-2xl mb-4">
        Scans the NSE universe every trading day after market close.
        Finds stocks with a 20%+ consolidation box that just broke out with high volume,
        sitting above their EMA-200 uptrend with Risk:Reward ≥ 1.5.
      </p>
      <div class="flex flex-wrap gap-5 text-sm text-slate-300">
        <span><i class="fas fa-clock mr-1"></i>Scan time: <strong class="text-white">{run_time_ist}</strong></span>
        <span><i class="fas fa-eye mr-1"></i>Stocks scanned: <strong class="text-white">{total_scanned}</strong></span>
        <span><i class="fas fa-fire mr-1 text-amber-400"></i>Breakouts found: <strong class="text-amber-300">{len(candidates)}</strong></span>
      </div>
    </div>
  </section>

  <!-- Strategy Summary -->
  <section class="max-w-5xl mx-auto px-4 py-4">
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-4 grid md:grid-cols-5 gap-3 text-xs text-center">
      <div class="p-3 bg-blue-50 rounded-lg">
        <p class="text-2xl mb-1">📈</p>
        <p class="font-bold text-gray-700">EMA-200</p>
        <p class="text-gray-500">Close above 200-day MA (bull structure only)</p>
      </div>
      <div class="p-3 bg-amber-50 rounded-lg">
        <p class="text-2xl mb-1">📦</p>
        <p class="font-bold text-gray-700">Box ≥ 20%</p>
        <p class="text-gray-500">60-day consolidation range at least 20% tall</p>
      </div>
      <div class="p-3 bg-green-50 rounded-lg">
        <p class="text-2xl mb-1">🚀</p>
        <p class="font-bold text-gray-700">Breakout</p>
        <p class="text-gray-500">Close &gt; box high with 1.2× volume surge</p>
      </div>
      <div class="p-3 bg-purple-50 rounded-lg">
        <p class="text-2xl mb-1">🎯</p>
        <p class="font-bold text-gray-700">GTT Order</p>
        <p class="text-gray-500">Place limit order above box — auto triggers on retest</p>
      </div>
      <div class="p-3 bg-red-50 rounded-lg">
        <p class="text-2xl mb-1">⚖️</p>
        <p class="font-bold text-gray-700">R:R ≥ 1.5</p>
        <p class="text-gray-500">Only setups with reward at least 1.5× the risk</p>
      </div>
    </div>
  </section>

  <!-- Results -->
  <main class="max-w-5xl mx-auto px-4 py-2 pb-12">
    <div class="flex items-center gap-3 mb-4">
      <h2 class="text-lg font-bold text-gray-800">
        <i class="fas fa-trophy mr-1 text-amber-500"></i>
        Top {len(candidates)} Breakout Candidates
      </h2>
      <span class="text-xs text-gray-400">Ranked by RSI strength</span>
    </div>
    {cards}
    {no_candidates_block}
  </main>

  <!-- How to use -->
  <section class="max-w-5xl mx-auto px-4 pb-10">
    <div class="bg-slate-800 text-white rounded-xl p-6 text-sm">
      <h3 class="font-bold text-amber-400 mb-4 text-base"><i class="fas fa-graduation-cap mr-2"></i>How to Execute This Strategy</h3>
      <div class="grid md:grid-cols-3 gap-5 text-slate-300">
        <div>
          <p class="font-bold text-white mb-2">1. NSE Stock Selection</p>
          <p>On NSE India, filter for Advances → sort by Total Trading Volume → pick stocks that moved 5%+ in one session. These are your high-momentum candidates.</p>
        </div>
        <div>
          <p class="font-bold text-white mb-2">2. Box Setup on Chart</p>
          <p>Open daily chart. Identify swing high and swing low with ≥20% range. Draw horizontal rectangle between them. The breakout above the upper band is your entry signal.</p>
        </div>
        <div>
          <p class="font-bold text-white mb-2">3. GTT Order (No Screen-Watching)</p>
          <p>Place a Good-Till-Triggered limit order just above the box high after the breakout candle closes. It fires automatically on retest. No intraday monitoring needed.</p>
        </div>
        <div>
          <p class="font-bold text-white mb-2">4. Profit Targets (Math-Based)</p>
          <p>50% of box height = conservative partial booking. 100% clone of the box above breakout = full swing target. Pure price symmetry — no guessing.</p>
        </div>
        <div>
          <p class="font-bold text-white mb-2">5. Stop Loss</p>
          <p>Hard stop at box low (ultimate invalidation). Since this is a wide stop, use small position sizing per trade (e.g. ₹5,000) so a full loss is never portfolio-damaging.</p>
        </div>
        <div>
          <p class="font-bold text-white mb-2">6. Capital Allocation</p>
          <p>Split capital into small pots. Deploy only a small fraction per breakout. The wide stop is designed for equity only — never leverage or F&O on this strategy.</p>
        </div>
      </div>
      <div class="mt-5 pt-4 border-t border-slate-600 grid md:grid-cols-2 gap-4 text-xs text-slate-400">
        <div><strong class="text-green-400">Advantages:</strong> Mathematically objective targets, stress-free GTT execution, no time decay (equity only), predefined risk per trade.</div>
        <div><strong class="text-red-400">Risks:</strong> Capital locked for 40–100+ days, wide nominal drawdowns during pullbacks before the move. Only use surplus funds.</div>
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


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ist          = ZoneInfo("Asia/Kolkata")
    run_time_ist = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    print(f"🔍 Range Breakout Box Scanner — {run_time_ist}")
    print(f"   Min box height: {BOX_MIN_HEIGHT_PCT}% | Volume surge: {VOLUME_SURGE_RATIO}× | Min R:R: {MIN_RR_RATIO}")
    print()

    # ── 1. Get tickers ────────────────────────────────────────────────────────
    tickers = get_nse_tickers()
    print()

    # ── 2. Batch download 1 year of daily OHLCV ──────────────────────────────
    # Process in chunks of 100 to avoid Yahoo throttling on large universes
    CHUNK = 100
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        print(f"  Batch {i // CHUNK + 1}: tickers {i+1}–{i+len(chunk)}")
        chunk_data = batch_download(chunk)
        all_data.update(chunk_data)

    print(f"\n  Total tickers with 1-year data: {len(all_data)}")
    total_scanned = len(all_data)

    # ── 3. Analyse each ticker ────────────────────────────────────────────────
    print("\n⚙️  Analysing breakout conditions…")
    candidates: list[dict] = []
    for ticker, df in all_data.items():
        result = analyse_ticker(ticker, df)
        if result:
            candidates.append(result)
            print(f"  ✅ BREAKOUT: {ticker} | Box {result['boxHeightPct']:.1f}% | R:R 1:{result['riskReward']}")

    # ── 4. Rank top N by RSI ──────────────────────────────────────────────────
    candidates.sort(key=lambda x: x["rsi"], reverse=True)
    top = candidates[:TOP_N]

    print(f"\n── Scan Summary ──────────────────────────────")
    print(f"  Scanned : {total_scanned}")
    print(f"  Breakouts: {len(candidates)}")
    print(f"  Returning top {len(top)} by RSI")

    # ── 5. Save JSON ──────────────────────────────────────────────────────────
    output = {
        "lastUpdated":   datetime.utcnow().isoformat() + "Z",
        "runTimeIST":    run_time_ist,
        "totalScanned":  total_scanned,
        "totalBreakouts": len(candidates),
        "config": {
            "boxLookbackDays":   BOX_LOOKBACK_DAYS,
            "boxMinHeightPct":   BOX_MIN_HEIGHT_PCT,
            "volumeSurgeRatio":  VOLUME_SURGE_RATIO,
            "minRR":             MIN_RR_RATIO,
        },
        "candidates": top,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✅ Saved: {OUTPUT_JSON}")

    # ── 6. Save HTML ──────────────────────────────────────────────────────────
    html = build_html(top, run_time_ist, total_scanned)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Saved: {OUTPUT_HTML}")

    return 0


if __name__ == "__main__":
    main()
