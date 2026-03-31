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
const show = (el) => { if (typeof el === 'string') el = $(el); el.style.display = ''; };
const hide = (el) => { if (typeof el === 'string') el = $(el); el.style.display = 'none'; };

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
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
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
    const pct = (prob * 100).toFixed(1);
    $('#probValue').textContent = `${pct}%`;
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

    // 3. Show synthetic tracks if we have them
    if (d.tracks && d.tracks.length > 0) {
      showSyntheticTracks(d.tracks);
      // 4. Find similar real tracks
      findSimilarTracks(d.tracks);
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
              <span>${pct.toFixed(1)}%</span>
            </div>
          </div>
          <span class="compare-latency">${r.latency_ms.toFixed(0)}ms</span>
        </div>`;
    }).join('');
  } catch (e) {
    $('#compareBars').innerHTML = `<span style="color:var(--text-muted);">Compare unavailable: ${e.message}</span>`;
  }
}

// ---- Synthetic Tracks Display ----
function showSyntheticTracks(trackIds) {
  show('#tracksCard');
  $('#tracksGrid').innerHTML = trackIds.map(tid => {
    const id = typeof tid === 'object' ? tid.track_id : tid;
    return `
      <div class="track-card">
        <div class="track-card-header">
          <span class="track-id">Track #${id}</span>
        </div>
        <div class="track-features" id="trackFeatures_${id}">
          <span style="font-size:0.75rem;color:var(--text-muted);">Synthetic track generated</span>
        </div>
      </div>`;
  }).join('');
}

// ---- Similar Real Tracks ----
async function findSimilarTracks(trackIds) {
  show('#playlistCard');
  loading('#playlistList', 'Finding similar real tracks...');

  const ids = trackIds.map(t => typeof t === 'object' ? t.track_id : t);

  try {
    const res = await api('/api/v1/generate/playlist', {
      method: 'POST',
      body: JSON.stringify({ synthetic_track_ids: ids, num_similar: 5 }),
    });

    const tracks = res.data.similar_tracks || [];
    if (tracks.length === 0) {
      $('#playlistList').innerHTML = '<div style="color:var(--text-muted);padding:1rem;text-align:center;">No similar tracks found</div>';
      return;
    }

    $('#playlistList').innerHTML = tracks.map((t, i) => `
      <div class="playlist-item">
        <span class="playlist-rank">${i + 1}</span>
        <div class="playlist-info">
          <div class="playlist-track-name">${escHtml(t.recording_name)}</div>
          <div class="playlist-artist-name">${escHtml(t.artist_name)}${t.artist_name_2 ? ' & ' + escHtml(t.artist_name_2) : ''}</div>
        </div>
        <span class="playlist-score">${(t.similarity * 100).toFixed(1)}%</span>
      </div>
    `).join('');
  } catch (e) {
    $('#playlistList').innerHTML = `<span style="color:var(--text-muted);">Playlist unavailable: ${e.message}</span>`;
  }
}

// ---- Neighbor Discovery ----
async function discoverNeighbors() {
  const artist = $('#neighborInput').value.trim();
  const limit = parseInt($('#neighborLimit').value) || 10;
  if (!artist) return alert('Enter an artist');

  show('#neighborsCard');
  $('#neighborsTitle').textContent = 'Predicted Collaborators';
  $('#neighborsBody').innerHTML = '<tr><td colspan="4"><div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 30 seconds for uncached artists...</div></td></tr>';

  try {
    const res = await api('/api/v1/predict/neighbors', {
      method: 'POST',
      body: JSON.stringify({ artist, limit }),
    });

    const d = res.data;
    const title = d.artist_name ? `Predicted Collaborators for ${d.artist_name}` : 'Predicted Collaborators';
    $('#neighborsTitle').textContent = title;

    const neighbors = d.neighbors || [];
    if (neighbors.length === 0) {
      $('#neighborsBody').innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">No neighbors found</td></tr>';
      return;
    }

    $('#neighborsBody').innerHTML = neighbors.map((n, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${escHtml(n.name || n.artist_id)}</td>
        <td><span class="prob-badge ${probClass(n.probability)}">${(n.probability * 100).toFixed(1)}%</span></td>
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
              <div class="genre-bar-fill" style="width:${pct}%;">
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

// ---- Event Listeners ----
document.addEventListener('DOMContentLoaded', () => {
  initApiKey();
  checkStatus();

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
