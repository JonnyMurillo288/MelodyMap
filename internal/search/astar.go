package search

import (
	"container/heap"
	"fmt"
	"log"
	"strings"
	"time"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

// AStarNode represents a node in the A* search
type AStarNode struct {
	Artist   *sixdegrees.Artists
	G        float64 // cost from start to this node
	H        float64 // heuristic cost to target
	F        float64 // G + H
	Depth    int
	Parent   *AStarNode
	EdgeCost float64 // cost of edge from parent to this node
	index    int     // heap index
}

// PriorityQueue implements heap.Interface for A* nodes
type PriorityQueue []*AStarNode

func (pq PriorityQueue) Len() int { return len(pq) }

func (pq PriorityQueue) Less(i, j int) bool {
	// Lower F score = higher priority
	return pq[i].F < pq[j].F
}

func (pq PriorityQueue) Swap(i, j int) {
	pq[i], pq[j] = pq[j], pq[i]
	pq[i].index = i
	pq[j].index = j
}

func (pq *PriorityQueue) Push(x interface{}) {
	n := len(*pq)
	node := x.(*AStarNode)
	node.index = n
	*pq = append(*pq, node)
}

func (pq *PriorityQueue) Pop() interface{} {
	old := *pq
	n := len(old)
	node := old[n-1]
	old[n-1] = nil
	node.index = -1
	*pq = old[0 : n-1]
	return node
}

// RunSearchOptsAStar performs A* search using Node2Vec embeddings as heuristic
func RunSearchOptsAStar(
	s *Store,
	start, target *sixdegrees.Artists,
	maxDepth int,
	verbose bool,
	limit *int,
	offline bool,
) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool) {
	// Check if embeddings are loaded
	if GlobalEmbeddingStore == nil {
		fmt.Println("ERROR: Embeddings not loaded. Call InitEmbeddings first.")
		return nil, nil, nil, nil, 500, false
	}

	fmt.Println("Running A* search with Node2Vec heuristic")
	globalCacheMu.RLock()
	cacheSize := len(GlobalNeighborCache)
	globalCacheMu.RUnlock()
	fmt.Println("Number of items in the cache:", cacheSize)

	// =========================================================
	// Store management
	// =========================================================
	openedHere := false
	if s == nil {
		var err error
		s, err = Open("")
		if err != nil {
			fmt.Printf("RunSearchOptsAStar: failed to open DB: %v\n", err)
			return nil, nil, nil, nil, 500, false
		}
		openedHere = true
	}

	if openedHere {
		defer s.Close()
	}

	// =========================================================
	// Validate inputs
	// =========================================================
	if start == nil || start.ID == "" || target == nil || target.ID == "" {
		return nil, nil, nil, nil, 400, false
	}

	// Trivial case
	if start.ID == target.ID {
		h := sixdegrees.NewHelper()
		h.ArtistByID[start.ID] = start
		h.IDByName[start.Name] = start.ID
		return h,
			[]string{start.Name},
			[]string{start.ID},
			[][]sixdegrees.Track{},
			200, true
	}

	// Neighbor cap per artist
	perArtistLimit := 5000
	if limit != nil && *limit > 0 {
		perArtistLimit = *limit
	}
	if perArtistLimit > 20000 {
		perArtistLimit = 20000
	}

	const maxSearchDuration = 3000 * time.Second
	startTime := time.Now()

	// =========================================================
	// Initialize A* data structures
	// =========================================================
	h := sixdegrees.NewHelper()
	h.ArtistByID[start.ID] = start
	h.IDByName[start.Name] = start.ID

	// Priority queue
	pq := make(PriorityQueue, 0)
	heap.Init(&pq)

	// Start node
	startNode := &AStarNode{
		Artist: start,
		G:      0,
		H:      GlobalEmbeddingStore.AStarHeuristic(start.ID, target.ID),
		Depth:  0,
		Parent: nil,
	}
	startNode.F = startNode.G + startNode.H
	heap.Push(&pq, startNode)

	// Track visited nodes and their best G scores
	visited := make(map[string]bool)
	gScore := map[string]float64{start.ID: 0}

	// Track edges for path reconstruction
	prevTracks := make(map[string][]sixdegrees.Track)

	var expandedCount int

	// =========================================================
	// A* main loop
	// =========================================================
	log.Println("Starting A* search...")

	for pq.Len() > 0 {
		// Pop node with lowest F score
		current := heap.Pop(&pq).(*AStarNode)

		// Check if we've reached the target
		if current.Artist.ID == target.ID {
			// Reconstruct path
			finalPathIDs := reconstructPathFromAStar(current)
			finalPathNames := make([]string, 0, len(finalPathIDs))
			finalPathTracks := make([][]sixdegrees.Track, 0, len(finalPathIDs)-1)

			// Build names and tracks
			for _, id := range finalPathIDs {
				if art, ok := h.ArtistByID[id]; ok {
					finalPathNames = append(finalPathNames, art.Name)
				} else {
					finalPathNames = append(finalPathNames, id)
				}
			}

			for i := 1; i < len(finalPathIDs); i++ {
				edgeKey := finalPathIDs[i-1] + "->" + finalPathIDs[i]
				finalPathTracks = append(finalPathTracks, prevTracks[edgeKey])
			}

			fmt.Printf("A* search completed! Found path with %d hops\n", len(finalPathIDs)-1)
			return h, finalPathNames, finalPathIDs, finalPathTracks, 200, true
		}

		// Mark as visited
		currentID := current.Artist.ID
		if visited[currentID] {
			continue
		}
		visited[currentID] = true

		// Update search ticker
		SearchTicker.Artist = current.Artist.Name
		if current.Depth > SearchTicker.Depth {
			SearchTicker.Depth = current.Depth
		}

		// Timeout check
		if time.Since(startTime) > maxSearchDuration {
			return h, nil, nil, nil, 504, false
		}

		// Depth guard
		if maxDepth > 0 && current.Depth > maxDepth {
			continue
		}

		if verbose {
			log.Printf("[A*] Expanding %s (G=%.3f, H=%.3f, F=%.3f, depth=%d)",
				current.Artist.Name, current.G, current.H, current.F, current.Depth)
		}

		// Get neighbors
		var neighbors []*NeighborEdge
		var status int
		var err error

		cacheKey := currentID

		// Check cache with read lock
		globalCacheMu.RLock()
		cached, ok := GlobalNeighborCache[cacheKey]
		globalCacheMu.RUnlock()

		if ok {
			neighbors = cached
			status = 200
			if verbose {
				log.Printf("[CACHE] Using %d cached neighbors for %s", len(neighbors), current.Artist.Name)
			}
		} else {
			neighbors, status, err = s.MusicBrainzNeighborProvider(
				current.Artist,
				perArtistLimit,
				offline,
			)

			if status == 429 {
				return h, nil, nil, nil, 429, false
			}

			if err != nil {
				if verbose {
					log.Printf("[A*] Provider error for %s: %v", current.Artist.Name, err)
				}
				continue
			}

			// Store in cache with write lock
			globalCacheMu.Lock()
			GlobalNeighborCache[cacheKey] = neighbors
			globalCacheMu.Unlock()
		}
		// ============================
		// Build FrontendStep for /lookup
		// ============================
		step := FrontendStep{
			ID:   current.Artist.ID,
			Name: current.Artist.Name,
			Neighbors: make([]struct {
				ID     string      `json:"ID"`
				Name   string      `json:"Name"`
				Tracks []TrackInfo `json:"Tracks"`
			}, 0, len(neighbors)),
		}

		SearchTicker.Max = len(neighbors)
		expandedCount = 0

		// Process each neighbor
		for _, nb := range neighbors {
			if nb == nil || nb.Artist == nil || nb.Artist.ID == "" {
				continue
			}

			expandedCount++
			SearchTicker.Count = expandedCount

			childID := nb.Artist.ID

			// Skip if already visited
			if visited[childID] {
				continue
			}

			// Convert neighbor data
			convertedArtist := convertToArtist(nb.Artist)
			tracks := convertTrackList(nb.Track)

			// Update helper
			if _, ok := h.ArtistByID[childID]; !ok {
				h.ArtistByID[childID] = convertedArtist
			}
			if convertedArtist.Name != "" {
				h.IDByName[convertedArtist.Name] = childID
			}

			// Deduplicate tracks
			tracks = sixdegrees.DeduplicateTracks(tracks, 0.65, false)

			if len(tracks) == 0 {
				continue
			}

			// convert deduped tracks → TrackInfo for /lookup
			ti := make([]TrackInfo, 0, len(tracks))
			for _, t := range tracks {
				ti = append(ti, TrackInfo{
					ID:            t.ID,
					Name:          t.Name,
					RecordingID:   t.RecordingID,
					RecordingName: t.RecordingName,
					PhotoURL:      t.PhotoURL,
				})
			}

			// append neighbor entry for /lookup
			step.Neighbors = append(step.Neighbors, struct {
				ID     string      `json:"ID"`
				Name   string      `json:"Name"`
				Tracks []TrackInfo `json:"Tracks"`
			}{
				ID:     nb.Artist.ID,
				Name:   nb.Artist.Name,
				Tracks: ti,
			})

			if len(tracks) == 0 {
				continue
			}

			// Calculate edge cost (uniform cost = 1.0 for now)
			edgeCost := 1.0

			// Calculate tentative G score
			tentativeG := current.G + edgeCost

			// Check if this path is better
			if prevG, exists := gScore[childID]; exists && tentativeG >= prevG {
				continue
			}

			// Update G score
			gScore[childID] = tentativeG

			// Store tracks for reconstruction
			edgeKey := currentID + "->" + childID
			prevTracks[edgeKey] = tracks

			// Calculate heuristic
			heuristic := GlobalEmbeddingStore.AStarHeuristic(childID, target.ID)

			// Create new node
			childNode := &AStarNode{
				Artist:   convertedArtist,
				G:        tentativeG,
				H:        heuristic,
				F:        tentativeG + heuristic,
				Depth:    current.Depth + 1,
				Parent:   current,
				EdgeCost: edgeCost,
			}

			heap.Push(&pq, childNode)

		}

		// store the neighbors for this artist into the global lookup
		if len(step.Neighbors) > 0 {
			key := strings.ToLower(current.Artist.Name)
			globalLookupMu.Lock()
			GlobalNeighborLookup[key] = step
			globalLookupMu.Unlock()
		}
	}

	// No path found
	fmt.Println("A* search completed: no path found")
	return h, nil, nil, nil, 404, false
}

// reconstructPathFromAStar builds the path by following parent pointers
func reconstructPathFromAStar(node *AStarNode) []string {
	var path []string
	for node != nil {
		path = append(path, node.Artist.ID)
		node = node.Parent
	}

	// Reverse the path
	for i, j := 0, len(path)-1; i < j; i, j = i+1, j-1 {
		path[i], path[j] = path[j], path[i]
	}

	return path
}
