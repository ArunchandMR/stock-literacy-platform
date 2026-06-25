/**
 * Stock Performance Dashboard - Main Logic
 * Source of truth: data/stocks.json  (static fields: ticker, entryPrice, strategy, targets, stopLoss)
 * Live fields computed in browser:   currentPrice, deviance, deviancePercent, riskFlag
 *
 * Live price strategy (in order, first success wins):
 *   1. query2.finance.yahoo.com  (direct, works in most browsers)
 *   2. query1.finance.yahoo.com  (alternate subdomain)
 *   3. allorigins.win CORS proxy → query2 (works when direct requests are blocked)
 */

let dashboardData = null;   // { stocks: [...], lastUpdated }
let filteredStocks = [];
let currentStrategy = 'all';

// ─── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

// ─── Data Loading ─────────────────────────────────────────────────────────────
/**
 * Load stocks.json (the single source of truth) then immediately fetch live prices.
 * dashboard.json is only used as a fallback if stocks.json is unavailable.
 */
async function loadDashboardData() {
    try {
        showLoadingState();

        const ts = Date.now();
        // PRIMARY: read stocks.json — contains entryPrice, strategy, targets, stopLoss
        let response = await fetch(`data/stocks.json?t=${ts}`);
        if (!response.ok) throw new Error(`stocks.json HTTP ${response.status}`);

        const raw = await response.json();
        const stocks = raw.stocks || [];

        // Build internal dashboardData — currentPrice starts as entryPrice (will be replaced by live)
        dashboardData = {
            lastUpdated: new Date().toISOString(),
            stocks: stocks.map(s => ({
                ...s,
                currentPrice: s.entryPrice,          // placeholder until live fetch
                deviance: 0,
                deviancePercent: '+0.00%',
                riskFlag: 'Fetching live price…',
                riskLevel: 'low',
                lastChecked: new Date().toISOString()
            }))
        };

        filteredStocks = [...dashboardData.stocks];
        renderDashboard();
        hideLoadingState();

        // Fetch live prices in background — re-renders table when done
        await fetchLivePrices();

    } catch (err) {
        console.error('Error loading dashboard data:', err);
        showErrorState();
    }
}

// ─── Live Price Fetching ──────────────────────────────────────────────────────
/**
 * Fetch a single stock price via Yahoo Finance, trying 3 endpoints in order.
 * Returns the numeric price or null on total failure.
 */
async function fetchYahooPrice(ticker) {
    const encodedTicker = encodeURIComponent(ticker);
    const params = `interval=1d&range=1d`;

    // Endpoint list — tried in order until one succeeds
    const endpoints = [
        `https://query2.finance.yahoo.com/v8/finance/chart/${encodedTicker}?${params}`,
        `https://query1.finance.yahoo.com/v8/finance/chart/${encodedTicker}?${params}`,
        `https://api.allorigins.win/raw?url=${encodeURIComponent(`https://query2.finance.yahoo.com/v8/finance/chart/${encodedTicker}?${params}`)}`
    ];

    for (const url of endpoints) {
        try {
            const res = await fetch(url, { cache: 'no-store' });
            if (!res.ok) continue;
            const data = await res.json();
            const meta = data?.chart?.result?.[0]?.meta;
            if (!meta) continue;
            const price = meta.regularMarketPrice || meta.previousClose;
            if (price && price > 0) return parseFloat(price.toFixed(2));
        } catch (_) {
            // try next endpoint
        }
    }
    return null;
}

/**
 * Fetch live prices for all stocks in batches of 5.
 * Updates currentPrice, deviance, deviancePercent, riskFlag on each stock in-place.
 * Re-renders the table after every batch so prices appear progressively.
 */
async function fetchLivePrices() {
    if (!dashboardData?.stocks?.length) return;

    const stocks = dashboardData.stocks;
    const BATCH = 5;
    let anyUpdated = false;

    for (let i = 0; i < stocks.length; i += BATCH) {
        const batch = stocks.slice(i, i + BATCH);

        await Promise.all(batch.map(async (stock) => {
            const livePrice = await fetchYahooPrice(stock.ticker);

            if (livePrice === null) {
                // Keep entry price; mark as unavailable
                stock.currentPrice = stock.entryPrice;
                stock.deviance = 0;
                stock.deviancePercent = '+0.00%';
                stock.riskFlag = 'Price unavailable';
                stock.riskLevel = 'low';
                return;
            }

            stock.currentPrice = livePrice;

            // Deviance = ((current - entry) / entry) × 100
            const dev = ((livePrice - stock.entryPrice) / stock.entryPrice) * 100;
            stock.deviance = parseFloat(dev.toFixed(2));
            stock.deviancePercent = `${dev >= 0 ? '+' : ''}${dev.toFixed(2)}%`;

            // Risk flag logic
            if (dev <= -5) {
                stock.riskFlag = 'Below Stop Loss Zone';
                stock.riskLevel = 'high';
            } else if (dev <= -2) {
                stock.riskFlag = 'Approaching Stop Loss';
                stock.riskLevel = 'medium';
            } else if (dev >= 15) {
                stock.riskFlag = 'Near/Above Target';
                stock.riskLevel = 'low';
            } else if (dev >= 10) {
                stock.riskFlag = 'Near Target Zone';
                stock.riskLevel = 'low';
            } else {
                stock.riskFlag = 'Normal';
                stock.riskLevel = 'low';
            }

            stock.lastChecked = new Date().toISOString();
            anyUpdated = true;
        }));

        // Re-render after each batch so users see prices appearing live
        if (anyUpdated) {
            dashboardData.lastUpdated = new Date().toISOString();
            applySearchAndFilters();
            renderSummaryCards();
            updateLastRefreshed();
        }
    }

    if (anyUpdated) {
        console.log('Live prices updated for all stocks.');
    }
}

// ─── Strategy Filter ──────────────────────────────────────────────────────────
window.applyStrategyFilter = function (strategy) {
    currentStrategy = strategy;
    if (!dashboardData?.stocks) return;

    filteredStocks = strategy === 'all'
        ? [...dashboardData.stocks]
        : dashboardData.stocks.filter(s => s.strategy === strategy);

    // Update active tab styling
    document.querySelectorAll('.strategy-tab').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`tab-${strategy}`);
    if (tabEl) tabEl.classList.add('active');

    applySearchAndFilters();
    renderDashboard();

    setTimeout(() => {
        const sec = document.getElementById('table-section');
        if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
};

// ─── Rendering ────────────────────────────────────────────────────────────────
function renderDashboard() {
    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateFilteredCount();
}

function renderSummaryCards() {
    if (!dashboardData?.stocks) return;
    const all = dashboardData.stocks;
    document.getElementById('total-stocks').textContent = all.length || 0;
    document.getElementById('swing-count').textContent = all.filter(s => s.strategy === 'swing').length || 0;
    document.getElementById('longterm-count').textContent = all.filter(s => s.strategy === 'long-term').length || 0;
    document.getElementById('active-flags').textContent = all.filter(s => s.riskLevel === 'high' || s.riskLevel === 'medium').length || 0;
}

function renderStockTable() {
    const tableBody = document.getElementById('table-body');
    const mobileCards = document.getElementById('mobile-cards');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');

    tableBody.innerHTML = '';
    mobileCards.innerHTML = '';

    if (filteredStocks.length === 0) {
        tableContainer.classList.add('hidden');
        mobileCards.classList.add('hidden');
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');
    tableContainer.classList.remove('hidden');
    mobileCards.classList.remove('hidden');

    filteredStocks.forEach(stock => {
        tableBody.appendChild(createTableRow(stock));
        mobileCards.appendChild(createMobileCard(stock));
    });
}

function createTableRow(stock) {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-gray-50 transition';
    if (stock.riskLevel === 'high') tr.className += ' bg-red-50';
    else if (stock.riskLevel === 'medium') tr.className += ' bg-yellow-50';

    const daysHeld = calculateDaysHeld(stock.entryDate);
    const isLive = stock.riskFlag !== 'Fetching live price…' && stock.riskFlag !== 'Price unavailable';

    // Current price cell — shows a spinner while fetching, then the live price
    const priceCell = isLive
        ? `<span class="font-bold text-gray-900">${formatCurrency(stock.currentPrice)}</span>
           <span class="block text-xs text-green-600 font-semibold">● Live</span>`
        : `<span class="text-gray-400 text-sm">${stock.riskFlag === 'Fetching live price…'
            ? '<i class="fas fa-spinner fa-spin mr-1"></i>Fetching…'
            : formatCurrency(stock.entryPrice)}</span>`;

    tr.innerHTML = `
        <td class="px-4 py-4 whitespace-nowrap">
            <div class="text-sm font-bold text-gray-900">${escapeHtml(stock.name)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(stock.ticker)}</div>
            <div class="text-xs text-blue-600 mt-1"><i class="fas fa-tag mr-1"></i>${escapeHtml(stock.sector || 'N/A')}</div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">${getStrategyBadge(stock.strategy)}</td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700">
            <div class="font-semibold">${formatDate(stock.entryDate)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(stock.entryTime || 'N/A')}</div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700 text-right font-semibold">
            ${formatCurrency(stock.entryPrice)}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-right">
            ${priceCell}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700 text-right">
            <div class="font-semibold text-green-700">${formatTargetRange(stock.targetExitMin, stock.targetExitMax)}</div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700 text-right">
            <div class="font-semibold text-red-700">${formatCurrency(stock.stopLoss)}</div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">
            <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold bg-gray-100 text-gray-700">
                <i class="fas fa-calendar-alt mr-1"></i>${daysHeld} days
            </span>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">
            ${getRiskFlagBadge(stock.riskFlag, stock.riskLevel)}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">
            <a href="${escapeHtml(stock.discussionUrl || '#')}"
               target="_blank"
               class="inline-flex items-center px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-semibold hover:bg-blue-200 transition">
                <i class="fas fa-external-link-alt mr-1"></i>View
            </a>
        </td>
    `;
    return tr;
}

function createMobileCard(stock) {
    const card = document.createElement('div');
    card.className = 'p-4 border-b hover:bg-gray-50';
    if (stock.riskLevel === 'high') card.className += ' bg-red-50';
    else if (stock.riskLevel === 'medium') card.className += ' bg-yellow-50';

    const daysHeld = calculateDaysHeld(stock.entryDate);
    const isLive = stock.riskFlag !== 'Fetching live price…' && stock.riskFlag !== 'Price unavailable';

    card.innerHTML = `
        <div class="flex justify-between items-start mb-3">
            <div>
                <h3 class="font-bold text-gray-900">${escapeHtml(stock.name)}</h3>
                <p class="text-xs text-gray-500">${escapeHtml(stock.ticker)} · ${escapeHtml(stock.sector || 'N/A')}</p>
            </div>
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
        </div>
        <div class="mb-2">${getStrategyBadge(stock.strategy)}</div>
        <div class="grid grid-cols-2 gap-3 mb-3 text-sm">
            <div>
                <p class="text-gray-500 text-xs">Entry Price</p>
                <p class="font-semibold">${formatCurrency(stock.entryPrice)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Current Price ${isLive ? '<span class="text-green-600">● Live</span>' : ''}</p>
                <p class="font-bold">${isLive ? formatCurrency(stock.currentPrice) : '<span class="text-gray-400 text-xs">Fetching…</span>'}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Target Range</p>
                <p class="font-semibold text-green-700">${formatTargetRange(stock.targetExitMin, stock.targetExitMax)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Stop Loss</p>
                <p class="font-semibold text-red-700">${formatCurrency(stock.stopLoss)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Entry Date</p>
                <p class="font-semibold">${formatDate(stock.entryDate)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Days Held</p>
                <p class="font-semibold">${daysHeld} days</p>
            </div>
            <div class="col-span-2">
                <p class="text-gray-500 text-xs">Risk Flag</p>
                ${getRiskFlagBadge(stock.riskFlag, stock.riskLevel)}
            </div>
        </div>
        <a href="${escapeHtml(stock.discussionUrl || '#')}"
           target="_blank"
           class="block text-center bg-blue-100 text-blue-700 rounded-lg py-2 text-sm font-semibold hover:bg-blue-200 transition">
            <i class="fas fa-external-link-alt mr-1"></i>View Discussion
        </a>
    `;
    return card;
}

// ─── Badge Helpers ────────────────────────────────────────────────────────────
function getStrategyBadge(strategy) {
    if (strategy === 'swing') {
        return `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-purple-100 text-purple-700">
            <i class="fas fa-bolt mr-1"></i>Swing</span>`;
    } else if (strategy === 'long-term') {
        return `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-green-100 text-green-700">
            <i class="fas fa-chart-line mr-1"></i>Long Term</span>`;
    }
    return '<span class="text-xs text-gray-500">N/A</span>';
}

function getDevianceBadge(deviance, deviancePercent) {
    let icon, colorClass, bgClass;
    if (deviance > 0)      { icon = '🟩'; colorClass = 'text-green-700'; bgClass = 'bg-green-100'; }
    else if (deviance < 0) { icon = '🟥'; colorClass = 'text-red-700';   bgClass = 'bg-red-100';   }
    else                   { icon = '🟨'; colorClass = 'text-yellow-700'; bgClass = 'bg-yellow-100'; }
    return `<span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-bold ${bgClass} ${colorClass}">
        ${icon} ${escapeHtml(deviancePercent)}</span>`;
}

function getRiskFlagBadge(riskFlag, riskLevel) {
    let icon, colorClass, bgClass;
    switch (riskLevel) {
        case 'high':   icon = '🚨'; colorClass = 'text-red-700';    bgClass = 'bg-red-100';    break;
        case 'medium': icon = '⚠️'; colorClass = 'text-yellow-700'; bgClass = 'bg-yellow-100'; break;
        default:       icon = '✅'; colorClass = 'text-green-700';  bgClass = 'bg-green-100';
    }
    return `<span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${bgClass} ${colorClass}">
        ${icon} ${escapeHtml(riskFlag)}</span>`;
}

// ─── Utility Helpers ──────────────────────────────────────────────────────────
function calculateDaysHeld(entryDate) {
    if (!entryDate) return 0;
    return Math.ceil(Math.abs(new Date() - new Date(entryDate)) / (1000 * 60 * 60 * 24));
}

function formatTargetRange(min, max) {
    if (!min || !max) return 'N/A';
    return `₹${parseFloat(min).toFixed(2)} – ₹${parseFloat(max).toFixed(2)}`;
}

function updateLastRefreshed() {
    if (!dashboardData?.lastUpdated) return;
    const fmt = new Date(dashboardData.lastUpdated).toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: true,
        timeZone: 'Asia/Kolkata'
    });
    document.getElementById('last-updated').textContent = fmt + ' IST (Live)';
}

function updateFilteredCount() {
    document.getElementById('filtered-count').textContent = filteredStocks.length;
}

// ─── Search / Sort / Sector Filters ──────────────────────────────────────────
function applySearchAndFilters() {
    if (!dashboardData?.stocks) return;

    let stocks = dashboardData.stocks;
    if (currentStrategy !== 'all') {
        stocks = stocks.filter(s => s.strategy === currentStrategy);
    }

    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    if (searchTerm) {
        stocks = stocks.filter(s =>
            s.name.toLowerCase().includes(searchTerm) ||
            s.ticker.toLowerCase().includes(searchTerm)
        );
    }

    const sectorFilter = document.getElementById('sector-filter').value;
    if (sectorFilter !== 'all') {
        stocks = stocks.filter(s => s.sector === sectorFilter);
    }

    filteredStocks = sortStocks(stocks, document.getElementById('sort-select').value);
    renderStockTable();
    updateFilteredCount();
}

function sortStocks(stocks, sortBy) {
    const sorted = [...stocks];
    switch (sortBy) {
        case 'deviance-desc': sorted.sort((a, b) => b.deviance - a.deviance); break;
        case 'deviance-asc':  sorted.sort((a, b) => a.deviance - b.deviance); break;
        case 'date-desc':     sorted.sort((a, b) => new Date(b.entryDate) - new Date(a.entryDate)); break;
        case 'date-asc':      sorted.sort((a, b) => new Date(a.entryDate) - new Date(b.entryDate)); break;
        case 'name-asc':      sorted.sort((a, b) => a.name.localeCompare(b.name)); break;
    }
    return sorted;
}

function clearAllFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('sector-filter').value = 'all';
    document.getElementById('sort-select').value = 'deviance-desc';
    currentStrategy = 'all';
    document.querySelectorAll('.strategy-tab').forEach(t => t.classList.remove('active'));
    const tabAll = document.getElementById('tab-all');
    if (tabAll) tabAll.classList.add('active');
    applySearchAndFilters();
}

// ─── Event Listeners ──────────────────────────────────────────────────────────
function setupEventListeners() {
    document.getElementById('refresh-btn').addEventListener('click', async function () {
        this.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i>Refreshing…';
        await loadDashboardData();
        this.innerHTML = '<i class="fas fa-sync-alt mr-1"></i>Refresh';
    });

    document.getElementById('search-input').addEventListener('input', applySearchAndFilters);
    document.getElementById('sector-filter').addEventListener('change', applySearchAndFilters);
    document.getElementById('sort-select').addEventListener('change', applySearchAndFilters);
    document.getElementById('export-csv').addEventListener('click', exportToCSV);
    document.getElementById('print-table').addEventListener('click', () => window.print());
    document.getElementById('clear-filters').addEventListener('click', clearAllFilters);
    document.getElementById('clear-filters-empty').addEventListener('click', clearAllFilters);
}

// ─── Export ───────────────────────────────────────────────────────────────────
function exportToCSV() {
    if (!filteredStocks?.length) { alert('No data to export'); return; }
    const headers = ['Stock Name', 'Ticker', 'Sector', 'Strategy', 'Entry Date', 'Entry Time',
                     'Entry Price', 'Current Price (Live)', 'Target Min', 'Target Max',
                     'Stop Loss', 'Deviance %', 'Days Held', 'Risk Flag'];
    const rows = filteredStocks.map(s => [
        s.name, s.ticker, s.sector || 'N/A', s.strategy || 'N/A',
        s.entryDate, s.entryTime || 'N/A', s.entryPrice, s.currentPrice,
        s.targetExitMin || 'N/A', s.targetExitMax || 'N/A', s.stopLoss || 'N/A',
        s.deviancePercent, calculateDaysHeld(s.entryDate), s.riskFlag
    ]);
    let csv = headers.join(',') + '\n';
    rows.forEach(r => { csv += r.map(c => `"${c}"`).join(',') + '\n'; });
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `stock-dashboard-${new Date().toISOString().split('T')[0]}.csv`;
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ─── UI State ─────────────────────────────────────────────────────────────────
function showLoadingState() {
    document.getElementById('loading-state').classList.remove('hidden');
    document.getElementById('error-state').classList.add('hidden');
    document.getElementById('table-container').classList.add('hidden');
    document.getElementById('mobile-cards').classList.add('hidden');
}
function hideLoadingState() {
    document.getElementById('loading-state').classList.add('hidden');
}
function showErrorState() {
    document.getElementById('loading-state').classList.add('hidden');
    document.getElementById('error-state').classList.remove('hidden');
    document.getElementById('table-container').classList.add('hidden');
    document.getElementById('mobile-cards').classList.add('hidden');
}

// ─── Formatters ───────────────────────────────────────────────────────────────
function formatCurrency(value) {
    if (value === null || value === undefined) return 'N/A';
    return '₹' + parseFloat(value).toLocaleString('en-IN', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
    });
}
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric'
    });
}
function escapeHtml(text) {
    if (!text) return '';
    return text.toString().replace(/[&<>"']/g, m => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]
    ));
}

// Made with Bob
