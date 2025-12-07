package auth

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/secret"
	"golang.org/x/oauth2"
)

var Endpoint = oauth2.Endpoint{
	AuthURL:  "https://accounts.spotify.com/authorize",
	TokenURL: "https://accounts.spotify.com/api/token",
}

type preconfig struct {
	ClientID     string   `json:"client_id"`
	ClientSecret string   `json:"client_secret"`
	RedirectURL  string   `json:"redirect_url"`
	Scopes       []string `json:"scopes"`
}

var ErrNoSpotifyToken = errors.New("no spotify token")
var config *oauth2.Config

// Location where token will persist on Render:
var tokenPath = getSpotifyTokenPath()

func getSpotifyTokenPath() string {
	if p := os.Getenv("SPOTIFY_TOKEN_PATH"); p != "" {
		return p
	}
	return "/var/data/spotify_token.json"
}

// HasSpotifyToken checks whether a usable Spotify OAuth token exists
// and is refreshable. It does NOT log or expose the token.
func HasSpotifyToken() error {
	if config == nil {
		config = createConfig()
	}

	// First, quick existence check on the file
	if _, err := os.Stat(tokenPath); err != nil {
		if os.IsNotExist(err) {
			return ErrNoSpotifyToken
		}
		return fmt.Errorf("stat token file: %w", err)
	}

	// Then try to load/refresh. This catches corrupt or invalid tokens.
	if _, err := LoadSpotifyToken(config); err != nil {
		return fmt.Errorf("load/refresh spotify token: %w", err)
	}

	return nil
}

// ---------------------------------------------
// Start OAuth
// ---------------------------------------------
var expectedState = "sds-oauth-state" // static, survives OAuth cycle

func HomePage(w http.ResponseWriter, r *http.Request) {
	if config == nil {
		config = createConfig()
	}

	authURL := config.AuthCodeURL(expectedState, oauth2.AccessTypeOffline)
	http.Redirect(w, r, authURL, http.StatusFound)
}

// ---------------------------------------------
// OAuth Callback - Save Token
// ---------------------------------------------
func Authorize(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "cannot parse form", 400)
		return
	}

	// 1. Validate state
	state := r.Form.Get("state")
	if state != expectedState {
		http.Error(w, "invalid oauth state", 400)
		return
	}

	// 2. Get code
	code := r.Form.Get("code")
	if code == "" {
		http.Error(w, "missing code", 400)
		return
	}

	// 3. Load config
	if config == nil {
		config = createConfig()
	}

	// 4. Exchange code → token
	token, err := config.Exchange(context.Background(), code)
	if err != nil {
		http.Error(w, "cannot exchange token: "+err.Error(), 500)
		return
	}

	// 5. Save token
	saveToken(token)

	// 6. Popup sends event to opener
	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(`
<html><body>
<script>
  if (window.opener) {
      window.opener.postMessage({ auth: "done" }, "*");
      window.close();
  } else {
      window.location.href = "/";
  }
</script>
Auth success
</body></html>
	`))
}

// ---------------------------------------------
// Config from secret.AuthConfig (NOT disk)
// ---------------------------------------------
func createConfig() *oauth2.Config {
	var p preconfig

	b, _ := json.Marshal(secret.AuthConfig)
	json.Unmarshal(b, &p)

	return &oauth2.Config{
		ClientID:     p.ClientID,
		ClientSecret: p.ClientSecret,
		RedirectURL:  p.RedirectURL,
		Scopes:       p.Scopes,
		Endpoint:     Endpoint,
	}
}

// ---------------------------------------------
// Save OAuth token to /var/data
// ---------------------------------------------

func saveToken(tok *oauth2.Token) {
	st := struct {
		AccessToken string `json:"access_token"`
		Type        string `json:"token_type"`
		Refresh     string `json:"refresh_token"`
		Expires     string `json:"expiry"`
	}{
		AccessToken: tok.AccessToken,
		Type:        tok.TokenType,
		Refresh:     tok.RefreshToken,
		Expires:     tok.Expiry.Format(time.RFC3339Nano),
	}

	// 🔥 Ensure directory exists
	os.MkdirAll(filepath.Dir(tokenPath), 0o700)

	f, err := os.OpenFile(tokenPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		panic(err)
	}
	json.NewEncoder(f).Encode(st)
	f.Close()
}

// LoadSpotifyToken reads the stored token, refreshes it if needed,
// and writes back any updates.
func LoadSpotifyToken(config *oauth2.Config) (*oauth2.Token, error) {
	data, err := os.ReadFile(tokenPath)
	if err != nil {
		return nil, fmt.Errorf("read token file: %w", err)
	}

	var st struct {
		AccessToken string `json:"access_token"`
		Type        string `json:"token_type"`
		Refresh     string `json:"refresh_token"`
		Expires     string `json:"expiry"`
	}
	if err := json.Unmarshal(data, &st); err != nil {
		return nil, fmt.Errorf("parse token file: %w", err)
	}

	expiry, err := time.Parse(time.RFC3339Nano, st.Expires)
	if err != nil {
		return nil, fmt.Errorf("parse token expiry: %w", err)
	}

	// Build the token object
	tok := &oauth2.Token{
		AccessToken:  st.AccessToken,
		TokenType:    st.Type,
		RefreshToken: st.Refresh,
		Expiry:       expiry,
	}

	// TokenSource will auto-refresh if expired
	ts := config.TokenSource(context.Background(), tok)
	newTok, err := ts.Token()
	if err != nil {
		return nil, fmt.Errorf("refresh token: %w", err)
	}

	// If a new token was issued, persist it
	if newTok.AccessToken != tok.AccessToken || !newTok.Expiry.Equal(tok.Expiry) {
		saveToken(newTok)
	}

	return newTok, nil
}

// SpotifyClient returns an HTTP client that automatically uses
// the stored + refreshed Spotify OAuth token.
func SpotifyClient(ctx context.Context) (*http.Client, error) {
	if config == nil {
		config = createConfig()
	}

	tok, err := LoadSpotifyToken(config)
	if err != nil {
		return nil, fmt.Errorf("load spotify token: %w", err)
	}

	return config.Client(ctx, tok), nil
}
