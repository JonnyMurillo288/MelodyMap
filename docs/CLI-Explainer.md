# CLI Explainer: `go run main.go`

This document explains what the root-level CLI program does when you run:

- `go run main.go -start "Artist A" -find "Artist B" [-depth N] [-verbose]`

It computes a path of collaborations between two artists on Spotify (a “six degrees” style connection), using featured appearances on tracks as edges in a graph.


## Quickstart

1. Ensure Go is installed and `go run` works on your system.
2. Create a Spotify Developer App to obtain a Client ID and Client Secret.
3. Run the CLI:
   - `go run main.go -start "Taylor Swift" -find "Adele" -depth 3 -verbose`
4. The first run will prompt you to authorize with Spotify in your browser. After you approve, the program searches for a connection and prints the path.


## Command-line flags

- `-start` (required): Name of the starting artist.
- `-find` (required): Name of the target artist to connect to.
- `-depth` (optional): Maximum breadth-first search (BFS) depth in hops.
  - Use `-1` (default) for unlimited depth.
- `-verbose` (optional): Enables verbose logging to stdout, showing search progress and API activity.

If required flags are missing, the program prints usage and exits with status 1.


## What happens step-by-step

1. Parse flags and validate input
   - If `-start` or `-find` is missing, usage is printed and the program exits with code 1.

2. Ensure Spotify authorization
   - It checks for `./main/authConfig.txt` (OAuth client settings). If missing, it tries to bootstrap from `./main/authConfig.sample.json` into `./main/authConfig.txt` and then exits with an instruction to fill in your credentials.
   - It checks for a valid token in `./main/authToken.txt`. If missing or expired:
     - Launches the local auth server: `go run ./main/auth.go`
     - Waits for `http://localhost:8392/` to be reachable
     - Opens your browser to authorize
     - Waits for a valid token to be written to `./main/authToken.txt`

3. Resolve artists via Spotify Search
   - For both `-start` and `-find`, it queries Spotify’s Search API and takes the first matching artist result.
   - Populates the artist’s ID, popularity, and genres (stored internally), and logs the normalized artist name it will use.

4. Fetch albums and tracks for the starting artist
   - Calls Spotify’s Artist Albums API and aggregates up to 15 albums/singles.
   - Parses the album list and ignores compilations credited to "Various Artists".
   - For each album, fetches its tracks and builds Track objects.
   - Track objects include the primary artist and any featured artists (the collaborators that define graph edges).

5. Run the BFS collaboration search
   - A BFS queue starts at the `-start` artist with distance 0.
   - For each artist dequeued, the program explores all their tracks.
   - For every featured artist discovered on a track:
     - Records the predecessor chain and the track name that connected them (for reconstruction and readable output).
     - Lazily enriches that featured artist by fetching some of their albums/tracks the first time they are seen (to expand the graph further on demand). This is rate-limited with a short sleep to respect Spotify API limits.
     - If the featured artist is the target (or later yields the target), the search stops and reconstructs the path from start → target.
   - If `-depth` is non-negative, artists at or beyond the maximum hop count are not expanded further.

6. Output
   - If a path is found, prints a numbered list of steps like:
     - `1. Artist A —[Track Name]→ Artist B`
     - `2. Artist B —[Another Track]→ Artist C`
     - ... until the target artist.
   - If no path is found (within the given depth, if provided), prints a message and exits with code 0.


## Files involved

- CLI entrypoint: `./main.go`
- Spotify API client: `./spotify/spotify.go`
- Artist/track modeling and parsing: `./sixDegrees/artists.go`, `./sixDegrees/tracks.go`
- BFS search and path reconstruction: `./sixDegrees/bfs.go`
- Local OAuth server: `./main/auth.go`


## Data stored on disk

- `./main/authConfig.txt`
  - JSON with your Spotify OAuth credentials (client ID/secret, redirect URL, scopes).
  - Initially created from `./main/authConfig.sample.json` if missing; you must edit it with your real credentials.
- `./main/authToken.txt`
  - JSON with your access token, refresh token (if granted), type, and expiry timestamp.
  - Automatically created by the auth server after you approve in the browser.


## Exit codes and logging

- Exit code 1: missing flags or fatal errors (e.g., unable to authorize, artist not found).
- Exit code 0: no path found between the artists (a normal, handled outcome).
- Verbose mode prints detailed progress for album/track fetches and BFS expansion.


## Notes on API usage and rate limits

- The Spotify client includes retry logic with exponential backoff and honors `Retry-After` on HTTP 429.
- BFS introduces a small delay when enriching newly discovered artists to avoid hitting rate limits aggressively.
- Deep or unbounded searches can take time and may be constrained by rate limits.


## Known limitations

- Artist disambiguation: the program selects the first Spotify search result for each name, which may not always be the desired artist.
- Graph edges are based on featured appearances; solo tracks without features do not add new edges.
- Compilations from "Various Artists" are skipped to reduce noise.
- Unlimited depth (`-depth -1`) can explore a large portion of the collaboration graph and take a long time.


## Examples

- Basic:
  - `go run main.go -start "Artist A" -find "Artist B"`
- With depth limit and verbose logging:
  - `go run main.go -start "Kendrick Lamar" -find "Eminem" -depth 4 -verbose`


## Troubleshooting

- "created ./main/authConfig.txt from sample; edit it with your Spotify credentials and re-run"
  - Open `./main/authConfig.txt`, paste your Spotify client credentials, ensure the redirect URL matches `http://localhost:8392/auth`, then re-run the CLI.
- "authorization server did not start on http://localhost:8392"
  - Try running `go run ./main/auth.go` directly and inspect its output. Ensure nothing else is using port 8392.
- Browser didn’t open automatically
  - Visit `http://localhost:8392/` manually to start authorization.
- Token issues
  - Delete `./main/authToken.txt` and re-run to force a fresh authorization.


## Internals and extensibility

- The BFS-based search used by the CLI is implemented in `sixDegrees/bfs.go`.
- There is also a weighted search scaffold (`sixDegrees/weightedSearch.go`) implementing Dijkstra’s algorithm and strategies, which the CLI does not currently invoke but can be extended to use for more nuanced path scoring.

