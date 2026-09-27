#!/usr/bin/env python3
"""
Institutional Momentum-Squeeze & Structural-Box Scanner — Dynamic NSE Universe
-------------------------------------------------------------------------------
Architecture: THREE STRICT LAYERS (no cross-contamination)
  Layer 1 — Scanner  : raw signal detection, NO forward data
  Layer 2 — Trade    : dynamic stop-loss formulation (4 methods)
  Layer 3 — Evidence : backtested bucketed metrics (RSI, momentum, convergence)

Strategy A (Momentum Compression):
  - EMA 20/50 spread <= 1.5%  (coiled-spring compression)
  - Volume < 20-day SMA       (exhaustion dry-up)
  - RSI captured but NOT used as a hard filter — bucketed for empirical testing
  - Momentum bucket: price change % on breakout day, captured in bands

Strategy B (Structural Box — mathematically defined):
  - Minimum 21 trading sessions between qualifying boundaries
  - Range depth (High.max – Low.min) / Low.min >= 20%
  - At least 3 distinct price touches within ±1.5% of upper ceiling AND lower floor
  - Zero daily closes violating boundaries by more than 1.0% during consolidation

Convergence Engine (Layer 3):
  - A only / B only / A ∩ B / Neither
  - Empirically proves whether intersection improves Profit Factor

Stop-Loss Options (tested, not assumed):
  1. Fixed 2% capital cap
  2. 1.5× ATR subtracted from entry
  3. Below active daily 20-EMA
  4. Structural swing low of the consolidation box

Market Regime Dimension:
  - Nifty 50 above/below its own 200-SMA → positive / weak regime
  - Results split by regime for PF comparison

Back-test: 36-month look-back, T+1/T+3/T+5/T+10/T+20 return tracking
           MAE + MFE recorded per signal — NO look-ahead bias
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
ROOT           = Path(__file__).parent.parent
DATA_DIR       = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SCANNER_JSON   = DATA_DIR / "swing_scanner.json"
DASHBOARD_HTML = ROOT / "swing-dashboard.html"
STOCKS_JSON    = DATA_DIR / "stocks.json"   # Stock Manager source of truth

# ── Strategy A — Compression thresholds (BRD §1) ─────────────────────────────
EMA_SPREAD_MAX    = 1.5    # % — EMAs must be pinched tighter than this
VOLUME_DRYUP_MAX  = 1.0    # ratio — vol strictly lower than 20-day SMA
# NOTE: RSI is NO LONGER a hard entry filter — it is bucketed for research
RSI_OVERBOUGHT    = 65     # only used for "overextended" informational label

# ── RSI Research Buckets (reviewer recommendation) ───────────────────────────
RSI_BUCKETS = [
    (0,   40,  "RSI <40"),
    (40,  50,  "RSI 40–50"),
    (50,  55,  "RSI 50–55"),
    (55,  60,  "RSI 55–60"),
    (60,  65,  "RSI 60–65"),
    (65,  200, "RSI >65"),
]

# ── Momentum Buckets (% daily move on breakout day) ──────────────────────────
MOM_BUCKETS = [
    (0,   3,   "Move <3%"),
    (3,   4,   "Move 3–4%"),
    (4,   5,   "Move 4–5%"),
    (5,   6,   "Move 5–6%"),
    (6,   8,   "Move 6–8%"),
    (8,   999, "Move >8%"),
]

# ── Strategy B — Box parameters (mathematically defined) ─────────────────────
BOX_MIN_SESSIONS   = 21    # minimum trading sessions for a qualifying box
BOX_MIN_DEPTH_PCT  = 20.0  # minimum range depth: (high - low) / low * 100
BOX_TOUCH_BAND_PCT = 1.5   # ±% tolerance for counting ceiling/floor touches
BOX_MIN_TOUCHES    = 3     # minimum distinct touches per boundary
BOX_CLOSE_VIOL_PCT = 1.0   # max allowed % close violation of boundary

# ── Back-testing parameters ───────────────────────────────────────────────────
BT_LOOKBACK_YEARS = 3      # 36-month look-back
BT_HOLD_SESSIONS  = 20     # T+20 max tracking window
BT_TARGET_PCT     = 10.0   # proxy win target = +10%
BT_SL_FIXED_PCT   = 2.0    # Stop Option 1: fixed 2%
BT_ATR_MULT       = 1.5    # Stop Option 2: 1.5× ATR
BT_ATR_PERIOD     = 14     # ATR period
BT_MIN_RR_TARGET  = 2.5    # target R:R
BT_WIN_RATE_TARGET = 60.0  # realistic win-rate target (not 80% overfit bait)

# ── Market regime ticker ──────────────────────────────────────────────────────
REGIME_TICKER = "^NSEI"   # Nifty 50 index

# ── Mentor's seed watchlist (always included) ─────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Fetch live NSE tickers
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1b: Load stocks from Stock Manager (data/stocks.json)
# ─────────────────────────────────────────────────────────────────────────────
def load_stocks_json() -> list[dict]:
    """
    Reads data/stocks.json (the Stock Manager's source of truth) and returns
    a list of meta dicts compatible with SEED_META format:
      { "ticker": "X.NS", "name": "...", "sector": "..." }

    These are merged with SEED_WATCHLIST so every stock added via the
    Stock Manager page is automatically included in the daily scan.
    """
    result = []
    try:
        with open(STOCKS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            ticker = s.get("ticker", "").strip()
            if not ticker:
                continue
            # Normalise — ensure .NS suffix
            if not ticker.endswith(".NS"):
                ticker = ticker + ".NS"
            result.append({
                "ticker": ticker,
                "name":   s.get("name", ticker.replace(".NS", "")),
                "sector": s.get("sector", "Portfolio"),
            })
        print(f"  ✅ Loaded {len(result)} stocks from Stock Manager (stocks.json)")
    except FileNotFoundError:
        print("  ℹ stocks.json not found — using seed watchlist only")
    except Exception as e:
        print(f"  ⚠ stocks.json load failed: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Market regime (Nifty above/below 200-SMA)
# ─────────────────────────────────────────────────────────────────────────────
def get_market_regime() -> dict:
    """
    Fetches Nifty 50 and determines:
      - regime: "positive" (above 200-SMA) or "weak" (below 200-SMA)
      - nifty_price: latest close
      - nifty_sma200: 200-session SMA
    """
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
        print(f"  ⚠ Market regime fetch failed: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: RSI calculation
# ─────────────────────────────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta    = series.diff().dropna()
    avg_gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    rsi      = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: ATR calculation
# ─────────────────────────────────────────────────────────────────────────────
def compute_atr(df: pd.DataFrame, period: int = BT_ATR_PERIOD) -> float:
    """
    True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|).
    Returns the latest ATR value. Uses 'high'/'low'/'close' columns.
    Falls back to close-based proxy if OHLC not available.
    """
    try:
        h = df["high"]
        l = df["low"]
        c = df["close"].shift(1)
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        return round(float(tr.rolling(period).mean().iloc[-1]), 4)
    except Exception:
        # Fallback: use close-based rolling std as ATR proxy
        return round(float(df["close"].pct_change().abs().rolling(period).mean().iloc[-1]
                           * df["close"].iloc[-1]), 4)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Research bucket classifiers
# ─────────────────────────────────────────────────────────────────────────────
def rsi_bucket(rsi: float | None) -> str:
    if rsi is None:
        return "RSI N/A"
    for lo, hi, label in RSI_BUCKETS:
        if lo <= rsi < hi:
            return label
    return "RSI >65"


def momentum_bucket(pct_change: float | None) -> str:
    if pct_change is None:
        return "Move N/A"
    abs_move = abs(pct_change)
    for lo, hi, label in MOM_BUCKETS:
        if lo <= abs_move < hi:
            return label
    return "Move >8%"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Batch download — handles all yfinance column-layout variants
# ─────────────────────────────────────────────────────────────────────────────
def _find_col(raw_cols, field: str, ticker: str) -> str | None:
    """
    Robustly find the right column name regardless of yfinance version.
      Multi-ticker, auto_adjust=False : "Close_TICKER" or "Adj Close_TICKER"
      Single ticker                   : "Close" or "Adj Close"
    """
    candidates = [
        f"{field}_{ticker}",
        f"Adj {field}_{ticker}",
        field,
        f"Adj {field}",
    ]
    for c in candidates:
        if c in raw_cols:
            return c
    return None


def batch_download(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    Single yf.download() call. Returns {ticker: df(close, high, low, volume)}.
    Handles MultiIndex and flat column layouts defensively.
    """
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

        # Defensive MultiIndex flatten
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [f"{field}_{ticker}" for field, ticker in raw.columns]

        raw_cols = set(raw.columns)
        print(f"got {len(raw)} rows | cols sample: {list(raw.columns)[:6]}")

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


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7: Strategy B — Structural Box Detection (mathematical definition)
# ─────────────────────────────────────────────────────────────────────────────
def detect_structural_box(df: pd.DataFrame) -> dict:
    """
    Scans the most recent BOX_MIN_SESSIONS window for a qualifying structural box.

    Mathematical qualifications:
      1. Window >= BOX_MIN_SESSIONS sessions
      2. (High.max – Low.min) / Low.min * 100 >= BOX_MIN_DEPTH_PCT
      3. >= BOX_MIN_TOUCHES distinct candles touching within ±BOX_TOUCH_BAND_PCT
         of the ceiling (High.max) AND the floor (Low.min)
      4. Zero daily closes violating boundaries by more than BOX_CLOSE_VIOL_PCT

    Returns a dict with:
      stratB_active   : bool
      boxHigh, boxLow : float
      boxDepth        : float (%)
      boxDuration     : int (sessions)
      ceilTouches     : int
      floorTouches    : int
      closeViolations : int
      boxNote         : str
    """
    result = {
        "stratB_active":   False,
        "boxHigh":         None,
        "boxLow":          None,
        "boxDepth":        None,
        "boxDuration":     0,
        "ceilTouches":     0,
        "floorTouches":    0,
        "closeViolations": 0,
        "boxNote":         "No qualifying structural box found",
    }

    try:
        window = df.tail(BOX_MIN_SESSIONS)
        if len(window) < BOX_MIN_SESSIONS:
            result["boxNote"] = f"Insufficient data ({len(window)} sessions < {BOX_MIN_SESSIONS} required)"
            return result

        box_high = float(window["high"].max())
        box_low  = float(window["low"].min())
        box_depth = (box_high - box_low) / box_low * 100

        if box_depth < BOX_MIN_DEPTH_PCT:
            result["boxNote"] = f"Range too narrow: {box_depth:.1f}% < {BOX_MIN_DEPTH_PCT}% required"
            result["boxHigh"] = round(box_high, 2)
            result["boxLow"]  = round(box_low, 2)
            result["boxDepth"]= round(box_depth, 2)
            return result

        # Count ceiling touches: candle high within ±BOX_TOUCH_BAND_PCT of box_high
        ceil_band_hi = box_high * (1 + BOX_TOUCH_BAND_PCT / 100)
        ceil_band_lo = box_high * (1 - BOX_TOUCH_BAND_PCT / 100)
        floor_band_hi = box_low * (1 + BOX_TOUCH_BAND_PCT / 100)
        floor_band_lo = box_low * (1 - BOX_TOUCH_BAND_PCT / 100)

        ceil_touches  = int(((window["high"] >= ceil_band_lo) & (window["high"] <= ceil_band_hi)).sum())
        floor_touches = int(((window["low"]  >= floor_band_lo) & (window["low"]  <= floor_band_hi)).sum())

        # Count close violations: daily close > box_high * (1 + VIOL%) or < box_low * (1 - VIOL%)
        upper_viol = box_high * (1 + BOX_CLOSE_VIOL_PCT / 100)
        lower_viol = box_low  * (1 - BOX_CLOSE_VIOL_PCT / 100)
        close_viols = int(((window["close"] > upper_viol) | (window["close"] < lower_viol)).sum())

        qualifies = (
            ceil_touches  >= BOX_MIN_TOUCHES and
            floor_touches >= BOX_MIN_TOUCHES and
            close_viols   == 0
        )

        note = (
            f"Box {box_depth:.1f}% deep | {BOX_MIN_SESSIONS}d | "
            f"Ceil touches: {ceil_touches} | Floor touches: {floor_touches} | "
            f"Close violations: {close_viols}"
        )
        if not qualifies:
            if ceil_touches < BOX_MIN_TOUCHES:
                note += f" ← need {BOX_MIN_TOUCHES} ceiling touches"
            if floor_touches < BOX_MIN_TOUCHES:
                note += f" ← need {BOX_MIN_TOUCHES} floor touches"
            if close_viols > 0:
                note += f" ← {close_viols} close violation(s) disqualify"

        result.update({
            "stratB_active":   qualifies,
            "boxHigh":         round(box_high, 2),
            "boxLow":          round(box_low, 2),
            "boxDepth":        round(box_depth, 2),
            "boxDuration":     BOX_MIN_SESSIONS,
            "ceilTouches":     ceil_touches,
            "floorTouches":    floor_touches,
            "closeViolations": close_viols,
            "boxNote":         note,
        })

    except Exception as e:
        result["boxNote"] = f"Box detection error: {e}"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8: Back-test with multi-stop, MAE/MFE, T+intervals, regime-split
# ─────────────────────────────────────────────────────────────────────────────
def backtest_squeeze(df: pd.DataFrame, regime: str = "unknown") -> dict:
    """
    36-month squeeze back-test with:
      - 4 stop-loss formulations tested in parallel
      - MAE / MFE recorded per signal
      - T+1, T+3, T+5, T+10, T+20 return distribution
      - Expectancy, Profit Factor as hero metrics (not just win rate)
      - Regime tagging for each event

    Strategy A signal = EMA compressed + volume dry-up
    RSI is NO LONGER a filter — every compression event is captured.
    """
    base_result = {
        "btEvents":       0,
        "btWinRate":      None,
        "btProfitFactor": None,
        "btExpectancy":   None,
        "btMaxDrawdown":  None,
        "btAvgMAE":       None,
        "btAvgMFE":       None,
        "btAvgWin":       None,
        "btAvgLoss":      None,
        "btMedT5":        None,
        "btMedT20":       None,
        "btMeetsRR":      False,
        "btNote":         "Insufficient history for back-test",
        "btStopComparison": {},
        "btRSIBuckets":     {},
        "btMomBuckets":     {},
        "btRegimeSplit":    {},
    }

    try:
        df = df.copy()
        df["ema20"]   = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]   = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"] = df["volume"].rolling(window=20).mean()
        df["spread"]  = (df["ema20"] - df["ema50"]).abs() / df["ema50"] * 100

        # ATR column (14-period)
        h = df["high"]
        l = df["low"]
        c = df["close"].shift(1)
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(BT_ATR_PERIOD).mean()

        # RSI column
        delta    = df["close"].diff()
        gain     = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss     = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs       = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        # Price change %
        df["pct_change"] = df["close"].pct_change() * 100

        cutoff = len(df) - BT_HOLD_SESSIONS
        if cutoff < 60:
            return base_result

        events = []
        for i in range(55, cutoff):
            row = df.iloc[i]
            if pd.isna(row["avg_vol"]) or row["avg_vol"] <= 0:
                continue
            compressed = row["spread"] <= EMA_SPREAD_MAX
            vol_dry    = row["volume"] < row["avg_vol"] * VOLUME_DRYUP_MAX
            # Strategy A: capture ALL compression events, no RSI gate
            if compressed and vol_dry:
                events.append(i)

        if not events:
            base_result["btNote"] = "No historical Strategy A events found"
            return base_result

        # ── Per-event tracking ─────────────────────────────────────────────
        records = []
        for idx in events:
            entry  = float(df["close"].iloc[idx])
            atr_v  = float(df["atr"].iloc[idx]) if not pd.isna(df["atr"].iloc[idx]) else entry * 0.02
            rsi_v  = float(df["rsi"].iloc[idx]) if not pd.isna(df["rsi"].iloc[idx]) else None
            pct_v  = float(df["pct_change"].iloc[idx]) if not pd.isna(df["pct_change"].iloc[idx]) else None
            ema20_v= float(df["ema20"].iloc[idx])
            box_low= float(df["low"].iloc[max(0, idx - BOX_MIN_SESSIONS):idx + 1].min())

            # 4 stop-loss levels
            sl_fixed = entry * (1 - BT_SL_FIXED_PCT / 100)        # Option 1: 2% fixed
            sl_atr   = entry - (BT_ATR_MULT * atr_v)               # Option 2: 1.5×ATR
            sl_ema   = ema20_v                                       # Option 3: 20-EMA
            sl_box   = box_low                                       # Option 4: structural low

            target   = entry * (1 + BT_TARGET_PCT / 100)
            future   = df["close"].iloc[idx + 1 : idx + 1 + BT_HOLD_SESSIONS]
            future_h = df["high"].iloc[idx + 1 : idx + 1 + BT_HOLD_SESSIONS]
            future_l = df["low"].iloc[idx + 1 : idx + 1 + BT_HOLD_SESSIONS]

            # T+N returns
            t_rets = {}
            for t in [1, 3, 5, 10, 20]:
                if len(future) >= t:
                    t_rets[f"t{t}"] = round((float(future.iloc[t-1]) - entry) / entry * 100, 3)

            # MAE / MFE over entire window
            if len(future) > 0:
                mfe = round((float(future_h.max()) - entry) / entry * 100, 3)
                mae = round((entry - float(future_l.min())) / entry * 100, 3)
            else:
                mfe = mae = 0.0

            # Outcome per stop type
            outcomes = {}
            for sl_name, sl_val in [("fixed2pct", sl_fixed), ("atr1_5x", sl_atr),
                                     ("ema20", sl_ema), ("swingLow", sl_box)]:
                outcome = "loss"
                pnl     = -(BT_SL_FIXED_PCT)  # default to fixed loss if neither hit
                for j, (fp, fl) in enumerate(zip(future, future_l)):
                    if fp >= target:
                        outcome = "win"
                        pnl     = round((fp - entry) / entry * 100, 3)
                        break
                    if fl <= sl_val:
                        outcome = "loss"
                        pnl     = round((sl_val - entry) / entry * 100, 3)
                        break
                outcomes[sl_name] = {"outcome": outcome, "pnl": pnl}

            records.append({
                "entry":    entry,
                "rsi":      rsi_v,
                "pct":      pct_v,
                "mfe":      mfe,
                "mae":      mae,
                "outcomes": outcomes,
                "trets":    t_rets,
                "regime":   regime,
            })

        if not records:
            base_result["btNote"] = "No valid back-test records"
            return base_result

        # ── Aggregate primary metrics (using ATR stop as default) ─────────
        def agg_metrics(recs, stop_key="atr1_5x"):
            wins   = [r["outcomes"][stop_key]["pnl"] for r in recs if r["outcomes"][stop_key]["outcome"] == "win"]
            losses = [abs(r["outcomes"][stop_key]["pnl"]) for r in recs if r["outcomes"][stop_key]["outcome"] == "loss"]
            total  = len(wins) + len(losses)
            if total == 0:
                return {}
            win_rate = round(len(wins) / total * 100, 1)
            avg_win  = round(sum(wins) / len(wins), 3) if wins else 0
            avg_loss = round(sum(losses) / len(losses), 3) if losses else 0
            pf       = round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else None
            exp      = round((win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss), 4)
            return {
                "events": total, "wins": len(wins), "losses": len(losses),
                "winRate": win_rate, "avgWin": avg_win, "avgLoss": avg_loss,
                "profitFactor": pf, "expectancy": exp,
            }

        primary = agg_metrics(records, "atr1_5x")

        # ── Stop comparison table ─────────────────────────────────────────
        stop_cmp = {}
        for sk in ["fixed2pct", "atr1_5x", "ema20", "swingLow"]:
            stop_cmp[sk] = agg_metrics(records, sk)

        # ── RSI bucket breakdown ──────────────────────────────────────────
        rsi_bkt = {}
        for lo, hi, label in RSI_BUCKETS:
            grp = [r for r in records if r["rsi"] is not None and lo <= r["rsi"] < hi]
            if grp:
                rsi_bkt[label] = agg_metrics(grp, "atr1_5x")

        # ── Momentum bucket breakdown ─────────────────────────────────────
        mom_bkt = {}
        for lo, hi, label in MOM_BUCKETS:
            grp = [r for r in records if r["pct"] is not None and lo <= abs(r["pct"]) < hi]
            if grp:
                mom_bkt[label] = agg_metrics(grp, "atr1_5x")

        # ── Regime split ─────────────────────────────────────────────────
        regime_split = {}
        for rg in ["positive", "weak", "unknown"]:
            grp = [r for r in records if r["regime"] == rg]
            if grp:
                regime_split[rg] = agg_metrics(grp, "atr1_5x")

        # ── MAE / MFE aggregates ──────────────────────────────────────────
        maes  = [r["mae"] for r in records]
        mfes  = [r["mfe"] for r in records]
        t5s   = [r["trets"].get("t5") for r in records if "t5" in r["trets"]]
        t20s  = [r["trets"].get("t20") for r in records if "t20" in r["trets"]]

        max_dd = max(maes) if maes else 0

        base_result.update({
            "btEvents":       primary.get("events", 0),
            "btWinRate":      primary.get("winRate"),
            "btProfitFactor": primary.get("profitFactor"),
            "btExpectancy":   primary.get("expectancy"),
            "btMaxDrawdown":  round(max_dd, 2),
            "btAvgMAE":       round(float(np.mean(maes)), 3) if maes else None,
            "btAvgMFE":       round(float(np.mean(mfes)), 3) if mfes else None,
            "btAvgWin":       primary.get("avgWin"),
            "btAvgLoss":      primary.get("avgLoss"),
            "btMedT5":        round(float(np.median(t5s)), 3) if t5s else None,
            "btMedT20":       round(float(np.median(t20s)), 3) if t20s else None,
            "btMeetsRR":      (primary.get("profitFactor") or 0) >= BT_MIN_RR_TARGET,
            "btNote":         f"{primary.get('events',0)} events (ATR stop) | 36-month window",
            "btStopComparison": stop_cmp,
            "btRSIBuckets":     rsi_bkt,
            "btMomBuckets":     mom_bkt,
            "btRegimeSplit":    regime_split,
        })

    except Exception as e:
        base_result["btNote"] = f"Back-test error: {e}"

    return base_result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 9: Analyse single stock — Strategy A + B + convergence
# ─────────────────────────────────────────────────────────────────────────────
def analyse(ticker: str, df: pd.DataFrame, meta: dict, regime: str = "unknown") -> dict:
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
        "rsiBucket":    None,
        "volumeRatio":  None,
        "momBucket":    None,
        "atr":          None,
        "atrStopFloor": None,
        "ema20StopFloor": None,
        "swingLowFloor":  None,
        # Strategy A
        "isCompressed":  False,
        "isVolumeDryUp": False,
        "stratA_active": False,
        # Strategy B
        "stratB_active": False,
        "box":           {},
        # Convergence
        "cohort":        "None",
        "cohortLabel":   "No signal",
        # Framework
        "framework":    None,
        "frameworkDesc": None,
        # Back-test
        "backtest":     {},
        "marketRegime": regime,
    }

    try:
        df = df.copy()
        df["ema20"]   = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"]   = df["close"].ewm(span=50, adjust=False).mean()
        df["avg_vol"] = df["volume"].rolling(window=20).mean()

        latest  = df.iloc[-1]
        prev    = df.iloc[-2]

        price     = round(float(latest["close"]), 2)
        ema20     = round(float(latest["ema20"]), 2)
        ema50     = round(float(latest["ema50"]), 2)
        spread    = round(abs(ema20 - ema50) / ema50 * 100, 3)
        vol       = int(latest["volume"])
        avg_vol   = int(latest["avg_vol"]) if latest["avg_vol"] > 0 else 1
        vol_ratio = round(vol / avg_vol, 3)
        rsi       = compute_rsi(df["close"])
        atr_v     = compute_atr(df)
        pct_chg   = round((price - float(prev["close"])) / float(prev["close"]) * 100, 3)

        # Dynamic stop-loss floors (all 4 methods)
        swing_low    = round(float(df["low"].tail(BOX_MIN_SESSIONS).min()), 2)
        atr_floor    = round(price - (BT_ATR_MULT * atr_v), 2)
        ema20_floor  = ema20  # stop below current 20-EMA line

        # Strategy A conditions (RSI no longer a hard gate)
        compressed   = spread <= EMA_SPREAD_MAX
        vol_dry_up   = vol < avg_vol * VOLUME_DRYUP_MAX
        strat_a      = compressed and vol_dry_up

        # Strategy B — structural box
        box_data = detect_structural_box(df)
        strat_b  = box_data["stratB_active"]

        # Convergence cohort
        if strat_a and strat_b:
            cohort      = "A_AND_B"
            cohort_label = "💎 A ∩ B — Strong Convergence"
            alert_level  = "critical"
        elif strat_a:
            cohort      = "A_ONLY"
            cohort_label = "⚡ Strategy A — Momentum Compression"
            alert_level  = "setup" if rsi < RSI_OVERBOUGHT else "overextended"
        elif strat_b:
            cohort      = "B_ONLY"
            cohort_label = "📐 Strategy B — Structural Box"
            alert_level  = "watch"
        else:
            cohort      = "NONE"
            cohort_label = "No convergence signal"
            alert_level  = "normal"

        # Alert text
        if cohort == "A_AND_B":
            alert = (f"CONVERGENCE: Both strategies active. "
                     f"EMA spread {spread:.2f}% | Vol {vol_ratio:.2f}x | RSI {rsi} | "
                     f"Box depth {box_data.get('boxDepth','?')}%")
        elif cohort == "A_ONLY":
            alert = (f"Strategy A: EMA compressed ({spread:.2f}%) + Vol dry-up ({vol_ratio:.2f}x). "
                     f"RSI {rsi} [{rsi_bucket(rsi)}]")
        elif cohort == "B_ONLY":
            alert = f"Strategy B: {box_data['boxNote']}"
        else:
            alert = f"No signal. EMA spread {spread:.2f}% | RSI {rsi}"

        # Framework (positional context)
        if price >= ema50:
            framework      = "A"
            framework_desc = "Framework A — Swing Breakout (5–15 sessions). Price above EMA-50."
        else:
            framework      = "B"
            framework_desc = "Framework B — Bottom-Sweep Accumulation (3–24 months). Price below EMA-50."

        # Back-test
        bt = backtest_squeeze(df, regime=regime)

        result.update({
            "status":         "ok",
            "alert":          alert,
            "alertLevel":     alert_level,
            "currentPrice":   price,
            "ema20":          ema20,
            "ema50":          ema50,
            "emaSpread":      spread,
            "rsi":            rsi,
            "rsiBucket":      rsi_bucket(rsi),
            "volumeRatio":    vol_ratio,
            "momBucket":      momentum_bucket(pct_chg),
            "atr":            round(atr_v, 2),
            "atrStopFloor":   atr_floor,
            "ema20StopFloor": ema20_floor,
            "swingLowFloor":  swing_low,
            "isCompressed":    compressed,
            "isVolumeDryUp":   vol_dry_up,
            "stratA_active":   strat_a,
            "stratB_active":   strat_b,
            "box":             box_data,
            "cohort":          cohort,
            "cohortLabel":     cohort_label,
            "framework":       framework,
            "frameworkDesc":   framework_desc,
            "backtest":        bt,
            "marketRegime":    regime,
        })

    except Exception as e:
        result["alert"] = f"Error: {e}"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 10: Build HTML dashboard
# ─────────────────────────────────────────────────────────────────────────────
def build_html(results: list[dict], run_time: str, regime_info: dict) -> str:

    LEVEL_BORDER = {
        "critical":    "border-l-4 border-green-500 bg-green-50",
        "setup":       "border-l-4 border-yellow-400 bg-yellow-50",
        "watch":       "border-l-4 border-blue-400 bg-blue-50",
        "overextended":"border-l-4 border-red-400 bg-red-50",
        "normal":      "border-l-4 border-gray-200 bg-white",
        "error":       "border-l-4 border-gray-200 bg-gray-50",
    }
    LEVEL_ICON = {
        "critical":"💎","setup":"⚡","watch":"📐",
        "overextended":"🚫","normal":"⏳","error":"⚠️",
    }
    FW_PILL = {
        "A": '<span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded font-semibold">FW-A Swing</span>',
        "B": '<span class="text-xs bg-amber-100  text-amber-700  px-2 py-0.5 rounded font-semibold">FW-B Bottom</span>',
    }
    COHORT_PILL = {
        "A_AND_B": '<span class="text-xs bg-green-200 text-green-900 px-2 py-0.5 rounded font-bold">💎 A ∩ B</span>',
        "A_ONLY":  '<span class="text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded font-semibold">A Only</span>',
        "B_ONLY":  '<span class="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded font-semibold">B Only</span>',
        "NONE":    '',
    }

    def badge(ok, yes, no, yc="bg-green-100 text-green-800", nc="bg-gray-100 text-gray-400"):
        return f'<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold {yc if ok else nc}">{yes if ok else no}</span>'

    def p_fmt(v, d="—"):
        return f"₹{v:,.2f}" if v is not None else d

    n_critical   = sum(1 for r in results if r["alertLevel"] == "critical")
    n_setup      = sum(1 for r in results if r["alertLevel"] == "setup")
    n_watch      = sum(1 for r in results if r["alertLevel"] == "watch")
    n_convergent = sum(1 for r in results if r.get("cohort") == "A_AND_B")
    n_seed       = sum(1 for r in results if r.get("isSeed"))

    regime_label = regime_info.get("regime", "unknown")
    regime_color = "text-green-400" if regime_label == "positive" else ("text-red-400" if regime_label == "weak" else "text-gray-400")
    regime_txt   = f"Nifty: ₹{regime_info.get('nifty_price','?')} | 200-SMA: ₹{regime_info.get('nifty_sma200','?')} | Regime: <span class='{regime_color} font-bold'>{regime_label.upper()}</span>"

    cards = ""
    for r in results:
        if r.get("cohort") == "NONE" and not r.get("isSeed"):
            continue   # only render signalling stocks + always show seed
        lvl   = r.get("alertLevel", "normal")
        icon  = LEVEL_ICON.get(lvl, "⏳")
        cls   = LEVEL_BORDER.get(lvl, LEVEL_BORDER["normal"])
        sp    = f"{r['emaSpread']:.2f}%" if r.get("emaSpread") is not None else "—"
        rsi_s = str(r["rsi"]) if r.get("rsi") is not None else "—"
        vr_s  = f"{r['volumeRatio']:.2f}x" if r.get("volumeRatio") is not None else "—"
        atr_s = f"₹{r['atrStopFloor']:.2f}" if r.get("atrStopFloor") else "—"
        ema_s = f"₹{r['ema20StopFloor']:.2f}" if r.get("ema20StopFloor") else "—"
        sw_s  = f"₹{r['swingLowFloor']:.2f}" if r.get("swingLowFloor") else "—"
        seed_pill = '<span class="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Mentor</span>' if r.get("isSeed") else '<span class="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">Universe</span>'
        fw_pill   = FW_PILL.get(r.get("framework", ""), "")
        coh_pill  = COHORT_PILL.get(r.get("cohort", "NONE"), "")
        rsi_bkt   = r.get("rsiBucket", "")
        mom_bkt   = r.get("momBucket", "")
        box       = r.get("box", {})

        # Back-test quick metrics
        bt = r.get("backtest", {})
        pf_s  = f"{bt.get('btProfitFactor','—')}" if bt.get("btProfitFactor") else "—"
        exp_s = f"{bt.get('btExpectancy','—')}" if bt.get("btExpectancy") is not None else "—"
        t5_s  = f"{bt.get('btMedT5','—')}%" if bt.get("btMedT5") is not None else "—"
        mae_s = f"{bt.get('btAvgMAE','—')}%" if bt.get("btAvgMAE") is not None else "—"
        mfe_s = f"{bt.get('btAvgMFE','—')}%" if bt.get("btAvgMFE") is not None else "—"

        cards += f"""
        <div class="rounded-lg shadow-sm p-5 {cls} mb-4">
          <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
            <div class="flex-1">
              <div class="flex flex-wrap items-center gap-2 mb-1">
                <span class="text-xl">{icon}</span>
                <h3 class="text-base font-bold text-gray-900">{r['name']}</h3>
                <span class="text-xs text-gray-400 font-mono">{r['ticker'].replace('.NS','')}</span>
                <span class="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">{r['sector']}</span>
                {seed_pill} {fw_pill} {coh_pill}
              </div>
              <p class="text-sm text-gray-700 font-medium">{r['alert']}</p>
              <p class="text-xs text-gray-500 mt-0.5">
                RSI bucket: <b>{rsi_bkt}</b> &nbsp;|&nbsp; Momentum: <b>{mom_bkt}</b>
                &nbsp;|&nbsp; Regime: <b>{r.get('marketRegime','?')}</b>
              </p>
              {"<p class='text-xs text-gray-400 mt-0.5 italic'>" + box.get("boxNote","") + "</p>" if box.get("boxNote") else ""}
            </div>
            <div class="text-right flex-shrink-0">
              <p class="text-2xl font-bold text-gray-900">{p_fmt(r['currentPrice'])}</p>
              <p class="text-xs text-gray-400">Current Price</p>
            </div>
          </div>

          <!-- Indicator row -->
          <div class="mt-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 text-sm">
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA Spread</p>
              <p class="font-semibold {'text-green-700' if r.get('isCompressed') else 'text-gray-700'}">{sp}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">RSI (14)</p>
              <p class="font-semibold {'text-orange-600' if (r.get('rsi') or 0) >= RSI_OVERBOUGHT else 'text-gray-700'}">{rsi_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Vol Ratio</p>
              <p class="font-semibold {'text-green-700' if r.get('isVolumeDryUp') else 'text-gray-700'}">{vr_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">ATR Stop</p>
              <p class="font-semibold text-red-600">{atr_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">EMA20 Stop</p>
              <p class="font-semibold text-orange-600">{ema_s}</p>
            </div>
            <div class="bg-white rounded p-3 shadow-sm text-center">
              <p class="text-xs text-gray-400 mb-1">Swing Low</p>
              <p class="font-semibold text-purple-700">{sw_s}</p>
            </div>
          </div>

          <!-- Evidence row -->
          <div class="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 text-xs text-center">
            <div class="bg-slate-50 rounded p-2">
              <p class="text-gray-400">Profit Factor</p>
              <p class="font-bold text-gray-800">{pf_s}</p>
            </div>
            <div class="bg-slate-50 rounded p-2">
              <p class="text-gray-400">Expectancy</p>
              <p class="font-bold text-gray-800">{exp_s}</p>
            </div>
            <div class="bg-slate-50 rounded p-2">
              <p class="text-gray-400">Med T+5</p>
              <p class="font-bold text-gray-800">{t5_s}</p>
            </div>
            <div class="bg-slate-50 rounded p-2">
              <p class="text-gray-400">Avg MAE</p>
              <p class="font-bold text-red-700">{mae_s}</p>
            </div>
            <div class="bg-slate-50 rounded p-2">
              <p class="text-gray-400">Avg MFE</p>
              <p class="font-bold text-green-700">{mfe_s}</p>
            </div>
          </div>

          <!-- Conditions badges -->
          <div class="mt-3 flex flex-wrap gap-2 text-xs">
            {badge(r.get('isCompressed'),  '✅ EMA ≤1.5%',   '❌ Spread wide')}
            {badge(r.get('isVolumeDryUp'), '✅ Vol &lt; SMA', '❌ Normal vol')}
            {badge(r.get('stratA_active'), '✅ Strategy A',   '— Strategy A', 'bg-yellow-100 text-yellow-800', 'bg-gray-100 text-gray-400')}
            {badge(r.get('stratB_active'), '✅ Strategy B',   '— Strategy B', 'bg-blue-100 text-blue-800', 'bg-gray-100 text-gray-400')}
            {badge(r.get('cohort') == 'A_AND_B', '💎 Convergent', '— Divergent', 'bg-green-200 text-green-900', 'bg-gray-100 text-gray-400')}
          </div>
        </div>"""

    if not cards:
        cards = """<div class="bg-white rounded-lg shadow-sm p-12 text-center">
          <div class="text-5xl mb-4">⏳</div>
          <h3 class="text-xl font-bold text-gray-700 mb-2">No signals today</h3>
          <p class="text-gray-400 text-sm">Run the workflow: Actions → Daily Swing Squeeze Scanner → Run workflow</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Institutional Convergence Scanner — A ∩ B Engine</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-50 min-h-screen">

  <div class="bg-yellow-50 border-b border-yellow-300 py-2 px-4 text-xs text-yellow-800 text-center">
    <i class="fas fa-exclamation-triangle mr-1"></i><strong>Educational research only.</strong>
    Not investment advice. Results are back-tests — not guarantees. <a href="disclaimer.html" class="underline ml-1">Full Disclaimer</a>
  </div>

  <nav class="bg-white shadow sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="index.html" class="flex items-center gap-2 text-gray-800 font-bold text-lg">
        <i class="fas fa-chart-line text-blue-600"></i> Financial Literacy Hub
      </a>
      <div class="hidden md:flex items-center gap-6 text-sm">
        <a href="index.html"                    class="text-gray-600 hover:text-blue-600">Home</a>
        <a href="dashboard.html"                class="text-gray-600 hover:text-blue-600">Dashboard</a>
        <a href="swing-dashboard.html"          class="text-blue-600 font-semibold border-b-2 border-blue-600 pb-0.5">Momentum Scanner</a>
        <a href="convergence-dashboard.html"    class="text-gray-600 hover:text-blue-600">Evidence Engine</a>
        <a href="box-dashboard.html"            class="text-gray-600 hover:text-blue-600">Box Scanner</a>
        <a href="discussions.html"              class="text-gray-600 hover:text-blue-600"><i class="fas fa-tasks mr-1"></i>Stock Manager</a>
      </div>
    </div>
  </nav>

  <section class="bg-gradient-to-r from-slate-800 to-blue-900 text-white py-10">
    <div class="max-w-6xl mx-auto px-4">
      <h1 class="text-3xl font-bold mb-2">
        <i class="fas fa-compress-arrows-alt mr-2 text-yellow-400"></i>
        Institutional Convergence Scanner — A ∩ B Engine
      </h1>
      <p class="text-blue-200 text-sm max-w-2xl mb-4">
        Three strict layers: <strong class="text-white">Scanner → Trade Rules → Evidence.</strong>
        Strategy A (Momentum Compression) meets Strategy B (Structural Box). RSI is no longer a hard filter —
        it is bucketed empirically. Stop-loss tested across 4 methods. MAE/MFE tracked per signal.
      </p>
      <div class="flex flex-wrap gap-5 text-xs text-blue-300">
        <span><i class="fas fa-clock mr-1"></i>Scan: <strong class="text-white">{run_time}</strong></span>
        <span><i class="fas fa-database mr-1"></i>Universe: <strong class="text-white">{len(results)}</strong> stocks</span>
        <span class="text-green-400"><i class="fas fa-gem mr-1"></i>{n_convergent} A∩B Convergent</span>
        <span class="text-yellow-400"><i class="fas fa-bolt mr-1"></i>{n_setup} Strategy A</span>
        <span class="text-blue-300"><i class="fas fa-th-large mr-1"></i>{n_watch} Strategy B</span>
        <span><i class="fas fa-seedling text-blue-200 mr-1"></i>{n_seed} mentor seeds</span>
      </div>
      <p class="text-xs text-blue-300 mt-2">
        <i class="fas fa-chart-bar mr-1"></i>Market {regime_txt}
      </p>
    </div>
  </section>

  <!-- Regime + Legend -->
  <section class="max-w-6xl mx-auto px-4 py-4 space-y-3">
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
      <div>
        <p class="font-bold text-gray-700 mb-2">Stop-Loss Methods (all 4 shown per card)</p>
        <ul class="text-gray-500 space-y-1">
          <li><b class="text-red-600">ATR Stop</b> — Entry minus 1.5× ATR(14). Dynamic volatility buffer.</li>
          <li><b class="text-orange-600">EMA20 Stop</b> — Below the active 20-EMA line. Structural trend anchor.</li>
          <li><b class="text-purple-700">Swing Low</b> — Bottom of the consolidation box (21-session structural floor).</li>
          <li><b class="text-gray-500">Fixed 2%</b> — Legacy reference only. Tested in back-test comparison table.</li>
        </ul>
      </div>
      <div>
        <p class="font-bold text-gray-700 mb-2">Evidence Metrics (not win rate)</p>
        <ul class="text-gray-500 space-y-1">
          <li><b>Profit Factor</b> — Gross wins ÷ Gross losses. Target ≥ 1.75.</li>
          <li><b>Expectancy</b> — Average $ return per unit risked. Positive = edge.</li>
          <li><b>MAE</b> — Max Adverse Excursion. If winners show −3% MAE, a 2% stop kills them.</li>
          <li><b>MFE</b> — Max Favorable Excursion. Guides profit-booking GTT placement.</li>
        </ul>
      </div>
    </div>
    <div class="bg-white rounded-lg shadow-sm p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-green-500 flex-shrink-0"></span>
        <div><p class="font-bold">💎 A ∩ B Convergent</p><p class="text-gray-500">Both strategies independently identify the same stock. Highest research priority.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-yellow-400 flex-shrink-0"></span>
        <div><p class="font-bold">⚡ Strategy A Only</p><p class="text-gray-500">EMA compressed + volume exhaustion. RSI bucketed, not filtered.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-blue-400 flex-shrink-0"></span>
        <div><p class="font-bold">📐 Strategy B Only</p><p class="text-gray-500">21-session box ≥20% depth, 3+ boundary touches, no close violations.</p></div>
      </div>
      <div class="flex items-start gap-2">
        <span class="w-3 h-8 rounded bg-red-400 flex-shrink-0"></span>
        <div><p class="font-bold">🚫 Overextended</p><p class="text-gray-500">RSI ≥ 65. Informational only — now tracked in RSI bucket table, not hard-rejected.</p></div>
      </div>
    </div>
  </section>

  <main class="max-w-6xl mx-auto px-4 py-2 pb-12">
    {cards}
  </main>

  <section class="max-w-6xl mx-auto px-4 pb-10">
    <div class="bg-slate-800 text-white rounded-lg p-6 text-sm">
      <h3 class="font-bold text-yellow-400 mb-3"><i class="fas fa-graduation-cap mr-2"></i>Research Architecture</h3>
      <div class="grid md:grid-cols-3 gap-4 text-gray-300 text-xs">
        <div>
          <p class="font-semibold text-white mb-1">Layer 1 — Scanner</p>
          <p>Raw signal detection only. No forward data. Strategy A: EMA ≤1.5% + Vol dry-up (RSI now bucketed, not filtered). Strategy B: 21-session box with mathematical boundary rules.</p>
        </div>
        <div>
          <p class="font-semibold text-white mb-1">Layer 2 — Trade Rules</p>
          <p>4 stop-loss methods tested in parallel. ATR-based is the primary. EMA20 and structural swing-low are alternatives. Fixed 2% is the legacy reference for comparison.</p>
        </div>
        <div>
          <p class="font-semibold text-white mb-1">Layer 3 — Evidence</p>
          <p>36-month back-test. RSI buckets, momentum buckets, regime split. Hero metrics: Profit Factor, Expectancy, MAE, MFE. Not win rate. Results on the Evidence Engine page.</p>
        </div>
      </div>
    </div>
  </section>

  <footer class="bg-gray-800 text-gray-400 text-center py-6 text-xs">
    <p>© 2026 Financial Literacy Platform — Personal study tool. Solely owned &amp; independently operated. For educational purposes only. Not investment advice by any means.</p>
  </footer>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ist      = ZoneInfo("Asia/Kolkata")
    run_time = datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")

    print(f"🔍 Convergence Scanner (A ∩ B) — {run_time}")
    print(f"   Strategy A: EMA ≤{EMA_SPREAD_MAX}% + Vol dry-up (RSI now BUCKETED, not filtered)")
    print(f"   Strategy B: Box ≥{BOX_MIN_SESSIONS}d, depth ≥{BOX_MIN_DEPTH_PCT}%, ≥{BOX_MIN_TOUCHES} touches each boundary")
    print(f"   Stop-loss: 4 methods tested | ATR×{BT_ATR_MULT} is primary")
    print()

    # ── 1. Market regime ────────────────────────────────────────────────────
    print("  Fetching market regime (Nifty 200-SMA)...")
    regime_info = get_market_regime()
    print(f"  Regime: {regime_info['regime']} | Nifty: {regime_info.get('nifty_price')} | 200-SMA: {regime_info.get('nifty_sma200')}\n")

    # ── 1b. Load Stock Manager stocks (stocks.json) and merge into seed universe
    print("  Loading Stock Manager watchlist (data/stocks.json)...")
    portfolio_stocks = load_stocks_json()
    # Merge portfolio stocks into the meta lookup — they get "isSeed=True" treatment
    # so they always appear in the dashboard even if no signal fires on them
    portfolio_tickers: set[str] = set()
    for s in portfolio_stocks:
        t = s["ticker"]
        portfolio_tickers.add(t)
        if t not in SEED_META:          # don't overwrite existing seed metadata
            SEED_META[t]    = s
            SEED_TICKERS.add(t)
    print(f"  Portfolio stocks added to scan: {len(portfolio_tickers)}\n")

    # ── 2. Build full ticker universe ───────────────────────────────────────
    live_tickers = get_nse_tickers()
    all_tickers  = list({*live_tickers, *SEED_TICKERS})
    print(f"  Total universe: {len(all_tickers)} tickers\n")

    # ── 3. Batch download in chunks of 80 ───────────────────────────────────
    CHUNK = 80
    all_data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(all_tickers), CHUNK):
        chunk      = all_tickers[i:i + CHUNK]
        chunk_data = batch_download(chunk, period="3y")   # 3y for 36-month back-test
        all_data.update(chunk_data)

    print(f"\n  Downloaded: {len(all_data)} tickers with sufficient history\n")

    # ── 4. Analyse every ticker ──────────────────────────────────────────────
    results: list[dict] = []
    for ticker, df in all_data.items():
        meta = SEED_META.get(ticker, {"ticker": ticker,
                                      "name":   ticker.replace(".NS",""),
                                      "sector": "NSE"})
        r = analyse(ticker, df, meta, regime=regime_info["regime"])
        results.append(r)

    # ── 5. Sort: convergent first, then A, then B, then normal ───────────────
    ORDER = {"critical":0,"setup":1,"watch":2,"overextended":3,"normal":4,"error":5}
    results.sort(key=lambda r: (ORDER.get(r["alertLevel"], 5), -(r.get("rsi") or 0)))

    # ── 6. Summary ────────────────────────────────────────────────────────────
    counts: dict[str, int] = {}
    for r in results:
        counts[r["alertLevel"]] = counts.get(r["alertLevel"], 0) + 1
    cohort_counts = {"A_AND_B": 0, "A_ONLY": 0, "B_ONLY": 0, "NONE": 0}
    for r in results:
        cohort_counts[r.get("cohort", "NONE")] = cohort_counts.get(r.get("cohort","NONE"), 0) + 1

    print("── Scan Summary ──")
    for lvl, n in sorted(counts.items(), key=lambda x: ORDER.get(x[0], 9)):
        print(f"  {lvl:15s}: {n}")
    print("\n── Cohort Summary ──")
    for cohort, n in cohort_counts.items():
        print(f"  {cohort:15s}: {n}")

    # ── 7. Save JSON ──────────────────────────────────────────────────────────
    out = {
        "lastUpdated":    datetime.utcnow().isoformat() + "Z",
        "runTimeIST":     run_time,
        "totalScanned":   len(results),
        "marketRegime":   regime_info,
        "summary":        counts,
        "cohortSummary":  cohort_counts,
        "thresholds": {
            "emaSpreadMax":     EMA_SPREAD_MAX,
            "volumeDryUpRatio": VOLUME_DRYUP_MAX,
            "rsiOverbought":    RSI_OVERBOUGHT,
            "boxMinSessions":   BOX_MIN_SESSIONS,
            "boxMinDepthPct":   BOX_MIN_DEPTH_PCT,
            "boxMinTouches":    BOX_MIN_TOUCHES,
            "atrMultiplier":    BT_ATR_MULT,
            "fixedSlPct":       BT_SL_FIXED_PCT,
        },
        "results": results,
    }
    with open(SCANNER_JSON, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n✅ {SCANNER_JSON}")

    # ── 8. Save HTML ───────────────────────────────────────────────────────────
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(results, run_time, regime_info))
    print(f"✅ {DASHBOARD_HTML}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
