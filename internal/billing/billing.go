package billing

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	mu       sync.RWMutex
	store    *billingStore
	dataPath = getBillingDataPath()
)

func getBillingDataPath() string {
	if p := os.Getenv("BILLING_DATA_PATH"); p != "" {
		return p
	}
	return "billing_data.json"
}

type UserTier struct {
	Tier             string         `json:"tier"`
	StripeCustomerID string         `json:"stripe_customer_id,omitempty"`
	SubscriptionType string         `json:"subscription_type,omitempty"` // "monthly" or "lifetime"
	DailyUsage       map[string]int `json:"daily_usage"`
}

type billingStore struct {
	Users map[string]*UserTier `json:"users"`
}

func load() *billingStore {
	if store != nil {
		return store
	}

	store = &billingStore{Users: make(map[string]*UserTier)}

	data, err := os.ReadFile(dataPath)
	if err != nil {
		return store
	}

	json.Unmarshal(data, store)
	if store.Users == nil {
		store.Users = make(map[string]*UserTier)
	}
	return store
}

func save() error {
	s := load()

	if dir := filepath.Dir(dataPath); dir != "." {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return fmt.Errorf("create billing dir: %w", err)
		}
	}

	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(dataPath, data, 0o600)
}

func getOrCreateUser(userID string) *UserTier {
	s := load()
	u, ok := s.Users[userID]
	if !ok {
		u = &UserTier{
			Tier:       "free",
			DailyUsage: make(map[string]int),
		}
		s.Users[userID] = u
	}
	if u.DailyUsage == nil {
		u.DailyUsage = make(map[string]int)
	}
	return u
}

func todayStr() string {
	return time.Now().UTC().Format("2006-01-02")
}

// GetUserTier returns "free" or "paid" for the given user.
func GetUserTier(userID string) string {
	mu.RLock()
	defer mu.RUnlock()
	return getOrCreateUser(userID).Tier
}

// GetDailyUsage returns how many predictions the user has made today.
func GetDailyUsage(userID string) int {
	mu.RLock()
	defer mu.RUnlock()
	return getOrCreateUser(userID).DailyUsage[todayStr()]
}

// IncrementDailyUsage bumps the daily usage counter by 1.
func IncrementDailyUsage(userID string) error {
	mu.Lock()
	defer mu.Unlock()
	u := getOrCreateUser(userID)
	u.DailyUsage[todayStr()]++
	return save()
}

// SetUserTier upgrades or downgrades a user's tier.
func SetUserTier(userID, tier, stripeCustomerID, subscriptionType string) error {
	mu.Lock()
	defer mu.Unlock()
	u := getOrCreateUser(userID)
	u.Tier = tier
	u.StripeCustomerID = stripeCustomerID
	u.SubscriptionType = subscriptionType
	return save()
}

// UserInfo returns tier and today's usage for the API response.
type UserInfo struct {
	Tier       string `json:"tier"`
	UsageToday int    `json:"usage_today"`
	DailyLimit int    `json:"daily_limit"` // -1 = unlimited
}

func GetUserInfo(userID string) UserInfo {
	mu.RLock()
	defer mu.RUnlock()
	u := getOrCreateUser(userID)
	limit := 1
	if u.Tier == "paid" {
		limit = -1
	}
	return UserInfo{
		Tier:       u.Tier,
		UsageToday: u.DailyUsage[todayStr()],
		DailyLimit: limit,
	}
}
