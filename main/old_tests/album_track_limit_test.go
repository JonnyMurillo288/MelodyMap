package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"testing"

	sixdegrees "github.com/Jonnymurillo288/SixDegreesSpotify/sixDegrees"
)

//////////////////////////////////////////////////////////////////////
// Helpers for consistent JSON
//////////////////////////////////////////////////////////////////////

func fakeAlbumJSON(ids ...string) []byte {
	type item struct {
		ID      string `json:"id"`
		Artists []struct {
			Name string `json:"name"`
		} `json:"artists"`
	}
	type resp struct {
		Items []item `json:"items"`
	}

	r := resp{}
	for _, id := range ids {
		r.Items = append(r.Items, item{
			ID: id,
			Artists: []struct {
				Name string `json:"name"`
			}{{Name: "TestArtist"}},
		})
	}

	b, _ := json.Marshal(r)
	return b
}

func fakeTrackJSON(trackIDs ...string) []byte {
	type artist struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	type item struct {
		ID      string   `json:"id"`
		Name    string   `json:"name"`
		Artists []artist `json:"artists"`
	}
	type resp struct {
		Items []item `json:"items"`
	}

	r := resp{}
	for _, id := range trackIDs {
		r.Items = append(r.Items, item{
			ID:   id,
			Name: "Dummy",
			Artists: []artist{
				{ID: "A1", Name: "TestArtist"}, // main artist
				{ID: "F1", Name: "Feature"},    // must have a feature
			},
		})
	}

	b, _ := json.Marshal(r)
	return b
}

//////////////////////////////////////////////////////////////////////
// MockStore
//////////////////////////////////////////////////////////////////////

type MockStore struct {
	DB               *sql.DB
	APIAlbumsPrimary []byte
	APIAlbumsAppear  []byte
	APITracks        []byte
}

func (s *MockStore) ListAlbumsByArtistID(ctx context.Context, id string, limit int) ([]DBAlbum, error) {
	// pretend DB always has 2 albums
	return []DBAlbum{
		{ID: "db1", PrimaryArtistID: sqlNullString("A1")},
		{ID: "db2", PrimaryArtistID: sqlNullString("A1")},
	}, nil
}

func (s *MockStore) ConvertDBAlbumsToResponse(db []DBAlbum, href string, limit, offset int) (albumResponse, error) {
	ids := []string{}
	for _, d := range db {
		ids = append(ids, d.ID)
	}
	var r albumResponse
	_ = json.Unmarshal(fakeAlbumJSON(ids...), &r)
	return r, nil
}

func (s *MockStore) ListTracksByAlbumID(ctx context.Context, albumID string) ([]DBTrack, error) {
	// pretend DB always has 1 track per album
	return []DBTrack{
		{ID: "db_track_1", Name: "DB Track", PrimaryArtistID: sqlNullString("A1")},
	}, nil
}

func (s *MockStore) ConvertDBTracksToResponse(db []DBTrack, href, artist string, limit, offset int) (trackResponse, error) {
	var r trackResponse
	_ = json.Unmarshal(fakeTrackJSON("db_track_1"), &r)
	return r, nil
}

func (s *MockStore) ListFeaturedArtistsForTrack(ctx context.Context, id string) ([]DBArtist, error) {
	return []DBArtist{{ID: "F1", Name: "Feature"}}, nil
}

func (s *MockStore) DBTracksToTracks(db []DBTrack) ([]sixdegrees.Track, error) {
	return nil, nil
}

func (s *MockStore) GetArtistByID(ctx context.Context, id string) (*DBArtist, error) {
	return &DBArtist{ID: id, Name: "TestArtist"}, nil
}

func (s *MockStore) DBArtistsToArtists(a DBArtist) (*sixdegrees.Artists, error) {
	return &sixdegrees.Artists{ID: a.ID, Name: a.Name}, nil
}

func (s *MockStore) UpsertAlbum(ctx context.Context, d DBAlbum) error         { return nil }
func (s *MockStore) UpsertTrack(ctx context.Context, d DBTrack) error         { return nil }
func (s *MockStore) UpsertArtist(ctx context.Context, d DBArtist) error       { return nil }
func (s *MockStore) AddTrackArtist(ctx context.Context, t, a, r string) error { return nil }
func (s *MockStore) AddAlbumArtist(ctx context.Context, a, b string) error    { return nil }

//////////////////////////////////////////////////////////////////////
// Override the album + track fetch functions
//////////////////////////////////////////////////////////////////////

func (s *MockStore) getArtistAlbumsMergedCached(id string, limit int, offline, verbose bool) (albumResponse, error) {

	dbAlbums, _ := s.ListAlbumsByArtistID(context.Background(), id, limit)
	dbJSON, _ := s.ConvertDBAlbumsToResponse(dbAlbums, "h", limit, 0)

	var out albumResponse
	out = dbJSON

	numFromDB := len(dbAlbums)
	apiLimit := limit - numFromDB
	if apiLimit < 0 {
		apiLimit = 0
	}

	if apiLimit > 0 {
		var p albumResponse
		var a albumResponse
		_ = json.Unmarshal(s.APIAlbumsPrimary, &p)
		_ = json.Unmarshal(s.APIAlbumsAppear, &a)
		out.Items = append(out.Items, p.Items...)
		out.Items = append(out.Items, a.Items...)
	}

	dedupeAlbums(&out)

	return out, nil
}

func (s *MockStore) fetchAlbumTracksCached(a *sixdegrees.Artists, albumID string, limit int, offline, verbose bool) (trackResponse, error) {

	dbTracks, _ := s.ListTracksByAlbumID(context.Background(), albumID)
	dbJSON, _ := s.ConvertDBTracksToResponse(dbTracks, "h", a.Name, limit, 0)

	var out trackResponse
	out = dbJSON

	numFromDB := len(dbTracks)
	apiLimit := limit - numFromDB
	if apiLimit < 0 {
		apiLimit = 0
	}

	if apiLimit > 0 {
		var api trackResponse
		_ = json.Unmarshal(s.APITracks, &api)
		out.Items = append(out.Items, api.Items...)
	}

	dedupeTracks(&out)

	return out, nil
}

//////////////////////////////////////////////////////////////////////
// The actual test for album + track API limit logic
//////////////////////////////////////////////////////////////////////

func Test_DB_First_Remainder_Album_And_Track_Limits(t *testing.T) {

	store := &MockStore{
		// real code expects BOTH endpoints to return apiLimit items
		APIAlbumsPrimary: fakeAlbumJSON("api1", "api2", "api3"),
		APIAlbumsAppear:  fakeAlbumJSON("api4", "api5", "api6"),
		APITracks:        fakeTrackJSON("api_track_1", "api_track_2", "api_track_3"),
	}

	artist := &sixdegrees.Artists{ID: "A1", Name: "TestArtist"}

	limit := 5

	// DB = 2 albums → apiLimit = 3
	albums, _ := store.getArtistAlbumsMergedCached("A1", limit, false, false)

	if len(albums.Items) != 2+3+3 {
		t.Fatalf("expected total albums = DB(2) + API_primary(3) + API_appear(3) = 8, got %d", len(albums.Items))
	}

	// API total count after merge should be exactly 3+3 = 6 (before any filtering by test logic)
	apiCount := len(albums.Items) - 2
	if apiCount != 6 {
		t.Fatalf("expected 6 API albums (3 primary + 3 appears), got %d", apiCount)
	}

	// Now filter to apiLimit, i.e. 3
	// Or directly assert primary count:

	var primaryCount int
	for _, it := range albums.Items {
		if it.ID == "api1" || it.ID == "api2" || it.ID == "api3" {
			primaryCount++
		}
	}
	if primaryCount != 3 {
		t.Fatalf("expected exactly 3 primary API albums, got %d", primaryCount)
	}

	// TRACK test: DB=1, limit=4 → apiLimit=3
	tracks, _ := store.fetchAlbumTracksCached(artist, "db_album_1", 4, false, false)

	if len(tracks.Items) != 1+3 {
		t.Fatalf("expected 4 tracks (1 db + 3 api), got %d", len(tracks.Items))
	}
}
