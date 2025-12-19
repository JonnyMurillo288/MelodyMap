# Search Performance Metrics System

Track and compare BFS vs A* search performance to optimize heuristics.

## Overview

This system automatically saves search results to a database table for performance analysis:

- **Search Type**: BFS or A*
- **Start & End Artists**: Artist names and IDs
- **Number of Hops**: Path length
- **Duration**: Time taken in milliseconds
- **Success**: Whether path was found
- **Timestamp**: When the search was executed

## Setup

### 1. Create the Metrics Table

Run this once to create the `search_metrics` table:

```bash
go run cmd/init-metrics/main.go init
```

This creates:
```sql
CREATE TABLE search_metrics (
    id SERIAL PRIMARY KEY,
    search_type VARCHAR(10) NOT NULL,  -- 'BFS' or 'ASTAR'
    start_artist_id VARCHAR(255) NOT NULL,
    start_artist VARCHAR(500) NOT NULL,
    end_artist_id VARCHAR(255) NOT NULL,
    end_artist VARCHAR(500) NOT NULL,
    num_hops INTEGER NOT NULL,
    duration_ms BIGINT NOT NULL,
    success BOOLEAN NOT NULL DEFAULT true,
    error_message TEXT,
    max_depth INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### 2. Enable Metrics Collection

Use the wrapper functions that automatically save metrics:

#### In Your Search Code

```go
// Instead of:
helper, pathNames, pathIDs, pathTracks, status, found := search.RunSearchOptsBFS(...)

// Use:
helper, pathNames, pathIDs, pathTracks, status, found := search.RunSearchOptsBFSWithMetrics(...)

// Or for A*:
helper, pathNames, pathIDs, pathTracks, status, found := search.RunSearchOptsAStarWithMetrics(...)
```

#### Update search_artists.go

Change line 67 from:
```go
helper, _, pathIDs, tracksPerHop, status, ok := RunSearchOptsBFS(...)
```

To:
```go
helper, _, pathIDs, tracksPerHop, status, ok := RunSearchOptsBFSWithMetrics(...)
```

Or for A*:
```go
helper, _, pathIDs, tracksPerHop, status, ok := RunSearchOptsAStarWithMetrics(...)
```

## Usage

### View Performance Comparison

```bash
go run cmd/init-metrics/main.go compare
```

Output:
```json
{
  "ASTAR": {
    "avg_duration_ms": 1245.67,
    "avg_hops": 3.2,
    "max_duration_ms": 3500,
    "min_duration_ms": 450,
    "successful_searches": 150,
    "total_searches": 150
  },
  "BFS": {
    "avg_duration_ms": 2834.21,
    "avg_hops": 3.2,
    "max_duration_ms": 8900,
    "min_duration_ms": 890,
    "successful_searches": 200,
    "total_searches": 200
  }
}

=== Summary ===
BFS average:   2834.21 ms
A* average:    1245.67 ms
Speedup:       2.28x 🚀 (A* much faster)
```

### List Recent Searches

```bash
# All searches
go run cmd/init-metrics/main.go list

# Only BFS
go run cmd/init-metrics/main.go list BFS

# Only A*
go run cmd/init-metrics/main.go list ASTAR
```

Output:
```
=== Recent Searches (BFS) ===

[BFS] The Beatles → Radiohead
  Hops: 3, Duration: 2340ms, Time: 2025-12-17 10:30:45

[BFS] Daft Punk → Kanye West
  Hops: 2, Duration: 1200ms, Time: 2025-12-17 10:25:12
```

### HTTP Endpoints

Add to your [main/main.go](../main/main.go):

```go
// In main() after creating mux
mux.HandleFunc("/api/metrics/compare", HandleMetricsComparison)
mux.HandleFunc("/api/metrics/list", HandleMetricsList)
```

Then access:
- `GET /api/metrics/compare` - Performance comparison
- `GET /api/metrics/list?type=BFS` - List BFS searches
- `GET /api/metrics/list?type=ASTAR` - List A* searches

## Automatic Metrics Collection

Metrics are saved automatically and **non-blocking**:
- Uses goroutine to save asynchronously
- Won't slow down your search
- Failures to save metrics are logged but don't affect search results

```go
// Automatic metric saved after search completes
[METRICS] Saved BFS search: The Beatles → Radiohead, 3 hops, 2340ms
```

## Analysis Queries

### Find Fastest Searches

```sql
SELECT
    search_type,
    start_artist,
    end_artist,
    num_hops,
    duration_ms
FROM search_metrics
WHERE success = true
ORDER BY duration_ms ASC
LIMIT 10;
```

### Compare by Hop Count

```sql
SELECT
    num_hops,
    AVG(CASE WHEN search_type = 'BFS' THEN duration_ms END) as bfs_avg_ms,
    AVG(CASE WHEN search_type = 'ASTAR' THEN duration_ms END) as astar_avg_ms
FROM search_metrics
WHERE success = true
GROUP BY num_hops
ORDER BY num_hops;
```

### Speedup by Search Depth

```sql
WITH stats AS (
    SELECT
        num_hops,
        search_type,
        AVG(duration_ms) as avg_ms
    FROM search_metrics
    WHERE success = true
    GROUP BY num_hops, search_type
)
SELECT
    b.num_hops,
    b.avg_ms as bfs_ms,
    a.avg_ms as astar_ms,
    ROUND(b.avg_ms / a.avg_ms, 2) as speedup
FROM stats b
JOIN stats a ON b.num_hops = a.num_hops
WHERE b.search_type = 'BFS'
  AND a.search_type = 'ASTAR'
ORDER BY b.num_hops;
```

## Tuning A* Heuristics

### Goal

Find heuristic parameters where A* is consistently faster than BFS.

### Process

1. **Collect Baseline Data**
   ```bash
   # Run 100+ searches with current heuristic
   # Check metrics
   go run cmd/init-metrics/main.go compare
   ```

2. **Modify Heuristic**

   In [internal/search/embeddings.go](../internal/search/embeddings.go):
   ```go
   func (es *EmbeddingStore) AStarHeuristic(currentID, targetID string) float64 {
       // Current
       similarity := CosineSimilarity(currentEmb, targetEmb)
       distance := 1.0 - similarity

       // Try: Scale factor
       distance := (1.0 - similarity) * 0.5  // Less aggressive

       // Or: Use euclidean
       distance := EuclideanDistance(currentEmb, targetEmb)

       return distance
   }
   ```

3. **Test New Heuristic**
   ```bash
   # Clear metrics or note the time
   # Run 100+ searches with new heuristic
   # Compare
   go run cmd/init-metrics/main.go compare
   ```

4. **Analyze Results**
   - Is A* faster on average?
   - Does speedup increase with hop count?
   - Are there cases where BFS is better?

### Heuristic Variations to Test

1. **Scaling Factor**
   ```go
   distance := (1.0 - similarity) * scaleFactor
   // Try: 0.1, 0.5, 1.0, 2.0
   ```

2. **Distance Metrics**
   ```go
   // Cosine distance
   distance := 1.0 - CosineSimilarity(a, b)

   // Euclidean distance
   distance := EuclideanDistance(a, b)

   // Hybrid
   distance := (1.0 - cosine) * 0.7 + euclidean * 0.3
   ```

3. **Admissibility**
   ```go
   // Ensure never overestimate (admissible)
   rawDistance := 1.0 - similarity
   distance := rawDistance * 0.5  // Conservative
   ```

## Export Metrics for Analysis

```bash
# Export to CSV
psql -U postgres -d musicbrainz_db -c "
COPY (
    SELECT * FROM search_metrics
    WHERE created_at > NOW() - INTERVAL '7 days'
    ORDER BY created_at
) TO '/tmp/search_metrics.csv' CSV HEADER;
"
```

Then analyze in Python/Jupyter:
```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('/tmp/search_metrics.csv')

# Compare distributions
bfs = df[df['search_type'] == 'BFS']
astar = df[df['search_type'] == 'ASTAR']

plt.hist([bfs['duration_ms'], astar['duration_ms']],
         label=['BFS', 'A*'], bins=30)
plt.xlabel('Duration (ms)')
plt.legend()
plt.show()
```

## Monitoring Dashboard (Future)

Add a web UI to visualize metrics:
- Real-time speedup chart
- Success rate by algorithm
- Performance over time
- Heuristic A/B testing results

## Files

- [internal/search/search_metrics.go](../internal/search/search_metrics.go) - Core metrics functions
- [internal/search/search_with_metrics.go](../internal/search/search_with_metrics.go) - Wrapper functions
- [cmd/init-metrics/main.go](../cmd/init-metrics/main.go) - CLI tool
- [main/metrics_handlers.go](../main/metrics_handlers.go) - HTTP endpoints

## Summary

- ✓ Automatic metrics collection
- ✓ Non-blocking (doesn't slow searches)
- ✓ CLI tools for analysis
- ✓ HTTP API for dashboards
- ✓ Export to CSV for deep analysis
- ✓ Ready for A/B testing heuristics
