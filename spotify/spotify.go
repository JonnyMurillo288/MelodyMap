package spotify

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"math/rand"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/auth"
	"golang.org/x/text/unicode/norm"
)

// ========================================================== //
// Types

type Playback struct {
	Progress float64     `json:"progress_ms"`
	Item     interface{} `json:"item"`
}

type Queue struct {
	Progress, Duration             float64
	TrackName, TrackPhoto, TrackID string
}

type PaginatedItems struct {
	Items  []interface{} `json:"items"`
	Next   *string       `json:"next"`
	Total  int           `json:"total"`
	Limit  int           `json:"limit"`
	Offset int           `json:"offset"`
}

// ========================================================== //
// HTTP client and retry logic

var httpClient = &http.Client{Timeout: 15 * time.Second}

func doSpotifyRequest(
	ctx context.Context,
	method string,
	endpoint string,
	query map[string]string,
	body io.Reader,
) ([]byte, int, error) {

	client, err := auth.SpotifyClient(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("spotify client err: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return nil, 0, err
	}

	// Apply query params
	if len(query) > 0 {
		u, _ := url.Parse(endpoint)
		q := u.Query()
		for k, v := range query {
			q.Set(k, v)
		}
		u.RawQuery = q.Encode()
		req.URL = u
	}

	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	return fetchWithRetry(client, req, 5)
}
func fetchWithRetry(client *http.Client, req *http.Request, maxRetries int) ([]byte, int, error) {
	var lastErr error
	var status int

	for attempt := 0; attempt <= maxRetries; attempt++ {
		resp, err := client.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(backoff(attempt))
			continue
		}

		status = resp.StatusCode
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if status >= 200 && status < 300 {
			return body, status, nil
		}
		if status == 429 {
			time.Sleep(time.Second)
			continue
		}
		if status >= 500 {
			time.Sleep(backoff(attempt))
			continue
		}

		// client / 4xx error
		return body, status, nil
	}

	return nil, status, lastErr
}

func backoff(attempt int) time.Duration {
	base := 20 * time.Millisecond
	f := math.Pow(2, float64(attempt))
	jitter := time.Duration(rand.Intn(200)) * time.Millisecond
	return time.Duration(float64(base)*f) + jitter
}

func backoffDuration(attempt int) time.Duration {
	base := 5 * time.Millisecond
	factor := math.Pow(2, float64(attempt))
	jitter := time.Duration(rand.Intn(300)) * time.Millisecond
	return time.Duration(float64(base)*factor) + jitter
}

// ========================================================== //
// Spotify API: search, albums, tracks

func SearchArtist(ctx context.Context, artist string) ([]byte, error) {
	params := map[string]string{
		"q":    artist,
		"type": "artist",
	}

	body, _, err := doSpotifyRequest(ctx, "GET",
		"https://api.spotify.com/v1/search", params, nil)
	return body, err
}

// ========================================================== //
// Spotify API: search Tracks

var (
	reParens    = regexp.MustCompile(`\(.+?\)`)
	reRemixTags = regexp.MustCompile(`(?i)\s*[-–—]\s*(remix|live|version|edit|mix|remaster(ed)?|re-?edit|radio edit|acoustic|instrumental|demo|bonus track).*$`)
)

// normalizeUnicode applies NFC normalization and straightens curly quotes.
func normalizeUnicode(s string) string {
	s = norm.NFC.String(s)
	s = strings.ReplaceAll(s, "\u2019", "'")
	s = strings.ReplaceAll(s, "\u2018", "'")
	s = strings.ReplaceAll(s, "\u201C", "\"")
	s = strings.ReplaceAll(s, "\u201D", "\"")
	s = strings.ReplaceAll(s, ",", "")
	s = strings.ReplaceAll(s, ";", "")
	s = strings.ReplaceAll(s, ":", "")
	return s
}

// cleanTrack normalizes unicode and lowercases. Does NOT strip parentheses.
func cleanTrack(t string) string {
	t = normalizeUnicode(t)
	return strings.TrimSpace(strings.ToLower(t))
}

// stripParens removes parenthetical content from a string.
func stripParens(t string) string {
	return strings.TrimSpace(reParens.ReplaceAllString(t, ""))
}

// stripRemixTags removes " - Remix", " - Live", etc. from track names.
func stripRemixTags(t string) string {
	return strings.TrimSpace(reRemixTags.ReplaceAllString(t, ""))
}

// cleanArtist strips feature markers, normalizes unicode, and lowercases.
func cleanArtist(a string) string {
	a = normalizeUnicode(a)
	a = strings.ToLower(a)
	a = strings.Split(a, " feat")[0]
	a = strings.Split(a, " featuring")[0]
	a = strings.Split(a, " & ")[0]
	return strings.TrimSpace(a)
}

// swapAmpersand replaces "&" with "and" or vice versa in a string.
func swapAmpersand(s string) string {
	if strings.Contains(s, " & ") {
		return strings.ReplaceAll(s, " & ", " and ")
	}
	if strings.Contains(s, " and ") {
		return strings.ReplaceAll(s, " and ", " & ")
	}
	return s
}

// SpotifyTrackItem represents a single track from Spotify search results.
type SpotifyTrackItem struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Artists []struct {
		Name string `json:"name"`
	} `json:"artists"`
}

type spotifyTrackSearch struct {
	Tracks struct {
		Items []SpotifyTrackItem `json:"items"`
	} `json:"tracks"`
}

// searchSpotify executes a Spotify search query and returns the result items.
func searchSpotify(ctx context.Context, query string) ([]SpotifyTrackItem, error) {
	params := map[string]string{
		"q":     query,
		"type":  "track",
		"limit": "10",
	}

	body, status, err := doSpotifyRequest(ctx, "GET",
		"https://api.spotify.com/v1/search", params, nil)
	if err != nil {
		return nil, err
	}
	if status != 200 {
		return nil, fmt.Errorf("spotify search returned status %d", status)
	}

	var out spotifyTrackSearch
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	return out.Tracks.Items, nil
}

// matchResults returns the ID of the first item where all mustArtists appear.
func matchResults(items []SpotifyTrackItem, mustArtists []string) (string, bool) {
	for _, tr := range items {
		var spotArtists []string
		for _, a := range tr.Artists {
			spotArtists = append(spotArtists, cleanArtist(a.Name))
		}

		matched := true
		for _, need := range mustArtists {
			if !contains(spotArtists, need) {
				matched = false
				break
			}
		}
		if matched {
			return tr.ID, true
		}
	}
	return "", false
}

// searchStrategy defines a single attempt at finding a Spotify track.
type searchStrategy struct {
	name  string
	query string
	must  []string // artist names that must appear in results
}

// SearchResult contains the Spotify track ID and which strategy found it.
type SearchResult struct {
	ID       string
	Strategy string
}

// SearchTrackIDResult tries multiple search strategies and returns the first hit
// along with which strategy succeeded.
func SearchTrackIDResult(ctx context.Context, trackName, artist1, artist2 string) (SearchResult, error) {
	ct := cleanTrack(trackName)
	stripped := stripRemixTags(stripParens(ct))
	ca1 := cleanArtist(artist1)
	ca2 := cleanArtist(artist2)

	log.Printf("[spotify] searching: track=%q artist1=%q artist2=%q", trackName, artist1, artist2)

	hasTwoArtists := ca2 != "" && ca2 != ca1

	// Build strategy list in priority order.
	var strategies []searchStrategy

	// 1. Primary: both artists in query + validation (only when two distinct artists)
	if hasTwoArtists {
		strategies = append(strategies, searchStrategy{
			name:  "primary",
			query: fmt.Sprintf(`track:"%s" artist:"%s" artist:"%s"`, ct, ca1, ca2),
			must:  []string{ca1, ca2},
		})
	}

	// 2. Artist1-only: single artist query, validate artist1
	strategies = append(strategies, searchStrategy{
		name:  "artist1-only",
		query: fmt.Sprintf(`track:"%s" artist:"%s"`, ct, ca1),
		must:  []string{ca1},
	})

	// 3. Strip-parens: remove parens/remix tags from track, query with artist1
	if stripped != ct {
		strategies = append(strategies, searchStrategy{
			name:  "strip-parens",
			query: fmt.Sprintf(`track:"%s" artist:"%s"`, stripped, ca1),
			must:  []string{ca1},
		})
	}

	// 4. Track-only: no artist in query, validate artist1 from results
	strategies = append(strategies, searchStrategy{
		name:  "track-only",
		query: fmt.Sprintf(`track:"%s"`, stripped),
		must:  []string{ca1},
	})

	// 5. Ampersand-swap: try &↔and in artist names
	sca1 := swapAmpersand(ca1)
	sca2 := swapAmpersand(ca2)
	if sca1 != ca1 || (hasTwoArtists && sca2 != ca2) {
		must := []string{sca1}
		q := fmt.Sprintf(`track:"%s" artist:"%s"`, ct, sca1)
		if hasTwoArtists {
			q = fmt.Sprintf(`track:"%s" artist:"%s" artist:"%s"`, ct, sca1, sca2)
			must = []string{sca1, sca2}
		}
		strategies = append(strategies, searchStrategy{
			name:  "ampersand-swap",
			query: q,
			must:  must,
		})
	}

	// Try each strategy in order.
	for _, s := range strategies {
		log.Printf("[spotify] trying strategy=%s query=%s", s.name, s.query)

		items, err := searchSpotify(ctx, s.query)
		if err != nil {
			log.Printf("[spotify] strategy=%s error: %v", s.name, err)
			return SearchResult{}, err
		}

		if id, ok := matchResults(items, s.must); ok {
			log.Printf("[spotify] HIT strategy=%s id=%s", s.name, id)
			return SearchResult{ID: id, Strategy: s.name}, nil
		}
		log.Printf("[spotify] MISS strategy=%s", s.name)
	}

	return SearchResult{}, fmt.Errorf("no spotify match for track=%q artist1=%q artist2=%q after %d strategies",
		trackName, artist1, artist2, len(strategies))
}

// SearchTrackID returns the first matching Spotify track ID using iterative
// fallback strategies. Existing callers are unaffected.
func SearchTrackID(ctx context.Context, trackName, artist1, artist2 string) (string, error) {
	res, err := SearchTrackIDResult(ctx, trackName, artist1, artist2)
	if err != nil {
		return "", err
	}
	return res.ID, nil
}

func contains(list []string, x string) bool {
	for _, v := range list {
		if v == x {
			return true
		}
	}
	return false
}

// ArtistAlbumsAppearsOn fetches albums where the artist appears as a featured contributor ("appears_on").
// It complements ArtistAlbums, which only fetches albums where the artist is the primary owner.
func ArtistAlbums(ctx context.Context, artistID string, limit int) ([]byte, error) {

	pageSize := 50
	totalLimit := limit
	if limit < 0 {
		totalLimit = math.MaxInt32
	}

	var all []interface{}
	offset := 0

	for {
		params := map[string]string{
			"include_groups": "album,single",
			"market":         "US",
			"limit":          strconv.Itoa(pageSize),
			"offset":         strconv.Itoa(offset),
		}

		body, status, err := doSpotifyRequest(ctx, "GET",
			"https://api.spotify.com/v1/artists/"+artistID+"/albums",
			params, nil)
		if err != nil {
			return nil, err
		}
		if status == 429 {
			time.Sleep(time.Second)
		}

		var page struct {
			Items []interface{} `json:"items"`
			Next  *string       `json:"next"`
		}
		if err := json.Unmarshal(body, &page); err != nil {
			return nil, err
		}

		all = append(all, page.Items...)

		if len(all) >= totalLimit || page.Next == nil || *page.Next == "" {
			break
		}
		offset += pageSize
	}

	return json.Marshal(struct{ Items []interface{} }{all})
}

// ============================================================
// Get album tracks
// ============================================================

func GetAlbumTracks(ctx context.Context, albumID string) ([]byte, error) {
	var all []interface{}
	offset := 0

	for {
		params := map[string]string{
			"limit":  "50",
			"offset": strconv.Itoa(offset),
		}

		body, status, err := doSpotifyRequest(ctx, "GET",
			"https://api.spotify.com/v1/albums/"+albumID+"/tracks",
			params, nil)
		if err != nil {
			return nil, err
		}

		var page struct {
			Items []interface{} `json:"items"`
			Next  *string       `json:"next"`
		}
		if err := json.Unmarshal(body, &page); err != nil {
			return nil, err
		}

		all = append(all, page.Items...)

		if status != 200 || page.Next == nil || *page.Next == "" {
			break
		}
		offset += 50
	}

	return json.Marshal(struct{ Items []interface{} }{all})
}

// ============================================================
// Create Playlist + add tracks
// ============================================================

func CreatePlaylist(ctx context.Context, name string, trackIDs []string) (string, error) {
	// GET /me to find user ID
	body, status, err := doSpotifyRequest(ctx, "GET",
		"https://api.spotify.com/v1/me", nil, nil)
	if err != nil {
		return "", err
	}
	if status != 200 {
		return "", fmt.Errorf("spotify /me returned %d", status)
	}

	var user struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(body, &user); err != nil {
		return "", err
	}

	// Create playlist
	createBody := map[string]any{
		"name":        name,
		"description": "Generated by SixDegreeSpotify",
		"public":      false,
	}
	raw, _ := json.Marshal(createBody)

	respBody, st, err := doSpotifyRequest(ctx, "POST",
		fmt.Sprintf("https://api.spotify.com/v1/users/%s/playlists", user.ID),
		nil, bytes.NewReader(raw))
	if err != nil {
		return "", fmt.Errorf("create playlist error: %w", err)
	}
	if st != 201 && st != 200 {
		return "", fmt.Errorf("playlist create failed: %s", string(respBody))
	}

	var playlist struct {
		ID  string            `json:"id"`
		URL map[string]string `json:"external_urls"`
	}
	json.Unmarshal(respBody, &playlist)

	// Add tracks
	if len(trackIDs) > 0 {
		uris := make([]string, len(trackIDs))
		for i, id := range trackIDs {
			uris[i] = "spotify:track:" + id
		}

		raw, _ := json.Marshal(map[string]any{"uris": uris})

		_, st, err := doSpotifyRequest(ctx, "POST",
			"https://api.spotify.com/v1/playlists/"+playlist.ID+"/tracks",
			nil, bytes.NewReader(raw))
		if err != nil || st >= 300 {
			return "", fmt.Errorf("add tracks failed")
		}
	}

	return playlist.URL["spotify"], nil
}

// ========================================================== //
// Playback utilities
// ============================================================
// Playback utilities - rewritten for new Spotify client
// ============================================================

func reqPlayback(ctx context.Context) (Playback, []byte) {
	endpoint := "https://api.spotify.com/v1/me/player/currently-playing"

	body, _, err := doSpotifyRequest(ctx, "GET", endpoint,
		map[string]string{"market": "US"},
		nil,
	)
	if err != nil {
		log.Println("reqPlayback error:", err)
		return Playback{}, nil
	}

	var pb Playback
	_ = json.Unmarshal(body, &pb)

	return pb, body
}

func postSpotify(ctx context.Context, endpoint string, query map[string]string) {
	_, status, err := doSpotifyRequest(ctx, "POST", endpoint, query, nil)
	if err != nil {
		log.Printf("POST %s error: %v", endpoint, err)
		return
	}
	log.Printf("POST %s status %d", endpoint, status)
}

// AddQueue adds multiple tracks to the user's queue
func AddQueue(ctx context.Context, tracks []string) {
	log.Printf("Adding %d tracks to queue", len(tracks))

	for _, t := range tracks {
		postSpotify(ctx,
			"https://api.spotify.com/v1/me/player/queue",
			map[string]string{"uri": "spotify:track:" + t},
		)
	}

	// Move to next track
	postSpotify(ctx, "https://api.spotify.com/v1/me/player/next", nil)
}

// Controller sends a playback command (pause, play, next, previous, etc.)
func Controller(ctx context.Context, endpoint string) {
	log.Println("Invoking controller:", endpoint)
	postSpotify(ctx, endpoint, nil)
}

// GetPlayback returns the currently playing track + meta info
func GetPlayback(ctx context.Context) Queue {
	pb, _ := reqPlayback(ctx)
	var q Queue
	q.Progress = pb.Progress

	item, ok := pb.Item.(map[string]interface{})
	if !ok {
		return q
	}

	if dur, ok := item["duration_ms"].(float64); ok {
		q.Duration = dur
	}
	if name, ok := item["name"].(string); ok {
		q.TrackName = name
	}
	if id, ok := item["id"].(string); ok {
		q.TrackID = id
	}

	// Extract album art
	if albumMap, ok := item["album"].(map[string]interface{}); ok {
		if imgs, ok := albumMap["images"].([]interface{}); ok && len(imgs) > 1 {
			if m, ok := imgs[1].(map[string]interface{}); ok {
				if u, ok := m["url"].(string); ok {
					q.TrackPhoto = u
				}
			}
		}
	}

	return q
}
