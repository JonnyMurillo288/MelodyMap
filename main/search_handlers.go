package main

import (
	"encoding/json"
	"net/http"

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
	go search.RunBackgroundBFS(job, search.SearchRequest{
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
