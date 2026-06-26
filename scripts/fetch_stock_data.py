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

    def fetch_current_price(self, ticker):
        # ✅ Skip invalid ticker
        if not ticker or ticker.upper() == "STOCKS":
            print(f"Skipping invalid ticker: {ticker}")
            return None

        try:
            stock = yf.Ticker(ticker)

            # ✅ Method 1: fast_info
            try:
                if hasattr(stock, "fast_info"):
                    fast = stock.fast_info
                    if fast and "last_price" in fast:
                        price = fast["last_price"]
                        if price:
                            print(f"{ticker} price (fast_info): {price}")
                            return float(price)
            except Exception:
                pass

            # ✅ Method 2: history fallback
            try:
                data = stock.history(period="5d")
                if not data.empty:
                    price = float(data["Close"].iloc[-1])
                    print(f"{ticker} price (history): {price}")
                    return price
            except Exception:
                pass

            print(f"WARNING: No data for {ticker}")
            return None

        except Exception as e:
            print(f"ERROR fetching {ticker}: {e}")
            return None

    def run(self):
        if not self.stocks_file.exists():
            print("ERROR: data/stocks.json not found!")
            return 1

        with open(self.stocks_file, "r") as f:
            stocks_data = json.load(f)

        # ✅ FIX: handle both formats
        if isinstance(stocks_data, dict) and "stocks" in stocks_data:
            stocks = stocks_data["stocks"]
        else:
            stocks = stocks_data

        dashboard_data = []

        for stock in stocks:
            time.sleep(2)  # ✅ prevent rate limiting

            # ✅ Handle formats
            if isinstance(stock, dict):
                ticker = stock.get("ticker")
                entry_price = float(stock.get("entryPrice", 0))
            else:
                ticker = stock
                entry_price = 0

            if not ticker:
                print("Skipping empty ticker")
                continue

            current_price = self.fetch_current_price(ticker)

            if current_price is None:
                current_price = entry_price

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

        # ✅ Write output
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
