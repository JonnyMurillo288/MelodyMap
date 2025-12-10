package search

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
)

const mbBaseURL = "https://musicbrainz.org/ws/2"
const mbUserAgent = "SixDegreeSpotify/1.0 (jonnymurillo288@gmail.com.com)"

// MBClient is a minimal MusicBrainz API client.
type MBClient struct {
	http *http.Client
}

// NewMBClient constructs a new MusicBrainz client.
func NewMBClient() *MBClient {
	return &MBClient{
		http: &http.Client{Timeout: 12 * time.Second},
	}
}

// get is a small helper that performs GET + JSON decode + 1req/sec throttle.
func (c *MBClient) get(u string, out interface{}) error {
	req, err := http.NewRequest("GET", u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", mbUserAgent)

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return err
	}

	// MusicBrainz polite usage: 1 request per second for anonymous clients.
	time.Sleep(1 * time.Second)
	return nil
}

// ------------
// Search API
// ------------

type mbArtistSearchResponse struct {
	Artists []mbArtist `json:"artists"`
}

type mbArtist struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Images []struct {
		URL string `json:"url"`
	} `json:"images"`
}

// SearchArtist searches MusicBrainz for an artist by name, returning all hits.
func (c *MBClient) SearchArtist(name string) ([]mbArtist, error) {
	q := url.QueryEscape(name)
	u := fmt.Sprintf("%s/artist?query=%s&fmt=json", mbBaseURL, q)

	var resp mbArtistSearchResponse
	if err := c.get(u, &resp); err != nil {
		return nil, err
	}
	return resp.Artists, nil
}

// ------------
// Lookup API
// ------------

type mbArtistLookup struct {
	ID        string             `json:"id"` // This is going to be the MusicBrainz ID
	Name      string             `json:"name"`
	Relations []mbArtistRelation `json:"relations"`
}

type mbArtistRelation struct {
	Type   string `json:"type"`
	Artist struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	} `json:"artist"`
}

// LookupArtist fetches an artist and its relations from MusicBrainz.
func (c *MBClient) LookupArtist(id string) (*mbArtistLookup, error) {
	u := fmt.Sprintf("%s/artist/%s?fmt=json&inc=artist-rels+recording-rels", mbBaseURL, id)
	var resp mbArtistLookup
	if err := c.get(u, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// NOT A CLIENT BY DB, GOING TO FIX IN THE FUTURE

func ResolveArtistOnce(s *Store, name string) (*sixdegrees.Artists, error) {
	name = strings.TrimSpace(name)

	// ============================================================
	// Popularity scoring used in all queries:
	// credit_score    = appearances in artist_credit_name
	// recording_score = appearances in l_artist_recording
	// release_score   = appearances in artist_release
	// ============================================================
	const popularityCols = `
        COALESCE(acn.cnt, 0) AS credit_score
    `

	const popularityJoins = `
        LEFT JOIN (
            SELECT artist, COUNT(*) AS cnt
            FROM artist_credit_name
            GROUP BY artist
        ) acn ON acn.artist = a.id
    `

	// ============================================================
	// 1. EXACT MATCH
	// ============================================================
	exact := fmt.Sprintf(`
        SELECT a.id, a.gid, a.name, %s
        FROM artist a
        %s
        WHERE lower(a.name) = lower($1)
        ORDER BY credit_score DESC,
                 a.id ASC
        LIMIT 1;
    `, popularityCols, popularityJoins)

	var internalID int
	var gid, cname string
	var credit int
	// fmt.Printf("QUERY:\n%s\nARGS: %v", exact, []any{name})
	err := s.DB.QueryRow(exact, name).Scan(
		&internalID, &gid, &cname,
		&credit,
	)
	if err == nil {
		return &sixdegrees.Artists{ID: gid, Name: cname}, nil
	}

	// ============================================================
	// 2. ALIAS MATCH
	// ============================================================
	alias := fmt.Sprintf(`
        SELECT a.id, a.gid, a.name, %s
        FROM artist a
        JOIN artist_alias aa ON aa.artist = a.id
        %s
        WHERE lower(aa.name) = lower($1)
        ORDER BY credit_score DESC,
                 a.id ASC
        LIMIT 1;
    `, popularityCols, popularityJoins)

	err = s.DB.QueryRow(alias, name).Scan(
		&internalID, &gid, &cname,
		&credit,
	)
	if err == nil {
		return &sixdegrees.Artists{ID: gid, Name: cname}, nil
	}

	// ============================================================
	// 3. FUZZY MATCH
	// ============================================================
	fuzzy := fmt.Sprintf(`
        SELECT a.id, a.gid, a.name, %s
        FROM artist a
        %s
        WHERE a.name ILIKE '%%' || $1 || '%%'
        ORDER BY credit_score DESC,
                 a.id ASC
        LIMIT 1;
    `, popularityCols, popularityJoins)

	err = s.DB.QueryRow(fuzzy, name).Scan(
		&internalID, &gid, &cname,
		&credit,
	)
	if err == nil {
		return &sixdegrees.Artists{ID: gid, Name: cname}, nil
	}

	return nil, fmt.Errorf("artist not found: %q", name)
}
