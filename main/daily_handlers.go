package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/auth"
	"github.com/Jonnymurillo288/MelodyMap/internal/billing"
	"github.com/Jonnymurillo288/MelodyMap/spotify"
	stripe "github.com/stripe/stripe-go/v81"
	"github.com/stripe/stripe-go/v81/checkout/session"
	"github.com/stripe/stripe-go/v81/webhook"
)

// dailyPageHandler serves the /daily HTML template with token injection.
func dailyPageHandler(w http.ResponseWriter, r *http.Request) {
	root := findProjectRoot()
	tok, err := auth.CreateToken()
	if err != nil {
		http.Error(w, fmt.Sprintf("token generation failed: %s", err), 500)
		return
	}
	data := struct{ Token string }{Token: tok}
	t := template.Must(template.ParseFiles(filepath.Join(root, "templates", "daily.html")))
	t.Execute(w, data)
}

// dailyTodayHandler returns all pre-computed predictions for today (all genres).
func dailyTodayHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	est, err := time.LoadLocation("America/New_York")
	if err != nil {
		est = time.FixedZone("EST", -5*60*60)
	}
	today := time.Now().In(est).Format("2006-01-02")

	genres, err := getAllDailyPredictions(today)
	if err != nil {
		log.Printf("[daily/today] Failed to fetch predictions: %v", err)
		json.NewEncoder(w).Encode(map[string]any{
			"date":   today,
			"genres": map[string]any{},
			"ready":  false,
		})
		return
	}

	json.NewEncoder(w).Encode(map[string]any{
		"date":   today,
		"genres": genres,
		"ready":  len(genres) > 0,
	})
}

// dailyPredictHandler proxies genre-based prediction to the Python ML service.
// First checks for pre-computed daily predictions; falls back to on-demand if not found.
func dailyPredictHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Println("[daily/predict] Received prediction request")

	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"error": "method_not_allowed"})
		return
	}

	var req struct {
		Genre string `json:"genre"`
		Date  string `json:"date"`
		Limit int    `json:"limit"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid_body"}`, http.StatusBadRequest)
		return
	}

	if req.Genre == "" {
		http.Error(w, `{"error":"missing_genre"}`, http.StatusBadRequest)
		return
	}
	if req.Limit <= 0 || req.Limit > 50 {
		req.Limit = 10
	}
	if req.Date == "" {
		est, err := time.LoadLocation("America/New_York")
		if err != nil {
			est = time.FixedZone("EST", -5*60*60)
		}
		req.Date = time.Now().In(est).Format("2006-01-02")
	}

	// Check for pre-computed prediction first (no billing cost)
	cached, err := getDailyPrediction(req.Date, req.Genre)
	if err == nil && cached != nil {
		log.Printf("[daily/predict] Serving cached prediction for genre=%q date=%s", req.Genre, req.Date)
		w.Write(cached)
		return
	}

	// Use a default user ID since the app currently has single-user Spotify auth.
	userID := "default_user"

	// Check tier and usage limits
	info := billing.GetUserInfo(userID)
	if info.Tier == "free" && info.UsageToday >= 1 {
		w.WriteHeader(http.StatusForbidden)
		json.NewEncoder(w).Encode(map[string]any{
			"error":       "daily_limit_reached",
			"tier":        info.Tier,
			"usage_today": info.UsageToday,
			"daily_limit": info.DailyLimit,
		})
		return
	}

	// Proxy to Python ML service
	mlPayload, err := json.Marshal(map[string]any{
		"date":  req.Date,
		"genre": req.Genre,
		"limit": req.Limit,
	})
	if err != nil {
		http.Error(w, `{"error":"payload_encode_failed"}`, http.StatusInternalServerError)
		return
	}

	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	mlURL := mlHost + "/interlude/daily-prediction"
	fmt.Printf("[daily/predict] Calling ML service at %s with payload: %s\n", mlURL, string(mlPayload))

	mlReq, err := http.NewRequest(http.MethodPost, mlURL, bytes.NewReader(mlPayload))
	if err != nil {
		http.Error(w, `{"error":"ml_request_build_failed"}`, http.StatusInternalServerError)
		return
	}
	mlReq.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		mlReq.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 5 * time.Minute}
	mlResp, err := client.Do(mlReq)
	if err != nil {
		log.Printf("[daily/predict] ML service error: %v", err)
		http.Error(w, `{"error":"ml_service_unavailable"}`, http.StatusBadGateway)
		return
	}
	defer mlResp.Body.Close()

	mlBody, err := io.ReadAll(mlResp.Body)
	if err != nil {
		http.Error(w, `{"error":"ml_read_failed"}`, http.StatusInternalServerError)
		return
	}

	if mlResp.StatusCode != http.StatusOK {
		log.Printf("[daily/predict] ML service returned %d: %s", mlResp.StatusCode, string(mlBody))
		w.WriteHeader(http.StatusBadGateway)
		w.Write(mlBody)
		return
	}

	// Increment usage on success
	if err := billing.IncrementDailyUsage(userID); err != nil {
		log.Printf("[daily/predict] Failed to increment usage: %v", err)
	}

	w.Write(mlBody)
}

// dailyCreatePlaylistHandler creates a Spotify playlist from selected synthetic connections.
// Reuses the same ML similarity → Spotify search → playlist creation flow.
func dailyCreatePlaylistHandler(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"error": "method_not_allowed"})
		return
	}

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

	// Spotify auth pre-check
	if err := auth.HasSpotifyToken(); err != nil {
		if errors.Is(err, auth.ErrNoSpotifyToken) {
			json.NewEncoder(w).Encode(map[string]any{
				"auth_required": true,
				"auth_url":      "/auth/start",
			})
			return
		}
		log.Printf("[daily/create-playlist] Spotify token error: %v", err)
		http.Error(w, `{"error":"spotify_token_error"}`, http.StatusInternalServerError)
		return
	}

	// Collect all synthetic track IDs
	var allSynthTrackIds []int
	for _, conn := range req.Connections {
		allSynthTrackIds = append(allSynthTrackIds, conn.SynthTrackIds...)
	}
	if len(allSynthTrackIds) == 0 {
		http.Error(w, `{"error":"no_synth_tracks"}`, http.StatusBadRequest)
		return
	}

	// Call Python ML service to find similar real tracks
	mlPayload, _ := json.Marshal(map[string]any{
		"input_tracks":       allSynthTrackIds,
		"num_similar_tracks": 10,
	})

	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	mlReq, _ := http.NewRequest(http.MethodPost, mlHost+"/ml/synthetic-tracks-similarity", bytes.NewReader(mlPayload))
	mlReq.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		mlReq.Header.Set("X-Internal-Secret", secret)
	}

	httpClient := &http.Client{Timeout: 2 * time.Minute}
	mlResp, err := httpClient.Do(mlReq)
	if err != nil {
		log.Printf("[daily/create-playlist] ML service error: %v", err)
		http.Error(w, `{"error":"ml_service_unavailable"}`, http.StatusBadGateway)
		return
	}
	defer mlResp.Body.Close()

	mlBody, _ := io.ReadAll(mlResp.Body)
	if mlResp.StatusCode != http.StatusOK {
		log.Printf("[daily/create-playlist] ML service returned %d: %s", mlResp.StatusCode, string(mlBody))
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
		http.Error(w, `{"error":"ml_decode_failed"}`, http.StatusInternalServerError)
		return
	}

	// Search each real track on Spotify
	var spotifyIDs []string
	for _, track := range mlResult.SimilarTracks {
		artist2 := track.ArtistName2
		if artist2 == "" {
			artist2 = track.ArtistName
		}
		id, err := spotify.SearchTrackID(ctx, track.RecordingName, track.ArtistName, artist2)
		if err != nil {
			continue
		}
		spotifyIDs = append(spotifyIDs, id)
	}

	// Deduplicate
	seen := make(map[string]bool)
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

	if req.PlaylistName == "" {
		req.PlaylistName = "MelodyMap Daily Playlist"
	}
	if len(req.PlaylistName) > 100 {
		req.PlaylistName = req.PlaylistName[:100]
	}

	playlistURL, err := spotify.CreatePlaylist(ctx, req.PlaylistName, uniq)
	if err != nil {
		log.Printf("[daily/create-playlist] CreatePlaylist error: %v", err)
		http.Error(w, `{"error":"playlist_failed"}`, http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"url": playlistURL})
}

// userTierHandler returns the current user's tier and usage info.
func userTierHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	userID := "default_user"
	info := billing.GetUserInfo(userID)
	json.NewEncoder(w).Encode(info)
}

// stripeCreateCheckoutHandler creates a Stripe Checkout Session.
func stripeCreateCheckoutHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"error": "method_not_allowed"})
		return
	}

	stripe.Key = os.Getenv("STRIPE_SECRET_KEY")
	if stripe.Key == "" {
		http.Error(w, `{"error":"stripe_not_configured"}`, http.StatusInternalServerError)
		return
	}

	var req struct {
		Plan string `json:"plan"` // "monthly" or "lifetime"
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid_body"}`, http.StatusBadRequest)
		return
	}

	var priceID string
	var mode stripe.CheckoutSessionMode

	switch req.Plan {
	case "monthly":
		priceID = os.Getenv("STRIPE_PRICE_MONTHLY")
		mode = stripe.CheckoutSessionModeSubscription
	case "lifetime":
		priceID = os.Getenv("STRIPE_PRICE_LIFETIME")
		mode = stripe.CheckoutSessionModePayment
	default:
		http.Error(w, `{"error":"invalid_plan"}`, http.StatusBadRequest)
		return
	}

	if priceID == "" {
		http.Error(w, `{"error":"price_not_configured"}`, http.StatusInternalServerError)
		return
	}

	successURL := os.Getenv("STRIPE_SUCCESS_URL")
	if successURL == "" {
		successURL = "http://localhost:8080/daily?payment=success"
	}
	cancelURL := os.Getenv("STRIPE_CANCEL_URL")
	if cancelURL == "" {
		cancelURL = "http://localhost:8080/daily?payment=cancelled"
	}

	params := &stripe.CheckoutSessionParams{
		Mode: stripe.String(string(mode)),
		LineItems: []*stripe.CheckoutSessionLineItemParams{
			{
				Price:    stripe.String(priceID),
				Quantity: stripe.Int64(1),
			},
		},
		SuccessURL:        stripe.String(successURL),
		CancelURL:         stripe.String(cancelURL),
		ClientReferenceID: stripe.String("default_user"),
	}

	s, err := session.New(params)
	if err != nil {
		log.Printf("[stripe/checkout] Error creating session: %v", err)
		http.Error(w, `{"error":"checkout_session_failed"}`, http.StatusInternalServerError)
		return
	}

	json.NewEncoder(w).Encode(map[string]string{"checkout_url": s.URL})
}

// stripeWebhookHandler processes Stripe webhook events.
func stripeWebhookHandler(w http.ResponseWriter, r *http.Request) {
	stripe.Key = os.Getenv("STRIPE_SECRET_KEY")

	body, err := io.ReadAll(io.LimitReader(r.Body, 65536))
	if err != nil {
		http.Error(w, "read body failed", http.StatusBadRequest)
		return
	}

	whSecret := os.Getenv("STRIPE_WEBHOOK_SECRET")
	event, err := webhook.ConstructEvent(body, r.Header.Get("Stripe-Signature"), whSecret)
	if err != nil {
		log.Printf("[stripe/webhook] Signature verification failed: %v", err)
		http.Error(w, "invalid signature", http.StatusBadRequest)
		return
	}

	switch event.Type {
	case "checkout.session.completed":
		var sess stripe.CheckoutSession
		if err := json.Unmarshal(event.Data.Raw, &sess); err != nil {
			log.Printf("[stripe/webhook] Failed to parse session: %v", err)
			break
		}
		userID := sess.ClientReferenceID
		subType := "lifetime"
		if sess.Mode == stripe.CheckoutSessionModeSubscription {
			subType = "monthly"
		}
		customerID := ""
		if sess.Customer != nil {
			customerID = sess.Customer.ID
		}
		if err := billing.SetUserTier(userID, "paid", customerID, subType); err != nil {
			log.Printf("[stripe/webhook] Failed to upgrade user %s: %v", userID, err)
		} else {
			log.Printf("[stripe/webhook] User %s upgraded to paid (%s)", userID, subType)
		}

		// Also upgrade the Python API tier via internal endpoint
		if customerEmail := sess.CustomerEmail; customerEmail != "" {
			go syncAPITier(customerEmail, "enterprise")
		}

	case "customer.subscription.deleted":
		var sub stripe.Subscription
		if err := json.Unmarshal(event.Data.Raw, &sub); err != nil {
			log.Printf("[stripe/webhook] Failed to parse subscription: %v", err)
			break
		}
		// Downgrade user - we need to find user by customer ID
		// For now with single user, just downgrade default_user
		if err := billing.SetUserTier("default_user", "free", "", ""); err != nil {
			log.Printf("[stripe/webhook] Failed to downgrade user: %v", err)
		} else {
			log.Printf("[stripe/webhook] User downgraded to free tier")
		}
		// Also downgrade the Python API tier
		// TODO: look up email from customer ID for accurate targeting
		go syncAPITier("default_user", "free")
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// syncAPITier calls the Python ML service's internal upgrade-tier endpoint
// to keep the api_users tier in sync with Stripe billing changes.
func syncAPITier(email, tier string) {
	mlHost := os.Getenv("ML_SERVICE_URL")
	if mlHost == "" {
		mlHost = "http://127.0.0.1:8000"
	}

	payload, _ := json.Marshal(map[string]string{"email": email, "tier": tier})
	req, err := http.NewRequest(http.MethodPost, mlHost+"/api/v1/internal/upgrade-tier", bytes.NewReader(payload))
	if err != nil {
		log.Printf("[stripe/sync-tier] Failed to build request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
		req.Header.Set("X-Internal-Secret", secret)
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[stripe/sync-tier] Request error: %v", err)
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		log.Printf("[stripe/sync-tier] Returned %d: %s", resp.StatusCode, string(body))
		return
	}
	log.Printf("[stripe/sync-tier] Synced tier=%s for email=%s", tier, email)
}

// Ensure context import is used
var _ = context.Background
