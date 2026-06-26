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
                threads=False,
                progress=False
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

    # ✅ Retry + health tracking
    def fetch_yahoo_with_retry(self, tickers):
        final_prices = None

        for attempt in range(2):
            print(f"Yahoo attempt {attempt + 1}")

            prices = self.fetch_yahoo_batch(tickers)

            success_count = sum(1 for v in prices.values() if v is not None)

            print(f"Yahoo success count: {success_count}/{len(tickers)}")

            if success_count > 0:
                final_prices = prices
                break

            time.sleep(3)

        # ✅ Determine status (UPDATED TERMINOLOGY ✅)
        if final_prices:
            success_count = sum(1 for v in final_prices.values() if v is not None)

            if success_count == len(tickers):
                status = "Healthy"
            elif success_count > 0:
                status = "Partial"
            else:
                status = "Unavailable"

            return final_prices, {
                "status": status,
                "successCount": success_count,
                "totalCount": len(tickers)
            }

        # Completely failed
        print("Yahoo unavailable")
        return {t: None for t in tickers}, {
            "status": "Unavailable",
            "successCount": 0,
            "totalCount": len(tickers)
        }

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

    # ✅ Cache
    def load_cache(self):
        if self.dashboard_file.exists():
            with open(self.dashboard_file, "r") as f:
                return json.load(f).get("stocks", [])
        return []

    def get_cached_price(self, cache, ticker, entry):
        for item in cache:
            if item.get("ticker") == ticker:
                return item.get("currentPrice", entry)
        return entry

    # ✅ Main execution
    def run(self):
        if not self.stocks_file.exists():
            print("stocks.json missing")
            return 1

        with open(self.stocks_file, "r") as f:
            data = json.load(f)

        stocks = data.get("stocks", [])
        cache = self.load_cache()

        tickers = [s.get("ticker") for s in stocks if s.get("ticker")]

        market_open = self.is_market_open()
        run_id = int(datetime.utcnow().timestamp())

        # ✅ Yahoo fetch only in market hours
        if market_open:
            yahoo_prices, yahoo_info = self.fetch_yahoo_with_retry(tickers)
        else:
            print("Market closed → skipping Yahoo")
            yahoo_prices = {t: None for t in tickers}
            yahoo_info = {
                "status": "Closed",
                "successCount": 0,
                "totalCount": len(tickers)
            }

        dashboard = []

        for stock in stocks:
            ticker = stock.get("ticker")
            entry = float(stock.get("entryPrice", 0))

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
                    cached = self.get_cached_price(cache, ticker, entry)

                    if cached != entry:
                        price = cached
                        source = "Cached"
                        status = "Fallback"
                    else:
                        price = entry
                        source = "Entry"
                        status = "Fallback"

            performance = 0
            if entry > 0:
                performance = ((price - entry) / entry) * 100

            dashboard.append({
                "ticker": ticker,
                "entryPrice": entry,
                "currentPrice": round(price, 2),
                "performance": round(performance, 2),
                "priceSource": source,
                "fetchStatus": status,
                "runId": run_id
            })

        # ✅ FINAL STRUCTURE (YOUR DESIGN ✅)
        final_output = {
            "lastUpdated": datetime.utcnow().isoformat() + "Z",
            "yahooStatus": yahoo_info,
            "marketStatus": "Open" if market_open else "Closed",
            "stocks": dashboard
        }

        with open(self.dashboard_file, "w") as f:
            json.dump(final_output, f, indent=2)

        print("✅ dashboard.json updated")
        return 0


if __name__ == "__main__":
    StockDataFetcher().run()
