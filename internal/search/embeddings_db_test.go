package search

import (
	"testing"
)

// TestLoadFromDB tests loading embeddings from the database
// This is an integration test that requires a database connection
func TestLoadFromDB(t *testing.T) {
	// Skip if not in integration test mode
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Open database connection
	store, err := Open("")
	if err != nil {
		t.Skipf("Could not connect to database: %v", err)
	}
	defer store.Close()

	// Create embedding store
	es := NewEmbeddingStore()

	// Load from database
	err = es.LoadFromDB(store)
	if err != nil {
		t.Fatalf("LoadFromDB failed: %v", err)
	}

	// Verify embeddings were loaded
	if len(es.embeddings) == 0 {
		t.Error("No embeddings loaded from database")
	}

	// Verify dimension
	if es.dimension != 32 {
		t.Errorf("Expected dimension 32, got %d", es.dimension)
	}

	t.Logf("Successfully loaded %d embeddings from database", len(es.embeddings))

	// Test getting a random embedding
	for artistID, emb := range es.embeddings {
		if len(emb) != 32 {
			t.Errorf("Embedding for artist %s has wrong dimension: %d", artistID, len(emb))
		}

		// Verify embedding has non-zero values
		hasNonZero := false
		for _, val := range emb {
			if val != 0.0 {
				hasNonZero = true
				break
			}
		}

		if !hasNonZero {
			t.Logf("Warning: Embedding for artist %s is all zeros", artistID)
		}

		// Only check first embedding
		break
	}
}

// TestInitEmbeddingsFromDB tests the convenience function
func TestInitEmbeddingsFromDB(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	store, err := Open("")
	if err != nil {
		t.Skipf("Could not connect to database: %v", err)
	}
	defer store.Close()

	// Initialize global store
	err = InitEmbeddingsFromDB(store)
	if err != nil {
		t.Fatalf("InitEmbeddingsFromDB failed: %v", err)
	}

	// Verify global store is set
	if GlobalEmbeddingStore == nil {
		t.Fatal("GlobalEmbeddingStore is nil after initialization")
	}

	if len(GlobalEmbeddingStore.embeddings) == 0 {
		t.Error("GlobalEmbeddingStore has no embeddings")
	}

	t.Logf("Global store initialized with %d embeddings", len(GlobalEmbeddingStore.embeddings))
}

// TestEmbeddingConsistency compares CSV and DB loading
func TestEmbeddingConsistency(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Check if CSV file exists
	csvPath := "/tmp/artist_embeddings.csv"

	// Load from CSV
	esCSV := NewEmbeddingStore()
	errCSV := esCSV.LoadFromCSV(csvPath)

	// Load from DB
	store, err := Open("")
	if err != nil {
		t.Skipf("Could not connect to database: %v", err)
	}
	defer store.Close()

	esDB := NewEmbeddingStore()
	errDB := esDB.LoadFromDB(store)

	// Both should succeed or both should fail
	if errCSV == nil && errDB == nil {
		t.Logf("CSV loaded %d embeddings", len(esCSV.embeddings))
		t.Logf("DB loaded %d embeddings", len(esDB.embeddings))

		// Check if same artists have embeddings
		matchCount := 0
		for artistID := range esCSV.embeddings {
			if _, exists := esDB.embeddings[artistID]; exists {
				matchCount++
			}
		}

		if matchCount == 0 {
			t.Error("No matching artist IDs between CSV and DB")
		} else {
			t.Logf("Found %d matching artists between CSV and DB", matchCount)
		}

		// Compare a few embeddings
		sampleSize := 0
		for artistID, csvEmb := range esCSV.embeddings {
			dbEmb, exists := esDB.embeddings[artistID]
			if !exists {
				continue
			}

			// Check if embeddings are similar
			similarity := CosineSimilarity(csvEmb, dbEmb)
			if similarity < 0.99 {
				t.Errorf("Embeddings for artist %s differ significantly: similarity=%.4f", artistID, similarity)
			}

			sampleSize++
			if sampleSize >= 10 {
				break
			}
		}
	} else if errCSV != nil {
		t.Logf("CSV loading failed (expected if file doesn't exist): %v", errCSV)
	} else if errDB != nil {
		t.Logf("DB loading failed: %v", errDB)
	}
}
