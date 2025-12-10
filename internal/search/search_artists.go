package search

import (
	"fmt"
	"strconv"
	"time"
)

// This version matches your handlers & background BFS.
// No provider or MB client required from caller.
func SearchArtists(
	s *Store,
	start, target string,
	depth, limit int,
	offline bool,
) (int,
	[]Step,
	string,
	int,
	error,
) {

	if start == "" || target == "" {
		return 0, nil, "start or target empty", 400, nil
	}

	startTime := time.Now().UTC().Unix()

	// ------------------------
	// Resolve START
	startArtist, err := ResolveArtistOnce(s, start)
	if err != nil {
		fmt.Println(err)
		return 0, nil, "start artist not found", 404, err
	}

	// ------------------------
	// Resolve TARGET

	targetArtist, err := ResolveArtistOnce(s, target)
	if err != nil {
		return 0, nil, "target artist not found", 404, nil
	}

	// ------------------------
	// BFS call
	helper, _, pathIDs, tracksPerHop, status, ok := RunSearchOptsBFS(
		s,
		startArtist,
		targetArtist,
		depth,
		false, // verbose
		&limit,
		offline,
	)

	if status == 429 {
		return 0, nil, "", 429, fmt.Errorf("rate limit")
	}
	if !ok || len(pathIDs) == 0 {
		msg := fmt.Sprintf("no path found between %q and %q", start, target)
		if depth >= 0 {
			msg += fmt.Sprintf(" within depth %d", depth)
		}
		return 0, nil, msg, 404, nil
	}

	// ------------------------
	// Build []Step
	var steps []Step

	for i := 1; i < len(pathIDs); i++ {
		from := helper.ArtistByID[pathIDs[i-1]]
		to := helper.ArtistByID[pathIDs[i]]

		step := Step{
			From:   from.Name,
			To:     to.Name,
			FromID: from.ID,
			ToID:   to.ID,
		}

		if i-1 < len(tracksPerHop) {
			for _, t := range tracksPerHop[i-1] {
				step.Tracks = append(step.Tracks, TrackInfo{
					ID:            t.ID,
					Name:          t.Name,
					RecordingID:   t.RecordingID,
					RecordingName: t.RecordingName,
					PhotoURL:      t.PhotoURL,
				})
			}
		}

		steps = append(steps, step)
	}

	endTime := time.Now().UTC().Unix()
	fmt.Println("Search took", strconv.FormatInt(endTime-startTime, 10), "sec")

	return len(pathIDs) - 1, steps, "", 200, nil
}
