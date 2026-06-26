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

        start = now.replace(hour=9, minute=15, second=0)
        end = now.replace(hour=15, minute=30, second=0)

        return start <= now <= end

    # ✅ Yahoo batch fetch (SAFE)
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
                except:
                    prices[ticker] = None

            return prices

        except Exception as e:
            print(f"Yahoo failed completely: {e}")
            return {t: None for t in tickers}

    # ✅ Retry (max 2)
    def fetch_yahoo_with_retry(self, tickers):
        for i in range(2):
            print(f"Yahoo attempt {i+1}")

            prices = self.fetch_yahoo_batch(tickers)

            if any(v is not None for v in prices.values()):
                return prices

            time.sleep(3)

        print("Yahoo unusable → switching to fallback")
        return {t: None for t in tickers}

    # ✅ Stooq fallback (per stock)
    def fetch_stooq(self, ticker):
        try:
            symbol = ticker.replace(".NS", ".IN")
            df = web.DataReader(symbol, "stooq")

            if not df.empty:
                price = float(df["Close"].iloc[0])
                return price
        except:
            pass

        return None

    # ✅ Cache
    def load_cache(self):
        if self.dashboard_file.exists():
            with open(self.dashboard_file, "r") as f:
                return json.load(f)
        return []

    def get_cached_price(self, cache, ticker, entry):
        for d in cache:
            if d.get("ticker") == ticker:
                return d.get("currentPrice", entry)
        return entry

    # ✅ MAIN
    def run(self):
        if not self.stocks_file.exists():
            print("stocks.json missing")
            return 1

        with open(self.stocks_file) as f:
            stocks_data = json.load(f)

        stocks = stocks_data.get("stocks", [])
        cache = self.load_cache()

        tickers = [s.get("ticker") for s in stocks if s.get("ticker")]

        market_open = self.is_market_open()

        # ✅ Yahoo only if market open
        if market_open:
            yahoo_prices = self.fetch_yahoo_with_retry(tickers)
        else:
            print("Market closed → skip Yahoo")
            yahoo_prices = {t: None for t in tickers}

        dashboard = []

        for stock in stocks:
            ticker = stock.get("ticker")
            entry = float(stock.get("entryPrice", 0))

            if not ticker:
                continue

            price = yahoo_prices.get(ticker)
            source = "Yahoo"
            status = "Success"

            # ✅ fallback chain
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
                "marketStatus": "Open" if market_open else "Closed",
                "lastUpdated": datetime.utcnow().isoformat()
            })

        with open(self.dashboard_file, "w") as f:
            json.dump(dashboard, f, indent=2)

        print("✅ dashboard.json updated")
        return 0


if __name__ == "__main__":
    StockDataFetcher().run()