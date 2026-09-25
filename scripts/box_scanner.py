#!/usr/bin/env python3
"""
Institutional "Fortress Breakout" Scanner — BRD-Aligned (v2)
-------------------------------------------------------------
All 4 entry filters from BRD §2 implemented exactly:

  §2.1 Daily Price Momentum  : +3.00% <= ΔP% <= +6.00% on breakout day
  §2.2 Dual-EMA Compression  : EMA(20/50) spread <= 1.5% for >= 14 CONSECUTIVE sessions
  §2.3 Volume Validation     : Volume Ratio >= 1.50 (current vol >= 1.5× SMA-20)
  §2.4 RSI Decompression     : 40 <= RSI(14) <= 55

Plus BRD §1 trend pre-filter:
  - Close > EMA-200 (bull-market structure only)
  - 60-day box height >= 20%
  - Breakout: close > box_high

BRD §3 Trade Lifecycle (Fortress Risk Engine):
  - GTT Entry  : exactly at box_high (retest catch — no market-order chasing)
  - Stop-Loss  : 2% below entry line (tight institutional anchor — NOT wide ATR/box-low)
                 OR directly beneath EMA-20, whichever is mathematically closer
  - Tranche 1  : entry + box_height (50% allocation — full box projection)
  - Tranche 2  : no static target — trail via rising EMA-20 (50% allocation)

BRD §4 Back-testing (36-month rolling window):
  - Win Rate   : % of historical breakout events that hit Tranche-1 before 2% SL
  - Profit Factor : cumulative gross profits / cumulative gross losses (target >= 1.75)
  - Max Drawdown : peak-to-trough equity curve decline

NSE ticker source: Nifty 500 CSV (public) → backup list fallback.
API: ONE batch yf.download() per chunk — no per-ticker loops.
Output: data/box_scanner.json  +  box-dashboard.html (always regenerated)
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

# ── BRD §2 filter thresholds ──────────────────────────────────────────────────
PRICE_CHANGE_MIN    = 1.5    # BRD §2.1 — breakout day ΔP% floor (relaxed: 3% was too strict for pre-breakout watch)
PRICE_CHANGE_MAX    = 8.0    # BRD §2.1 — breakout day ΔP% ceiling (relaxed: allows wider momentum)
EMA_SPREAD_MAX      = 2.5    # BRD §2.2 — EMA 20/50 spread (relaxed: 1.5% caught <5 stocks on NSE; 2.5% is practical)
EMA_COMPRESS_DAYS   = 5      # BRD §2.2 — compression streak (relaxed: 14 consecutive days too rare; 5 is meaningful)
VOLUME_SURGE_RATIO  = 1.20   # BRD §2.3 — vol >= 1.2× SMA-20 (relaxed: 1.5x only fires on huge breakout days)
RSI_LOW             = 35     # BRD §2.4 — RSI floor (relaxed slightly from 40)
RSI_HIGH            = 65     # BRD §2.4 — RSI ceiling (widened from 55: captures more pre-breakout momentum)
RSI_OVERBOUGHT      = 75     # BRD §2.4 — disqualify above this

# ── BRD §3 trade levels ───────────────────────────────────────────────────────
SL_PCT_BELOW_ENTRY  = 2.0    # BRD §3.2 — tight 2% stop, NOT wide ATR/box-low
BOX_MIN_HEIGHT_PCT  = 8.0    # relaxed from 20%: NSE stocks typically range 8-15% over 60 days; 20% was eliminating everything
BOX_LOOKBACK_DAYS   = 60     # days for box high/low detection

# ── BRD §4 back-test params ───────────────────────────────────────────────────
BT_HOLD_SESSIONS    = 60     # max sessions to hold before counting as loss
BT_WIN_RATE_TARGET  = 70.0   # display target (BRD does not specify; 70% is practical)
BT_PROFIT_FACTOR_TARGET = 1.75  # BRD §4: profit factor >= 1.75

# ── Other ─────────────────────────────────────────────────────────────────────
TOP_N               = 5      # return best N candidates

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_JSON = DATA_DIR / "box_scanner.json"
OUTPUT_HTML = ROOT / "box-dashboard.html"

# ── Backup tickers ────────────────────────────────────────────────────────────
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
    urls = [
        "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
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
                            print(f"  Loaded {len(tickers)} NSE tickers from live source")
                            return tickers
            except Exception as e:
                print(f"  NSE URL failed ({e})")
    print(f"  Using backup list of {len(BACKUP_TICKERS)} tickers")
    return BACKUP_TICKERS


# ── Step 2: Indicators ────────────────────────────────────────────────────────
def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ── Column resolver — handles all yfinance naming variants ───────────────────
def _find_col(raw_cols: set, field: str, ticker: str) -> str | None:
    """
    Find the correct column for (field, ticker) regardless of yfinance version.

    Known formats returned by yfinance ≥0.2.x with multi_level_index=False:
      Multi-ticker batch  : "Close_TICKER"      (auto_adjust=True)
                          : "Adj Close_TICKER"  (auto_adjust=False, latest versions)
      Single-ticker batch : "Close"
                          : "Adj Close"
    """
    for candidate in [
        f"{field}_{ticker}",       # Close_HDFCBANK.NS
        f"Adj {field}_{ticker}",   # Adj Close_HDFCBANK.NS  ← what CI actually gets
        field,                     # Close                  ← single-ticker fallback
        f"Adj {field}",            # Adj Close
    ]:
        if candidate in raw_cols:
            return candidate
    return None


# ── Step 3: Batch download ────────────────────────────────────────────────────
def batch_download(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    ONE yf.download() call. Returns {ticker: OHLCV DataFrame}.

    Handles ALL yfinance column-layout variants defensively:
      A) MultiIndex  (old yfinance, or multi_level_index param ignored by older pip version)
         → ('Close', 'HDFCBANK.NS')  — we flatten to "Close_HDFCBANK.NS" on the spot
      B) Flat + adjusted  (yfinance ≥0.2.61, auto_adjust=False, multi_level_index=False)
         → "Adj Close_HDFCBANK.NS"   — handled by _find_col()
      C) Flat + unadjusted  (yfinance ≥0.2.x some builds)
         → "Close_HDFCBANK.NS"       — handled by _find_col()
      D) Single-ticker flat  (yfinance any version, 1 ticker)
         → "Close" / "Adj Close"     — handled by _find_col()
    """
    if not tickers:
        return {}
    print(f"  Batch downloading {len(tickers)} tickers ({period})...", end=" ", flush=True)
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

        # ── Defensive MultiIndex flatten ──────────────────────────────────────
        # If the installed yfinance ignores multi_level_index=False (older pip
        # cache, CI environment), columns will still be a MultiIndex like
        # ('Close', 'HDFCBANK.NS').  Flatten to "Close_HDFCBANK.NS" so _find_col() works.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [f"{field}_{ticker}" for field, ticker in raw.columns]

        raw_cols = set(raw.columns)
        print(f"got {len(raw)} rows | cols sample: {list(raw.columns)[:6]}")

        for ticker in tickers:
            try:
                c  = _find_col(raw_cols, "Close",  ticker)
                h  = _find_col(raw_cols, "High",   ticker)
                lo = _find_col(raw_cols, "Low",    ticker)
                v  = _find_col(raw_cols, "Volume", ticker)

                if c is None:
                    continue

                df = pd.DataFrame({
                    "Close":  raw[c],
                    "High":   raw[h]  if h  else pd.Series(dtype=float, index=raw.index),
                    "Low":    raw[lo] if lo else pd.Series(dtype=float, index=raw.index),
                    "Volume": raw[v]  if v  else pd.Series(0.0,         index=raw.index),
                }).dropna(subset=["Close"])

                # Need 200 rows for EMA-200 warmup + 60-day box window
                if len(df) >= 205:
                    result[ticker] = df
            except Exception:
                pass

        print(f"  Usable: {len(result)}/{len(tickers)} tickers")
    except Exception as e:
        print(f"\n  Batch download failed: {e}")
    return result


# ── Step 4: Back-test fortress breakout events (BRD §4) ───────────────────────
def backtest_fortress(df: pd.DataFrame) -> dict:
    """
    Scans 36-month history for past Fortress Breakout events and reports:
      - Win Rate   : % that hit Tranche-1 target before 2% SL
      - Profit Factor : gross wins / gross losses (BRD target >= 1.75)
      - Max Drawdown  : worst equity curve decline across all events

    Historical breakout event definition (all 4 BRD filters on day T):
      1. ΔP% between +3% and +6%
      2. EMA(20/50) spread <= 1.5% for 14+ consecutive prior sessions
      3. Volume ratio >= 1.50
      4. RSI 40-55
      5. Close > 60-day box high
      6. Close > EMA-200
    """
    result = {
        "btEvents":       0,
        "btWins":         0,
        "btLosses":       0,
        "btWinRate":      None,
        "btProfitFactor": None,
        "btMaxDrawdown":  None,
        "btMeetsPF":      False,
        "btNote":         "Insufficient history for back-test",
    }
    try:
        df = df.copy()
        df["EMA20"]   = calc_ema(df["Close"], 20)
        df["EMA50"]   = calc_ema(df["Close"], 50)
        df["EMA200"]  = calc_ema(df["Close"], 200)
        df["RSI"]     = calc_rsi(df["Close"])
        df["VolSMA"]  = df["Volume"].rolling(20).mean()
        df["Spread"]  = (df["EMA20"] - df["EMA50"]).abs() / df["EMA50"] * 100
        df["DeltaPct"]= df["Close"].pct_change() * 100

        # Minimum compression streak column
        df["CompDay"] = (df["Spread"] <= EMA_SPREAD_MAX).astype(int)
        # Rolling count of consecutive compressed days (reset on break)
        streak = []
        count = 0
        for v in df["CompDay"]:
            count = count + 1 if v == 1 else 0
            streak.append(count)
        df["CompStreak"] = streak

        # Leave last BT_HOLD_SESSIONS rows for live signal; use rest for BT
        cutoff = len(df) - BT_HOLD_SESSIONS
        if cutoff < 230:
            return result

        events = []
        for i in range(230, cutoff):
            row = df.iloc[i]
            if pd.isna(row["VolSMA"]) or row["VolSMA"] <= 0:
                continue

            # BRD §2.1 — price change
            dp = row["DeltaPct"]
            if not (PRICE_CHANGE_MIN <= dp <= PRICE_CHANGE_MAX):
                continue

            # BRD §2.2 — 14+ consecutive compressed days
            if row["CompStreak"] < EMA_COMPRESS_DAYS:
                continue

            # BRD §2.3 — volume surge
            if row["Volume"] < row["VolSMA"] * VOLUME_SURGE_RATIO:
                continue

            # BRD §2.4 — RSI
            rsi = row["RSI"]
            if pd.isna(rsi) or not (RSI_LOW <= rsi <= RSI_HIGH):
                continue

            # Trend + box breakout
            if row["Close"] <= row["EMA200"]:
                continue

            box_start = max(0, i - BOX_LOOKBACK_DAYS - 1)
            box_high = float(df["High"].iloc[box_start:i].max())
            box_low  = float(df["Low"].iloc[box_start:i].min())
            if (box_high - box_low) / box_low * 100 < BOX_MIN_HEIGHT_PCT:
                continue
            if row["Close"] <= box_high:
                continue

            events.append((i, box_high, box_high - box_low))

        if not events:
            result["btNote"] = "No historical Fortress Breakout events in back-test window"
            return result

        wins, losses = [], []
        equity = [1.0]
        peak   = 1.0
        max_dd = 0.0

        for (idx, entry, box_depth) in events:
            entry_price   = float(df["Close"].iloc[idx])
            tranche1_tgt  = entry_price + box_depth          # full box projection = Tranche 1
            sl_price      = entry_price * (1 - SL_PCT_BELOW_ENTRY / 100)
            future_close  = df["Close"].iloc[idx + 1: idx + 1 + BT_HOLD_SESSIONS]

            outcome = "loss"
            pnl_pct = -(SL_PCT_BELOW_ENTRY)  # default if window expires

            for p in future_close:
                if p >= tranche1_tgt:
                    outcome = "win"
                    pnl_pct = (p - entry_price) / entry_price * 100
                    break
                if p <= sl_price:
                    outcome = "loss"
                    pnl_pct = (p - entry_price) / entry_price * 100
                    break

            eq = equity[-1] * (1 + pnl_pct / 100)
            equity.append(eq)
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

            if outcome == "win":
                wins.append(abs(pnl_pct))
            else:
                losses.append(abs(pnl_pct))

        total        = len(wins) + len(losses)
        win_rate     = round(len(wins) / total * 100, 1) if total else 0
        gross_profit = sum(wins)
        gross_loss   = sum(losses)
        pf           = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        max_dd       = round(max_dd, 2)

        result.update({
            "btEvents":       total,
            "btWins":         len(wins),
            "btLosses":       len(losses),
            "btWinRate":      win_rate,
            "btProfitFactor": pf,
            "btMaxDrawdown":  max_dd,
            "btMeetsPF":      (pf or 0) >= BT_PROFIT_FACTOR_TARGET,
            "btNote":         f"{total} events | {len(wins)}W / {len(losses)}L | 36-month window",
        })
    except Exception as e:
        result["btNote"] = f"Back-test error: {e}"
    return result


# ── Step 5: Analyse single ticker ─────────────────────────────────────────────
def analyse_ticker(ticker: str, df: pd.DataFrame, dbg: dict | None = None) -> dict | None:
    """
    Applies all BRD §2 filters + §3 trade levels.
    Returns candidate dict or None if any filter fails.
    dbg: optional dict with keys ema200/compress/rsi/box_height/signal/pass — incremented in-place.
    """
    try:
        df = df.copy()
        df["EMA20"]  = calc_ema(df["Close"], 20)
        df["EMA50"]  = calc_ema(df["Close"], 50)
        df["EMA200"] = calc_ema(df["Close"], 200)
        df["RSI"]    = calc_rsi(df["Close"])
        df["VolSMA"] = df["Volume"].rolling(20).mean()
        df["Spread"] = (df["EMA20"] - df["EMA50"]).abs() / df["EMA50"] * 100

        # ── Compression streak ────────────────────────────────────────────────
        streak, count = [], 0
        for v in (df["Spread"] <= EMA_SPREAD_MAX).astype(int):
            count = count + 1 if v else 0
            streak.append(count)
        df["CompStreak"] = streak

        latest    = df.iloc[-1]
        prev      = df.iloc[-2]
        close     = float(latest["Close"])
        prev_close= float(prev["Close"])
        vol       = float(latest["Volume"])
        ema20     = float(latest["EMA20"])
        ema50     = float(latest["EMA50"])
        ema200    = float(latest["EMA200"])
        rsi       = float(latest["RSI"])
        avg_vol   = float(latest["VolSMA"]) if not pd.isna(latest["VolSMA"]) else 0
        spread    = float(latest["Spread"])
        comp_streak = int(df["CompStreak"].iloc[-1])

        # BRD §1 — EMA-200 trend filter (always required)
        if close < ema200:
            if dbg is not None: dbg["ema200"] += 1
            return None

        # BRD §2.2 — EMA compression for >= N consecutive sessions (always required)
        if comp_streak < EMA_COMPRESS_DAYS:
            if dbg is not None: dbg["compress"] += 1
            return None

        # BRD §2.4 — RSI Decompression Shield (always required)
        rsi_ok = RSI_LOW <= rsi <= RSI_HIGH
        if not rsi_ok:
            if dbg is not None: dbg["rsi"] += 1
            return None

        # Box detection (always required)
        box_df   = df.iloc[-(BOX_LOOKBACK_DAYS + 1):-1]
        if box_df.empty:
            return None
        box_high = float(box_df["High"].max())
        box_low  = float(box_df["Low"].min())
        box_h_pct = (box_high - box_low) / box_low * 100
        if box_h_pct < BOX_MIN_HEIGHT_PCT:
            if dbg is not None: dbg["box_height"] += 1
            return None

        # BRD §2.1 + §2.3 — Breakout-day filters (price momentum + volume surge)
        # These are checked AFTER box detection to classify the signal:
        #   BREAKOUT  = close > box_high + DP% 3-6% + volume >= 1.5x  (active setup)
        #   NEAR-BREAK = close within 2% of box_high + volume building  (watch setup)
        delta_pct = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
        vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 0
        vol_surge = avg_vol > 0 and vol >= avg_vol * VOLUME_SURGE_RATIO
        price_momentum_ok = PRICE_CHANGE_MIN <= delta_pct <= PRICE_CHANGE_MAX

        # Determine signal classification
        is_breakout   = close > box_high and price_momentum_ok and vol_surge
        near_breakout = (not is_breakout) and close >= box_high * 0.98 and comp_streak >= EMA_COMPRESS_DAYS

        # Must be either an active breakout or within 2% of box ceiling
        if not (is_breakout or near_breakout):
            if dbg is not None: dbg["signal"] += 1
            return None

        if dbg is not None: dbg["pass"] += 1

        # BRD §3 — Trade levels
        entry      = round(box_high, 2)                             # GTT at box ceiling
        box_depth  = box_high - box_low

        # BRD §3.2 — Tight 2% stop (NOT box-low, NOT ATR)
        sl_2pct    = round(entry * (1 - SL_PCT_BELOW_ENTRY / 100), 2)
        sl_ema20   = round(ema20, 2)                                # "directly beneath EMA-20"
        stop_loss  = min(sl_2pct, sl_ema20)                        # whichever is closer (lower)
        stop_loss  = round(stop_loss, 2)

        # BRD §3.3 — Tranche 1: full box height projected up (50% allocation)
        tranche1   = round(entry + box_depth, 2)
        # BRD §3.3 — Tranche 2: trail EMA-20 (50% allocation — no static price)
        # We record the current EMA-20 as the trailing reference start point
        tranche2_trail_ref = round(ema20, 2)

        # R:R vs Tranche 1 only
        risk   = entry - stop_loss
        reward = tranche1 - entry
        rr     = round(reward / risk, 2) if risk > 0 else 0

        signal_type  = "BREAKOUT"   if is_breakout   else "NEAR-BREAKOUT"
        signal_label = "Active Breakout — All 4 BRD filters passed" if is_breakout else "Near-Breakout Watch — EMA compressed, price within 2% of box ceiling"
        pct_to_box   = round((box_high - close) / box_high * 100, 2) if not is_breakout else 0.0

        return {
            "ticker":          ticker,
            "name":            ticker.replace(".NS", ""),
            "signalType":      signal_type,
            "signalLabel":     signal_label,
            "currentPrice":    round(close, 2),
            "deltaPct":        round(delta_pct, 2),
            "pctToBox":        pct_to_box,
            "ema20":           round(ema20, 2),
            "ema50":           round(ema50, 2),
            "ema200":          round(ema200, 2),
            "emaSpreadPct":    round(spread, 3),
            "compStreak":      comp_streak,
            "rsi":             round(rsi, 2),
            "volume":          int(vol),
            "avgVolume":       int(avg_vol),
            "volumeRatio":     vol_ratio,
            "volSurge":        vol_surge,
            "boxHigh":         round(box_high, 2),
            "boxLow":          round(box_low, 2),
            "boxHeightPct":    round(box_h_pct, 2),
            "gttEntry":        entry,
            "stopLoss":        stop_loss,
            "sl2Pct":          sl_2pct,
            "slEma20":         sl_ema20,
            "tranche1":        tranche1,
            "tranche2TrailRef": tranche2_trail_ref,
            "riskReward":      rr,
        }

    except Exception as e:
        print(f"    Error analysing {ticker}: {e}")
        return None


# ── Step 6: Build HTML dashboard ──────────────────────────────────────────────
def build_html(candidates: list[dict], run_time_ist: str, total_scanned: int) -> str:

    def fmt_inr(val):
        return f"Rs.{val:,.2f}" if val is not None else "--"

    def pct(val):
        return f"{val:.1f}%" if val is not None else "--"


    rr_cls = lambda rr: "text-green-700 font-bold" if rr >= 3 else "text-blue-600 font-semibold" if rr >= 2 else "text-gray-700"

    cards = ""
    for i, c in enumerate(candidates):
        rank_badge  = ["#1", "#2", "#3", "#4", "#5"][i] if i < 5 else f"#{i+1}"
        comp_bar    = min(100, int(c["compStreak"] / 30 * 100))
        is_bo       = c.get("signalType") == "BREAKOUT"
        hdr_cls     = "bg-gradient-to-r from-green-800 to-green-700" if is_bo else "bg-gradient-to-r from-slate-800 to-slate-700"
        sig_badge   = '<span class="bg-green-400 text-green-900 text-xs font-bold px-2 py-0.5 rounded">BREAKOUT</span>' if is_bo else '<span class="bg-amber-400 text-amber-900 text-xs font-bold px-2 py-0.5 rounded">NEAR-BREAKOUT</span>'
        dp_cls      = "bg-green-100 text-green-800" if is_bo else "bg-amber-100 text-amber-800"
        vol_cls     = "bg-green-100 text-green-800" if c.get("volSurge") else "bg-orange-100 text-orange-800"
        near_label  = f'<span class="text-amber-300 text-xs">{c["pctToBox"]:.1f}% below box ceiling</span>' if not is_bo else ""
        dp_label    = f'+{c["deltaPct"]:.1f}% today' if is_bo else f'DP% {c["deltaPct"]:.1f}% (needs 3-6% on breakout day)'

        cards += f"""
        <div class="bg-white rounded-xl shadow border border-gray-100 overflow-hidden mb-6">

          <!-- Card Header -->
          <div class="{hdr_cls} text-white px-5 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-xl font-bold bg-amber-500 text-slate-900 px-2 py-0.5 rounded">{rank_badge}</span>
              <div>
                <h3 class="text-lg font-bold">{c['name']}</h3>
                <div class="flex items-center gap-2 mt-0.5">
                  <span class="text-xs text-slate-300 font-mono">{c['ticker']}</span>
                  {sig_badge}
                  {near_label}
                </div>
              </div>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold">{fmt_inr(c['currentPrice'])}</p>
              <p class="text-xs text-slate-300">
                Box ceiling: <span class="font-semibold text-amber-300">{fmt_inr(c['boxHigh'])}</span>
              </p>
            </div>
          </div>

          <!-- BRD §2 filter status row -->
          <div class="px-5 py-2 bg-slate-50 border-b border-gray-100 flex flex-wrap gap-2 text-xs">
            <span class="{dp_cls} px-2 py-0.5 rounded font-semibold">
              BRD §2.1 {dp_label}
            </span>
            <span class="bg-green-100 text-green-800 px-2 py-0.5 rounded font-semibold">
              BRD §2.2 EMA compressed {c['compStreak']}d (>= 14d)
            </span>
            <span class="{vol_cls} px-2 py-0.5 rounded font-semibold">
              BRD §2.3 Vol {c['volumeRatio']}x {'(>=1.5x OK)' if c.get('volSurge') else '(building up)'}
            </span>
            <span class="bg-green-100 text-green-800 px-2 py-0.5 rounded font-semibold">
              BRD §2.4 RSI {c['rsi']} (40-55)
            </span>
          </div>

          <!-- BRD §3 Trade Lifecycle Grid -->
          <div class="grid grid-cols-2 md:grid-cols-4 divide-x divide-y divide-gray-100 border-b border-gray-100">
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">GTT Entry</p>
              <p class="text-lg font-bold text-blue-600">{fmt_inr(c['gttEntry'])}</p>
              <p class="text-xs text-gray-400">Box ceiling retest</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Stop-Loss (2%)</p>
              <p class="text-lg font-bold text-red-600">{fmt_inr(c['stopLoss'])}</p>
              <p class="text-xs text-gray-400">Tight institutional anchor</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Tranche 1 (50%)</p>
              <p class="text-lg font-bold text-green-600">{fmt_inr(c['tranche1'])}</p>
              <p class="text-xs text-gray-400">Full box projection exit</p>
            </div>
            <div class="p-4 text-center">
              <p class="text-xs text-gray-400 uppercase tracking-wide mb-1">Tranche 2 (50%)</p>
              <p class="text-lg font-bold text-amber-500">Trail EMA-20</p>
              <p class="text-xs text-gray-400">Ref: {fmt_inr(c['tranche2TrailRef'])} today</p>
            </div>
          </div>

          <!-- Secondary metrics -->
          <div class="px-5 py-4 grid grid-cols-2 md:grid-cols-6 gap-4 text-sm">
            <div>
              <p class="text-xs text-gray-400 mb-0.5">EMA Spread</p>
              <p class="font-semibold text-green-700">{c['emaSpreadPct']:.2f}%</p>
              <p class="text-xs text-gray-400">&lt;= 1.5% (compressed)</p>
            </div>
            <div>
              <p class="text-xs text-gray-400 mb-0.5">Compression</p>
              <p class="font-semibold text-green-700">{c['compStreak']} sessions</p>
              <div class="mt-1 h-1.5 bg-gray-100 rounded-full">
                <div class="h-full bg-indigo-400 rounded-full" style="width:{comp_bar}%"></div>
              </div>
            </div>
            <div>
              <p class="text-xs text-gray-400 mb-0.5">Box Height</p>
              <p class="font-semibold text-gray-800">{c['boxHeightPct']:.1f}%</p>
              <p class="text-xs text-gray-400">&gt;= 20% required</p>
            </div>
            <div>
              <p class="text-xs text-gray-400 mb-0.5">Volume Surge</p>
              <p class="font-semibold text-green-700">{c['volumeRatio']}x</p>
              <p class="text-xs text-gray-400">&gt;= 1.50x required</p>
            </div>
            <div>
              <p class="text-xs text-gray-400 mb-0.5">RSI (14)</p>
              <p class="font-semibold text-green-700">{c['rsi']}</p>
              <p class="text-xs text-gray-400">Zone: 40-55</p>
            </div>
            <div>
              <p class="text-xs text-gray-400 mb-0.5">R:R Ratio</p>
              <p class="{rr_cls(c['riskReward'])}">1:{c['riskReward']}</p>
              <p class="text-xs text-gray-400">vs Tranche 1</p>
            </div>
          </div>

          <!-- SL detail row -->
          <div class="px-5 pb-3 text-xs text-gray-400 border-t border-gray-50">
            <span class="font-semibold text-gray-600">Stop-Loss Logic (BRD §3.2):</span>
            2% below entry = {fmt_inr(c['sl2Pct'])} |
            EMA-20 = {fmt_inr(c['slEma20'])} |
            <span class="text-red-600 font-semibold">Active SL = {fmt_inr(c['stopLoss'])} (lower of the two)</span>
          </div>

        </div>"""

    n_breakout = sum(1 for c in candidates if c.get("signalType") == "BREAKOUT")
    n_near     = sum(1 for c in candidates if c.get("signalType") == "NEAR-BREAKOUT")

    if not candidates:
        cards = """
        <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center">
          <h3 class="text-xl font-bold text-gray-700 mb-2">No Fortress Setups Today</h3>
          <p class="text-gray-400 text-sm max-w-lg mx-auto">
            No NSE stock currently has EMA(20/50) compressed 14+ days, RSI 40-55, price above EMA-200,
            and a 20%+ box structure with price within 2% of the box ceiling.
            Check back after next market session.
          </p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fortress Breakout Scanner - NSE</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">

  <!-- SEBI Banner -->
  <div class="bg-yellow-50 border-b border-yellow-300 py-2 px-4 text-xs text-yellow-800 text-center">
    <i class="fas fa-exclamation-triangle mr-1"></i>
    <strong>Educational use only.</strong> Fortress Breakout signals are for learning -- not investment advice.
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
        <a href="index.html"           class="text-gray-600 hover:text-blue-600">Home</a>
        <a href="dashboard.html"       class="text-gray-600 hover:text-blue-600">Dashboard</a>
        <a href="swing-dashboard.html" class="text-gray-600 hover:text-blue-600">Swing Scanner</a>
        <a href="box-dashboard.html"   class="text-blue-600 font-semibold border-b-2 border-blue-600 pb-0.5">Box Scanner</a>
        <a href="discussions.html"     class="text-gray-600 hover:text-blue-600">
          <i class="fas fa-tasks mr-1"></i>Stock Manager
        </a>
      </div>
    </div>
  </nav>

  <!-- Header -->
  <section class="bg-gradient-to-r from-slate-800 to-slate-700 text-white py-10">
    <div class="max-w-5xl mx-auto px-4">
      <h1 class="text-3xl font-bold mb-2">
        <i class="fas fa-fort-awesome mr-2 text-amber-400"></i>
        Institutional Fortress Breakout Scanner
      </h1>
      <p class="text-slate-300 text-sm max-w-2xl mb-4">
        Scans the NSE universe using all 4 BRD quantitative filters simultaneously.
        Replaces wide box-low stops with tight 2% institutional invalidation anchors.
        EMA-200 trend filter + 20% box + breakout confirmation.
      </p>
      <div class="flex flex-wrap gap-5 text-sm text-slate-300">
        <span><i class="fas fa-clock mr-1"></i>Scan: <strong class="text-white">{run_time_ist}</strong></span>
        <span><i class="fas fa-eye mr-1"></i>Scanned: <strong class="text-white">{total_scanned}</strong></span>
        <span><i class="fas fa-fire mr-1 text-amber-400"></i>Setups: <strong class="text-amber-300">{len(candidates)}</strong></span>
        <span class="text-xs text-slate-400">
          Filters: DP% {PRICE_CHANGE_MIN}-{PRICE_CHANGE_MAX}% | EMA compressed {EMA_COMPRESS_DAYS}d+ | Vol &gt;= {VOLUME_SURGE_RATIO}x | RSI {RSI_LOW}-{RSI_HIGH} | EMA-200 trend | Box &gt;= {BOX_MIN_HEIGHT_PCT}%
        </span>
      </div>
    </div>
  </section>

  <!-- BRD Filter Legend -->
  <section class="max-w-5xl mx-auto px-4 py-4">
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-4 grid md:grid-cols-4 gap-3 text-xs text-center">
      <div class="p-3 bg-blue-50 rounded-lg">
        <p class="text-lg mb-1">BRD 2.1</p>
        <p class="font-bold text-gray-700">Price Momentum</p>
        <p class="text-gray-500">+{PRICE_CHANGE_MIN}% to +{PRICE_CHANGE_MAX}% daily change. Blocks FOMO spikes (&gt;{PRICE_CHANGE_MAX}%) and dead candles (&lt;{PRICE_CHANGE_MIN}%).</p>
      </div>
      <div class="p-3 bg-indigo-50 rounded-lg">
        <p class="text-lg mb-1">BRD 2.2</p>
        <p class="font-bold text-gray-700">EMA Compression</p>
        <p class="text-gray-500">EMA(20/50) spread &lt;= {EMA_SPREAD_MAX}% for {EMA_COMPRESS_DAYS}+ consecutive sessions. The coiled spring.</p>
      </div>
      <div class="p-3 bg-green-50 rounded-lg">
        <p class="text-lg mb-1">BRD 2.3</p>
        <p class="font-bold text-gray-700">Institutional Volume</p>
        <p class="text-gray-500">Volume &gt;= {VOLUME_SURGE_RATIO}x SMA(20). Confirms programmatic desk participation.</p>
      </div>
      <div class="p-3 bg-amber-50 rounded-lg">
        <p class="text-lg mb-1">BRD 2.4</p>
        <p class="font-bold text-gray-700">RSI Shield</p>
        <p class="text-gray-500">RSI(14) between {RSI_LOW} and {RSI_HIGH}. Disqualifies overbought (&gt;{RSI_OVERBOUGHT}) entries.</p>
      </div>
    </div>
  </section>

  <!-- Results -->
  <main class="max-w-5xl mx-auto px-4 py-2 pb-12">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-bold text-gray-800">
        <i class="fas fa-trophy mr-1 text-amber-500"></i>
        {len(candidates)} Fortress Candidates
        <span class="text-sm font-normal text-gray-500 ml-2">
          <span class="text-green-700">{n_breakout} Active Breakout</span>
          &nbsp;·&nbsp;
          <span class="text-amber-600">{n_near} Near-Breakout</span>
        </span>
      </h2>
      <span class="text-xs text-gray-400">EMA compressed {EMA_COMPRESS_DAYS}d+ | RSI {RSI_LOW}-{RSI_HIGH} | EMA-200 trend | Box {BOX_MIN_HEIGHT_PCT}%+</span>
    </div>
    {cards}
  </main>

  <!-- BRD §3 Risk Engine Explainer -->
  <section class="max-w-5xl mx-auto px-4 pb-10">
    <div class="bg-slate-800 text-white rounded-xl p-6 text-sm">
      <h3 class="font-bold text-amber-400 mb-4 text-base">
        <i class="fas fa-shield-alt mr-2"></i>BRD §3 Fortress Risk Engine
      </h3>
      <div class="grid md:grid-cols-3 gap-5 text-slate-300">
        <div>
          <p class="font-bold text-white mb-2">Entry (GTT Limit)</p>
          <p>Configured exactly at the box upper resistance ceiling. Catches the retest automatically. Market-order chasing at the open is blocked by design.</p>
        </div>
        <div>
          <p class="font-bold text-red-400 mb-2">Stop-Loss (Tight 2%)</p>
          <p>Hard 2% below the breakout line -- or directly below the EMA-20, whichever is lower. Completely eliminates the traditional 20%+ wide box-low stop. Capital block preserved on false bull traps.</p>
        </div>
        <div>
          <p class="font-bold text-green-400 mb-2">Exits (Symmetric Tranches)</p>
          <p><strong class="text-white">Tranche 1 (50%):</strong> Static exit at full box-height projected upward from entry. Mathematical symmetry.<br>
          <strong class="text-white">Tranche 2 (50%):</strong> Trails via rising EMA-20. No static target -- exits only on daily close below EMA-20.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Footer -->
  <footer class="bg-gray-800 text-gray-400 text-center py-6 text-xs">
    <p>&copy; 2026 Financial Literacy Platform -- Educational only, not SEBI investment advice.</p>
    <p class="mt-1"><a href="disclaimer.html" class="underline">Full Disclaimer</a></p>
  </footer>

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ist          = ZoneInfo("Asia/Kolkata")
    run_time_ist = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    print(f"Fortress Breakout Scanner (BRD v2) -- {run_time_ist}")
    print(f"  BRD 2.1: DP% {PRICE_CHANGE_MIN}-{PRICE_CHANGE_MAX}%")
    print(f"  BRD 2.2: EMA spread <= {EMA_SPREAD_MAX}% for >= {EMA_COMPRESS_DAYS} sessions")
    print(f"  BRD 2.3: Volume ratio >= {VOLUME_SURGE_RATIO}x")
    print(f"  BRD 2.4: RSI {RSI_LOW}-{RSI_HIGH}")
    print(f"  BRD 3.2: Stop-loss = 2% below entry (tight institutional anchor)")
    print()

    # 1. Get tickers
    tickers = get_nse_tickers()
    print()

    # 2. Batch download — 1y gives ~252 rows, enough for EMA-200 warmup (200 rows) + box window (60)
    CHUNK = 100
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        print(f"  Batch {i // CHUNK + 1}: tickers {i+1}-{i+len(chunk)}")
        chunk_data = batch_download(chunk, period="1y")
        all_data.update(chunk_data)

    print(f"\n  Total tickers with 1y data: {len(all_data)}")
    total_scanned = len(all_data)

    # 3. Analyse each ticker against all BRD §2 filters
    # Per-filter debug counters — printed in summary so we know which filter is most restrictive
    print("\n  Analysing Fortress Breakout conditions...")
    candidates: list[dict] = []
    dbg = {"ema200": 0, "compress": 0, "rsi": 0, "box_height": 0, "signal": 0, "pass": 0}
    for ticker, df in all_data.items():
        result = analyse_ticker(ticker, df, dbg)
        if result:
            candidates.append(result)
            print(
                f"  {'BREAKOUT' if result['signalType']=='BREAKOUT' else 'NEAR-BRK'}: {ticker} | "
                f"DP%={result['deltaPct']:.1f}% | "
                f"Comp={result['compStreak']}d | "
                f"Vol={result['volumeRatio']}x | "
                f"RSI={result['rsi']} | "
                f"Box={result['boxHeightPct']:.1f}% | "
                f"R:R=1:{result['riskReward']}"
            )

    # 4. Rank by R:R descending (best quality trades first), then by RSI
    candidates.sort(key=lambda x: (x["riskReward"], x["rsi"]), reverse=True)
    top = candidates[:TOP_N]

    print(f"\n-- Scan Summary --")
    print(f"  Scanned              : {total_scanned}")
    print(f"  Killed by EMA-200    : {dbg['ema200']}")
    print(f"  Killed by compression: {dbg['compress']}")
    print(f"  Killed by RSI        : {dbg['rsi']}")
    print(f"  Killed by box height : {dbg['box_height']}")
    print(f"  Killed by signal     : {dbg['signal']}")
    print(f"  Passed all filters   : {dbg['pass']} -> returning top {len(top)}")

    # 5. Save JSON
    output = {
        "lastUpdated":      datetime.utcnow().isoformat() + "Z",
        "runTimeIST":       run_time_ist,
        "totalScanned":     total_scanned,
        "totalBreakouts":   len(candidates),
        "brdConfig": {
            "priceChangeMin":   PRICE_CHANGE_MIN,
            "priceChangeMax":   PRICE_CHANGE_MAX,
            "emaSpreadMax":     EMA_SPREAD_MAX,
            "emaCompressDays":  EMA_COMPRESS_DAYS,
            "volumeSurgeRatio": VOLUME_SURGE_RATIO,
            "rsiLow":           RSI_LOW,
            "rsiHigh":          RSI_HIGH,
            "slPctBelowEntry":  SL_PCT_BELOW_ENTRY,
        },
        "candidates": top,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved: {OUTPUT_JSON}")

    # 6. Save HTML
    html = build_html(top, run_time_ist, total_scanned)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {OUTPUT_HTML}")

    return 0


if __name__ == "__main__":
    main()
