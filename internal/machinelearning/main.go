package machinelearning

import (
	"bufio"
	"context"
	"encoding/csv"
	"fmt"
	"log"
	"math/rand"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/Jonnymurillo288/MelodyMap/internal/secret"
	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
	"github.com/joho/godotenv"
)

func init() {
	if err := godotenv.Load(".env.local"); err != nil {
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

type searchResult struct {
	request  searchRequest
	response SearchResponse
	duration float64
	err      error
}

func RunBatch(start int, N int, workerCount int) {
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

	artists, err := ReadLines("/home/jonnym/Desktop/MelodyMap/static/top_artists.txt")
	if err != nil {
		log.Fatal("failed to get random artists:", err)
	}

	// ==============================================
	// 2. Resolve artists concurrently
	// ==============================================
	resolved := resolveArtistsConcurrently(artists, mbStore, N, workerCount, start)

	// Must have enough resolved artists to proceed
	if len(resolved) == 0 {
		log.Fatal("No artists could be resolved!")
	}

	// ==============================================
	// 3. Generate all combinations N × N except same
	// ==============================================
	named_reqs := generateSearchRequests(artists, resolved, start, N)
	fmt.Printf("Generated %d search requests\n", len(named_reqs))

	// ==============================================
	// 3.5. Randomly shuffle the requests
	// ==============================================
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	rng.Shuffle(len(named_reqs), func(i, j int) {
		named_reqs[i], named_reqs[j] = named_reqs[j], named_reqs[i]
	})
	fmt.Println("Shuffled requests for random order processing")

	// ==============================================
	// 4. Open CSV log file
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
	// 5. Run BFS concurrently with worker pool
	// ==============================================
	processSearchesConcurrently(named_reqs, mbStore, mlStore, csvWriter, workerCount)

	fmt.Println("All searches completed.")
}

// resolveArtistsConcurrently resolves artist names to IDs using concurrent workers
func resolveArtistsConcurrently(artists []string, mbStore *search.Store, limit int, workers int, start int) map[string]*sixdegrees.Artists {
	resolved := make(map[string]*sixdegrees.Artists)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Channel for artist names to resolve
	artistChan := make(chan string, workers)

	// Start worker goroutines
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for clean := range artistChan {
				art, err := search.ResolveArtistOnce(mbStore, clean)
				if err != nil {
					fmt.Println("Could not resolve:", clean, err)
					continue
				}

				mu.Lock()
				resolved[clean] = art
				count := len(resolved)
				mu.Unlock()

				if count%10 == 0 {
					fmt.Printf("Resolved %d artists\n", count)
				}
			}
		}()
	}

	// Feed artists to workers
	seen := make(map[string]bool)
	for i := start; i < limit; i++ {
		clean := strings.TrimSpace(artists[i])
		if clean == "" || seen[clean] {
			continue
		}
		seen[clean] = true
		artistChan <- clean

		if i >= limit {
			break
		}
	}

	close(artistChan)
	wg.Wait()

	fmt.Printf("Total resolved: %d artists\n", len(resolved))
	return resolved
}

// generateSearchRequests creates all artist pair combinations
func generateSearchRequests(artists []string, resolved map[string]*sixdegrees.Artists, start int, N int) []searchRequest {
	var named_reqs []searchRequest

	for i := start; i < N && i < len(artists); i++ {
		startName := strings.TrimSpace(artists[i])
		startArt, ok := resolved[startName]
		if !ok {
			continue
		}

		for j := 0; j < N && j < len(artists); j++ {
			if i == j {
				continue
			}

			targetName := strings.TrimSpace(artists[j])
			targetArt, ok := resolved[targetName]
			if !ok {
				continue
			}

			named_reqs = append(named_reqs, searchRequest{
				Start:    startArt.Name,
				Target:   targetArt.Name,
				StartID:  startArt.ID,
				TargetID: targetArt.ID,
				Depth:    -1,
			})
		}
	}

	return named_reqs
}

// processSearchesConcurrently runs searches with a worker pool pattern
func processSearchesConcurrently(requests []searchRequest, mbStore *search.Store, mlStore *Store, csvWriter *csv.Writer, workers int) {
	var wg sync.WaitGroup
	var csvMu sync.Mutex

	// Channel for requests
	requestChan := make(chan struct {
		idx int
		req searchRequest
	}, workers)

	// Start worker goroutines
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()

			for item := range requestChan {
				idx := item.idx
				req := item.req

				fmt.Printf("[Worker %d] [%d/%d] Searching %s → %s\n",
					workerID, idx+1, len(requests), req.Start, req.Target)

				// Check if path already exists
				if pathid, err := mlStore.PathExistsAlready(context.Background(), req.StartID, req.TargetID); err == nil && pathid > 0 {
					fmt.Printf("[Worker %d] Already have path for %s → %s (path_id=%d)\n",
						workerID, req.Start, req.Target, pathid)
					continue
				}

				startTime := time.Now()
				response, err := main_run(req, mbStore)
				duration := time.Since(startTime).Seconds()

				// Handle errors
				if err != nil {
					fmt.Printf("[Worker %d] Search failed (%.4f sec): %v\n", workerID, duration, err)
					csvMu.Lock()
					csvWriter.Write([]string{req.Start, req.Target, "-1", "search_error", fmt.Sprintf("%.4f", duration)})
					csvWriter.Flush()
					csvMu.Unlock()
					continue
				}

				if response.Status >= 400 {
					fmt.Printf("[Worker %d] Error response: %s\n", workerID, response.Message)
				}

				fmt.Printf("[Worker %d] Completed in %.4f seconds with %d hops\n",
					workerID, duration, response.Hops)

				// Insert into database
				_, err = mlStore.InsertSearchResponse(context.Background(), response)
				if err != nil {
					fmt.Printf("[Worker %d] Insert failed: %v\n", workerID, err)
					csvMu.Lock()
					csvWriter.Write([]string{req.Start, req.Target, fmt.Sprintf("%d", response.Hops), "insert_error", fmt.Sprintf("%.4f", duration)})
					csvWriter.Flush()
					csvMu.Unlock()
					continue
				}

				// Log success
				csvMu.Lock()
				csvWriter.Write([]string{req.Start, req.Target, fmt.Sprintf("%d", response.Hops), fmt.Sprintf("%d", response.Status), fmt.Sprintf("%.4f", duration)})
				csvWriter.Flush()
				csvMu.Unlock()
			}
		}(i)
	}

	// Feed requests to workers
	for idx, req := range requests {
		requestChan <- struct {
			idx int
			req searchRequest
		}{idx, req}
	}

	close(requestChan)
	wg.Wait()
}
