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
    } catch (e) { detail += ': ' + await res.text(); }
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

    // Show synthetic tracks — if none returned, generate them
    let tracks = d.tracks || [];
    const hasFeatures = tracks.length > 0 && tracks.some(t => Object.keys(t).length > 1);

    if (!hasFeatures) {
      try {
        const genRes = await api('/api/v1/generate/tracks', {
          method: 'POST',
          body: JSON.stringify({
            src_artist: src,
            dst_artist: dst,
            num_tracks: 5,
          }),
        });
        tracks = genRes.data?.tracks || genRes.tracks || [];
      } catch (genErr) {
        console.warn('Track generation fallback failed:', genErr.message);
      }
    }

    showSyntheticTracks(tracks);

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
  } catch (e) { return []; }
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

// ====================================================================
// WHAT-IF EXPLORER — test data for /api/v1/explore/what-if
// ====================================================================

const WHATIF_TEST_DATA = {
  "Billie Eilish+The Weeknd": { probability: 0.81, genre: "dark-pop", mood: "melancholic" },
  "Billie Eilish+Daft Punk": { probability: 0.43, genre: "electro-pop", mood: "atmospheric" },
  "Billie Eilish+Tame Impala": { probability: 0.56, genre: "dream-pop", mood: "dreamy" },
  "The Weeknd+Daft Punk": { probability: 0.94, genre: "synth-funk", mood: "euphoric" },
  "The Weeknd+Tame Impala": { probability: 0.67, genre: "psychedelic-rnb", mood: "nocturnal" },
  "Daft Punk+Tame Impala": { probability: 0.71, genre: "space-disco", mood: "cosmic" },
};

function generateWhatIfTracks(src, dst, prob) {
  const seed = (src + dst).length;
  return [
    {
      track_id: 5000 + seed,
      genre_dortmund_electronic: 0.40 + prob * 0.3,
      genre_dortmund_pop: 0.15 + (1 - prob) * 0.2,
      genre_dortmund_alternative: 0.10 + Math.random() * 0.2,
      mood_electronic: 0.50 + prob * 0.2,
      mood_relaxed: 0.30 + Math.random() * 0.3,
      danceability: 0.50 + prob * 0.3,
      timbre_dark: 0.40 + Math.random() * 0.3,
      voice_instrumental_voice: 0.60 + Math.random() * 0.2,
      predicted_popularity: Math.round(60 + prob * 30),
      similar_real_tracks: [
        { recording: "Track by " + src, artist: src, similarity: 0.85 + Math.random() * 0.1 },
        { recording: "Track by " + dst, artist: dst, similarity: 0.78 + Math.random() * 0.1 },
      ]
    },
    {
      track_id: 5100 + seed,
      genre_dortmund_electronic: 0.35 + prob * 0.25,
      genre_dortmund_pop: 0.20 + (1 - prob) * 0.15,
      genre_dortmund_alternative: 0.15 + Math.random() * 0.15,
      mood_electronic: 0.45 + prob * 0.25,
      mood_happy: 0.20 + Math.random() * 0.3,
      danceability: 0.45 + prob * 0.35,
      timbre_bright: 0.35 + Math.random() * 0.3,
      voice_instrumental_voice: 0.55 + Math.random() * 0.25,
      predicted_popularity: Math.round(55 + prob * 28),
      similar_real_tracks: [
        { recording: "Another by " + dst, artist: dst, similarity: 0.80 + Math.random() * 0.1 },
        { recording: "Another by " + src, artist: src, similarity: 0.74 + Math.random() * 0.1 },
      ]
    }
  ];
}

// (What-If input/button functions removed — preview cards auto-render with fixed data)

function toggleWhatIfPair(idx) {
  const body = document.getElementById(`whatif-body-${idx}`);
  const arrow = document.getElementById(`whatif-arrow-${idx}`);
  if (body.style.display !== 'none') {
    body.style.display = 'none';
    arrow.innerHTML = '&#9654;';
  } else {
    body.style.display = '';
    arrow.innerHTML = '&#9660;';
  }
}

// ====================================================================
// SYNTHETIC TRACK FEATURES — test data for /api/v1/explore/synthetic-track-features
// ====================================================================

function generateSynthFeatures(src, dst) {
  const seed = (src + dst).length;
  const prob = 0.40 + (seed % 50) / 100;
  return {
    probability: prob,
    tracks: [
      {
        track_id: 7001 + seed,
        audio_features: {
          genre_dortmund_alternative: 0.48, genre_dortmund_electronic: 0.39,
          mood_relaxed: 0.65, mood_sad: 0.38, danceability: 0.55,
          timbre_dark: 0.52, voice_instrumental_voice: 0.73
        },
        instrumentation: {
          primary: ["synth", "bass"],
          secondary: ["guitar", "drum_machine"],
          confidence: { synth: 0.89, bass: 0.82, guitar: 0.71, drum_machine: 0.65, strings: 0.22, piano: 0.18 }
        },
        lyric_assessment: {
          mood: "introspective", themes: ["isolation", "self-reflection", "longing"],
          vocal_style: "breathy", density: 0.42, sentiment: -0.15, explicit_prob: 0.12
        },
        genre_style: {
          primary: "psychedelic-pop", subs: ["dream-pop", "electro-pop", "indie"],
          era: "2020s", blend_score: 0.74
        },
        popularity: {
          predicted: 79,
          by_region: {
            "North America": { score: 84, percentile: 92 },
            "Europe": { score: 81, percentile: 89 },
            "Latin America": { score: 62, percentile: 71 },
            "Asia Pacific": { score: 70, percentile: 78 },
            "Africa & Middle East": { score: 48, percentile: 60 }
          },
          by_consumer: {
            "Casual Listener": { appeal: 0.72, skip_rate: 0.18 },
            "Genre Enthusiast": { appeal: 0.88, skip_rate: 0.06 },
            "Playlist Curator": { appeal: 0.81, skip_rate: 0.10 },
            "Discovery Seeker": { appeal: 0.90, skip_rate: 0.05 },
            "Passive Streamer": { appeal: 0.60, skip_rate: 0.28 }
          }
        }
      },
      {
        track_id: 7101 + seed,
        audio_features: {
          genre_dortmund_alternative: 0.52, genre_dortmund_electronic: 0.34,
          mood_relaxed: 0.71, mood_electronic: 0.30, danceability: 0.60,
          timbre_bright: 0.44, voice_instrumental_voice: 0.68
        },
        instrumentation: {
          primary: ["guitar", "synth"],
          secondary: ["bass", "reverb_vocals"],
          confidence: { guitar: 0.87, synth: 0.80, bass: 0.74, reverb_vocals: 0.69, drums: 0.58, piano: 0.15 }
        },
        lyric_assessment: {
          mood: "dreamy", themes: ["escape", "nostalgia", "wonder"],
          vocal_style: "layered_harmonies", density: 0.35, sentiment: 0.22, explicit_prob: 0.04
        },
        genre_style: {
          primary: "dream-pop", subs: ["shoegaze", "art-pop", "synth-pop"],
          era: "2010s", blend_score: 0.81
        },
        popularity: {
          predicted: 74,
          by_region: {
            "North America": { score: 78, percentile: 85 },
            "Europe": { score: 80, percentile: 88 },
            "Latin America": { score: 55, percentile: 63 },
            "Asia Pacific": { score: 65, percentile: 72 },
            "Africa & Middle East": { score: 42, percentile: 54 }
          },
          by_consumer: {
            "Casual Listener": { appeal: 0.65, skip_rate: 0.22 },
            "Genre Enthusiast": { appeal: 0.91, skip_rate: 0.04 },
            "Playlist Curator": { appeal: 0.78, skip_rate: 0.12 },
            "Discovery Seeker": { appeal: 0.85, skip_rate: 0.07 },
            "Passive Streamer": { appeal: 0.52, skip_rate: 0.32 }
          }
        }
      }
    ]
  };
}

// (Synth features input/button function removed — preview card auto-renders with fixed data)

function instrumentIcon(name) {
  const icons = {
    synth: '🎹', bass: '🎸', guitar: '🎸', drum_machine: '🥁', drums: '🥁',
    strings: '🎻', piano: '🎹', reverb_vocals: '🎤', vocals: '🎤'
  };
  return icons[name] || '🎵';
}

// ====================================================================
// PLAYLIST GENERATOR — test data for /api/v1/generate/playlist
// ====================================================================

const PLAYLIST_TRACKS = [
  { name: "Blinding Lights", artist: "The Weeknd", similarity: 0.94, genre: "synth-pop", popularity: 95, features: { energy: 0.73, danceability: 0.51, valence: 0.34 } },
  { name: "bad guy", artist: "Billie Eilish", similarity: 0.91, genre: "electro-pop", popularity: 92, features: { energy: 0.43, danceability: 0.70, valence: 0.56 } },
  { name: "The Less I Know the Better", artist: "Tame Impala", similarity: 0.88, genre: "psychedelic-pop", popularity: 88, features: { energy: 0.74, danceability: 0.72, valence: 0.68 } },
  { name: "Starboy", artist: "The Weeknd", similarity: 0.87, genre: "electro-rnb", popularity: 93, features: { energy: 0.59, danceability: 0.68, valence: 0.49 } },
  { name: "everything i wanted", artist: "Billie Eilish", similarity: 0.85, genre: "dream-pop", popularity: 86, features: { energy: 0.23, danceability: 0.51, valence: 0.24 } },
  { name: "Let It Happen", artist: "Tame Impala", similarity: 0.84, genre: "psychedelic-rock", popularity: 82, features: { energy: 0.85, danceability: 0.52, valence: 0.46 } },
  { name: "Get Lucky", artist: "Daft Punk", similarity: 0.83, genre: "disco-funk", popularity: 90, features: { energy: 0.78, danceability: 0.87, valence: 0.93 } },
  { name: "Save Your Tears", artist: "The Weeknd", similarity: 0.82, genre: "synth-pop", popularity: 94, features: { energy: 0.64, danceability: 0.68, valence: 0.59 } },
  { name: "lovely", artist: "Billie Eilish", similarity: 0.80, genre: "dark-pop", popularity: 89, features: { energy: 0.30, danceability: 0.35, valence: 0.12 } },
  { name: "Instant Crush", artist: "Daft Punk", similarity: 0.79, genre: "synth-rock", popularity: 78, features: { energy: 0.60, danceability: 0.52, valence: 0.40 } },
  { name: "Borderline", artist: "Tame Impala", similarity: 0.77, genre: "synth-pop", popularity: 75, features: { energy: 0.72, danceability: 0.71, valence: 0.74 } },
  { name: "One More Time", artist: "Daft Punk", similarity: 0.76, genre: "french-house", popularity: 87, features: { energy: 0.82, danceability: 0.89, valence: 0.96 } },
];

// (Playlist input/button function removed — preview card auto-renders with fixed data)

function togglePlaylistDetail(row) {
  row.classList.toggle('expanded');
}

// ---- Auto-render preview cards with fixed demo data ----
function renderPreviewCards() {
  // What-If: prefill with 4 artists
  runWhatIfPreview(["Billie Eilish", "The Weeknd", "Daft Punk", "Tame Impala"]);

  // Synthetic Track Deep Dive: prefill
  runSynthFeaturesPreview("Billie Eilish", "Tame Impala");

  // Playlist: prefill
  runPlaylistPreview("Billie Eilish", "The Weeknd");
}

function runWhatIfPreview(artists) {
  const pairs = [];
  for (let i = 0; i < artists.length; i++) {
    for (let j = i + 1; j < artists.length; j++) {
      const key = artists[i] + '+' + artists[j];
      const revKey = artists[j] + '+' + artists[i];
      const testData = WHATIF_TEST_DATA[key] || WHATIF_TEST_DATA[revKey] || {
        probability: 0.30 + Math.random() * 0.5, genre: "experimental", mood: "exploratory"
      };
      pairs.push({
        src: artists[i], dst: artists[j], ...testData,
        tracks: generateWhatIfTracks(artists[i], artists[j], testData.probability)
      });
    }
  }
  pairs.sort((a, b) => b.probability - a.probability);

  // Network
  $('#whatifNetwork').innerHTML = `
    <div class="whatif-network-grid">
      ${artists.map((a, i) => {
        const angle = (i / artists.length) * 2 * Math.PI - Math.PI / 2;
        const x = 50 + 35 * Math.cos(angle);
        const y = 50 + 35 * Math.sin(angle);
        return `<div class="whatif-node" style="left:${x}%;top:${y}%;">${escHtml(a)}</div>`;
      }).join('')}
      <svg class="whatif-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
        ${pairs.map(p => {
          const si = artists.indexOf(p.src), di = artists.indexOf(p.dst);
          const a1 = (si / artists.length) * 2 * Math.PI - Math.PI / 2;
          const a2 = (di / artists.length) * 2 * Math.PI - Math.PI / 2;
          const x1 = 50 + 35 * Math.cos(a1), y1 = 50 + 35 * Math.sin(a1);
          const x2 = 50 + 35 * Math.cos(a2), y2 = 50 + 35 * Math.sin(a2);
          return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--accent)" stroke-opacity="${0.3 + p.probability * 0.7}" stroke-width="${0.3 + p.probability * 1.2}"/>`;
        }).join('')}
      </svg>
    </div>`;

  // Pairs
  $('#whatifPairs').innerHTML = pairs.map((p, idx) => `
    <div class="whatif-pair-card">
      <div class="whatif-pair-header" onclick="toggleWhatIfPair(${idx})">
        <div class="whatif-pair-artists">
          <span class="whatif-artist-name src">${escHtml(p.src)}</span>
          <span class="whatif-x">&times;</span>
          <span class="whatif-artist-name dst">${escHtml(p.dst)}</span>
        </div>
        <div class="whatif-pair-meta">
          <span class="prob-badge ${probClass(p.probability)}">${(p.probability * 100).toFixed(1)}%</span>
          <span class="whatif-genre-tag">${p.genre}</span>
          <span class="whatif-mood-tag">${p.mood}</span>
          <span class="expand-arrow" id="whatif-arrow-${idx}">&#9654;</span>
        </div>
      </div>
      <div class="whatif-pair-body" id="whatif-body-${idx}" style="display:none;">
        <div class="whatif-tracks-section">
          <h4>Synthetic Tracks</h4>
          <div class="tracks-grid">${renderTrackCards(p.tracks)}</div>
        </div>
        <div class="whatif-similar-section">
          <h4>Similar Real Tracks</h4>
          ${p.tracks.map(t => t.similar_real_tracks.map(s => `
            <div class="similar-track-row">
              <span class="similar-track-name">${escHtml(s.recording)}</span>
              <span class="similar-track-artist">${escHtml(s.artist)}</span>
              <span class="prob-badge ${probClass(s.similarity)}">${(s.similarity * 100).toFixed(0)}% match</span>
            </div>
          `).join('')).join('')}
        </div>
      </div>
    </div>
  `).join('');
}

// ---- Prediction Score & Insights ----

function renderPredictionScore(data, src, dst) {
  const track = data.tracks[0];
  const score = track.popularity.predicted;
  const regions = track.popularity.by_region;

  // Find best and worst regions
  const sorted = Object.entries(regions).sort((a, b) => b[1].score - a[1].score);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];

  const scoreClass = score >= 75 ? 'score-high' : score >= 55 ? 'score-mid' : 'score-low';

  $('#predictionScore').innerHTML = `
    <div class="prediction-score-card">
      <div class="prediction-score-ring ${scoreClass}">
        <span class="prediction-score-num">${score}</span>
        <span class="prediction-score-label">/ 100</span>
      </div>
      <div class="prediction-score-text">
        <div class="prediction-score-title">Predicted Performance</div>
        <div class="prediction-score-subtitle">Strong in ${best[0]} (${best[1].score}), weaker in ${worst[0]} (${worst[1].score})</div>
      </div>
    </div>`;
}

function generateInsights(data, src, dst) {
  const track = data.tracks[0];
  const regions = track.popularity.by_region;
  const consumers = track.popularity.by_consumer;
  const genre = track.genre_style;

  const insights = [];

  // Best market
  const bestRegion = Object.entries(regions).sort((a, b) => b[1].score - a[1].score)[0];
  insights.push({ text: `Best market: ${bestRegion[0]}`, type: 'positive' });

  // Strongest genre alignment
  insights.push({ text: `Strongest genre alignment: ${genre.primary.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ')}`, type: 'positive' });

  // Comparable artists
  insights.push({ text: `Comparable to: ${src} × ${dst} archetype`, type: 'neutral' });

  // Consumer insight — find lowest skip rate
  const lowestSkip = Object.entries(consumers).sort((a, b) => a[1].skip_rate - b[1].skip_rate)[0];
  if (lowestSkip[1].skip_rate < 0.10) {
    insights.push({ text: `${lowestSkip[0]}s rarely skip (${(lowestSkip[1].skip_rate * 100).toFixed(0)}% skip rate) — strong core audience`, type: 'positive' });
  }

  // Regional weakness
  const worstRegion = Object.entries(regions).sort((a, b) => a[1].score - b[1].score)[0];
  if (worstRegion[1].score < 55) {
    insights.push({ text: `Weak in ${worstRegion[0]} — consider localized marketing`, type: 'warning' });
  }

  // Genre crossover
  if (genre.blend_score > 0.7) {
    insights.push({ text: `High crossover appeal across ${genre.subs.slice(0, 2).join(' and ')} audiences`, type: 'positive' });
  }

  return insights.slice(0, 4); // cap at 4
}

function renderInsights(insights) {
  $('#synthInsights').innerHTML = `
    <div class="insights-list">
      ${insights.map(i => `
        <div class="insight-item insight-${i.type}">
          <span class="insight-icon">${i.type === 'positive' ? '&#9650;' : i.type === 'warning' ? '&#9888;' : '&#8594;'}</span>
          <span class="insight-text">${i.text}</span>
        </div>
      `).join('')}
    </div>`;
}

function runSynthFeaturesPreview(src, dst) {
  const data = generateSynthFeatures(src, dst);

  // 1. Prediction Score
  renderPredictionScore(data, src, dst);

  // 2. Insights
  const insights = generateInsights(data, src, dst);
  renderInsights(insights);

  // 3. Full track breakdown
  const container = $('#synthFeatContent');
  container.innerHTML = data.tracks.map((track, ti) => buildSynthTrackHtml(track, ti)).join('<hr class="synth-divider"/>');
}

function buildSynthTrackHtml(track, ti) {
  return `
    <div class="synth-track-deep ${ti > 0 ? 'synth-track-border' : ''}">
      <div class="synth-track-header">
        <span class="track-id">Track #${track.track_id}</span>
        <span class="synth-popularity-badge">Popularity: ${track.popularity.predicted}/100</span>
      </div>
      <div class="synth-sections-grid">
        <div class="synth-section">
          <h4>Instrumentation</h4>
          <div class="instrument-list">
            ${Object.entries(track.instrumentation.confidence)
              .sort((a, b) => b[1] - a[1])
              .map(([inst, conf]) => {
                const isPrimary = track.instrumentation.primary.includes(inst);
                return `<div class="instrument-row">
                  <span class="instrument-icon">${instrumentIcon(inst)}</span>
                  <span class="instrument-name${isPrimary ? ' primary' : ''}">${inst.replace(/_/g, ' ')}</span>
                  <div class="instrument-bar-bg"><div class="instrument-bar-fill" style="width:${(conf * 100).toFixed(0)}%;background:${isPrimary ? '#3b82f6' : '#64748b'};"></div></div>
                  <span class="instrument-val">${(conf * 100).toFixed(0)}%</span>
                </div>`;
              }).join('')}
          </div>
        </div>
        <div class="synth-section">
          <h4>Lyric Assessment</h4>
          <div class="lyric-info">
            <div class="lyric-mood-display"><span class="lyric-label">Mood</span><span class="lyric-mood-value">${track.lyric_assessment.mood}</span></div>
            <div class="lyric-mood-display"><span class="lyric-label">Vocal Style</span><span class="lyric-mood-value">${track.lyric_assessment.vocal_style.replace(/_/g, ' ')}</span></div>
            <div class="lyric-themes">${track.lyric_assessment.themes.map(t => `<span class="theme-tag">${t}</span>`).join('')}</div>
            <div class="lyric-meters">
              <div class="lyric-meter">
                <span class="lyric-label">Density</span>
                <div class="lyric-meter-bar"><div class="lyric-meter-fill" style="width:${(track.lyric_assessment.density * 100)}%;"></div></div>
                <span class="lyric-meter-val">${(track.lyric_assessment.density * 100).toFixed(0)}%</span>
              </div>
              <div class="lyric-meter">
                <span class="lyric-label">Sentiment</span>
                <div class="lyric-meter-bar sentiment"><div class="lyric-meter-fill sentiment" style="width:${50 + track.lyric_assessment.sentiment * 50}%;background:${track.lyric_assessment.sentiment >= 0 ? '#22c55e' : '#ef4444'};"></div></div>
                <span class="lyric-meter-val">${track.lyric_assessment.sentiment > 0 ? '+' : ''}${track.lyric_assessment.sentiment.toFixed(2)}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="synth-section">
          <h4>Genre Style</h4>
          <div class="genre-style-display">
            <div class="genre-primary">${track.genre_style.primary}</div>
            <div class="genre-subs">${track.genre_style.subs.map(s => `<span class="genre-sub-tag">${s}</span>`).join('')}</div>
            <div class="genre-meta-row"><span>Era: <strong>${track.genre_style.era}</strong></span><span>Blend: <strong>${(track.genre_style.blend_score * 100).toFixed(0)}%</strong></span></div>
          </div>
        </div>
        <div class="synth-section">
          <h4>Audio Features</h4>
          ${Object.entries(track.audio_features).map(([key, val]) => {
            const pct = Math.min(100, Math.max(0, val * 100));
            return `<div class="feat-row">
              <span class="feat-label">${key.replace(/^(genre_dortmund_|mood_|voice_instrumental_|timbre_)/, '')}</span>
              <div class="feat-bar-bg"><div class="feat-bar-fill" style="width:${pct.toFixed(0)}%;background:#8b5cf6;"></div></div>
              <span class="feat-val">${pct.toFixed(0)}%</span>
            </div>`;
          }).join('')}
        </div>
      </div>
      <div class="region-section">
        <h4>Popularity by Region</h4>
        <div class="region-map">
          ${Object.entries(track.popularity.by_region).map(([region, data]) => {
            const hue = data.score > 70 ? 142 : data.score > 50 ? 45 : 0;
            return `<div class="region-card" style="border-color:hsl(${hue},70%,50%);">
              <div class="region-name">${region}</div>
              <div class="region-score" style="color:hsl(${hue},70%,60%);">${data.score}</div>
              <div class="region-bar-bg"><div class="region-bar-fill" style="width:${data.percentile}%;background:hsl(${hue},70%,50%);"></div></div>
              <div class="region-percentile">Top ${100 - data.percentile}%</div>
            </div>`;
          }).join('')}
        </div>
      </div>
      <div class="consumer-section">
        <h4>Appeal by Consumer Type</h4>
        <div class="consumer-grid">
          ${Object.entries(track.popularity.by_consumer).map(([type, data]) => {
            const appealPct = (data.appeal * 100).toFixed(0);
            const skipPct = (data.skip_rate * 100).toFixed(0);
            return `<div class="consumer-card" onclick="this.classList.toggle('flipped')">
              <div class="consumer-front">
                <div class="consumer-type">${type}</div>
                <div class="consumer-appeal-ring" style="background:conic-gradient(#3b82f6 ${appealPct}%, rgba(255,255,255,0.08) 0);"><span>${appealPct}%</span></div>
                <div class="consumer-label">Appeal</div>
              </div>
              <div class="consumer-back">
                <div class="consumer-type">${type}</div>
                <div class="consumer-stat">Skip Rate: <strong>${skipPct}%</strong></div>
                <div class="consumer-skip-bar"><div style="width:${skipPct}%;background:#ef4444;height:100%;border-radius:4px;"></div></div>
                <div class="consumer-label flip-hint">Click to flip back</div>
              </div>
            </div>`;
          }).join('')}
        </div>
      </div>
    </div>`;
}

function runPlaylistPreview(src, dst) {
  const tracks = PLAYLIST_TRACKS;
  $('#playlistContent').innerHTML = `
    <div class="playlist-header-bar">
      <div class="playlist-cover">
        <div class="playlist-cover-grid">
          <div style="background:#3b82f6;"></div>
          <div style="background:#8b5cf6;"></div>
          <div style="background:#ec4899;"></div>
          <div style="background:#f59e0b;"></div>
        </div>
      </div>
      <div class="playlist-info-block">
        <div class="playlist-type-label">GENERATED PLAYLIST</div>
        <div class="playlist-name-big">${escHtml(src)} &times; ${escHtml(dst)}</div>
        <div class="playlist-meta-info">${tracks.length} tracks &bull; Based on synthetic collaboration analysis</div>
      </div>
    </div>
    <div class="playlist-tracks-list">
      ${tracks.map((t, i) => `
        <div class="playlist-track-row${i === 0 ? ' now-playing' : ''}" onclick="togglePlaylistDetail(this)">
          <div class="playlist-track-main">
            <span class="playlist-track-num">${i + 1}</span>
            <div class="playlist-track-info">
              <span class="playlist-track-name">${escHtml(t.name)}</span>
              <span class="playlist-track-artist">${escHtml(t.artist)}</span>
            </div>
            <span class="playlist-track-genre">${t.genre}</span>
            <div class="playlist-track-match">
              <div class="match-bar-bg"><div class="match-bar-fill" style="width:${(t.similarity * 100).toFixed(0)}%;"></div></div>
              <span>${(t.similarity * 100).toFixed(0)}%</span>
            </div>
            <span class="playlist-track-pop">${t.popularity}</span>
          </div>
          <div class="playlist-track-detail">
            <div class="detail-bars">
              <div class="detail-bar-item"><span>Energy</span><div class="detail-bar-bg"><div class="detail-bar-fill energy" style="width:${(t.features.energy * 100)}%;"></div></div><span>${(t.features.energy * 100).toFixed(0)}%</span></div>
              <div class="detail-bar-item"><span>Danceability</span><div class="detail-bar-bg"><div class="detail-bar-fill dance" style="width:${(t.features.danceability * 100)}%;"></div></div><span>${(t.features.danceability * 100).toFixed(0)}%</span></div>
              <div class="detail-bar-item"><span>Valence</span><div class="detail-bar-bg"><div class="detail-bar-fill valence" style="width:${(t.features.valence * 100)}%;"></div></div><span>${(t.features.valence * 100).toFixed(0)}%</span></div>
            </div>
          </div>
        </div>
      `).join('')}
    </div>`;
}

// ---- Event Listeners ----
document.addEventListener('DOMContentLoaded', () => {
  initApiKey();
  loadArtistNames();

  // Autocomplete on live inputs only
  createAutocomplete($('#srcInput'));
  createAutocomplete($('#dstInput'));
  createAutocomplete($('#neighborInput'));

  // Live buttons
  $('#predictBtn').addEventListener('click', predictConnection);
  $('#neighborBtn').addEventListener('click', discoverNeighbors);

  // Enter key support
  $('#srcInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#dstInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#neighborInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') discoverNeighbors(); });

  // Auto-render preview cards with test data
  renderPreviewCards();
});
