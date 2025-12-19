package secret

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"os"
)

type AuthConfigStruct struct {
	ClientID     string   `json:"client_id"`
	ClientSecret string   `json:"client_secret"`
	RedirectURL  string   `json:"redirect_url"`
	Scopes       []string `json:"scopes"`
	TokenSecret  string   `json:"token_secret"` // For SDS_TOKEN_SECRET
}

var AuthConfig AuthConfigStruct

// generateTokenSecret creates a random 32-byte secret for token signing
func generateTokenSecret() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Printf("Warning: Failed to generate random token secret: %v", err)
		return "fallback-insecure-secret-change-in-production"
	}
	return base64.StdEncoding.EncodeToString(b)
}

// LoadSecrets always loads from:
// 1. Environment variables (Render safe)
// 2. authconfig.json located in the project root
func LoadSecrets(_ string) error {

	// ----- 1. Load from environment -----
	id := os.Getenv("SPOTIFY_CLIENT_ID")
	secret := os.Getenv("SPOTIFY_CLIENT_SECRET")
	redirect := os.Getenv("SPOTIFY_REDIRECT_URI")
	tokenSecret := os.Getenv("SDS_TOKEN_SECRET")

	if id != "" && secret != "" && redirect != "" {
		AuthConfig = AuthConfigStruct{
			ClientID:     id,
			ClientSecret: secret,
			RedirectURL:  redirect,
			TokenSecret:  tokenSecret, // May be empty, will be generated if needed
			Scopes: []string{
				"playlist-modify-private",
				"playlist-modify-public",
				"user-read-email",
				"user-read-private",
			},
		}

		// Set SDS_TOKEN_SECRET env var for auth package if not already set
		if tokenSecret != "" {
			os.Setenv("SDS_TOKEN_SECRET", tokenSecret)
		}

		// Generate a token secret if not provided (development fallback)
		ensureTokenSecret()

		return nil
	}

	// ----- 2. Try local authconfig.json -----
	b, err := os.ReadFile("authconfig.json")
	if err == nil {
		err = json.Unmarshal(b, &AuthConfig)
		if err != nil {
			return fmt.Errorf("invalid authconfig.json: %w", err)
		}

		// Set SDS_TOKEN_SECRET env var from config file
		if AuthConfig.TokenSecret != "" {
			os.Setenv("SDS_TOKEN_SECRET", AuthConfig.TokenSecret)
		}

		// Generate a token secret if not provided (development fallback)
		ensureTokenSecret()

		return nil
	}

	return fmt.Errorf("missing Spotify configuration ENV vars or authconfig.json")
}

// ensureTokenSecret makes sure SDS_TOKEN_SECRET is set, generating one if needed
func ensureTokenSecret() {
	if os.Getenv("SDS_TOKEN_SECRET") == "" {
		secret := generateTokenSecret()
		os.Setenv("SDS_TOKEN_SECRET", secret)
		log.Println("Warning: SDS_TOKEN_SECRET not configured, generated random secret for this session")
		log.Println("For production, set SDS_TOKEN_SECRET environment variable or add 'token_secret' to authconfig.json")
	}
}
