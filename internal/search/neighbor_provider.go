package search

import (
	"context"
	"fmt"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

type MusicBrainzSearcher interface {
	SearchArtist(name string) ([]mbArtist, error)
}

func (s *Store) MusicBrainzNeighborProvider(
	a *sixdegrees.Artists,
	limit int,
	verbose bool,
) ([]*NeighborEdge, int, error) {

	if a == nil || a.ID == "" {
		return nil, 400, fmt.Errorf("artist missing MBID")
	}

	if limit <= 0 {
		limit = 200
	}

	// Make sure to return the variables below
	// nbID, nbName, recID, recName, trackID, trackName, releaseID
	new_q := `
		WITH input_artist AS (
			SELECT id
			FROM artist
			WHERE gid = $1
		)
		SELECT 
			a2.gid::text,
			a2.name,
			r.gid::text,
			r.name,
			t.gid::text,
			t.name,
			rl.gid::text
		FROM artist_collab c
		JOIN input_artist ia       ON ia.id = c.artist_id
		JOIN recording r           ON r.id = c.recording_id
		JOIN track t               ON t.recording = r.id
		JOIN medium m              ON m.id = t.medium
		JOIN release rl            ON rl.id = m.release
		JOIN artist a2             ON a2.id = c.neighbor_artist_id
		LIMIT $2;
	`

	rows, err := s.DB.QueryContext(context.Background(), new_q, a.ID, limit)
	if err != nil {
		return nil, 500, err
	}
	defer rows.Close()

	// group by neighbor ID
	// group by neighbor ID
	grouped := make(map[string]*NeighborEdge)
	// visited should be PER NEIGHBOR, not global
	visitedByNeighbor := make(map[string]map[string]bool)

	for rows.Next() {
		var nbID, nbName string
		var recID, recName string
		var trackID, trackName string
		var releaseID string

		if err := rows.Scan(
			&nbID, &nbName,
			&recID, &recName,
			&trackID, &trackName,
			&releaseID,
		); err != nil {
			return nil, 500, err
		}
		if trackID == "" {
			fmt.Println("Skipping track with empty ID for neighbor artist:", nbName)
			continue
		}

		// if neighbor not seen before, create struct
		if _, exists := grouped[nbID]; !exists {
			grouped[nbID] = &NeighborEdge{
				Artist: &ArtistsWrapper{
					ID:   nbID,
					Name: nbName,
				},
				Track: []TrackWrapper{},
				Link:  "track-collaboration",
			}
			visitedByNeighbor[nbID] = make(map[string]bool)
		}

		// correct dedupe: per-neighbor
		if !visitedByNeighbor[nbID][trackID] {
			grouped[nbID].Track = append(grouped[nbID].Track, TrackWrapper{
				ID:            trackID,
				Name:          trackName,
				RecordingID:   recID,
				RecordingName: recName,
				PhotoURL:      "https://coverartarchive.org/release/" + releaseID + "/front",
			})
			visitedByNeighbor[nbID][trackID] = true
		}
	}

	// convert map → slice
	out := make([]*NeighborEdge, 0, len(grouped))
	for _, v := range grouped {
		out = append(out, v)
	}

	return out, 200, nil
}
