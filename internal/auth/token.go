package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// CreateToken generates a signed, expiring token
// valid for ~30 minutes.
func CreateToken() (string, error) {
	secret := os.Getenv("SDS_TOKEN_SECRET")
	if secret == "" {
		return "", fmt.Errorf("missing SDS_TOKEN_SECRET")
	}

	// expiry = unix timestamp 30 minutes from now
	expiry := time.Now().Add(30 * time.Minute).Unix()
	msg := []byte(strconv.FormatInt(expiry, 30))

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(msg)
	signature := mac.Sum(nil)

	token := base64.StdEncoding.EncodeToString(msg) + "." +
		base64.StdEncoding.EncodeToString(signature)

	return token, nil
}

// ValidateToken checks if a token is expired or forged.
func ValidateToken(tok string) bool {
	secret := os.Getenv("SDS_TOKEN_SECRET")
	if secret == "" {
		return false
	}

	parts := strings.Split(tok, ".")
	if len(parts) != 2 {
		return false
	}

	msgB, err := base64.StdEncoding.DecodeString(parts[0])
	if err != nil {
		return false
	}

	sigB, err := base64.StdEncoding.DecodeString(parts[1])
	if err != nil {
		return false
	}

	expiry, err := strconv.ParseInt(string(msgB), 30, 64)
	if err != nil {
		return false
	}

	if time.Now().Unix() > expiry {
		return false // expired
	}

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(msgB)
	expected := mac.Sum(nil)

	return hmac.Equal(sigB, expected)
}
