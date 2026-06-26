/**
 * FINAL DASHBOARD (BACKEND DRIVEN + ORIGINAL UI SAFE)
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

// ✅ LOAD BACKEND DATA
async function loadDashboardData() {
    try {
        showLoadingState();

        const ts = Date.now();
        const response = await fetch(`data/dashboard.json?t=${ts}`);

        if (!response.ok) throw new Error("dashboard.json load failed");

        const data = await response.json();

        const stocks = data.stocks || [];

        // ✅ MAP BACKEND → UI FORMAT
        dashboardData = {
            lastUpdated: data.lastUpdated,
            stocks: stocks.map(s => ({
                ...s,
                deviance: s.performance,
                deviancePercent: `${s.performance >= 0 ? '+' : ''}${s.performance.toFixed(2)}%`,
                riskFlag: s.fetchStatus,
                riskLevel: s.fetchStatus === "Success" ? "low" : "medium",
                lastChecked: data.lastUpdated
            }))
        };

        filteredStocks = [...dashboardData.stocks];

        updateTopStatus(data);

        renderDashboard();
        hideLoadingState();

    } catch (err) {
        console.error(err);
        showErrorState();
    }
}

// ✅ UPDATE HEADER STATUS
function updateTopStatus(data) {
    if (!data) return;

    const last = document.getElementById("last-updated");
    if (last) last.textContent =
        new Date(data.lastUpdated).toLocaleString("en-IN");

    const market = document.getElementById("market-status");
    if (market) market.textContent = data.marketStatus || "-";

    const yahoo = document.getElementById("yahoo-status");
    if (yahoo && data.yahooStatus) {
        const y = data.yahooStatus;
        yahoo.textContent = `${y.status} (${y.successCount}/${y.totalCount})`;
    }
}

// ✅ MAIN RENDER
function renderDashboard() {
    renderSummaryCards();
    renderStockTable();
    updateFilteredCount();
}

// ✅ SUMMARY CARDS
function renderSummaryCards() {
    if (!dashboardData?.stocks) return;

    const all = dashboardData.stocks;

    document.getElementById('total-stocks').textContent = all.length;
    document.getElementById('swing-count').textContent =
        all.filter(s => s.strategy === 'swing').length;
    document.getElementById('longterm-count').textContent =
        all.filter(s => s.strategy === 'long-term').length;
    document.getElementById('active-flags').textContent =
        all.filter(s => s.fetchStatus !== 'Success').length;
}

// ✅ TABLE
function renderStockTable() {
    const tableBody = document.getElementById('table-body');

    if (!tableBody) return;

    tableBody.innerHTML = '';

    filteredStocks.forEach(stock => {
        tableBody.appendChild(createTableRow(stock));
    });

    document.getElementById('table-container')?.classList.remove('hidden');
}

// ✅ TABLE ROW (RESTORED UI STYLE)
function createTableRow(stock) {
    const tr = document.createElement('tr');

    const perfClass =
        stock.performance > 0 ? 'text-green-600' :
        stock.performance < 0 ? 'text-red-500' :
        'text-gray-600';

    const sourceLabel =
        stock.priceSource === 'Yahoo' ? '🟢 Live' :
        stock.priceSource === 'Stooq' ? '🟡 Backup' :
        stock.priceSource === 'Cached' ? '🔵 Cached' :
        '⚪ Entry';

    tr.innerHTML = `
        <td class="px-4 py-3">${stock.ticker}</td>
        <td class="px-4 py-3">${stock.strategy || 'N/A'}</td>
        <td class="px-4 py-3">₹${stock.entryPrice}</td>
        <td class="px-4 py-3">₹${stock.currentPrice}</td>

        <td class="px-4 py-3 ${perfClass}">
            ${stock.performance.toFixed(2)}%
        </td>

        <td class="px-4 py-3">${sourceLabel}</td>

        <td class="px-4 py-3 ${
            stock.fetchStatus === 'Success'
                ? 'text-green-600'
                : 'text-orange-500'
        }">
            ${stock.fetchStatus}
        </td>
    `;

    return tr;
}

// ✅ EVENTS
function setupEventListeners() {
    document.getElementById('refresh-btn')
        ?.addEventListener('click', loadDashboardData);
}

// ✅ STATES
function showLoadingState() {
    document.getElementById('loading-state')?.classList.remove('hidden');
}
function hideLoadingState() {
    document.getElementById('loading-state')?.classList.add('hidden');
}
function showErrorState() {
    document.getElementById('error-state')?.classList.remove('hidden');
}

// ✅ FILTER COUNT
function updateFilteredCount() {
    document.getElementById('filtered-count')
        ?.textContent = filteredStocks.length;
}
