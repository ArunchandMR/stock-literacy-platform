#!/usr/bin/env python3
"""
Stock Data Fetcher — CI-safe build
-----------------------------------
Root cause of Yahoo failures in GitHub Actions:
  yf.download() sends a batch request that Yahoo Finance blocks in CI
  environments (rate-limiting / missing browser cookies).

Fix applied:
  • Per-ticker yf.Ticker(t).fast_info (lightweight, single-ticker call)
  • 1-second delay between tickers to avoid rate-limiting
  • Stooq as first fallback (no cookie required)
  • Last-known cached price as second fallback
  • Entry price as last resort  (shows "Pending" in UI — not "Fallback")
  • Market-hours gate REMOVED: the workflow runs after market close,
    so we always want to fetch the closing price.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

# pandas_datareader Stooq fallback — optional, graceful if missing
try:
    import pandas_datareader.data as pdr_web
    _PDR_AVAILABLE = True
except ImportError:
    _PDR_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
_DATA_DIR    = _SCRIPT_DIR.parent / "data"
_STOCKS_FILE = _DATA_DIR / "stocks.json"
_DASH_FILE   = _DATA_DIR / "dashboard.json"

# ── Fetch delay (seconds) between individual ticker calls ────────────────────
_TICKER_DELAY = 1.2


class StockDataFetcher:

    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Individual-ticker fetch (CI-safe) ─────────────────────────────────────
    def _fetch_single_yahoo(self, ticker: str) -> float | None:
        """
        Uses Ticker.fast_info — a lightweight, single-stock endpoint that
        avoids the session/cookie issues that block yf.download() in CI.
        Falls back to history(period='5d') if fast_info is missing.
        """
        try:
            t = yf.Ticker(ticker)

            # fast_info is the most reliable in CI
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            if price and float(price) > 0:
                return round(float(price), 2)

            # fallback: last row of 5-day history
            hist = t.history(period="5d", auto_adjust=True)
            if not hist.empty:
                return round(float(hist["Close"].iloc[-1]), 2)

        except Exception as e:
            print(f"    Yahoo single fetch failed for {ticker}: {e}")

        return None

    # ── Stooq fallback (no authentication needed) ─────────────────────────────
    def _fetch_stooq(self, ticker: str) -> float | None:
        if not _PDR_AVAILABLE:
            return None
        try:
            symbol = ticker.replace(".NS", ".IN").replace(".BO", ".IN")
            df = pdr_web.DataReader(symbol, "stooq")
            if not df.empty:
                return round(float(df["Close"].iloc[0]), 2)
        except Exception:
            pass
        return None

    # ── Load previous dashboard.json for cached prices ────────────────────────
    def _load_cache(self) -> dict:
        """Returns {ticker: currentPrice} from last successful run."""
        if not _DASH_FILE.exists():
            return {}
        try:
            with open(_DASH_FILE) as f:
                data = json.load(f)
            stocks = data.get("stocks", data) if isinstance(data, dict) else data
            return {
                s["ticker"]: s.get("currentPrice")
                for s in stocks
                if s.get("ticker") and s.get("currentPrice")
            }
        except Exception:
            return {}

    # ── Main orchestrator ─────────────────────────────────────────────────────
    def run(self) -> int:
        if not _STOCKS_FILE.exists():
            print(f"ERROR: {_STOCKS_FILE} not found")
            return 1

        with open(_STOCKS_FILE) as f:
            stocks_data = json.load(f)

        stocks    = stocks_data.get("stocks", [])
        cache     = self._load_cache()
        run_id    = int(datetime.utcnow().timestamp())
        ist       = ZoneInfo("Asia/Kolkata")
        now_ist   = datetime.now(ist)

        print(f"▶ Fetching {len(stocks)} stocks at "
              f"{now_ist.strftime('%Y-%m-%d %H:%M IST')}")
        print(f"  Cache has {len(cache)} entries from previous run")

        dashboard    = []
        yahoo_ok     = 0
        stooq_ok     = 0
        cached_ok    = 0
        failed_total = 0

        for stock in stocks:
            ticker      = stock.get("ticker", "").strip()
            entry_price = float(stock.get("entryPrice") or 0)

            if not ticker:
                continue

            price  = None
            source = None
            status = None

            # ── 1. Yahoo Finance (per-ticker, CI-safe) ────────────────────
            print(f"  [{ticker}] trying Yahoo fast_info…", end=" ", flush=True)
            price = self._fetch_single_yahoo(ticker)
            if price:
                source = "Yahoo"
                status = "Live"
                yahoo_ok += 1
                print(f"✓ ₹{price}")
            else:
                print("✗")

            # ── 2. Stooq fallback ─────────────────────────────────────────
            if price is None:
                print(f"  [{ticker}] trying Stooq…", end=" ", flush=True)
                price = self._fetch_stooq(ticker)
                if price:
                    source = "Stooq"
                    status = "Live"
                    stooq_ok += 1
                    print(f"✓ ₹{price}")
                else:
                    print("✗")

            # ── 3. Cached price from previous run ─────────────────────────
            if price is None and ticker in cache:
                cached_val = cache[ticker]
                if cached_val and float(cached_val) > 0:
                    price  = float(cached_val)
                    source = "Cached"
                    status = "Cached"
                    cached_ok += 1
                    print(f"  [{ticker}] using cached ₹{price}")

            # ── 4. Entry price — last resort ──────────────────────────────
            if price is None:
                price  = entry_price
                source = "Entry"
                status = "Pending"
                failed_total += 1
                print(f"  [{ticker}] no data — showing entry price ₹{price}")

            performance = 0.0
            if entry_price > 0:
                performance = round(((price - entry_price) / entry_price) * 100, 2)

            dashboard.append({
                "id":           stock.get("id", ""),
                "ticker":       ticker,
                "name":         stock.get("name", ""),
                "sector":       stock.get("sector", ""),
                "strategy":     stock.get("strategy", ""),
                "entryDate":    stock.get("entryDate", ""),
                "entryPrice":   entry_price,
                "currentPrice": round(price, 2),
                "targetExitMin": stock.get("targetExitMin"),
                "targetExitMax": stock.get("targetExitMax"),
                "stopLoss":      stock.get("stopLoss"),
                "performance":  performance,
                "priceSource":  source,
                "fetchStatus":  status,
                "discussionUrl": stock.get("discussionUrl", ""),
                "notes":        stock.get("notes", ""),
                "runId":        run_id,
            })

            # Be polite to Yahoo — avoid rate limit
            time.sleep(_TICKER_DELAY)

        # ── Summary ───────────────────────────────────────────────────────────
        total = len(dashboard)
        live  = yahoo_ok + stooq_ok

        print(f"\n── Fetch Summary ──────────────────────────────")
        print(f"  Yahoo Live  : {yahoo_ok}/{total}")
        print(f"  Stooq Live  : {stooq_ok}/{total}")
        print(f"  Cached      : {cached_ok}/{total}")
        print(f"  Pending     : {failed_total}/{total}")

        if live == 0 and total > 0:
            yahoo_status = {"status": "Unavailable", "successCount": 0,  "totalCount": total}
        elif live < total:
            yahoo_status = {"status": "Partial",     "successCount": live, "totalCount": total}
        else:
            yahoo_status = {"status": "Healthy",     "successCount": live, "totalCount": total}

        final_output = {
            "lastUpdated":  datetime.utcnow().isoformat() + "Z",
            "marketStatus": self._market_status(now_ist),
            "yahooStatus":  yahoo_status,
            "stocks":       dashboard,
        }

        with open(_DASH_FILE, "w") as f:
            json.dump(final_output, f, indent=2)

        print(f"\n✅ dashboard.json saved — {live}/{total} live prices")
        return 0

    def _market_status(self, now_ist: datetime) -> str:
        if now_ist.weekday() >= 5:
            return "Weekend"
        open_t  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
        close_t = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        if open_t <= now_ist <= close_t:
            return "Open"
        elif now_ist < open_t:
            return "Pre-Market"
        return "Closed"


if __name__ == "__main__":
    StockDataFetcher().run()
