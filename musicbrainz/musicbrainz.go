package musicbrainz

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

const baseURL = "https://musicbrainz.org/ws/2"
const userAgent = "SixDegreeSpotify/1.0 (jonny@example.com)"

// -------------------------------------------------------
// Core client
// -------------------------------------------------------

type Client struct {
	http *http.Client
}

func NewClient() *Client {
	return &Client{
		http: &http.Client{Timeout: 15 * time.Second},
	}
}

func (c *Client) get(u string, v interface{}) error {
	req, err := http.NewRequest("GET", u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", userAgent)

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if err := json.NewDecoder(resp.Body).Decode(v); err != nil {
		return err
	}

	// MB rate-limit: 1 request / second
	time.Sleep(1 * time.Second)
	return nil
}

//
// -------------------------------------------------------
// Search Artist by Name
// -------------------------------------------------------

type ArtistSearchResponse struct {
	Artists []Artist `json:"artists"`
}

type Artist struct {
	ID             string `json:"id"`
	Name           string `json:"name"`
	SortName       string `json:"sort-name"`
	Country        string `json:"country"`
	Disambiguation string `json:"disambiguation"`
}

func (c *Client) SearchArtist(name string) ([]Artist, error) {
	q := url.QueryEscape(name)
	u := fmt.Sprintf("%s/artist?query=%s&fmt=json", baseURL, q)

	var out ArtistSearchResponse
	if err := c.get(u, &out); err != nil {
		return nil, err
	}
	return out.Artists, nil
}

//
// -------------------------------------------------------
// Lookup Artist (with relationships)
// -------------------------------------------------------

type ArtistLookup struct {
	ID        string     `json:"id"`
	Name      string     `json:"name"`
	Relations []Relation `json:"relations"`
}

type Relation struct {
	Type string `json:"type"`

	Artist struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	} `json:"artist"`

	Recording struct {
		ID    string `json:"id"`
		Title string `json:"title"`
	} `json:"recording"`
}

func (c *Client) LookupArtist(id string, includes ...string) (*ArtistLookup, error) {
	inc := url.QueryEscape(joinIncludes(includes))
	u := fmt.Sprintf("%s/artist/%s?fmt=json&inc=%s", baseURL, id, inc)

	var out ArtistLookup
	if err := c.get(u, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func joinIncludes(in []string) string {
	if len(in) == 0 {
		return ""
	}
	s := in[0]
	for i := 1; i < len(in); i++ {
		s += "+" + in[i]
	}
	return s
}

//
// -------------------------------------------------------
// Extract collaborators from ArtistLookup
// -------------------------------------------------------

func ExtractCollaborators(a *ArtistLookup) []Artist {
	var out []Artist
	fmt.Println("Here are the relations for:", a.Name)
	for _, rel := range a.Relations {
		// Performance, producer, composer, vocal, instrumental, etc
		if rel.Type == "collaboration" ||
			rel.Type == "vocal" ||
			rel.Type == "instrument" ||
			rel.Type == "performer" ||
			rel.Type == "producer" ||
			rel.Type == "remixer" ||
			rel.Type == "member of band" ||
			rel.Type == "composer" {
			fmt.Printf("Relation for -> %s: %s", rel.Artist.Name, rel.Type)
			if rel.Artist.ID != "" {
				out = append(out, Artist{
					ID:   rel.Artist.ID,
					Name: rel.Artist.Name,
				})
			}
		}
	}

	return out
}
