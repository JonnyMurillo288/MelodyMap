package main

// // ExpandNeighbors
// // --------------------------------------------------------------
// // This is the refactored “neighbor extraction” function.
// //
// // It replaces your old `enrichArtist`.
// // It does NOT do BFS or search logic. It ONLY:
// //
// //  1. Loads tracks/albums from DB (fast path)
// //  2. Fetches missing albums/tracks from API (slow path)
// //  3. Creates Track objects
// //  4. Writes all DB data (upserts)
// //  5. Extracts featured collaborators
// //  6. Returns a slice of collaborating artists (neighbors)
// //
// // This is fully compatible with GraphBuilder.
// func (s *Store) ExpandNeighbors(
// 	a *sixdegrees.Artists,
// 	limit int,
// 	verbose bool,
// ) ([]*NeighborEdge, error) {
// 	edges := make([]*NeighborEdge, 0, limit)

// 	ctx := context.Background()
// 	neighbors := []*sixdegrees.Artists{}

// 	if verbose {
// 		fmt.Printf("\n=== Expanding neighbors for %s (%s) ===\n", a.Name, a.ID)
// 	}

// 	// SAFETY: enforce reasonable default
// 	if limit <= 0 {
// 		limit = 15
// 	}

// 	// ---------------------------------------------------------
// 	// 1) TRACKS FROM DB (fast path)
// 	// ---------------------------------------------------------
// 	dbTracks, err := s.ListTracksByArtistID(ctx, a.ID, 1e6)
// 	if err == nil && len(dbTracks) > 0 {
// 		tracks, _ := s.DBTracksToTracks(dbTracks)
// 		a.Tracks = append(a.Tracks, tracks...)
// 		if verbose {
// 			log.Printf("    Loaded %d DB tracks for %s", len(tracks), a.Name)
// 		}
// 	}

// 	// ---------------------------------------------------------
// 	// 2) Get Albums (DB-first → API remainder)
// 	// ---------------------------------------------------------
// 	albums, _, err := s.getArtistAlbumsMergedCached(a.ID, limit, false, verbose)
// 	if err != nil {
// 		return nil, fmt.Errorf("ExpandNeighbors: failed to load albums: %w", err)
// 	}

// 	if verbose {
// 		log.Printf("    Found %d merged albums for %s\n", len(albums.Items), a.Name)
// 	}

// 	// ---------------------------------------------------------
// 	// 3) For each album → fetch tracks, create collaboration edges
// 	// ---------------------------------------------------------
// 	for _, al := range albums.Items {

// 		// Upsert album
// 		_ = s.UpsertAlbum(ctx, DBAlbum{
// 			ID:              al.ID,
// 			PrimaryArtistID: sqlNullString(a.ID),
// 		})

// 		// Record album artists
// 		for _, art := range al.Artists {
// 			_ = s.UpsertArtist(ctx, DBArtist{Name: art.Name})
// 			_ = s.AddAlbumArtist(ctx, al.ID, art.Name)
// 		}

// 		// -----------------------------------------------------
// 		// 3a. Fetch tracks for the album (DB-first + API remainder)
// 		// -----------------------------------------------------
// 		trackBody, err := s.fetchAlbumTracksCached(a, al.ID, limit, false, verbose)
// 		if err != nil {
// 			continue
// 		}

// 		// Convert API/DB response to Track struct
// 		j, _ := json.Marshal(trackBody)
// 		tracks, _ := a.CreateTracks(j, nil)

// 		if len(tracks) == 0 {
// 			continue
// 		}

// 		for _, t := range tracks {

// 			// -------------------------------------------------
// 			//  IMPORTANT: Only process tracks where THIS artist appears
// 			// -------------------------------------------------
// 			if !trackHasArtist(t, a) {
// 				continue
// 			}

// 			// Upsert track into DB
// 			_ = s.UpsertTrack(ctx, createDBTrack(t, al.ID))

// 			// Upsert primary artist
// 			if t.Artist != nil && t.Artist.ID != "" {
// 				_ = s.UpsertArtist(ctx, createDBArtist(*t.Artist))
// 				_ = s.AddTrackArtist(ctx, t.ID, t.Artist.ID, "primary")
// 			}

// 			// -------------------------------------------------
// 			// FEATURED ARTISTS = graph edges = neighbors
// 			// -------------------------------------------------
// 			for _, f := range t.Featured {
// 				if f == nil || f.ID == "" {
// 					continue
// 				}

// 				// DB writes
// 				_ = s.UpsertArtist(ctx, createDBArtist(*f))
// 				_ = s.AddTrackArtist(ctx, t.ID, f.ID, "featured")

// 				neighbors = append(neighbors, f)
// 				edges = append(edges, &NeighborEdge{
// 					Artist: f, // <-- the featured collaborator
// 					Track:  t, // <-- the connecting track
// 				})
// 			}
// 		}
// 	}

// 	// Avoid rate-limit cascades
// 	time.Sleep(10 * time.Millisecond)

// 	return dedupeArtists(edges), nil
// }

// // -------------------------------------------------------
// // Helper: check if a track contains the main artist
// // -------------------------------------------------------

// func trackHasArtist(t sixdegrees.Track, a *sixdegrees.Artists) bool {
// 	// primary
// 	if t.Artist != nil && t.Artist.ID == a.ID {
// 		return true
// 	}

// 	// featured
// 	for _, f := range t.Featured {
// 		if f != nil && f.ID == a.ID {
// 			return true
// 		}
// 	}

// 	return false
// }

// // -------------------------------------------------------
// // Helper: deduplicate neighbor list
// // -------------------------------------------------------

// func dedupeArtists(in []*NeighborEdge) []*NeighborEdge {
// 	out := make([]*NeighborEdge, 0, len(in))
// 	seen := map[string]bool{}

// 	for _, a := range in {
// 		if a.Artist == nil || a.Artist.ID == "" {
// 			continue
// 		}
// 		if !seen[a.Artist.ID] {
// 			seen[a.Artist.ID] = true
// 			out = append(out, a)
// 		}
// 	}

// 	return out
// }
