/* =========================================
   Interlude API Demo — Frontend JS
   Calls /api/v1/* endpoints directly
========================================= */

const API_BASE = window.location.origin;

// ---- Demo API Keys (auto-assigned per session, invisible to user) ----
const DEMO_KEYS = [
  'interlude-demo-001', 'interlude-demo-002', 'interlude-demo-003',
  'interlude-demo-004', 'interlude-demo-005', 'interlude-demo-006',
  'interlude-demo-007', 'interlude-demo-008', 'interlude-demo-009',
  'interlude-demo-010',
];
let apiKey = '';

function initApiKey() {
  const saved = localStorage.getItem('interlude_api_key');
  if (saved) {
    apiKey = saved;
  } else {
    apiKey = DEMO_KEYS[Math.floor(Math.random() * DEMO_KEYS.length)];
    localStorage.setItem('interlude_api_key', apiKey);
  }
}

// ---- DOM Helpers ----
const $ = (sel) => document.querySelector(sel);
const show = (el) => { if (typeof el === 'string') el = $(el); if (el) el.style.display = ''; };
const hide = (el) => { if (typeof el === 'string') el = $(el); if (el) el.style.display = 'none'; };

function probClass(p) {
  if (p >= 0.65) return 'high';
  if (p >= 0.4) return 'medium';
  return 'low';
}

function loading(container, msg = 'Loading...') {
  if (typeof container === 'string') container = $(container);
  container.innerHTML = `<div class="loading-inline"><div class="spinner-sm"></div>${msg}</div>`;
}

// ---- API Calls ----
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (apiKey) headers['X-API-Key'] = apiKey;
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || err.message || JSON.stringify(err);
    } catch { detail += ': ' + await res.text(); }
    throw new Error(detail);
  }
  return res.json();
}

// ---- Feature display config (categories for synthetic track bars) ----
const FEATURE_CATEGORIES = [
  { id: 'mood', label: 'Mood', icon: '🎭', color: '#f59e0b', keys: [
    'mood_acoustic','mood_aggressive','mood_electronic','mood_happy','mood_party','mood_relaxed','mood_sad'
  ]},
  { id: 'voice', label: 'Voice', icon: '🎤', color: '#ec4899', keys: [
    'voice_instrumental_voice','voice_instrumental_instrumental'
  ]},
  { id: 'timbre', label: 'Timbre', icon: '🔊', color: '#8b5cf6', keys: [
    'timbre_bright','timbre_dark','tonal_atonal_tonal','tonal_atonal_atonal'
  ]},
  { id: 'rhythm', label: 'Rhythm', icon: '💃', color: '#10b981', keys: [
    'danceability','ismir04_rhythm_chachacha','ismir04_rhythm_jive','ismir04_rhythm_samba','ismir04_rhythm_tango','ismir04_rhythm_waltz'
  ]},
  { id: 'genre', label: 'Genre', icon: '🎵', color: '#3b82f6', keys: [
    'genre_dortmund_alternative','genre_dortmund_blues','genre_dortmund_electronic','genre_dortmund_folkcountry',
    'genre_dortmund_funksoulrnb','genre_dortmund_jazz','genre_dortmund_pop','genre_dortmund_raphiphop','genre_dortmund_rock'
  ]},
];

function featureLabel(key) {
  return key.replace(/^(genre_dortmund_|genre_electronic_|genre_rosamerica_|genre_tzanetakis_|mood_|voice_instrumental_|ismir04_rhythm_|timbre_|tonal_atonal_|gender_)/, '');
}

// ---- Synthetic Tracks Display ----
function renderTrackCards(tracks) {
  return tracks.map((track, idx) => {
    const id = typeof track === 'object' ? track.track_id : track;
    const hasFeatures = typeof track === 'object' && Object.keys(track).length > 2;

    let featuresHtml = '';
    if (hasFeatures) {
      featuresHtml = FEATURE_CATEGORIES.map(cat => {
        const bars = cat.keys.filter(k => track[k] != null).map(k => {
          const val = track[k];
          const pct = Math.min(100, Math.max(0, val * 100));
          return `<div class="feat-row">
            <span class="feat-label">${featureLabel(k)}</span>
            <div class="feat-bar-bg"><div class="feat-bar-fill" style="width:${pct.toFixed(0)}%;background:${cat.color};"></div></div>
            <span class="feat-val">${pct.toFixed(2)}%</span>
          </div>`;
        }).join('');
        if (!bars) return '';
        return `<div class="feat-category">
          <div class="feat-cat-header">${cat.icon} ${cat.label}</div>
          ${bars}
        </div>`;
      }).join('');
    } else {
      featuresHtml = '<span style="font-size:0.75rem;color:var(--text-muted);">No feature data</span>';
    }

    return `<div class="track-card">
      <div class="track-card-header"><span class="track-id">Track #${id}</span></div>
      <div class="track-features">${featuresHtml}</div>
    </div>`;
  }).join('');
}

function showSyntheticTracks(tracks) {
  show('#tracksCard');
  if (tracks && tracks.length > 0) {
    $('#tracksGrid').innerHTML = renderTrackCards(tracks);
  } else {
    $('#tracksGrid').innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:1.5rem;">No synthetic tracks generated for this pair yet.</div>';
  }
}

// ---- Predict Connection ----
async function predictConnection() {
  const src = $('#srcInput').value.trim();
  const dst = $('#dstInput').value.trim();
  if (!src || !dst) return alert('Enter both artists');

  show('#connectionCard');
  hide('#tracksCard');

  $('#srcBadge').textContent = src;
  $('#dstBadge').textContent = dst;
  $('#probValue').textContent = '...';
  $('#probRing').className = 'prob-ring';
  $('#connectionMeta').innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 30 seconds for uncached artists...</div>';

  try {
    const res = await api('/api/v1/predict/connection', {
      method: 'POST',
      body: JSON.stringify({ src_artist: src, dst_artist: dst, limit: 5 }),
    });

    const d = res.data;
    const m = res.meta;
    const prob = d.probability;

    if (d.src_name) $('#srcBadge').textContent = d.src_name;
    if (d.dst_name) $('#dstBadge').textContent = d.dst_name;

    const pct = (prob * 100).toFixed(2);
    $('#probValue').textContent = `${pct}%`;
    $('#probRing').className = `prob-ring ${probClass(prob)}`;

    $('#connectionMeta').innerHTML = `
      <span>Model: <span class="meta-tag">${m.model_version}</span></span>
      <span>Latency: <span class="meta-tag">${m.latency_ms.toFixed(0)}ms</span></span>
      <span>Cached: <span class="meta-tag">${m.cached ? 'yes' : 'no'}</span></span>
      <span>Tracks: <span class="meta-tag">${(d.tracks || []).length}</span></span>
    `;

    // Show synthetic tracks
    showSyntheticTracks(d.tracks || []);

  } catch (e) {
    $('#connectionMeta').innerHTML = `<span style="color:var(--error);">${e.message}</span>`;
  }
}

// ---- Neighbor Discovery ----
// Store neighbor data so expand rows can access tracks
let neighborsData = [];

async function discoverNeighbors() {
  const artist = $('#neighborInput').value.trim();
  if (!artist) return alert('Enter an artist');

  show('#neighborsCard');
  $('#neighborsTitle').textContent = 'Predicted Collaborators';
  $('#neighborsBody').innerHTML = '<tr><td colspan="5"><div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 60 seconds for uncached artists...</div></td></tr>';

  try {
    const res = await api('/api/v1/predict/neighbors', {
      method: 'POST',
      body: JSON.stringify({ artist, limit: 50 }),
    });

    const d = res.data;
    const title = d.artist_name ? `Top Predicted Collaborators for ${d.artist_name}` : 'Top Predicted Collaborators';
    $('#neighborsTitle').textContent = title;

    neighborsData = d.neighbors || [];
    if (neighborsData.length === 0) {
      $('#neighborsBody').innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No neighbors found</td></tr>';
      return;
    }

    // Sort descending by probability, show top 10
    neighborsData.sort((a, b) => b.probability - a.probability);
    neighborsData = neighborsData.slice(0, 10);

    renderNeighborRows();
  } catch (e) {
    $('#neighborsBody').innerHTML = `<tr><td colspan="5" style="color:var(--error);">${e.message}</td></tr>`;
  }
}

function renderNeighborRows() {
  $('#neighborsBody').innerHTML = neighborsData.map((n, i) => `
    <tr class="neighbor-row" data-idx="${i}" onclick="toggleNeighborTracks(${i})">
      <td>${i + 1}</td>
      <td>${escHtml(n.name || n.artist_id)}</td>
      <td><span class="prob-badge ${probClass(n.probability)}">${(n.probability * 100).toFixed(2)}%</span></td>
      <td>${(n.tracks || []).length} tracks</td>
      <td class="expand-cell"><span class="expand-arrow" id="arrow-${i}">&#9654;</span></td>
    </tr>
    <tr class="neighbor-expand-row" id="expand-${i}" style="display:none;">
      <td colspan="5" class="expand-content" id="expand-content-${i}"></td>
    </tr>
  `).join('');
}

function toggleNeighborTracks(idx) {
  const expandRow = document.getElementById(`expand-${idx}`);
  const arrow = document.getElementById(`arrow-${idx}`);
  const content = document.getElementById(`expand-content-${idx}`);

  if (expandRow.style.display !== 'none') {
    expandRow.style.display = 'none';
    arrow.innerHTML = '&#9654;';
    return;
  }

  expandRow.style.display = '';
  arrow.innerHTML = '&#9660;';

  const n = neighborsData[idx];
  const tracks = n.tracks || [];

  if (tracks.length > 0) {
    content.innerHTML = `<div class="tracks-grid">${renderTrackCards(tracks)}</div>`;
  } else {
    content.innerHTML = '<div style="color:var(--text-muted);padding:1rem;text-align:center;">No synthetic tracks available for this connection.</div>';
  }
}

// ---- Utility ----
function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

// ---- Artist Autocomplete ----
let artistNameList = [];

async function loadArtistNames() {
  try {
    const res = await fetch('/static/top_artists.txt');
    if (!res.ok) return [];
    const text = await res.text();
    artistNameList = text.split('\n').map(x => x.trim()).filter(Boolean);
    return artistNameList;
  } catch { return []; }
}

function createAutocomplete(inputEl) {
  const container = inputEl.closest('.autocomplete-container');
  if (!container) return;
  const listEl = container.querySelector('.autocomplete-list');
  if (!listEl) return;
  let currentIndex = -1;

  function closeList() {
    listEl.style.display = 'none';
    listEl.innerHTML = '';
    currentIndex = -1;
  }

  async function updateSuggestions() {
    const q = inputEl.value.trim();
    if (!q) return closeList();
    if (!artistNameList.length) await loadArtistNames();
    const lc = q.toLowerCase();
    const starts = artistNameList.filter(n => n.toLowerCase().startsWith(lc));
    const contains = artistNameList.filter(n => !n.toLowerCase().startsWith(lc) && n.toLowerCase().includes(lc));
    const suggestions = [...starts, ...contains].slice(0, 15);
    listEl.innerHTML = '';
    if (!suggestions.length) return closeList();
    suggestions.forEach(name => {
      const item = document.createElement('div');
      item.className = 'autocomplete-item';
      item.setAttribute('role', 'option');
      item.innerHTML = `
        <div class="autocomplete-left">
          <div class="autocomplete-name">${escHtml(name)}</div>
        </div>
        <div class="autocomplete-tag">Artist</div>`;
      item.addEventListener('mousedown', e => {
        e.preventDefault();
        inputEl.value = name;
        closeList();
      });
      listEl.appendChild(item);
    });
    listEl.style.display = 'block';
  }

  inputEl.addEventListener('input', updateSuggestions);
  inputEl.addEventListener('focus', updateSuggestions);
  inputEl.addEventListener('blur', () => setTimeout(closeList, 120));
  inputEl.addEventListener('keydown', e => {
    const items = Array.from(listEl.querySelectorAll('.autocomplete-item'));
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      currentIndex = (currentIndex + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      currentIndex = (currentIndex - 1 + items.length) % items.length;
    } else if (e.key === 'Enter') {
      if (currentIndex >= 0) {
        e.preventDefault();
        inputEl.value = items[currentIndex].querySelector('.autocomplete-name').textContent;
        closeList();
      }
      return;
    } else { return; }
    items.forEach((item, idx) => item.setAttribute('aria-selected', idx === currentIndex));
  });
}

// ---- Event Listeners ----
document.addEventListener('DOMContentLoaded', () => {
  initApiKey();
  loadArtistNames();

  // Autocomplete on artist inputs
  createAutocomplete($('#srcInput'));
  createAutocomplete($('#dstInput'));
  createAutocomplete($('#neighborInput'));

  $('#predictBtn').addEventListener('click', predictConnection);
  $('#neighborBtn').addEventListener('click', discoverNeighbors);

  // Enter key support
  $('#srcInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#dstInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#neighborInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') discoverNeighbors(); });
});
