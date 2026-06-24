/**
 * Stock Dashboard - Filter & Search Logic
 * Handles search, sector filtering, and sorting
 */

// Initialize filters on page load
document.addEventListener('DOMContentLoaded', function() {
    setupFilterListeners();
});

/**
 * Setup filter event listeners
 */
function setupFilterListeners() {
    // Search input with debounce
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(applyFilters, 300));
    }
    
    // Sector filter
    const sectorFilter = document.getElementById('sector-filter');
    if (sectorFilter) {
        sectorFilter.addEventListener('change', applyFilters);
    }
    
    // Sort select
    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', applyFilters);
    }
}

/**
 * Apply all filters and re-render table
 */
function applyFilters() {
    if (!dashboardData || !dashboardData.stocks) return;
    
    // Start with all stocks
    let filtered = [...dashboardData.stocks];
    
    // Apply search filter
    const searchTerm = document.getElementById('search-input').value.toLowerCase().trim();
    if (searchTerm) {
        filtered = filtered.filter(stock => {
            return stock.name.toLowerCase().includes(searchTerm) ||
                   stock.ticker.toLowerCase().includes(searchTerm) ||
                   (stock.sector && stock.sector.toLowerCase().includes(searchTerm));
        });
    }
    
    // Apply sector filter
    const selectedSector = document.getElementById('sector-filter').value;
    if (selectedSector !== 'all') {
        filtered = filtered.filter(stock => stock.sector === selectedSector);
    }
    
    // Apply sorting
    const sortBy = document.getElementById('sort-select').value;
    filtered = sortStocks(filtered, sortBy);
    
    // Update global filtered stocks
    filteredStocks = filtered;
    
    // Re-render table
    renderStockTable();
    updateFilteredCount();
}

/**
 * Sort stocks based on selected criteria
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
        default:
            // Default: highest deviance
            sorted.sort((a, b) => b.deviance - a.deviance);
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
    applyFilters();
}

/**
 * Debounce function to limit API calls
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Made with Bob
