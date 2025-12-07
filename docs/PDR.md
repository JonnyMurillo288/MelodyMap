# SixDegreesSpotify — Product Design Requirements (PDR)

Version: 0.1
Status: Draft
Owner: Repository maintainers
Last updated: 2025-09-21


## 1. Background and Objective
SixDegreesSpotify is a tool that discovers relationships between two musical artists using Spotify data, inspired by the "six degrees" concept. Given a starting artist and a target artist, the system builds a collaboration graph (e.g., shared tracks/albums) and finds a path between them using graph search (BFS for unweighted shortest path and Dijkstra for weighted searches).

The objective of this PDR is to define product scope, requirements, system architecture, data models, algorithms, and quality criteria to guide implementation and validation.


## 2. Scope
- In scope
  - Command-line interface to accept a start artist and a target artist.
  - Spotify integration to fetch artist albums and album tracks.
  - Graph construction where vertices are artists and edges represent collaborations on tracks.
  - Search algorithms for shortest paths (BFS) and weighted paths (Dijkstra/heuristics).
  - Basic HTML templates exist and may be used for a basic UI, but primary focus is CLI.
  - Unit tests for core graph and search logic.

- Out of scope (for this phase)
  - Full-featured web application with login/session management.
  - Persistent database storage and background job queues.
  - Production-grade caching and distributed rate-limit handling.
  - Mobile apps.


## 3. Personas and Use Cases
- Personas
  - Music enthusiasts: Curious about how two artists are connected.
  - Developers/data enthusiasts: Interested in graph-based exploration using Spotify data.

- Primary Use Cases
  - UC1: Find an unweighted shortest path between Artist A and Artist B.
  - UC2: Find a weighted path between Artist A and Artist B prioritizing stronger collaborations (e.g., direct track collaborator vs. tenuous connections).
  - UC3: Display the path with intermediate artists and the tracks/edges that connect them.


## 4. Requirements
- Functional Requirements (FR)
  - FR1: Accept start and target artist names via CLI flags.
  - FR2: Resolve artist names to Spotify Artist objects (handle ambiguous names when possible).
  - FR3: Retrieve albums for the start artist and tracks from those albums.
  - FR4: Identify collaborating artists based on track credits and create edges accordingly.
  - FR5: Construct an in-memory graph with artist nodes and collaboration edges.
  - FR6: Provide BFS-based shortest path search between start and target.
  - FR7: Provide weighted search (Dijkstra) with configurable heuristics.
  - FR8: Output a human-readable path and/or step-by-step list of artists and connecting tracks.
  - FR9: Handle cases where no path is found with a clear error message.
  - FR10: Respect Spotify API limits and paginate through results as needed.

- Non-Functional Requirements (NFR)
  - NFR1: Performance: For typical artists, find paths within ~5–15 seconds on a broadband connection.
  - NFR2: Reliability: Avoid crashes; fail gracefully on API errors.
  - NFR3: Maintainability: Code organized into clear packages (spotify, sixDegrees, main) with tests.
  - NFR4: Testability: Unit tests for graph operations and search algorithms.
  - NFR5: Security: Do not commit client secrets or tokens; store secrets in local files ignored by VCS.
  - NFR6: Observability: Log high-level progress and errors.

- CLI Requirements
  - CLI1: Flags: -start "<artist>" and -find "<artist>" are required.
  - CLI2: Exit with code 1 and an informative message if flags are missing or invalid.
  - CLI3: Provide optional flags (future): -limit, -depth, -weighted, -verbose.

- API/Integration Requirements
  - API1: OAuth authorization code flow to obtain and cache access tokens.
  - API2: Use Spotify endpoints for artist albums and album tracks.
  - API3: Handle pagination (limit/offset) for albums and tracks; do not assume fixed limits.
  - API4: Back-off on 429 responses; respect rate-limit headers.


## 5. System Architecture Overview
- Components
  - main: CLI entry point; parses flags; orchestrates search.
  - spotify package: Minimal client wrappers for Spotify API (auth, ArtistAlbums, GetAlbumTracks, etc.).
  - sixDegrees package: Domain models (Artist, Track), graph structures (Graph, Edge), and search algorithms (BFS, Dijkstra/weighted search), helpers.
  - templates: Basic HTML templates that can be used for presenting results in a browser.

- High-Level Flow (CLI)
  1) Parse flags (-start, -find). Validate inputs.
  2) Resolve start artist and target artist to internal Artist objects (InputArtist).
  3) Fetch start artist's albums (ArtistAlbums) and tracks for each album (GetAlbumTracks).
  4) Parse tracks to collect collaborating artists and build the initial graph nodes and edges.
  5) Expand the graph as needed by exploring neighbors (per algorithm strategy).
  6) Run search (RunSearch/BFS or Dijkstra) from start to target.
  7) Output the path and distances/weights.


## 6. Data Model (Conceptual)
- Artist
  - Fields: ID (Spotify), Name, Albums[], Tracks[], Collaborators[]
  - Methods: ParseAlbums(), CreateTracks()

- Track
  - Fields: ID, Name, Artists[] (featuring), AlbumID, Popularity, ReleaseDate

- Graph
  - Fields: Vertices map[ArtistID]int (indexing), Keys []ArtistID (reverse), Adjacency list of edges
  - Methods: AddEdge(), Neighbors()

- Edge
  - Fields: From, To (vertex indices), Weight (collab strength or cost), Evidence (track references)

- SearchHelper/State
  - EdgeTo: map[ArtistID][]*Artist (or path-back pointers)
  - ArtistMap: map[ArtistName]*Artist (for quick lookup)

- Dijkstra/BFS
  - DistTo: map[Vertex]float64 or int
  - EdgeTo: map[Vertex]Edge

Note: The exact field names/types should match sixDegrees package; this conceptual model guides interfaces and invariants.


## 7. Algorithms
- BFS (Unweighted shortest path)
  - Use when all edges are considered equal (any collaboration counts the same).
  - Guarantees the minimum number of hops between start and target.

- Dijkstra (Weighted path)
  - Use when edges have different costs. Lower cost indicates stronger/shorter connection.
  - Potential weight heuristics:
    - Inverse of collaboration strength (e.g., 1 / number of shared tracks).
    - Penalties for loose associations (e.g., compilation appearances).
    - Freshness bias (recent tracks weighted lower cost).

- WeightedSearch implementation should support pluggable weighting strategies for experimentation.


## 8. Spotify Integration
- Auth Flow
  - Run: go run ./main/auth.go
  - Local callback: http://localhost:8392 (per README)
  - Store auth code and token in main/authConfig.txt and main/authToken.txt (local files; not committed)

- Endpoints
  - Get artist by name/search (implicit via InputArtist).
  - Get artist albums: /v1/artists/{id}/albums (with market, include_groups, limit, offset; paginate until complete or limit reached).
  - Get album tracks: /v1/albums/{id}/tracks (limit, offset; paginate).

- Constraints and Considerations
  - Rate limits: Respect Retry-After on 429 responses; exponential backoff.
  - Pagination: Never assume a fixed limit (e.g., 15); consider dynamic paging up to configured max.
  - Data quality: Some tracks list many artists; deduplicate edges and avoid self-loops.


## 9. Error Handling and Edge Cases
- Invalid or ambiguous artist names; zero results.
- Network errors, timeouts, 4xx/5xx responses from Spotify.
- Empty album or track lists.
- Cycles in the graph; ensure visited sets prevent infinite loops.
- No path found between start and target: return clear message and exit code 1.
- Partial graph due to pagination stop or API errors; communicate limitations.


## 10. Security and Privacy
- Never commit client secrets, auth codes, or tokens to VCS.
- Store secrets in local files ignored by .gitignore; optionally support environment variables.
- Bind local server only to localhost; use random state parameter in OAuth flow.
- Avoid logging sensitive data (tokens, raw headers).


## 11. Logging and Telemetry
- Log progress at INFO level: start/target, counts of albums/tracks fetched, queue sizes, depth explored.
- Log warnings on API backoffs, partial results, or retries.
- Log errors on fatal failures; include context and suggestion.
- Optional: structured logs (JSON) controlled by a -verbose flag.


## 12. Testing Strategy
- Unit tests
  - Graph operations: AddEdge, Neighbors, DistTo updates.
  - BFS: correctness on known small graphs.
  - Dijkstra/WeightedSearch: correctness and stability on synthetic graphs.
  - Parsing: album/track parsing to collaborators list.

- Integration tests (optional)
  - Mock Spotify client to avoid live API calls.

- Test data
  - Small fixture graphs and sample JSON payloads.


## 13. Performance and Scalability
- Optimize API usage: batch requests, limit scope to relevant albums (e.g., albums where artist is primary).
- Caching layer (optional): cache album/track lists per artist during a run; optional on-disk cache.
- Graph expansion strategy: iterative deepening with cutoffs to avoid combinatorial explosion.
- Parallelization: bounded worker pool for fetching album tracks, respecting rate limits.


## 14. Configuration and Secrets Management
- Config file or env vars for:
  - Spotify client ID/secret, redirect URL, scopes
  - API request timeouts and retry policy
  - Max albums/tracks per artist to fetch
  - Search strategy options (weighted/unweighted, max depth)


## 15. Deployment and Operations
- Primary mode: local CLI.
- Optional local web demo using templates/ for results rendering.
- Requirements: Go toolchain, network access to Spotify API.


## 16. Milestones and Deliverables
- M1: Robust CLI with BFS path search and clear output.
- M2: Weighted search (Dijkstra) with a default heuristic.
- M3: Improved error handling, retries, and pagination.
- M4: Tests covering graph/search and parsers; CI configuration.
- M5: Optional simple web UI to show path.


## 17. Acceptance Criteria
- Given valid -start and -find names that exist on Spotify, the program returns a path or a clear "no path" message within a reasonable time.
- BFS path length is minimal in hops on constructed graph.
- Weighted search produces reasonable paths reflecting collaboration strength.
- Program handles API pagination and does not crash on 429 responses (backs off and retries up to a limit).
- Secrets are not logged or stored in VCS.


## 18. Known Gaps and Open Questions
- main.go currently expects string values for -start and -find; README examples should reflect usage: `go run main.go -start "Artist A" -find "Artist B"`.
- Dijkstra implementation and edge weights: finalize and document weight function.
- Graph expansion breadth: do we explore only from start artist’s albums or expand via neighbors’ albums as well? Define depth limits.
- Ambiguous artist names resolution: how to disambiguate (by popularity, followers, or prompt)?
- Pagination policy: current code uses a static album limit (e.g., 15); should be configurable and paginated.
- Output formatting: define a stable, human-readable summary and an optional JSON format for programmatic use.


## 19. References
- Spotify Web API: https://developer.spotify.com/documentation/web-api
- Graph theory basics: BFS, Dijkstra’s Algorithm
- Project structure: packages `sixDegrees/`, `spotify/`, CLI in `main.go`, templates in `templates/`.
