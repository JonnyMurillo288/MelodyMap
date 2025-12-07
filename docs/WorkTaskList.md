# SixDegreesSpotify — PDR-Derived Work Task List and Implementation Plan

Version: planning v1  
Scope: Align codebase with PDR v0.1 and fill gaps to reach M1–M5 milestones

---

## 0) Snapshot: Current State vs PDR

Observed in codebase:
- CLI exists (main.go) with `-start` and `-find` flags, but has build issues and ad-hoc output.
- Spotify integration present with basic endpoints but lacks pagination, retries, and proper 429 handling.
- Graph and weighted search (Dijkstra) implemented with basic popularity-difference weights; decent set of unit tests for weighted path.
- BFS is implemented but mixes network fetching and search logic, lacks clear path reconstruction, depth limits, and structured output.
- Auth flow provided via `main/auth.go`; secrets stored in local files.
- Tests exist but mostly for weighted search and a small integration-like test; BFS/core graph tests are limited/not enabled.
- Templates exist but not integrated (optional UI).
- README is minimal and mismatched with CLI usage.

Key gaps vs PDR:
- FR1–FR10: CLI validation/error codes, robust graph building, path output, pagination, rate limiting not fully addressed.
- NFRs: Logging, reliability, test coverage, maintainability need improvement.
- Weighted search: needs pluggable heuristics, better edge evidence modeling.
- Output formatting and optional JSON not implemented.
- Config/secrets management and .gitignore hygiene not finalized.
- Acceptance criteria around performance/backoff not demonstrably met.

---

## 1) Milestones Overview (From PDR)

- M1: Robust CLI with BFS path search and clear output.
- M2: Weighted search (Dijkstra) with a default heuristic.
- M3: Improved error handling, retries, and pagination.
- M4: Tests covering graph/search and parsers; CI configuration.
- M5: Optional simple web UI to show path.

The work list below is structured to achieve these milestones in order, with dependencies.

---

## 2) Work Breakdown by Milestone

### M0: Project Hygiene and Build Stability (Pre-requisite)
- Fix build errors in main.go:
  - Remove invalid line `fmt.Println(g.Keys[dij.DistTo[]])`.
  - Ensure program returns appropriate exit codes and clear messages per CLI2.
  - Remove or guard debug prints.
- Add/review .gitignore:
  - Exclude `main/authConfig.txt`, `main/authToken.txt`, and any secrets.
  - Exclude test artifacts, coverage, and local bin directories.
- README cleanup:
  - Correct usage: `go run main.go -start "Artist A" -find "Artist B"`.
  - Explicit prerequisites (Go version, auth setup, required scopes).
- Create a “config.sample.json” or example env file for auth and app-level config.
- Add basic Makefile or task runner (optional) for `lint`, `test`, `run`, `auth`.

Deliverable: Builds cleanly; README aligns with CLI; secrets excluded from VCS.

---

### M1: CLI + Core BFS with Clear Output
- CLI:
  - Validate required flags `-start`, `-find`; exit code 1 with informative message if missing.
  - Optional flags scaffolding: `-limit`, `-depth`, `-weighted`, `-verbose`. Implement `-depth` and `-verbose` now; keep others as no-ops with TODO.
- Artist resolution:
  - On ambiguous names, select top result by popularity by default and log a warning (consider `-interactive` later).
- Graph construction approach for BFS:
  - Define an internal data model to capture edges with “evidence” (track references).
  - Avoid mixing BFS traversal logic with network calls where possible. Introduce an interface for Spotify client to allow mocking.
  - Implement visited sets and proper queue handling.
  - Implement path reconstruction to target with a predecessor map; avoid only building reverse adjacency as currently done.
- BFS edge/evidence:
  - Use track collaborators to form edges; deduplicate and avoid self-loops.
  - Capture references: track ID/name and album if available.
- Output:
  - Human-readable path:
    - Example: `Artist A —[Track T1 (YYYY)]→ Artist B —[Track T2]→ Artist C`
  - On no path: return clear message, exit code 1.
- Logging:
  - `-verbose` toggles INFO-level logs: counts fetched, queue sizes, explored depth.

Deliverable: End-to-end CLI returns an unweighted path or a clear “no path” result with informative logs; meets FR1, FR3–FR6, FR8–FR9 basics.

Example usage:
```bash
go run main.go -start "Eminem" -find "Taylor Swift" -depth 4 -verbose
```

---

### M2: Weighted Search with Pluggable Heuristics
- Weight strategy interface:
  - Define `type WeightStrategy interface { Weight(from, to *Artists, edge EdgeMetadata) float64 }`.
  - Provide default strategy:
    - Base on inverse of collaboration strength (1 / number of shared tracks).
    - Optionally add freshness bias (recent tracks reduce cost).
    - Optional penalty for compilation-only associations.
- Graph population for weighted search:
  - Ensure edges carry metadata: sharedTracks, release dates, isCompilation.
  - Dijkstra uses weights from `WeightStrategy`.
- CLI integration:
  - `-weighted` flag switches to weighted mode with default strategy.
  - `-strategy=<name>` optional for future.
- Path output:
  - Show total “cost�� with explanation of metric.

Deliverable: Weighted path search returns expected “stronger” connection paths; meets FR7, parts of FR8.

Illustrative interface:
```go
type EdgeMetadata struct {
  SharedTracks []TrackRef // {ID, Name, ReleaseDate, AlbumID}
  IsCompilation bool
  RecencyScore  float64
}
```

---

### M3: Robust Spotify Integration: Pagination, Retries, Rate Limits
- Pagination:
  - Implement full pagination for `/artists/{id}/albums` and `/albums/{id}/tracks`.
  - Make page size configurable; do not assume fixed limits.
- Rate limiting and backoff:
  - On 429, parse Retry-After and sleep; implement exponential backoff with jitter.
  - Add retry policy for transient 5xx/timeout network errors with caps.
- Timeouts:
  - Use `http.Client` with context and sensible timeouts.
- Market/include_groups parameters:
  - Ensure albums endpoint honors `market` and `include_groups` per config.
- Refactor dynamic JSON parsing:
  - Introduce typed structs for Spotify responses; reduce reliance on `interface{}` and fragile type switches.
- Partial-result handling:
  - If pagination/tracks incomplete due to retry limits, log warnings and proceed; mark partial graph.

Deliverable: Compliance with API requirements and resilience to rate limits; meets FR10, API1–API4.

---

### M4: Testing Strategy + CI
- Unit tests:
  - Graph operations: `AddEdge`, `Neighbors`, path reconstruction, deduplication.
  - BFS: correctness on synthetic graphs; path length minimality.
  - Weighted: additional tests for multiple strategies and metadata impacts.
  - Parsing: album/track parsing covers edge cases (Various Artists, empty lists).
- Integration tests:
  - Mock Spotify client interface; deterministic fixtures for albums/tracks responses.
- Test data:
  - JSON fixtures for albums/tracks.
- CI:
  - GitHub Actions workflow: `go test ./...` and `go vet ./...`.
  - Optional lint (golangci-lint) and coverage thresholds.

Deliverable: Reliable, automated tests and CI pipeline; meets NFR3–NFR4, parts of NFR2.

---

### M5: Optional Simple Web UI
- Minimal HTTP server to render path using templates in `templates/`.
- Routes:
  - GET form for start/target; POST triggers search; render results.
- Share code between CLI and web layer for core logic; avoid duplication.
- Security:
  - Bind to localhost; no sessions; no secrets in responses/logs.

Deliverable: Basic web demo showcasing paths; respects PDR scope constraints.

---

## 3) Detailed Task List (Backlog Items)

1) CLI and Program Structure
- [ ] Validate `-start` and `-find`; structured error and exit code 1.
- [ ] Add optional flags: `-depth`, `-verbose`; stub `-weighted`, `-limit`.
- [ ] Centralize output formatting; implement JSON output flag `-json` (optional per PDR 18 note).

2) Artist Resolution and Data Modeling
- [ ] Implement disambiguation policy (top popularity) and log on ambiguity.
- [ ] Extend Artist and Edge to carry metadata required by weighted strategies and output.
- [ ] Avoid storing secrets or sensitive fields on Artist in logs.

3) BFS Implementation
- [ ] Separate fetch-expansion logic from BFS traversal; introduce interfaces for data retrieval.
- [ ] Implement visited set and predecessor map with proper reconstruction:
  ```go
  prev := map[ArtistID]ArtistID
  ```
- [ ] Deduplicate edges; avoid self-loops.
- [ ] Depth limit support via `-depth`.
- [ ] Return “no path” with exit code 1 and reason.

4) Weighted Search (Dijkstra)
- [ ] Implement WeightStrategy and default strategy.
- [ ] Populate edge metadata during graph construction.
- [ ] Path reconstruction and total cost display.

5) Spotify Client Enhancements
- [ ] Typed response models for search, albums, tracks.
- [ ] Pagination for albums and tracks with configurable limits.
- [ ] Retry/backoff on 429 with `Retry-After`; exponential backoff on transient failures.
- [ ] Context timeouts and cancellation.
- [ ] Configurable parameters (market, include_groups).

6) Logging and Observability
- [ ] Structured logs (key/value) at INFO level.
- [ ] `-verbose` toggles debug detail (queue sizes, depths, counts).
- [ ] Summaries: number of albums/tracks fetched, nodes/edges, search time.

7) Error Handling and Edge Cases
- [ ] Clear messages for invalid artist names and zero results.
- [ ] Handle empty album or track responses.
- [ ] Cycle safety and visited checks.
- [ ] Partial graph warnings when fetch incomplete.
- [ ] Graceful handling of network errors/timeouts.

8) Configuration and Secrets
- [ ] Load config from env or file; sample config committed; real vars ignored.
- [ ] Ensure `main/auth*.txt` ignored by VCS.
- [ ] Document required scopes and redirect URL.

9) Testing
- [ ] Expand unit tests to cover BFS correctness and parsing.
- [ ] Mock Spotify client for integration-like tests without live API.
- [ ] Add fixtures for albums and tracks payloads.
- [ ] Coverage gates in CI.

10) Documentation
- [ ] Update README: setup, auth flow, CLI usage, examples, flags.
- [ ] Contribute a “Design Notes” doc describing weight strategies and graph expansion trade-offs.
- [ ] Add “Known limitations” section (e.g., ambiguous artist handling).

11) Optional Web UI
- [ ] Minimal server and routes; reuse core logic.
- [ ] Display path with track evidence; add loading template if long-running.
- [ ] Security hygiene (localhost binding only).

---

## 4) Traceability: Requirements → Tasks

- FR1–FR2: CLI flags, artist resolution → M1.1–M1.2
- FR3–FR5: Albums/tracks fetch, graph edges → M1.3, M3.1
- FR6: BFS path → M1.3
- FR7: Dijkstra weighted → M2 tasks
- FR8–FR9: Output path/no-path → M1.4
- FR10, API1–API4: Pagination/backoff → M3 tasks
- NFR1–NFR6: Performance, reliability, maintainability, testability, security, observability → M3, M4, M0, M6

---

## 5) Success Criteria and Metrics

- Functional:
  - Given valid `-start` and `-find`, program returns a path or “no path” within 5–15s for typical cases.
  - BFS path has minimal hops; proven on synthetic graphs via tests.
  - Weighted search reflect stronger collaborations; unit tests validate expected weight sums and chosen edges.
- API Resilience:
  - Handles pagination to completion or logs partial with retries and backoff; no crashes on 429s.
- Quality:
  - Tests: >80% coverage on sixDegrees and spotify packages (excluding auth).
  - CI: All tests pass on PR; lint checks clean.
- Security:
  - No secrets in VCS; verified by repo grep; logs avoid sensitive info.

---

## 6) Open Questions and Assumptions

Open questions (from PDR and code review):
- Should graph expansion explore neighbors’ albums beyond start artist immediately, or use iterative deepening with depth cutoffs? Default depth?
- How to disambiguate artist names beyond “top popularity”? Offer `-artist-id` override?
- Weight strategy defaults: What exact coefficients for collaboration count vs recency?
- Should we include features like producers/remixers in “collaboration,” or strictly appearing artists?
- Output: include JSON format flag now or later?
- Performance: acceptable max albums/tracks per artist default?

Assumptions:
- Primary mode remains CLI; web UI is optional, demo-only.
- For ambiguous names, top popularity is acceptable default for now.
- Collaboration defined as co-appearance in track “artists” array; producers not included unless in API-provided artist list.

---

## 7) Risks and Mitigations

- Risk: Hitting rate limits during broad searches.
  - Mitigation: Backoff, configurable limits, depth limit defaults, caching.
- Risk: Ambiguous artist name causing wrong graph root.
  - Mitigation: log warning and support future `-artist-id`.
- Risk: API changes or unexpected payloads break parsing.
  - Mitigation: typed models, robust validation, tests with fixtures.
- Risk: Long runtimes on highly connected artists.
  - Mitigation: depth limits, heuristics to prioritize stronger neighbors, concurrency with bounded worker pools.

---

## 8) Suggested Implementation Sequencing

1) M0 hygiene and README updates.
2) M1 CLI/BFS with clean output and path reconstruction.
3) M3 Spotify client pagination/backoff refactor (safe to do now; supports both BFS and Dijkstra).
4) M2 weighted search with default strategy and edge metadata.
5) M4 tests and CI; increase coverage.
6) M5 optional web UI.

---

## 9) Example Interfaces (Illustrative)

Weight strategy:
```go
type WeightStrategy interface {
  Weight(from, to *sixdegrees.Artists, meta EdgeMetadata) float64
}

type DefaultWeight struct {
  RecencyBias float64 // 0..1
}

func (d DefaultWeight) Weight(from, to *sixdegrees.Artists, meta EdgeMetadata) float64 {
  strength := float64(len(meta.SharedTracks))
  if strength == 0 {
    return 10 // high penalty for weak ties
  }
  freshness := 1.0
  if meta.RecencyScore > 0 {
    freshness = 1.0 - d.RecencyBias*meta.RecencyScore
  }
  penalty := 1.0
  if meta.IsCompilation {
    penalty += 0.5
  }
  return (1.0/strength) * penalty * freshness
}
```

CLI flags (sketch):
```go
var (
  start    = flag.String("start", "", "Starting artist")
  find     = flag.String("find", "", "Target artist")
  depth    = flag.Int("depth", 4, "Max BFS depth")
  weighted = flag.Bool("weighted", false, "Use weighted search")
  verbose  = flag.Bool("verbose", false, "Verbose logging")
)
```

---

This plan enumerates all major tasks to meet the PDR across M1–M5. Implementing tasks in the sequence above will ensure no critical requirements are missed and provides measurable milestones to validate progress and quality.
