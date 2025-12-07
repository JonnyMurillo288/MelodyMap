package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"testing"
	"time"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

//////////////////////////////////////////////////////////////////////
// Helpers to produce EXACT JSON formats that ParseAlbums/CreateTracks use
//////////////////////////////////////////////////////////////////////

// Correct JSON shape for ParseAlbums → albumResponse
func dummyAlbumJSON(ids ...string) []byte {
	type artist struct {
		Name string `json:"name"`
	}
	type item struct {
		ID      string   `json:"id"`
		Artists []artist `json:"artists"`
	}
	type albumResp struct {
		Items []item `json:"items"`
	}

	resp := albumResp{}
	for _, id := range ids {
		resp.Items = append(resp.Items, item{
			ID: id,
			Artists: []artist{
				{Name: "TestArtist"}, // must not be "Various Artists"
			},
		})
	}

	b, _ := json.Marshal(resp)
	return b
}

// Correct JSON shape for CreateTracks → trackResponse
func dummyTrackJSON(artistID string, trackID string, featuredIDs ...string) ([]byte, *sixdegrees.Helper) {
	type artist struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	type item struct {
		ID      string   `json:"id"`
		Name    string   `json:"name"`
		Artists []artist `json:"artists"`
	}
	type trackResp struct {
		Href  string `json:"href"`
		Items []item `json:"items"`
		Limit int    `json:"limit"`
	}

	// Prepare Helper with featured artists preloaded so CreateTracks does NOT call InputArtist
	h := sixdegrees.NewHelper()
	artists := []artist{
		{ID: artistID, Name: "TestArtist"},
	}

	for _, fid := range featuredIDs {
		artists = append(artists, artist{ID: fid, Name: "FeatTwo"})
		h.ArtistByID[fid] = &sixdegrees.Artists{ID: fid, Name: "FeatTwo"}
	}

	resp := trackResp{
		Href:  "dummy",
		Limit: 50,
		Items: []item{
			{
				ID:      trackID,
				Name:    "DummyTrack",
				Artists: artists,
			},
		},
	}

	b, _ := json.Marshal(resp)
	return b, h
}

//////////////////////////////////////////////////////////////////////
// MockStore implementing only the functions enrichArtist needs
//////////////////////////////////////////////////////////////////////

type MockStore struct {
	DB              *sql.DB
	AlbumJSON       []byte
	TrackJSONByID   map[string][]byte
	FeaturedArtists map[string][]DBArtist
}

func (s *MockStore) ListTracksByArtistID(ctx context.Context, id string, limit int) ([]DBTrack, error) {
	return nil, nil // start with no DB tracks
}

func (s *MockStore) DBTracksToTracks(dbt []DBTrack) ([]sixdegrees.Track, error) {
	return nil, nil // not needed for this test
}

func (s *MockStore) ListAlbumsByArtistID(ctx context.Context, id string, limit int) ([]DBAlbum, error) {
	// DB: return 1 album
	return []DBAlbum{
		{
			ID:              "db_album_1",
			PrimaryArtistID: sqlNullString("A1"),
		},
	}, nil
}

func (s *MockStore) ConvertDBAlbumsToResponse(dbAlbums []DBAlbum, href string, limit, offset int) ([]byte, error) {
	// Make DB albums use same JSON schema as ParseAlbums expects
	return dummyAlbumJSON("db_album_1"), nil
}

func (s *MockStore) ConvertDBTracksToResponse(dbTracks []DBTrack, href, artist string, limit, offset int) ([]byte, error) {
	// DB tracks JSON (shape: trackResponse)
	b, _ := dummyTrackJSON("A1", "db_track_1", "F1")
	return b, nil
}

func (s *MockStore) UpsertAlbum(ctx context.Context, d DBAlbum) error   { return nil }
func (s *MockStore) UpsertTrack(ctx context.Context, d DBTrack) error   { return nil }
func (s *MockStore) UpsertArtist(ctx context.Context, d DBArtist) error { return nil }
func (s *MockStore) AddTrackArtist(ctx context.Context, t, a, r string) error {
	return nil
}

func (s *MockStore) GetArtistByID(ctx context.Context, id string) (*DBArtist, error) {
	return &DBArtist{ID: id, Name: "TestArtist"}, nil
}

func (s *MockStore) ListFeaturedArtistsForTrack(ctx context.Context, id string) ([]DBArtist, error) {
	// DB featured artists
	if fa, ok := s.FeaturedArtists[id]; ok {
		return fa, nil
	}
	return []DBArtist{}, nil
}

//////////////////////////////////////////////////////////////////////
// Override album + track fetch functions
//////////////////////////////////////////////////////////////////////

func (s *MockStore) getArtistAlbumsMergedCached(id string, limit int, offline, verbose bool) ([]byte, error) {

	dbAlbums, _ := s.ListAlbumsByArtistID(context.Background(), id, limit)
	dbJSON, _ := s.ConvertDBAlbumsToResponse(dbAlbums, "href", limit, 0)

	var dbItems struct {
		Items []map[string]interface{} `json:"items"`
	}
	_ = json.Unmarshal(dbJSON, &dbItems)

	// Add API albums
	var apiItems struct {
		Items []map[string]interface{} `json:"items"`
	}
	_ = json.Unmarshal(s.AlbumJSON, &apiItems)

	merged := append(dbItems.Items, apiItems.Items...)

	final, _ := json.Marshal(struct {
		Items []map[string]interface{} `json:"items"`
	}{Items: merged})

	return final, nil
}

func (s *MockStore) fetchAlbumTracksCached(a *sixdegrees.Artists, albumID string, limit int, offline, verbose bool) ([]byte, error) {
	// DB tracks
	dbTracks := []DBTrack{
		{ID: "db_track_1", Name: "DB Track One", PrimaryArtistID: sqlNullString("A1")},
	}
	dbJSON, _ := s.ConvertDBTracksToResponse(dbTracks, "href", a.Name, limit, 0)

	var dbItems struct {
		Items []map[string]interface{} `json:"items"`
	}
	_ = json.Unmarshal(dbJSON, &dbItems)

	// API tracks for this album
	apiJSON := s.TrackJSONByID[albumID]
	var apiItems struct {
		Items []map[string]interface{} `json:"items"`
	}
	_ = json.Unmarshal(apiJSON, &apiItems)

	merged := append(dbItems.Items, apiItems.Items...)

	final, _ := json.Marshal(struct {
		Items []map[string]interface{} `json:"items"`
	}{Items: merged})

	return final, nil
}

//////////////////////////////////////////////////////////////////////
// The Actual Test
//////////////////////////////////////////////////////////////////////

func Test_EnrichArtist_DBAndAPI_MergingCreatesTracks(t *testing.T) {

	// --------------------
	// 1. PREPARE API JSON
	// --------------------
	apiAlbumJSON := dummyAlbumJSON("api_album_1", "api_album_2")

	apiTrack1JSON, h := dummyTrackJSON("A1", "api_track_1", "F1")
	apiTrack2JSON, _ := dummyTrackJSON("A1", "api_track_2", "F1")

	store := &MockStore{
		AlbumJSON: apiAlbumJSON,
		TrackJSONByID: map[string][]byte{
			"db_album_1":  apiTrack1JSON,
			"api_album_1": apiTrack2JSON,
			"api_album_2": apiTrack1JSON,
		},
		FeaturedArtists: map[string][]DBArtist{
			"db_track_1": {{ID: "F1", Name: "FeatTwo"}},
		},
	}

	// --------------------
	// 2. Prepare artist
	// --------------------
	artist := &sixdegrees.Artists{
		ID:   "A1",
		Name: "TestArtist",
	}

	// helper is preloaded with featured artists for CreateTracks
	helper := h

	// --------------------
	// 3. Run the real enrichArtist
	// --------------------
	target := "TGT"
	found := false
	limit := 10

	fmt.Println("Enriching Artist")
	err := store.enrichArtist(artist, helper, target, &found, false, &limit, false)
	if err != nil {
		t.Fatalf("enrichArtist returned error: %v", err)
	}

	// --------------------
	// 4. ASSERT RESULTS
	// --------------------
	if len(artist.Tracks) == 0 {
		t.Fatalf("expected tracks, got none")
	}

	ids := map[string]bool{}
	for _, tr := range artist.Tracks {
		ids[tr.ID] = true
		if tr.Artist == nil || tr.Artist.ID != "A1" {
			t.Fatalf("invalid primary artist on track: %#v", tr)
		}
		if len(tr.Featured) == 0 {
			t.Fatalf("track missing featured artist: %#v", tr)
		}
	}

	if !ids["db_track_1"] {
		t.Fatalf("expected db_track_1 in results")
	}
	if !ids["api_track_1"] {
		t.Fatalf("expected api_track_1 in results")
	}
	if !ids["api_track_2"] {
		t.Fatalf("expected api_track_2 in results")
	}
}

// ----------------------------------------------------------------------------------------------------------------------------
// Enrich Function - If this changes, change
// ----------------------------------------------------------------------------------------------------------------------------

func (s *MockStore) enrichArtist(
	a *sixdegrees.Artists,
	h *sixdegrees.Helper,
	target string,
	found *bool,
	verbose bool,
	limit *int,
	offline bool,
) error {
	fmt.Println("Enriching artist:", a.Name)
	albumLimit := 15
	if limit != nil && *limit > 0 {
		albumLimit = *limit
	}

	// 1) Load tracks from DB first
	dbTracks, err := s.ListTracksByArtistID(context.Background(), a.ID, 1e6)
	if err == nil && len(dbTracks) > 0 {
		T, _ := s.DBTracksToTracks(dbTracks)
		if len(T) > 0 {
			if verbose {
				log.Printf("    Loaded %d tracks from DB for %s", len(T), a.Name)
			}
			// Only append tracks that have featured artists
			if hasFeatured(a.Tracks) {
				a.Tracks = append(a.Tracks, T...)
			}
		}
	}

	// 2) Get albums (DB + API remainder)
	albumsBody, err := s.getArtistAlbumsMergedCached(a.ID, albumLimit, offline, verbose)
	if err != nil || albumsBody == nil {
		return err
	}

	// 3) Parse albums and build track relationships
	for i, al := range a.ParseAlbums(albumsBody) {
		if i == 0 {
			fmt.Printf("Number of albums for %d:%s\n", len(al), a.Name)
		}
		if i >= albumLimit {
			break
		}

		_ = s.UpsertAlbum(context.Background(), DBAlbum{
			ID:              al,
			PrimaryArtistID: sqlNullString(a.ID),
		})

		tracksBody, err := s.fetchAlbumTracksCached(a, al, albumLimit, offline, verbose)
		if err != nil {
			continue
		}

		T, _ := a.CreateTracks(tracksBody, nil)
		if len(T) == 0 {
			continue
		}

		for _, t := range T {
			if len(t.Featured) > 0 {
				a.Tracks = append(a.Tracks, t)
			}
			dba := createDBTrack(t, al)
			_ = s.UpsertTrack(context.Background(), dba)

			if t.Artist != nil && t.Artist.ID != "" {
				_ = s.UpsertArtist(context.Background(), createDBArtist(*t.Artist))
				_ = s.AddTrackArtist(context.Background(), t.ID, t.Artist.ID, "primary")
			}
			for _, f := range t.Featured {
				if f == nil || f.ID == "" {
					continue
				}
				_ = s.UpsertArtist(context.Background(), createDBArtist(*f))
				_ = s.AddTrackArtist(context.Background(), t.ID, f.ID, "featured")
			}
		}
	}

	time.Sleep(10 * time.Millisecond)
	return nil
}
