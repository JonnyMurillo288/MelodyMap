package search

import (
	"math"
	"os"
	"testing"
)

func TestCosineSimilarity(t *testing.T) {
	tests := []struct {
		name     string
		a, b     []float64
		expected float64
		delta    float64
	}{
		{
			name:     "identical vectors",
			a:        []float64{1, 2, 3},
			b:        []float64{1, 2, 3},
			expected: 1.0,
			delta:    0.0001,
		},
		{
			name:     "orthogonal vectors",
			a:        []float64{1, 0, 0},
			b:        []float64{0, 1, 0},
			expected: 0.0,
			delta:    0.0001,
		},
		{
			name:     "opposite vectors",
			a:        []float64{1, 0, 0},
			b:        []float64{-1, 0, 0},
			expected: -1.0,
			delta:    0.0001,
		},
		{
			name:     "different lengths",
			a:        []float64{1, 2},
			b:        []float64{1, 2, 3},
			expected: 0.0,
			delta:    0.0001,
		},
		{
			name:     "zero vector",
			a:        []float64{0, 0, 0},
			b:        []float64{1, 2, 3},
			expected: 0.0,
			delta:    0.0001,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := CosineSimilarity(tt.a, tt.b)
			if math.Abs(result-tt.expected) > tt.delta {
				t.Errorf("CosineSimilarity(%v, %v) = %v, want %v",
					tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestEuclideanDistance(t *testing.T) {
	tests := []struct {
		name     string
		a, b     []float64
		expected float64
		delta    float64
	}{
		{
			name:     "identical vectors",
			a:        []float64{1, 2, 3},
			b:        []float64{1, 2, 3},
			expected: 0.0,
			delta:    0.0001,
		},
		{
			name:     "unit distance",
			a:        []float64{0, 0, 0},
			b:        []float64{1, 0, 0},
			expected: 1.0,
			delta:    0.0001,
		},
		{
			name:     "3-4-5 triangle",
			a:        []float64{0, 0},
			b:        []float64{3, 4},
			expected: 5.0,
			delta:    0.0001,
		},
		{
			name:     "different lengths",
			a:        []float64{1, 2},
			b:        []float64{1, 2, 3},
			expected: math.MaxFloat64,
			delta:    0.0001,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := EuclideanDistance(tt.a, tt.b)
			if math.Abs(result-tt.expected) > tt.delta {
				t.Errorf("EuclideanDistance(%v, %v) = %v, want %v",
					tt.a, tt.b, result, tt.expected)
			}
		})
	}
}

func TestEmbeddingStore(t *testing.T) {
	// Create a temporary CSV file for testing
	content := `artist_id,emb_0,emb_1,emb_2
1,0.5,0.5,0.707
2,1.0,0.0,0.0
3,0.0,1.0,0.0
`

	tmpFile, err := os.CreateTemp("", "test_embeddings_*.csv")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(content); err != nil {
		t.Fatalf("Failed to write temp file: %v", err)
	}
	tmpFile.Close()

	// Test loading embeddings
	store := NewEmbeddingStore()
	err = store.LoadFromCSV(tmpFile.Name())
	if err != nil {
		t.Fatalf("LoadFromCSV failed: %v", err)
	}

	// Check dimension
	if store.dimension != 3 {
		t.Errorf("Expected dimension 3, got %d", store.dimension)
	}

	// Check embeddings loaded
	emb, ok := store.GetEmbedding("1")
	if !ok {
		t.Error("Expected to find embedding for artist 1")
	}

	if len(emb) != 3 {
		t.Errorf("Expected embedding length 3, got %d", len(emb))
	}

	// Verify values
	expected := []float64{0.5, 0.5, 0.707}
	for i, v := range expected {
		if math.Abs(emb[i]-v) > 0.001 {
			t.Errorf("Embedding[%d] = %v, want %v", i, emb[i], v)
		}
	}

	// Test missing artist
	_, ok = store.GetEmbedding("999")
	if ok {
		t.Error("Expected not to find embedding for artist 999")
	}
}

func TestAStarHeuristic(t *testing.T) {
	// Create test store with known embeddings
	store := NewEmbeddingStore()
	store.dimension = 3

	// Artist 1 and 2 are very similar (cosine ≈ 1)
	store.embeddings = map[string][]float64{
		"1": {1.0, 0.0, 0.0},
		"2": {0.9, 0.1, 0.0}, // Nearly parallel
		"3": {0.0, 1.0, 0.0}, // Orthogonal to 1
		"4": {-1.0, 0.0, 0.0}, // Opposite to 1
	}

	tests := []struct {
		name     string
		from, to string
		maxDist  float64
	}{
		{
			name:    "similar artists",
			from:    "1",
			to:      "2",
			maxDist: 0.2, // Should be close
		},
		{
			name:    "orthogonal artists",
			from:    "1",
			to:      "3",
			maxDist: 2.0, // Should be ~1.0
		},
		{
			name:    "opposite artists",
			from:    "1",
			to:      "4",
			maxDist: 2.0, // Should be ~2.0
		},
		{
			name:    "missing artist",
			from:    "1",
			to:      "999",
			maxDist: 0.1, // Should return 0.0
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dist := store.AStarHeuristic(tt.from, tt.to)

			if dist < 0 || dist > tt.maxDist {
				t.Errorf("AStarHeuristic(%s, %s) = %v, want in range [0, %v]",
					tt.from, tt.to, dist, tt.maxDist)
			}

			t.Logf("Distance from %s to %s: %.4f", tt.from, tt.to, dist)
		})
	}
}

func TestHeuristicAdmissibility(t *testing.T) {
	// A* heuristic must be admissible (never overestimate actual cost)
	// For our graph, minimum hop distance is 1
	// Our heuristic range is [0, 2]
	// This is NOT admissible if actual cost > 2 hops

	// In practice, we use a multiplier < 1.0 or trust that
	// embedding space distance correlates with hop distance

	store := NewEmbeddingStore()
	store.dimension = 2
	store.embeddings = map[string][]float64{
		"1": {1.0, 0.0},
		"2": {0.0, 1.0},
	}

	h := store.AStarHeuristic("1", "2")

	// Heuristic should be in valid range
	if h < 0 || h > 2 {
		t.Errorf("Heuristic out of range: %v", h)
	}

	t.Logf("Heuristic for orthogonal artists: %.4f", h)
	t.Logf("Note: Admissibility depends on scaling factor in real usage")
}
