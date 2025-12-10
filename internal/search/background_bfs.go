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

// ConvertSteps adapts the anonymous step type returned by SearchArtists
// into the stable Step type used by the HTTP + jobs layers.
func ConvertSteps(in []struct {
	From   string
	Tracks []struct {
		ID            string
		Name          string
		RecordingID   string
		RecordingName string
		PhotoURL      string
	}
	To string
}) []Step {
	out := make([]Step, 0, len(in))

	for _, s := range in {
		step := Step{
			From: s.From,
			To:   s.To,
		}

		for _, t := range s.Tracks {
			step.Tracks = append(step.Tracks, TrackInfo{
				ID:            t.ID,
				Name:          t.Name,
				RecordingID:   t.RecordingID,
				RecordingName: t.RecordingName,
				PhotoURL:      t.PhotoURL,
			})
		}

		out = append(out, step)
	}

	return out
}
