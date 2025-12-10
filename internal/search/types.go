package search

// TrackInfo used in path steps
type TrackInfo struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	RecordingID   string `json:"recordingID"`
	RecordingName string `json:"recordingName"`
	PhotoURL      string `json:"photoURL"`
}

// Step in the returned path
type Step struct {
	From   string      `json:"from"`
	To     string      `json:"to"`
	Tracks []TrackInfo `json:"tracks"`
	FromID string      `json:"fromID"`
	ToID   string      `json:"toID"`
}

// SearchResponse returned by background BFS and HTTP layer
type SearchResponse struct {
	Start    string `json:"start"`
	Target   string `json:"target"`
	StartID  string `json:"startID"`
	TargetID string `json:"targetID"`
	Hops     int    `json:"hops"`
	Path     []Step `json:"path"`
	Message  string `json:"message,omitempty"`
	Status   int    `json:"status"`
}

// Ticker for frontend live-updates
var SearchTicker = struct {
	Artist string `json:"artist"`
	Count  int    `json:"count"`
	Max    int    `json:"max"`
	Depth  int    `json:"depth"`
}{}

// Cached neighbors per artist for autocomplete expansion
var GlobalNeighborLookup = make(map[string]FrontendStep)

// What the UI expects when requesting neighbor lists
type FrontendStep struct {
	ID        string `json:"ID"`
	Name      string `json:"Name"`
	Neighbors []struct {
		ID     string      `json:"ID"`
		Name   string      `json:"Name"`
		Tracks []TrackInfo `json:"Tracks"`
	} `json:"Neighbors"`
}

// Internal BFS neighbor representation
type NeighborEdge struct {
	Artist *ArtistsWrapper
	Track  []TrackWrapper
	Link   string
}

type SearchRequest struct {
	Start    string `json:"start"`
	Target   string `json:"target"`
	StartID  string `json:"startID"`
	TargetID string `json:"targetID"`
	Depth    int    `json:"depth"`
}

// Minimal local wrappers to avoid sixdegrees import hell
type ArtistsWrapper struct {
	ID   string
	Name string
}

type TrackWrapper struct {
	ID            string
	Name          string
	RecordingID   string
	RecordingName string
	PhotoURL      string
}

type TrackDTO struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	RecordingID   string `json:"recordingID"`
	RecordingName string `json:"recordingName"`
	PhotoURL      string `json:"photoURL"`
}
