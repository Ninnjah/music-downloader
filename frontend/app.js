// Configuration - use relative URLs since frontend is served from same origin
const API_BASE_URL = '';

// DOM elements
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const loading = document.getElementById('loading');
const error = document.getElementById('error');
const results = document.getElementById('results');
const tracksList = document.getElementById('tracksList');
const downloadStatus = document.getElementById('downloadStatus');
const statusContent = document.getElementById('statusContent');

// Track download status tracking
const activeDownloads = new Map();

// Event listeners
searchBtn.addEventListener('click', handleSearch);
searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        handleSearch();
    }
});

async function handleSearch() {
    const query = searchInput.value.trim();
    
    if (!query) {
        showError('Please enter a search query');
        return;
    }
    
    hideError();
    showLoading();
    hideResults();
    
    try {
        const tracks = await searchTracks(query);
        await displayTracks(tracks);
        hideLoading();
        showResults();
    } catch (err) {
        hideLoading();
        showError(`Search failed: ${err.message}`);
    }
}

async function searchTracks(query) {
    const response = await fetch(`${API_BASE_URL}/api/search`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query, limit: 20 }),
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Search failed');
    }
    
    return await response.json();
}

async function displayTracks(tracks) {
    if (tracks.length === 0) {
        tracksList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No tracks found</p>';
        return;
    }
    
    // Check which tracks are already downloaded
    const downloadedTracks = new Set();
    const checkPromises = tracks.map(async (track) => {
        try {
            const response = await fetch(`${API_BASE_URL}/api/track/${track.id}/exists`);
            if (response.ok) {
                const data = await response.json();
                if (data.exists) {
                    downloadedTracks.add(track.id);
                }
            }
        } catch (err) {
            // Silently fail - just won't show as downloaded
        }
    });
    
    await Promise.all(checkPromises);
    
    tracksList.innerHTML = tracks.map(track => createTrackCard(track, downloadedTracks.has(track.id))).join('');
    
    // Add event listeners to download buttons
    tracks.forEach(track => {
        const downloadBtn = document.getElementById(`download-${track.id}`);
        if (downloadBtn && !downloadedTracks.has(track.id)) {
            downloadBtn.addEventListener('click', () => downloadTrack(track));
        }
    });
}

function createTrackCard(track, isDownloaded = false) {
    const albumArt = track.album_art || 'https://via.placeholder.com/80?text=No+Image';
    const duration = formatDuration(track.duration_ms);
    const isDownloading = activeDownloads.has(track.id);
    
    return `
        <div class="track-card">
            <img src="${albumArt}" alt="${track.album}" class="track-art" />
            <div class="track-info">
                <div class="track-name">${escapeHtml(track.name)}</div>
                <div class="track-artist">${escapeHtml(track.artist)}</div>
                <div class="track-album">${escapeHtml(track.album)} • ${duration}</div>
            </div>
            <div class="track-actions">
                ${isDownloaded ? `
                    <span class="downloaded-badge">✓ Downloaded</span>
                ` : `
                    <button 
                        id="download-${track.id}" 
                        class="btn btn-download"
                        ${isDownloading ? 'disabled' : ''}
                    >
                        ${isDownloading ? 'Downloading...' : 'Download'}
                    </button>
                `}
            </div>
        </div>
    `;
}

async function downloadTrack(track) {
    const trackId = track.id;
    
    // Get download location preference
    const downloadLocation = document.getElementById('downloadLocation').value;
    
    // Mark as downloading
    activeDownloads.set(trackId, { status: 'queued' });
    updateDownloadButton(trackId, true);
    
    try {
        // Start download
        const response = await fetch(`${API_BASE_URL}/api/download`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                track_id: trackId,
                location: downloadLocation  // 'local' or 'navidrome'
            }),
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Download failed');
        }
        
        // Show download status section
        showDownloadStatus();
        addStatusItem(trackId, track, 'queued', 'Download queued...');
        
        // Poll for status updates
        pollDownloadStatus(trackId, track);
        
    } catch (err) {
        updateDownloadButton(trackId, false);
        activeDownloads.delete(trackId);
        showError(`Download failed: ${err.message}`);
    }
}

async function pollDownloadStatus(trackId, track) {
    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/api/download/status/${trackId}`);
            
            if (!response.ok) {
                clearInterval(pollInterval);
                updateStatusItem(trackId, 'error', 'Failed to check status');
                updateDownloadButton(trackId, false);
                activeDownloads.delete(trackId);
                return;
            }
            
            const status = await response.json();
            activeDownloads.set(trackId, status);
            updateStatusItem(trackId, status.status, status.message);
            
            if (status.status === 'completed' || status.status === 'error') {
                clearInterval(pollInterval);
                updateDownloadButton(trackId, false);
                activeDownloads.delete(trackId);
                
                if (status.status === 'completed') {
                    // If it's a local download, trigger browser download
                    if (status.download_url) {
                        // Trigger browser download (saves to user's Downloads folder)
                        const link = document.createElement('a');
                        link.href = status.download_url;
                        link.download = status.file_path.split('/').pop() || 'download.mp3';
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                        
                        updateStatusItem(trackId, 'completed', 'Download started - check your Downloads folder');
                    } else {
                        // Navidrome download - just show as completed
                        updateTrackToDownloaded(trackId);
                    }
                    
                    // Remove status after a delay
                    setTimeout(() => {
                        removeStatusItem(trackId);
                    }, 5000);
                }
            }
        } catch (err) {
            clearInterval(pollInterval);
            updateStatusItem(trackId, 'error', `Error: ${err.message}`);
            updateDownloadButton(trackId, false);
            activeDownloads.delete(trackId);
        }
    }, 2000); // Poll every 2 seconds
}

function addStatusItem(trackId, track, status, message) {
    const statusItem = document.createElement('div');
    statusItem.id = `status-${trackId}`;
    statusItem.className = `status-item status-${status}`;
    statusItem.innerHTML = `
        <h3>${escapeHtml(track.name)} - ${escapeHtml(track.artist)}</h3>
        <p>${escapeHtml(message)}</p>
    `;
    statusContent.appendChild(statusItem);
}

function updateStatusItem(trackId, status, message) {
    const statusItem = document.getElementById(`status-${trackId}`);
    if (statusItem) {
        statusItem.className = `status-item status-${status}`;
        const p = statusItem.querySelector('p');
        if (p) {
            p.textContent = message;
        }
    }
}

function removeStatusItem(trackId) {
    const statusItem = document.getElementById(`status-${trackId}`);
    if (statusItem) {
        statusItem.remove();
        
        // Hide status section if no items left
        if (statusContent.children.length === 0) {
            hideDownloadStatus();
        }
    }
}

function updateDownloadButton(trackId, downloading) {
    const button = document.getElementById(`download-${trackId}`);
    if (button) {
        button.disabled = downloading;
        button.textContent = downloading ? 'Downloading...' : 'Download';
    }
}

function updateTrackToDownloaded(trackId) {
    const button = document.getElementById(`download-${trackId}`);
    if (button) {
        const trackCard = button.closest('.track-card');
        if (trackCard) {
            const actionsDiv = trackCard.querySelector('.track-actions');
            if (actionsDiv) {
                actionsDiv.innerHTML = '<span class="downloaded-badge">✓ Downloaded</span>';
            }
        }
    }
}

function formatDuration(ms) {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showLoading() {
    loading.classList.remove('hidden');
}

function hideLoading() {
    loading.classList.add('hidden');
}

function showError(message) {
    error.textContent = message;
    error.classList.remove('hidden');
}

function hideError() {
    error.classList.add('hidden');
}

function showResults() {
    results.classList.remove('hidden');
}

function hideResults() {
    results.classList.add('hidden');
}

function showDownloadStatus() {
    downloadStatus.classList.remove('hidden');
}

function hideDownloadStatus() {
    downloadStatus.classList.add('hidden');
}

