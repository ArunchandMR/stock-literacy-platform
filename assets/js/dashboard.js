/**
 * Stock Performance Dashboard - Main Logic
 * Handles data loading, rendering, and real-time updates with strategy filtering
 */

let dashboardData = null;
let filteredStocks = [];
let currentStrategy = 'all'; // Track current strategy filter

// Initialize dashboard on page load
document.addEventListener('DOMContentLoaded', function() {
    loadDashboardData();
    setupEventListeners();
});

/**
 * Load dashboard data from JSON file
 */
async function loadDashboardData() {
    try {
        showLoadingState();
        
        // Fetch dashboard.json with cache busting
        const timestamp = new Date().getTime();
        const response = await fetch(`data/dashboard.json?t=${timestamp}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        dashboardData = await response.json();
        filteredStocks = [...dashboardData.stocks];
        
        // Apply current strategy filter if set
        if (currentStrategy !== 'all') {
            applyStrategyFilter(currentStrategy);
        }
        
        renderDashboard();
        hideLoadingState();
        
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        showErrorState();
    }
}

/**
 * Apply strategy filter
 */
window.applyStrategyFilter = function(strategy) {
    currentStrategy = strategy;
    
    if (!dashboardData || !dashboardData.stocks) return;
    
    if (strategy === 'all') {
        filteredStocks = [...dashboardData.stocks];
    } else {
        filteredStocks = dashboardData.stocks.filter(stock =>
            stock.strategy === strategy
        );
    }
    
    // Update active tab styling
    document.querySelectorAll('.strategy-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.getElementById(`tab-${strategy}`).classList.add('active');
    
    // Re-apply other filters if they exist
    applySearchAndFilters();
    
    renderDashboard();
    
    // Smooth scroll to table section
    setTimeout(() => {
        const tableSection = document.getElementById('table-section');
        if (tableSection) {
            tableSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }, 100);
};

/**
 * Render complete dashboard
 */
function renderDashboard() {
    renderSummaryCards();
    renderStockTable();
    updateLastRefreshed();
    updateFilteredCount();
}

/**
 * Render summary metric cards
 */
function renderSummaryCards() {
    if (!dashboardData || !dashboardData.stocks) return;
    
    const allStocks = dashboardData.stocks;
    const swingStocks = allStocks.filter(s => s.strategy === 'swing');
    const longTermStocks = allStocks.filter(s => s.strategy === 'long-term');
    
    // Total stocks
    document.getElementById('total-stocks').textContent = allStocks.length || 0;
    
    // Swing count
    document.getElementById('swing-count').textContent = swingStocks.length || 0;
    
    // Long-term count
    document.getElementById('longterm-count').textContent = longTermStocks.length || 0;
    
    // Active flags
    const activeFlags = allStocks.filter(s => s.riskLevel === 'high' || s.riskLevel === 'medium').length;
    document.getElementById('active-flags').textContent = activeFlags || 0;
}

/**
 * Render stock performance table
 */
function renderStockTable() {
    const tableBody = document.getElementById('table-body');
    const mobileCards = document.getElementById('mobile-cards');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');
    
    // Clear existing content
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
    
    // Render each stock
    filteredStocks.forEach(stock => {
        // Desktop table row
        const row = createTableRow(stock);
        tableBody.appendChild(row);
        
        // Mobile card
        const card = createMobileCard(stock);
        mobileCards.appendChild(card);
    });
}

/**
 * Create desktop table row for a stock
 */
function createTableRow(stock) {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-gray-50 transition';
    
    // Apply row color based on risk level
    if (stock.riskLevel === 'high') {
        tr.className += ' bg-red-50';
    } else if (stock.riskLevel === 'medium') {
        tr.className += ' bg-yellow-50';
    }
    
    // Calculate days held
    const daysHeld = calculateDaysHeld(stock.entryDate);
    
    // Get strategy badge
    const strategyBadge = getStrategyBadge(stock.strategy);
    
    // Format entry date/time
    const entryDateTime = formatDateTime(stock.entryDate, stock.entryTime);
    
    // Format target range
    const targetRange = formatTargetRange(stock.targetExitMin, stock.targetExitMax);
    
    tr.innerHTML = `
        <td class="px-4 py-4 whitespace-nowrap">
            <div class="text-sm font-bold text-gray-900">${escapeHtml(stock.name)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(stock.ticker)}</div>
            <div class="text-xs text-blue-600 mt-1">
                <i class="fas fa-tag mr-1"></i>${escapeHtml(stock.sector || 'N/A')}
            </div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-center">
            ${strategyBadge}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700">
            <div class="font-semibold">${formatDate(stock.entryDate)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(stock.entryTime || 'N/A')}</div>
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700 text-right font-semibold">
            ${formatCurrency(stock.entryPrice)}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-900 text-right font-bold">
            ${formatCurrency(stock.currentPrice)}
        </td>
        <td class="px-4 py-4 whitespace-nowrap text-sm text-gray-700 text-right">
            <div class="font-semibold text-green-700">${targetRange}</div>
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
            <a href="${escapeHtml(stock.discussionUrl)}" 
               target="_blank" 
               class="inline-flex items-center px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-semibold hover:bg-blue-200 transition">
                <i class="fas fa-external-link-alt mr-1"></i>
                View
            </a>
        </td>
    `;
    
    return tr;
}

/**
 * Create mobile card for a stock
 */
function createMobileCard(stock) {
    const card = document.createElement('div');
    card.className = 'p-4 border-b hover:bg-gray-50';
    
    if (stock.riskLevel === 'high') {
        card.className += ' bg-red-50';
    } else if (stock.riskLevel === 'medium') {
        card.className += ' bg-yellow-50';
    }
    
    const daysHeld = calculateDaysHeld(stock.entryDate);
    const strategyBadge = getStrategyBadge(stock.strategy);
    const targetRange = formatTargetRange(stock.targetExitMin, stock.targetExitMax);
    
    card.innerHTML = `
        <div class="flex justify-between items-start mb-3">
            <div>
                <h3 class="font-bold text-gray-900">${escapeHtml(stock.name)}</h3>
                <p class="text-xs text-gray-500">${escapeHtml(stock.ticker)} • ${escapeHtml(stock.sector || 'N/A')}</p>
            </div>
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
        </div>
        
        <div class="mb-2">
            ${strategyBadge}
        </div>
        
        <div class="grid grid-cols-2 gap-3 mb-3 text-sm">
            <div>
                <p class="text-gray-500 text-xs">Entry Price</p>
                <p class="font-semibold">${formatCurrency(stock.entryPrice)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Current Price</p>
                <p class="font-bold">${formatCurrency(stock.currentPrice)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Target Range</p>
                <p class="font-semibold text-green-700">${targetRange}</p>
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
        
        <a href="${escapeHtml(stock.discussionUrl)}" 
           target="_blank" 
           class="block text-center bg-blue-100 text-blue-700 rounded-lg py-2 text-sm font-semibold hover:bg-blue-200 transition">
            <i class="fas fa-external-link-alt mr-1"></i>View Discussion
        </a>
    `;
    
    return card;
}

/**
 * Get strategy badge HTML
 */
function getStrategyBadge(strategy) {
    if (strategy === 'swing') {
        return `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-purple-100 text-purple-700">
            <i class="fas fa-bolt mr-1"></i>Swing
        </span>`;
    } else if (strategy === 'long-term') {
        return `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-green-100 text-green-700">
            <i class="fas fa-chart-line mr-1"></i>Long Term
        </span>`;
    }
    return '<span class="text-xs text-gray-500">N/A</span>';
}

/**
 * Calculate days held
 */
function calculateDaysHeld(entryDate) {
    if (!entryDate) return 0;
    const entry = new Date(entryDate);
    const today = new Date();
    const diffTime = Math.abs(today - entry);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
}

/**
 * Format date and time
 */
function formatDateTime(dateString, timeString) {
    if (!dateString) return 'N/A';
    const formatted = formatDate(dateString);
    if (timeString) {
        return `${formatted} ${timeString}`;
    }
    return formatted;
}

/**
 * Format target range
 */
function formatTargetRange(min, max) {
    if (!min || !max) return 'N/A';
    return `₹${parseFloat(min).toFixed(2)} - ₹${parseFloat(max).toFixed(2)}`;
}

/**
 * Get deviance badge HTML
 */
function getDevianceBadge(deviance, deviancePercent) {
    let icon, colorClass, bgClass;
    
    if (deviance > 0) {
        icon = '🟩';
        colorClass = 'text-green-700';
        bgClass = 'bg-green-100';
    } else if (deviance < 0) {
        icon = '🟥';
        colorClass = 'text-red-700';
        bgClass = 'bg-red-100';
    } else {
        icon = '🟨';
        colorClass = 'text-yellow-700';
        bgClass = 'bg-yellow-100';
    }
    
    return `
        <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-bold ${bgClass} ${colorClass}">
            ${icon} ${escapeHtml(deviancePercent)}
        </span>
    `;
}

/**
 * Get risk flag badge HTML
 */
function getRiskFlagBadge(riskFlag, riskLevel) {
    let icon, colorClass, bgClass;
    
    switch (riskLevel) {
        case 'high':
            icon = '🚨';
            colorClass = 'text-red-700';
            bgClass = 'bg-red-100';
            break;
        case 'medium':
            icon = '⚠️';
            colorClass = 'text-yellow-700';
            bgClass = 'bg-yellow-100';
            break;
        default:
            icon = '✅';
            colorClass = 'text-green-700';
            bgClass = 'bg-green-100';
    }
    
    return `
        <span class="inline-flex items-center px-2 py-1 rounded-full text-xs font-semibold ${bgClass} ${colorClass}">
            ${icon} ${escapeHtml(riskFlag)}
        </span>
    `;
}

/**
 * Update last refreshed timestamp
 */
function updateLastRefreshed() {
    if (!dashboardData || !dashboardData.lastUpdated) return;
    
    const lastUpdated = new Date(dashboardData.lastUpdated);
    const formatted = lastUpdated.toLocaleString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true
    });
    
    document.getElementById('last-updated').textContent = formatted;
}

/**
 * Update filtered count
 */
function updateFilteredCount() {
    document.getElementById('filtered-count').textContent = filteredStocks.length;
}

/**
 * Apply search and filters (called from filters.js)
 */
function applySearchAndFilters() {
    if (!dashboardData || !dashboardData.stocks) return;
    
    // Start with strategy-filtered stocks
    let stocks = dashboardData.stocks;
    if (currentStrategy !== 'all') {
        stocks = stocks.filter(stock => stock.strategy === currentStrategy);
    }
    
    // Apply search
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    if (searchTerm) {
        stocks = stocks.filter(stock => 
            stock.name.toLowerCase().includes(searchTerm) ||
            stock.ticker.toLowerCase().includes(searchTerm)
        );
    }
    
    // Apply sector filter
    const sectorFilter = document.getElementById('sector-filter').value;
    if (sectorFilter !== 'all') {
        stocks = stocks.filter(stock => stock.sector === sectorFilter);
    }
    
    // Apply sorting
    const sortBy = document.getElementById('sort-select').value;
    stocks = sortStocks(stocks, sortBy);
    
    filteredStocks = stocks;
    renderStockTable();
    updateFilteredCount();
}

/**
 * Sort stocks based on criteria
 */
function sortStocks(stocks, sortBy) {
    const sorted = [...stocks];
    
    switch (sortBy) {
        case 'deviance-desc':
            sorted.sort((a, b) => b.deviance - a.deviance);
            break;
        case 'deviance-asc':
            sorted.sort((a, b) => a.deviance - b.deviance);
            break;
        case 'date-desc':
            sorted.sort((a, b) => new Date(b.entryDate) - new Date(a.entryDate));
            break;
        case 'date-asc':
            sorted.sort((a, b) => new Date(a.entryDate) - new Date(b.entryDate));
            break;
        case 'name-asc':
            sorted.sort((a, b) => a.name.localeCompare(b.name));
            break;
    }
    
    return sorted;
}

/**
 * Clear all filters
 */
function clearAllFilters() {
    document.getElementById('search-input').value = '';
    document.getElementById('sector-filter').value = 'all';
    document.getElementById('sort-select').value = 'deviance-desc';
    
    // Reset to all stocks strategy
    currentStrategy = 'all';
    document.querySelectorAll('.strategy-tab').forEach(tab => tab.classList.remove('active'));
    document.getElementById('tab-all').classList.add('active');
    
    applySearchAndFilters();
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', function() {
        this.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i>Refreshing...';
        loadDashboardData();
        setTimeout(() => {
            this.innerHTML = '<i class="fas fa-sync-alt mr-1"></i>Refresh';
        }, 1000);
    });
    
    // Search and filters
    document.getElementById('search-input').addEventListener('input', applySearchAndFilters);
    document.getElementById('sector-filter').addEventListener('change', applySearchAndFilters);
    document.getElementById('sort-select').addEventListener('change', applySearchAndFilters);
    
    // Export CSV
    document.getElementById('export-csv').addEventListener('click', exportToCSV);
    
    // Print
    document.getElementById('print-table').addEventListener('click', function() {
        window.print();
    });
    
    // Clear filters
    document.getElementById('clear-filters').addEventListener('click', clearAllFilters);
    document.getElementById('clear-filters-empty').addEventListener('click', clearAllFilters);
}

/**
 * Export data to CSV
 */
function exportToCSV() {
    if (!filteredStocks || filteredStocks.length === 0) {
        alert('No data to export');
        return;
    }
    
    const headers = ['Stock Name', 'Ticker', 'Sector', 'Strategy', 'Entry Date', 'Entry Time', 'Entry Price', 'Current Price', 'Target Min', 'Target Max', 'Stop Loss', 'Deviance %', 'Days Held', 'Risk Flag'];
    const rows = filteredStocks.map(stock => [
        stock.name,
        stock.ticker,
        stock.sector || 'N/A',
        stock.strategy || 'N/A',
        stock.entryDate,
        stock.entryTime || 'N/A',
        stock.entryPrice,
        stock.currentPrice,
        stock.targetExitMin || 'N/A',
        stock.targetExitMax || 'N/A',
        stock.stopLoss || 'N/A',
        stock.deviancePercent,
        calculateDaysHeld(stock.entryDate),
        stock.riskFlag
    ]);
    
    let csvContent = headers.join(',') + '\n';
    rows.forEach(row => {
        csvContent += row.map(cell => `"${cell}"`).join(',') + '\n';
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    
    link.setAttribute('href', url);
    link.setAttribute('download', `stock-dashboard-${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Show loading state
 */
function showLoadingState() {
    document.getElementById('loading-state').classList.remove('hidden');
    document.getElementById('error-state').classList.add('hidden');
    document.getElementById('table-container').classList.add('hidden');
    document.getElementById('mobile-cards').classList.add('hidden');
}

/**
 * Hide loading state
 */
function hideLoadingState() {
    document.getElementById('loading-state').classList.add('hidden');
}

/**
 * Show error state
 */
function showErrorState() {
    document.getElementById('loading-state').classList.add('hidden');
    document.getElementById('error-state').classList.remove('hidden');
    document.getElementById('table-container').classList.add('hidden');
    document.getElementById('mobile-cards').classList.add('hidden');
}

/**
 * Format currency (Indian Rupee)
 */
function formatCurrency(value) {
    if (value === null || value === undefined) return 'N/A';
    return '₹' + parseFloat(value).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Format percentage
 */
function formatPercentage(value) {
    if (value === null || value === undefined) return 'N/A';
    const sign = value >= 0 ? '+' : '';
    return sign + parseFloat(value).toFixed(2) + '%';
}

/**
 * Format date (DD-MMM-YYYY)
 */
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-IN', {
        day: '2-digit',
        month: 'short',
        year: 'numeric'
    });
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&',
        '<': '<',
        '>': '>',
        '"': '"',
        "'": '&#039;'
    };
    return text.toString().replace(/[&<>"']/g, m => map[m]);
}

// Made with Bob
