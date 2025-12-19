package search

import (
	"context"
	"fmt"
	"log"
	"time"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

// SearchWithMetrics wraps a search function and saves performance metrics
func SearchWithMetrics(
	s *Store,
	searchType string, // "BFS" or "ASTAR"
	start, target *sixdegrees.Artists,
	maxDepth int,
	verbose bool,
	limit *int,
	offline bool,
	searchFunc func(*Store, *sixdegrees.Artists, *sixdegrees.Artists, int, bool, *int, bool) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool),
) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool) {

	startTime := time.Now()

	// Execute the search
	helper, pathNames, pathIDs, pathTracks, status, found := searchFunc(
		s, start, target, maxDepth, verbose, limit, offline,
	)

	duration := time.Since(startTime)

	// Prepare metric
	metric := SearchMetric{
		SearchType:    searchType,
		StartArtistID: start.ID,
		StartArtist:   start.Name,
		EndArtistID:   target.ID,
		EndArtist:     target.Name,
		NumHops:       len(pathIDs) - 1,
		DurationMs:    duration.Milliseconds(),
		Success:       found && status == 200,
		MaxDepth:      maxDepth,
		CreatedAt:     startTime,
	}

	if !found || status != 200 {
		metric.ErrorMessage = fmt.Sprintf("Search failed with status %d", status)
		metric.NumHops = 0
	}

	// Save metric (non-blocking, don't fail search if this fails)
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		if err := s.SaveSearchMetric(ctx, metric); err != nil {
			log.Printf("Warning: Failed to save search metric: %v", err)
		} else {
			log.Printf("[METRICS] Saved %s search: %s → %s, %d hops, %dms",
				searchType, start.Name, target.Name, metric.NumHops, metric.DurationMs)
		}
	}()

	return helper, pathNames, pathIDs, pathTracks, status, found
}

// RunSearchOptsBFSWithMetrics runs BFS and saves performance metrics
func RunSearchOptsBFSWithMetrics(
	s *Store,
	start, target *sixdegrees.Artists,
	maxDepth int,
	verbose bool,
	limit *int,
	offline bool,
) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool) {
	return SearchWithMetrics(
		s, "BFS", start, target, maxDepth, verbose, limit, offline,
		RunSearchOptsBFS,
	)
}

// RunSearchOptsAStarWithMetrics runs A* and saves performance metrics
func RunSearchOptsAStarWithMetrics(
	s *Store,
	start, target *sixdegrees.Artists,
	maxDepth int,
	verbose bool,
	limit *int,
	offline bool,
) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool) {
	return SearchWithMetrics(
		s, "ASTAR", start, target, maxDepth, verbose, limit, offline,
		RunSearchOptsAStar,
	)
}
