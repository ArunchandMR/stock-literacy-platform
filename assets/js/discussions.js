/**
 * GitHub Discussions Integration
 * Fetches and displays discussions from GitHub API
 */

// Configuration - UPDATE THIS WITH YOUR REPO
const GITHUB_REPO_OWNER = 'ArunchandMR';
const GITHUB_REPO_NAME = 'stock-literacy-platform';
const GITHUB_API_URL = `https://api.github.com/repos/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/discussions`;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    loadDiscussions();
    setupSearchFilter();
});

/**
 * Load discussions from GitHub API
 */
async function loadDiscussions() {
    const container = document.getElementById('discussions-container');
    const loading = document.getElementById('discussions-loading');
    const empty = document.getElementById('discussions-empty');
    
    try {
        // Note: GitHub Discussions API requires GraphQL
        // For now, we'll show a message to use GitHub Discussions directly
        
        loading.classList.add('hidden');
        container.classList.remove('hidden');
        
        // Show instruction card
        container.innerHTML = `
            <div class="bg-blue-50 border-l-4 border-blue-500 p-6 rounded-lg">
                <div class="flex items-start">
                    <i class="fas fa-info-circle text-blue-500 text-2xl mr-4"></i>
                    <div>
                        <h3 class="text-lg font-bold text-gray-800 mb-2">
                            GitHub Discussions Integration
                        </h3>
                        <p class="text-gray-700 mb-4">
                            Your discussions are hosted on GitHub Discussions. Click the button below to view and participate in all discussions.
                        </p>
                        <a href="https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/discussions" 
                           target="_blank"
                           class="inline-flex items-center bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 transition font-semibold">
                            <i class="fab fa-github mr-2"></i>
                            View All Discussions on GitHub
                        </a>
                    </div>
                </div>
            </div>
            
            <div class="mt-6 bg-white rounded-lg shadow-md p-6">
                <h3 class="text-xl font-bold text-gray-800 mb-4">
                    <i class="fas fa-lightbulb mr-2 text-yellow-500"></i>
                    How to Link Discussions to Stocks
                </h3>
                <ol class="space-y-3 text-gray-700">
                    <li class="flex items-start">
                        <span class="font-bold text-blue-600 mr-3">1.</span>
                        <span>Create a new discussion on GitHub for each stock analysis</span>
                    </li>
                    <li class="flex items-start">
                        <span class="font-bold text-blue-600 mr-3">2.</span>
                        <span>Copy the discussion URL from your browser</span>
                    </li>
                    <li class="flex items-start">
                        <span class="font-bold text-blue-600 mr-3">3.</span>
                        <span>Edit <code class="bg-gray-100 px-2 py-1 rounded">data/stocks.json</code></span>
                    </li>
                    <li class="flex items-start">
                        <span class="font-bold text-blue-600 mr-3">4.</span>
                        <span>Add the URL to the <code class="bg-gray-100 px-2 py-1 rounded">discussionUrl</code> field</span>
                    </li>
                    <li class="flex items-start">
                        <span class="font-bold text-blue-600 mr-3">5.</span>
                        <span>The dashboard will automatically link to your discussions!</span>
                    </li>
                </ol>
            </div>
        `;
        
    } catch (error) {
        console.error('Error loading discussions:', error);
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
    }
}

/**
 * Setup search and filter
 */
function setupSearchFilter() {
    const searchInput = document.getElementById('discussion-search');
    const categoryFilter = document.getElementById('category-filter');
    
    if (searchInput) {
        searchInput.addEventListener('input', debounce(filterDiscussions, 300));
    }
    
    if (categoryFilter) {
        categoryFilter.addEventListener('change', filterDiscussions);
    }
}

/**
 * Filter discussions
 */
function filterDiscussions() {
    // This would filter discussions if we were loading them via API
    // For now, it's a placeholder
    console.log('Filtering discussions...');
}

/**
 * Debounce function
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
