package main

import (
	"fmt"
	"log"
	"testing"
	"time"

	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
)

// -----------------------------------------------------------------------------
// Fake enrichment
// -----------------------------------------------------------------------------

// fakeEnrichArtist mimics the real enrichArtist but injects
// deterministic test data, including one intentionally bad link.
func fakeEnrichArtist(
	a *sixdegrees.Artists,
	h *sixdegrees.Helper,
	target string,
	found *bool,
	verbose bool,
	limit *int,
	offline bool,
) error {
	if offline && len(a.Tracks) > 0 {
		if verbose {
			log.Printf("Offline & already enriched: %s", a.Name)
		}
		return nil
	}

	if verbose {
		log.Printf("[FAKE] Enriching %s...", a.Name)
	}

	switch a.Name {
	case "Artist A":
		// A has a valid collab with B and an invalid one with X.
		a.Tracks = []sixdegrees.Track{
			{
				ID:       "t1",
				Name:     "GoodCollab",
				PhotoURL: "img1.jpg",
				Featured: []*sixdegrees.Artists{
					{Name: "Artist B", ID: "b"},
				},
			},
			{
				ID:       "t2",
				Name:     "FakeCollab",
				PhotoURL: "img2.jpg",
				Featured: []*sixdegrees.Artists{
					{Name: "Artist X", ID: "x"},
				},
			},
		}

	case "Artist B":
		a.Tracks = []sixdegrees.Track{
			{
				ID:       "t3",
				Name:     "CollabB",
				PhotoURL: "img3.jpg",
				Featured: []*sixdegrees.Artists{
					{Name: "Artist C", ID: "c"},
				},
			},
			{
				ID:       "t5",
				Name:     "DupCollab",
				PhotoURL: "img2.jpg",
				Featured: []*sixdegrees.Artists{
					{Name: "Artist A", ID: "a"},
				},
			},
		}

	case "Artist C":
		a.Tracks = []sixdegrees.Track{
			{
				ID:       "t4",
				Name:     "FinalTrack",
				PhotoURL: "img4.jpg",
				Featured: []*sixdegrees.Artists{
					{Name: target, ID: "target"},
				},
			},
		}

	case "Artist X":
		// Fake artist that does NOT feature anyone back.
		a.Tracks = []sixdegrees.Track{}

	default:
		// Others have no new connections.
	}

	time.Sleep(3 * time.Millisecond)
	fmt.Println("----- Fake enriched artist:", a.Name)
	fmt.Println()
	return nil
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

// validateEdges ensures that every EdgeSnap in Helper.Evidence corresponds to
// an actual featured relationship (defensive verification)
func validateEdges(t *testing.T, h *sixdegrees.Helper) {
	for _, e := range h.Evidence {
		from := h.ArtistByID[e.FromID]
		to := h.ArtistByID[e.ToID]

		if from == nil || to == nil {
			t.Errorf("Invalid evidence missing artist: %+v", e)
			continue
		}

		valid := false
		for _, tr := range from.Tracks {
			for _, f := range tr.Featured {
				if f != nil && f.ID == to.ID {
					valid = true
					break
				}
			}
		}
		if !valid {
			t.Errorf("Invalid edge: %s -> %s via %s (%s)",
				from.Name, to.Name, e.TrackName, e.TrackID)
		}
	}
}

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------

// TestBFS_HappyPath confirms the BFS can find a valid route A→B→C→Target.
func TestBFS_HappyPath(t *testing.T) {
	start := &sixdegrees.Artists{Name: "Artist A", ID: "a"}
	target := &sixdegrees.Artists{Name: "Artist Z", ID: "target"}

	h, path, songs, found := RunSearchOptsBFS(start, target, 5, false, nil, true, fakeEnrichArtist)

	fmt.Println("---- HAPPY PATH ----")
	for _, e := range h.Evidence {
		fmt.Printf("%s -> %s via %s\n", e.FromName, e.ToName, e.TrackName)
	}

	if !found {
		t.Fatalf("Expected BFS to find a path A→B→C→Target")
	}
	if len(path) < 3 {
		t.Errorf("Expected multi-hop path, got: %v", path)
	}
	if len(songs) == 0 {
		t.Errorf("Expected some track evidence")
	}

	validateEdges(t, h)
	h.PrintPath(path, songs)
	fmt.Println("------TESTED Happy Path-------")
	fmt.Print("\n\n")
}

// TestBFS_InvalidLinks ensures fake invalid collabs (A→X) are ignored.
func TestBFS_InvalidLinks(t *testing.T) {
	start := &sixdegrees.Artists{Name: "Artist A", ID: "a"}
	target := &sixdegrees.Artists{Name: "Artist Q", ID: "q"} // not reachable

	h, path, _, found := RunSearchOptsBFS(start, target, 5, false, nil, true, fakeEnrichArtist)

	fmt.Println("---- INVALID LINK TEST ----")
	for _, e := range h.Evidence {
		fmt.Printf("%s -> %s via %s\n", e.FromName, e.ToName, e.TrackName)
	}

	if found {
		t.Fatalf("Expected no path, but BFS found one %s", path)
	}
	for _, e := range h.Evidence {
		if e.ToName == "Artist X" {
			t.Fatalf("Invalid edge to Artist X should not appear in Evidence")
		}
	}

	validateEdges(t, h)
	fmt.Println("------TESTED Invalid Links-------")
	fmt.Print("\n\n")

}

func TestBFS_NoDuplicateRevisit(t *testing.T) {
	start := &sixdegrees.Artists{Name: "Artist A", ID: "a"}
	target := &sixdegrees.Artists{Name: "Artist Z", ID: "target"}

	var enrichCount = make(map[string]int)

	// Wrap fakeEnrichArtist to count calls per artist
	countingEnrich := func(
		a *sixdegrees.Artists,
		h *sixdegrees.Helper,
		target string,
		found *bool,
		verbose bool,
		limit *int,
		offline bool,
	) error {
		enrichCount[a.Name]++
		return fakeEnrichArtist(a, h, target, found, verbose, limit, offline)
	}

	h, path, songs, found := RunSearchOptsBFS(start, target, 5, false, nil, true, countingEnrich)

	fmt.Println("---- LOOP TEST ----")
	for _, e := range h.Evidence {
		fmt.Printf("%s -> %s via %s\n", e.FromName, e.ToName, e.TrackName)
	}

	// Sanity: BFS should still find the valid chain A→B→C→Target
	if !found {
		t.Fatalf("Expected BFS to find a valid path, even with loop B→A")
	}

	// Check that Artist A was enriched only once
	if enrichCount["Artist A"] != 1 {
		t.Errorf("Expected Artist A to be enriched once, got %d", enrichCount["Artist A"])
	}

	// Check that no duplicates exist in path or evidence
	seen := make(map[string]bool)
	for _, p := range path {
		if seen[p] {
			t.Errorf("Duplicate artist in path: %s", p)
		}
		seen[p] = true
	}

	// Validate edges are still real
	validateEdges(t, h)

	fmt.Println("Visited enrichment counts:")
	for k, v := range enrichCount {
		fmt.Printf("  %s: %d\n", k, v)
	}

	fmt.Println("\nFinal path:", path)
	fmt.Println("Total evidence:", len(songs))
}
