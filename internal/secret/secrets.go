package secret

import (
	"encoding/json"
	"fmt"
	"os"
)

type AuthConfigStruct struct {
	ClientID     string   `json:"client_id"`
	ClientSecret string   `json:"client_secret"`
	RedirectURL  string   `json:"redirect_url"`
	Scopes       []string `json:"scopes"`
}

var AuthConfig AuthConfigStruct

// LoadSecrets always loads from:
// 1. Environment variables (Render safe)
// 2. authconfig.json located in the project root
func LoadSecrets(_ string) error {

	// ----- 1. Load from environment -----
	id := os.Getenv("SPOTIFY_CLIENT_ID")
	secret := os.Getenv("SPOTIFY_CLIENT_SECRET")
	redirect := os.Getenv("SPOTIFY_REDIRECT_URI")

	if id != "" && secret != "" && redirect != "" {
		AuthConfig = AuthConfigStruct{
			ClientID:     id,
			ClientSecret: secret,
			RedirectURL:  redirect,
			Scopes: []string{
				"playlist-modify-private",
				"playlist-modify-public",
				"user-read-email",
				"user-read-private",
			},
		}
		return nil
	}

	// ----- 2. Try local authconfig.json -----
	b, err := os.ReadFile("authconfig.json")
	if err == nil {
		err = json.Unmarshal(b, &AuthConfig)
		if err != nil {
			return fmt.Errorf("invalid authconfig.json: %w", err)
		}
		return nil
	}

	return fmt.Errorf("missing Spotify configuration ENV vars or authconfig.json")
}
