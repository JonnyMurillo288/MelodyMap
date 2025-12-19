package main

import (
	"fmt"
	"log"

	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
)

func main() {
	fmt.Println("=== A* Search with Node2Vec Embeddings ===\n")

	// Step 1: Initialize embeddings
	embeddingPath := "/tmp/artist_embeddings.csv"
	fmt.Printf("Loading embeddings from %s...\n", embeddingPath)

	err := search.InitEmbeddings(embeddingPath)
	if err != nil {
		log.Fatalf("Failed to load embeddings: %v", err)
	}
	fmt.Println("✓ Embeddings loaded successfully\n")

	// Step 2: Open database connection
	fmt.Println("Opening database connection...")
	store, err := search.Open("")
	if err != nil {
		log.Fatalf("Failed to open database: %v", err)
	}
	defer store.Close()
	fmt.Println("✓ Database connected\n")

	// Step 3: Define start and target artists
	// Replace these with actual artist IDs from your database
	start := &sixdegrees.Artists{
		ID:   "1",  // Example: replace with real artist ID
		Name: "Artist A",
	}

	target := &sixdegrees.Artists{
		ID:   "1000",  // Example: replace with real artist ID
		Name: "Artist B",
	}

	fmt.Printf("Searching from: %s (ID: %s)\n", start.Name, start.ID)
	fmt.Printf("Searching to:   %s (ID: %s)\n\n", target.Name, target.ID)

	// Step 4: Run A* search
	maxDepth := 6
	verbose := true
	limit := 5000
	offline := false

	fmt.Println("Running A* search...")
	helper, pathNames, pathIDs, pathTracks, statusCode, found := search.RunSearchOptsAStar(
		store,
		start,
		target,
		maxDepth,
		verbose,
		&limit,
		offline,
	)

	// Step 5: Display results
	fmt.Println("\n=== Search Results ===")
	fmt.Printf("Status Code: %d\n", statusCode)
	fmt.Printf("Found: %v\n", found)

	if found && len(pathNames) > 0 {
		fmt.Printf("\nPath found with %d hops:\n", len(pathNames)-1)
		for i, name := range pathNames {
			fmt.Printf("%d. %s (ID: %s)\n", i+1, name, pathIDs[i])

			if i < len(pathTracks) {
				fmt.Printf("   → %d shared tracks\n", len(pathTracks[i]))
			}
		}
	} else {
		fmt.Println("\nNo path found")
	}

	// Step 6: Demonstrate embedding similarity
	if search.GlobalEmbeddingStore != nil {
		fmt.Println("\n=== Embedding Analysis ===")

		startEmb, ok1 := search.GlobalEmbeddingStore.GetEmbedding(start.ID)
		targetEmb, ok2 := search.GlobalEmbeddingStore.GetEmbedding(target.ID)

		if ok1 && ok2 {
			similarity := search.CosineSimilarity(startEmb, targetEmb)
			distance := search.EuclideanDistance(startEmb, targetEmb)

			fmt.Printf("Cosine Similarity: %.4f\n", similarity)
			fmt.Printf("Euclidean Distance: %.4f\n", distance)
			fmt.Printf("A* Heuristic: %.4f\n",
				search.GlobalEmbeddingStore.AStarHeuristic(start.ID, target.ID))
		} else {
			fmt.Println("Embeddings not found for one or both artists")
		}
	}

	if helper != nil {
		fmt.Printf("\nTotal artists explored: %d\n", len(helper.ArtistByID))
	}
}
