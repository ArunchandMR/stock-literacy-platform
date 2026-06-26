/**
 * Stock Performance Dashboard - Main Logic (Backend Driven)
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

// ─── Bootstrap ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

// ─── Data Loading (UPDATED ✅) ──────────────────────────────
async function loadDashboardData() {
    try {
        showLoadingState();

        const ts = Date.now();

        // ✅ LOAD FROM BACKEND
        let response = await fetch(`data/dashboard.json?t=${ts}`);
        if (!response.ok) throw new Error(`dashboard.json HTTP ${response.status}`);

        const raw = await response.json();
        const stocks = raw.stocks || [];

        dashboardData = {
            lastUpdated: raw.lastUpdated,
            stocks: stocks.map(s => {
                let dev = s.performance || 0;

                return {
                    ...s,
                    currentPrice: s.currentPrice,

                    deviance: dev,
                    deviancePercent: `${dev >= 0 ? '+' : ''}${dev.toFixed(2)}%`,

                    riskFlag: s.fetchStatus === "Success" ? "Normal" : "Fallback",
                    riskLevel: s.fetchStatus === "Success" ? "low" : "medium",

                    lastChecked: raw.lastUpdated
                };
            })
        };

        filteredStocks = [...dashboardData.stocks];

        updateTopStatus(raw);

        renderDashboard();
        hideLoadingState();

    } catch (err) {
        console.error('Error loading dashboard data:', err);
        showErrorState();
    }
}

// ✅ STATUS UPDATE
function updateTopStatus(data) {
    if (!data) return;

    const last = document.getElementById("last-updated");
    if (last) last.textContent = new Date(data.lastUpdated).toLocaleString("en-IN");

    const market = document.getElementById("market-status");
    if (market) market.textContent = data.marketStatus || "-";

    const yahoo = document.getElementById("yahoo-status");
    if (yahoo && data.yahooStatus) {
        const y = data.yahooStatus;
        yahoo.textContent = `${y.status} (${y.successCount}/${y.totalCount})`;
    }
}

// ─── Strategy Filter (UNCHANGED ✅) ─────────────────────────
window.applyStrategyFilter = function (strategy) {
    currentStrategy = strategy;
    if (!dashboardData?.stocks) return;

    filteredStocks = strategy === 'all'
        ? [...dashboardData.stocks]
        : dashboardData.stocks.filter(s => s.strategy === strategy);

    document.querySelectorAll('.strategy-tab').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`tab-${strategy}`);
    if (tabEl) tabEl.classList.add('active');

    applySearchAndFilters();
    renderDashboard();
};

// ─── Rendering (UNCHANGED ✅) ───────────────────────────────
function renderDashboard() {
    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateFilteredCount();
}

function renderSummaryCards() {
    if (!dashboardData?.stocks) return;

    const all = dashboardData.stocks;

    document.getElementById('total-stocks').textContent = all.length;
    document.getElementById('swing-count').textContent =
        all.filter(s => s.strategy === 'swing').length;
    document.getElementById('longterm-count').textContent =
        all.filter(s => s.strategy === 'long-term').length;

    document.getElementById('active-flags').textContent =
        all.filter(s => s.riskLevel !== 'low').length;
}

// ✅ MAIN FIX → no Yahoo, no updateStockRow needed
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

// ✅ FIXED "isLive"
function createTableRow(stock) {
    const tr = document.createElement('tr');
    tr.setAttribute('data-ticker', stock.ticker);

    const isLive = stock.priceSource === "Yahoo" || stock.priceSource === "Stooq";

    tr.innerHTML = `
        <td class="px-4 py-4">
            <div class="font-bold">${stock.name || ''}</div>
            <div class="text-xs text-gray-500">${stock.ticker}</div>
        </td>

        <td class="text-center">${getStrategyBadge(stock.strategy)}</td>

        <td class="text-sm text-right font-semibold">
            ${formatCurrency(stock.entryPrice)}
        </td>

        <td class="text-right">
            ${isLive ? formatCurrency(stock.currentPrice) : '—'}
        </td>

        <td class="text-center">
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
        </td>

        <td class="text-center">
            ${getRiskFlagBadge(stock.riskFlag, stock.riskLevel)}
        </td>
    `;

    return tr;
}

// ✅ KEEP YOUR EXISTING HELPERS BELOW (UNCHANGED)

// ─── Event Listeners ─────────────────────────────
function setupEventListeners() {
    document.getElementById('refresh-btn').addEventListener('click', loadDashboardData);
}

// ─── UI States ────────────────────────────────────
function showLoadingState() {
    document.getElementById('loading-state').classList.remove('hidden');
}
function hideLoadingState() {
    document.getElementById('loading-state').classList.add('hidden');
}
function showErrorState() {
    document.getElementById('error-state').classList.remove('hidden');
}

// ✅ formatting
function formatCurrency(value) {
    return '₹' + parseFloat(value).toFixed(2);
}