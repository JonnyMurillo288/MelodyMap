/**
 * MelodyMap Daily Page
 * Genre-based ML prediction discovery with Stripe billing
 * Pre-computed predictions auto-load at 12pm EST daily
 */

(function () {
  'use strict';

  // =========================================
  // State
  // =========================================
  const DailyState = {
    genre: null,
    tier: 'free',
    usageToday: 0,
    dailyLimit: 1,
    loggedIn: false,
    predictions: null,
    precomputed: {},   // genre -> ML response data (pre-computed at 12pm EST)
    precomputedReady: false,
  };

  // DOM refs
  const loginSection = document.getElementById('loginSection');
  const userSection = document.getElementById('userSection');
  const tierBadge = document.getElementById('tierBadge');
  const usageCounter = document.getElementById('usageCounter');
  const upgradeSection = document.getElementById('upgradeSection');
  const genrePicker = document.getElementById('genrePicker');
  const genreSpinner = document.getElementById('genreSpinner');
  const seedArtistCard = document.getElementById('seedArtistCard');
  const seedArtistTitle = document.getElementById('seedArtistTitle');
  const seedArtistSubtitle = document.getElementById('seedArtistSubtitle');
  const resultsCard = document.getElementById('resultsCard');
  const upgradeModal = document.getElementById('upgradeModal');

  // =========================================
  // Initialize
  // =========================================
  document.addEventListener('DOMContentLoaded', () => {
    fetchUserTier();
    setupGenreButtons();
    setupSavedPanel();
    checkPaymentResult();
    loadPrecomputedPredictions();
  });

  // =========================================
  // Login
  // =========================================
  window.startLogin = function () {
    const popup = window.open('/auth/start', 'spotify_auth', 'width=500,height=700');
    window.addEventListener('message', function handler(e) {
      if (e.data && e.data.auth === 'done') {
        window.removeEventListener('message', handler);
        if (popup) popup.close();
        DailyState.loggedIn = true;
        fetchUserTier();
      }
    });
  };

  // =========================================
  // User Tier
  // =========================================
  async function fetchUserTier() {
    try {
      const res = await fetch('/api/user/tier', {
        headers: { 'X-SDS-Token': window.SDSToken },
      });
      if (res.ok) {
        const data = await res.json();
        DailyState.tier = data.tier;
        DailyState.usageToday = data.usage_today;
        DailyState.dailyLimit = data.daily_limit;
        DailyState.loggedIn = true;
        updateTierUI();
      }
    } catch (err) {
      console.log('[daily] Could not fetch tier info:', err);
    }
  }

  function updateTierUI() {
    if (DailyState.loggedIn) {
      loginSection.style.display = 'none';
      userSection.style.display = '';

      if (DailyState.tier === 'paid') {
        tierBadge.textContent = 'Unlimited';
        tierBadge.className = 'badge badge-accent';
        usageCounter.textContent = `${DailyState.usageToday} playlists used today`;
        upgradeSection.style.display = 'none';
      } else {
        tierBadge.textContent = 'Free';
        tierBadge.className = 'badge';
        usageCounter.textContent = `${DailyState.usageToday}/1 playlists used today`;
        upgradeSection.style.display = '';
      }
    } else {
      loginSection.style.display = '';
      userSection.style.display = 'none';
      upgradeSection.style.display = 'none';
    }
  }

  // =========================================
  // Pre-computed Predictions (auto-load)
  // =========================================
  async function loadPrecomputedPredictions() {
    try {
      const res = await fetch('/api/daily/today', {
        headers: { 'X-SDS-Token': window.SDSToken },
      });
      if (!res.ok) {
        console.log('[daily] Pre-computed predictions not available');
        return;
      }

      const data = await res.json();
      if (data.ready && data.genres) {
        DailyState.precomputed = data.genres;
        DailyState.precomputedReady = true;

        // Mark genre buttons that have pre-computed data
        const buttons = genrePicker.querySelectorAll('.genre-btn');
        buttons.forEach(btn => {
          const genre = btn.dataset.genre;
          if (DailyState.precomputed[genre]) {
            btn.classList.add('precomputed');
          }
        });

        console.log(`[daily] Loaded pre-computed predictions for ${Object.keys(data.genres).length} genres`);

        // Auto-select the first available genre
        const firstGenre = Object.keys(data.genres)[0];
        if (firstGenre) {
          const firstBtn = genrePicker.querySelector(`[data-genre="${firstGenre}"]`);
          if (firstBtn) {
            selectGenre(firstGenre, firstBtn);
          }
        }
      }
    } catch (err) {
      console.log('[daily] Could not load pre-computed predictions:', err);
    }
  }

  // =========================================
  // Genre Selection
  // =========================================
  function setupGenreButtons() {
    const buttons = genrePicker.querySelectorAll('.genre-btn');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const genre = btn.dataset.genre;
        selectGenre(genre, btn);
      });
    });
  }

  async function selectGenre(genre, btn) {
    // Update active button
    genrePicker.querySelectorAll('.genre-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    DailyState.genre = genre;

    // Check if we have pre-computed data for this genre
    if (DailyState.precomputed[genre]) {
      const data = DailyState.precomputed[genre];
      DailyState.predictions = data;

      // Show seed artist info
      seedArtistCard.style.display = '';
      seedArtistTitle.textContent = `Today's Artist: ${data.src_artist_name}`;
      const latency = data.latency_ms ? ` | ${data.latency_ms.toFixed(0)}ms` : '';
      seedArtistSubtitle.textContent = `Genre: ${data.genre} | ${data.neighbors.length} predicted collaborations${latency}`;

      // Render results table
      renderResults(data);
      return;
    }

    // No pre-computed data - fall back to on-demand prediction
    // Check tier limits for on-demand requests
    if (DailyState.tier === 'free' && DailyState.usageToday >= 1) {
      showUpgradeModal();
      return;
    }

    // Show spinner
    genreSpinner.classList.add('visible');
    seedArtistCard.style.display = 'none';
    resultsCard.style.display = 'none';

    try {
      const today = new Date().toISOString().split('T')[0];
      const res = await fetch('/api/daily/predict', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-SDS-Token': window.SDSToken,
        },
        body: JSON.stringify({ genre, date: today, limit: 10 }),
      });

      if (res.status === 403) {
        const errData = await res.json();
        if (errData.error === 'daily_limit_reached') {
          showUpgradeModal();
          return;
        }
      }

      if (!res.ok) {
        const errText = await res.text();
        console.error('[daily] Prediction failed:', errText);
        alert('Failed to load predictions. Please try again.');
        return;
      }

      const data = await res.json();
      DailyState.predictions = data;

      // Update usage
      DailyState.usageToday++;
      updateTierUI();

      // Show seed artist info
      seedArtistCard.style.display = '';
      seedArtistTitle.textContent = `Today's Artist: ${data.src_artist_name}`;
      seedArtistSubtitle.textContent = `Genre: ${data.genre} | ${data.neighbors.length} predicted collaborations | ${data.latency_ms.toFixed(0)}ms`;

      // Render results table
      renderResults(data);

    } catch (err) {
      console.error('[daily] Error fetching predictions:', err);
      alert('Network error. Please try again.');
    } finally {
      genreSpinner.classList.remove('visible');
    }
  }

  // =========================================
  // Results Rendering
  // =========================================
  async function renderResults(data) {
    resultsCard.style.display = '';
    const tableEl = document.getElementById('dailyTable');

    // Resolve artist names from GIDs
    const gids = new Set();
    gids.add(data.src_artist_id);
    data.neighbors.forEach(n => gids.add(n.dst_artist_id));

    let nameMap = {};
    try {
      const res = await fetch('/artistLookupByGID', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gids: Array.from(gids) }),
      });
      if (res.ok) {
        const names = await res.json();
        nameMap = names.artistNames || {};
      }
    } catch (err) {
      console.error('[daily] Name resolution failed:', err);
    }

    const srcName = nameMap[data.src_artist_id] || data.src_artist_name || data.src_artist_id;

    // Build table rows
    const rows = data.neighbors.map(n => {
      const dstName = nameMap[n.dst_artist_id] || n.dst_artist_id;
      const isSaved = SavedConnectionsStore.has(data.src_artist_id, n.dst_artist_id);
      return {
        srcArtistId: data.src_artist_id,
        srcName,
        dstArtistId: n.dst_artist_id,
        dstName,
        probability: n.probability,
        tracks: n.tracks || [],
        isSaved,
      };
    });

    // Sort by probability descending
    rows.sort((a, b) => b.probability - a.probability);

    // Render using DataTable
    if ($.fn.DataTable.isDataTable('#dailyResultsTable')) {
      $('#dailyResultsTable').DataTable().destroy();
      tableEl.innerHTML = '';
    }

    tableEl.innerHTML = `<table id="dailyResultsTable" class="display" style="width:100%"></table>`;

    const dt = $('#dailyResultsTable').DataTable({
      data: rows,
      columns: [
        {
          title: 'Save',
          data: null,
          orderable: false,
          width: '60px',
          render: function (data, type, row) {
            const saved = SavedConnectionsStore.has(row.srcArtistId, row.dstArtistId);
            return `<button class="save-btn ${saved ? 'saved' : 'unsaved'}"
                      data-src="${escAttr(row.srcArtistId)}"
                      data-dst="${escAttr(row.dstArtistId)}"
                      title="${saved ? 'Remove' : 'Save'}">
                      ${saved ? '&#x2715' : '&#x2b;'}
                    </button>`;
          },
        },
        {
          title: 'Predicted Collaborator',
          data: 'dstName',
        },
        {
          title: 'Collaboration Score',
          data: 'probability',
          render: function (data) {
            const pct = (data * 100).toFixed(1);
            return `<div class="prob-bar-container">
                      <div class="prob-bar" style="width:${pct}%"></div>
                      <span class="prob-value">${pct}%</span>
                    </div>`;
          },
        },
        {
          title: 'Tracks',
          data: 'tracks',
          render: function (data) {
            return `${data.length} synthetic track${data.length !== 1 ? 's' : ''}`;
          },
        },
      ],
      pageLength: 25,
      order: [[2, 'desc']],
      language: {
        emptyTable: 'No predictions available for this genre.',
      },
    });

    // Handle save button clicks
    $('#dailyResultsTable').on('click', '.save-btn', function () {
      const srcId = this.dataset.src;
      const dstId = this.dataset.dst;

      const row = rows.find(r => r.srcArtistId === srcId && r.dstArtistId === dstId);
      if (!row) return;

      if (SavedConnectionsStore.has(srcId, dstId)) {
        SavedConnectionsStore.remove(srcId, dstId);
      } else {
        SavedConnectionsStore.add(srcId, dstId, row.tracks);
      }

      // Re-render table to update button states
      dt.rows().invalidate().draw(false);

      // Refresh saved panel
      if (window._dailySavedPanel) {
        window._dailySavedPanel.refresh();
      }
    });

    // Setup collapse toggle
    const collapseBtn = document.getElementById('collapseDaily');
    const container = document.getElementById('dailyTableContainer');
    if (collapseBtn && container) {
      collapseBtn.onclick = () => {
        const hidden = container.style.display === 'none';
        container.style.display = hidden ? '' : 'none';
        collapseBtn.textContent = hidden ? '\u2212' : '+';
      };
    }
  }

  // =========================================
  // Saved Connections Panel
  // =========================================
  function setupSavedPanel() {
    // Override the playlist endpoint for daily page
    const panel = new SavedConnectionsPanel();
    window._dailySavedPanel = panel;

    // Override the createPlaylist method to use the daily endpoint
    panel.createPlaylist = async function () {
      const connections = SavedConnectionsStore.getAll();
      if (connections.length === 0) {
        alert('No saved connections to create a playlist from.');
        return;
      }

      const playlistName = this.playlistNameInput?.value.trim() || 'MelodyMap Daily Playlist';

      if (this.createBtn) {
        this.createBtn.disabled = true;
        this.createBtn.textContent = 'Creating\u2026';
      }

      try {
        const res = await fetch('/api/daily/create-playlist', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-SDS-Token': window.SDSToken,
          },
          body: JSON.stringify({
            playlistName,
            connections: connections.map(c => ({
              srcArtistId: c.srcArtistId,
              dstArtistId: c.dstArtistId,
              synthTrackIds: c.synthTrackIds || [],
            })),
          }),
        });

        const data = await res.json();

        if (data.auth_required) {
          window.open(data.auth_url, 'spotify_auth', 'width=500,height=700');
          return;
        }

        if (data.url) {
          const link = document.createElement('a');
          link.href = data.url;
          link.target = '_blank';
          link.className = 'btn btn-primary';
          link.textContent = 'Open Playlist on Spotify';
          link.style.marginTop = '1rem';
          link.style.display = 'inline-block';

          const bar = document.getElementById('savedActionsBar');
          const existing = bar.querySelector('.playlist-link');
          if (existing) existing.remove();
          link.classList.add('playlist-link');
          bar.appendChild(link);
        } else if (data.error) {
          alert('Failed to create playlist: ' + data.error);
        }
      } catch (err) {
        console.error('[daily] Playlist creation error:', err);
        alert('Failed to create playlist. Please try again.');
      } finally {
        if (this.createBtn) {
          this.createBtn.disabled = false;
          this.createBtn.textContent = 'Create Spotify Playlist';
        }
      }
    };

    panel.refresh();
  }

  // =========================================
  // Stripe Checkout
  // =========================================
  window.startCheckout = async function (plan) {
    try {
      const res = await fetch('/api/stripe/create-checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        alert('Failed to start checkout: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      console.error('[daily] Checkout error:', err);
      alert('Failed to start checkout. Please try again.');
    }
  };

  // =========================================
  // Upgrade Modal
  // =========================================
  window.showUpgradeModal = function () {
    upgradeModal.style.display = 'flex';
  };

  window.hideUpgradeModal = function () {
    upgradeModal.style.display = 'none';
  };

  // Close modal on outside click
  upgradeModal.addEventListener('click', function (e) {
    if (e.target === upgradeModal) {
      hideUpgradeModal();
    }
  });

  // =========================================
  // Payment Result Check
  // =========================================
  function checkPaymentResult() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('payment') === 'success') {
      // Remove the query param
      window.history.replaceState({}, '', '/daily');
      // Refresh tier after a short delay (webhook may take a moment)
      setTimeout(() => {
        fetchUserTier();
        alert('Payment successful! Your account has been upgraded.');
      }, 2000);
    } else if (params.get('payment') === 'cancelled') {
      window.history.replaceState({}, '', '/daily');
    }
  }

  // =========================================
  // Helpers
  // =========================================
  function escAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }
})();
