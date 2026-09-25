#!/usr/bin/env python3
"""
Institutional Momentum-Squeeze & Bottom-Sweep Scanner — Dynamic NSE Universe
------------------------------------------------------------------------------
BRD-aligned implementation (v2):

  Squeeze criteria (BRD Section 1):
    1. EMA 20/50 spread  <= 1.5%  (Dual-EMA Compression — coiled spring)
    2. Today's volume    < 20-day SMA of volume (Volume Exhaustion — selling death)
    3. RSI (14)          30 – 55 (RSI Decompression Shield; disqualify >= 65)
  -> All three = CRITICAL
  -> #1 + #2 only = SETUP (RSI outside zone)
  -> #1 only       = WATCH
  -> RSI >= 65     = OVEREXTENDED (retail FOMO disqualified)

  Framework mapping (BRD Section 2):
    A. Swing Breakout  -> price above EMA-50 (bullish structure, 5-15 session horizon)
    B. Bottom-Sweep    -> price below EMA-50 near structural demand (3-24 month horizon)

  Back-testing (BRD Section 3) — 36-month look-back per ticker:
    Finds every historical squeeze event and measures:
      - Win Rate    : % of events that hit +10% target before -5% SL within 15 sessions
      - Max Drawdown: worst peak-to-trough during each event's 15-session window
      - R:R         : avg winner delta / avg loser delta (BRD target: >= 1:2.5)

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

# ── Thresholds — BRD Section 1 exact values ──────────────────────────────────
EMA_SPREAD_MAX    = 1.5    # % — EMAs must be pinched tighter than this (BRD: <= 1.5%)
VOLUME_DRYUP_MAX  = 1.0    # ratio — vol STRICTLY LOWER than 20-day SMA (BRD: < SMA, not < 75%)
RSI_LOW           = 30     # RSI floor (BRD: 30-55 zone; oversold floor = 30)
RSI_HIGH          = 55     # RSI ceiling before FOMO (BRD: 55)
RSI_OVERBOUGHT    = 65     # disqualify threshold (BRD: ">=65-70"; using 65 = conservative)

# ── Back-testing parameters (BRD Section 3) ──────────────────────────────────
BT_LOOKBACK_YEARS = 3      # 36-month look-back window
BT_HOLD_SESSIONS  = 15     # "within 3 weeks" = 15 trading sessions
BT_TARGET_PCT     = 10.0   # proxy for "next structural resistance" = +10%
BT_SL_PCT         = 5.0    # stop-loss proxy = -5% (below breakout candle's wick)
BT_MIN_RR_TARGET  = 2.5    # BRD target: >= 1:2.5 R:R
BT_WIN_RATE_TARGET = 80.0  # BRD target: >80% win rate

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

                if len(df) >= 60:   # need 50 for EMA-50 warmup + 15 forward sessions for BT
                    out[ticker] = df

            except Exception:
                pass

    except Exception as e:
        print(f"\n  ✗ Batch failed: {e}")

    return out


# ── Step 4: Back-test squeeze events (BRD §3 — 36-month window) ───────────────
def backtest_squeeze(df: pd.DataFrame) -> dict:
    """
    Scans historical data (up to BT_LOOKBACK_YEARS years) for past squeeze events
    and reports Win Rate, Max Drawdown, and R:R efficiency.

    A historical squeeze event = day where:
      - EMA spread <= EMA_SPREAD_MAX
      - volume < avg_vol (VOLUME_DRYUP_MAX = 1.0)
      - RSI between RSI_LOW and RSI_HIGH

    Each event is then forward-tested over BT_HOLD_SESSIONS days:
      - Win  = price hits +BT_TARGET_PCT before hitting -BT_SL_PCT
      - Loss = price hits -BT_SL_PCT first (or neither hit = loss by default)
    """
    result = {
        "btEvents":      0,
        "btWins":        0,
        "btLosses":      0,
        "btWinRate":     None,
        "btMaxDrawdown": None,
        "btRR":          None,
        "btMeetsWinRate": False,
        "btMeetsRR":      False,
        "btNote":        "Insufficient history for back-test",
    }

    try:
        df = df.copy()
        df["ema20"]    = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]    = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"]  = df["volume"].rolling(window=20).mean()
        df["spread"]   = (df["ema20"] - df["ema50"]).abs() / df["ema50"] * 100

        # RSI column
        delta    = df["close"].diff()
        gain     = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss     = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs       = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        # Only use rows older than BT_HOLD_SESSIONS (leave tail for live signal)
        cutoff = len(df) - BT_HOLD_SESSIONS
        if cutoff < 60:
            return result

        events = []
        for i in range(55, cutoff):
            row = df.iloc[i]
            if pd.isna(row["avg_vol"]) or row["avg_vol"] <= 0:
                continue
            compressed = row["spread"] <= EMA_SPREAD_MAX
            vol_dry    = row["volume"] < row["avg_vol"] * VOLUME_DRYUP_MAX
            rsi_ok     = RSI_LOW <= row["rsi"] <= RSI_HIGH if not pd.isna(row["rsi"]) else False
            if compressed and vol_dry and rsi_ok:
                events.append(i)

        if not events:
            result["btNote"] = "No historical squeeze events found in back-test window"
            return result

        wins, losses = [], []
        all_drawdowns = []

        for idx in events:
            entry = float(df["close"].iloc[idx])
            target = entry * (1 + BT_TARGET_PCT / 100)
            sl     = entry * (1 - BT_SL_PCT / 100)
            future = df["close"].iloc[idx + 1: idx + 1 + BT_HOLD_SESSIONS]

            outcome = "loss"   # default if neither hit in window
            win_delta = loss_delta = 0.0

            # track intra-window drawdown
            peak = entry
            max_dd = 0.0
            for p in future:
                if p > peak:
                    peak = p
                dd = (peak - p) / peak * 100
                if dd > max_dd:
                    max_dd = dd
                if p >= target:
                    outcome = "win"
                    win_delta = (p - entry) / entry * 100
                    break
                if p <= sl:
                    outcome = "loss"
                    loss_delta = (entry - p) / entry * 100
                    break

            all_drawdowns.append(max_dd)
            if outcome == "win":
                wins.append(win_delta)
            else:
                losses.append(loss_delta if loss_delta else BT_SL_PCT)

        total      = len(wins) + len(losses)
        win_rate   = round(len(wins) / total * 100, 1) if total else 0
        avg_win    = round(sum(wins) / len(wins), 2) if wins else 0
        avg_loss   = round(sum(losses) / len(losses), 2) if losses else 0
        rr         = round(avg_win / avg_loss, 2) if avg_loss > 0 else None
        max_dd_all = round(max(all_drawdowns), 2) if all_drawdowns else 0

        result.update({
            "btEvents":      total,
            "btWins":        len(wins),
            "btLosses":      len(losses),
            "btWinRate":     win_rate,
            "btMaxDrawdown": max_dd_all,
            "btRR":          rr,
            "btAvgWin":      avg_win,
            "btAvgLoss":     avg_loss,
            "btMeetsWinRate": win_rate >= BT_WIN_RATE_TARGET,
            "btMeetsRR":      (rr or 0) >= BT_MIN_RR_TARGET,
            "btNote":        f"{total} events | {len(wins)}W/{len(losses)}L over 36-month window",
        })

    except Exception as e:
        result["btNote"] = f"Back-test error: {e}"

    return result


# ── Step 5: Analyse single stock ─────────────────────────────────────────────
def analyse(ticker: str, df: pd.DataFrame, meta: dict) -> dict:
    result = {
        "ticker":       ticker,
        "name":         meta.get("name", ticker.replace(".NS", "")),
        "sector":       meta.get("sector", "NSE"),
        "isSeed":       ticker in SEED_TICKERS,
        "status":       "error",
        "alert":        "Insufficient data",
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
        # Framework (BRD §2)
        "framework":    None,   # "A" = Swing Breakout, "B" = Bottom-Sweep
        "frameworkDesc": None,
        # Back-test (BRD §3)
        "backtest":     {},
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

        # BRD §1 — exact conditions
        compressed   = spread <= EMA_SPREAD_MAX
        vol_dry_up   = vol < avg_vol * VOLUME_DRYUP_MAX   # strictly < SMA (VOLUME_DRYUP_MAX=1.0)
        rsi_in_zone  = RSI_LOW <= rsi <= RSI_HIGH
        rsi_over     = rsi >= RSI_OVERBOUGHT              # BRD: disqualify >= 65

        # BRD §2 — Framework mapping
        if price >= ema50:
            framework      = "A"
            framework_desc = "Framework A — Swing Breakout (5–15 sessions). Price above EMA-50."
        else:
            framework      = "B"
            framework_desc = "Framework B — Bottom-Sweep Accumulation (3–24 months). Price below EMA-50."

        # Alert classification
        if rsi_over:
            alert, level = f"RSI Overextended ({rsi}) — retail FOMO zone, disqualified.", "overextended"
        elif compressed and vol_dry_up and rsi_in_zone:
            alert, level = f"CRITICAL: All 3 BRD conditions met! Spread {spread:.2f}% | Vol ratio {vol_ratio:.2f}x | RSI {rsi}", "critical"
        elif compressed and vol_dry_up:
            alert, level = f"Setup: EMA compressed ({spread:.2f}%) + volume exhaustion (ratio {vol_ratio:.2f}x). RSI {rsi} outside 30-55 zone.", "setup"
        elif compressed:
            alert, level = f"Watch: EMA spread {spread:.2f}% (compressed). Awaiting volume dry-up.", "watch"
        else:
            alert, level = f"Normal consolidation. Spread {spread:.2f}% | RSI {rsi}", "normal"

        # BRD §3 — back-test (only run on non-normal/non-error; avoids CI timeout on universe)
        bt = backtest_squeeze(df)

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
            "framework":     framework,
            "frameworkDesc": framework_desc,
            "backtest":      bt,
        })

    except Exception as e:
        result["alert"] = f"Error: {e}"

    return result


# ── Step 6: Build HTML ────────────────────────────────────────────────────────
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
    FW_PILL = {
        "A": '<span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded font-semibold">Framework A — Swing Breakout</span>',
        "B": '<span class="text-xs bg-amber-100  text-amber-700  px-2 py-0.5 rounded font-semibold">Framework B — Bottom Sweep</span>',
    }

    def badge(ok, yes, no, yc="bg-green-100 text-green-800", nc="bg-gray-100 text-gray-400"):
        return f'<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold {yc if ok else nc}">{yes if ok else no}</span>'

    def bt_cell(val, suffix="", good_fn=None, na="—"):
        if val is None:
            return f'<span class="text-gray-400">{na}</span>'
        s = f"{val}{suffix}"
        if good_fn:
            c = "text-green-700 font-bold" if good_fn(val) else "text-red-600 font-semibold"
            return f'<span class="{c}">{s}</span>'
        return f'<span class="text-gray-700 font-semibold">{s}</span>'

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
        vr_s  = f"{r['volumeRatio']:.2f}x" if r["volumeRatio"] is not None else "—"
        seed_pill = '<span class="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Mentor</span>' if r.get("isSeed") else '<span class="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">Universe</span>'
        fw_pill   = FW_PILL.get(r.get("framework", ""), "")

        bt = r.get("backtest", {})
        bt_wr  = bt.get("btWinRate")
        bt_mdd = bt.get("btMaxDrawdown")
        bt_rr  = bt.get("btRR")
        bt_note = bt.get("btNote", "")
        bt_ev  = bt.get("btEvents", 0)

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
                {fw_pill}
              </div>
              <p class="text-sm text-gray-700 font-medium">{r['alert']}</p>
              <p class="text-xs text-gray-400 mt-0.5 italic">{r.get('frameworkDesc','')}</p>
            </div>
            <div class="text-right flex-shrink-0">
              <p class="text-2xl font-bold text-gray-900">{p(r['currentPrice'])}</p>
              <p class="text-xs text-gray-400">Current Price</p>
            </div>
          </div>

          <!-- Live signal metrics -->
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
              <p class="font-semibold {'text-green-700' if r['isRsiInZone'] else 'text-red-600' if r['rsi'] and r['rsi'] >= RSI_OVERBOUGHT else 'text-gray-700'}">{rsi_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Vol Ratio</p>
              <p class="font-semibold {'text-green-700' if r['isVolumeDryUp'] else 'text-gray-700'}">{vr_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center text-xs space-y-1">
              <p class="text-gray-400 mb-1">BRD Conditions</p>
              {badge(r['isCompressed'],  '✅ EMA ≤1.5%',  '❌ Spread wide')}
              {badge(r['isVolumeDryUp'], '✅ Vol &lt; SMA', '❌ Normal vol')}
              {badge(r['isRsiInZone'],   '✅ RSI 30-55',   '⚠️ RSI outside', 'bg-green-100 text-green-800', 'bg-orange-100 text-orange-700')}
            </div>
          </div>

          <!-- Back-test metrics (BRD §3) -->
          <div class="mt-3 bg-slate-50 border border-slate-200 rounded p-3">
            <p class="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">36-Month Back-test  <span class="font-normal normal-case text-slate-400">({bt_ev} squeeze events)</span></p>
            <div class="grid grid-cols-3 gap-3 text-sm text-center">
              <div>
                <p class="text-xs text-gray-400 mb-0.5">Win Rate <span class="text-gray-300">(target &gt;80%)</span></p>
                {bt_cell(bt_wr, '%', lambda v: v >= BT_WIN_RATE_TARGET)}
              </div>
              <div>
                <p class="text-xs text-gray-400 mb-0.5">Max Drawdown</p>
                {bt_cell(bt_mdd, '%', lambda v: v < 10.0)}
              </div>
              <div>
                <p class="text-xs text-gray-400 mb-0.5">R:R <span class="text-gray-300">(target ≥1:2.5)</span></p>
                {bt_cell(bt_rr, ':1', lambda v: v >= BT_MIN_RR_TARGET)}
              </div>
            </div>
            <p class="text-xs text-slate-400 mt-2 italic">{bt_note}</p>
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
        <a href="discussions.html"     class="text-gray-600 hover:text-blue-600"><i class="fas fa-tasks mr-1"></i>Stock Manager</a>
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
        EMA 20/50 are compressed (≤ 1.5%), volume is strictly below the 20-day SMA (exhaustion), and RSI is in the 30–55 neutral zone. RSI ≥ 65 is disqualified.
        Mentor's 7 seed stocks are always included. Each card includes 36-month back-test metrics.
      </p>
      <div class="flex flex-wrap gap-5 text-xs text-blue-300">
      <span><i class="fas fa-clock mr-1"></i>Scan: <strong class="text-white">{run_time}</strong></span>
      <span><i class="fas fa-database mr-1"></i>Universe: <strong class="text-white">{len(results)}</strong> stocks analysed</span>
      <span class="text-green-400"><i class="fas fa-fire mr-1"></i>{n_critical} Critical</span>
      <span class="text-yellow-400"><i class="fas fa-bolt mr-1"></i>{n_setup} Setup</span>
      <span class="text-blue-300"><i class="fas fa-eye mr-1"></i>{n_watch} Watch</span>
      <span class="text-blue-200"><i class="fas fa-seedling mr-1"></i>{n_seed} seed | {n_universe} universe finds</span>
      <span class="text-indigo-300"><i class="fas fa-info-circle mr-1"></i>BRD: EMA ≤1.5% | Vol &lt; SMA(20) | RSI 30–55 | Disqualify ≥65</span>
    </div>
    </div>
  </section>

  <section class="max-w-6xl mx-auto px-4 py-4 space-y-3">
    <!-- Signal legend -->
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-green-500 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🎯 Critical</p><p class="text-gray-500">All 3 BRD conditions: EMA ≤1.5% + Vol &lt; SMA(20) + RSI 30–55.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-yellow-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">⚡ Setup</p><p class="text-gray-500">EMA compressed + volume exhaustion. RSI still outside zone.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-blue-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🔄 Watch</p><p class="text-gray-500">EMAs compressing. Awaiting volume dry-up confirmation.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-red-400 flex-shrink-0"></span>
        <div><p class="font-bold text-gray-800">🚫 Overextended</p><p class="text-gray-500">RSI ≥ 65 — retail FOMO. BRD disqualifies this entry.</p></div>
      </div>
    </div>
    <!-- Framework legend -->
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-indigo-400 flex-shrink-0"></span>
        <div>
          <p class="font-bold text-gray-800">Framework A — High-Velocity Swing Breakout</p>
          <p class="text-gray-500">Price above EMA-50. Horizon: 5–15 sessions. Entry: Day 1 above resistance box + VWAP. SL: daily close below breakout candle's wick.</p>
        </div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-amber-400 flex-shrink-0"></span>
        <div>
          <p class="font-bold text-gray-800">Framework B — Positional Bottom-Sweep</p>
          <p class="text-gray-500">Price below EMA-50. Horizon: 3–24 months. Entry: 3-tier grid below price anchored to 50-week EMA/structural floors. SL optional if asset is debt-free.</p>
        </div>
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

    # ── 2. Batch download in chunks of 80 — 3y needed for 36-month back-test ─
    CHUNK = 80
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(all_tickers), CHUNK):
        chunk = all_tickers[i:i + CHUNK]
        chunk_data = batch_download(chunk, period="3y")
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
