# A* Search with Node2Vec Embeddings

This document explains how to use Node2Vec embeddings from PecanPy as heuristics for A* search in the MelodyMap project.

## Overview

The system uses artist collaboration embeddings generated from the `artist_collab` table to guide A* search toward the target artist more efficiently than BFS.

### Key Components

1. **Embeddings Generation** ([acousticbrainz/embeddings.ipynb](../acousticbrainz/embeddings.ipynb))
   - Extracts artist collaboration edges from PostgreSQL
   - Uses PecanPy to generate 32-dimensional Node2Vec embeddings
   - Outputs to `/tmp/artist_embeddings.csv`

2. **Embedding Store** ([internal/search/embeddings.go](../internal/search/embeddings.go))
   - Loads embeddings into memory
   - Provides similarity functions (cosine, euclidean)
   - Computes A* heuristic based on embedding distance

3. **A* Search** ([internal/search/astar.go](../internal/search/astar.go))
   - Priority queue-based A* implementation
   - Uses embedding similarity as heuristic function
   - Falls back to BFS behavior when embeddings unavailable

## Setup

### 1. Generate Embeddings

Run the Jupyter notebook to generate embeddings:

```bash
cd acousticbrainz
jupyter notebook embeddings.ipynb
```

The notebook will:
- Query the `artist_collab` table
- Build a graph with ~583K nodes and ~3.2M edges
- Train Node2Vec with parameters:
  - `dim=32` (embedding dimensions)
  - `num_walks=5`
  - `walk_length=10`
  - `p=1.0, q=1.0` (random walk parameters)
- Save to `/tmp/artist_embeddings.csv`

Expected format:
```csv
artist_id,emb_0,emb_1,emb_2,...,emb_31
1,0.546129,0.498049,0.393799,...,-0.629423
10,0.606939,0.565944,0.415253,...,-0.581472
...
```

### 2. Load Embeddings in Go

```go
import "github.com/Jonnymurillo288/MelodyMap/internal/search"

// Initialize the global embedding store
err := search.InitEmbeddings("/tmp/artist_embeddings.csv")
if err != nil {
    log.Fatal(err)
}
```

### 3. Run A* Search

```go
// Set up search parameters
start := &sixdegrees.Artists{ID: "123", Name: "Artist A"}
target := &sixdegrees.Artists{ID: "456", Name: "Artist B"}

store, _ := search.Open("")
defer store.Close()

// Run A* with embeddings
helper, pathNames, pathIDs, pathTracks, status, found := search.RunSearchOptsAStar(
    store,
    start,
    target,
    6,      // maxDepth
    true,   // verbose
    nil,    // limit (nil = default)
    false,  // offline
)

if found {
    fmt.Printf("Found path: %v\n", pathNames)
}
```

## Architecture

### Heuristic Function

The A* heuristic converts cosine similarity to distance:

```go
func (es *EmbeddingStore) AStarHeuristic(currentID, targetID string) float64 {
    currentEmb := es.GetEmbedding(currentID)
    targetEmb := es.GetEmbedding(targetID)

    similarity := CosineSimilarity(currentEmb, targetEmb)
    distance := 1.0 - similarity  // Convert similarity to distance

    return distance
}
```

- **Cosine Similarity ∈ [-1, 1]**
  - `1.0` = identical direction (very close artists)
  - `0.0` = orthogonal (unrelated artists)
  - `-1.0` = opposite direction (very different)

- **Heuristic Distance ∈ [0, 2]**
  - `0.0` = identical (best case)
  - `1.0` = orthogonal (neutral)
  - `2.0` = opposite (worst case)

### Priority Queue

A* uses a min-heap ordered by `F = G + H`:
- **G**: Actual cost from start (number of hops)
- **H**: Heuristic estimate to target (embedding distance)
- **F**: Total estimated cost

Nodes with lower `F` scores are explored first, guiding search toward artists similar to the target.

### Fallback Behavior

If embeddings are missing for an artist:
```go
// Return neutral heuristic (0.0)
// A* behaves like uniform-cost search for this node
return 0.0
```

## Performance Considerations

### Memory Usage

- ~583K artists × 32 dimensions × 8 bytes = ~150 MB
- Loaded once at startup into `GlobalEmbeddingStore`

### Speed

- Embedding lookup: O(1) hash table access
- Cosine similarity: O(d) where d=32 (very fast)
- Expected to explore fewer nodes than BFS by ~30-50%

### Cache Reuse

The A* implementation reuses `GlobalNeighborCache` from BFS:
```go
if cached, ok := GlobalNeighborCache[cacheKey]; ok {
    neighbors = cached  // Skip database query
}
```

## Testing

Run the example program:

```bash
go run cmd/astar-example/main.go
```

This will:
1. Load embeddings from CSV
2. Connect to the database
3. Run an example A* search
4. Display path and embedding analysis

## Tuning Parameters

### Node2Vec Parameters (in notebook)

- **`dim`**: Embedding dimensions (16-64 typical)
  - Higher = more expressive but slower and more memory

- **`num_walks`**: Random walks per node (5-10 typical)
  - More walks = better embeddings but slower training

- **`walk_length`**: Steps per walk (10-80 typical)
  - Longer = captures more context

- **`p`**: Return parameter (0.5-2.0)
  - Lower = more likely to return to previous node (local structure)

- **`q`**: In-out parameter (0.5-2.0)
  - Lower = more DFS-like (communities)
  - Higher = more BFS-like (structural roles)

### A* Parameters

- **`maxDepth`**: Maximum search depth (6 typical for six degrees)
- **`limit`**: Neighbors per artist (5000 default, 20000 max)
- **`offline`**: Skip MusicBrainz API calls (faster, less complete)

## Next Steps

1. **Weighted Edges**: Use collaboration strength as edge costs
2. **Learned Heuristics**: Train ML model to predict hop distance
3. **Bidirectional A***: Search from both ends simultaneously
4. **Dynamic Embeddings**: Update embeddings as new collaborations are discovered
5. **Multiple Heuristics**: Combine embedding distance with graph features

## Files

- [internal/search/embeddings.go](../internal/search/embeddings.go) - Embedding store and similarity functions
- [internal/search/astar.go](../internal/search/astar.go) - A* search implementation
- [cmd/astar-example/main.go](../cmd/astar-example/main.go) - Example usage
- [acousticbrainz/embeddings.ipynb](../acousticbrainz/embeddings.ipynb) - Embedding generation
