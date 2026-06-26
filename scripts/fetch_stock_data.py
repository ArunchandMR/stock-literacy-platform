#!/usr/bin/env python3

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas_datareader.data as web


class StockDataFetcher:
    def __init__(self):
        self.data_dir = Path("data")
        self.stocks_file = self.data_dir / "stocks.json"
        self.dashboard_file = self.data_dir / "dashboard.json"

    # ✅ Market hours (IST)
    def is_market_open(self):
        now = datetime.now(ZoneInfo("Asia/Kolkata"))

        # Weekend check
        if now.weekday() >= 5:
            return False

        start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        end = now.replace(hour=15, minute=30, second=0, microsecond=0)

        return start <= now <= end

    # ✅ Yahoo batch fetch
    def fetch_yahoo_batch(self, tickers):
        try:
            data = yf.download(
                tickers=tickers,
                period="5d",
                group_by="ticker",
                threads=False,      # ✅ CI stability
                progress=False      # ✅ cleaner logs
            )

            prices = {}

            for ticker in tickers:
                try:
                    df = data[ticker] if ticker in data else data

                    if "Close" in df and not df["Close"].empty:
                        prices[ticker] = float(df["Close"].iloc[-1])
                    else:
                        prices[ticker] = None
                except Exception:
                    prices[ticker] = None

            return prices

        except Exception as e:
            print(f"Yahoo batch failed completely: {e}")
            return {t: None for t in tickers}

    # ✅ Retry logic
    def fetch_yahoo_with_retry(self, tickers):
        for attempt in range(2):
            print(f"Yahoo attempt {attempt + 1}")

            prices = self.fetch_yahoo_batch(tickers)

            if any(v is not None for v in prices.values()):
                return prices

            time.sleep(3)

        print("Yahoo unusable → switching to fallback")
        return {t: None for t in tickers}

    # ✅ Stooq fallback
    def fetch_stooq(self, ticker):
        try:
            symbol = ticker.replace(".NS", ".IN")
            df = web.DataReader(symbol, "stooq")

            if not df.empty:
                return float(df["Close"].iloc[0])
        except Exception:
            pass

        return None

    # ✅ Load cached data
    def load_cache(self):
        if self.dashboard_file.exists():
            with open(self.dashboard_file, "r") as f:
                return json.load(f)
        return []

    def get_cached_price(self, cache, ticker, entry_price):
        for item in cache:
            if item.get("ticker") == ticker:
                return item.get("currentPrice", entry_price)
        return entry_price

    # ✅ Main execution
    def run(self):
        if not self.stocks_file.exists():
            print("ERROR: stocks.json not found")
            return 1

        with open(self.stocks_file, "r") as f:
            data = json.load(f)

        stocks = data.get("stocks", [])
        cache = self.load_cache()

        tickers = [s.get("ticker") for s in stocks if s.get("ticker")]

        market_open = self.is_market_open()

        # ✅ Generate one runId for entire batch (YOUR FIX ✅)
        run_id = int(datetime.utcnow().timestamp())

        # ✅ Yahoo fetch only during market hours
        if market_open:
            yahoo_prices = self.fetch_yahoo_with_retry(tickers)
        else:
            print("Market closed → skipping Yahoo fetch")
            yahoo_prices = {t: None for t in tickers}

        dashboard = []

        for stock in stocks:
            ticker = stock.get("ticker")
            entry_price = float(stock.get("entryPrice", 0))

            if not ticker:
                continue

            price = yahoo_prices.get(ticker)
            source = "Yahoo"
            status = "Success"

            # ✅ Fallback chain
            if price is None:
                stooq_price = self.fetch_stooq(ticker)

                if stooq_price:
                    price = stooq_price
                    source = "Stooq"
                else:
                    cached_price = self.get_cached_price(
                        cache, ticker, entry_price
                    )

                    if cached_price != entry_price:
                        price = cached_price
                        source = "Cached"
                        status = "Fallback"
                    else:
                        price = entry_price
                        source = "Entry"
                        status = "Fallback"

            # ✅ Performance calculation
            performance = 0
            if entry_price > 0:
                performance = (
                    (price - entry_price) / entry_price
                ) * 100

            dashboard.append({
                "ticker": ticker,
                "entryPrice": entry_price,
                "currentPrice": round(price, 2),
                "performance": round(performance, 2),
                "priceSource": source,
                "fetchStatus": status,
                "marketStatus": "Open" if market_open else "Closed",
                "lastUpdated": datetime.utcnow().isoformat() + "Z",
                "runId": run_id   # ✅ CONSISTENT across batch
            })

        with open(self.dashboard_file, "w") as f:
            json.dump(dashboard, f, indent=2)

        print("✅ dashboard.json updated successfully")
        return 0


if __name__ == "__main__":
    StockDataFetcher().run()
