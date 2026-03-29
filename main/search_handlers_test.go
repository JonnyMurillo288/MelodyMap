package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// callNeighbors fires a GET request at artistNeighborsHandler and returns the recorder.
func callNeighbors(t *testing.T, name string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/api/artist/neighbors?name="+name, nil)
	rec := httptest.NewRecorder()
	artistNeighborsHandler(rec, req)
	return rec
}

func skipIfNoDB(t *testing.T) {
	t.Helper()
	if os.Getenv("DB_PATH") == "" {
		t.Skip("DB_PATH not set, skipping")
	}
}

func TestArtistNeighborsHandler_ReturnsValidJSON(t *testing.T) {
	skipIfNoDB(t)

	rec := callNeighbors(t, "Drake")
	require.Equal(t, http.StatusOK, rec.Code)
	fmt.Println(rec.Header().Get("Content-Type"))
	assert.Equal(t, "application/json", rec.Header().Get("Content-Type"))

	var steps search.FrontendStep
	err := json.NewDecoder(rec.Body).Decode(&steps)
	require.NoError(t, err, "body should be valid JSON")

	t.Logf("got step: ID=%s  Name=%s  Neighbors=%d",
		steps.ID, steps.Name, len(steps.Neighbors))
}

func TestArtistNeighborsHandler_HasNeighbors(t *testing.T) {
	skipIfNoDB(t)

	rec := callNeighbors(t, "Drake")
	require.Equal(t, http.StatusOK, rec.Code)

	var steps search.FrontendStep
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&steps))

	require.NotNil(t, steps.Neighbors, "Neighbors should not be nil")
	assert.Greater(t, len(steps.Neighbors), 0, "Drake should have at least one neighbor")

	for _, n := range steps.Neighbors {
		t.Logf("  neighbor: ID=%s  Name=%s  Tracks=%d", n.ID, n.Name, len(n.Tracks))
		assert.NotEmpty(t, n.ID, "neighbor ID should not be empty")
		assert.NotEmpty(t, n.Name, "neighbor Name should not be empty")
	}
}

func TestArtistNeighborsHandler_TracksHavePhotoURL(t *testing.T) {
	skipIfNoDB(t)

	rec := callNeighbors(t, "Drake")
	require.Equal(t, http.StatusOK, rec.Code)

	var steps search.FrontendStep
	require.NoError(t, json.NewDecoder(rec.Body).Decode(&steps))
	require.NotNil(t, steps.Neighbors)

	for _, n := range steps.Neighbors {
		for _, tr := range n.Tracks {
			assert.Contains(t, tr.PhotoURL, "https://coverartarchive.org/release/",
				"PhotoURL should point to Cover Art Archive")
		}
	}
}

func TestArtistNeighborsHandler_CaseInsensitive(t *testing.T) {
	skipIfNoDB(t)

	rec1 := callNeighbors(t, "drake")
	rec2 := callNeighbors(t, "DRAKE")

	var steps1, steps2 search.FrontendStep
	require.NoError(t, json.NewDecoder(rec1.Body).Decode(&steps1))
	require.NoError(t, json.NewDecoder(rec2.Body).Decode(&steps2))

	assert.Equal(t, steps1.ID, steps2.ID, "lowercase and uppercase should return the same artist")
}

func TestArtistNeighborsHandler_UnknownArtist(t *testing.T) {
	skipIfNoDB(t)

	rec := callNeighbors(t, "zzz_no_such_artist_zzz")
	assert.Equal(t, http.StatusOK, rec.Code, "unknown artist should not 500")

	var steps search.FrontendStep
	err := json.NewDecoder(rec.Body).Decode(&steps)
	require.NoError(t, err, "response should still be valid JSON")

	if len(steps.Neighbors) > 0 {
		assert.Empty(t, steps.Neighbors)
	}
}
