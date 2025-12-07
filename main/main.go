package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"log"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Jonnymurillo288/MelodyMap/internal/auth"
	"github.com/Jonnymurillo288/MelodyMap/internal/jobs"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/Jonnymurillo288/MelodyMap/internal/secret"
	"github.com/Jonnymurillo288/MelodyMap/spotify"
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

func main() {
	root := findProjectRoot()
	if err := secret.LoadSecrets(""); err != nil {
		log.Fatal(err)
	}
	info, err := os.Stat("/etc/sixdegrees/auth/authconfig.json")
	fmt.Println("CONFIG FILE CHECK:", info, err)
	fmt.Printf("AUTHCONFIG RAW: %+v\n", secret.AuthConfig)

	mux := http.NewServeMux()

	// static
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.Dir(filepath.Join(root, "static")))))

	// HTML template + token inject
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		tok, _ := auth.CreateToken()
		data := struct{ Token string }{Token: tok}
		t := template.Must(template.ParseFiles(filepath.Join(root, "templates", "graph_test.html")))
		t.Execute(w, data)
	})

	// search API (background)
	// --- PROTECTED ROUTES ---
	mux.Handle("/createPlaylist", tokenAuth(http.HandlerFunc(createPlaylistHandler)))
	mux.Handle("/api/search/start", tokenAuth(http.HandlerFunc(startSearchHandler)))
	mux.Handle("/api/search/status", tokenAuth(http.HandlerFunc(searchStatusHandler)))
	mux.Handle("/lookup", tokenAuth(http.HandlerFunc(handleLookup)))

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

func handleLookup(w http.ResponseWriter, r *http.Request) {
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

// POST /createPlaylist
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
