package main

// import (
// 	"context"
// 	"fmt"

// 	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
// )

// //
// // ======================================================================
// // MAIN NEIGHBOR PROVIDER (this is the one BFS calls)
// // ======================================================================
// //

// func (s *Store) MusicBrainzNeighborProvider(
// 	ctx context.Context,
// 	a *sixdegrees.Artists,
// 	limit int,
// 	verbose bool,
// ) ([]*NeighborEdge, int, error) {

// 	if a == nil || a.ID == "" {
// 		return nil, 400, fmt.Errorf("artist missing MBID")
// 	}
// 	if limit <= 0 {
// 		limit = 200
// 	}

// 	if verbose {
// 		fmt.Printf("\n=== MusicBrainz Neighbors for %s (%s) ===\n", a.Name, a.ID)
// 	}

// 	neighbors := []*NeighborEdge{}
// 	seen := make(map[string]bool)

// 	//
// 	// ======================================================
// 	// A) CO-RECORDING NEIGHBORS (THE REAL COLLAB GRAPH)
// 	// ======================================================
// 	//

// 	recEdges, err := s.getCoRecordingNeighbors(ctx, a.ID, limit, verbose)
// 	if err != nil {
// 		return nil, 500, fmt.Errorf("co-recording neighbors failed: %w", err)
// 	}

// 	for _, e := range recEdges {
// 		if !seen[e.Artist.ID] {
// 			seen[e.Artist.ID] = true
// 			neighbors = append(neighbors, e)
// 			if len(neighbors) >= limit {
// 				return neighbors, 200, nil
// 			}
// 		}
// 	}

// 	//
// 	// ======================================================
// 	// B) ARTIST-ARTIST RELATIONS (OPTIONAL, SPARSE)
// 	// ======================================================
// 	//

// 	relEdges, err := s.getArtistRelationNeighbors(ctx, a.ID, limit, verbose)
// 	if err != nil {
// 		// not fatal — MB relations are extra anyway
// 		if verbose {
// 			fmt.Println("artist-relation neighbors failed:", err)
// 		}
// 	} else {
// 		for _, e := range relEdges {
// 			if !seen[e.Artist.ID] {
// 				seen[e.Artist.ID] = true
// 				neighbors = append(neighbors, e)
// 				if len(neighbors) >= limit {
// 					return neighbors, 200, nil
// 				}
// 			}
// 		}
// 	}

// 	return neighbors, 200, nil
// }

// //
// // ======================================================================
// // A) REAL COLLABORATIONS — co-recording neighbors
// // ======================================================================
// //

// func (s *Store) getCoRecordingNeighbors(
// 	ctx context.Context,
// 	artistMBID string,
// 	limit int,
// 	verbose bool,
// ) ([]*NeighborEdge, error) {

// 	q := `
// WITH target AS (
//     SELECT id FROM artist WHERE gid = $1
// )
// SELECT DISTINCT
//     a2.gid::text   AS neighbor_mbid,
//     a2.name        AS neighbor_name,
//     r.gid::text    AS recording_mbid,
//     r.name         AS recording_name,
//     t.gid::text    AS track_mbid,
//     t.name         AS track_name,
//     rls.gid::text  AS release_mbid
// FROM recording r
// JOIN artist_credit ac         ON ac.id = r.artist_credit
// JOIN artist_credit_name acn1  ON acn1.artist_credit = ac.id
// JOIN artist_credit_name acn2  ON acn2.artist_credit = ac.id
// JOIN artist a1                ON a1.id = acn1.artist
// JOIN artist a2                ON a2.id = acn2.artist
// JOIN track t                  ON t.recording = r.id
// JOIN medium m                 ON m.id = t.medium
// JOIN release rls              ON rls.id = m.release
// JOIN target ta                ON ta.id = a1.id
// WHERE a2.id != ta.id
// LIMIT $2;
// `
// 	rows, err := s.DB.QueryContext(ctx, q, artistMBID, limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()

// 	results := []*NeighborEdge{}

// 	for rows.Next() {
// 		var nbMBID, nbName string
// 		var recMBID, recName string
// 		var trackMBID, trackName string
// 		var releaseMBID string

// 		if err := rows.Scan(
// 			&nbMBID,
// 			&nbName,
// 			&recMBID,
// 			&recName,
// 			&trackMBID,
// 			&trackName,
// 			&releaseMBID,
// 		); err != nil {
// 			return nil, err
// 		}

// 		results = append(results, &NeighborEdge{
// 			Artist: &sixdegrees.Artists{
// 				ID:   nbMBID,
// 				Name: nbName,
// 			},
// 			Track: sixdegrees.Track{
// 				ID:        trackMBID,
// 				Name:      trackName,
// 				Recording: recMBID,
// 				PhotoURL:  "https://coverartarchive.org/release/" + releaseMBID + "/front",
// 			},
// 			Link: "co-recording",
// 		})
// 	}

// 	if verbose {
// 		fmt.Printf("  Found %d recording-based neighbors.\n", len(results))
// 	}

// 	return results, nil
// }

// //
// // ======================================================================
// // B) OPTIONAL: Artist–Artist direct relations
// // (this is sparse, but adds edges like producers, “member of”, etc.)
// // ======================================================================
// //

// func (s *Store) getArtistRelationNeighbors(
// 	ctx context.Context,
// 	artistMBID string,
// 	limit int,
// 	verbose bool,
// ) ([]*NeighborEdge, error) {

// 	// Get internal numeric ID
// 	var internalID int
// 	if err := s.DB.QueryRowContext(ctx,
// 		`SELECT id FROM artist WHERE gid = $1`,
// 		artistMBID,
// 	).Scan(&internalID); err != nil {
// 		return nil, err
// 	}

// 	q := `
// SELECT
//     a2.gid::text AS mbid,
//     a2.name,
//     lt.name AS link_type
// FROM l_artist_artist laa
// JOIN artist a1 ON laa.entity0 = a1.id
// JOIN artist a2 ON laa.entity1 = a2.id
// JOIN link l ON laa.link = l.id
// JOIN link_type lt ON l.link_type = lt.id
// WHERE a1.id = $1

// UNION ALL

// SELECT
//     a1.gid::text AS mbid,
//     a1.name,
//     lt.name AS link_type
// FROM l_artist_artist laa
// JOIN artist a1 ON laa.entity0 = a1.id
// JOIN artist a2 ON laa.entity1 = a2.id
// JOIN link l ON laa.link = l.id
// JOIN link_type lt ON l.link_type = lt.id
// WHERE a2.id = $1

// LIMIT $2;
// `
// 	rows, err := s.DB.QueryContext(ctx, q, internalID, limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()

// 	results := []*NeighborEdge{}

// 	for rows.Next() {
// 		var mbid, name, linkType string
// 		if err := rows.Scan(&mbid, &name, &linkType); err != nil {
// 			return nil, err
// 		}

// 		results = append(results, &NeighborEdge{
// 			Artist: &sixdegrees.Artists{
// 				ID:   mbid,
// 				Name: name,
// 			},
// 			Track: sixdegrees.Track{}, // no track associated
// 			Link:  linkType,
// 		})
// 	}

// 	if verbose {
// 		fmt.Printf("  Added %d artist-relation neighbors.\n", len(results))
// 	}

// 	return results, nil
// }
