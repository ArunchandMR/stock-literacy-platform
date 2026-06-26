/**
 * FINAL DASHBOARD (Backend Driven)
 * Source: data/dashboard.json
 * No direct Yahoo calls in UI
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

// ✅ INIT
document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

// ✅ LOAD FROM BACKEND JSON
async function loadDashboardData() {
    try {
        showLoadingState();

        const ts = Date.now();
        const response = await fetch(`data/dashboard.json?t=${ts}`);

        if (!response.ok) throw new Error("dashboard.json load failed");

        const data = await response.json();

        dashboardData = data;

        // ✅ Use backend stocks directly
        filteredStocks = [...(data.stocks || [])];

        renderDashboard();
        hideLoadingState();

    } catch (err) {
        console.error("Error loading dashboard:", err);
        showErrorState();
    }
}

// ✅ RENDER
function renderDashboard() {
    if (!dashboardData) return;

    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateYahooStatus();
    updateFilteredCount();
}

// ✅ NEW — Yahoo status display
function updateYahooStatus() {
    if (!dashboardData.yahooStatus) return;

    const el = document.getElementById("yahoo-status");

    if (el) {
        const y = dashboardData.yahooStatus;
        el.textContent =
            `Yahoo: ${y.status} (${y.successCount}/${y.totalCount})`;
    }
}

// ✅ LAST UPDATED
function updateLastRefreshed() {
    if (!dashboardData?.lastUpdated) return;

    const date = new Date(dashboardData.lastUpdated);

    const formatted = date.toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    });

    document.getElementById('last-updated').textContent = formatted;
}

// ✅ SUMMARY
function renderSummaryCards() {
    if (!dashboardData?.stocks) return;

    const all = dashboardData.stocks;

    document.getElementById('total-stocks').textContent = all.length;
    document.getElementById('swing-count').textContent =
        all.filter(s => s.strategy === 'swing').length;
    document.getElementById('longterm-count').textContent =
        all.filter(s => s.strategy === 'long-term').length;
    document.getElementById('active-flags').textContent =
        all.filter(s => s.fetchStatus === 'Fallback').length;
}

// ✅ TABLE
function renderStockTable() {
    const tableBody = document.getElementById('table-body');
    const mobileCards = document.getElementById('mobile-cards');

    tableBody.innerHTML = '';
    mobileCards.innerHTML = '';

    filteredStocks.forEach(stock => {
        tableBody.appendChild(createTableRow(stock));
        mobileCards.appendChild(createMobileCard(stock));
    });
}

// ✅ ROW
function createTableRow(stock) {
    const tr = document.createElement('tr');

    tr.innerHTML = `
        <td>${stock.name || ''}</td>
        <td>${stock.strategy}</td>
        <td>${formatDate(stock.entryDate)}</td>
        <td>${formatCurrency(stock.entryPrice)}</td>
        <td>${formatCurrency(stock.currentPrice)}</td>
        <td>${formatCurrency(stock.targetExitMin)} - ${formatCurrency(stock.targetExitMax)}</td>
        <td>${formatCurrency(stock.stopLoss)}</td>
        <td>${stock.performance.toFixed(2)}%</td>
        <td>${stock.priceSource}</td>
        <td>${stock.fetchStatus}</td>
    `;

    return tr;
}

// ✅ MOBILE CARD
function createMobileCard(stock) {
    const div = document.createElement('div');

    div.innerHTML = `
        <div class="p-4 border-b">
            <b>${stock.ticker}</b><br>
            Price: ${formatCurrency(stock.currentPrice)}<br>
            Perf: ${stock.performance.toFixed(2)}%<br>
            Source: ${stock.priceSource}
        </div>
    `;

    return div;
}

// ✅ HELPERS
function formatCurrency(val) {
    if (val === null || val === undefined) return '-';
    return '₹' + Number(val).toFixed(2);
}

function formatDate(date) {
    if (!date) return '-';
    return new Date(date).toLocaleDateString();
}

// ✅ FILTERS
function applySearchAndFilters() {
    let stocks = dashboardData.stocks;

    if (currentStrategy !== 'all') {
        stocks = stocks.filter(s => s.strategy === currentStrategy);
    }

    filteredStocks = stocks;
    renderStockTable();
    updateFilteredCount();
}

// ✅ EVENTS
function setupEventListeners() {
    document.getElementById('refresh-btn')
        .addEventListener('click', loadDashboardData);
}

// ✅ UI STATES
function showLoadingState() {
    document.getElementById('loading-state').classList.remove('hidden');
}
function hideLoadingState() {
    document.getElementById('loading-state').classList.add('hidden');
}
function showErrorState() {
    document.getElementById('error-state').classList.remove('hidden');
}
``