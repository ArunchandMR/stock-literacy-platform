#!/usr/bin/env python3

import json
import sys
from datetime import datetime
from pathlib import Path

import yfinance as yf


class StockDataFetcher:
    def __init__(self):
        self.data_dir = Path("data")
        self.stocks_file = self.data_dir / "stocks.json"
        self.dashboard_file = self.data_dir / "dashboard.json"

    def fetch_current_price(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period="1d")

            if data.empty:
                print(f"WARNING: No data for {ticker}")
                return None

            price = float(data["Close"].iloc[-1])
            print(f"{ticker} price: {price}")
            return price

        except Exception as e:
            print(f"ERROR fetching {ticker}: {e}")
            return None

    def run(self):
        if not self.stocks_file.exists():
            print("ERROR: data/stocks.json not found!")
            return 1

        with open(self.stocks_file, "r") as f:
            stocks = json.load(f)

        dashboard_data = []

        for stock in stocks:
            ticker = stock.get("ticker")
            entry_price = float(stock.get("entryPrice", 0))

            current_price = self.fetch_current_price(ticker)

            if current_price is None:
                current_price = entry_price

            performance = ((current_price - entry_price) / entry_price) * 100

            dashboard_data.append({
                "ticker": ticker,
                "entryPrice": entry_price,
                "currentPrice": round(current_price, 2),
                "performance": round(performance, 2),
                "lastUpdated": datetime.utcnow().isoformat()
            })

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
