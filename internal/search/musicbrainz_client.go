package search

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
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

func ResolveArtistOnce(dsn, name string) (*sixdegrees.Artists, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	defer db.Close()

	// set schema
	_, _ = db.Exec("SET search_path TO musicbrainz;")

	// IMPORTANT: order by id ASC so the canonical artist is chosen
	const q = `
        SELECT id, gid, name
        FROM artist
        WHERE lower(name) = lower($1)
        ORDER BY id ASC
        LIMIT 1;
    `

	var (
		internalID int
		mbid       string
		cname      string
	)

	err = db.QueryRow(q, name).Scan(&internalID, &mbid, &cname)
	if err != nil {
		return nil, fmt.Errorf("artist not found: %w", err)
	}

	return &sixdegrees.Artists{
		ID:   mbid, // UUID (gid)
		Name: cname,
	}, nil
}
