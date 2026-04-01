package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/auth"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/Jonnymurillo288/MelodyMap/spotify"
)

// inflight tracks src artist IDs that already have an ML request in progress.
// Prevents duplicate ML service calls when the frontend polls while a
// prediction is still running.
var inflight sync.Map // key: src string → value: struct{}

// ------------------------------------------------------------
// POST /api/search/start
// GET /ml/synth/artists
// ------------------------------------------------------------

type mlSearchRequest struct {
	Start  string `json:"targetSearch"`
	Target string `json:"destSearch"`
	Depth  int    `json:"depth"`
}

// GET - Tells backend to look at the src (or src and dst) to return potential connections.
// First checks the DB for cached synthetic tracks; only calls the ML service on cache miss.
func HandleMachineLearningMainPage(w http.ResponseWriter, r *http.Request) {

	var getLink bool // variable to trigger a different mlURL, if user inputs dst then get different data from backend

	// 1. Parse & validate query params (browser-facing)
	src := strings.TrimSpace(r.URL.Query().Get("src"))
	dst := strings.TrimSpace(r.URL.Query().Get("dst"))
	limitStr := r.URL.Query().Get("limit")

	if src == "" {
		http.Error(w, "missing src", http.StatusBadRequest)
		return
	}

	if dst != "" {
		getLink = true
	}

	limit := 25
	if limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 && v <= 100 {
			limit = v
		}
	}

	// 2. Open DB and set up context (used for cache check and table init)
	store, err := search.Open("")
	if err != nil {
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	// Initialize synthetic tables (skip errors — tables already exist on Render)
	if err := search.InitSyntheticTrackTables(ctx, store); err != nil {
		log.Printf("[ML Handler] InitSyntheticTrackTables skipped: %v", err)
	}

	// 3. DB cache check — return cached predictions if they exist
	srcArtist, lookupErr := store.LookupArtistByMBID(src)
	if lookupErr == nil && srcArtist != nil {
		cached, cacheErr := search.GetCachedSynthNeighbors(ctx, store, srcArtist.ID, limit)
		if cacheErr == nil && len(cached) > 0 {
			fmt.Printf("[ML Handler] Cache hit for src=%s (%d neighbors)\n", src, len(cached))
			resp := map[string]any{
				"src_artist_id": src,
				"neighbors":     cached,
				"model_version": "logit_v3",
				"latency_ms":    0,
				"cached":        true,
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
			return
		}
	}

	// 4. Cache miss — check if an ML request is already in-flight for this src.
	//    If so, tell the frontend to keep polling (the result will land in the
	//    DB cache once the original request finishes).
	inflightKey := src
	if _, alreadyRunning := inflight.LoadOrStore(inflightKey, struct{}{}); alreadyRunning {
		fmt.Printf("[ML Handler] ML request already in-flight for src=%s, returning pending\n", src)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":  "pending",
			"message": "ML prediction in progress, please poll again",
		})
		return
	}
	// Ensure we clear the inflight flag when done (success or failure).
	defer inflight.Delete(inflightKey)

	fmt.Printf("[ML Handler] Cache miss for src=%s, calling ML service\n", src)

	payload := map[string]any{
		"src_artist_id": src,
		"limit":         limit,
		"model_version": "logit_v3",
	}
	if getLink {
		payload["dst_artist_id"] = dst
	}

	body, err := json.Marshal(payload)
	if err != nil {
		http.Error(w, "failed to encode request", http.StatusInternalServerError)
		return
	}

	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	mlURL := mlHost + "/ml/predict/artist-neighbors"
	if getLink {
		mlURL = mlHost + "/ml/predict/artist-link"
	}

	fmt.Println("Going to POST Request to:", mlURL)
	fmt.Println("/ml/predict/artist:", string(body))

	req, err := http.NewRequest(http.MethodPost, mlURL, bytes.NewReader(body))
	if err != nil {
		fmt.Println("Error creating request:", err)
		http.Error(w, "failed to create ML request", http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		req.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Println("Error calling ML service:", err)
		http.Error(w, fmt.Sprintf("ML service unavailable: %v", err), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	fmt.Println("ML service responded with status:", resp.StatusCode)

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Println("Error reading ML response body:", err)
		http.Error(w, "failed to read ML response", http.StatusInternalServerError)
		return
	}

	// fmt.Println("ML response body:", string(respBody))

	if resp.StatusCode != http.StatusOK {
		http.Error(
			w,
			fmt.Sprintf("ML error (%d): %s", resp.StatusCode, string(respBody)),
			http.StatusBadGateway,
		)
		return
	}

	// 5. Return ML response to browser
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(respBody)
}

type synthGIDFeaturesToGet struct {
	GIDs []int `json:"gids"`
}

// This is the same function as the regular track lookup, but for synthesized tracks
// The tracks will be saved on our Docker ML synth server
// They will be passed here when the frontend wants to get their features
// POST /ml/synth/track
func SynthTrackLookupHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "method_not_allowed",
		})
		return
	}

	var featuresMap synthGIDFeaturesToGet
	var features search.SyntheticFrontendTracksList

	// Should be passing in Json type with list of []string `json:"gids"`
	// Instead of recording GIDs, these should be list of synthetic track IDs
	err := json.NewDecoder(r.Body).Decode(&featuresMap)

	store, err := search.Open("")
	if err != nil {
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	// Initialize the database
	// search.InitSyntheticTrackTables(ctx, store)

	features.FeaturesMap, err = search.GetSyntheticTrackFeaturesByGIDs(ctx, store, featuresMap.GIDs, 15)
	json.NewEncoder(w).Encode(features)
}

// SyntheticTrackRequest is the payload sent to the ML service to generate synthetic tracks
type SyntheticTrackRequest struct {
	SrcArtistID  string `json:"src_artist_id"`
	DstArtistID  string `json:"dst_artist_id,omitempty"`
	NumTracks    int    `json:"num_tracks"`
	ModelVersion string `json:"model_version"`
}

// ------------------------------------------------------------
// POST /ml/generate/tracks
// ------------------------------------------------------------
// For this function we need to send the Synthetic Track Request to the ML server
// and get back the response which includes the SyntheticTrackResponse structure
// defined below

// SyntheticTrackRequest is the payload sent to the ML service to generate synthetic tracks
// SyntheticTrackResponse is the response structure received from the ML service

// class SyntheticTrackResponse(BaseModel):
//     src_artist_id: str
//     dst_artist_id: str
//     probability: float
//     tracks: List[SyntheticTrack]
//     model_version: str
//     latency_ms: float

// class SyntheticTrack(BaseModel):
//     features: dict
//     predicted_popularity: float

// Steps:
// 1. Parse query params from browser (src, dst, num_tracks)
// 2. Build SyntheticTrackRequest payload
// 3. POST to ML service /ml/generate/tracks
// 4. Return ML response to browser
func SynthTrackLookupHandlerInterludeServer(w http.ResponseWriter, r *http.Request) {

	var getLink bool // variable to trigger a different mlURL, if user inputs dst then get different data from backend

	// Type to output should be this, the features that we get from SyntheticTrackResponse

	// 1. Parse & validate query params (browser-facing)
	src := strings.TrimSpace(r.URL.Query().Get("src"))
	dst := strings.TrimSpace(r.URL.Query().Get("dst"))

	limitStr := r.URL.Query().Get("limit")

	if src == "" {
		http.Error(w, "missing src", http.StatusBadRequest)
		return
	}

	if dst != "" {
		getLink = true
	}

	limit := 25
	if limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 && v <= 100 {
			limit = v
		}
	}

	// 2. Build ML request payload (ML-facing)
	payload := map[string]any{
		"src_artist_id": src,
		"limit":         limit,
		"model_version": "logit_v3",
	}

	// If getLink, add dst
	if getLink {
		payload["dst_artist_id"] = dst
	}

	body, err := json.Marshal(payload)
	if err != nil {
		http.Error(w, "failed to encode request", http.StatusInternalServerError)
		return
	}

	//

	// 3. Call ML service (internal, trusted)
	// Use ML_SERVICE_URL env var if set, otherwise default to localhost for local dev
	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	mlURL := mlHost + "/ml/predict/artist-neighbors"
	// Different url to get link between neighbors or certain links
	if getLink {
		mlURL = mlHost + "/ml/predict/artist-link"
	}

	fmt.Println("Going to POST Request to:", mlURL)
	fmt.Println("Request payload:", string(body))

	req, err := http.NewRequest(http.MethodPost, mlURL, bytes.NewReader(body))
	if err != nil {
		fmt.Println("Error creating request:", err)
		http.Error(w, "failed to create ML request", http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		req.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Println("Error calling ML service:", err)
		http.Error(w, fmt.Sprintf("ML service unavailable: %v", err), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	fmt.Println("ML service responded with status:", resp.StatusCode)

	// Read the full response body
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Println("Error reading ML response body:", err)
		http.Error(w, "failed to read ML response", http.StatusInternalServerError)
		return
	}

	fmt.Println("ML response body:", string(respBody))

	if resp.StatusCode != http.StatusOK {
		http.Error(
			w,
			fmt.Sprintf("ML error (%d): %s", resp.StatusCode, string(respBody)),
			http.StatusBadGateway,
		)
		return
	}

	// 4. Return ML response to browser
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(respBody)
}

// ------------------------------------------------------------
// POST /api/createplaylist
// Creates a Spotify playlist from saved synthetic connections.
// Unlike /createPlaylist, this does NOT require a BFS jobID.
// Instead it takes saved connections from the frontend, calls
// the ML service to find similar real tracks, then creates a
// Spotify playlist from those.
// ------------------------------------------------------------
func createPlaylistFromSavedHandler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	w.Header().Set("Content-Type", "application/json")
	fmt.Println("HIT Create Playlist Handler")

	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"error": "method_not_allowed"})
		return
	}
	// 1. Parse request
	var req struct {
		PlaylistName string `json:"playlistName"`
		Connections  []struct {
			SrcArtistId   string `json:"srcArtistId"`
			DstArtistId   string `json:"dstArtistId"`
			SynthTrackIds []int  `json:"synthTrackIds"`
		} `json:"connections"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid_body"}`, http.StatusBadRequest)
		return
	}

	// 2. Spotify auth pre-check
	if err := auth.HasSpotifyToken(); err != nil {
		if errors.Is(err, auth.ErrNoSpotifyToken) {
			json.NewEncoder(w).Encode(map[string]any{
				"auth_required": true,
				"auth_url":      "/auth/start",
			})
			return
		}
		log.Printf("[api/createplaylist] Spotify token error: %v", err)
		http.Error(w, `{"error":"spotify_token_error"}`, http.StatusInternalServerError)
		return
	}

	// 3. Collect all synthetic track IDs from the saved connections
	var allSynthTrackIds []int
	for _, conn := range req.Connections {
		allSynthTrackIds = append(allSynthTrackIds, conn.SynthTrackIds...)
	}

	if len(allSynthTrackIds) == 0 {
		http.Error(w, `{"error":"no_synth_tracks"}`, http.StatusBadRequest)
		return
	}
	fmt.Println("All synthetic track IDs to find similar real tracks for:", allSynthTrackIds)
	// 4. Call Python ML service to find similar real tracks
	mlPayload, err := json.Marshal(map[string]any{
		"input_tracks":       allSynthTrackIds,
		"num_similar_tracks": 10,
	})
	if err != nil {
		http.Error(w, `{"error":"payload_encode_failed"}`, http.StatusInternalServerError)
		return
	}

	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}
	fmt.Printf("[api/createplaylist] Calling ML service at %s/ml/synthetic-tracks-similarity with payload: %s", mlHost, string(mlPayload))

	mlReq, err := http.NewRequest(http.MethodPost, mlHost+"/ml/synthetic-tracks-similarity", bytes.NewReader(mlPayload))
	if err != nil {
		http.Error(w, `{"error":"ml_request_build_failed"}`, http.StatusInternalServerError)
		return
	}
	mlReq.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		mlReq.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 2 * time.Minute}
	mlResp, err := client.Do(mlReq)
	if err != nil {
		log.Printf("[api/createplaylist] ML service error: %v", err)
		http.Error(w, fmt.Sprintf(`{"error":"ml_service_unavailable"}`), http.StatusBadGateway)
		return
	}
	defer mlResp.Body.Close()

	mlBody, err := io.ReadAll(mlResp.Body)
	if err != nil {
		http.Error(w, `{"error":"ml_read_failed"}`, http.StatusInternalServerError)
		return
	}
	// fmt.Println("ML [similar_tracks] response body:", string(mlBody))
	fmt.Println("ML [similar_tracks] response status:", mlResp.StatusCode)
	if mlResp.StatusCode != http.StatusOK {
		log.Printf("[api/createplaylist] ML service returned %d: %s", mlResp.StatusCode, string(mlBody))
		http.Error(w, fmt.Sprintf(`{"error":"ml_error","detail":%q}`, string(mlBody)), http.StatusBadGateway)
		return
	}

	var mlResult struct {
		SimilarTracks []struct {
			RecordingName string  `json:"recording_name"`
			ArtistName    string  `json:"artist_name"`
			ArtistName2   string  `json:"artist_name_2"`
			Similarity    float64 `json:"similarity"`
		} `json:"similar_tracks"`
	}
	if err := json.Unmarshal(mlBody, &mlResult); err != nil {
		log.Printf("[api/createplaylist] ML decode error: %v", err)
		http.Error(w, `{"error":"ml_decode_failed"}`, http.StatusInternalServerError)
		return
	}

	// 5. Search each real track on Spotify
	// For this I need to return a lot of tracks, for the user instead of just one or two
	var spotifyIDs []string
	for _, track := range mlResult.SimilarTracks {
		artist2 := track.ArtistName2
		if artist2 == "" {
			artist2 = track.ArtistName
		}
		id, err := spotify.SearchTrackID(ctx, track.RecordingName, track.ArtistName, artist2)
		if err != nil {
			log.Printf("[api/createplaylist] SearchTrackID failed (%s, %s): %v", track.RecordingName, track.ArtistName, err)
			continue
		} else {
			log.Printf("[api/createplaylist] Found Spotify ID %s for track '%s' by '%s'", id, track.RecordingName, track.ArtistName)
		}
		spotifyIDs = append(spotifyIDs, id)
	}

	// 6. Deduplicate
	seen := make(map[string]bool, len(spotifyIDs))
	var uniq []string
	for _, id := range spotifyIDs {
		if !seen[id] {
			seen[id] = true
			uniq = append(uniq, id)
		}
	}

	if len(uniq) == 0 {
		http.Error(w, `{"error":"no_spotify_tracks_found"}`, http.StatusBadRequest)
		return
	}

	// 7. Playlist name
	if req.PlaylistName == "" {
		req.PlaylistName = "MelodyMap: ML Synthetic Playlist"
	}
	if len(req.PlaylistName) > 100 {
		req.PlaylistName = req.PlaylistName[:100]
	}

	// 8. Create Spotify playlist
	playlistURL, err := spotify.CreatePlaylist(ctx, req.PlaylistName, uniq)
	if err != nil {
		log.Printf("[api/createplaylist] CreatePlaylist error: %v", err)
		http.Error(w, `{"error":"playlist_failed"}`, http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(map[string]string{
		"url": playlistURL,
	})
}
