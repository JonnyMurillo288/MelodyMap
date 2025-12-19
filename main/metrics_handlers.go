package main

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
)

// HandleMetricsComparison returns BFS vs A* performance comparison
func HandleMetricsComparison(w http.ResponseWriter, r *http.Request) {
	store, err := search.Open("")
	if err != nil {
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	comparison, err := store.CompareSearchPerformance(ctx)
	if err != nil {
		http.Error(w, "Failed to get comparison", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"comparison": comparison,
	})
}

// HandleMetricsList returns recent search metrics
func HandleMetricsList(w http.ResponseWriter, r *http.Request) {
	searchType := r.URL.Query().Get("type") // "BFS" or "ASTAR" or ""

	store, err := search.Open("")
	if err != nil {
		http.Error(w, "Database error", http.StatusInternalServerError)
		return
	}
	defer store.Close()

	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	metrics, err := store.GetSearchMetrics(ctx, searchType, 50)
	if err != nil {
		http.Error(w, "Failed to get metrics", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"metrics": metrics,
		"count":   len(metrics),
	})
}
