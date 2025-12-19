package search

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
