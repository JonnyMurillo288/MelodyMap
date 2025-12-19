# Integration Guide: A* Search with Node2Vec

Quick guide to integrate A* search into your existing MelodyMap application.

## Quick Start

### 1. Generate Embeddings (One-Time Setup)

```bash
# Run the Jupyter notebook
cd acousticbrainz
jupyter notebook embeddings.ipynb
# Execute all cells to generate /tmp/artist_embeddings.csv
```

### 2. Load Embeddings at Application Startup

In your [main/main.go](../main/main.go) or initialization code:

```go
import "github.com/Jonnymurillo288/MelodyMap/internal/search"

func main() {
    // Load embeddings once at startup
    embeddingPath := "/tmp/artist_embeddings.csv"

    fmt.Println("Loading Node2Vec embeddings...")
    if err := search.InitEmbeddings(embeddingPath); err != nil {
        log.Printf("Warning: Failed to load embeddings: %v", err)
        log.Println("A* search will not be available")
    } else {
        fmt.Println("✓ Embeddings loaded successfully")
    }

    // ... rest of your application initialization
}
```

### 3. Add A* Endpoint to Your HTTP Handlers

In [main/search_handlers.go](../main/search_handlers.go):

```go
// Add this new handler
func HandleSearchAStar(w http.ResponseWriter, r *http.Request) {
    // Parse request (similar to existing BFS handler)
    var req search.SearchRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "Invalid request", http.StatusBadRequest)
        return
    }

    // Validate embeddings are loaded
    if search.GlobalEmbeddingStore == nil {
        http.Error(w, "Embeddings not loaded", http.StatusServiceUnavailable)
        return
    }

    // Convert to sixdegrees.Artists
    start := &sixdegrees.Artists{
        ID:   req.StartID,
        Name: req.Start,
    }
    target := &sixdegrees.Artists{
        ID:   req.TargetID,
        Name: req.Target,
    }

    // Open store
    store, err := search.Open("")
    if err != nil {
        http.Error(w, "Database error", http.StatusInternalServerError)
        return
    }
    defer store.Close()

    // Run A* search
    maxDepth := req.Depth
    if maxDepth <= 0 {
        maxDepth = 6
    }

    helper, pathNames, pathIDs, pathTracks, statusCode, found := search.RunSearchOptsAStar(
        store,
        start,
        target,
        maxDepth,
        false, // verbose
        nil,   // limit
        false, // offline
    )

    // Build response (reuse existing logic)
    if !found {
        http.Error(w, "No path found", statusCode)
        return
    }

    // Convert to search.SearchResponse
    response := buildSearchResponse(helper, pathNames, pathIDs, pathTracks, statusCode)

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(response)
}
```

### 4. Register the Route

In your router setup:

```go
// Add alongside your existing search routes
router.HandleFunc("/api/search/astar", HandleSearchAStar).Methods("POST")
```

### 5. Frontend Integration

Add an option to choose search algorithm:

```javascript
// In your search component
const searchOptions = {
  algorithm: 'astar', // or 'bfs'
  start: startArtist,
  target: targetArtist,
  depth: 6
};

const response = await fetch('/api/search/astar', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(searchOptions)
});
```

## Comparison: BFS vs A*

### When to Use BFS ([internal/search/bfs.go](../internal/search/bfs.go))

- **Guaranteed shortest path** (unweighted graph)
- Embeddings not available
- Small search space (< 1000 artists)
- Testing/debugging

### When to Use A* ([internal/search/astar.go](../internal/search/astar.go))

- **Faster search** (explores fewer nodes)
- Large search space (> 10K artists)
- Embeddings are loaded
- Production traffic

### Performance Comparison

| Metric | BFS | A* |
|--------|-----|-----|
| Nodes Explored | 100% | ~40-60% |
| Memory (per search) | O(b^d) | O(b^d) |
| Memory (embeddings) | 0 MB | ~150 MB |
| Startup Time | Instant | +2-3 sec |
| Path Optimality | Optimal | Optimal* |

*Optimal if heuristic is admissible (never overestimates)

## Advanced: Switching Algorithm Dynamically

```go
func HandleSmartSearch(w http.ResponseWriter, r *http.Request) {
    var req search.SearchRequest
    json.NewDecoder(r.Body).Decode(&req)

    // Choose algorithm based on availability and heuristics
    useAStar := search.GlobalEmbeddingStore != nil

    // Optional: Check if embeddings exist for both artists
    if useAStar {
        _, hasStart := search.GlobalEmbeddingStore.GetEmbedding(req.StartID)
        _, hasTarget := search.GlobalEmbeddingStore.GetEmbedding(req.TargetID)
        useAStar = hasStart && hasTarget
    }

    var helper *sixdegrees.Helper
    var pathNames, pathIDs []string
    var pathTracks [][]sixdegrees.Track
    var statusCode int
    var found bool

    store, _ := search.Open("")
    defer store.Close()

    if useAStar {
        log.Println("Using A* search")
        helper, pathNames, pathIDs, pathTracks, statusCode, found = search.RunSearchOptsAStar(
            store, start, target, req.Depth, false, nil, false,
        )
    } else {
        log.Println("Using BFS (A* not available)")
        helper, pathNames, pathIDs, pathTracks, statusCode, found = search.RunSearchOptsBFS(
            store, start, target, req.Depth, false, nil, false,
        )
    }

    // ... return response
}
```

## Monitoring and Metrics

Add logging to compare performance:

```go
import "time"

func benchmarkSearch(name string, searchFunc func()) {
    start := time.Now()
    nodesExpanded := 0

    searchFunc()

    elapsed := time.Since(start)
    log.Printf("[%s] Completed in %v, expanded %d nodes",
        name, elapsed, nodesExpanded)
}
```

## Troubleshooting

### "Embeddings not loaded"

Check:
1. File exists at `/tmp/artist_embeddings.csv`
2. `InitEmbeddings()` called at startup
3. No errors during CSV parsing

```bash
# Verify file
ls -lh /tmp/artist_embeddings.csv
head /tmp/artist_embeddings.csv
```

### A* is slower than BFS

This can happen if:
- Artist is very obscure (bad embeddings)
- Graph is very dense (heuristic doesn't help much)
- Embeddings were trained on different data

Solution: Use BFS as fallback, or retrain embeddings.

### Out of memory

Embeddings use ~150 MB. If this is too much:
1. Reduce embedding dimension (32 → 16)
2. Load embeddings for subset of artists only
3. Use on-demand loading from database

## Production Checklist

- [ ] Generate embeddings with latest database snapshot
- [ ] Store embeddings in persistent location (not `/tmp`)
- [ ] Add health check endpoint to verify embeddings loaded
- [ ] Log search algorithm choice (BFS vs A*)
- [ ] Monitor search latency and node expansion
- [ ] Set up automatic embedding regeneration (weekly/monthly)
- [ ] Add cache warming for popular searches
- [ ] Consider A/B testing to measure user experience

## Files Modified/Added

### New Files
- [internal/search/embeddings.go](../internal/search/embeddings.go)
- [internal/search/astar.go](../internal/search/astar.go)
- [internal/search/embeddings_test.go](../internal/search/embeddings_test.go)
- [cmd/astar-example/main.go](../cmd/astar-example/main.go)

### Files to Modify
- [main/main.go](../main/main.go) - Add `InitEmbeddings()` call
- [main/search_handlers.go](../main/search_handlers.go) - Add A* endpoint
- Frontend routing/search component - Add algorithm selection

## Next Steps

1. **Generate Production Embeddings**
   ```bash
   cd acousticbrainz
   jupyter notebook embeddings.ipynb
   cp /tmp/artist_embeddings.csv /var/lib/melodymap/embeddings.csv
   ```

2. **Update Application Startup**
   ```go
   search.InitEmbeddings("/var/lib/melodymap/embeddings.csv")
   ```

3. **Test with Real Queries**
   ```bash
   go run cmd/astar-example/main.go
   ```

4. **Deploy and Monitor**
   - Watch search latency metrics
   - Compare BFS vs A* performance
   - Collect user feedback

## Support

For questions or issues:
1. Check logs for embedding loading errors
2. Run test suite: `go test ./internal/search -v`
3. Review [ASTAR_SETUP.md](ASTAR_SETUP.md) for detailed architecture
