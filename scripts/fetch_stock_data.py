#!/usr/bin/env python3
"""
Stock Data Fetcher — Single-batch, fast, CI-safe
-------------------------------------------------
Strategy: ONE yf.download() call for all tickers at once.

Why this works better than per-ticker loops:
  • Single HTTP session = 1 cookie/crumb handshake with Yahoo
  • No per-ticker delay needed → runtime ~20-30s instead of 4+ minutes
  • multi_level_index=False (yfinance ≥ 0.2.50) gives a clean flat DataFrame
  • auto_adjust=True gives adjusted close prices directly

Fallback chain (only for tickers that fail in the batch):
  1. Retry that single ticker with Ticker.history(period='2d') — different endpoint
  2. Last-known cached price from previous dashboard.json run
  3. Entry price shown as "Pending" (never crashes the dashboard)
"""

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
_DATA_DIR    = _SCRIPT_DIR.parent / "data"
_STOCKS_FILE = _DATA_DIR / "stocks.json"
_DASH_FILE   = _DATA_DIR / "dashboard.json"


class StockDataFetcher:

    def __init__(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── ONE batch download for all tickers ────────────────────────────────────
    def _batch_download(self, tickers: list[str]) -> dict[str, float | None]:
        """
        Single yf.download() call — ONE Yahoo session, ONE crumb handshake.
        Returns {ticker: last_close_price or None}.
        """
        print(f"  📡 Batch downloading {len(tickers)} tickers in one call…")
        prices: dict[str, float | None] = {t: None for t in tickers}

        try:
            # multi_level_index=False (yfinance ≥ 0.2.50) gives columns like
            # Close_RELIANCE.NS  instead of a MultiIndex — much easier to parse.
            df = yf.download(
                tickers=" ".join(tickers),
                period="5d",
                auto_adjust=True,
                progress=False,
                threads=True,           # parallel inside yfinance — still 1 session
                multi_level_index=False,
            )

            if df.empty:
                print("  ⚠ Batch download returned empty DataFrame")
                return prices

            # With multi_level_index=False and multiple tickers, columns are
            # ("Close", "TICKER") tuples flattened to "Close_TICKER" strings.
            # With a single ticker they're just "Close", "Open", etc.
            close_cols = [c for c in df.columns if str(c).startswith("Close")]

            for ticker in tickers:
                try:
                    # Try flat-column name first (multi-ticker)
                    col = f"Close_{ticker}"
                    if col in df.columns:
                        series = df[col].dropna()
                    elif "Close" in df.columns:
                        # Single-ticker fallback
                        series = df["Close"].dropna()
                    else:
                        continue

                    if not series.empty:
                        prices[ticker] = round(float(series.iloc[-1]), 2)
                except Exception as e:
                    print(f"    parse error for {ticker}: {e}")

        except Exception as e:
            print(f"  ✗ Batch download failed: {e}")

        ok = sum(1 for v in prices.values() if v is not None)
        print(f"  ✓ Batch result: {ok}/{len(tickers)} prices retrieved")
        return prices

    # ── Single-ticker retry (for batch misses only) ───────────────────────────
    def _retry_single(self, ticker: str) -> float | None:
        """
        Used ONLY for tickers that returned None from the batch.
        Uses Ticker.history (different Yahoo endpoint) with a short wait.
        """
        try:
            time.sleep(2)   # brief pause before retry — single ticker only
            hist = yf.Ticker(ticker).history(period="2d", auto_adjust=True)
            if not hist.empty:
                val = hist["Close"].dropna()
                if not val.empty:
                    return round(float(val.iloc[-1]), 2)
        except Exception as e:
            print(f"    retry failed for {ticker}: {e}")
        return None

    # ── Load cached prices from last run ─────────────────────────────────────
    def _load_cache(self) -> dict[str, float]:
        if not _DASH_FILE.exists():
            return {}
        try:
            with open(_DASH_FILE) as f:
                data = json.load(f)
            stocks = data.get("stocks", []) if isinstance(data, dict) else data
            return {
                s["ticker"]: float(s["currentPrice"])
                for s in stocks
                if s.get("ticker") and s.get("currentPrice")
            }
        except Exception:
            return {}

    # ── Main ──────────────────────────────────────────────────────────────────
    def run(self) -> int:
        if not _STOCKS_FILE.exists():
            print(f"ERROR: {_STOCKS_FILE} not found")
            return 1

        with open(_STOCKS_FILE) as f:
            raw = json.load(f)

        stocks  = raw.get("stocks", [])
        cache   = self._load_cache()
        run_id  = int(datetime.utcnow().timestamp())
        ist     = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(ist)

        tickers = [s["ticker"].strip() for s in stocks if s.get("ticker")]

        print(f"▶ Stock Dashboard Fetcher — {now_ist.strftime('%Y-%m-%d %H:%M IST')}")
        print(f"  Stocks: {len(stocks)} | Cache entries: {len(cache)}")

        # ── Step 1: ONE batch call ────────────────────────────────────────────
        batch_prices = self._batch_download(tickers)

        # ── Step 2: Retry only the misses (usually 0-2 tickers) ──────────────
        misses = [t for t, v in batch_prices.items() if v is None]
        if misses:
            print(f"  🔄 Retrying {len(misses)} missed ticker(s): {misses}")
            for ticker in misses:
                retry_price = self._retry_single(ticker)
                if retry_price:
                    batch_prices[ticker] = retry_price
                    print(f"    ✓ Retry success: {ticker} = ₹{retry_price}")
                else:
                    print(f"    ✗ Retry failed: {ticker}")

        # ── Step 3: Build dashboard records ───────────────────────────────────
        dashboard    = []
        yahoo_ok     = 0
        cached_ok    = 0
        pending_total = 0

        for stock in stocks:
            ticker      = stock.get("ticker", "").strip()
            entry_price = float(stock.get("entryPrice") or 0)
            if not ticker:
                continue

            price  = batch_prices.get(ticker)
            source = "Yahoo"
            status = "Live"

            if price and price > 0:
                yahoo_ok += 1
            elif ticker in cache and cache[ticker] > 0:
                price  = cache[ticker]
                source = "Cached"
                status = "Cached"
                cached_ok += 1
                print(f"  [{ticker}] using cached ₹{price}")
            else:
                price  = entry_price
                source = "Entry"
                status = "Pending"
                pending_total += 1
                print(f"  [{ticker}] no data — showing entry price")

            performance = 0.0
            if entry_price > 0 and price:
                performance = round(((price - entry_price) / entry_price) * 100, 2)

            dashboard.append({
                "id":            stock.get("id", ""),
                "ticker":        ticker,
                "name":          stock.get("name", ""),
                "sector":        stock.get("sector", ""),
                "strategy":      stock.get("strategy", ""),
                "entryDate":     stock.get("entryDate", ""),
                "entryPrice":    entry_price,
                "currentPrice":  round(price, 2),
                "targetExitMin": stock.get("targetExitMin"),
                "targetExitMax": stock.get("targetExitMax"),
                "stopLoss":      stock.get("stopLoss"),
                "performance":   performance,
                "priceSource":   source,
                "fetchStatus":   status,
                "discussionUrl": stock.get("discussionUrl", ""),
                "notes":         stock.get("notes", ""),
                "runId":         run_id,
            })

        # ── Step 4: Summary + save ─────────────────────────────────────────────
        total = len(dashboard)
        live  = yahoo_ok

        print(f"\n── Fetch Summary ─────────────────────────────")
        print(f"  Live (Yahoo) : {yahoo_ok}/{total}")
        print(f"  Cached       : {cached_ok}/{total}")
        print(f"  Pending      : {pending_total}/{total}")

        if live == total:
            ystat = "Healthy"
        elif live > 0:
            ystat = "Partial"
        else:
            ystat = "Unavailable"

        output = {
            "lastUpdated":  datetime.utcnow().isoformat() + "Z",
            "marketStatus": self._market_label(now_ist),
            "yahooStatus":  {"status": ystat, "successCount": live, "totalCount": total},
            "stocks":       dashboard,
        }

        with open(_DASH_FILE, "w") as f:
            json.dump(output, f, indent=2)

        print(f"\n✅ dashboard.json saved — {live}/{total} live prices")
        return 0

    def _market_label(self, now_ist: datetime) -> str:
        if now_ist.weekday() >= 5:
            return "Weekend"
        o = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
        c = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        if o <= now_ist <= c:
            return "Open"
        return "Pre-Market" if now_ist < o else "Closed"


if __name__ == "__main__":
    StockDataFetcher().run()
