#!/usr/bin/env python3

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yfinance as yf


class StockDataFetcher:
    def __init__(self):
        self.data_dir = Path("data")
        self.stocks_file = self.data_dir / "stocks.json"
        self.dashboard_file = self.data_dir / "dashboard.json"

    def safe_fetch_price(self, ticker, fallback_price):
        """
        Try to fetch live price.
        If fails → return fallback (previous or entry)
        """
        try:
            stock = yf.Ticker(ticker)

            # Try history (most stable)
            data = stock.history(period="5d")

            if not data.empty:
                price = float(data["Close"].iloc[-1])
                print(f"{ticker} price: {price}")
                return price

            print(f"WARNING: No data for {ticker}, using fallback")
            return fallback_price

        except Exception as e:
            print(f"API FAILED for {ticker}: {e}")
            return fallback_price

    def load_previous_dashboard(self):
        if self.dashboard_file.exists():
            with open(self.dashboard_file, "r") as f:
                return json.load(f)
        return []

    def get_previous_price(self, previous_data, ticker, entry_price):
        for item in previous_data:
            if item.get("ticker") == ticker:
                return item.get("currentPrice", entry_price)
        return entry_price

    def run(self):
        if not self.stocks_file.exists():
            print("ERROR: data/stocks.json not found!")
            return 1

        with open(self.stocks_file, "r") as f:
            stocks_data = json.load(f)

        # ✅ FIX: handle your format
        stocks = stocks_data.get("stocks", [])

        previous_data = self.load_previous_dashboard()

        dashboard_data = []

        for stock in stocks:
            time.sleep(2)  # ✅ reduce API blocking

            ticker = stock.get("ticker")
            entry_price = float(stock.get("entryPrice", 0))

            if not ticker:
                continue

            # ✅ Get previous value (important fallback)
            previous_price = self.get_previous_price(
                previous_data, ticker, entry_price
            )

            # ✅ Fetch safely
            current_price = self.safe_fetch_price(
                ticker, previous_price
            )

            # ✅ Compute performance
            performance = 0
            if entry_price > 0:
                performance = ((current_price - entry_price) / entry_price) * 100

            dashboard_data.append({
                "ticker": ticker,
                "entryPrice": entry_price,
                "currentPrice": round(current_price, 2),
                "performance": round(performance, 2),
                "lastUpdated": datetime.utcnow().isoformat()
            })

        # ✅ Always write file
        with open(self.dashboard_file, "w") as f:
            json.dump(dashboard_data, f, indent=2)

        print("✅ dashboard.json updated successfully")
        return 0


def main():
    try:
        fetcher = StockDataFetcher()
        return fetcher.run()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())