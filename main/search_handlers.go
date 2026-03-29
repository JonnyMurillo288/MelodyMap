package main

import (
	"encoding/json"
	"net/http"
	"os"
	"strings"

	"github.com/Jonnymurillo288/MelodyMap/internal/jobs"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
)

var GlobalNeighborLookup = make(map[string]frontendStep)

type searchRequest struct {
	Start  string `json:"start"`
	Target string `json:"target"`
	Depth  int    `json:"depth"`
}

// ------------------------------------------------------------
// POST /api/search/start
// ------------------------------------------------------------
func startSearchHandler(w http.ResponseWriter, r *http.Request) {
	var req searchRequest
	json.NewDecoder(r.Body).Decode(&req)

	// Create job
	job := jobs.Manager.CreateJob(req.Start, req.Target)

	// Launch background BFS with the correct request type
	// THIS IS WHERE YOU UPDATE IF RETURNING TO A NEW SEARCH FUNCTION
	go search.RunBackgroundAStar(job, search.SearchRequest{
		Start:  req.Start,
		Target: req.Target,
		Depth:  req.Depth,
	})

	json.NewEncoder(w).Encode(map[string]string{
		"jobID": job.ID,
	})
}

// ------------------------------------------------------------
// GET /api/search/status?id=<jobID>
// ------------------------------------------------------------
func searchStatusHandler(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("jobID")

	job, ok := jobs.Manager.Get(id)
	if !ok {
		http.Error(w, "job not found", http.StatusNotFound)
		return
	}

	json.NewEncoder(w).Encode(job)
}

// ------------------------------------------------------------
// GET /api/artist/neighbors?name=<artistName>
// ------------------------------------------------------------
// This function calls the database and returns the direct neighbors of a given artist ID
func artistNeighborsHandler(w http.ResponseWriter, r *http.Request) {
	name := strings.ToLower(r.URL.Query().Get("name"))
	// Returns the artist: id, name
	// Neighbor returns: id, name, tracks[]
	// Track returns: id, name, photoURL
	q := `
		WITH input_artist AS (
			SELECT id, gid::text, name
			FROM artist
			WHERE lower(artist.name) = $1
		)
		SELECT 
			ia.gid::text,
			ia.name,
			a2.gid::text,
			a2.name,
			r.gid::text,
			r.name,
			rl.gid::text,
			t.name
		FROM artist_collab c
		JOIN input_artist ia       ON ia.id = c.artist_id
		JOIN recording r           ON r.id = c.recording_id
		JOIN track t               ON t.recording = r.id
		JOIN medium m              ON m.id = t.medium
		JOIN release rl            ON rl.id = m.release
		JOIN artist a2             ON a2.id = c.neighbor_artist_id
		ORDER BY a2.gid;
		`
	// Need to return type FrontEndStep which contains ID, Name, Neighbors
	con, _ := search.Open(os.Getenv("DB_PATH"))
	// This will return rows, need to scan into FrontEndStep
	rows, err := con.DB.Query(q, name)
	// fmt.Println("Executing neighbor query for artist name:", name)
	// fmt.Println(err, "[TESTING] returned from neighbor query")
	if err != nil {
		http.Error(w, "database error", http.StatusInternalServerError)
		return
	}

	var prevArtistID string
	var prevNeighborObj struct {
		ID     string             `json:"ID"`
		Name   string             `json:"Name"`
		Tracks []search.TrackInfo `json:"Tracks"`
	}
	var step search.FrontendStep
	var debugNumberOfNeighbors int
	var trackInfoArtistMap = make(map[string][]search.TrackInfo)
	// If artist ID changes, create new step object and append to steps if the artist ID is the same as prevArtistID
	// We are only getting one artist, and all of their neighbors. So it should just be one frontendStep and list of neighbors.
	for rows.Next() {
		var neighborID, neighborName string
		var recordingID, recordingName string
		var releaseID string
		var trackObj search.TrackInfo
		var trackID string // Including trackID for the lookup because you can have multiple recordings that are part of the same track. ONly want unique tracks

		if err := rows.Scan(&step.ID, &step.Name, &neighborID, &neighborName, &recordingID, &recordingName, &releaseID, &trackID); err != nil {
			// fmt.Println(err, "[TESTING] error scanning neighbor row")
			http.Error(w, "database error", http.StatusInternalServerError)
			return
		}

		step.Name = name // there should be only one name per artist ID
		// If we have a new neighbor than previously then create a new track set and append previous neighbor to frontendStep.Neighbors
		// If out neighborID is the same as the last neighborID then we append the track information to the current t
		// If our neighborID is different from the last neighborID then we append the track information to the
		if prevArtistID != "" && prevArtistID != neighborID {
			// Create a new neighbor struct

			// 1. Append the previous neighbor to step.Neighbors
			// Skip the first append since prevArtistID is empty
			if debugNumberOfNeighbors != 0 {
				step.Neighbors = append(step.Neighbors, prevNeighborObj)
			}
			debugNumberOfNeighbors++
			trackInfoArtistMap[prevArtistID] = prevNeighborObj.Tracks

			// 2. Create a new neighbor struct
			neighbor := struct {
				ID     string             `json:"ID"`
				Name   string             `json:"Name"`
				Tracks []search.TrackInfo `json:"Tracks"`
			}{
				ID:     neighborID,
				Name:   neighborName,
				Tracks: []search.TrackInfo{},
			}
			prevNeighborObj = neighbor
			trackObj = search.TrackInfo{
				ID:            trackID,
				Name:          recordingName,
				RecordingID:   recordingID,
				RecordingName: recordingName,
				PhotoURL:      "https://coverartarchive.org/release/" + releaseID + "/front",
			}
			prevNeighborObj.Tracks = append(prevNeighborObj.Tracks, trackObj)
			// fmt.Println("[TESTING] Appended neighbor:", neighborName)
			// fmt.Println("[TESTING] Total neighbors so far:", debugNumberOfNeighbors)
		}

		if prevArtistID == neighborID {
			// Same neighbor, just append track
			trackObj = search.TrackInfo{
				ID:            recordingID,
				Name:          recordingName,
				RecordingID:   recordingID,
				RecordingName: recordingName,
				PhotoURL:      "https://coverartarchive.org/release/" + releaseID + "/front",
			}
			if !neighborIDContainsTrack(neighborID, trackObj.ID, trackInfoArtistMap) {
				trackInfoArtistMap[neighborID] = append(trackInfoArtistMap[neighborID], trackObj)
				prevNeighborObj.Tracks = append(prevNeighborObj.Tracks, trackObj)
			}
		}
		// 3. Update prevArtistID
		prevArtistID = neighborID
	}
	// 4. After loop ends, append the last neighbor
	step.Neighbors = append(step.Neighbors, prevNeighborObj)
	debugNumberOfNeighbors++
	// fmt.Println("[TESTING] Total neighbors found:", debugNumberOfNeighbors)

	defer rows.Close()
	if err != nil {
		// fmt.Println(err, "[TESTING] Error in the rows somewhere")
		http.Error(w, "database error", http.StatusInternalServerError)
		return
	}

	// case for no artist found, just return empty ID, handle in frontend
	if step.ID == "" {
		step = search.FrontendStep{
			ID:   "",
			Name: "",
			Neighbors: []struct {
				ID     string             `json:"ID"`
				Name   string             `json:"Name"`
				Tracks []search.TrackInfo `json:"Tracks"`
			}{},
		}
	}

	// Return the steps
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(step)
}

// The neighbor ID within the trackInfoArtitMap
func neighborIDContainsTrack(artist, trackid string, trackInfoArtistMap map[string][]search.TrackInfo) bool {
	return trackInfoArtistMap[artist] != nil && containsTrack(trackInfoArtistMap[artist], trackid)
}

func containsTrack(tracks []search.TrackInfo, trackid string) bool {
	for _, t := range tracks {
		if t.ID == trackid {
			return true
		}
	}
	return false
}
