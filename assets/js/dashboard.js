/**
 * FINAL DASHBOARD (FULLY BACKEND CONNECTED)
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
});

// ✅ LOAD DATA
async function loadDashboardData() {
    try {
        showLoadingState();

        const res = await fetch(`data/dashboard.json?t=${Date.now()}`);
        const data = await res.json();

        dashboardData = data;
        filteredStocks = [...data.stocks];

        renderDashboard();
        hideLoadingState();

    } catch (err) {
        console.error(err);
        showErrorState();
    }
}

// ✅ RENDER
function renderDashboard() {
    renderSummary();
    renderTable();
    updateTopStatus();
}

// ✅ TOP STATUS
function updateTopStatus() {
    if (!dashboardData) return;

    document.getElementById('last-updated').textContent =
        new Date(dashboardData.lastUpdated).toLocaleString("en-IN");

    document.getElementById('market-status').textContent =
        dashboardData.marketStatus;

    const y = dashboardData.yahooStatus;
    document.getElementById('yahoo-status').textContent =
        `${y.status} (${y.successCount}/${y.totalCount})`;
}

// ✅ SUMMARY
function renderSummary() {
    const stocks = dashboardData.stocks;

    document.getElementById('total-stocks').textContent = stocks.length;
    document.getElementById('swing-count').textContent =
        stocks.filter(s => s.strategy === 'swing').length;
    document.getElementById('longterm-count').textContent =
        stocks.filter(s => s.strategy === 'long-term').length;
    document.getElementById('active-flags').textContent =
        stocks.filter(s => s.fetchStatus === 'Fallback').length;
}

// ✅ TABLE
function renderTable() {
    const tableBody = document.getElementById('table-body');

    if (!tableBody) return;

    tableBody.innerHTML = '';

    filteredStocks.forEach(stock => {
        const tr = document.createElement('tr');

        tr.innerHTML = `
            <td>${stock.ticker}</td>
            <td>${stock.strategy || '-'}</td>
            <td>₹${stock.entryPrice}</td>
            <td>₹${stock.currentPrice}</td>

            <td class="${
                stock.performance > 0 ? 'text-green-600' :
                stock.performance < 0 ? 'text-red-600' :
                'text-gray-600'
            }">
                ${stock.performance.toFixed(2)}%
            </td>

            <td>
                ${
                    stock.priceSource === 'Yahoo' ? '🟢 Live' :
                    stock.priceSource === 'Stooq' ? '🟡 Backup' :
                    stock.priceSource === 'Cached' ? '🔵 Cached' :
                    '⚪ Entry'
                }
            </td>

            <td class="${
                stock.fetchStatus === 'Success'
                    ? 'text-green-600'
                    : 'text-orange-500'
            }">
                ${stock.fetchStatus}
            </td>
        `;

        tableBody.appendChild(tr);
    });
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