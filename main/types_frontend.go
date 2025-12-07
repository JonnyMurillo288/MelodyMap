package main

// frontendStep is used by /lookup and /lookupNames
// You must keep it in the main (HTTP/UI) layer—not the search engine.
type frontendStep struct {
	ID        string `json:"ID"`
	Name      string `json:"Name"`
	Neighbors []struct {
		ID     string `json:"ID"`
		Name   string `json:"Name"`
		Tracks []struct {
			ID            string `json:"ID"`
			Name          string `json:"Name"`
			RecordingID   string `json:"RecordingID"`
			RecordingName string `json:"RecordingName"`
			PhotoURL      string `json:"PhotoURL"`
		} `json:"Tracks"`
	} `json:"Neighbors"`
}
