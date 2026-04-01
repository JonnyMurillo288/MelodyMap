/* =========================================
   Interlude API Demo — Frontend JS
   Calls /api/v1/* endpoints directly
========================================= */

// API calls go through the same origin — Go proxies /api/v1/* to the ML service
const API_BASE = window.location.origin;

// ---- Demo Keys (10 pre-registered, randomly assigned per session) ----
const DEMO_KEYS = [
  'interlude-demo-001', 'interlude-demo-002', 'interlude-demo-003',
  'interlude-demo-004', 'interlude-demo-005', 'interlude-demo-006',
  'interlude-demo-007', 'interlude-demo-008', 'interlude-demo-009',
  'interlude-demo-010',
];

// ---- State ----
let apiKey = '';

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

// ---- Boot: Health + Models ----
async function checkStatus() {
  try {
    const health = await api('/api/v1/health');
    const d = health.data;
    $('#statusDb').classList.toggle('ok', d.db_connected);
    $('#statusDb').classList.toggle('err', !d.db_connected);
    $('#statusVersion').textContent = d.version || '1.0.0';

    const models = await api('/api/v1/models');
    const m = models.data;
    const logitVersions = m.logit?.available?.join(', ') || '--';
    $('#statusModels').textContent = `logit: ${logitVersions}`;
  } catch (e) {
    $('#statusDb').classList.add('err');
    $('#statusVersion').textContent = 'offline';
  }
}

// ---- API Key: auto-assign demo key per session ----
function initApiKey() {
  const input = $('#apiKeyInput');
  const dot = $('#keyStatus');
  const info = $('#keyInfo');

  // Check if user has their own key saved
  const savedKey = localStorage.getItem('interlude_api_key');
  const savedType = localStorage.getItem('interlude_key_type');

  if (savedKey && savedType === 'personal') {
    // User registered their own key
    apiKey = savedKey;
    input.value = savedKey;
    dot.classList.add('ok');
    info.textContent = 'Your personal API key';
    $('#demoNote').style.display = 'none';
  } else {
    // Assign a random demo key for this session
    const idx = Math.floor(Math.random() * DEMO_KEYS.length);
    const demoKey = DEMO_KEYS[idx];
    apiKey = demoKey;
    input.value = demoKey;
    localStorage.setItem('interlude_api_key', demoKey);
    localStorage.setItem('interlude_key_type', 'demo');
    dot.classList.add('ok');
    info.textContent = 'Demo key (auto-assigned)';
  }
}

// ---- API Key Registration ----
async function registerApiKey() {
  const email = $('#registerEmail').value.trim();
  if (!email) return alert('Enter your email');

  const org = $('#registerOrg').value.trim();
  const resultDiv = $('#registerResult');
  resultDiv.innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Creating your account...</div>';

  try {
    const headers = { 'Content-Type': 'application/json' };
    // Don't send API key for registration — it's a public endpoint
    const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ email, org_name: org || null }),
    });

    const data = await res.json();
    console.log('Register response:', res.status, data);

    if (!res.ok) {
      resultDiv.innerHTML = `<span style="color:#ef4444;">Error ${res.status}: ${data.detail || JSON.stringify(data)}</span>`;
      return;
    }

    const key = data.api_key;
    if (!key) {
      resultDiv.innerHTML = `<span style="color:#ef4444;">No API key in response: ${JSON.stringify(data)}</span>`;
      return;
    }

    // Save as personal key and load into the bar
    apiKey = key;
    $('#apiKeyInput').value = key;
    localStorage.setItem('interlude_api_key', key);
    localStorage.setItem('interlude_key_type', 'personal');
    $('#keyStatus').classList.add('ok');
    $('#keyInfo').textContent = 'Your personal API key';
    $('#demoNote').style.display = 'none';

    resultDiv.innerHTML = `
      <div class="register-success">
        <strong>Account created!</strong> Your API key:<br/>
        <code>${escHtml(key)}</code><br/>
        <small style="color:var(--text-muted);">Saved automatically. 100 requests/hour on the free tier.</small>
      </div>`;
  } catch (e) {
    console.error('Register error:', e);
    resultDiv.innerHTML = `<span style="color:#ef4444;">Request failed: ${e.message}. Is the ML service running?</span>`;
  }
}

// ---- Predict Connection ----
async function predictConnection() {
  const src = $('#srcInput').value.trim();
  const dst = $('#dstInput').value.trim();
  if (!src || !dst) return alert('Enter both artists');

  show('#connectionCard');
  hide('#compareCard');
  hide('#tracksCard');
  hide('#playlistCard');

  $('#srcBadge').textContent = src;
  $('#dstBadge').textContent = dst;
  $('#probValue').textContent = '...';
  $('#probRing').className = 'prob-ring';
  $('#connectionMeta').innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 30 seconds for uncached artists...</div>';

  try {
    // 1. Predict connection
    const res = await api('/api/v1/predict/connection', {
      method: 'POST',
      body: JSON.stringify({ src_artist: src, dst_artist: dst, limit: 5 }),
    });

    const d = res.data;
    const m = res.meta;
    const prob = d.probability;

    // Update artist names if returned
    if (d.src_name) $('#srcBadge').textContent = d.src_name;
    if (d.dst_name) $('#dstBadge').textContent = d.dst_name;

    // Probability display
    const pct = (prob * 100).toFixed(2);
    $('#probValue').textContent = `${pct}`;
    $('#probRing').className = `prob-ring ${probClass(prob)}`;

    // Meta
    $('#connectionMeta').innerHTML = `
      <span>Model: <span class="meta-tag">${m.model_version}</span></span>
      <span>Latency: <span class="meta-tag">${m.latency_ms.toFixed(0)}ms</span></span>
      <span>Cached: <span class="meta-tag">${m.cached ? 'yes' : 'no'}</span></span>
      <span>Tracks: <span class="meta-tag">${(d.tracks || []).length}</span></span>
    `;

    // 2. Run model comparison in parallel
    runComparison(src, dst);

    // 3. Show synthetic tracks with features
    if (d.tracks && d.tracks.length > 0) {
      showSyntheticTracks(d.tracks);
    }

  } catch (e) {
    $('#connectionMeta').innerHTML = `<span style="color:var(--error);">${e.message}</span>`;
  }
}

// ---- Model Comparison ----
async function runComparison(src, dst) {
  show('#compareCard');
  loading('#compareBars', 'Comparing model versions...');

  try {
    const res = await api('/api/v1/predict/compare', {
      method: 'POST',
      body: JSON.stringify({ src_artist: src, dst_artist: dst, versions: ['v1', 'v3', 'v5'] }),
    });

    const results = res.data.results;
    const maxProb = Math.max(...results.map(r => r.probability));
    const colors = ['#60a5fa', '#a78bfa', '#34d399', '#fbbf24', '#f472b6'];

    $('#compareBars').innerHTML = results.map((r, i) => {
      const pct = Math.max(0, r.probability * 100);
      const w = maxProb > 0 ? (r.probability / maxProb * 100) : 0;
      const color = colors[i % colors.length];
      return `
        <div class="compare-row">
          <span class="compare-label">${r.version}</span>
          <div class="compare-bar-track">
            <div class="compare-bar-fill" style="width:${w}%;background:${color};">
              <span>${pct.toFixed(0)}</span>
            </div>
          </div>
          <span class="compare-latency">${r.latency_ms.toFixed(0)}ms</span>
        </div>`;
    }).join('');
  } catch (e) {
    $('#compareBars').innerHTML = `<span style="color:var(--text-muted);">Compare unavailable: ${e.message}</span>`;
  }
}

// ---- Feature display config (same categories as ML page) ----
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

// ---- Synthetic Tracks Display with Feature Bars ----
function showSyntheticTracks(tracks) {
  show('#tracksCard');
  $('#tracksGrid').innerHTML = tracks.map((track, idx) => {
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
            <span class="feat-val">${pct.toFixed(0)}</span>
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

// ---- Neighbor Discovery ----
async function discoverNeighbors() {
  const artist = $('#neighborInput').value.trim();
  if (!artist) return alert('Enter an artist');

  show('#neighborsCard');
  $('#neighborsTitle').textContent = 'Predicted Collaborators';
  $('#neighborsBody').innerHTML = '<tr><td colspan="4"><div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 60 seconds for uncached artists...</div></td></tr>';

  try {
    const res = await api('/api/v1/predict/neighbors', {
      method: 'POST',
      body: JSON.stringify({ artist, limit: 20 }),
    });

    const d = res.data;
    const title = d.artist_name ? `Top Predicted Collaborators for ${d.artist_name}` : 'Top Predicted Collaborators';
    $('#neighborsTitle').textContent = title;

    let neighbors = d.neighbors || [];
    if (neighbors.length === 0) {
      $('#neighborsBody').innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">No neighbors found</td></tr>';
      return;
    }

    // Sort descending by probability
    neighbors.sort((a, b) => b.probability - a.probability);

    $('#neighborsBody').innerHTML = neighbors.map((n, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${escHtml(n.name || n.artist_id)}</td>
        <td><span class="prob-badge ${probClass(n.probability)}">${(n.probability * 100).toFixed(2)}%</span></td>
        <td>${(n.tracks || []).length} tracks</td>
      </tr>
    `).join('');
  } catch (e) {
    $('#neighborsBody').innerHTML = `<tr><td colspan="4" style="color:var(--error);">${e.message}</td></tr>`;
  }
}

// ---- Artist Profile ----
async function loadProfile() {
  const artist = $('#profileInput').value.trim();
  if (!artist) return alert('Enter an artist');

  show('#profileCard');
  $('#profileName').textContent = 'Loading...';
  $('#profileBadges').innerHTML = '';
  $('#genreBars').innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div></div>';
  $('#collabList').innerHTML = '';

  try {
    const res = await api(`/api/v1/artist/${encodeURIComponent(artist)}/profile`);
    const d = res.data;

    $('#profileName').textContent = d.name;

    // Badges
    const badges = [];
    if (d.popularity != null) badges.push(`<span class="profile-badge popularity">Popularity: ${d.popularity.toFixed(1)}</span>`);
    badges.push(`<span class="profile-badge collabs">${d.collab_count} collaborations</span>`);
    if (d.spotify_id) badges.push(`<span class="profile-badge spotify">Spotify linked</span>`);
    if (d.embedding_available) badges.push(`<span class="profile-badge embedding">Embedding ready</span>`);
    $('#profileBadges').innerHTML = badges.join('');

    // Genre distribution
    const genres = d.genre_distribution || {};
    const genreEntries = Object.entries(genres).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const maxGenre = genreEntries.length > 0 ? genreEntries[0][1] : 1;

    if (genreEntries.length === 0) {
      $('#genreBars').innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;">No genre data available</div>';
    } else {
      $('#genreBars').innerHTML = genreEntries.map(([name, val]) => {
        const pct = (val / maxGenre * 100).toFixed(0);
        const label = name.replace('prop_genre_', '').replace('rosamerica_', '').replace('dortmund_', '');
        return `
          <div class="genre-row">
            <span class="genre-label">${label}</span>
            <div class="genre-bar-track">
              <div class="genre-bar-fill" style="width:${pct}%;"></div>
                <span>${(val * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>`;
      }).join('');
    }

    // Top collaborators
    const collabs = d.top_collabs || [];
    if (collabs.length === 0) {
      $('#collabList').innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;">No collaborators found</div>';
    } else {
      $('#collabList').innerHTML = collabs.map(c => `
        <div class="collab-item">
          <span class="name">${escHtml(c.name)}</span>
          <span class="count">${c.collab_count} tracks</span>
        </div>
      `).join('');
    }

  } catch (e) {
    $('#profileName').textContent = 'Error';
    $('#genreBars').innerHTML = `<span style="color:var(--error);">${e.message}</span>`;
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
  checkStatus();
  loadArtistNames();

  // Autocomplete on all artist inputs
  createAutocomplete($('#srcInput'));
  createAutocomplete($('#dstInput'));
  createAutocomplete($('#neighborInput'));
  createAutocomplete($('#profileInput'));

  $('#predictBtn').addEventListener('click', predictConnection);
  $('#neighborBtn').addEventListener('click', discoverNeighbors);
  $('#profileBtn').addEventListener('click', loadProfile);

  // Get own key button → toggle registration form
  $('#getKeyBtn').addEventListener('click', () => {
    const form = $('#registerForm');
    form.style.display = form.style.display === 'none' ? '' : 'none';
  });
  $('#registerBtn').addEventListener('click', registerApiKey);
  $('#registerEmail').addEventListener('keydown', (e) => { if (e.key === 'Enter') registerApiKey(); });

  // Enter key support
  $('#srcInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#dstInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#neighborInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') discoverNeighbors(); });
  $('#profileInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadProfile(); });
});
