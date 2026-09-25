/**
 * Stock Performance Dashboard — JavaScript
 * Features: search, filter, sort, Target/SL columns, strategy badges,
 *           sector dropdown population, avg-performance card, live count,
 *           IST timestamp, market status dot colour.
 */

let dashboardData    = null;
let filteredStocks   = [];
let currentSortMode  = 'name';

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    loadDashboardData();
    setupEventListeners();
});

// ── Fetch + parse dashboard.json ─────────────────────────────────────────────
async function loadDashboardData() {
    try {
        showLoadingState();

        const res = await fetch(`data/dashboard.json?t=${Date.now()}`);
        if (!res.ok) throw new Error("dashboard.json load failed");

        const raw    = await res.json();
        const stocks = raw.stocks || [];

        dashboardData = {
            lastUpdated:  raw.lastUpdated,
            marketStatus: raw.marketStatus,
            yahooStatus:  raw.yahooStatus,
            stocks: stocks.map(s => {
                const perf = s.performance ?? s.deviance ?? 0;

                const statusMap = {
                    "Live":    { label: "Live",    cls: "text-emerald-600 font-semibold", level: "live"    },
                    "Success": { label: "Live",    cls: "text-emerald-600 font-semibold", level: "live"    },
                    "Stooq":   { label: "Live",    cls: "text-emerald-600 font-semibold", level: "live"    },
                    "Cached":  { label: "Cached",  cls: "text-amber-500",                level: "cached"  },
                    "Pending": { label: "Pending", cls: "text-gray-400 italic",           level: "pending" },
                    "Fallback":{ label: "Pending", cls: "text-gray-400 italic",           level: "pending" },
                };
                const si = statusMap[s.fetchStatus] || { label: s.fetchStatus || "—", cls: "text-gray-400", level: "cached" };

                return {
                    ...s,
                    performance:    perf,
                    statusLabel:    si.label,
                    statusCls:      si.cls,
                    statusLevel:    si.level,
                };
            })
        };

        filteredStocks = [...dashboardData.stocks];

        updateHeader(raw);
        populateSectorFilter();
        applyFilters();          // renders cards + table
        hideLoadingState();

    } catch (err) {
        console.error("Dashboard load error:", err);
        showErrorState();
    }
}

// ── Header status bar ─────────────────────────────────────────────────────────
function updateHeader(raw) {
    // Last updated → IST
    const luEl = document.getElementById("last-updated");
    if (luEl && raw.lastUpdated) {
        luEl.textContent = new Date(raw.lastUpdated)
            .toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: true });
    }

    // Market status + dot colour
    const msEl  = document.getElementById("market-status");
    const dotEl = document.getElementById("market-dot");
    if (msEl && raw.marketStatus) {
        msEl.textContent = raw.marketStatus;
        if (dotEl) {
            const colourMap = { Open: "text-green-300", Closed: "text-red-400", Weekend: "text-gray-400", "Pre-Market": "text-yellow-300" };
            dotEl.className = `fas fa-circle mr-1 text-xs ${colourMap[raw.marketStatus] || "text-gray-400"}`;
        }
    }

    // Yahoo status
    const ysEl = document.getElementById("yahoo-status");
    if (ysEl && raw.yahooStatus) {
        const { status, successCount, totalCount } = raw.yahooStatus;
        ysEl.textContent = `${status} (${successCount}/${totalCount})`;
    }
}

// ── Populate sector dropdown from data ───────────────────────────────────────
function populateSectorFilter() {
    const sel = document.getElementById("sector-filter");
    if (!sel || !dashboardData?.stocks) return;

    const sectors = [...new Set(dashboardData.stocks.map(s => s.sector).filter(Boolean))].sort();
    // keep only the "All Sectors" option then repopulate
    sel.innerHTML = '<option value="all">All Sectors</option>';
    sectors.forEach(sec => {
        const opt = document.createElement("option");
        opt.value = sec;
        opt.textContent = sec;
        sel.appendChild(opt);
    });
}

// ── Summary cards ─────────────────────────────────────────────────────────────
function renderSummaryCards() {
    if (!dashboardData?.stocks) return;
    const all = dashboardData.stocks;

    setText("total-stocks",  all.length);
    setText("swing-count",   all.filter(s => s.strategy === "swing").length);
    setText("longterm-count",all.filter(s => s.strategy === "long-term").length);
    setText("live-count",    all.filter(s => s.statusLevel === "live").length);
    setText("filtered-count",filteredStocks.length);

    // Average performance (live stocks only — pending skews it)
    const liveStocks = filteredStocks.filter(s => s.statusLevel === "live");
    const avgPerfEl  = document.getElementById("avg-perf");
    if (avgPerfEl) {
        if (liveStocks.length === 0) {
            avgPerfEl.textContent = "—";
            avgPerfEl.className   = "text-2xl font-bold text-gray-400";
        } else {
            const avg = liveStocks.reduce((sum, s) => sum + s.performance, 0) / liveStocks.length;
            avgPerfEl.textContent = `${avg >= 0 ? "+" : ""}${avg.toFixed(2)}%`;
            avgPerfEl.className   = `text-2xl font-bold ${avg >= 0 ? "perf-positive" : "perf-negative"}`;
        }
    }
}

// ── Apply search + filter + sort → re-render ─────────────────────────────────
function applyFilters() {
    if (!dashboardData?.stocks) return;

    const search    = (document.getElementById("search-input")?.value || "").toLowerCase().trim();
    const strategy  = document.getElementById("strategy-filter")?.value  || "all";
    const sector    = document.getElementById("sector-filter")?.value    || "all";
    const sortMode  = document.getElementById("sort-select")?.value      || "name";

    filteredStocks = dashboardData.stocks.filter(s => {
        if (search && !`${s.name} ${s.ticker} ${s.sector}`.toLowerCase().includes(search)) return false;
        if (strategy !== "all" && s.strategy !== strategy) return false;
        if (sector   !== "all" && s.sector   !== sector)   return false;
        return true;
    });

    // Sort
    filteredStocks.sort((a, b) => {
        if (sortMode === "perf-desc")  return b.performance - a.performance;
        if (sortMode === "perf-asc")   return a.performance - b.performance;
        if (sortMode === "entry-desc") return b.entryPrice  - a.entryPrice;
        return (a.name || "").localeCompare(b.name || "");
    });

    renderSummaryCards();
    renderStockTable();
    setText("filtered-count", filteredStocks.length);
}

// ── Table render ──────────────────────────────────────────────────────────────
function renderStockTable() {
    const tbody    = document.getElementById("table-body");
    const container= document.getElementById("table-container");
    const empty    = document.getElementById("empty-state");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!filteredStocks.length) {
        container?.classList.add("hidden");
        empty?.classList.remove("hidden");
        return;
    }
    empty?.classList.add("hidden");
    container?.classList.remove("hidden");

    filteredStocks.forEach(stock => {
        const isLive = stock.statusLevel === "live";
        const perf   = stock.performance ?? 0;

        // Performance display
        const perfIcon  = perf > 0 ? "▲" : perf < 0 ? "▼" : "—";
        const perfClass = perf > 0 ? "perf-positive" : perf < 0 ? "perf-negative" : "perf-neutral";
        const perfStr   = `${perfIcon} ${Math.abs(perf).toFixed(2)}%`;

        // Strategy badge
        const stratBadge = stock.strategy === "swing"
            ? `<span class="strategy-swing text-xs px-2 py-0.5 rounded font-semibold">Swing</span>`
            : stock.strategy === "long-term"
            ? `<span class="strategy-longterm text-xs px-2 py-0.5 rounded font-semibold">Long Term</span>`
            : `<span class="text-gray-400 text-xs">${stock.strategy || "—"}</span>`;

        // Current price
        const currentStr = isLive
            ? `₹${Number(stock.currentPrice).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
            : `<span class="text-gray-400 text-xs italic">${stock.statusLabel}</span>`;

        // Target range
        const hasTarget = stock.targetExitMin && stock.targetExitMax;
        const targetStr = hasTarget
            ? `<span class="text-gray-600">₹${Number(stock.targetExitMin).toLocaleString("en-IN")} – ₹${Number(stock.targetExitMax).toLocaleString("en-IN")}</span>`
            : `<span class="text-gray-300">—</span>`;

        // Stop Loss
        const slStr = stock.stopLoss
            ? `<span class="text-red-400">₹${Number(stock.stopLoss).toLocaleString("en-IN")}</span>`
            : `<span class="text-gray-300">—</span>`;

        // Row background hint for performance
        const rowBg = !isLive ? "" : perf >= 10 ? "bg-green-50" : perf <= -10 ? "bg-red-50" : "";

        const tr = document.createElement("tr");
        tr.className = `stock-row ${rowBg}`;
        tr.innerHTML = `
            <td class="px-4 py-3">
                <div class="font-semibold text-gray-900">${stock.name || "—"}</div>
                <div class="text-xs text-gray-400 font-mono">${stock.ticker}</div>
                ${stock.sector ? `<div class="text-xs text-gray-400 mt-0.5">${stock.sector}</div>` : ""}
            </td>
            <td class="px-4 py-3 text-center">${stratBadge}</td>
            <td class="px-4 py-3 text-right font-mono text-gray-700">₹${Number(stock.entryPrice).toLocaleString("en-IN")}</td>
            <td class="px-4 py-3 text-right font-mono">${currentStr}</td>
            <td class="px-4 py-3 text-right text-xs">${targetStr}</td>
            <td class="px-4 py-3 text-right text-xs">${slStr}</td>
            <td class="px-4 py-3 text-center ${perfClass} font-mono text-sm">${isLive ? perfStr : '<span class="text-gray-300 text-xs">—</span>'}</td>
            <td class="px-4 py-3 text-center text-xs ${stock.statusCls}">${stock.statusLabel}</td>
        `;
        tbody.appendChild(tr);
    });
}

// ── Event listeners ───────────────────────────────────────────────────────────
function setupEventListeners() {
    document.getElementById("refresh-btn")?.addEventListener("click", async function () {
        this.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i>Refreshing…';
        await loadDashboardData();
        this.innerHTML = '<i class="fas fa-sync-alt mr-1"></i>Refresh';
    });

    ["search-input", "strategy-filter", "sector-filter", "sort-select"].forEach(id => {
        document.getElementById(id)?.addEventListener(id === "search-input" ? "input" : "change", applyFilters);
    });

    // Sortable column headers
    document.querySelectorAll(".sort-btn[data-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const sel = document.getElementById("sort-select");
            if (sel) { sel.value = th.dataset.sort; applyFilters(); }
        });
    });

    const clearAll = () => {
        ["search-input"].forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
        ["strategy-filter","sector-filter","sort-select"].forEach(id => {
            const el = document.getElementById(id); if (el) el.selectedIndex = 0;
        });
        applyFilters();
    };
    document.getElementById("clear-filters")?.addEventListener("click", clearAll);
    document.getElementById("clear-filters-empty")?.addEventListener("click", clearAll);
}

// ── UI state helpers ──────────────────────────────────────────────────────────
function showLoadingState() {
    document.getElementById("loading-state")?.classList.remove("hidden");
    document.getElementById("error-state")?.classList.add("hidden");
    document.getElementById("table-container")?.classList.add("hidden");
    document.getElementById("empty-state")?.classList.add("hidden");
}
function hideLoadingState() {
    document.getElementById("loading-state")?.classList.add("hidden");
}
function showErrorState() {
    document.getElementById("loading-state")?.classList.add("hidden");
    document.getElementById("error-state")?.classList.remove("hidden");
}
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
