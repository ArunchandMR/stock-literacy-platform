/**
 * FINAL STABLE DASHBOARD JS
 * (Backend driven + Safe DOM handling + No Yahoo calls)
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all';

// ✅ INIT
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
        console.error("Error loading dashboard:", err);
        showErrorState();
    }
}

// ✅ STATUS UPDATE
function updateTopStatus(data) {
    if (!data) return;

    document.getElementById("last-updated") &&
        (document.getElementById("last-updated").textContent =
            new Date(data.lastUpdated).toLocaleString("en-IN"));

    document.getElementById("market-status") &&
        (document.getElementById("market-status").textContent =
            data.marketStatus || "-");

    if (data.yahooStatus) {
        document.getElementById("yahoo-status") &&
            (document.getElementById("yahoo-status").textContent =
                `${data.yahooStatus.status} (${data.yahooStatus.successCount}/${data.yahooStatus.totalCount})`);
    }
}

// ✅ MAIN RENDER
function renderDashboard() {
    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateFilteredCount();
}

// ✅ SAFE SUMMARY
function renderSummaryCards() {
    if (!dashboardData?.stocks) return;

    const all = dashboardData.stocks;

    document.getElementById("total-stocks") &&
        (document.getElementById("total-stocks").textContent = all.length);

    document.getElementById("swing-count") &&
        (document.getElementById("swing-count").textContent =
            all.filter(s => s.strategy === "swing").length);

    document.getElementById("longterm-count") &&
        (document.getElementById("longterm-count").textContent =
            all.filter(s => s.strategy === "long-term").length);

    document.getElementById("active-flags") &&
        (document.getElementById("active-flags").textContent =
            all.filter(s => s.riskLevel !== "low").length);
}

// ✅ ✅ ✅ FINAL FIXED TABLE FUNCTION
function renderStockTable() {

    const tableBody = document.getElementById('table-body');
    const mobileCards = document.getElementById('mobile-cards');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');

    // ✅ CRITICAL SAFETY CHECK
    if (!tableBody) {
        console.error("table-body not found in DOM");
        return;
    }

    tableBody.innerHTML = '';
    mobileCards && (mobileCards.innerHTML = '');

    if (!filteredStocks || filteredStocks.length === 0) {
        tableContainer?.classList.add('hidden');
        mobileCards?.classList.add('hidden');
        emptyState?.classList.remove('hidden');
        return;
    }

    emptyState?.classList.add('hidden');
    tableContainer?.classList.remove('hidden');
    mobileCards?.classList.remove('hidden');

    filteredStocks.forEach(stock => {

        const tr = document.createElement("tr");

        const isLive =
            stock.priceSource === "Yahoo" ||
            stock.priceSource === "Stooq";

        tr.innerHTML = `
            <td class="px-4 py-3">
                <div class="font-bold">${stock.name || ''}</div>
                <div class="text-xs text-gray-500">${stock.ticker}</div>
            </td>

            <td class="text-center">${stock.strategy || "N/A"}</td>

            <td class="text-right">₹${stock.entryPrice}</td>

            <td class="text-right">
                ${isLive ? "₹" + stock.currentPrice : "—"}
            </td>

            <td class="text-center ${
                stock.performance > 0
                    ? "text-green-600"
                    : stock.performance < 0
                    ? "text-red-500"
                    : "text-gray-500"
            }">
                ${stock.performance.toFixed(2)}%
            </td>

            <td class="text-center ${stock.fetchStatus === "Success" ? "text-green-600" : "text-orange-500"}">
                ${stock.fetchStatus}
            </td>
        `;

        tableBody.appendChild(tr);

        if (mobileCards) {
            mobileCards.appendChild(tr.cloneNode(true));
        }
    });
}

// ✅ SAFE EVENTS
function setupEventListeners() {

    const refreshBtn = document.getElementById("refresh-btn");

    if (refreshBtn) {
        refreshBtn.addEventListener("click", async function () {
            this.innerHTML =
                '<i class="fas fa-spinner fa-spin mr-1"></i>Refreshing…';

            await loadDashboardData();

            this.innerHTML =
                '<i class="fas fa-sync-alt mr-1"></i>Refresh';
        });
    }

    document.getElementById("search-input")?.addEventListener("input", applySearchAndFilters);
    document.getElementById("sector-filter")?.addEventListener("change", applySearchAndFilters);
    document.getElementById("sort-select")?.addEventListener("change", applySearchAndFilters);

    document.getElementById("export-csv")?.addEventListener("click", exportToCSV);
    document.getElementById("print-table")?.addEventListener("click", () => window.print());

    document.getElementById("clear-filters")?.addEventListener("click", clearAllFilters);
    document.getElementById("clear-filters-empty")?.addEventListener("click", clearAllFilters);
}

// ✅ UI STATES
function showLoadingState() {
    document.getElementById("loading-state")?.classList.remove("hidden");
    document.getElementById("error-state")?.classList.add("hidden");
}

function hideLoadingState() {
    document.getElementById("loading-state")?.classList.add("hidden");
}

function showErrorState() {
    document.getElementById("loading-state")?.classList.add("hidden");
    document.getElementById("error-state")?.classList.remove("hidden");
}

// ✅ SAFE UPDATES
function updateLastRefreshed() {
    if (!dashboardData?.lastUpdated) return;

    const el = document.getElementById("last-updated");
    if (el) {
        el.textContent =
            new Date(dashboardData.lastUpdated).toLocaleString("en-IN");
    }
}

function updateFilteredCount() {
    const el = document.getElementById("filtered-count");
    if (el) el.textContent = filteredStocks.length;
}
``