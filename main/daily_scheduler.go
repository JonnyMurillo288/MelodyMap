package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// dailyGenres is the hardcoded list of genres to pre-compute predictions for.
var dailyGenres = []string{
	"rock", "pop", "hip hop", "jazz", "classical", "electronic",
	"r&b", "country", "metal", "folk", "punk", "blues",
}

// initDailyPredictionsTable creates the daily_predictions table if it doesn't exist.
func initDailyPredictionsTable() error {
	db, err := openDailyDB()
	if err != nil {
		return fmt.Errorf("open db for migration: %w", err)
	}
	defer db.Close()

	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS daily_predictions (
			id SERIAL PRIMARY KEY,
			date DATE NOT NULL,
			genre TEXT NOT NULL,
			src_artist_id TEXT NOT NULL,
			src_artist_name TEXT NOT NULL,
			response_json JSONB NOT NULL,
			created_at TIMESTAMPTZ DEFAULT NOW(),
			UNIQUE(date, genre)
		);
	`)
	if err != nil {
		return fmt.Errorf("create daily_predictions table: %w", err)
	}
	log.Println("[daily-scheduler] daily_predictions table ready")
	return nil
}

// openDailyDB opens a connection to the PostgreSQL database using PG_DSN.
func openDailyDB() (*sql.DB, error) {
	dsn := os.Getenv("PG_DSN")
	if dsn == "" {
		return nil, fmt.Errorf("PG_DSN not set")
	}
	// Append search_path so queries find musicbrainz schema tables
	if !strings.Contains(dsn, "search_path") {
		sep := "&"
		if !strings.Contains(dsn, "?") {
			sep = "?"
		}
		dsn = dsn + sep + "search_path=musicbrainz,public"
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	return db, nil
}

// startDailyScheduler runs a background goroutine that:
// 1. On startup, generates today's predictions if missing
// 2. Fires at 12:00 PM EST every day to generate new predictions
func startDailyScheduler() {
	go func() {
		// Generate on startup if today's data is missing
		triggerV1PopulateDaily()
		generateMissingPredictions()

		for {
			now := time.Now()
			est, err := time.LoadLocation("America/New_York")
			if err != nil {
				log.Printf("[daily-scheduler] Failed to load EST timezone: %v, using UTC-5", err)
				est = time.FixedZone("EST", -5*60*60)
			}

			nowEST := now.In(est)
			// Next 12:00 PM EST
			next := time.Date(nowEST.Year(), nowEST.Month(), nowEST.Day(), 12, 0, 0, 0, est)
			if nowEST.After(next) {
				next = next.Add(24 * time.Hour)
			}

			sleepDuration := time.Until(next)
			log.Printf("[daily-scheduler] Next generation at %s (sleeping %s)", next.Format(time.RFC3339), sleepDuration.Round(time.Second))

			timer := time.NewTimer(sleepDuration)
			<-timer.C

			log.Println("[daily-scheduler] 12:00 PM EST - generating daily predictions for all genres")
			triggerV1PopulateDaily()
			generateAllPredictions(time.Now().In(est).Format("2006-01-02"))
		}
	}()
}

// generateMissingPredictions checks if today's predictions exist and generates any that are missing.
func generateMissingPredictions() {
	est, err := time.LoadLocation("America/New_York")
	if err != nil {
		est = time.FixedZone("EST", -5*60*60)
	}
	today := time.Now().In(est).Format("2006-01-02")

	db, err := openDailyDB()
	if err != nil {
		log.Printf("[daily-scheduler] Failed to open DB for startup check: %v", err)
		return
	}
	defer db.Close()

	var count int
	err = db.QueryRow("SELECT COUNT(*) FROM daily_predictions WHERE date = $1", today).Scan(&count)
	if err != nil {
		log.Printf("[daily-scheduler] Failed to check existing predictions: %v", err)
		// Table might not exist yet, that's ok
		return
	}

	if count >= len(dailyGenres) {
		log.Printf("[daily-scheduler] Today's predictions already complete (%d/%d genres)", count, len(dailyGenres))
		return
	}

	log.Printf("[daily-scheduler] Found %d/%d genres for today, generating missing ones", count, len(dailyGenres))

	// Find which genres are missing
	rows, err := db.Query("SELECT genre FROM daily_predictions WHERE date = $1", today)
	if err != nil {
		log.Printf("[daily-scheduler] Failed to query existing genres: %v", err)
		generateAllPredictions(today)
		return
	}
	defer rows.Close()

	existing := make(map[string]bool)
	for rows.Next() {
		var g string
		rows.Scan(&g)
		existing[g] = true
	}

	for _, genre := range dailyGenres {
		if !existing[genre] {
			generateAndStorePrediction(today, genre)
		}
	}
}

// generateAllPredictions generates predictions for all genres for the given date.
func generateAllPredictions(date string) {
	for _, genre := range dailyGenres {
		generateAndStorePrediction(date, genre)
	}
	log.Printf("[daily-scheduler] Finished generating predictions for %s", date)
}

// generateAndStorePrediction calls the ML service for one genre and stores the result.
func generateAndStorePrediction(date, genre string) {
	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	payload, _ := json.Marshal(map[string]any{
		"date":  date,
		"genre": genre,
		"limit": 10,
	})

	log.Printf("[daily-scheduler] Generating predictions for genre=%q date=%s", genre, date)

	req, err := http.NewRequest(http.MethodPost, mlHost+"/interlude/daily-prediction", bytes.NewReader(payload))
	if err != nil {
		log.Printf("[daily-scheduler] Failed to build request for genre=%q: %v", genre, err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		req.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[daily-scheduler] ML service error for genre=%q: %v", genre, err)
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("[daily-scheduler] Failed to read ML response for genre=%q: %v", genre, err)
		return
	}

	if resp.StatusCode != http.StatusOK {
		log.Printf("[daily-scheduler] ML service returned %d for genre=%q: %s", resp.StatusCode, genre, string(body))
		return
	}

	// Parse response to extract artist info
	var mlResp struct {
		SrcArtistID   string `json:"src_artist_id"`
		SrcArtistName string `json:"src_artist_name"`
	}
	if err := json.Unmarshal(body, &mlResp); err != nil {
		log.Printf("[daily-scheduler] Failed to parse ML response for genre=%q: %v", genre, err)
		return
	}

	// Store in database (upsert)
	db, err := openDailyDB()
	if err != nil {
		log.Printf("[daily-scheduler] Failed to open DB for storing genre=%q: %v", genre, err)
		return
	}
	defer db.Close()

	_, err = db.Exec(`
		INSERT INTO daily_predictions (date, genre, src_artist_id, src_artist_name, response_json)
		VALUES ($1, $2, $3, $4, $5)
		ON CONFLICT (date, genre) DO UPDATE SET
			src_artist_id = EXCLUDED.src_artist_id,
			src_artist_name = EXCLUDED.src_artist_name,
			response_json = EXCLUDED.response_json,
			created_at = NOW()
	`, date, genre, mlResp.SrcArtistID, mlResp.SrcArtistName, string(body))

	if err != nil {
		log.Printf("[daily-scheduler] Failed to store prediction for genre=%q: %v", genre, err)
		return
	}

	log.Printf("[daily-scheduler] Stored prediction for genre=%q artist=%q", genre, mlResp.SrcArtistName)
}

// triggerV1PopulateDaily calls the Python ML service's internal populate-daily endpoint.
// This runs the DB-first predict+generate pipeline and stores results in both
// the shared prediction_connections/synthetic_tracks tables and daily_predictions.
func triggerV1PopulateDaily() {
	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	log.Println("[daily-scheduler] Calling v1 populate-daily endpoint")

	req, err := http.NewRequest(http.MethodPost, mlHost+"/api/v1/internal/populate-daily", nil)
	if err != nil {
		log.Printf("[daily-scheduler] Failed to build populate-daily request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		req.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[daily-scheduler] populate-daily request error: %v", err)
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		log.Printf("[daily-scheduler] populate-daily returned %d: %s", resp.StatusCode, string(body))
		return
	}

	log.Printf("[daily-scheduler] populate-daily success: %s", string(body))
}

// getDailyPrediction retrieves a stored prediction for a specific date and genre.
func getDailyPrediction(date, genre string) (json.RawMessage, error) {
	db, err := openDailyDB()
	if err != nil {
		return nil, err
	}
	defer db.Close()

	var responseJSON string
	err = db.QueryRow(
		"SELECT response_json FROM daily_predictions WHERE date = $1 AND genre = $2",
		date, genre,
	).Scan(&responseJSON)
	if err != nil {
		return nil, err
	}
	return json.RawMessage(responseJSON), nil
}

// getAllDailyPredictions retrieves all stored predictions for a specific date.
func getAllDailyPredictions(date string) (map[string]json.RawMessage, error) {
	db, err := openDailyDB()
	if err != nil {
		return nil, err
	}
	defer db.Close()

	rows, err := db.Query(
		"SELECT genre, response_json FROM daily_predictions WHERE date = $1",
		date,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make(map[string]json.RawMessage)
	for rows.Next() {
		var genre, responseJSON string
		if err := rows.Scan(&genre, &responseJSON); err != nil {
			continue
		}
		result[genre] = json.RawMessage(responseJSON)
	}
	return result, nil
}
