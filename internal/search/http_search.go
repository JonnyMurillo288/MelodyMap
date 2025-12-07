package search

// import (
// 	"fmt"
// 	"time"

// 	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
// )

// // SearchArtists runs the BFS path search between two artists.
// // NOW context-aware.
// func SearchArtists(
// 	start, target string,
// 	depth, limit int,
// 	offline bool,
// ) (int, []step, string, int, error) {

// 	if start == "" || target == "" {
// 		return 0, nil, "start or target empty", 400, nil
// 	}

// 	mb := mb.NewMBClient()
// 	verbose := true
// 	startTime := time.Now().UTC().Unix()

// 	// ----------------------------------------------------
// 	// Resolve START artist
// 	// ----------------------------------------------------
// 	startHits, err := mb.SearchArtist(start)
// 	if err != nil || len(startHits) == 0 {
// 		return 0, nil, fmt.Sprint(err), 404, nil
// 	}
// 	startArtist := &sixdegrees.Artists{
// 		ID:   startHits[0].ID,
// 		Name: startHits[0].Name,
// 	}

// 	// ----------------------------------------------------
// 	// Resolve TARGET artist
// 	// ----------------------------------------------------
// 	targetHits, err := mb.SearchArtist(target)
// 	if err != nil || len(targetHits) == 0 {
// 		return 0, nil, "target artist not found", 404, nil
// 	}
// 	targetArtist := &sixdegrees.Artists{
// 		ID:   targetHits[0].ID,
// 		Name: targetHits[0].Name,
// 	}

// 	fmt.Printf("Running MusicBrainz BFS Search from %q to %q...\n",
// 		startArtist.Name, targetArtist.Name)

// 	// ----------------------------------------------------
// 	// BFS
// 	// ----------------------------------------------------
// 	helper, pathNames, pathIDs, tracksPerHop, status, ok := RunSearchOptsBFS(
// 		startArtist,
// 		targetArtist,
// 		depth,
// 		verbose,
// 		&limit,
// 		offline,
// 	)

// 	if status == 429 {
// 		return 0, nil, "", 429, fmt.Errorf("external rate limit reached")
// 	}
// 	if !ok || len(pathIDs) == 0 {
// 		msg := fmt.Sprintf("no path found between %q and %q", startArtist.Name, targetArtist.Name)
// 		if depth >= 0 {
// 			msg = fmt.Sprintf("%s within depth %d", msg, depth)
// 		}
// 		return 0, nil, msg, 404, nil
// 	}

// 	fmt.Printf("Path found (%d hops)\n", len(pathIDs)-1)
// 	fmt.Println(pathNames)
// 	fmt.Println(pathIDs)

// 	// ----------------------------------------------------
// 	// Build []Step output
// 	// ----------------------------------------------------
// 	var steps []step

// 	for i := 1; i < len(pathIDs); i++ {
// 		fromID := pathIDs[i-1]
// 		toID := pathIDs[i]

// 		from := helper.ArtistByID[fromID]
// 		to := helper.ArtistByID[toID]

// 		var hopTracks []trackInfo

// 		if i-1 < len(tracksPerHop) {
// 			for _, t := range tracksPerHop[i-1] {
// 				hopTracks = append(hopTracks, trackInfo{
// 					ID:            t.ID,
// 					Name:          t.Name,
// 					RecordingID:   t.RecordingID,
// 					RecordingName: t.RecordingName,
// 					PhotoURL:      t.PhotoURL,
// 				})
// 			}
// 		}

// 		steps = append(steps, step{
// 			From:   from.Name,
// 			To:     to.Name,
// 			Tracks: hopTracks,
// 		})
// 	}

// 	endTime := time.Now().UTC().Unix()
// 	fmt.Printf("Analysis took %d seconds\n", endTime-startTime)

// 	return len(pathIDs) - 1, steps, "", 200, nil
// }
