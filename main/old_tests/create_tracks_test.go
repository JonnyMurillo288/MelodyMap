package main

import (
	"fmt"
	"testing"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

// Fake album JSON, simulating Spotify /albums/{id}/tracks output.
var albumIntention = []byte(`{
  "items": [
    {
      "id": "track1",
      "name": "Song with T-Pain",
      "artists": [
        {"id": "watsky", "name": "Watsky"},
        {"id": "tpain", "name": "T-Pain"}
      ]
    },
    {
      "id": "track2",
      "name": "Song with Abhi",
      "artists": [
        {"id": "watsky", "name": "Watsky"},
        {"id": "abhi", "name": "Abhi"}
      ]
    }
  ]
}`)

func TestCreateTracks_AlbumLevelLeakage(t *testing.T) {
	a := &sixdegrees.Artists{ID: "abhi", Name: "Abhi"}
	h := sixdegrees.NewHelper()

	tracks, _ := a.CreateTracks(albumIntention, h)

	if len(tracks) == 0 {
		t.Fatalf("expected tracks for Abhi, got none")
	}

	// Collect all featured artist IDs from Abhi’s created tracks
	got := make(map[string]bool)
	for _, tr := range tracks {
		for _, f := range tr.Featured {
			got[f.Name] = true
		}
	}
	fmt.Println("Got:", got)

	// Abhi should only connect to Watsky
	if !got["Watsky"] {
		fmt.Println("Got featured artists:", got)
		t.Errorf("expected Watsky to be a featured connection for Abhi")
	}
	// Should NOT connect to T-Pain (since Abhi & T-Pain never shared a track)
	if got["T-Pain"] {
		t.Errorf("unexpected false link: Abhi connected to T-Pain")
	}
}

func TestCreateTracks_TPainConnections(t *testing.T) {
	a := &sixdegrees.Artists{ID: "tpain", Name: "T-Pain"}
	h := sixdegrees.NewHelper()

	tracks, _ := a.CreateTracks(albumIntention, h)
	if len(tracks) == 0 {
		t.Fatalf("expected tracks for T-Pain, got none")
	}

	got := make(map[string]bool)
	for _, tr := range tracks {
		for _, f := range tr.Featured {
			got[f.Name] = true
		}
	}
	fmt.Println("Got:", got)
	if !got["Watsky"] {
		t.Errorf("expected Watsky to be a featured connection for T-Pain")
	}
	if got["Abhi"] {
		t.Errorf("unexpected false link: T-Pain connected to Abhi")
	}
}
