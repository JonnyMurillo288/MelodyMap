package search

import (
	"fmt"
	"log"
	"strings"
	"time"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

//
// ============================================================
// BFS Search (pure backend, writes GlobalNeighborLookup)
// ============================================================
//

func RunSearchOptsBFS(
	start, target *sixdegrees.Artists,
	maxDepth int,
	verbose bool,
	limit *int,
	offline bool,
) (*sixdegrees.Helper, []string, []string, [][]sixdegrees.Track, int, bool) {

	s, err := Open("")
	if err != nil {
		log.Printf("RunSearchOptsBFS: failed to open DB: %v", err)
		return nil, nil, nil, nil, 500, false
	}
	defer s.Close()

	if start == nil || start.ID == "" || target == nil || target.ID == "" {
		return nil, nil, nil, nil, 400, false
	}

	// trivial case
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

	// neighbor cap per artist
	perArtistLimit := 5000
	if limit != nil && *limit > 0 {
		perArtistLimit = *limit
	}
	if perArtistLimit > 20000 {
		perArtistLimit = 20000
	}

	const maxSearchDuration = 3000 * time.Second
	startTime := time.Now()

	h := sixdegrees.NewHelper()
	h.ArtistByID[start.ID] = start
	h.IDByName[start.Name] = start.ID

	type queueItem struct {
		A     *sixdegrees.Artists
		Depth int
	}

	queue := []queueItem{{A: start, Depth: 0}}
	visited := map[string]bool{start.ID: true}

	prev := make(map[string]string)
	prevTracks := make(map[string][]sixdegrees.Track)

	var (
		foundTarget     bool
		finalPathIDs    []string
		finalPathNames  []string
		finalPathTracks [][]sixdegrees.Track
	)
	var expandedCount = 0

	log.Println()
	for len(queue) > 0 {
		expandedCount = 0
		// pop
		item := queue[0]
		queue = queue[1:]
		SearchTicker.Artist = item.A.Name
		// Only update if it goes up, do not revert down
		if item.Depth > SearchTicker.Depth {
			SearchTicker.Depth = item.Depth
		}

		// timeout
		if time.Since(startTime) > maxSearchDuration {
			return h, nil, nil, nil, 504, false
		}

		// depth guard
		if maxDepth > 0 && item.Depth > maxDepth {
			continue
		}

		if verbose {
			log.Printf("[BFS] Expanding %s at depth %d", item.A.Name, item.Depth)
		}

		neighbors, status, err := s.MusicBrainzNeighborProvider(
			item.A,
			perArtistLimit,
			offline,
		)
		if status == 429 {
			return h, nil, nil, nil, 429, false
		}
		if err != nil {
			if verbose {
				log.Printf("[BFS] error from provider for %s: %v", item.A.Name, err)
			}
			continue
		}

		if verbose {
			log.Printf("[BFS] Found %d neighbors for %s", len(neighbors), item.A.Name)
		}

		// ============================
		// Build FrontendStep for /lookup
		// ============================
		step := FrontendStep{
			ID:   item.A.ID,
			Name: item.A.Name,
			Neighbors: make([]struct {
				ID     string      `json:"ID"`
				Name   string      `json:"Name"`
				Tracks []TrackInfo `json:"Tracks"`
			}, 0, len(neighbors)),
		}

		SearchTicker.Max = len(neighbors)
		for _, nb := range neighbors {
			if nb == nil || nb.Artist == nil || nb.Artist.ID == "" {
				continue
			}

			expandedCount++
			SearchTicker.Count = expandedCount

			// Convert ArtistsWrapper → sixdegrees.Artists
			convertedArtist := convertToArtist(nb.Artist)

			// Convert TrackWrapper → []sixdegrees.Track
			tracks := convertTrackList(nb.Track)

			childID := convertedArtist.ID

			// keep helper maps populated
			if _, ok := h.ArtistByID[childID]; !ok {
				h.ArtistByID[childID] = convertedArtist
			}
			if convertedArtist.Name != "" {
				h.IDByName[convertedArtist.Name] = childID
			}

			// Deduplicate within this edge
			tracks = sixdegrees.DeduplicateTracks(tracks, 0.65, false)

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

			edgeKey := item.A.ID + "->" + childID

			// first time we see this child
			if _, seen := prev[childID]; !seen {
				prev[childID] = item.A.ID
				prevTracks[edgeKey] = tracks
				visited[childID] = true

				queue = append(queue, queueItem{
					A:     convertedArtist,
					Depth: item.Depth + 1,
				})
			}

			// Hit target
			if childID == target.ID {
				foundTarget = true

				finalPathIDs = reconstructIDPath(prev, start.ID, target.ID)

				// names
				finalPathNames = make([]string, 0, len(finalPathIDs))
				for _, id := range finalPathIDs {
					if art, ok := h.ArtistByID[id]; ok {
						finalPathNames = append(finalPathNames, art.Name)
					} else {
						finalPathNames = append(finalPathNames, id)
					}
				}

				// tracks per hop
				finalPathTracks = make([][]sixdegrees.Track, 0, len(finalPathIDs)-1)
				for i := 1; i < len(finalPathIDs); i++ {
					from := finalPathIDs[i-1]
					to := finalPathIDs[i]
					eKey := from + "->" + to
					finalPathTracks = append(finalPathTracks, prevTracks[eKey])
				}

				queue = nil
				break
			}
		}

		// store the neighbors for this artist into the global lookup
		if len(step.Neighbors) > 0 {
			key := strings.ToLower(item.A.Name)
			GlobalNeighborLookup[key] = step
		}

		if foundTarget {
			break
		}
	}

	if !foundTarget {
		return h, nil, nil, nil, 404, false
	}

	return h, finalPathNames, finalPathIDs, finalPathTracks, 200, true
}

//
// ============================================================
// Helpers
// ============================================================
//

func convertToArtist(a *ArtistsWrapper) *sixdegrees.Artists {
	if a == nil {
		return nil
	}
	return &sixdegrees.Artists{
		ID:     a.ID,
		Name:   a.Name,
		Tracks: []sixdegrees.Track{},
		Genres: map[string]int{},
	}
}

func debugTrackNames(tracks []sixdegrees.Track) string {
	parts := make([]string, 0, len(tracks))
	for _, t := range tracks {
		parts = append(parts, fmt.Sprintf("%s (%s)", t.Name, t.RecordingID))
	}
	return strings.Join(parts, " | ")
}

func reconstructIDPath(prev map[string]string, startID, targetID string) []string {
	var path []string
	for at := targetID; at != ""; at = prev[at] {
		path = append(path, at)
		if at == startID {
			break
		}
	}
	for i, j := 0, len(path)-1; i < j; i, j = i+1, j-1 {
		path[i], path[j] = path[j], path[i]
	}
	if len(path) == 0 || path[0] != startID {
		return nil
	}
	return path
}

func convertTrackList(in []TrackWrapper) []sixdegrees.Track {
	out := make([]sixdegrees.Track, 0, len(in))
	for _, t := range in {
		out = append(out, sixdegrees.Track{
			ID:            t.ID,
			Name:          t.Name,
			RecordingID:   t.RecordingID,
			RecordingName: t.RecordingName,
			PhotoURL:      t.PhotoURL,
		})
	}
	return out
}
