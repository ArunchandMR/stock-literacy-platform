/**
 * FINAL FIXED DASHBOARD JS (SAFE VERSION)
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

async function loadDashboardData() {
    try {
        showLoadingState();

        const ts = Date.now();
        const response = await fetch(`data/dashboard.json?t=${ts}`);

        if (!response.ok) throw new Error("dashboard.json load failed");

        const data = await response.json();

        dashboardData = data;
        filteredStocks = [...(data.stocks || [])];

        renderDashboard();
        hideLoadingState();

    } catch (err) {
        console.error("Error loading dashboard:", err);
        showErrorState();
    }
}

function renderDashboard() {
    if (!dashboardData) return;

    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateYahooStatus();
    updateMarketStatus();
}

function updateYahooStatus() {
    const el = document.getElementById("yahoo-status");
    if (!el || !dashboardData?.yahooStatus) return;

    const y = dashboardData.yahooStatus;
    el.textContent = `${y.status} (${y.successCount}/${y.totalCount})`;
}

function updateMarketStatus() {
    const el = document.getElementById("market-status");
    if (!el || !dashboardData) return;

    el.textContent = dashboardData.marketStatus || "-";
}

function updateLastRefreshed() {
    const el = document.getElementById("last-updated");
    if (!el || !dashboardData?.lastUpdated) return;

    const date = new Date(dashboardData.lastUpdated);

    el.textContent = date.toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    });
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
        all.filter(s => s.fetchStatus === 'Fallback').length;
}

// ✅ FIXED TABLE RENDER
function renderStockTable() {
    const tableBody = document.getElementById('table-body');
    const container = document.getElementById('table-container');

    // ✅ SAFETY FIX
    if (!tableBody || !container) {
        console.error("Table elements missing in HTML");
        return;
    }

    tableBody.innerHTML = '';

    filteredStocks.forEach(stock => {
        tableBody.appendChild(createTableRow(stock));
    });

    container.classList.remove('hidden');
}

function createTableRow(stock) {
    const tr = document.createElement('tr');

    tr.innerHTML = `
        <td class="p-3">${stock.ticker}</td>
        <td class="p-3">${stock.strategy}</td>
        <td class="p-3">₹${stock.entryPrice}</td>
        <td class="p-3">₹${stock.currentPrice}</td>
        <td class="p-3">${stock.performance.toFixed(2)}%</td>
        <td class="p-3">${stock.priceSource}</td>
        <td class="p-3">${stock.fetchStatus}</td>
    `;

    return tr;
}

function setupEventListeners() {
    const btn = document.getElementById('refresh-btn');

    if (btn) {
        btn.addEventListener('click', loadDashboardData);
    }
}

// ✅ STATES
function showLoadingState() {
    const el = document.getElementById('loading-state');
    if (el) el.classList.remove('hidden');
}

function hideLoadingState() {
    const el = document.getElementById('loading-state');
    if (el) el.classList.add('hidden');
}

function showErrorState() {
    const el = document.getElementById('error-state');
    if (el) el.classList.remove('hidden');
}