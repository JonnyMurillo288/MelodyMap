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
	"strconv"
	"strings"
	"time"

	"github.com/Jonnymurillo288/SixDegreesSpotify/internal/auth"
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

type SpotifyTrackSearch struct {
	Tracks struct {
		Items []struct {
			ID      string `json:"id"`
			Name    string `json:"name"`
			Artists []struct {
				Name string `json:"name"`
			} `json:"artists"`
		} `json:"items"`
	} `json:"tracks"`
}

// SearchTrackID returns the FIRST matching Spotify track ID.
func SearchTrackID(ctx context.Context, trackName, artist1, artist2 string) (string, error) {
	q := fmt.Sprintf(`track:"%s" artist:"%s"`, trackName, artist1)

	params := map[string]string{
		"q":     q,
		"type":  "track",
		"limit": "8",
	}

	body, status, err := doSpotifyRequest(ctx, "GET",
		"https://api.spotify.com/v1/search", params, nil)
	if err != nil {
		return "", err
	}
	if status != 200 {
		return "", fmt.Errorf("spotify search returned status %d", status)
	}

	var out SpotifyTrackSearch
	if err := json.Unmarshal(body, &out); err != nil {
		return "", err
	}

	if len(out.Tracks.Items) == 0 {
		return "", fmt.Errorf("no track found for '%s' by '%s'", trackName, artist1)
	}

	matches := []struct {
		ID      string `json:"id"`
		Name    string `json:"name"`
		Artists []struct {
			Name string `json:"name"`
		} `json:"artists"`
	}{}

	// Filter by both artists
	for _, tr := range out.Tracks.Items {
		var artists []string
		for _, a := range tr.Artists {
			artists = append(artists, strings.ToLower(a.Name))
		}

		a1 := strings.ToLower(artist1)
		a2 := strings.ToLower(artist2)

		if contains(artists, a1) && contains(artists, a2) {
			matches = append(matches, tr)
		}
	}

	if len(matches) == 0 {
		return "", fmt.Errorf("no track matched both artists '%s' and '%s'", artist1, artist2)
	}

	return matches[0].ID, nil
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
