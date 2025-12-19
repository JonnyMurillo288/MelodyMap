package search

import (
	"github.com/Jonnymurillo288/MelodyMap/internal/jobs"
)

// RunBackgroundBFS executes a search in the background and updates a Job.
func RunBackgroundBFS(job *jobs.Job, req SearchRequest) {
	jobs.Manager.Update(job.ID, func(j *jobs.Job) {
		j.Status = jobs.StatusRunning
	})

	hops, stepsList, msg, status, err := SearchArtists(
		nil,
		req.Start,
		req.Target,
		req.Depth,
		3000,
		false,
	)

	// stepsList IS ALREADY []Step
	resp := SearchResponse{
		Start:   req.Start,
		Target:  req.Target,
		Hops:    hops,
		Path:    stepsList,
		Message: msg,
		Status:  status,
	}

	if err != nil || status != 200 {
		jobs.Manager.Update(job.ID, func(j *jobs.Job) {
			j.Status = jobs.StatusError
			j.Error = resp.Message
		})
		return
	}

	jobs.Manager.Update(job.ID, func(j *jobs.Job) {
		j.Status = jobs.StatusFinished
		j.Result = resp
	})
}
