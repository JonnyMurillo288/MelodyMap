/**
 * ML Page v2 - DataTables Integration
 * Uses DataTables 2.3.6 with expandable rows to show track features
 * CDN: //cdn.datatables.net/2.3.6/js/dataTables.min.js
 */

/**
 * SavedConnectionsStore — localStorage-backed store for user-saved
 * synthetic connections (thumbs-up rows in table2).
 *
 * Each entry: { srcArtistId, dstArtistId, synthTrackIds }
 */
const SavedConnectionsStore = {
  _KEY: 'melodymap_saved_connections',

  _load() {
    return JSON.parse(localStorage.getItem(this._KEY) || '[]');
  },

  _save(list) {
    localStorage.setItem(this._KEY, JSON.stringify(list));
  },

  getAll() {
    return this._load();
  },

  has(srcId, dstId) {
    return this._load().some(
      c => c.srcArtistId === srcId && c.dstArtistId === dstId
    );
  },

  add(srcId, dstId, tracks) {
    const list = this._load();
    if (list.some(c => c.srcArtistId === srcId && c.dstArtistId === dstId)) {
      return; // already saved
    }
    list.push({
      srcArtistId: srcId,
      dstArtistId: dstId,
      synthTrackIds: (tracks || []).map(t =>
        typeof t === 'object' ? (t.id || t.track_id) : t
      ),
    });
    this._save(list);
  },

  remove(srcId, dstId) {
    this._save(
      this._load().filter(
        c => !(c.srcArtistId === srcId && c.dstArtistId === dstId)
      )
    );
  },

  clear() {
    localStorage.removeItem(this._KEY);
  },
};

/**
 * SavedConnectionsPanel — manages the visible "Playlist Selection" card
 * that shows all saved connections and provides a "Create Playlist" button.
 */
class SavedConnectionsPanel {
  constructor() {
    this.card = document.getElementById('savedConnectionsCard');
    this.listEl = document.getElementById('savedConnectionsList');
    this.countEl = document.getElementById('savedCount');
    this.clearBtn = document.getElementById('clearSavedBtn');
    this.createBtn = document.getElementById('createPlaylistFromSavedBtn');
    this.playlistNameInput = document.getElementById('mlPlaylistName');
    this.collapseBtn = document.getElementById('collapseSaved');
    this.container = document.getElementById('savedContainer');
    this._nameCache = {}; // gid -> artist name

    this.clearBtn?.addEventListener('click', () => this.clearAll());
    this.createBtn?.addEventListener('click', () => this.createPlaylist());

    // Collapse toggle
    if (this.collapseBtn && this.container) {
      this.collapseBtn.addEventListener('click', () => {
        const hidden = this.container.style.display === 'none';
        this.container.style.display = hidden ? '' : 'none';
        this.collapseBtn.textContent = hidden ? '\u2212' : '+';
      });
    }
  }

  /** Refresh the panel from localStorage. Call after every add/remove. */
  async refresh() {
    const connections = SavedConnectionsStore.getAll();

    if (connections.length === 0) {
      if (this.card) this.card.style.display = 'none';
      return;
    }

    if (this.card) this.card.style.display = '';
    if (this.countEl) {
      this.countEl.textContent = `${connections.length} connection${connections.length !== 1 ? 's' : ''}`;
    }

    // Collect GIDs needing name resolution
    const gidsToResolve = new Set();
    connections.forEach(c => {
      if (c.srcArtistId && !this._nameCache[c.srcArtistId]) gidsToResolve.add(c.srcArtistId);
      if (c.dstArtistId && !this._nameCache[c.dstArtistId]) gidsToResolve.add(c.dstArtistId);
    });

    // Batch resolve via existing /artistLookupByGID endpoint
    if (gidsToResolve.size > 0) {
      try {
        const res = await fetch('/artistLookupByGID', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gids: Array.from(gidsToResolve) }),
        });
        if (res.ok) {
          const data = await res.json();
          Object.assign(this._nameCache, data.artistNames || {});
        }
      } catch (err) {
        console.error('[SavedPanel] Name resolution failed:', err);
      }
    }

    // Render list
    if (this.listEl) {
      this.listEl.innerHTML = connections.map(c => {
        const srcName = this._nameCache[c.srcArtistId] || c.srcArtistId;
        const dstName = this._nameCache[c.dstArtistId] || c.dstArtistId;
        const trackCount = (c.synthTrackIds || []).length;

        return `
          <div class="saved-connection-item" data-src="${this._escAttr(c.srcArtistId)}" data-dst="${this._escAttr(c.dstArtistId)}">
            <div class="saved-connection-info">
              <span class="saved-src">${this._escHtml(srcName)}</span>
              <span class="saved-arrow">&rarr;</span>
              <span class="saved-dst">${this._escHtml(dstName)}</span>
              <span class="saved-track-count">${trackCount} track${trackCount !== 1 ? 's' : ''}</span>
            </div>
            <button class="save-btn-themed saved saved-remove-btn" title="Remove">
              <span class="save-btn-icon">&#x2715;</span>
            </button>
          </div>`;
      }).join('');

      // Wire remove buttons
      this.listEl.querySelectorAll('.saved-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const item = btn.closest('.saved-connection-item');
          SavedConnectionsStore.remove(item.dataset.src, item.dataset.dst);
          this.refresh();
          // Dispatch event so table2 can re-render affected rows
          document.dispatchEvent(new CustomEvent('savedConnectionsChanged'));
        });
      });
    }
  }

  clearAll() {
    SavedConnectionsStore.clear();
    this.refresh();
    document.dispatchEvent(new CustomEvent('savedConnectionsChanged'));
  }

  async createPlaylist() {
    const connections = SavedConnectionsStore.getAll();
    if (connections.length === 0) {
      alert('No saved connections to create a playlist from.');
      return;
    }

    const playlistName = this.playlistNameInput?.value.trim() ||
      'MelodyMap: ML Synthetic Playlist';

    // Disable button during request
    if (this.createBtn) {
      this.createBtn.disabled = true;
      this.createBtn.textContent = 'Creating\u2026';
    }

    try {
      const res = await fetch('/api/createplaylist', {
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

      // Handle Spotify auth requirement
      if (data.auth_required) {
        this._startAuthAndRetry(data.auth_url || '/auth/start');
        return;
      }

      if (!res.ok) {
        alert('Playlist creation failed: ' + (data.error || JSON.stringify(data)));
        return;
      }

      if (data.url) {
        if (confirm('Playlist created! Open in Spotify?')) {
          window.open(data.url, '_blank');
        }
      } else {
        alert('Playlist created, but no URL was returned.');
      }
    } catch (err) {
      console.error('[CreatePlaylist] Error:', err);
      alert('Error creating playlist: ' + err.message);
    } finally {
      if (this.createBtn) {
        this.createBtn.disabled = false;
        this.createBtn.textContent = 'Create Spotify Playlist';
      }
    }
  }

  _startAuthAndRetry(authURL) {
    // Guard against infinite auth loops (e.g. redirect URI mismatch)
    console.log('[Auth] Starting Spotify auth flow, attempt #' + (this._authRetries || 1));
    console.log('[Auth] Auth URL:', authURL);
    if (!this._authRetries) this._authRetries = 0;
    this._authRetries++;
    if (this._authRetries > 2) {
      this._authRetries = 0;
      alert('Spotify auth keeps failing. Check that SPOTIFY_REDIRECT_URI points to this server (not production).');
      return;
    }

    const win = window.open(authURL, 'spotify_auth', 'width=600,height=800');
    if (!win) {
      this._authRetries = 0;
      alert('Popup blocked. Please allow popups for this site.');
      return;
    }
    const handleAuth = (event) => {
      if (!event.data || event.data.auth !== 'done') return;
      window.removeEventListener('message', handleAuth);
      if (win && !win.closed) win.close();
      this.createPlaylist().then(() => { this._authRetries = 0; });
    };
    window.addEventListener('message', handleAuth);
  }

  _escHtml(text) {
    if (!text) return '';
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  _escAttr(text) {
    if (!text) return '';
    return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
}

/**
 * TrackFeaturesDisplay - Configurable object for defining how track features
 * are displayed. Edit this object to add/modify/remove feature categories
 * and their display properties.
 *
 * Structure:
 * - categories: Array of feature category definitions
 *   - id: Unique identifier for the category
 *   - label: Display label for the category header
 *   - icon: Icon/emoji for visual identification
 *   - color: Theme color for bars and accents (CSS color)
 *   - features: Array of feature definitions within this category
 *     - key: The JSON key from RecordingFeatures (matches backend)
 *     - label: Display label for the feature
 *     - type: 'percentage' (0-1 value), 'binary' (yes/no), 'value' (raw display)
 *     - description: Optional tooltip/description
 */
const TrackFeaturesDisplay = {
  // Cover art configuration
  coverArt: {
    enabled: true,
    defaultImage: '/static/images/default-cover.png',
    size: { width: 80, height: 80 },
    position: 'left' // 'left', 'right', 'top'
  },

  // Feature categories configuration - Edit these to add/modify categories
  categories: [
    {
      id: 'mood',
      label: 'Mood',
      icon: '🎭',
      color: '#f59e0b', // amber
      features: [
        { key: 'mood_acoustic', label: 'Acoustic', type: 'percentage', description: 'How acoustic the track sounds' },
        { key: 'mood_aggressive', label: 'Aggressive', type: 'percentage', description: 'Intensity and aggression level' },
        { key: 'mood_electronic', label: 'Electronic', type: 'percentage', description: 'Electronic/synthesized sound presence' },
        { key: 'mood_happy', label: 'Happy', type: 'percentage', description: 'Positive, upbeat emotional tone' },
        { key: 'mood_party', label: 'Party', type: 'percentage', description: 'Suitability for party/dance settings' },
        { key: 'mood_relaxed', label: 'Relaxed', type: 'percentage', description: 'Calm, soothing qualities' },
        { key: 'mood_sad', label: 'Sad', type: 'percentage', description: 'Melancholic or sad emotional tone' }
      ]
    },
    {
      id: 'voice',
      label: 'Voice & Vocals',
      icon: '🎤',
      color: '#ec4899', // pink
      features: [
        { key: 'voice_instrumental_voice', label: 'Vocal', type: 'percentage', description: 'Presence of vocals' },
        { key: 'voice_instrumental_instrumental', label: 'Instrumental', type: 'percentage', description: 'Instrumental (no vocals)' }
        // { key: 'gender_female', label: 'Female Voice', type: 'percentage', description: 'Female vocal characteristics' },
        // { key: 'gender_male', label: 'Male Voice', type: 'percentage', description: 'Male vocal characteristics' }
      ]
    },
    {
      id: 'timbre',
      label: 'Timbre & Tone',
      icon: '🔊',
      color: '#8b5cf6', // violet
      features: [
        { key: 'timbre_bright', label: 'Bright', type: 'percentage', description: 'Bright, high-frequency emphasis' },
        { key: 'timbre_dark', label: 'Dark', type: 'percentage', description: 'Dark, low-frequency emphasis' },
        { key: 'tonal_atonal_tonal', label: 'Tonal', type: 'percentage', description: 'Clear tonal structure' },
        { key: 'tonal_atonal_atonal', label: 'Atonal', type: 'percentage', description: 'Lack of tonal center' }
      ]
    },
    {
      id: 'rhythm',
      label: 'Rhythm & Dance',
      icon: '💃',
      color: '#10b981', // emerald
      features: [
        { key: 'danceability', label: 'Danceability', type: 'percentage', description: 'How suitable for dancing' },
        { key: 'ismir04_rhythm_chachacha', label: 'Cha-Cha-Cha', type: 'percentage', description: 'Cha-cha-cha rhythm pattern' },
        { key: 'ismir04_rhythm_jive', label: 'Jive', type: 'percentage', description: 'Jive rhythm pattern' },
        { key: 'ismir04_rhythm_quickstep', label: 'Quickstep', type: 'percentage', description: 'Quickstep rhythm pattern' },
        { key: 'ismir04_rhythm_samba', label: 'Samba', type: 'percentage', description: 'Samba rhythm pattern' },
        { key: 'ismir04_rhythm_tango', label: 'Tango', type: 'percentage', description: 'Tango rhythm pattern' },
        { key: 'ismir04_rhythm_waltz', label: 'Waltz', type: 'percentage', description: 'Waltz rhythm pattern' },
        { key: 'ismir04_rhythm_viennesewaltz', label: 'Viennese Waltz', type: 'percentage', description: 'Viennese waltz rhythm' },
        { key: 'ismir04_rhythm_rumba_american', label: 'Rumba (American)', type: 'percentage', description: 'American rumba style' },
        { key: 'ismir04_rhythm_rumba_international', label: 'Rumba (International)', type: 'percentage', description: 'International rumba style' }
      ]
    },
    {
      id: 'genre_main',
      label: 'Genre (Dortmund)',
      icon: '🎵',
      color: '#3b82f6', // blue
      features: [
        { key: 'genre_dortmund_alternative', label: 'Alternative', type: 'percentage' },
        { key: 'genre_dortmund_blues', label: 'Blues', type: 'percentage' },
        { key: 'genre_dortmund_electronic', label: 'Electronic', type: 'percentage' },
        { key: 'genre_dortmund_folkcountry', label: 'Folk/Country', type: 'percentage' },
        { key: 'genre_dortmund_funksoulrnb', label: 'Funk/Soul/R&B', type: 'percentage' },
        { key: 'genre_dortmund_jazz', label: 'Jazz', type: 'percentage' },
        { key: 'genre_dortmund_pop', label: 'Pop', type: 'percentage' },
        { key: 'genre_dortmund_raphiphop', label: 'Rap/Hip-Hop', type: 'percentage' },
        { key: 'genre_dortmund_rock', label: 'Rock', type: 'percentage' }
      ]
    },
    {
      id: 'genre_electronic',
      label: 'Electronic Subgenres',
      icon: '🎛️',
      color: '#06b6d4', // cyan
      features: [
        { key: 'genre_electronic_ambient', label: 'Ambient', type: 'percentage' },
        { key: 'genre_electronic_dnb', label: 'Drum & Bass', type: 'percentage' },
        { key: 'genre_electronic_house', label: 'House', type: 'percentage' },
        { key: 'genre_electronic_techno', label: 'Techno', type: 'percentage' },
        { key: 'genre_electronic_trance', label: 'Trance', type: 'percentage' }
      ]
    },
    {
      id: 'mirex',
      label: 'Mood Clusters (MIREX)',
      icon: '📊',
      color: '#6366f1', // indigo
      features: [
        { key: 'moods_mirex_cluster1', label: 'Cluster 1 (Passionate)', type: 'percentage', description: 'Passionate, rousing, confident' },
        { key: 'moods_mirex_cluster2', label: 'Cluster 2 (Rollicking)', type: 'percentage', description: 'Rollicking, cheerful, fun' },
        { key: 'moods_mirex_cluster3', label: 'Cluster 3 (Literate)', type: 'percentage', description: 'Literate, poignant, wistful' },
        { key: 'moods_mirex_cluster4', label: 'Cluster 4 (Humorous)', type: 'percentage', description: 'Humorous, silly, campy' },
        { key: 'moods_mirex_cluster5', label: 'Cluster 5 (Aggressive)', type: 'percentage', description: 'Aggressive, fiery, tense' }
      ]
    }
  ],

  // Display settings
  display: {
    showEmptyCategories: false, // Whether to show categories with no data
    minValueToShow: 0.35, // Minimum value (0-1) to display a feature
    maxFeaturesPerCategory: 4, // Max features to show per category (top N by value)
    barHeight: 8, // Height of progress bars in pixels
    compactMode: false, // Use compact single-line display
    showDescriptions: true // Show feature descriptions on hover
  },

  /**
   * Get all feature keys across all categories
   * @returns {string[]} Array of all feature keys
   */
  getAllFeatureKeys() {
    return this.categories.flatMap(cat => cat.features.map(f => f.key));
  },

  /**
   * Find a feature definition by its key
   * @param {string} key - The feature key to find
   * @returns {Object|null} Feature definition or null
   */
  getFeatureByKey(key) {
    for (const cat of this.categories) {
      const feature = cat.features.find(f => f.key === key);
      if (feature) return { ...feature, category: cat };
    }
    return null;
  },

  /**
   * Add a new category dynamically
   * @param {Object} category - Category definition object
   */
  addCategory(category) {
    if (!category.id || !category.label || !category.features) {
      console.error('Invalid category definition');
      return;
    }
    this.categories.push(category);
  },

  /**
   * Add a feature to an existing category
   * @param {string} categoryId - The category ID to add to
   * @param {Object} feature - Feature definition object
   */
  addFeatureToCategory(categoryId, feature) {
    const category = this.categories.find(c => c.id === categoryId);
    if (category && feature.key && feature.label) {
      category.features.push(feature);
    }
  },

  /**
   * Update display settings
   * @param {Object} settings - Partial settings to update
   */
  updateDisplaySettings(settings) {
    this.display = { ...this.display, ...settings };
  }
};

/**
 * TrackFeatureRenderer - Renders track features using TrackFeaturesDisplay config
 */
class TrackFeatureRenderer {
  constructor(config = TrackFeaturesDisplay) {
    this.config = config;
    // Stats for tracking render success rate
    this.stats = {
      tracksAttempted: 0,
      tracksWithFeatures: 0,
      totalCategoriesRendered: 0
    };
  }

  /**
   * Reset render statistics
   */
  resetStats() {
    this.stats = {
      tracksAttempted: 0,
      tracksWithFeatures: 0,
      totalCategoriesRendered: 0
    };
  }

  /**
   * Get current render statistics
   * @returns {Object} Stats object with counts and percentages
   */
  getStats() {
    const successRate = this.stats.tracksAttempted > 0
      ? ((this.stats.tracksWithFeatures / this.stats.tracksAttempted) * 100).toFixed(1)
      : 0;
    return {
      ...this.stats,
      successRate: `${successRate}%`
    };
  }

  /**
   * Log current stats to console
   */
  logStats() {
    const stats = this.getStats();
    console.log(`[TrackFeatureRenderer Stats] Attempted: ${stats.tracksAttempted}, With Features: ${stats.tracksWithFeatures} (${stats.successRate}), Categories Rendered: ${stats.totalCategoriesRendered}`);
  }

  /**
   * Render a complete track card with cover art and features
   * @param {Object} track - Track data object with features
   * @param {number} index - Track index for numbering
   * @returns {string} HTML string
   */
  renderTrackCard(track, index) {
    const trackName = track.recordingName || track.recording_name || track.name || 'Unknown Track';
    const photoURL = track.photoURL || track.PhotoURL || track.photo_url || null;

    // Debug: log track data to verify features are present
    // console.log(`[TrackFeatureRenderer] Rendering track ${index + 1}: "${trackName}"`, {
    //   hasFeatures: this.config.getAllFeatureKeys().some(key => track[key] !== undefined),
    //   sampleFeatures: {
    //     mood_happy: track.mood_happy,
    //     mood_sad: track.mood_sad,
    //     danceability: track.danceability,
    //     timbre_bright: track.timbre_bright
    //   },
    //   photoURL
    // });

    let html = '<div class="track-feature-card">';

    // Header with cover art
    html += '<div class="track-feature-header">';

    if (this.config.coverArt.enabled) {
      html += this.renderCoverArt(photoURL, trackName);
    }

    html += `
      <div class="track-feature-info">
        <span class="track-feature-number">${index + 1}</span>
        <span class="track-feature-name" title="${this.escapeHtml(trackName)}">${this.escapeHtml(trackName)}</span>
        ${track.connection ? '<span class="track-connection-badge">Connection</span>' : ''}
      </div>
    `;
    html += '</div>';

    // Features body
    html += '<div class="track-feature-body">';
    html += this.renderAllCategories(track);
    html += '</div>';

    html += '</div>';
    return html;
  }

  /**
   * Render cover art thumbnail
   * @param {string|null} photoURL - URL to cover art image
   * @param {string} altText - Alt text for accessibility
   * @returns {string} HTML string
   */
  renderCoverArt(photoURL, altText) {
    const { size, defaultImage } = this.config.coverArt;
    const imgSrc = photoURL || defaultImage;

    return `
      <div class="track-cover-art" style="width: ${size.width}px; height: ${size.height}px;">
        <img
          src="${imgSrc}"
          alt="${this.escapeHtml(altText)}"
          onerror="this.src='${defaultImage}'; this.onerror=null;"
          loading="lazy"
        />
      </div>
    `;
  }

  /**
   * Render all feature categories for a track
   * @param {Object} track - Track data with features
   * @returns {string} HTML string
   */
  renderAllCategories(track) {
    let html = '<div class="track-feature-categories">';
    let categoriesRendered = 0;

    for (const category of this.config.categories) {
      const categoryHtml = this.renderCategory(track, category);
      if (categoryHtml) {
        html += categoryHtml;
        categoriesRendered++;
      }
    }

    // Update stats
    this.stats.tracksAttempted++;
    if (categoriesRendered > 0) {
      this.stats.tracksWithFeatures++;
    }
    this.stats.totalCategoriesRendered += categoriesRendered;

    // Check if no features were rendered
    if (html === '<div class="track-feature-categories">') {
      html += '<div class="no-features-message">No audio features available for this track</div>';
    }

    html += '</div>';
    return html;
  }

  /**
   * Render a single feature category
   * @param {Object} track - Track data
   * @param {Object} category - Category definition
   * @returns {string|null} HTML string or null if no features
   */
  renderCategory(track, category) {
    // Get features that have values
    const featuresWithValues = category.features
      .map(f => ({
        ...f,
        value: track[f.key]
      }))
      .filter(f => f.value !== undefined && f.value !== null && f.value >= this.config.display.minValueToShow)
      .sort((a, b) => b.value - a.value)
      .slice(0, this.config.display.maxFeaturesPerCategory);

    if (featuresWithValues.length === 0 && !this.config.display.showEmptyCategories) {
      return null;
    }

    let html = `
      <div class="feature-category" data-category="${category.id}">
        <div class="feature-category-header" style="--category-color: ${category.color}">
          <span class="feature-category-icon">${category.icon}</span>
          <span class="feature-category-label">${category.label}</span>
        </div>
        <div class="feature-category-items">
    `;

    if (featuresWithValues.length === 0) {
      html += '<div class="feature-category-empty">No data</div>';
    } else {
      for (const feature of featuresWithValues) {
        html += this.renderFeature(feature, category.color);
      }
    }

    html += '</div></div>';
    return html;
  }

  /**
   * Render a single feature with progress bar
   * @param {Object} feature - Feature with value
   * @param {string} color - Category color
   * @returns {string} HTML string
   */
  renderFeature(feature, color) {
    const percentage = Math.min(Math.max(feature.value * 100, 0), 100);
    const displayValue = feature.type === 'percentage'
      ? `${(feature.value * 100).toFixed(1)}%`
      : feature.value.toFixed(3);

    const description = feature.description && this.config.display.showDescriptions
      ? `title="${this.escapeHtml(feature.description)}"`
      : '';

    return `
      <div class="feature-item-row" ${description}>
        <span class="feature-item-label">${feature.label}</span>
        <div class="feature-item-bar-wrapper">
          <div class="feature-item-bar" style="width: ${percentage}%; background: ${color};"></div>
        </div>
        <span class="feature-item-value">${displayValue}</span>
      </div>
    `;
  }

  /**
   * Get a summary of the dominant features for quick display
   * @param {Object} track - Track data
   * @param {number} topN - Number of top features to return
   * @returns {Object[]} Array of top features
   */
  getTopFeatures(track, topN = 5) {
    const allFeatures = [];

    for (const category of this.config.categories) {
      for (const feature of category.features) {
        const value = track[feature.key];
        if (value !== undefined && value !== null && value >= this.config.display.minValueToShow) {
          allFeatures.push({
            ...feature,
            value,
            category: category.label,
            color: category.color
          });
        }
      }
    }

    return allFeatures
      .sort((a, b) => b.value - a.value)
      .slice(0, topN);
  }

  /**
   * Render a compact summary badge of top features
   * @param {Object} track - Track data
   * @returns {string} HTML string
   */
  renderCompactSummary(track) {
    const topFeatures = this.getTopFeatures(track, 3);

    if (topFeatures.length === 0) {
      return '<span class="feature-summary-empty">No features</span>';
    }

    return `
      <div class="feature-summary-badges">
        ${topFeatures.map(f => `
          <span class="feature-summary-badge" style="--badge-color: ${f.color}" title="${f.label}: ${(f.value * 100).toFixed(1)}%">
            ${f.label}
          </span>
        `).join('')}
      </div>
    `;
  }

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// Create a global instance of the renderer
const trackFeatureRenderer = new TrackFeatureRenderer(TrackFeaturesDisplay);

class MLDataTable {
  constructor(containerId, options = {}) {
    console.log('[DEBUG ctor] containerId:', containerId);
    console.log('[DEBUG ctor] DOM lookup:', document.getElementById(containerId));
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.dataTable = null;
    this.options = {
      showFeatures: true,
      ...options
    };
  }

  /**
   * Initialize DataTables with the given data
   * @param {Array} data - Array of collaboration objects
   */
  init(data) {
    this.destroy();
    this.container.innerHTML = '';
    console.log("this is the data for the init:",data)
    console.log("[DEBUG]: Length Data:",data.length)
    if (!data || data.length === 0) {
      this.renderEmpty();
      return;
    }

    // Create table element
    const table = document.createElement('table');
    table.id = `${this.containerId}-datatable`;
    table.className = 'display compact ml-datatable';
    table.style.width = '100%';
    this.container.appendChild(table);
    console.log("Table:",table)
    console.log("Table Data:",data)
    // Initialize DataTables
    this.dataTable = new DataTable(table, {
      
      data: data,
      columns: [
        {
          className: 'dt-control',
          orderable: false,
          data: null,
          defaultContent: '',
          width: '30px'
        },
        { data: 'artistName', title: 'Artist Name' },
        { data: 'featuredWith', title: 'Featured With' },
        { data: 'numberOfTracks', title: 'Tracks' },
        {
          data: 'prob',
          title: 'Probability',
          render: (data) => {
            if (data === null || data === undefined || data === 'Unknown') {
              return '<span class="prob-badge prob-unknown">N/A</span>';
            }
            const prob = parseFloat(data);
            const colorClass = prob >= 0.7 ? 'prob-high' : prob >= 0.4 ? 'prob-medium' : 'prob-low';
            return `<span class="prob-badge ${colorClass}">${prob.toFixed(2)}</span>`;
          }
        },
        {
          data: null,
          title: '',
          orderable: false,
          searchable: false,
          width: '50px',
          render: (data, type, row) => {
            if (!row.srcArtistId || !row.dstArtistId) return '';

            const saved = SavedConnectionsStore.has(row.srcArtistId, row.dstArtistId);
            const cls = saved ? 'save-btn-themed saved' : 'save-btn-themed';
            const icon = saved ? '&#x2715;' : '&#x2b;';
            const title = saved ? 'Remove from playlist selection' : 'Add to playlist selection';

            return `<button class="${cls}" title="${title}"><span class="save-btn-icon">${icon}</span></button>`;
          }
        }
      ],
      order: [[3, 'desc']],
      pageLength: 25,
      lengthMenu: [10, 25, 50, 100],
      responsive: true,
      language: {
        emptyTable: 'No collaboration data available',
        zeroRecords: 'No matching records found'
      },
      dom: '<"top"lf>rt<"bottom"ip><"clear">',
      initComplete: function() {
        // Apply dark theme styling after init
        this.api().columns.adjust();
      }
    });
  console.log('[DEBUG] DataTable instance:', this.dataTable);


  // Add click handler for expanding rows (DataTables 2.x compatible)
  table.addEventListener('click', (e) => {
    const cell = e.target.closest('td.dt-control');
    if (!cell) return;

    const tr = cell.closest('tr');
    const row = this.dataTable.row(tr);

    if (row.child.isShown()) {
      row.child.hide();
      tr.classList.remove('shown');
    } else {
      row.child(this.formatChildRow(row.data())).show();
      tr.classList.add('shown');
    }
  });

  // Add click handler for save/remove buttons
  table.addEventListener('click', (e) => {
    const btn = e.target.closest('.save-btn-themed');
    if (!btn) return;

    const tr = btn.closest('tr');
    const row = this.dataTable.row(tr);
    const d = row.data();

    if (!d.srcArtistId || !d.dstArtistId) return;

    if (SavedConnectionsStore.has(d.srcArtistId, d.dstArtistId)) {
      SavedConnectionsStore.remove(d.srcArtistId, d.dstArtistId);
    } else {
      SavedConnectionsStore.add(d.srcArtistId, d.dstArtistId, d.tracks);
    }

    // Re-render just this row so the button toggles
    row.invalidate().draw(false);

    // Refresh saved connections panel
    if (window._savedPanel) window._savedPanel.refresh();
  });
  }

  /**
   * Format the child row content with track details and features
   * @param {Object} rowData - The row data object
   * @returns {string} HTML string for the child row
   */
  formatChildRow(rowData) {
    if (!rowData.tracks || rowData.tracks.length === 0) {
      return '<div class="track-details-empty">No track details available</div>';
    }

    // Reset stats before rendering this batch
    trackFeatureRenderer.resetStats();

    let html = '<div class="track-details-container">';
    html += '<h4 class="track-details-header">Tracks & Features</h4>';
    html += '<div class="tracks-grid">';

    rowData.tracks.forEach((track, index) => {
      // Use the new TrackFeatureRenderer for rich display
      html += trackFeatureRenderer.renderTrackCard(track, index);
    });

    html += '</div></div>';

    // Log stats after rendering all tracks
    trackFeatureRenderer.logStats();

    return html;
  }

  /**
   * Render track features as a grid of values
   * @param {Object} track - Track object with potential features
   * @returns {string} HTML string for features
   */
  renderTrackFeatures(track) {
    // Define the feature groups we're interested in
    const featureGroups = {
      'Audio': ['danceability', 'energy', 'tempo', 'valence', 'acousticness'],
      'Mood': ['mood_acoustic', 'mood_aggressive', 'mood_electronic', 'mood_happy', 'mood_party', 'mood_relaxed', 'mood_sad'],
      'Voice': ['voice_instrumental_instrumental', 'voice_instrumental_voice', 'gender_female', 'gender_male'],
      'Timbre': ['timbre_bright', 'timbre_dark'],
      'Tonal': ['tonal_atonal_atonal', 'tonal_atonal_tonal']
    };

    // Check if track has any features
    const hasFeatures = Object.values(featureGroups).flat().some(key =>
      track[key] !== undefined && track[key] !== null
    );

    if (!hasFeatures) {
      // Show basic track info if no features
      let basicHtml = '<div class="track-basic-info">';

      if (track.RecordingID || track.recordingId) {
        basicHtml += `<div class="feature-item"><span class="feature-label">Recording ID:</span> <span class="feature-value">${track.RecordingID || track.recordingId}</span></div>`;
      }
      if (track.PhotoURL || track.photoURL) {
        basicHtml += `<div class="feature-item"><span class="feature-label">Photo:</span> <a href="${track.PhotoURL || track.photoURL}" target="_blank" class="feature-link">View</a></div>`;
      }
      if (track.ID || track.id) {
        basicHtml += `<div class="feature-item"><span class="feature-label">Track ID:</span> <span class="feature-value">${track.ID || track.id}</span></div>`;
      }

      if (basicHtml === '<div class="track-basic-info">') {
        basicHtml += '<span class="no-features">No additional features available</span>';
      }

      basicHtml += '</div>';
      return basicHtml;
    }

    let html = '<div class="features-container">';

    for (const [groupName, features] of Object.entries(featureGroups)) {
      const groupFeatures = features.filter(f => track[f] !== undefined && track[f] !== null);

      if (groupFeatures.length > 0) {
        html += `<div class="feature-group">`;
        html += `<div class="feature-group-title">${groupName}</div>`;
        html += '<div class="feature-group-items">';

        groupFeatures.forEach(feature => {
          const value = track[feature];
          const displayName = this.formatFeatureName(feature);
          const displayValue = typeof value === 'number' ? value.toFixed(3) : value;
          const barWidth = typeof value === 'number' ? Math.min(value * 100, 100) : 0;

          html += `
            <div class="feature-item">
              <span class="feature-label">${displayName}</span>
              <div class="feature-bar-container">
                <div class="feature-bar" style="width: ${barWidth}%"></div>
              </div>
              <span class="feature-value">${displayValue}</span>
            </div>
          `;
        });

        html += '</div></div>';
      }
    }

    // Also show genre features if present
    const genreFeatures = Object.keys(track).filter(k => k.startsWith('genre_'));
    if (genreFeatures.length > 0) {
      html += `<div class="feature-group">`;
      html += `<div class="feature-group-title">Genre</div>`;
      html += '<div class="feature-group-items genre-items">';

      // Sort by value and show top 5
      const sortedGenres = genreFeatures
        .map(g => ({ name: g, value: track[g] }))
        .filter(g => g.value > 0.1)
        .sort((a, b) => b.value - a.value)
        .slice(0, 5);

      sortedGenres.forEach(genre => {
        const displayName = this.formatFeatureName(genre.name);
        const barWidth = Math.min(genre.value * 100, 100);

        html += `
          <div class="feature-item">
            <span class="feature-label">${displayName}</span>
            <div class="feature-bar-container">
              <div class="feature-bar genre-bar" style="width: ${barWidth}%"></div>
            </div>
            <span class="feature-value">${genre.value.toFixed(3)}</span>
          </div>
        `;
      });

      html += '</div></div>';
    }

    html += '</div>';
    return html;
  }

  /**
   * Format feature name for display
   * @param {string} name - Raw feature name
   * @returns {string} Formatted name
   */
  formatFeatureName(name) {
    return name
      .replace(/^(genre_dortmund_|genre_electronic_|genre_rosamerica_|genre_tzanetakis_|mood_|voice_instrumental_|ismir04_rhythm_|moods_mirex_|tonal_atonal_|timbre_|gender_)/, '')
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .trim()
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  }

  /**
   * Escape HTML to prevent XSS
   * @param {string} text - Text to escape
   * @returns {string} Escaped text
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Render empty state
   */
  renderEmpty() {
    this.container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📊</div>
        <p>No data available {123}</p>
        <p style="font-size: 0.8rem; margin-top: 0.5rem;">
          Perform a search to see results here
        </p>
      </div>
    `;
  }

  /**
   * Render loading state
   */
  renderLoading() {
    this.destroy();
    this.container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>Loading data...</p>
      </div>
    `;
  }

  /**
   * Destroy the DataTable instance
   */
  destroy() {
    if (this.dataTable) {
      this.dataTable.destroy();
      this.dataTable = null;
    }
  }

  /**
   * Refresh the table with new data
   * @param {Array} data - New data array
   */
  refresh(data) {
    this.init(data);
  }

  /**
   * Get the DataTable instance
   * @returns {DataTable} The DataTables instance
   */
  getInstance() {
    return this.dataTable;
  }
}

/**
 * Add required CSS styles for DataTables dark theme and features
 */
function injectMLDataTableStyles() {
  if (document.getElementById('ml-datatable-styles')) return;

  const styles = document.createElement('style');
  styles.id = 'ml-datatable-styles';
  styles.textContent = `
    /* DataTables Dark Theme Override */
    .ml-datatable {
      --dt-row-hover: rgba(31, 41, 55, 0.6);
      --dt-row-stripe: rgba(15, 23, 42, 0.4);
      --dt-html-background: transparent;
    }

    .ml-datatable thead th {
      background: rgba(15, 23, 42, 0.8) !important;
      color: var(--text-muted, #94a3b8) !important;
      border-bottom: 1px solid rgba(148, 163, 184, 0.2) !important;
      padding: 12px 10px !important;
      font-weight: 600;
    }

    .ml-datatable tbody td {
      background: transparent !important;
      color: var(--text-main, #e2e8f0) !important;
      border-bottom: 1px solid rgba(148, 163, 184, 0.1) !important;
      padding: 10px !important;
    }

    .ml-datatable tbody tr:hover td {
      background: rgba(31, 41, 55, 0.5) !important;
    }

    .ml-datatable tbody tr.shown td {
      background: rgba(59, 130, 246, 0.1) !important;
    }

    /* Expand/Collapse Control */
    td.dt-control {
      cursor: pointer;
      position: relative;
    }

    td.dt-control::before {
      content: '+';
      display: inline-block;
      width: 20px;
      height: 20px;
      line-height: 20px;
      text-align: center;
      background: rgba(59, 130, 246, 0.2);
      border: 1px solid rgba(59, 130, 246, 0.4);
      border-radius: 4px;
      color: #60a5fa;
      font-weight: bold;
      font-size: 14px;
      transition: all 0.2s ease;
    }

    td.dt-control:hover::before {
      background: rgba(59, 130, 246, 0.3);
      border-color: rgba(59, 130, 246, 0.6);
    }

    tr.shown td.dt-control::before {
      content: '−';
      background: rgba(59, 130, 246, 0.4);
    }

    /* Probability Badge */
    .prob-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 0.8rem;
      font-weight: 600;
    }

    .prob-high {
      background: rgba(34, 197, 94, 0.2);
      color: #22c55e;
    }

    .prob-medium {
      background: rgba(251, 191, 36, 0.2);
      color: #fbbf24;
    }

    .prob-low {
      background: rgba(239, 68, 68, 0.2);
      color: #ef4444;
    }

    .prob-unknown {
      background: rgba(148, 163, 184, 0.2);
      color: #94a3b8;
    }

    /* Themed Save / Remove Button */
    .save-btn-themed {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: rgba(15, 23, 42, 0.8);
      color: var(--text-muted, #94a3b8);
      cursor: pointer;
      font-size: 1rem;
      transition: all 0.2s ease;
      backdrop-filter: blur(6px);
    }
    .save-btn-themed:hover {
      border-color: rgba(34, 197, 94, 0.6);
      background: rgba(34, 197, 94, 0.15);
      color: #22c55e;
      transform: scale(1.1);
      box-shadow: 0 0 12px rgba(34, 197, 94, 0.3);
    }
    .save-btn-themed.saved {
      border-color: rgba(34, 197, 94, 0.5);
      background: linear-gradient(135deg, rgba(34, 197, 94, 0.2), rgba(14, 165, 233, 0.15));
      color: #22c55e;
      box-shadow: 0 0 8px rgba(34, 197, 94, 0.2);
    }
    .save-btn-themed.saved:hover {
      border-color: rgba(239, 68, 68, 0.5);
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
      box-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
    }
    .save-btn-icon {
      line-height: 1;
      font-weight: 700;
    }

    /* Saved Connections Panel */
    .saved-header-actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .badge-accent {
      font-size: 0.75rem;
      background: rgba(34, 197, 94, 0.15);
      color: #22c55e;
      padding: 2px 10px;
      border-radius: 999px;
      border: 1px solid rgba(34, 197, 94, 0.3);
    }
    .saved-connections-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 300px;
      overflow-y: auto;
      margin-bottom: 1rem;
    }
    .saved-connection-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid rgba(148, 163, 184, 0.12);
      border-radius: 10px;
      transition: border-color 0.15s ease;
    }
    .saved-connection-item:hover {
      border-color: rgba(34, 197, 94, 0.3);
    }
    .saved-connection-info {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1;
      min-width: 0;
    }
    .saved-src, .saved-dst {
      color: var(--text-main, #e2e8f0);
      font-weight: 500;
      font-size: 0.9rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .saved-arrow {
      color: var(--accent, #10b981);
      font-size: 1rem;
      flex-shrink: 0;
    }
    .saved-track-count {
      color: var(--text-muted, #94a3b8);
      font-size: 0.75rem;
      background: rgba(148, 163, 184, 0.1);
      padding: 2px 8px;
      border-radius: 999px;
      flex-shrink: 0;
    }
    .saved-actions-bar {
      display: flex;
      gap: 0.75rem;
      align-items: center;
      padding-top: 1rem;
      border-top: 1px solid rgba(148, 163, 184, 0.12);
    }
    .saved-actions-bar input {
      flex: 1;
    }

    /* Track Details Container */
    .track-details-container {
      padding: 16px;
      background: rgba(15, 23, 42, 0.6);
      border-radius: 8px;
      margin: 8px 0;
    }

    .track-details-header {
      color: var(--text-main, #e2e8f0);
      margin: 0 0 12px 0;
      font-size: 1rem;
      font-weight: 600;
      border-bottom: 1px solid rgba(148, 163, 184, 0.2);
      padding-bottom: 8px;
    }

    .track-details-empty {
      padding: 20px;
      text-align: center;
      color: var(--text-muted, #94a3b8);
      font-style: italic;
    }

    /* Tracks Grid */
    .tracks-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 12px;
    }

    /* Track Card */
    .track-card {
      background: rgba(31, 41, 55, 0.5);
      border: 1px solid rgba(148, 163, 184, 0.15);
      border-radius: 6px;
      overflow: hidden;
    }

    .track-card-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: rgba(15, 23, 42, 0.5);
      border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    }

    .track-number {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      background: rgba(59, 130, 246, 0.2);
      color: #60a5fa;
      border-radius: 50%;
      font-size: 0.75rem;
      font-weight: 600;
    }

    .track-name {
      flex: 1;
      color: var(--text-main, #e2e8f0);
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .connection-badge {
      background: rgba(168, 85, 247, 0.2);
      color: #a855f7;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
    }

    .track-card-body {
      padding: 12px;
    }

    /* Track Basic Info */
    .track-basic-info {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .track-basic-info .feature-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .track-basic-info .feature-label {
      color: var(--text-muted, #94a3b8);
      font-size: 0.8rem;
    }

    .track-basic-info .feature-value {
      color: var(--text-main, #e2e8f0);
      font-size: 0.8rem;
      font-family: 'Courier New', monospace;
    }

    .track-basic-info .feature-link {
      color: #60a5fa;
      text-decoration: none;
      font-size: 0.8rem;
    }

    .track-basic-info .feature-link:hover {
      text-decoration: underline;
    }

    .no-features {
      color: var(--text-muted, #94a3b8);
      font-style: italic;
      font-size: 0.85rem;
    }

    /* Features Container */
    .features-container {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .feature-group {
      background: rgba(15, 23, 42, 0.4);
      border-radius: 4px;
      padding: 8px;
    }

    .feature-group-title {
      color: #60a5fa;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    }

    .feature-group-items {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .feature-item {
      display: grid;
      grid-template-columns: 100px 1fr 50px;
      align-items: center;
      gap: 8px;
    }

    .feature-label {
      color: var(--text-muted, #94a3b8);
      font-size: 0.75rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .feature-bar-container {
      height: 6px;
      background: rgba(148, 163, 184, 0.1);
      border-radius: 3px;
      overflow: hidden;
    }

    .feature-bar {
      height: 100%;
      background: linear-gradient(90deg, #3b82f6, #60a5fa);
      border-radius: 3px;
      transition: width 0.3s ease;
    }

    .feature-bar.genre-bar {
      background: linear-gradient(90deg, #8b5cf6, #a78bfa);
    }

    .feature-value {
      color: var(--text-main, #e2e8f0);
      font-size: 0.75rem;
      font-family: 'Courier New', monospace;
      text-align: right;
    }

    /* Genre Items - Horizontal layout for small items */
    .genre-items .feature-item {
      grid-template-columns: 80px 1fr 45px;
    }

    /* DataTables Controls Styling */
    .dataTables_wrapper {
      color: var(--text-main, #e2e8f0);
    }

    .dataTables_wrapper .dataTables_length,
    .dataTables_wrapper .dataTables_filter,
    .dataTables_wrapper .dataTables_info,
    .dataTables_wrapper .dataTables_paginate {
      color: var(--text-muted, #94a3b8) !important;
      padding: 8px 0;
    }

    .dataTables_wrapper .dataTables_length select,
    .dataTables_wrapper .dataTables_filter input {
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(148, 163, 184, 0.3);
      color: var(--text-main, #e2e8f0);
      border-radius: 4px;
      padding: 4px 8px;
    }

    .dataTables_wrapper .dataTables_length select:focus,
    .dataTables_wrapper .dataTables_filter input:focus {
      outline: none;
      border-color: rgba(59, 130, 246, 0.5);
    }

    .dataTables_wrapper .dataTables_paginate .paginate_button {
      background: rgba(15, 23, 42, 0.6) !important;
      border: 1px solid rgba(148, 163, 184, 0.2) !important;
      color: var(--text-muted, #94a3b8) !important;
      border-radius: 4px !important;
      margin: 0 2px !important;
    }

    .dataTables_wrapper .dataTables_paginate .paginate_button:hover {
      background: rgba(31, 41, 55, 0.8) !important;
      color: var(--text-main, #e2e8f0) !important;
    }

    .dataTables_wrapper .dataTables_paginate .paginate_button.current {
      background: rgba(59, 130, 246, 0.3) !important;
      border-color: rgba(59, 130, 246, 0.5) !important;
      color: #60a5fa !important;
    }

    .dataTables_wrapper .dataTables_paginate .paginate_button.disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    /* Responsive */
    @media (max-width: 768px) {
      .tracks-grid {
        grid-template-columns: 1fr;
      }

      .feature-item {
        grid-template-columns: 80px 1fr 40px;
      }
    }

    /* ========================================
       Track Feature Display Styles (New)
       ======================================== */

    /* Track Feature Card */
    .track-feature-card {
      background: rgba(31, 41, 55, 0.5);
      border: 1px solid rgba(148, 163, 184, 0.15);
      border-radius: 8px;
      overflow: hidden;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    .track-feature-card:hover {
      border-color: rgba(59, 130, 246, 0.3);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }

    /* Header with Cover Art */
    .track-feature-header {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: rgba(15, 23, 42, 0.6);
      border-bottom: 1px solid rgba(148, 163, 184, 0.1);
    }

    /* Cover Art */
    .track-cover-art {
      flex-shrink: 0;
      border-radius: 6px;
      overflow: hidden;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(148, 163, 184, 0.2);
    }

    .track-cover-art img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    /* Track Info */
    .track-feature-info {
      flex: 1;
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .track-feature-number {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      background: rgba(59, 130, 246, 0.2);
      color: #60a5fa;
      border-radius: 50%;
      font-size: 0.8rem;
      font-weight: 600;
      flex-shrink: 0;
    }

    .track-feature-name {
      flex: 1;
      color: var(--text-main, #e2e8f0);
      font-weight: 500;
      font-size: 0.95rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .track-connection-badge {
      background: rgba(168, 85, 247, 0.2);
      color: #a855f7;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      flex-shrink: 0;
    }

    /* Feature Body */
    .track-feature-body {
      padding: 12px;
    }

    /* Feature Categories Container */
    .track-feature-categories {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    /* Single Feature Category */
    .feature-category {
      background: rgba(15, 23, 42, 0.4);
      border-radius: 6px;
      overflow: hidden;
    }

    .feature-category-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: rgba(var(--category-color-rgb, 59, 130, 246), 0.15);
      border-left: 3px solid var(--category-color, #3b82f6);
    }

    .feature-category-icon {
      font-size: 1rem;
    }

    .feature-category-label {
      color: var(--text-main, #e2e8f0);
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .feature-category-items {
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .feature-category-empty {
      color: var(--text-muted, #64748b);
      font-size: 0.8rem;
      font-style: italic;
      text-align: center;
      padding: 8px;
    }

    /* Feature Item Row */
    .feature-item-row {
      display: grid;
      grid-template-columns: 120px 1fr 55px;
      align-items: center;
      gap: 10px;
    }

    .feature-item-label {
      color: var(--text-muted, #94a3b8);
      font-size: 0.75rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .feature-item-bar-wrapper {
      height: 8px;
      background: rgba(148, 163, 184, 0.1);
      border-radius: 4px;
      overflow: hidden;
    }

    .feature-item-bar {
      height: 100%;
      border-radius: 4px;
      transition: width 0.3s ease;
      opacity: 0.85;
    }

    .feature-item-value {
      color: var(--text-main, #e2e8f0);
      font-size: 0.75rem;
      font-family: 'Courier New', monospace;
      text-align: right;
    }

    /* No Features Message */
    .no-features-message {
      text-align: center;
      color: var(--text-muted, #64748b);
      font-size: 0.85rem;
      font-style: italic;
      padding: 20px;
    }

    /* Feature Summary Badges (Compact Mode) */
    .feature-summary-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .feature-summary-badge {
      display: inline-block;
      padding: 3px 8px;
      background: rgba(var(--badge-color-rgb, 59, 130, 246), 0.2);
      color: var(--badge-color, #60a5fa);
      border-radius: 10px;
      font-size: 0.7rem;
      font-weight: 500;
      cursor: default;
    }

    .feature-summary-empty {
      color: var(--text-muted, #64748b);
      font-size: 0.8rem;
      font-style: italic;
    }

    /* Responsive adjustments for feature display */
    @media (max-width: 600px) {
      .track-feature-header {
        flex-direction: column;
        text-align: center;
      }

      .track-feature-info {
        flex-direction: column;
      }

      .feature-item-row {
        grid-template-columns: 90px 1fr 45px;
        gap: 6px;
      }

      .track-cover-art {
        margin: 0 auto;
      }
    }
  `;

  document.head.appendChild(styles);
}

/**
 * Initialize the ML DataTable system
 * Call this after DOM is ready and DataTables library is loaded
 */
function initMLDataTables() {
  // Inject styles
  injectMLDataTableStyles();

  // Return the MLDataTable class for use
  return MLDataTable;
}

// Auto-inject styles when script loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', injectMLDataTableStyles);
} else {
  injectMLDataTableStyles();
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MLDataTable, initMLDataTables, injectMLDataTableStyles };
}


