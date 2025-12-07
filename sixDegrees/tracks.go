package sixdegrees

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
)

type Track struct {
	Artist        *Artists
	Name          string
	PhotoURL      string
	ID            string
	RecordingID   string
	RecordingName string
	Featured      []*Artists
}

type trackResponse struct {
	Href  string `json:"href"`
	Items []struct {
		ID      string `json:"id"`
		Name    string `json:"name"`
		Artists []struct {
			ID   string `json:"id"`
			Name string `json:"name"`
		} `json:"artists"`
	} `json:"items"`
	Limit    int         `json:"limit"`
	Next     interface{} `json:"next"`
	Offset   int         `json:"offset"`
	Previous interface{} `json:"previous"`
	Total    int         `json:"total"`
}

type albumResponse struct {
	Items []struct {
		ID      string `json:"id"`
		Artists []struct {
			Name string `json:"name"`
		} `json:"artists"`
	} `json:"items"`
}

type EdgeSnap struct {
	FromID    string
	FromName  string
	ToID      string
	ToName    string
	TrackID   string
	TrackName string
	PhotoURL  string
}

type Helper struct {
	ArtistByID map[string]*Artists
	IDByName   map[string]string

	DistToID map[string]int
	PrevID   map[string]string
	Evidence map[string]EdgeSnap
}

func NewHelper() *Helper {
	return &Helper{
		ArtistByID: make(map[string]*Artists),
		IDByName:   make(map[string]string),

		DistToID: make(map[string]int),
		PrevID:   make(map[string]string),
		Evidence: make(map[string]EdgeSnap),
	}
}

func (h *Helper) ReconstructPathIDs(startID, targetID string) ([]string, []EdgeSnap) {
	fmt.Println("Reconstructing path from", startID, "to", targetID)
	if startID == "" || targetID == "" {
		return nil, nil
	}

	cur := targetID
	var ids []string
	var edges []EdgeSnap

	for cur != "" {
		ids = append(ids, cur)
		if cur != startID {
			if e, ok := h.Evidence[cur]; ok {
				edges = append(edges, e)
			}
		}
		if cur == startID {
			break
		}
		cur = h.PrevID[cur]
		if cur == "" {
			return nil, nil
		}
	}

	// reverse
	for i, j := 0, len(ids)-1; i < j; i, j = i+1, j-1 {
		ids[i], ids[j] = ids[j], ids[i]
	}
	for i, j := 0, len(edges)-1; i < j; i, j = i+1, j-1 {
		edges[i], edges[j] = edges[j], edges[i]
	}

	return ids, edges
}

func (h *Helper) PrintPath(ids []string, edges []EdgeSnap) {
	for i, id := range ids {
		name := ""
		if a := h.ArtistByID[id]; a != nil {
			name = a.Name
		}
		fmt.Printf("%d. %s (%s)\n", i+1, name, id)
		if i < len(edges) {
			e := edges[i]
			fmt.Printf("   └─ [%s] %s → %s\n", e.TrackID, e.TrackName, e.ToName)
		}
	}
}

func newTrack(art *Artists, name, photo, id string, feat []*Artists) Track {
	return Track{
		Artist:   art,
		Name:     name,
		PhotoURL: photo,
		ID:       id,
		Featured: feat,
	}
}

func (a *Artists) CreateTracks(ctx context.Context, data []byte, h *Helper) ([]Track, *Helper) {
	if h == nil {
		h = NewHelper()
	}

	var parsed trackResponse
	_ = json.Unmarshal(data, &parsed)

	if len(parsed.Items) == 0 {
		log.Printf("CreateTracks: no tracks found for %s", a.Name)
		return nil, h
	}

	var tracks []Track
	for _, item := range parsed.Items {

		hasSelf := false
		for _, art := range item.Artists {
			if art.ID == a.ID || art.Name == a.Name {
				hasSelf = true
				break
			}
		}
		if !hasSelf {
			continue
		}

		var feat []*Artists
		for _, art := range item.Artists {
			if art.ID == "" || art.Name == "" {
				continue
			}
			if art.ID == a.ID || art.Name == a.Name {
				continue
			}

			if existing, ok := h.ArtistByID[art.ID]; ok {
				feat = append(feat, existing)
			} else {
				newA := InputArtist(ctx, art.Name)
				if newA != nil {
					h.ArtistByID[newA.ID] = newA
					feat = append(feat, newA)
				}
			}
		}

		if len(feat) == 0 {
			continue
		}

		tracks = append(tracks, newTrack(a, item.Name, "", item.ID, feat))
	}

	return tracks, h
}

func (a *Artists) ParseAlbums(data []byte) []string {
	var parsed albumResponse
	if err := json.Unmarshal(data, &parsed); err != nil {
		log.Printf("ParseAlbums: failed for %s: %v", a.Name, err)
		return nil
	}
	if len(parsed.Items) == 0 {
		log.Printf("ParseAlbums: no albums found for %s", a.Name)
		return nil
	}

	var ids []string
	for _, item := range parsed.Items {
		skip := false
		for _, art := range item.Artists {
			if art.Name == "Various Artists" {
				skip = true
				break
			}
		}
		if !skip {
			ids = append(ids, item.ID)
		}
	}
	return ids
}

func (art *Artists) CheckTracks(db *sql.DB) (int, error) {
	if db == nil {
		return 0, errors.New("nil database connection")
	}
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM Tracks").Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}
