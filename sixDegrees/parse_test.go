package sixdegrees

import (
	"encoding/json"
	"testing"
)

// Minimal fixtures that mimic the spotify client aggregated shape: { Items: [] }
func TestParseAlbums_IgnoresVariousArtists(t *testing.T) {
	artist := &Artists{Name: "X"}
	payload := map[string]interface{}{
		"items": []interface{}{
			map[string]interface{}{
				"id": "album-1",
				"artists": []interface{}{map[string]interface{}{"name": "Various Artists"}},
			},
			map[string]interface{}{
				"id": "album-2",
				"artists": []interface{}{map[string]interface{}{"name": "X"}},
			},
		},
	}
	b, _ := json.Marshal(payload)
	ids := artist.ParseAlbums(b)
	if len(ids) != 1 || ids[0] != "album-2" {
		t.Fatalf("expected only album-2, got %v", ids)
	}
}

func TestCreateTracks_ParsesArtistsAndIds(t *testing.T) {
	artist := &Artists{Name: "A"}
	h := NewHelper()
	payload := map[string]interface{}{
		"items": []interface{}{
			map[string]interface{}{
				"id": "t1",
				"name": "Track 1",
				"artists": []interface{}{
					map[string]interface{}{"name": "A"},
					map[string]interface{}{"name": "B"},
				},
			},
		},
	}
	b, _ := json.Marshal(payload)
	tracks, _ := artist.CreateTracks(b, h)
	if len(tracks) != 1 {
		t.Fatalf("expected 1 track, got %d", len(tracks))
	}
	if tracks[0].ID != "t1" || tracks[0].Name != "Track 1" {
		t.Fatalf("unexpected track fields: %+v", tracks[0])
	}
	if len(tracks[0].Featured) != 2 {
		t.Fatalf("expected 2 artists in Featured, got %d", len(tracks[0].Featured))
	}
}
