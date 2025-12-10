package machinelearning

import (
	"bufio"
	"context"
	"encoding/csv"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/Jonnymurillo288/MelodyMap/internal/secret"
	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
	"github.com/joho/godotenv"
)

func init() {
	if err := godotenv.Load(".env"); err != nil {
		log.Println("No .env file found, falling back to system env")
	}
}

func ReadLines(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}

	return lines, scanner.Err()
}

type searchRequest struct {
	Start    string `json:"start"`
	Target   string `json:"target"`
	StartID  string `json:"startID"`
	TargetID string `json:"targetID"`
	Depth    int    `json:"depth"`
}

func RunBatch() {
	// ==============================================
	// Load secrets/env
	// ==============================================
	if err := secret.LoadSecrets(""); err != nil {
		log.Fatal(err)
	}

	// ==============================================
	// Open ML database connection
	// ==============================================
	mbStore, err := search.Open(os.Getenv("PG_DSN"))
	if err != nil {
		log.Fatal("Music Brainz mbDB open failed:", err)
	}

	mlStore, err := Open(os.Getenv("PG_DSN"))
	if err != nil {
		log.Fatal("Machine Learning mlDB open failed:", err)
	}

	// Run migrations
	if err := mlStore.Migrate(context.Background()); err != nil {
		log.Fatal("Migration failed:", err)
	}

	// ==============================================
	// 1. Get N random artists
	// ==============================================
	const N = 10

	// ids, artists, err := s.GetRandomArtistIDs(context.Background(), N)
	artists, err := ReadLines("/home/jonnym/Desktop/MelodyMap/static/top_artists.txt")
	if err != nil {
		log.Fatal("failed to get random artists:", err)
	}

	// ==============================================
	// 2. Generate all combinations N × N except same
	// ==============================================
	var reqs []searchRequest
	var named_reqs []searchRequest

	// 1. Normalize & resolve all artists once
	resolved := make(map[string]*sixdegrees.Artists)

	for i, raw := range artists {
		clean := strings.TrimSpace(raw)

		if clean == "" {
			continue
		}

		if _, ok := resolved[clean]; ok {
			continue // already resolved
		}

		art, err := search.ResolveArtistOnce(mbStore, clean)

		if err != nil {
			fmt.Println("Could not resolve:", clean, err)
			continue
		}

		resolved[clean] = art
		fmt.Println("Added to resolved:", len(resolved))
		if i > N {
			break
		}
	}

	// Must have enough resolved artists to proceed
	if len(resolved) == 0 {
		log.Fatal("No artists could be resolved!")
	}

	// 2. Generate combinations using resolved map
	for i := 0; i < N; i++ {
		startName := strings.TrimSpace(artists[i])
		startArt, ok := resolved[startName]
		if !ok {
			fmt.Println("Skipping unresolved start artist:", startName)
			continue
		}

		for j := 0; j < N; j++ {
			if i == j {
				continue
			}

			targetName := strings.TrimSpace(artists[j])
			targetArt, ok := resolved[targetName]
			if !ok {
				fmt.Println("Skipping unresolved target artist:", startName, "→", targetName)
				continue
			}

			// BFS uses IDs
			reqs = append(reqs, searchRequest{
				Start:  startArt.ID,
				Target: targetArt.ID,
				Depth:  -1,
			})

			// Logging uses names
			named_reqs = append(named_reqs, searchRequest{
				Start:    startArt.Name,
				Target:   targetArt.Name,
				StartID:  startArt.ID,
				TargetID: targetArt.ID,
				Depth:    -1,
			})
		}
	}
	fmt.Printf("Generated %d search requests\n", len(named_reqs)) // Should be (N — non resolved)!

	// ==============================================
	// 3. Open CSV log file
	// ==============================================
	logFile, err := os.Create("search_log.csv")
	if err != nil {
		log.Fatal("Failed to create CSV log file:", err)
	}
	defer logFile.Close()

	csvWriter := csv.NewWriter(logFile)
	defer csvWriter.Flush()

	// Write header
	csvWriter.Write([]string{"start", "target", "hops", "status", "seconds"})

	// ==============================================
	// 4. Run BFS for each request, time it, log it, insert result
	// ==============================================
	for idx, req := range named_reqs {
		fmt.Printf("[%d/%d] Searching %s → %s\n", idx+1, len(reqs), req.Start, req.Target)
		fmt.Println("IDs are:", req.StartID, req.TargetID)

		startTime := time.Now()

		// Run BFS
		response, err := main_run(req, mbStore)
		if response.Status >= 400 {
			fmt.Println("Message from response:", response.Message)
		}
		duration := time.Since(startTime).Seconds()

		if err != nil {
			fmt.Printf("Search failed (%.4f sec): %v\n", duration, err)

			csvWriter.Write([]string{
				req.Start,
				req.Target,
				"-1",
				"search_error",
				fmt.Sprintf("%.4f", duration),
			})
			csvWriter.Flush()
			continue
		}

		fmt.Printf("Completed in %.4f seconds with %d hops\n", duration, response.Hops)
		// b, _ := json.MarshalIndent(response, "", "  ")
		// fmt.Println("FULL RESPONSE:\n", string(b))

		// Insert into ML database
		_, err = mlStore.InsertSearchResponse(context.Background(), response)
		if err != nil {
			fmt.Println("Insert into ML DB failed:", err)

			csvWriter.Write([]string{
				named_reqs[idx].Start,
				named_reqs[idx].Target,
				fmt.Sprintf("%d", response.Hops),
				"insert_error",
				fmt.Sprintf("%.4f", duration),
			})
			csvWriter.Flush()
			continue
		}

		// Log success to CSV
		csvWriter.Write([]string{
			named_reqs[idx].Start,
			named_reqs[idx].Target,
			fmt.Sprintf("%d", response.Hops),
			fmt.Sprintf("%d", response.Status),
			fmt.Sprintf("%.4f", duration),
		})
		csvWriter.Flush()
	}

	fmt.Println("All searches completed.")
}
