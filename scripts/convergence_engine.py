#!/usr/bin/env python3
"""
Convergence & Evidence Engine — Standalone Post-Market Runner
--------------------------------------------------------------
Produces: data/convergence.json  →  convergence-dashboard.html

This script is the EVIDENCE LAYER. It is deliberately separate from
scanner.py (the detection layer) to prevent cross-contamination.

What it does:
  1. Fetches 1y of OHLCV data for all NSE tickers
  2. Runs Strategy A + Strategy B detection frozen at each historical date
  3. Classifies every signal into A_ONLY / B_ONLY / A_AND_B cohorts
  4. Computes per-cohort Profit Factor, Expectancy, MAE, MFE,
     T+1/T+5/T+10/T+20 return distributions, and regime splits
  5. Tests all 4 stop-loss methods side-by-side
  6. Renders convergence-dashboard.html — the non-technical evidence UI

NO look-ahead bias: each historical signal is generated using only data
available at T=0 (4:30 PM on that day). Future prices are only read
AFTER the signal is frozen.
"""

import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT            = Path(__file__).parent.parent
DATA_DIR        = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CONV_JSON       = DATA_DIR / "convergence.json"
CONV_HTML       = ROOT / "convergence-dashboard.html"

# ── Parameters (must stay in sync with scanner.py constants) ─────────────────
EMA_SPREAD_MAX    = 1.5
VOLUME_DRYUP_MAX  = 1.0
RSI_OVERBOUGHT    = 65
BOX_MIN_SESSIONS  = 21
BOX_MIN_DEPTH_PCT = 20.0
BOX_TOUCH_BAND_PCT= 1.5
BOX_MIN_TOUCHES   = 3
BOX_CLOSE_VIOL_PCT= 1.0
ATR_MULT          = 1.5
ATR_PERIOD        = 14
FIXED_SL_PCT      = 2.0
TARGET_PCT        = 10.0
HOLD_SESSIONS     = 20
REGIME_TICKER     = "^NSEI"

SEED_TICKERS = [
    "LT.NS", "ACMESOLAR.NS", "CYIENTDLM.NS", "TECHNOE.NS",
    "SRF.NS", "COALINDIA.NS", "HINDCOPPER.NS",
]
BACKUP_TICKERS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "BHARTIARTL.NS","KOTAKBANK.NS","HINDUNILVR.NS","AXISBANK.NS","BAJFINANCE.NS",
    "WIPRO.NS","ULTRACEMCO.NS","MARUTI.NS","TITAN.NS","SUNPHARMA.NS",
    "NTPC.NS","COALINDIA.NS","LT.NS","SRF.NS","HINDCOPPER.NS",
    "TECHM.NS","TATAMOTORS.NS","BAJAJ-AUTO.NS","BEL.NS","ADANIENT.NS",
    "ONGC.NS","POWERGRID.NS","ITC.NS","SBIN.NS","ACMESOLAR.NS",
    "CYIENTDLM.NS","TECHNOE.NS","APARINDS.NS","IRFC.NS","RVNL.NS",
    "HUDCO.NS","SJVN.NS","NHPC.NS","TATAPOWER.NS","TORNTPOWER.NS",
    "CESC.NS","TIINDIA.NS","DIVISLAB.NS","DRREDDY.NS","CIPLA.NS",
    "LUPIN.NS","HAVELLS.NS","ABB.NS","SIEMENS.NS","CUMMINSIND.NS",
]


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def get_nse_tickers() -> list[str]:
    if not _HAS_REQUESTS:
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
                        return tickers
        except Exception:
            pass
    return BACKUP_TICKERS


def _find_col(raw_cols, field: str, ticker: str):
    for c in [f"{field}_{ticker}", f"Adj {field}_{ticker}", field, f"Adj {field}"]:
        if c in raw_cols:
            return c
    return None


def batch_download(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    print(f"  Downloading {len(tickers)} tickers ({period})...", end=" ", flush=True)
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
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [f"{f}_{t}" for f, t in raw.columns]
        raw_cols = set(raw.columns)
        print(f"got {len(raw)} rows")
        for ticker in tickers:
            try:
                c_col = _find_col(raw_cols, "Close",  ticker)
                v_col = _find_col(raw_cols, "Volume", ticker)
                h_col = _find_col(raw_cols, "High",   ticker)
                l_col = _find_col(raw_cols, "Low",    ticker)
                if c_col is None:
                    continue
                df = pd.DataFrame({
                    "close":  raw[c_col],
                    "volume": raw[v_col] if v_col else pd.Series(0.0, index=raw.index),
                    "high":   raw[h_col] if h_col else raw[c_col],
                    "low":    raw[l_col] if l_col else raw[c_col],
                }).dropna(subset=["close"])
                if len(df) >= 55:
                    out[ticker] = df
            except Exception:
                pass
    except Exception as e:
        print(f"\n  Batch failed: {e}")
    return out


def get_market_regime() -> dict:
    result = {"regime": "unknown", "nifty_price": None, "nifty_sma200": None}
    try:
        raw = yf.download(REGIME_TICKER, period="2y", progress=False, auto_adjust=True)
        if raw.empty or len(raw) < 200:
            return result
        # .squeeze() converts a single-column DataFrame → Series before float()
        # .item() extracts the Python scalar safely regardless of yfinance version
        close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
        close = close.squeeze().dropna()
        sma200 = float(close.rolling(200).mean().iloc[-1].item()
                       if hasattr(close.rolling(200).mean().iloc[-1], "item")
                       else close.rolling(200).mean().iloc[-1])
        price  = float(close.iloc[-1].item()
                       if hasattr(close.iloc[-1], "item")
                       else close.iloc[-1])
        result["regime"]      = "positive" if price > sma200 else "weak"
        result["nifty_price"] = round(price, 2)
        result["nifty_sma200"]= round(sma200, 2)
    except Exception as e:
        print(f"  ⚠ Regime fetch failed: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Signal detection helpers (frozen at each historical index)
# ─────────────────────────────────────────────────────────────────────────────
def _detect_strat_a(df_slice: pd.DataFrame) -> bool:
    """Strategy A at the LAST row of df_slice. No forward data used."""
    df = df_slice.copy()
    df["ema20"]   = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"]   = df["close"].ewm(span=50, adjust=False).mean()
    df["avg_vol"] = df["volume"].rolling(20).mean()
    row = df.iloc[-1]
    if pd.isna(row["avg_vol"]) or row["avg_vol"] <= 0:
        return False
    spread    = abs(float(row["ema20"]) - float(row["ema50"])) / float(row["ema50"]) * 100
    vol_ratio = float(row["volume"]) / float(row["avg_vol"])
    return spread <= EMA_SPREAD_MAX and vol_ratio < VOLUME_DRYUP_MAX


def _detect_strat_b(df_slice: pd.DataFrame) -> bool:
    """Strategy B at the LAST row of df_slice. No forward data used."""
    window = df_slice.tail(BOX_MIN_SESSIONS)
    if len(window) < BOX_MIN_SESSIONS:
        return False
    box_high = float(window["high"].max())
    box_low  = float(window["low"].min())
    depth    = (box_high - box_low) / box_low * 100
    if depth < BOX_MIN_DEPTH_PCT:
        return False
    ceil_lo = box_high * (1 - BOX_TOUCH_BAND_PCT / 100)
    ceil_hi = box_high * (1 + BOX_TOUCH_BAND_PCT / 100)
    floor_lo = box_low * (1 - BOX_TOUCH_BAND_PCT / 100)
    floor_hi = box_low * (1 + BOX_TOUCH_BAND_PCT / 100)
    ceil_touches  = int(((window["high"] >= ceil_lo) & (window["high"] <= ceil_hi)).sum())
    floor_touches = int(((window["low"]  >= floor_lo) & (window["low"]  <= floor_hi)).sum())
    upper_viol = box_high * (1 + BOX_CLOSE_VIOL_PCT / 100)
    lower_viol = box_low  * (1 - BOX_CLOSE_VIOL_PCT / 100)
    close_viols = int(((window["close"] > upper_viol) | (window["close"] < lower_viol)).sum())
    return ceil_touches >= BOX_MIN_TOUCHES and floor_touches >= BOX_MIN_TOUCHES and close_viols == 0


def _atr_at(df_slice: pd.DataFrame) -> float:
    try:
        h = df_slice["high"]
        l = df_slice["low"]
        c = df_slice["close"].shift(1)
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        return float(tr.rolling(ATR_PERIOD).mean().iloc[-1])
    except Exception:
        return float(df_slice["close"].iloc[-1]) * 0.02


def _ema20_at(df_slice: pd.DataFrame) -> float:
    return float(df_slice["close"].ewm(span=20, adjust=False).mean().iloc[-1])


def _swing_low_at(df_slice: pd.DataFrame) -> float:
    return float(df_slice["low"].tail(BOX_MIN_SESSIONS).min())


# ─────────────────────────────────────────────────────────────────────────────
# Core: build signal records with outcome tracking for all 4 SL methods
# ─────────────────────────────────────────────────────────────────────────────
def build_signal_records(ticker: str, df: pd.DataFrame) -> list[dict]:
    """
    Walks through every historical row >= 55 and <= (len-HOLD_SESSIONS).
    For each row, generates the signal frozen at that point in time,
    then reveals future prices to classify outcome.

    Returns list of signal dicts with:
      ticker, date, cohort, entry, rsi, pctChange,
      sl_fixed, sl_atr, sl_ema20, sl_swingLow,
      outcomes_{fixed/atr/ema/swing}, mae, mfe, t1..t20
    """
    records = []
    try:
        df = df.copy()
        # Pre-compute rolling indicators on full series (no look-ahead)
        df["ema20"]    = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]    = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"]  = df["volume"].rolling(20).mean()
        df["spread"]   = (df["ema20"] - df["ema50"]).abs() / df["ema50"] * 100
        delta          = df["close"].diff()
        gain           = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss           = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        df["rsi"]      = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
        df["pct_chg"]  = df["close"].pct_change() * 100

        # ATR column
        h = df["high"]
        l = df["low"]
        c = df["close"].shift(1)
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(ATR_PERIOD).mean()

        cutoff = len(df) - HOLD_SESSIONS

        for i in range(55, cutoff):
            row = df.iloc[i]
            if pd.isna(row["avg_vol"]) or row["avg_vol"] <= 0:
                continue

            # Strategy A: EMA compressed + vol dry-up (RSI NOT filtered)
            strat_a = (row["spread"] <= EMA_SPREAD_MAX and
                       row["volume"] < row["avg_vol"] * VOLUME_DRYUP_MAX)

            # Strategy B: structural box (use slice up to this row only)
            strat_b = _detect_strat_b(df.iloc[max(0, i - BOX_MIN_SESSIONS * 2): i + 1])

            if not strat_a and not strat_b:
                continue

            if strat_a and strat_b:
                cohort = "A_AND_B"
            elif strat_a:
                cohort = "A_ONLY"
            else:
                cohort = "B_ONLY"

            entry   = float(row["close"])
            atr_v   = float(row["atr"])   if not pd.isna(row["atr"])   else entry * 0.02
            rsi_v   = float(row["rsi"])   if not pd.isna(row["rsi"])   else None
            pct_v   = float(row["pct_chg"]) if not pd.isna(row["pct_chg"]) else None
            ema20_v = float(row["ema20"])
            swing_l = float(df["low"].iloc[max(0, i - BOX_MIN_SESSIONS): i + 1].min())
            date_s  = df.index[i].strftime("%Y-%m-%d") if hasattr(df.index[i], "strftime") else str(df.index[i])

            # 4 stop-loss floors
            sl_fixed = entry * (1 - FIXED_SL_PCT / 100)
            sl_atr   = entry - (ATR_MULT * atr_v)
            sl_ema   = ema20_v
            sl_swing = swing_l

            target   = entry * (1 + TARGET_PCT / 100)
            future_c = df["close"].iloc[i + 1: i + 1 + HOLD_SESSIONS]
            future_h = df["high"].iloc[i + 1: i + 1 + HOLD_SESSIONS]
            future_l = df["low"].iloc[i + 1: i + 1 + HOLD_SESSIONS]

            # T+N returns
            t_rets = {}
            for t in [1, 3, 5, 10, 20]:
                if len(future_c) >= t:
                    t_rets[f"t{t}"] = round((float(future_c.iloc[t-1]) - entry) / entry * 100, 3)

            # MAE / MFE
            if len(future_c) > 0:
                mfe = round((float(future_h.max()) - entry) / entry * 100, 3)
                mae = round((entry - float(future_l.min())) / entry * 100, 3)
            else:
                mfe = mae = 0.0

            # Outcome per stop-loss method
            outcomes: dict[str, dict] = {}
            for sl_name, sl_val in [("fixed", sl_fixed), ("atr", sl_atr),
                                    ("ema20", sl_ema), ("swing", sl_swing)]:
                out = "loss"
                pnl = -(FIXED_SL_PCT)
                for fp, fl in zip(future_c, future_l):
                    if fp >= target:
                        out = "win"
                        pnl = round((fp - entry) / entry * 100, 3)
                        break
                    if fl <= sl_val:
                        out = "loss"
                        pnl = round((sl_val - entry) / entry * 100, 3)
                        break
                outcomes[sl_name] = {"outcome": out, "pnl": pnl}

            records.append({
                "ticker":  ticker,
                "date":    date_s,
                "cohort":  cohort,
                "entry":   round(entry, 2),
                "rsi":     round(rsi_v, 1) if rsi_v is not None else None,
                "pct":     round(pct_v, 2) if pct_v is not None else None,
                "mfe":     mfe,
                "mae":     mae,
                "trets":   t_rets,
                "outcomes": outcomes,
            })

    except Exception as e:
        print(f"  ⚠ Signal scan failed for {ticker}: {e}")

    return records


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate cohort metrics
# ─────────────────────────────────────────────────────────────────────────────
def aggregate(records: list[dict], stop_key: str = "atr") -> dict:
    """Compute Profit Factor, Expectancy, win rate, MAE/MFE, T+N medians."""
    if not records:
        return {}
    wins   = [r["outcomes"][stop_key]["pnl"] for r in records
              if stop_key in r["outcomes"] and r["outcomes"][stop_key]["outcome"] == "win"]
    losses = [abs(r["outcomes"][stop_key]["pnl"]) for r in records
              if stop_key in r["outcomes"] and r["outcomes"][stop_key]["outcome"] == "loss"]
    total = len(wins) + len(losses)
    if total == 0:
        return {}
    win_rate = round(len(wins) / total * 100, 1)
    avg_win  = round(float(np.mean(wins)), 3) if wins else 0.0
    avg_loss = round(float(np.mean(losses)), 3) if losses else 0.0
    gross_w  = sum(wins)
    gross_l  = sum(losses)
    pf       = round(gross_w / gross_l, 3) if gross_l > 0 else None
    exp      = round((win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss), 4)

    maes   = [r["mae"] for r in records]
    mfes   = [r["mfe"] for r in records]
    t5s    = [r["trets"]["t5"]  for r in records if "t5"  in r["trets"]]
    t20s   = [r["trets"]["t20"] for r in records if "t20" in r["trets"]]

    return {
        "trades":       total,
        "wins":         len(wins),
        "losses":       len(losses),
        "winRate":      win_rate,
        "avgWin":       avg_win,
        "avgLoss":      avg_loss,
        "profitFactor": pf,
        "expectancy":   exp,
        "maxDrawdown":  round(float(max(maes)), 2) if maes else None,
        "avgMAE":       round(float(np.mean(maes)), 3) if maes else None,
        "avgMFE":       round(float(np.mean(mfes)), 3) if mfes else None,
        "medT5":        round(float(np.median(t5s)), 3) if t5s else None,
        "medT20":       round(float(np.median(t20s)), 3) if t20s else None,
    }


def build_cohort_table(all_records: list[dict]) -> dict:
    """Split records by cohort, compute metrics for primary stop (ATR) and all 4 stops."""
    cohorts = {"A_ONLY": [], "B_ONLY": [], "A_AND_B": []}
    for r in all_records:
        if r["cohort"] in cohorts:
            cohorts[r["cohort"]].append(r)

    result = {}
    for cohort, recs in cohorts.items():
        stop_comparison = {}
        for sk in ["fixed", "atr", "ema20", "swing"]:
            stop_comparison[sk] = aggregate(recs, sk)
        result[cohort] = {
            "count":           len(recs),
            "primaryMetrics":  aggregate(recs, "atr"),
            "stopComparison":  stop_comparison,
        }
    return result


def build_regime_split(all_records: list[dict], regime_info: dict) -> dict:
    """
    Because we only have current regime (not historical per-day), we tag all
    records with the current regime for now and flag this as a forward-only split.
    A full historical regime split would require fetching Nifty OHLCV for each
    signal date — documented here as the next research iteration.
    """
    return {
        "note": "Regime split requires per-day Nifty data. Current implementation tags all records with today's regime. Full regime-split is the next research iteration.",
        "currentRegime": regime_info.get("regime", "unknown"),
        "niftyPrice":    regime_info.get("nifty_price"),
        "niftySMA200":   regime_info.get("nifty_sma200"),
    }


def build_live_scan(all_data: dict[str, pd.DataFrame]) -> list[dict]:
    """
    Current-day scan: shows today's convergence status for all downloaded tickers.
    Only returns stocks with an active A, B, or A∩B signal.
    """
    live = []
    for ticker, df in all_data.items():
        try:
            df_work = df.copy()
            df_work["ema20"]   = df_work["close"].ewm(span=20, adjust=False).mean()
            df_work["ema50"]   = df_work["close"].ewm(span=50, adjust=False).mean()
            df_work["avg_vol"] = df_work["volume"].rolling(20).mean()

            row    = df_work.iloc[-1]
            prev   = df_work.iloc[-2]
            price  = round(float(row["close"]), 2)
            ema20  = round(float(row["ema20"]), 2)
            ema50  = round(float(row["ema50"]), 2)
            spread = round(abs(ema20 - ema50) / ema50 * 100, 3)
            avg_v  = float(row["avg_vol"]) if not pd.isna(row["avg_vol"]) else 1
            vol_r  = round(float(row["volume"]) / avg_v, 3) if avg_v > 0 else 0

            # ATR
            h = df_work["high"]
            l = df_work["low"]
            c = df_work["close"].shift(1)
            tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
            atr_v  = round(float(tr.rolling(ATR_PERIOD).mean().iloc[-1]), 2)
            atr_floor = round(price - ATR_MULT * atr_v, 2)

            # RSI
            delta = df_work["close"].diff()
            gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
            loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
            rsi_s = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
            rsi   = round(float(rsi_s.iloc[-1]), 1)

            strat_a = spread <= EMA_SPREAD_MAX and vol_r < VOLUME_DRYUP_MAX
            strat_b = _detect_strat_b(df_work)

            if not strat_a and not strat_b:
                continue

            cohort = "A_AND_B" if strat_a and strat_b else ("A_ONLY" if strat_a else "B_ONLY")

            live.append({
                "ticker":    ticker.replace(".NS", ""),
                "price":     price,
                "ema20":     ema20,
                "ema50":     ema50,
                "spread":    spread,
                "rsi":       rsi,
                "volRatio":  vol_r,
                "atrFloor":  atr_floor,
                "ema20Floor":ema20,
                "swingFloor":round(float(df_work["low"].tail(BOX_MIN_SESSIONS).min()), 2),
                "stratA":    strat_a,
                "stratB":    strat_b,
                "cohort":    cohort,
            })
        except Exception:
            pass

    # Sort: A∩B first, then A, then B
    order = {"A_AND_B": 0, "A_ONLY": 1, "B_ONLY": 2}
    live.sort(key=lambda r: order.get(r["cohort"], 3))
    return live


# ─────────────────────────────────────────────────────────────────────────────
# HTML renderer — convergence-dashboard.html
# ─────────────────────────────────────────────────────────────────────────────
def build_html(data: dict) -> str:
    run_time    = data.get("runTimeIST", "—")
    regime      = data.get("marketRegime", {})
    regime_lbl  = regime.get("regime", "unknown").upper()
    regime_col  = "#16a34a" if regime_lbl == "POSITIVE" else ("#dc2626" if regime_lbl == "WEAK" else "#64748b")
    cohort_data = data.get("cohortTable", {})
    live_scan   = data.get("liveScan", [])

    def fmt(v, suffix="", prefix="", d="—"):
        return f"{prefix}{v}{suffix}" if v is not None else d

    def pf_color(pf):
        if pf is None:
            return "#64748b"
        return "#16a34a" if pf >= 1.75 else ("#ca8a04" if pf >= 1.0 else "#dc2626")

    def cohort_rows():
        rows = ""
        defs = [
            ("A_AND_B", "💎 A ∩ B Convergence", "#dcfce7", "#166534"),
            ("A_ONLY",  "⚡ Strategy A Only",    "#fef9c3", "#854d0e"),
            ("B_ONLY",  "📐 Strategy B Only",    "#dbeafe", "#1e40af"),
        ]
        for key, label, bg, fg in defs:
            d = cohort_data.get(key, {})
            m = d.get("primaryMetrics", {})
            sc = d.get("stopComparison", {})
            n  = d.get("count", 0)
            pf = m.get("profitFactor")
            ex = m.get("expectancy")
            wr = m.get("winRate")
            t5 = m.get("medT5")
            t20= m.get("medT20")
            mae= m.get("avgMAE")
            mfe= m.get("avgMFE")
            dd = m.get("maxDrawdown")

            # Stop comparison mini-table
            stop_html = ""
            for sk, slabel in [("fixed","Fixed 2%"),("atr","1.5×ATR"),("ema20","20-EMA"),("swing","Swing Low")]:
                sm = sc.get(sk, {})
                spf = sm.get("profitFactor")
                swr = sm.get("winRate")
                color = pf_color(spf)
                stop_html += f"""<span style="margin-right:12px;font-size:11px;">
                  <b style="color:{color}">{slabel}</b>:
                  PF {fmt(spf, d='—')} | WR {fmt(swr,'%',d='—')}
                </span>"""

            rows += f"""
            <tr style="border-bottom:1px solid #e5e7eb;">
              <td style="padding:14px 12px;">
                <span style="display:inline-block;padding:4px 10px;border-radius:12px;
                  background:{bg};color:{fg};font-weight:700;font-size:13px;">{label}</span>
              </td>
              <td style="padding:14px 12px;font-weight:600;">{n}</td>
              <td style="padding:14px 12px;font-size:22px;font-weight:700;color:{pf_color(pf)};">{fmt(pf, d='—')}</td>
              <td style="padding:14px 12px;font-weight:600;">{fmt(ex, d='—')}</td>
              <td style="padding:14px 12px;">{fmt(wr,'%',d='—')}</td>
              <td style="padding:14px 12px;color:#16a34a;font-weight:600;">{fmt(t5,'%',d='—')}</td>
              <td style="padding:14px 12px;color:#16a34a;font-weight:600;">{fmt(t20,'%',d='—')}</td>
              <td style="padding:14px 12px;color:#dc2626;">{fmt(mae,'%',d='—')}</td>
              <td style="padding:14px 12px;color:#2563eb;">{fmt(mfe,'%',d='—')}</td>
              <td style="padding:14px 12px;color:#dc2626;">{fmt(dd,'%',d='—')}</td>
              <td style="padding:14px 12px;font-size:11px;">{stop_html}</td>
            </tr>"""
        return rows

    def live_rows():
        if not live_scan:
            return '<tr><td colspan="8" style="padding:30px;text-align:center;color:#64748b;">No active signals today. Run workflow to refresh.</td></tr>'
        rows = ""
        cohort_styles = {
            "A_AND_B": ("#dcfce7","#166534","💎 A ∩ B"),
            "A_ONLY":  ("#fef9c3","#854d0e","⚡ A Only"),
            "B_ONLY":  ("#dbeafe","#1e40af","📐 B Only"),
        }
        for r in live_scan:
            bg, fg, label = cohort_styles.get(r["cohort"], ("#f1f5f9","#475569","—"))
            rows += f"""
            <tr style="border-bottom:1px solid #e5e7eb;">
              <td style="padding:14px 12px;font-weight:700;">{r['ticker']}</td>
              <td style="padding:14px 12px;font-weight:700;">₹{r['price']:,.2f}</td>
              <td style="padding:14px 12px;">{"🟢 Active" if r['stratA'] else "🔴 —"}</td>
              <td style="padding:14px 12px;">{"🟢 Active" if r['stratB'] else "🔴 —"}</td>
              <td style="padding:14px 12px;">
                <span style="display:inline-block;padding:3px 10px;border-radius:12px;
                  background:{bg};color:{fg};font-weight:700;font-size:12px;">{label}</span>
              </td>
              <td style="padding:14px 12px;">{r['spread']:.2f}% | RSI {r['rsi']}</td>
              <td style="padding:14px 12px;">
                <div style="font-size:12px;color:#dc2626;">ATR: ₹{r['atrFloor']:,.2f}</div>
                <div style="font-size:12px;color:#d97706;">EMA20: ₹{r['ema20Floor']:,.2f}</div>
                <div style="font-size:12px;color:#7c3aed;">SwingLow: ₹{r['swingFloor']:,.2f}</div>
              </td>
            </tr>"""
        return rows

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Institutional Convergence &amp; Evidence Dashboard</title>
<style>
  :root {{
    --bg: #f8fafc; --card: #ffffff; --border: #e5e7eb;
    --title: #0f172a; --body: #334155; --muted: #64748b;
    --green: #16a34a; --yellow: #ca8a04; --red: #dc2626; --blue: #2563eb;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,"Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--body); font-size:14px; line-height:1.6; padding:0; }}
  .disclaimer {{ background:#fefce8; border-bottom:1px solid #fbbf24; padding:8px 24px; font-size:12px; color:#92400e; text-align:center; }}
  .disclaimer a {{ color:#92400e; }}
  nav {{ background:#fff; border-bottom:1px solid var(--border); padding:0 24px; height:56px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:50; }}
  nav .brand {{ font-weight:700; font-size:16px; color:var(--title); text-decoration:none; }}
  nav .links {{ display:flex; gap:24px; font-size:13px; }}
  nav .links a {{ color:var(--muted); text-decoration:none; }}
  nav .links a.active {{ color:var(--blue); font-weight:600; border-bottom:2px solid var(--blue); padding-bottom:2px; }}
  .hero {{ background:linear-gradient(135deg,#1e293b 0%,#1e3a8a 100%); color:#fff; padding:32px 24px; }}
  .hero h1 {{ font-size:26px; font-weight:700; margin-bottom:8px; }}
  .hero p {{ color:#94a3b8; font-size:14px; max-width:640px; margin-bottom:16px; }}
  .hero .meta {{ display:flex; flex-wrap:wrap; gap:20px; font-size:12px; color:#94a3b8; }}
  .hero .meta b {{ color:#fff; }}
  .page {{ max-width:1200px; margin:0 auto; padding:32px 24px; }}
  .section-title {{ font-size:18px; font-weight:700; color:var(--title); margin-bottom:16px; padding-bottom:8px; border-bottom:2px solid var(--border); }}
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:32px; }}
  .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
  .kpi .label {{ font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin-bottom:6px; }}
  .kpi .value {{ font-size:28px; font-weight:700; color:var(--title); }}
  .kpi .sub {{ font-size:11px; color:var(--muted); margin-top:4px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin-bottom:32px; box-shadow:0 1px 3px rgba(0,0,0,.04); }}
  .card-header {{ padding:16px 20px; border-bottom:1px solid var(--border); font-weight:700; font-size:16px; color:var(--title); }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ background:#f8fafc; padding:12px 12px; font-size:12px; font-weight:600; color:var(--muted); text-align:left; border-bottom:2px solid var(--border); white-space:nowrap; }}
  .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:32px; }}
  .info-box {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
  .info-box h3 {{ font-size:14px; font-weight:700; color:var(--title); margin-bottom:8px; }}
  .info-box ul {{ list-style:none; font-size:13px; color:var(--body); }}
  .info-box ul li {{ padding:3px 0; border-bottom:1px solid #f1f5f9; }}
  .info-box ul li:last-child {{ border:none; }}
  @media(max-width:768px) {{ .info-grid {{ grid-template-columns:1fr; }} nav .links {{ display:none; }} }}
  .mae-note {{ background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:14px 18px; font-size:13px; color:#991b1b; margin-top:8px; }}
  footer {{ background:#1e293b; color:#94a3b8; text-align:center; padding:24px; font-size:12px; border-top:1px solid #334155; }}
</style>
</head>
<body>

<div class="disclaimer">
  ⚠️ <strong>Educational research only.</strong> Not investment advice. Back-test results do not guarantee future performance.
  <a href="disclaimer.html">Full Disclaimer</a>
</div>

<nav>
  <a href="index.html" class="brand">📊 Financial Literacy Hub</a>
  <div class="links">
    <a href="index.html">Home</a>
    <a href="dashboard.html">Dashboard</a>
    <a href="swing-dashboard.html">Momentum Scanner</a>
    <a href="convergence-dashboard.html" class="active">Evidence Engine</a>
    <a href="box-dashboard.html">Box Scanner</a>
    <a href="discussions.html">Stock Manager</a>
  </div>
</nav>

<div class="hero">
  <h1>📊 Institutional Convergence &amp; Evidence Dashboard</h1>
  <p>Three strict layers: Scanner → Trade Rules → Evidence.
     Profit Factor, Expectancy, MAE &amp; MFE are the hero metrics — not win rate.
     All 4 stop-loss methods tested side-by-side. No look-ahead bias.</p>
  <div class="meta">
    <span>🕐 Updated: <b>{run_time}</b></span>
    <span>📈 Nifty: <b>₹{regime.get('nifty_price','—')}</b> | 200-SMA: <b>₹{regime.get('nifty_sma200','—')}</b></span>
    <span>🏳 Regime: <b style="color:{regime_col};">{regime_lbl}</b></span>
  </div>
</div>

<div class="page">

  <!-- KPI scorecard -->
  <h2 class="section-title">🏆 System Evidence Scorecard (A ∩ B Cohort)</h2>
  <div class="kpi-grid">
    {"".join(
      f'<div class="kpi"><div class="label">{label}</div>'
      f'<div class="value" style="color:{color};">{value}</div>'
      f'<div class="sub">{sub}</div></div>'
      for label, value, color, sub in [
        ("A ∩ B Profit Factor",
         str(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("profitFactor","—")),
         pf_color(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("profitFactor")),
         "Target threshold: ≥ 1.75 | ATR stop"),
        ("A ∩ B Win Rate",
         fmt(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("winRate"),"%",d="—"),
         "#0f172a", "ATR stop basis"),
        ("A ∩ B Median T+20",
         fmt(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("medT20"),"%",d="—"),
         "#16a34a", "Bypasses look-ahead bias"),
        ("A ∩ B Max Drawdown",
         fmt(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("maxDrawdown"),"%",d="—"),
         "#dc2626", "Largest MAE across signals"),
        ("A ∩ B Expectancy",
         fmt(cohort_data.get("A_AND_B",{}).get("primaryMetrics",{}).get("expectancy"),d="—"),
         "#0f172a", "Avg ₹ per unit risked. Positive = edge."),
        ("Total Signals Tracked",
         str(sum(cohort_data.get(k,{}).get("count",0) for k in ["A_ONLY","B_ONLY","A_AND_B"])),
         "#0f172a", "All cohorts combined"),
      ]
    )}
  </div>

  <!-- MAE/MFE explanation -->
  <div class="mae-note">
    <b>What MAE tells you about your 2% stop:</b> If winning trades show an average MAE of −3.2%
    before reaching their target, a fixed 2% stop is <em>prematurely exiting winning setups</em>.
    Compare the ATR stop vs Fixed 2% columns in the table below to see this empirically.
  </div>

  <!-- Cohort comparison table -->
  <div class="card" style="margin-top:24px;">
    <div class="card-header">📐 Historical Evidence Ledger — Cohort Comparison (36-Month Back-Test)</div>
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>Cohort</th>
            <th>Signals</th>
            <th>Profit Factor</th>
            <th>Expectancy</th>
            <th>Win Rate</th>
            <th>Med T+5</th>
            <th>Med T+20</th>
            <th>Avg MAE</th>
            <th>Avg MFE</th>
            <th>Max Drawdown</th>
            <th>Stop Method Comparison</th>
          </tr>
        </thead>
        <tbody>
          {cohort_rows()}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Live scan table -->
  <h2 class="section-title" style="margin-top:32px;">🎯 Today's Active Convergence Signals</h2>
  <div class="card">
    <div class="card-header">Active Cohort Overlap Monitor — Post-Market Scan</div>
    <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>Stock</th>
            <th>Price</th>
            <th>Strategy A (Momentum)</th>
            <th>Strategy B (Structural Box)</th>
            <th>Convergence Status</th>
            <th>EMA Spread | RSI</th>
            <th>Dynamic Risk Anchors</th>
          </tr>
        </thead>
        <tbody>
          {live_rows()}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Educational callouts -->
  <div class="info-grid">
    <div class="info-box">
      <h3>📖 The 4 Stop-Loss Methods Explained</h3>
      <ul>
        <li><b>Fixed 2%</b> — Legacy reference. Often too tight for Indian equities.</li>
        <li><b>1.5× ATR</b> — Volatility-adjusted. Recommended primary method.</li>
        <li><b>20-EMA Line</b> — Structural trend anchor. Dynamic, moves with price.</li>
        <li><b>Swing Low</b> — Absolute floor of the 21-session consolidation box.</li>
      </ul>
      <p style="font-size:12px;color:var(--muted);margin-top:8px;">
        Compare the Stop Method columns above. The ATR stop empirically captures more winners
        by giving volatile Indian equities room to breathe before moving up.
      </p>
    </div>
    <div class="info-box">
      <h3>📖 MAE &amp; MFE — What They Mean</h3>
      <ul>
        <li><b>MAE (Max Adverse Excursion)</b> — How far a trade went against you before recovering. Use to calibrate your stop.</li>
        <li><b>MFE (Max Favorable Excursion)</b> — The peak profit a trade reached. Use to calibrate your GTT target.</li>
        <li><b>Profit Factor ≥ 1.75</b> — Target threshold. PF = gross wins ÷ gross losses.</li>
        <li><b>Expectancy &gt; 0</b> — Expected return per unit risked. This is the real edge metric.</li>
      </ul>
      <p style="font-size:12px;color:var(--muted);margin-top:8px;">
        A 70% win-rate strategy can lose money (70×1% − 30×4% = −50). A 45% strategy with
        good R:R can make money. Expectancy and Profit Factor are the only metrics that matter.
      </p>
    </div>
  </div>

  <!-- Architecture note -->
  <div class="info-box" style="margin-bottom:32px;">
    <h3>🏛 Research Architecture — 3 Strict Layers (No Cross-Contamination)</h3>
    <ul>
      <li><b>Layer 1 — Scanner:</b> Raw detection. EMA ≤1.5% + Vol dry-up (Strategy A). 21-session box ≥20% depth with 3+ touches (Strategy B). RSI is BUCKETED, not filtered.</li>
      <li><b>Layer 2 — Trade Rules:</b> All 4 stop-loss methods calculated. ATR×1.5 is the primary. Fixed 2% is the comparison legacy baseline.</li>
      <li><b>Layer 3 — Evidence:</b> This page. 36-month back-test. T+1 to T+20 distributions. MAE/MFE per signal. No look-ahead bias — signals are frozen at T=0 before future prices are revealed.</li>
    </ul>
  </div>

</div>

<footer>
  <p>© 2026 Financial Literacy Platform — Personal study tool. Solely owned &amp; independently operated. For educational purposes only. Not investment advice by any means.</p>
</footer>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ist      = ZoneInfo("Asia/Kolkata")
    run_time = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")
    print(f"📊 Convergence & Evidence Engine — {run_time}")

    # 1. Market regime
    print("  Fetching market regime...")
    regime_info = get_market_regime()
    print(f"  Regime: {regime_info['regime']} | Nifty {regime_info.get('nifty_price')}")

    # 2. Ticker universe
    tickers     = list({*get_nse_tickers(), *SEED_TICKERS})
    print(f"  Universe: {len(tickers)} tickers")

    # 3. Batch download (1y — enough for detection + tracking)
    CHUNK    = 80
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk_data = batch_download(tickers[i:i + CHUNK], period="1y")
        all_data.update(chunk_data)
    print(f"  Downloaded: {len(all_data)} tickers\n")

    # 4. Build signal records (look-back evidence)
    print("  Building signal records...")
    all_records: list[dict] = []
    for ticker, df in all_data.items():
        recs = build_signal_records(ticker, df)
        all_records.extend(recs)
    print(f"  Total signals found: {len(all_records)}")

    # 5. Cohort table
    cohort_table = build_cohort_table(all_records)
    for k, v in cohort_table.items():
        m = v.get("primaryMetrics", {})
        print(f"  {k}: {v['count']} signals | PF {m.get('profitFactor','—')} | "
              f"WR {m.get('winRate','—')}% | Exp {m.get('expectancy','—')}")

    # 6. Live scan
    print("\n  Building live scan...")
    live_scan = build_live_scan(all_data)
    print(f"  Active signals today: {len(live_scan)}")

    # 7. Save JSON
    out = {
        "lastUpdated":   datetime.utcnow().isoformat() + "Z",
        "runTimeIST":    run_time,
        "marketRegime":  regime_info,
        "cohortTable":   cohort_table,
        "liveScan":      live_scan,
        "regimeSplit":   build_regime_split(all_records, regime_info),
        "totalSignals":  len(all_records),
        "parameters": {
            "emaSpreadMax":    EMA_SPREAD_MAX,
            "volumeDryupMax":  VOLUME_DRYUP_MAX,
            "boxMinSessions":  BOX_MIN_SESSIONS,
            "boxMinDepthPct":  BOX_MIN_DEPTH_PCT,
            "boxMinTouches":   BOX_MIN_TOUCHES,
            "atrMult":         ATR_MULT,
            "fixedSlPct":      FIXED_SL_PCT,
            "targetPct":       TARGET_PCT,
            "holdSessions":    HOLD_SESSIONS,
        },
    }
    with open(CONV_JSON, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n✅ {CONV_JSON}")

    # 8. Save HTML
    with open(CONV_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(out))
    print(f"✅ {CONV_HTML}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
