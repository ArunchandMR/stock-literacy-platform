#!/usr/bin/env python3
"""
Risk Analyzer - Automated Risk Flag Detection
Detects circuit breakers, volume spikes, and volatility issues
"""

import yfinance as yf
from datetime import datetime, timedelta


def analyze_risk(ticker, current_price, entry_price, config):
    """
    Analyze stock for risk flags
    
    Args:
        ticker: Stock ticker symbol
        current_price: Current market price
        entry_price: Original entry price
        config: Configuration dict with thresholds
    
    Returns:
        tuple: (risk_flag_message, risk_level)
    """
    
    # Default thresholds
    circuit_threshold = config.get('circuit_threshold', 5.0)  # 5% circuit
    volume_spike_multiplier = config.get('volume_spike_multiplier', 3.0)  # 3x avg volume
    volatility_threshold = config.get('volatility_threshold', 5.0)  # 5% intraday
    
    try:
        stock = yf.Ticker(ticker)
        
        # Get historical data (last 30 days for averages)
        hist = stock.history(period='30d')
        
        if hist.empty:
            return "Data Unavailable", "low"
        
        # Get today's data
        today = hist.iloc[-1]
        
        # Calculate price change percentage
        price_change_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check 1: Circuit Breaker Detection
        if len(hist) >= 2:
            prev_close = hist.iloc[-2]['Close']
            daily_change_pct = ((today['Close'] - prev_close) / prev_close) * 100
            
            # Lower circuit (stock falling)
            if daily_change_pct <= -circuit_threshold:
                return "🚨 Near Lower Circuit", "high"
            
            # Upper circuit (stock rising rapidly)
            if daily_change_pct >= circuit_threshold * 2:  # 10% upper circuit
                return "⚠️ Near Upper Circuit", "medium"
        
        # Check 2: Volume Spike Detection
        if len(hist) >= 10:
            avg_volume = hist['Volume'][:-1].mean()  # Exclude today
            today_volume = today['Volume']
            
            if today_volume > avg_volume * volume_spike_multiplier:
                return "⚠️ Volume Spike Detected", "medium"
        
        # Check 3: Intraday Volatility
        if 'High' in today and 'Low' in today:
            intraday_range_pct = ((today['High'] - today['Low']) / today['Low']) * 100
            
            if intraday_range_pct > volatility_threshold:
                return "⚠️ High Volatility", "medium"
        
        # Check 4: Significant Loss from Entry
        if price_change_pct < -10:
            return "🚨 Significant Loss", "high"
        
        # Check 5: 52-Week Low Proximity
        if len(hist) >= 252:  # ~1 year of trading days
            week_52_low = hist['Low'].min()
            if current_price <= week_52_low * 1.05:  # Within 5% of 52-week low
                return "⚠️ Near 52-Week Low", "medium"
        
        # Check 6: 52-Week High Proximity
        if len(hist) >= 252:
            week_52_high = hist['High'].max()
            if current_price >= week_52_high * 0.95:  # Within 5% of 52-week high
                return "✅ Near 52-Week High", "low"
        
        # All clear
        return "✅ Normal Volume", "low"
        
    except Exception as e:
        print(f"  Risk analysis error for {ticker}: {e}")
        return "Analysis Failed", "low"


def get_volume_analysis(ticker, days=30):
    """
    Get detailed volume analysis
    
    Args:
        ticker: Stock ticker symbol
        days: Number of days to analyze
    
    Returns:
        dict: Volume statistics
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f'{days}d')
        
        if hist.empty:
            return None
        
        return {
            'current_volume': hist['Volume'].iloc[-1],
            'avg_volume': hist['Volume'].mean(),
            'max_volume': hist['Volume'].max(),
            'min_volume': hist['Volume'].min(),
            'volume_ratio': hist['Volume'].iloc[-1] / hist['Volume'].mean()
        }
    except:
        return None


def get_price_volatility(ticker, days=30):
    """
    Calculate price volatility metrics
    
    Args:
        ticker: Stock ticker symbol
        days: Number of days to analyze
    
    Returns:
        dict: Volatility statistics
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f'{days}d')
        
        if hist.empty:
            return None
        
        # Calculate daily returns
        hist['Returns'] = hist['Close'].pct_change()
        
        return {
            'volatility': hist['Returns'].std() * 100,  # Standard deviation as %
            'max_gain': hist['Returns'].max() * 100,
            'max_loss': hist['Returns'].min() * 100,
            'avg_daily_change': hist['Returns'].mean() * 100
        }
    except:
        return None


if __name__ == '__main__':
    # Test the risk analyzer
    print("Testing Risk Analyzer...")
    
    test_stocks = [
        ('RELIANCE.NS', 2720.00, 2450.00),
        ('INFY.NS', 1595.00, 1600.00),
        ('TATAMOTORS.NS', 845.00, 910.00)
    ]
    
    config = {
        'circuit_threshold': 5.0,
        'volume_spike_multiplier': 3.0,
        'volatility_threshold': 5.0
    }
    
    for ticker, current, entry in test_stocks:
        print(f"\n{ticker}:")
        print(f"  Entry: ₹{entry:.2f}, Current: ₹{current:.2f}")
        
        risk_flag, risk_level = analyze_risk(ticker, current, entry, config)
        print(f"  Risk Flag: {risk_flag} (Level: {risk_level})")
        
        volume = get_volume_analysis(ticker)
        if volume:
            print(f"  Volume Ratio: {volume['volume_ratio']:.2f}x")
        
        volatility = get_price_volatility(ticker)
        if volatility:
            print(f"  Volatility: {volatility['volatility']:.2f}%")

# Made with Bob
