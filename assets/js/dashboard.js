/**
 * Stock Performance Dashboard - Main Logic
 * Handles data loading, rendering, and real-time updates
 */

let dashboardData = null;
let filteredStocks = [];

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
        
        renderDashboard();
        hideLoadingState();
        
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        showErrorState();
    }
}

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
    if (!dashboardData || !dashboardData.summary) return;
    
    const summary = dashboardData.summary;
    
    document.getElementById('total-stocks').textContent = summary.totalStocks || 0;
    
    const avgPerf = summary.avgPerformance || 0;
    const avgPerfElement = document.getElementById('avg-performance');
    avgPerfElement.textContent = formatPercentage(avgPerf);
    avgPerfElement.className = avgPerf >= 0 ? 'text-4xl font-bold mt-2' : 'text-4xl font-bold mt-2 text-red-200';
    
    document.getElementById('active-flags').textContent = summary.activeFlags || 0;
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
    
    tr.innerHTML = `
        <td class="px-6 py-4 whitespace-nowrap">
            <div class="text-sm font-bold text-gray-900">${escapeHtml(stock.name)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(stock.ticker)}</div>
            <div class="text-xs text-blue-600 mt-1">
                <i class="fas fa-tag mr-1"></i>${escapeHtml(stock.sector || 'N/A')}
            </div>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
            ${formatDate(stock.entryDate)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 text-right font-semibold">
            ${formatCurrency(stock.entryPrice)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right font-bold">
            ${formatCurrency(stock.currentPrice)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-center">
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-center">
            ${getRiskFlagBadge(stock.riskFlag, stock.riskLevel)}
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-center">
            <a href="${escapeHtml(stock.discussionUrl)}" 
               target="_blank" 
               class="inline-flex items-center px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-semibold hover:bg-blue-200 transition">
                <i class="fas fa-external-link-alt mr-1"></i>
                View Discussion
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
    
    card.innerHTML = `
        <div class="flex justify-between items-start mb-3">
            <div>
                <h3 class="font-bold text-gray-900">${escapeHtml(stock.name)}</h3>
                <p class="text-xs text-gray-500">${escapeHtml(stock.ticker)} • ${escapeHtml(stock.sector || 'N/A')}</p>
            </div>
            ${getDevianceBadge(stock.deviance, stock.deviancePercent)}
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
                <p class="text-gray-500 text-xs">Date Mentioned</p>
                <p class="font-semibold">${formatDate(stock.entryDate)}</p>
            </div>
            <div>
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
    
    const headers = ['Stock Name', 'Ticker', 'Sector', 'Entry Date', 'Entry Price', 'Current Price', 'Deviance %', 'Risk Flag'];
    const rows = filteredStocks.map(stock => [
        stock.name,
        stock.ticker,
        stock.sector || 'N/A',
        stock.entryDate,
        stock.entryPrice,
        stock.currentPrice,
        stock.deviancePercent,
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
