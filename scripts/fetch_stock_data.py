#!/usr/bin/env python3
"""
Stock Data Fetcher - GitHub Actions Automation Script
Fetches current stock prices, calculates deviance, and generates dashboard.json
Zero-cost solution using yfinance (no API key required)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

# Import risk analyzer
try:
    from risk_analyzer import analyze_risk
except ImportError:
    print("WARNING: risk_analyzer.py not found. Risk analysis will be skipped.")
    analyze_risk = None

# Import sentiment analyzer (optional - requires Gemini API)
try:
    from sentiment_analyzer import analyze_sentiment
except ImportError:
    print("INFO: sentiment_analyzer.py not found. Sentiment analysis will be skipped.")
    analyze_sentiment = None


class StockDataFetcher:
    """Main class for fetching and processing stock data"""
    
    def __init__(self, data_dir='data'):
        self.data_dir = Path(data_dir)
        self.stocks_file = self.data_dir / 'stocks.json'
        self.dashboard_file = self.data_dir / 'dashboard.json'
        self.config_file = self.data_dir / 'config.json'
        
    def load_stocks(self):
        """Load stock list from stocks.json"""
        try:
            with open(self.stocks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('stocks', [])
        except FileNotFoundError:
            print(f"ERROR: {self.stocks_file} not found!")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in {self.stocks_file}: {e}")
            sys.exit(1)
    
    def load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"WARNING: {self.config_file} not found. Using defaults.")
            return {}
        except json.JSONDecodeError:
            print(f"WARNING: Invalid JSON in {self.config_file}. Using defaults.")
            return {}
    
    def fetch_current_price(self, ticker):
        """Fetch current price for a stock using yfinance"""
        try:
            stock = yf.Ticker(ticker)
            
            # Try to get current price from multiple sources
            # 1. Try fast_info (fastest)
            try:
                current_price = stock.fast_info.get('lastPrice')
                if current_price and current_price > 0:
                    return float(current_price)
            except:
                pass
            
            # 2. Try info dict
            try:
                info = stock.info
                current_price = info.get('currentPrice') or info.get('regularMarketPrice')
                if current_price and current_price > 0:
                    return float(current_price)
            except:
                pass
            
            # 3. Try history (most reliable but slower)
            hist = stock.history(period='1d')
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            
            print(f"WARNING: Could not fetch price for {ticker}")
            return None
            
        except Exception as e:
            print(f"ERROR fetching {ticker}: {e}")
            return None
    
    def calculate_deviance(self, entry_price, current_price):
        """Calculate price deviance percentage"""
        if not entry_price or not current_price:
            return 0.0, "0.00%"
        
        deviance = ((current_price - entry_price) / entry_price) * 100
        sign = '+' if deviance >= 0 else ''
        deviance_percent = f"{sign}{deviance:.2f}%"
        
        return deviance, deviance_percent
    
    def process_stocks(self, stocks, config):
        """Process all stocks and generate dashboard data"""
        processed_stocks = []
        total_deviance = 0
        active_flags = 0
        successful_fetches = 0
        
        print(f"\nProcessing {len(stocks)} stocks...")
        
        for i, stock in enumerate(stocks, 1):
            print(f"[{i}/{len(stocks)}] Processing {stock['ticker']}...", end=' ')
            
            # Fetch current price
            current_price = self.fetch_current_price(stock['ticker'])
            
            if current_price is None:
                print("FAILED")
                # Keep entry price as current if fetch fails
                current_price = stock['entryPrice']
            else:
                print(f"₹{current_price:.2f}")
                successful_fetches += 1
            
            # Calculate deviance
            deviance, deviance_percent = self.calculate_deviance(
                stock['entryPrice'], 
                current_price
            )
            
            # Analyze risk (if available)
            risk_flag = "Normal Volume"
            risk_level = "low"
            
            if analyze_risk:
                try:
                    risk_flag, risk_level = analyze_risk(
                        stock['ticker'], 
                        current_price, 
                        stock['entryPrice'],
                        config
                    )
                except Exception as e:
                    print(f"  WARNING: Risk analysis failed: {e}")
            
            # Analyze sentiment (if available and API key configured)
            if analyze_sentiment and config.get('gemini_api_key'):
                try:
                    sentiment_flag = analyze_sentiment(
                        stock['name'], 
                        stock['ticker'],
                        config
                    )
                    if sentiment_flag:
                        risk_flag = sentiment_flag
                        risk_level = 'medium'
                except Exception as e:
                    print(f"  WARNING: Sentiment analysis failed: {e}")
            
            # Count active flags
            if risk_level in ['medium', 'high']:
                active_flags += 1
            
            # Build processed stock data with enhanced fields
            processed_stock = {
                'id': stock.get('id', f"STK{i:03d}"),
                'ticker': stock['ticker'],
                'name': stock['name'],
                'sector': stock.get('sector', 'N/A'),
                'strategy': stock.get('strategy', 'long-term'),
                'entryDate': stock['entryDate'],
                'entryTime': stock.get('entryTime', ''),
                'entryPrice': stock['entryPrice'],
                'currentPrice': round(current_price, 2),
                'targetExitMin': stock.get('targetExitMin'),
                'targetExitMax': stock.get('targetExitMax'),
                'stopLoss': stock.get('stopLoss'),
                'deviance': round(deviance, 2),
                'deviancePercent': deviance_percent,
                'riskFlag': risk_flag,
                'riskLevel': risk_level,
                'discussionUrl': stock.get('discussionUrl', '#'),
                'notes': stock.get('notes', ''),
                'lastChecked': datetime.now(timezone.utc).isoformat()
            }
            
            processed_stocks.append(processed_stock)
            total_deviance += deviance
        
        # Calculate summary
        avg_performance = total_deviance / len(stocks) if stocks else 0
        
        summary = {
            'totalStocks': len(stocks),
            'avgPerformance': round(avg_performance, 2),
            'activeFlags': active_flags,
            'successfulFetches': successful_fetches,
            'failedFetches': len(stocks) - successful_fetches
        }
        
        return processed_stocks, summary
    
    def save_dashboard(self, stocks, summary):
        """Save processed data to dashboard.json"""
        dashboard_data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'summary': summary,
            'stocks': stocks
        }
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Write dashboard.json
        with open(self.dashboard_file, 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Dashboard data saved to {self.dashboard_file}")
        print(f"  Total Stocks: {summary['totalStocks']}")
        print(f"  Avg Performance: {summary['avgPerformance']:.2f}%")
        print(f"  Active Flags: {summary['activeFlags']}")
        print(f"  Successful Fetches: {summary['successfulFetches']}/{summary['totalStocks']}")
    
    def run(self):
        """Main execution flow"""
        print("=" * 60)
        print("Stock Data Fetcher - GitHub Actions Automation")
        print("=" * 60)
        
        # Load configuration
        config = self.load_config()
        
        # Load stocks
        stocks = self.load_stocks()
        if not stocks:
            print("ERROR: No stocks found in stocks.json")
            sys.exit(1)
        
        # Process stocks
        processed_stocks, summary = self.process_stocks(stocks, config)
        
        # Save dashboard
        self.save_dashboard(processed_stocks, summary)
        
        print("\n" + "=" * 60)
        print("✓ Stock data fetch completed successfully!")
        print("=" * 60)
        
        return 0


def main():
    """Entry point"""
    try:
        fetcher = StockDataFetcher()
        return fetcher.run()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        return 1
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
