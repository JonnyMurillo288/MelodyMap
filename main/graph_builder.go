package main

import (
	"fmt"

	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
)

// Graph is a minimal, in-memory artist collaboration graph.
type Graph struct {
	Nodes      map[string]*sixdegrees.Artists
	Edges      map[string][]string
	TrackEdges map[string]map[string]sixdegrees.Track
}

type NeighborProvider func(
	a *sixdegrees.Artists,
	limit int,
	verbose bool,
) ([]*sixdegrees.Artists, int, error)

type GraphBuilder struct {
	NeighborFn NeighborProvider
}

func NewGraphBuilder(np NeighborProvider) *GraphBuilder {
	return &GraphBuilder{NeighborFn: np}
}

// BuildFrom builds the graph via BFS from the start artist.
// EARLY EXIT: stops building the moment we discover the targetID.
func (gb *GraphBuilder) BuildFrom(
	start *sixdegrees.Artists,
	targetID string,
	maxDepth, perArtistLimit int,
	verbose bool,
) (*Graph, error) {

	if gb.NeighborFn == nil {
		return nil, fmt.Errorf("GraphBuilder.NeighborFn is nil")
	}

	g := &Graph{
		Nodes:      make(map[string]*sixdegrees.Artists),
		Edges:      make(map[string][]string),
		TrackEdges: make(map[string]map[string]sixdegrees.Track),
	}

	type frontierItem struct {
		Artist *sixdegrees.Artists
		Depth  int
	}

	queue := []frontierItem{{Artist: start, Depth: 0}}
	seen := map[string]bool{start.ID: true}
	g.Nodes[start.ID] = start

	if verbose {
		fmt.Println("GraphBuilder: starting BFS graph construction")
	}

	for len(queue) > 0 {
		item := queue[0]
		queue = queue[1:]

		if item.Depth >= maxDepth && maxDepth > 0 {
			continue
		}

		neighbors, status, err := gb.NeighborFn(item.Artist, perArtistLimit, verbose)
		if status == 429 {
			return nil, fmt.Errorf("external rate limit during graph build")
		}
		if err != nil {
			return nil, fmt.Errorf("NeighborProvider failed for %s: %w",
				item.Artist.Name, err)
		}

		// Add edges
		for _, nb := range neighbors {
			if nb == nil || nb.ID == "" {
				continue
			}

			// Track node
			if _, ok := g.Nodes[nb.ID]; !ok {
				g.Nodes[nb.ID] = nb
			}

			// Add adjacency
			g.Edges[item.Artist.ID] = append(g.Edges[item.Artist.ID], nb.ID)

			// EARLY EXIT if we've just found the target
			if nb.ID == targetID {
				if verbose {
					fmt.Printf("GraphBuilder: discovered target %s at depth %d\n",
						targetID, item.Depth+1)
				}
				return g, nil
			}

			// enqueue new node
			if !seen[nb.ID] {
				seen[nb.ID] = true
				queue = append(queue, frontierItem{
					Artist: nb,
					Depth:  item.Depth + 1,
				})
			}
		}
	}

	if verbose {
		fmt.Println("GraphBuilder: completed full BFS graph construction")
	}

	return g, nil
}

// BFSOnGraph runs a pure BFS on the already-built Graph.
// No DB calls, no API calls — only adjacency traversal.
func BFSOnGraph(
	g *Graph,
	startID, targetID string,
) ([]string, []sixdegrees.Track, bool) {

	if g == nil || startID == "" || targetID == "" {
		return nil, nil, false
	}

	// Immediate match
	if startID == targetID {
		return []string{startID}, []sixdegrees.Track{}, true
	}

	// Standard BFS queue
	type queueItem struct {
		ID string
	}
	queue := []queueItem{{ID: startID}}

	visited := map[string]bool{startID: true}

	// Maps for reconstructing the path:
	// childID → parentID
	prev := make(map[string]string)

	// childID → track used to reach child
	trackTo := make(map[string]sixdegrees.Track)

	for len(queue) > 0 {
		item := queue[0]
		queue = queue[1:]

		// If we reached the target, reconstruct path immediately.
		if item.ID == targetID {
			return reconstructPathWithTracks(prev, trackTo, startID, targetID)
		}

		// Explore neighbors
		for _, nbID := range g.Edges[item.ID] {
			if !visited[nbID] {
				visited[nbID] = true
				prev[nbID] = item.ID // store parent

				// Store track edge if available
				if g.TrackEdges[item.ID] != nil {
					if t, ok := g.TrackEdges[item.ID][nbID]; ok {
						trackTo[nbID] = t
					}
				}

				queue = append(queue, queueItem{ID: nbID})
			}
		}
	}

	return nil, nil, false // no path
}

func reconstructPathWithTracks(
	prev map[string]string,
	trackTo map[string]sixdegrees.Track,
	startID, targetID string,
) ([]string, []sixdegrees.Track, bool) {

	var path []string
	var tracks []sixdegrees.Track

	cur := targetID
	for cur != "" {
		path = append(path, cur)

		if cur != startID {
			if t, ok := trackTo[cur]; ok {
				tracks = append(tracks, t)
			} else {
				// Missing track means graph didn't store it
				tracks = append(tracks, sixdegrees.Track{})
			}
		}
		cur = prev[cur]
	}

	// Reverse both slices in-place
	for i, j := 0, len(path)-1; i < j; i, j = i+1, j-1 {
		path[i], path[j] = path[j], path[i]
	}
	for i, j := 0, len(tracks)-1; i < j; i, j = i+1, j-1 {
		tracks[i], tracks[j] = tracks[j], tracks[i]
	}

	return path, tracks, true
}
