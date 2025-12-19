package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/joho/godotenv"
)

func main() {
	// Load .env file
	if err := godotenv.Load(); err != nil {
		log.Printf("Warning: .env file not found: %v", err)
	}

	// Open database
	store, err := search.Open("")
	if err != nil {
		log.Fatalf("Failed to open database: %v", err)
	}
	defer store.Close()

	ctx := context.Background()

	if len(os.Args) > 1 && os.Args[1] == "init" {
		// Initialize the metrics table
		fmt.Println("Creating search_metrics table...")
		if err := store.CreateSearchMetricsTable(ctx); err != nil {
			log.Fatalf("Failed to create metrics table: %v", err)
		}
		fmt.Println("✓ search_metrics table created successfully")
		return
	}

	if len(os.Args) > 1 && os.Args[1] == "compare" {
		// Compare BFS vs A* performance
		fmt.Println("=== Search Performance Comparison ===\n")

		comparison, err := store.CompareSearchPerformance(ctx)
		if err != nil {
			log.Fatalf("Failed to get comparison: %v", err)
		}

		// Pretty print JSON
		jsonData, _ := json.MarshalIndent(comparison, "", "  ")
		fmt.Println(string(jsonData))

		// Calculate speedup if both exist
		if bfsData, ok := comparison["BFS"].(map[string]interface{}); ok {
			if astarData, ok := comparison["ASTAR"].(map[string]interface{}); ok {
				bfsAvg := bfsData["avg_duration_ms"].(float64)
				astarAvg := astarData["avg_duration_ms"].(float64)
				speedup := bfsAvg / astarAvg

				fmt.Printf("\n=== Summary ===\n")
				fmt.Printf("BFS average:   %.2f ms\n", bfsAvg)
				fmt.Printf("A* average:    %.2f ms\n", astarAvg)
				fmt.Printf("Speedup:       %.2fx %s\n", speedup, getSpeedupIcon(speedup))
			}
		}

		return
	}

	if len(os.Args) > 1 && os.Args[1] == "list" {
		// List recent searches
		searchType := ""
		if len(os.Args) > 2 {
			searchType = os.Args[2] // "BFS" or "ASTAR"
		}

		fmt.Printf("=== Recent Searches (%s) ===\n\n", ifEmpty(searchType, "ALL"))

		metrics, err := store.GetSearchMetrics(ctx, searchType, 20)
		if err != nil {
			log.Fatalf("Failed to get metrics: %v", err)
		}

		if len(metrics) == 0 {
			fmt.Println("No metrics found")
			return
		}

		for _, m := range metrics {
			fmt.Printf("[%s] %s → %s\n", m.SearchType, m.StartArtist, m.EndArtist)
			fmt.Printf("  Hops: %d, Duration: %dms, Time: %s\n\n",
				m.NumHops, m.DurationMs, m.CreatedAt.Format("2006-01-02 15:04:05"))
		}

		return
	}

	// Default: show help
	fmt.Println("Search Metrics Tool")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  go run cmd/init-metrics/main.go init          - Create metrics table")
	fmt.Println("  go run cmd/init-metrics/main.go compare       - Compare BFS vs A*")
	fmt.Println("  go run cmd/init-metrics/main.go list [TYPE]   - List recent searches")
	fmt.Println()
	fmt.Println("Examples:")
	fmt.Println("  go run cmd/init-metrics/main.go list BFS")
	fmt.Println("  go run cmd/init-metrics/main.go list ASTAR")
}

func ifEmpty(s, defaultVal string) string {
	if s == "" {
		return defaultVal
	}
	return s
}

func getSpeedupIcon(speedup float64) string {
	if speedup > 2.0 {
		return "🚀 (A* much faster)"
	} else if speedup > 1.2 {
		return "✓ (A* faster)"
	} else if speedup > 0.8 {
		return "≈ (similar)"
	} else {
		return "⚠ (BFS faster)"
	}
}
