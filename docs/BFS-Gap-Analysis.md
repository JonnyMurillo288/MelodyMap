# BFS Module: Expected Behavior vs Current Implementation (Gap Analysis)

Scope
- File: bfs.go (package main)
- Purpose: Traverse an artist graph via track features to find a shortest connection path between two artists. Integrates with DB (Store) and Spotify API to fetch tracks.

## What the BFS Should Do (Product/Engineering Requirements)

1) Correct Shortest-Path Search (BFS)
- Use a FIFO queue to guarantee minimal hop-count paths in an unweighted graph.
- Maintain a visited set for artists to avoid cycles and redundant work.
- Set DistTo and Prev only upon first discovery of a node (ensures minimality and stable reconstruction).

2) Clear Interfaces and Separation of Concerns
- Core search should obtain neighbors (featured artists) via an injected provider function:
  - GetNeighbors(artistID) -> []Neighbor, where Neighbor includes child artist and edge metadata (track ID/name).
- Search core should not directly open DB connections or call the Spotify API; those belong to a provider layer.

3) Operational Controls and Observability
- Options to constrain the search: MaxDepth, MaxNodes, Timeout, EarlyExit callback.
- Progress callback for telemetry, plus basic metrics in the result (visited/expanded counts, duration, reason for termination).
- Deterministic traversal order at each depth; optional tiebreaker that does not violate BFS semantics.

4) Robust Offline/Online Modes and Caching
- Offline: use DB/cache only, never call remote APIs.
- Online: prefer DB cache, then API; write back to DB/cache as needed.
- Coherent, bounded caching strategy to avoid redundant work and unbounded memory growth.

5) Resource and Error Management
- Single, externally managed DB session/connection; migrations run at startup only.
- Clear error-handling policy (terminate vs continue) and surface termination reason and last error in the result.
- No global mutable state in core search (e.g., connection pointers, unbounded caches).

6) Clean Logging
- Use leveled logging gated by an option; avoid noisy fmt prints.

## What the BFS Currently Does

- Implements a popularity-based priority queue (max-heap) via ArtistQueue; this is best-first by popularity, not BFS by hop count.
- Enqueues featured artists discovered from the current artist’s tracks and populates Prev, DistTo, and Evidence for reconstruction.
- Queries DB for tracks for each popped artist and upserts tracks; records evidence as the track that links to a child artist.
- Uses hasTarget to check if any track or feature of the current artist matches the target; early-exits when found.
- Uses a visitedTracks map to avoid reprocessing the same track ID, but the artist visited set is commented out (disabled).
- Applies a partial maxDepth guard: skips exploration when h.DistTo[current.Name] >= maxDepth.

## Gaps and Issues

1) Not Actually BFS
- Expected: FIFO queue for minimal hop count.
- Current: Popularity-ordered heap; can return non-minimal paths or reorder depths.
- Impact: Fails BFS correctness and determinism by hop count.
- Status: IGNORE FOR NOW, KEEPING THIS AS FUTURE OPTION

2) Missing Artist-Level Visited Set
- Expected: visited[artistID or name] to prevent re-enqueue and cycles.
- Current: Only visitedTracks, artist-level visited is commented out.
- Impact: Repeated re-enqueue, larger search, potential overwrites of DistTo/Prev.
- Status: DONE

3) Path Minimality Not Guaranteed
- Expected: First discovery defines minimal DistTo and Prev.
- Current: Heap order can pop deeper nodes earlier; DistTo/Prev may be overwritten.
- Impact: Reconstructed path may not be shortest; evidence may be inconsistent.
- STATUS: MADE THE UPDATE, MAKING A MINOR CHANGE
  - KEPT IN THE POPULARITY, ONLY IF IT IS A TIE ON LENGTH FOR THE SEARCH PRIORITY
  - ONLY ASSIGN DISTTO AND PREV ON FIRST DISCOVERY INSTEAD OF ALL DISCOVERY


4) Tight Coupling to DB/API
- Expected: Injected neighbor provider; core independent of storage/API.
- Current: RunSearchOpts uses global storeConn and calls DB; enrichArtist opens its own DB connection and runs Migrate.
- Impact: Hard to test; runtime overhead; potential for resource leaks and contention.
- STATUS: THIS IS OKAY RIGHT NOW, WILL FIX AT THE END. 
  - POTENTIAL FOR OPTIMIZATION?

5) DB Connections and Migrations in Hot Path
- Expected: Single connection, migrations at startup only.
- Current: enrichArtist performs Open("") and Migrate per call.
- Impact: Severe performance cost; incorrect operational behavior. <- This may have been a huge issue before with time
- STATUS: THIS IS LIKE #4 ABOVE ^.
  - MADE THE DATABASE A POINTER FOR enrichArtist. One database connection

6) Inconsistent Offline Handling and Conditional Logic
- Expected: Offline forbids API; online prefers DB then API.
- Current: RunSearchOpts does not gate work by offline; enrichArtist condition `if !offline && len(dbTracks) == 0 || err != nil` is ambiguous (operator precedence) and may misbehave.
- Impact: May call APIs in offline or skip API when desired; unpredictable behavior.
- STATUS: FIXED THE LOGIC GATE

7) Fragmented/Unbounded Caching
- Expected: Coherent per-artist neighbor caching; bounded memory.
- Current: albumCache keyed by album ID only; no per-artist neighbor cache; global map without eviction.
- Impact: Redundant calls/work; potential memory growth.
- STATUS: ADDING AN ALBUM CACHED TO GET THE ALBUM ID TO KEEP FROM CONTINUING TO CALL API OR DB IF WE ALREADY HAVE IN MEMORY

8) Limited Operational Controls
- Expected: MaxDepth, MaxNodes, Timeout, EarlyExit, Progress.
- Current: Only partial MaxDepth; no node/time limits or early-exit hooks beyond target found.
- Impact: Risk of long/expensive runs on large graphs.
- STATUS: WILL FIX LATER, RIGHT NOW I AM OKAY WITH LONG SEARCHES

9) Inconsistent Error Handling
- Expected: Strategy to terminate or continue; expose termination reason and error.
- Current: Errors are printed/logged and often ignored; search continues.
- Impact: Hidden failures and difficult diagnostics.
- STATUS: WILL FIX LATER, RIGHT NOW I AM OKAY WITH NOT STOPPING AT ERRORS AND WHATNOT, JUST NEED THE CODE TO RUN CORRECTLY FIRST

10) Global Mutable State
- Expected: No globals in core search.
- Current: Global `storeConn` and `albumCache`.
- Impact: Concurrency hazards; lifecycle/ownership unclear; test brittleness.
- STATUS: WAS ABLE TO REMOVE BOTH GLOBALS SINCE WE ADDED A CACHE ABOVE, STORECONN DOES NOT NEED TO BE A GLOBAL. ONLY OPEN THE STORECONN IF THE STORE IS NOT OPEN OR IS NIL (SHOULD NEVER BE THE CASE, BUT WANT THE CODE TO WORK FIRST BEFORE OPTIMIZING)

11) Evidence/Prev Stability
- Expected: Set once on first discovery to match shortest path.
- Current: Without artist visited and with heap ordering, Prev/Evidence can be overwritten.
- Impact: Path and evidence may not reflect the minimal-hop route.
- STATUS: WAS NOT MAKING SEEN TRUE EARLY ENOUGH, UPDATED VISTED = TRUE, BUT CHECKED IT FIRST

12) Dead/Unused or Divergent Enrichment Path
- Expected: Single consistent strategy for obtaining neighbors.
- Current: enrichArtist exists but RunSearchOpts populates tracks via DB directly; comments show partial refactors.
- Impact: Maintenance confusion; code path divergence.
- STATUS: REMOVED THE BFS.GO DBTRACK LOOKUP, BECAUSE I WAS ALSO DOING IT IN ENRICHARTIST(). THIS LED TO DOUBLE SAVING 

13) Noisy Logging and Prints
- Expected: Leveled logs via logger interface.
- Current: Mixed fmt and log usage; printlns in hasTarget and elsewhere.
- Impact: Noisy output; hard to control verbosity.

14) Rate Limit Handling in Wrong Layer
- Expected: Provider-level rate limiting/backoff; none in core.
- Current: enrichArtist sleeps 300ms unconditionally.
- Impact: Unnecessary latency and reduced throughput, even when offline.

## Recommended Fixes (Prioritized)

1) Correct the Algorithm
- Replace the priority heap with a FIFO queue to implement true BFS.
- Add an artist-level visited set; mark visited when enqueuing.
- Set DistTo/Prev only if the node has not been seen before.

2) Decouple Search from Data Fetching
- Define and inject a neighbor provider interface; remove DB/API calls from RunSearchOpts.
- Move DB/API logic to sixDegrees/bfs_wrapper.go or a provider in store/spotify packages.

3) Add Operational Controls and Metrics
- Introduce Options: MaxDepth, MaxNodes, Timeout, EarlyExit, Progress.
- Track visited/expanded counts, duration, and termination reason in the result.

4) Fix Offline/Online Logic and Caching
- Enforce offline=no API calls. In online mode, prefer DB then API, with consistent writes back to DB.
- Replace ambiguous condition with explicit parentheses: `if !offline && (len(dbTracks) == 0 || err != nil)`.
- Consider per-artist neighbor memoization during a run; bound cache memory or scope it to the run.

5) Resource Management
- Remove per-call Open/Migrate in enrichArtist; initialize once at startup and pass the handle in.
- Eliminate global storeConn/albumCache in favor of scoped objects.

6) Error Handling and Logging
- Decide on continue vs terminate policy for neighbor fetch errors; expose termination reason and last error.
- Replace fmt prints with leveled logging controlled by a verbose flag or logger.

7) Optional Enhancements
- Keep a popularity tiebreaker for neighbor ordering within the same BFS depth without violating FIFO semantics across depths.
- Plan for bidirectional BFS in the future for performance on large graphs.

## What the Code Does Well
- Uses Helper (Prev, DistTo, Evidence, ArtistMap) to reconstruct a path when the target is found.
- Upserts tracks and creates linking records (in enrichArtist), which is useful for building the local graph representation.
- Track-level deduplication (visitedTracks) helps reduce repeated processing of identical track IDs.
- Early target detection to short-circuit deeper exploration.

## Summary
- Current implementation performs a popularity-biased best-first search with partial BFS-like structures. It lacks key BFS guarantees (minimal hops), artist-level deduplication, separation of concerns, and robust operational controls. Addressing the prioritized fixes above will restore correctness, improve performance and maintainability, and make the module easier to test and operate.
