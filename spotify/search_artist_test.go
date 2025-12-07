package spotify

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"
)

// Must match actual JSON structure you provided
type NeighborLookup map[string]struct {
	ID        string `json:"ID"`
	Name      string `json:"Name"`
	Neighbors []struct {
		ID     string `json:"ID"`
		Name   string `json:"Name"`
		Tracks []struct {
			ID          string `json:"ID"`
			Name        string `json:"Name"`
			RecordingID string `json:"RecordingID"`
			PhotoURL    string `json:"PhotoURL"`
		} `json:"Tracks"`
	} `json:"Neighbors"`
}

func Test_DebugPaths(t *testing.T) {
	wd, _ := os.Getwd()
	fmt.Println("Working directory:", wd)

	_, err1 := os.Stat("./main/authConfig.txt")
	_, err2 := os.Stat("./main/authToken.txt")

	fmt.Printf("authConfig.txt exists? %v\n", err1 == nil)
	fmt.Printf("authToken.txt exists?  %v\n", err2 == nil)
}

// Minimal preflight check: ensures auth files exist
func ensureSpotifyAuthFiles(t *testing.T) {
	files := []string{
		"./main/authConfig.txt",
		"./main/authToken.txt",
	}

	for _, f := range files {
		if _, err := os.Stat(f); err != nil {
			t.Fatalf(
				"Missing Spotify auth file %q. "+
					"Live test requires valid Spotify credentials.\n"+
					"Ensure both authConfig.txt and authToken.txt exist.",
				f,
			)
		}
	}
}

func TestSearchTrackID_FromNeighborLookup(t *testing.T) {
	ensureSpotifyAuthFiles(t)

	raw, err := os.ReadFile("../NeighborLookup.json")
	if err != nil {
		t.Fatalf("failed reading NeighborLookup.json: %v", err)
	}

	var data NeighborLookup
	if err := json.Unmarshal(raw, &data); err != nil {
		t.Fatalf("failed parsing NeighborLookup.json: %v", err)
	}

	lookups := 0
	maxLookups := 8 // prevent hammering Spotify

	for key, block := range data {
		artist := block.Name
		if artist == "" {
			t.Fatalf("missing Name for artist key %q", key)
		}

		for _, neigh := range block.Neighbors {
			// skip if no tracks at all
			if len(neigh.Tracks) == 0 {
				continue
			}

			for _, tr := range neigh.Tracks {

				// validate track name
				if tr.Name == "" {
					continue
				}

				fmt.Printf("\nLookup [%d]: Artist=%q Track=%q\n",
					lookups+1, artist, tr.Name)

				id, err := SearchTrackID(tr.Name, artist)
				if err != nil {
					t.Fatalf("SearchTrackID(%q,%q) failed: %v",
						tr.Name, artist, err)
				}

				if id == "" {
					t.Fatalf("Spotify returned empty ID for %q – %q",
						tr.Name, artist)
				}

				fmt.Printf("  ✓ Spotify ID: %s\n", id)

				lookups++
				if lookups >= maxLookups {
					fmt.Printf("\nHit lookup limit (%d). Test complete.\n", maxLookups)
					return
				}
			}
		}
	}

	if lookups == 0 {
		t.Fatalf(
			"No track lookups executed. " +
				"Does NeighborLookup.json contain Tracks arrays?",
		)
	}

	fmt.Printf("\nFinished with %d real Spotify lookups.\n", lookups)
}
