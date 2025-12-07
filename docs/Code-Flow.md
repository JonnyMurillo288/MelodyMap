# Code Execution Flow: SixDegreesSpotify CLI

This document explains, step by step, what the code does when you run the CLI to find a collaboration path between two artists on Spotify.

It focuses on the flow through these key modules:
- CLI entrypoint: ./main.go
- Spotify API client: ./spotify/spotify.go
- Artist/track modeling and parsing: ./sixDegrees/artists.go, ./sixDegrees/tracks.go
- Breadth-first search (BFS) and enrichment: ./sixDegrees/bfs.go
- Weighted search scaffold (not used by CLI): ./sixDegrees/weightedSearch.go


## High-level sequence

1. Parse command-line flags: -start, -find, -depth, -verbose, -limit.
2. Ensure Spotify authorization, launching a local auth server and browser flow if needed.
3. Resolve the start and target artist objects via Spotify Search.
4. Optionally swap start/target so the less popular artist is used as the BFS source.
5. Fetch albums and tracks for the start artist, building track objects that include featured artists.
6. Run BFS over artists connected by features, lazily enriching newly found artists with their albums and tracks as needed.
7. When the target is found, reconstruct the path and print the connection steps and timings.


## Detailed flow

### 1) CLI flags and validation (./main.go)

- Flags:
  - -start (string, required): starting artist name.
  - -find (string, required): target artist name.
  - -depth (int, default -1): maximum BFS hop depth (-1 means unlimited).
  - -verbose (bool): extra logging.
  - -limit (int, default 5): used to control album parsing breadth during enrichment.
- If -start or -find is missing, the program prints usage and exits with status 1.


### 2) Spotify authorization bootstrap (ensureSpotifyAuth in ./main.go)

- Checks ./main/authConfig.txt exists (holds your Spotify app credentials). If missing, it tries to copy from ./main/authConfig.sample.json and informs you to edit the file.
- Validates ./main/authToken.txt using tokenValid:
  - Reads the stored token (spotify.Auth), verifies access token and expiry (accepts RFC3339/RFC3339Nano), and ensures it won’t expire within 1 minute.
- If not valid, it starts the local auth server:
  - Spawns go run ./main/auth.go.
  - Polls http://localhost:8392/ for up to 10 seconds to ensure the server is up.
  - Attempts to open the browser (xdg-open) pointing to the local auth page.
  - Waits up to 2 minutes for ./main/authToken.txt to be created/updated with a valid token.
- On success, the rest of the program can call Spotify APIs.

Note: The Spotify client module (./spotify/spotify.go) includes its own token loader (loadOrObtainToken) and may also trigger the auth flow on first API request if a valid token is not present.


### 3) Artist resolution (sixDegrees.InputArtist in ./sixDegrees/artists.go)

- Creates an Artists struct with default fields (Name, Tracks, popularity metrics, Genres map).
- Calls spotify.SearchArtist(name), which performs GET https://api.spotify.com/v1/search with type=artist.
- Parses the response, takes the first artist result, and populates:
  - ID (Spotify ID)
  - Name (normalized to Spotify’s canonical name)
  - Popularity (float)
  - Genres (as a frequency map)
- If no result or parse error, the Artists object remains a placeholder with just Name.


### 4) Popularity-based source normalization (./main.go)

- If the start artist is more popular than the target, the code swaps them and records switchingArtist = true to later flip the output. This heuristic often produces shorter search paths by expanding from the less popular side first.


### 5) Build the start artist’s track list (./main.go + sixDegrees/tracks.go)

- Fetch albums for the starting artist:
  - Intended: spotify.ArtistAlbums(startArtist.ID, 15) to aggregate up to 15 albums/singles.
  - Albums response is parsed by startArtist.ParseAlbums, which:
    - JSON-decodes { items: [ { id, artists: [{ name }, …] } ] }.
    - Skips albums where any listed artist is "Various Artists" (to reduce compilation noise).
    - Returns a list of album IDs.
- For each album ID:
  - Calls spotify.GetAlbumTracks(albumID), which paginates and aggregates all tracks for that album.
  - Calls startArtist.CreateTracks(tracksJSON, helper) to convert raw JSON into []Track:
    - Each Track has: Artist (primary), Name, PhotoURL (unused in this path), ID, and Featured ([]*Artists).
    - For each contributing artist on the track other than the primary artist, CreateTracks:
      - Reuses an existing Artists from Helper.ArtistMap if present, otherwise loads it via InputArtist and stores it in ArtistMap.
    - Returns the newly created Track slice, which is appended to startArtist.Tracks.

Note: In ./main.go, the call is spotify.ArtistAlbums(startID, 15) where startID is empty and not set. The intended call appears to be spotify.ArtistAlbums(startArtist.ID, 15). If startID remains empty, this call will fail; in practice, it should be changed to use startArtist.ID.


### 6) BFS over collaboration graph (sixDegrees.RunSearchOpts in ./sixDegrees/bfs.go)

- Initializes Helper, which tracks:
  - ArtistMap: map of artist name to *Artists (visited/known artists)
  - DistTo: hop count from the start
  - Prev: predecessor chain for path reconstruction
  - Evidence: connecting track name for each edge Prev[x] -> x
- Initializes a priority queue of artists (ArtistQueue) ordered by higher popularity first (Less returns aq[i].Popularity > aq[j].Popularity) and pushes the start artist.
- visited map[string]bool marks which artists have been enqueued.
- Main loop:
  - Pop the next artist (current) from the queue.
  - If maxDepth is set (>= 0) and current’s depth equals/exceeds maxDepth, skip expanding it.
  - For each track of current:
    - Direct hit: if tr.Artist.Name == target.Name
      - Record Prev[target.Name] = current.Name, Evidence[target.Name] = tr.Name, found = true, break.
    - For each featured artist feat on the track:
      - Skip empty names and self-edges.
      - If feat was already visited, continue.
      - Mark visited, set Prev[feat] = current, Evidence[feat] = tr.Name, DistTo[feat] = DistTo[current] + 1, ArtistMap[feat] = feat.
      - Enrich the featured artist (first time seen):
        - enrichArtist(feat, h, targetName, &found, verbose, limit)
        - If feat has no Tracks yet, fetches up to 5 albums via spotify.ArtistAlbums(feat.ID, 5), then for each (capped at 5-6 due to index check):
          - fetchAlbumTracksCached uses an in-memory albumCache map[string][]byte to avoid duplicate album track requests across the run.
          - CreateTracks to populate feat.Tracks and add collaborators into Helper.ArtistMap.
        - After each album fetch, hasTarget(feat, targetName) checks whether any of feat’s tracks involve the target (either primary or featured); if so, set found = true.
        - Sleeps 300ms between artists to be gentle on rate limits.
      - If target is found during/after enrichment via hasTarget, set Prev[target] = feat.Name and found = true.
      - Push feat into the priority queue for further expansion.
- If a target connection is found, returns the Helper, reconstructed path, and ok=true. Otherwise returns ok=false.


### 7) Path reconstruction and output (./main.go + sixDegrees/bfs.go)

- ReconstructPath(start, target) walks Helper.Prev from target back to start and then reverses the list.
- If switchingArtist was set earlier, the path is reversed once more for display.
- Prints a numbered list where each step includes the evidence track if available:
  - i. From —[Track Name]→ To
- Prints analysis time in seconds and exits.


## Data structures and helpers

- sixDegrees.Artists
  - Name, ID
  - Tracks []Track
  - Popularity (float64)
  - PopularityKeys, NumFeatKeys []int (not used in the main flow)
  - Genres map[string]int

- sixDegrees.Track
  - Artist *Artists (primary artist)
  - Name, PhotoURL, ID
  - Featured []*Artists (collaborators on the track)

- sixDegrees.Helper
  - ArtistMap map[string]*Artists
  - DistTo map[string]int
  - Prev map[string]string
  - Evidence map[string]string

- sixDegrees.albumCache
  - Global in-memory cache: map[albumID]rawTrackJSON to avoid re-fetching the same album’s tracks across enrichments.

- Spotify client (./spotify/spotify.go)
  - doRequest: constructs the HTTP request with headers/query and delegates to fetchWithRetry.
  - fetchWithRetry: retries on network errors and 5xx with exponential backoff; honors Retry-After on 429.
  - SearchArtist: GET /v1/search with type=artist.
  - ArtistAlbums: GET /v1/artists/{id}/albums with pagination, aggregates items up to the requested limit.
  - GetAlbumTracks: GET /v1/albums/{id}/tracks with pagination, aggregates all tracks.
  - Auth helpers: loadOrObtainToken, launchAuthFlow, isExpired, plus convenience getHeader.


## Weighted search (optional, not used by CLI)

- sixDegrees/weightedSearch.go provides Dijkstra’s algorithm scaffolding with pluggable WeightStrategy implementations (e.g., PopularityDiffStrategy, CollabStrengthStrategy) and a Graph structure.
- This is currently not invoked by the CLI path but can be used to implement shortest "weighted" paths instead of unweighted BFS.


## Notes and limitations

- Artist search chooses the first Spotify result, which may not match the intended artist for ambiguous names.
- Compilations credited to "Various Artists" are skipped when building album lists.
- BFS can be broad; API limits are mitigated with small sleeps and client-level retries.
- Known quirk in ./main.go: spotify.ArtistAlbums is called with startID (never assigned) instead of startArtist.ID. For the intended behavior, use startArtist.ID.
