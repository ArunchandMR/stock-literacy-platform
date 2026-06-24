# UI-Based Stock Entry System - Complete Guide

## 🎉 What's New

Your stock literacy platform now includes a **user-friendly web form** for adding stocks! Non-technical users can now add stocks through a simple interface without editing JSON files directly.

## ✨ New Features Added

### 1. **Add Stock Page** (`add-stock.html`)
- Beautiful web form for entering stock details
- Automatic JSON code generation
- Copy-to-clipboard functionality
- Input validation and helpful hints
- Mobile-responsive design

### 2. **Enhanced Dashboard** (`dashboard.html`)
- **Strategy Tabs**: Filter stocks by "All", "Swing Trading", or "Long Term"
- **New Columns**:
  - Strategy badge (Swing/Long Term)
  - Entry Date & Time
  - Target Exit Range (Min-Max)
  - Stop Loss
  - Days Held (auto-calculated)
- **Enhanced Summary Cards**: Shows counts for swing vs long-term positions
- **Add Stock Button**: Quick access to add new stocks

### 3. **Updated JavaScript** (`assets/js/dashboard.js`)
- Strategy filtering logic
- Days held calculation
- Enhanced data display with all new fields
- Improved CSV export with all columns

### 4. **Updated Python Script** (`scripts/fetch_stock_data.py`)
- Handles new fields: strategy, entryTime, targetExitMin, targetExitMax, stopLoss, notes
- Preserves all enhanced data during daily updates

---

## 📝 How to Add a Stock (Step-by-Step)

### Method 1: Using the Web Form (Recommended for Non-Technical Users)

1. **Open the Add Stock Page**
   - Visit: `https://arunchandmr.github.io/stock-literacy-platform/add-stock.html`
   - Or click "Add Stock" button in the dashboard navigation

2. **Fill in the Form**
   
   **Basic Information:**
   - Stock Ticker Symbol: e.g., `RELIANCE.NS` (use .NS for NSE, .BO for BSE)
   - Company Name: e.g., `Reliance Industries`
   - Sector: Select from dropdown (Energy, Banking, IT, etc.)
   - Investment Strategy: Choose "Swing Trading" or "Long Term"

   **Entry Details:**
   - Entry Date: The date you're recommending this stock
   - Entry Time: The time of entry (auto-filled with current time)
   - Entry Price: The price at which you're recommending entry (₹)

   **Target & Risk Management:**
   - Target Exit (Min): Minimum target price (₹)
   - Target Exit (Max): Maximum target price (₹)
   - Stop Loss: Stop loss price (₹)

   **Additional Information:**
   - Discussion URL: Link to GitHub Discussion (optional)
   - Trading Notes: Why you're entering this trade (optional)

3. **Generate JSON Code**
   - Click "Generate JSON Code" button
   - The form will validate all required fields
   - JSON code will appear below the form

4. **Copy the JSON Code**
   - Click "Copy Code" button
   - The code is now in your clipboard

5. **Add to GitHub**
   - Go to your GitHub repository
   - Navigate to `data/stocks.json`
   - Click the pencil icon (Edit)
   - Find the `"stocks": [` section
   - Scroll to the last stock entry
   - Add a comma (`,`) after the last closing brace (`}`)
   - Paste your copied JSON code
   - Click "Commit changes"

6. **Wait for Update**
   - GitHub Pages will rebuild (takes 2-3 minutes)
   - Your new stock will appear on the dashboard!

---

## 📊 Example: Adding a Swing Trade

Let's say you want to add TATAMOTORS as a swing trade:

**Form Input:**
```
Stock Ticker: TATAMOTORS.NS
Company Name: Tata Motors
Sector: Auto
Strategy: Swing Trading
Entry Date: 2026-06-24
Entry Time: 10:15:00
Entry Price: 920.00
Target Exit (Min): 950.00
Target Exit (Max): 980.00
Stop Loss: 880.00
Discussion URL: https://github.com/ArunchandMR/stock-literacy-platform/discussions/5
Notes: Breakout above resistance with strong volume
```

**Generated JSON:**
```json
{
  "id": "TATAMOTORS001",
  "ticker": "TATAMOTORS.NS",
  "name": "Tata Motors",
  "sector": "Auto",
  "strategy": "swing",
  "entryDate": "2026-06-24",
  "entryTime": "10:15:00",
  "entryPrice": 920.00,
  "targetExitMin": 950.00,
  "targetExitMax": 980.00,
  "stopLoss": 880.00,
  "discussionUrl": "https://github.com/ArunchandMR/stock-literacy-platform/discussions/5",
  "notes": "Breakout above resistance with strong volume"
}
```

---

## 🔄 How the Dashboard Works

### Strategy Tabs
Click on the tabs at the top of the dashboard:
- **All Stocks**: Shows all tracked stocks
- **Swing Trading**: Shows only swing trades (short-term positions)
- **Long Term**: Shows only long-term holdings

### Dashboard Columns Explained

| Column | Description |
|--------|-------------|
| **Stock Name** | Company name, ticker, and sector |
| **Strategy** | Badge showing Swing ⚡ or Long Term 🎯 |
| **Entry Date/Time** | When the stock was recommended |
| **Entry Price** | Price at recommendation |
| **Current Price** | Live market price (updated daily) |
| **Target Range** | Your target exit price range |
| **Stop Loss** | Your stop loss level |
| **Deviance (%)** | Performance: 🟩 profit, 🟥 loss, 🟨 flat |
| **Days Held** | Auto-calculated days since entry |
| **Risk Flag** | Automated alerts: ✅ normal, ⚠️ caution, 🚨 high risk |
| **Discussion** | Link to detailed analysis |

### Summary Cards
- **Total Studies**: Total number of stocks tracked
- **Swing Trades**: Number of active swing positions
- **Long Term**: Number of long-term holdings
- **Market Flags**: Number of stocks with risk alerts

---

## 🎯 Best Practices

### For Swing Trading
- Set realistic target ranges (5-10% typically)
- Always define stop loss (3-5% below entry)
- Add detailed notes about technical setup
- Link to chart analysis in discussions
- Monitor daily for exit signals

### For Long-Term Investing
- Set wider target ranges (20-50%+)
- Set stop loss at key support levels
- Focus on fundamental analysis in notes
- Link to fundamental research in discussions
- Review monthly, not daily

### General Tips
1. **Always use .NS or .BO suffix** for Indian stocks
2. **Be specific in notes** - explain your rationale
3. **Create GitHub Discussions** for each stock with charts/analysis
4. **Update stop loss** if you trail it (edit stocks.json)
5. **Review performance weekly** using the dashboard

---

## 📁 File Structure Reference

```
stock-literacy-platform/
├── add-stock.html              # NEW: Web form for adding stocks
├── dashboard.html              # UPDATED: Enhanced with strategy tabs
├── index.html                  # Home page
├── discussions.html            # Discussion board
├── about.html                  # About page
├── assets/
│   └── js/
│       └── dashboard.js        # UPDATED: Strategy filtering logic
├── data/
│   ├── stocks.json            # Your stock list (edit this)
│   └── dashboard.json         # Auto-generated (don't edit)
└── scripts/
    └── fetch_stock_data.py    # UPDATED: Handles new fields
```

---

## 🔧 Troubleshooting

### "Failed to load dashboard data"
- Check if `data/dashboard.json` exists
- Run GitHub Actions workflow manually
- Wait 2-3 minutes for GitHub Pages to rebuild

### Stock not appearing after adding
- Did you add a comma after the previous stock?
- Is your JSON syntax correct? (use the web form to avoid errors)
- Did you commit the changes to GitHub?
- Wait 2-3 minutes for rebuild

### Strategy filter not working
- Clear browser cache (Ctrl+F5)
- Check if stock has `"strategy": "swing"` or `"strategy": "long-term"` field
- Ensure dashboard.js is uploaded to GitHub

### New columns not showing
- Clear browser cache
- Ensure you uploaded the updated dashboard.html
- Check browser console for JavaScript errors (F12)

---

## 📤 Files to Upload to GitHub

Make sure these files are uploaded to your repository:

### New Files:
- ✅ `add-stock.html` - The stock entry form

### Updated Files:
- ✅ `dashboard.html` - Enhanced dashboard with tabs
- ✅ `assets/js/dashboard.js` - Updated JavaScript
- ✅ `scripts/fetch_stock_data.py` - Updated Python script

### Data Files:
- ✅ `data/stocks.json` - Add your stocks here using the web form

---

## 🚀 Quick Start Checklist

- [ ] Upload `add-stock.html` to GitHub
- [ ] Upload updated `dashboard.html` to GitHub
- [ ] Upload updated `assets/js/dashboard.js` to GitHub
- [ ] Upload updated `scripts/fetch_stock_data.py` to GitHub
- [ ] Wait 2-3 minutes for GitHub Pages to rebuild
- [ ] Visit the Add Stock page
- [ ] Add your first stock using the web form
- [ ] Copy the generated JSON
- [ ] Edit `data/stocks.json` on GitHub
- [ ] Paste the JSON code
- [ ] Commit changes
- [ ] Wait 2-3 minutes
- [ ] Check dashboard - your stock should appear!
- [ ] Click strategy tabs to filter
- [ ] Celebrate! 🎉

---

## 💡 Pro Tips

1. **Bookmark the Add Stock page** for quick access
2. **Create a GitHub Discussion** before adding a stock
3. **Use consistent naming** for sectors
4. **Add entry time** for intraday precision
5. **Export to CSV** regularly for backup
6. **Review "Days Held"** to track position duration
7. **Use strategy tabs** to focus on specific trading styles
8. **Update stop loss** as price moves in your favor

---

## 📞 Need Help?

If you encounter issues:
1. Check this guide first
2. Review the Troubleshooting section
3. Check browser console for errors (F12)
4. Verify all files are uploaded to GitHub
5. Clear browser cache and try again

---

## 🎓 Educational Disclaimer

Remember: This platform is for educational purposes only. All stock recommendations should be discussed in GitHub Discussions with proper analysis. Always do your own research and consult a certified financial advisor before investing.

---

**Made with ❤️ for Financial Literacy**

Last Updated: June 24, 2026