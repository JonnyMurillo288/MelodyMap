package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"log"
	"mime"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/auth"
	"github.com/Jonnymurillo288/MelodyMap/internal/jobs"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/Jonnymurillo288/MelodyMap/internal/secret"
	"github.com/Jonnymurillo288/MelodyMap/spotify"
	"github.com/joho/godotenv"
)

var lookupMu sync.RWMutex
var lastSearchResponse *searchRequest

func init() {
	mime.AddExtensionType(".css", "text/css")
	mime.AddExtensionType(".js", "application/javascript")
}

// findProjectRoot walks up a few levels to find /static and /templates.
func findProjectRoot() string {
	dir, err := os.Getwd()
	if err != nil {
		log.Fatal(err)
	}
	for i := 0; i < 8; i++ {
		static := filepath.Join(dir, "static")
		templates := filepath.Join(dir, "templates")
		if exists(static) && exists(templates) {
			return dir
		}
		dir = filepath.Dir(dir)
	}
	log.Fatal("Could not locate project root containing /static and /templates")
	return ""
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// tokenAuth enforces the short-lived anti-scrape token on API routes.
func tokenAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tok := r.Header.Get("X-SDS-Token")
		if tok == "" || !auth.ValidateToken(tok) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func loadEnv() {
	runEnv := os.Getenv("RUN_ENV")

	switch runEnv {
	case "docker":
		// Docker already injects env vars via docker-compose
		log.Println("[ENV] Running in Docker, skipping .env loading")

	default:
		// Local dev
		if err := godotenv.Load(".env.local"); err != nil {
			log.Printf("[ENV] .env.local not found (ok): %v", err)
		} else {
			log.Println("[ENV] Loaded .env.local")
		}
	}
}

func main() {
	// Load .env file
	loadEnv()

	root := findProjectRoot()
	if err := secret.LoadSecrets(""); err != nil {
		log.Fatal(err)
	}
	info, err := os.Stat("/etc/sixdegrees/auth/authconfig.json")
	fmt.Println("CONFIG FILE CHECK:", info, err)
	fmt.Printf("AUTHCONFIG RAW: %+v\n", secret.AuthConfig)

	mux := http.NewServeMux()

	// Reverse proxy /api/v1/* to the ML service
	// On Render, both services have separate URLs so the browser can't reach ML directly.
	mlURL := os.Getenv("ML_SERVICE_URL")
	if mlURL == "" {
		mlURL = "http://127.0.0.1:8000"
	}
	mlTarget, _ := url.Parse(mlURL)
	mlProxy := httputil.NewSingleHostReverseProxy(mlTarget)
	mlProxy.Transport = &http.Transport{
		ResponseHeaderTimeout: 120 * time.Second,
		IdleConnTimeout:       90 * time.Second,
	}
	// Override the Director to set the correct Host header for Render internal networking
	origDirector := mlProxy.Director
	mlProxy.Director = func(r *http.Request) {
		origDirector(r)
		r.Host = mlTarget.Host
	}
	mux.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) {
		// Pass through user requests as-is — don't inject internal secret.
		// The user's X-API-Key header handles auth on the ML side.
		mlProxy.ServeHTTP(w, r)
	})

	// static
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.Dir(filepath.Join(root, "static")))))

	// Homepage → Demo page (the landing page for leads)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		t := template.Must(template.ParseFiles(filepath.Join(root, "templates", "demo.html")))
		t.Execute(w, nil)
	})

	// Combined graph + ML page (the full exploration dashboard)
	mux.HandleFunc("/combined", func(w http.ResponseWriter, r *http.Request) {
		tok, err := auth.CreateToken()
		if err != nil {
			http.Error(w, fmt.Sprintf("token generation failed %s", err), 500)
			return
		}
		data := struct{ Token string }{Token: tok}
		t := template.Must(template.ParseFiles(filepath.Join(root, "templates", "combined.html")))
		t.Execute(w, data)
	})

	// search API (background)
	// --- PROTECTED ROUTES ---
	mux.Handle("/createPlaylist", tokenAuth(http.HandlerFunc(createPlaylistHandler)))
	mux.Handle("/api/createplaylist", tokenAuth(http.HandlerFunc(createPlaylistFromSavedHandler)))
	mux.Handle("/api/search/start", tokenAuth(http.HandlerFunc(startSearchHandler)))
	mux.Handle("/api/search/status", tokenAuth(http.HandlerFunc(searchStatusHandler)))
	mux.Handle("/lookup", tokenAuth(http.HandlerFunc(handleArtistLookup)))
	mux.Handle("/api/artist/neighbors", tokenAuth(http.HandlerFunc(artistNeighborsHandler)))
	mux.Handle("/trackLookup", http.HandlerFunc(handleTrackLookup))
	mux.Handle("/artistLookupByGID", http.HandlerFunc(handleArtistLookupByGID))

	// Spotify OAuth begin (public)
	mux.HandleFunc("/auth/start", auth.HomePage)

	// Spotify OAuth callback
	mux.HandleFunc("/auth/callback", auth.Authorize)

	mux.HandleFunc("/api/search/ticker", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(search.SearchTicker)
	})

	// others
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"ok": true})
	})

	// Daily Page
	mux.HandleFunc("/daily", dailyPageHandler)
	mux.Handle("/api/daily/predict", tokenAuth(http.HandlerFunc(dailyPredictHandler)))
	mux.Handle("/api/daily/today", tokenAuth(http.HandlerFunc(dailyTodayHandler)))
	mux.Handle("/api/daily/create-playlist", tokenAuth(http.HandlerFunc(dailyCreatePlaylistHandler)))
	mux.Handle("/api/user/tier", tokenAuth(http.HandlerFunc(userTierHandler)))

	// Stripe endpoints (NOT behind tokenAuth — Stripe calls webhook directly)
	mux.HandleFunc("/api/stripe/create-checkout", stripeCreateCheckoutHandler)
	mux.HandleFunc("/api/stripe/webhook", stripeWebhookHandler)

	// /demo redirects to homepage (backward compat)
	mux.HandleFunc("/demo", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/", http.StatusMovedPermanently)
	})

	// API Documentation page (served as raw HTML — contains {{BASE_URL}} JS placeholders
	// that conflict with Go's template engine)
	mux.HandleFunc("/docs", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		http.ServeFile(w, r, filepath.Join(root, "templates", "docs.html"))
	})

	// Machine Learning Page
	mux.HandleFunc("/ml", func(w http.ResponseWriter, r *http.Request) {
		tok, err := auth.CreateToken()
		if err != nil {
			http.Error(w, fmt.Sprintf("token generation failed %s", err), 500)
			return
		}
		data := struct{ Token string }{Token: tok}
		t := template.Must(template.ParseFiles(filepath.Join(root, "templates", "ml_page.html")))
		t.Execute(w, data)
	})

	// MachineLearning API (background)
	// --- TODO: PROTECT THE ROUTES ---
	mux.Handle("/ml/synth/artist", tokenAuth(http.HandlerFunc(HandleMachineLearningMainPage)))
	mux.Handle("/ml/synth/tracks", tokenAuth(http.HandlerFunc(SynthTrackLookupHandler)))

	// Initialize daily predictions table and start scheduler
	if err := initDailyPredictionsTable(); err != nil {
		log.Printf("[WARN] Failed to init daily_predictions table: %v", err)
	} else {
		startDailyScheduler()
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Println("Listening on :" + port)
	err = http.ListenAndServe(":"+port, mux)
	if err != nil {
		log.Fatal(err)
	}
}

// GET - Tells backend to give me what you have so far in the GlobalNeighborLookup for this [Name]
func handleArtistLookup(w http.ResponseWriter, r *http.Request) {
	name := strings.ToLower(r.URL.Query().Get("name"))

	step, ok := search.GlobalNeighborLookup[name]
	// Default is an empty neighbor list if there is no name lookup. This would be an error
	if !ok {
		json.NewEncoder(w).Encode(struct {
			Name      string      `json:"Name"`
			Neighbors interface{} `json:"Neighbors"`
		}{Name: name, Neighbors: []interface{}{}})
		return
	}

	json.NewEncoder(w).Encode(step)
}

type gidFeaturesToGet struct {
	GIDs []string `json:"gids"`
}

// GET - Tells backend to give me what you have so far in the GlobalNeighborLookup for this [Name]
// output is type search.FrontendTracksList map[gid]RecordingFeatures
// RecordingFeatures:
func handleTrackLookup(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "method_not_allowed",
		})
		return
	}

	fmt.Println("[TRACK LOOKUP] HIT")
	// name := strings.ToLower(r.URL.Query().Get("track"))
	var featuresMap gidFeaturesToGet
	var features search.FrontendTracksList

	// Should be passing in Json type with list of []string `json:"gids"`
	err := json.NewDecoder(r.Body).Decode(&featuresMap)

	store, err := search.Open("")
	if err != nil {
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	// fmt.Println("Here are the input recording featuresby gids:", featuresMap)
	// fmt.Printf("The types of the items in the featres: %T\n", (featuresMap.GIDs[0]))
	features.FeaturesMap, err = search.GetRecordingFeaturesByGIDs(ctx, store, featuresMap.GIDs)
	json.NewEncoder(w).Encode(features)
}

// POST /artistLookupByGID - Batch lookup artist names by their GIDs
func handleArtistLookupByGID(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "method_not_allowed",
		})
		return
	}

	var req struct {
		GIDs []string `json:"gids"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid_body"}`, http.StatusBadRequest)
		return
	}

	fmt.Printf("[artistLookupByGID] Received %d GIDs: %v\n", len(req.GIDs), req.GIDs)

	store, err := search.Open("")
	if err != nil {
		fmt.Printf("[artistLookupByGID] Failed to open store: %v\n", err)
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	// Build response map: gid -> name
	namesMap := make(map[string]string)
	for _, gid := range req.GIDs {
		artist, err := store.LookupArtistByMBID(gid)
		if err != nil {
			fmt.Printf("[artistLookupByGID] Failed to lookup GID %s: %v\n", gid, err)
			continue
		}
		if artist != nil {
			namesMap[gid] = artist.Name
			fmt.Printf("[artistLookupByGID] Resolved %s -> %s\n", gid, artist.Name)
		}
	}

	fmt.Printf("[artistLookupByGID] Returning %d resolved names\n", len(namesMap))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"artistNames": namesMap,
	})
}

// POST /createPlaylist
func createPlaylistHandler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	w.Header().Set("Content-Type", "application/json")
	fmt.Println("HIT CREATE PLAYLIST ENDPOINT")

	var req struct {
		PlaylistName string `json:"playlistName"`
		JobID        string `json:"jobID"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid_body"}`, http.StatusBadRequest)
		return
	}

	// 0. Spotify auth pre-check via auth package
	if err := auth.HasSpotifyToken(); err != nil {
		if errors.Is(err, auth.ErrNoSpotifyToken) {
			json.NewEncoder(w).Encode(map[string]any{
				"auth_required": true,
				"auth_url":      "/auth/start",
			})
			return
		}

		fmt.Printf("Spotify token error: %v", err)
		http.Error(w, `{"error":"spotify_token_error"}`, http.StatusInternalServerError)
		return
	}

	// 1. BFS job checks
	if req.JobID == "" {
		http.Error(w, `{"error":"missing_jobID"}`, http.StatusBadRequest)
		return
	}

	job, _ := jobs.Manager.Get(req.JobID)
	if job == nil {
		http.Error(w, `{"error":"invalid_jobID"}`, http.StatusNotFound)
		return
	}

	if job.Status != jobs.StatusFinished {
		http.Error(w, `{"error":"job_not_finished"}`, http.StatusBadRequest)
		return
	}

	result, ok := job.Result.(search.SearchResponse)
	if !ok {
		http.Error(w, `{"error":"bad_job_result"}`, http.StatusInternalServerError)
		return
	}

	path := result.Path
	if len(path) == 0 {
		http.Error(w, `{"error":"no_path"}`, http.StatusBadRequest)
		return
	}

	if req.PlaylistName == "" {
		req.PlaylistName = "SixDegreeSpotify: " + result.Start + " → " + result.Target
	}
	if len(req.PlaylistName) > 100 {
		req.PlaylistName = req.PlaylistName[:100]
	}

	// 2. Convert BFS track names → Spotify IDs
	var spotifyIDs []string

	for _, step := range path {
		from := step.From
		to := step.To

		for _, t := range step.Tracks {
			recName := t.RecordingName
			if recName == "" {
				recName = t.Name
			}
			if recName == "" {
				continue
			}

			id, err := spotify.SearchTrackID(ctx, recName, from, to)
			if err != nil {
				log.Printf("SearchTrackID failed (%s,%s,%s): %v", recName, from, to, err)
				continue
			}
			spotifyIDs = append(spotifyIDs, id)
		}
	}
	fmt.Println("TRACK IDS FOUND:", spotifyIDs)
	// Deduplicate track IDs to keep playlist clean + avoid errors
	seen := make(map[string]bool, len(spotifyIDs))
	uniq := make([]string, 0, len(spotifyIDs))
	for _, id := range spotifyIDs {
		if !seen[id] {
			seen[id] = true
			uniq = append(uniq, id)
		}
	}
	spotifyIDs = uniq

	if len(spotifyIDs) == 0 {
		http.Error(w, `{"error":"no_spotify_tracks_found"}`, http.StatusBadRequest)
		return
	}

	// Need to save the number of tracks attempted to get, and the number of tracks inserted based on the src artist_id, this will help test how well the spotify search is working, and if there are certain artists that are not working well with the search
	log.Printf("Attempting to find Spotify IDs for %d tracks from BFS path", len(spotifyIDs))
	// Save a csv logging with |src_artist_id|num_tracks|num_spotify_ids_found for each step in the path, this will help us understand if there are certain artists that are not working well with the spotify search, and if there are certain steps in the path that are more difficult to find spotify tracks for
	// Save at ./internal/interlude_service/machine_learning/outputs/createPlaylistLogging/spotify_search_log.csv
	logFile, err := os.OpenFile("./internal/interlude_service/machine_learning/outputs/createPlaylistLogging/spotify_search_log.csv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("Failed to open log file: %v", err)
	} else {
		defer logFile.Close()
		for _, step := range path {
			srcArtistID := step.From
			numTracks := len(step.Tracks)
			numSpotifyIDs := 0
			for _, t := range step.Tracks {
				recName := t.RecordingName
				if recName == "" {
					recName = t.Name
				}
				if recName == "" {
					continue
				}
				id, err := spotify.SearchTrackID(ctx, recName, step.From, step.To)
				if err == nil && id != "" {
					numSpotifyIDs++
				}
			}
			logLine := fmt.Sprintf("%s|%d|%d\n", srcArtistID, numTracks, numSpotifyIDs)
			if _, err := logFile.WriteString(logLine); err != nil {
				log.Printf("Failed to write log line: %v", err)
			}
		}
	}

	// 3. Create playlist
	playlistURL, err := spotify.CreatePlaylist(ctx, req.PlaylistName, spotifyIDs)
	if err != nil {
		log.Println("CreatePlaylist ERROR:", err)
		http.Error(w, `{"error":"playlist_failed"}`, http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(map[string]string{
		"url": playlistURL,
	})
}

func extractSpotifyTrackIDs(path []search.Step) []string {
	ids := []string{}

	for _, step := range path {
		for _, t := range step.Tracks {
			if t.ID != "" {
				ids = append(ids, t.ID)
			}
		}
	}
	return ids
}
