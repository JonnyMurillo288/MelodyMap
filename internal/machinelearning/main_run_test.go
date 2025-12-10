package machinelearning_test

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"

	"github.com/Jonnymurillo288/MelodyMap/internal/machinelearning"
	"github.com/Jonnymurillo288/MelodyMap/internal/search"
)

// =======================================================
// VALIDATOR — mirrors DB schema (UUID enforcement)
// =======================================================
func validateSearchResponseForDB(t *testing.T, resp search.SearchResponse) {
	t.Helper()
	// b, _ := json.MarshalIndent(resp, "", "  ")
	// fmt.Println("FULL RESPONSE:\n", string(b))

	// ---- Validate required top-level UUIDs ----
	require.NotEmpty(t, resp.StartID, "StartID must not be empty")
	require.NotEmpty(t, resp.TargetID, "TargetID must not be empty")

	_, err := uuid.Parse(resp.StartID)
	require.NoError(t, err, "StartID must be valid UUID")

	_, err = uuid.Parse(resp.TargetID)
	require.NoError(t, err, "TargetID must be valid UUID")

	// ---- Validate path steps ----
	for i, step := range resp.Path {
		require.NotEmpty(t, step.ToID, "Path[%d].ToID must not be empty", i)
		_, err := uuid.Parse(step.ToID)
		require.NoError(t, err, "Path[%d].ToID must be UUID", i)

		// FromID is nullable but must be valid UUID if present
		if step.FromID != "" {
			_, err := uuid.Parse(step.FromID)
			require.NoError(t, err, "Path[%d].FromID must be UUID", i)
		}

		// Tracks → recording UUIDs
		for j, tr := range step.Tracks {
			require.NotEmpty(t, tr.RecordingID, "Path[%d].Tracks[%d].RecordingID empty", i, j)

			_, err := uuid.Parse(tr.RecordingID)
			require.NoError(t, err, "Path[%d].Tracks[%d].RecordingID must be UUID", i, j)
		}
	}
}

// ----------------------------------------------------
// TEST: Run the REAL SearchArtists function
// ----------------------------------------------------
func TestSearchArtists_RealOutput(t *testing.T) {

	s, err := machinelearning.Open("postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable")
	require.NoError(t, err, "Error opening DB")
	defer s.Close()

	startName, endName := "Eminem", "Taylor Swift"
	startID, _ := search.ResolveArtistOnce(s.Store, startName)
	endID, _ := search.ResolveArtistOnce(s.Store, endName)

	req := search.SearchRequest{
		Start:    startName,
		Target:   endName,
		StartID:  startID.ID,
		TargetID: endID.ID,
		Depth:    6,
	}

	// Call your actual BFS system.
	hops, steps, _, status, err := search.SearchArtists(
		s.Store,
		req.Start,
		req.Target,
		req.Depth,
		3000,
		false,
	)

	require.NoError(t, err, "SearchArtists returned an unexpected error")
	require.Equal(t, 200, status, "status should be 200 OK")
	require.GreaterOrEqual(t, hops, 0, "hops should be ≥ 0")

	// Build the full response with IDs
	resp := search.SearchResponse{
		Start:    req.Start,
		Target:   req.Target,
		StartID:  req.StartID,
		TargetID: req.TargetID,
		Hops:     hops,
		Path:     steps,
		Status:   status,
	}

	// ------------------------------------------------
	// Print the full response
	// ------------------------------------------------
	// b, _ := json.MarshalIndent(resp, "", "  ")
	// fmt.Println("FULL RESPONSE:\n", string(b))

	if hops == 0 || len(steps) == 0 {
		t.Log("Search returned no path; dataset might not contain a connection")
		return
	}

	require.Equal(t, hops, len(steps), "hops must equal number of path steps")

	// ------------------------------------------------
	// Validate path structure basic checks
	// ------------------------------------------------
	for i, step := range steps {
		t.Logf("Step %d: From=%s To=%s Tracks=%d", i, step.FromID, step.ToID, len(step.Tracks))
		require.NotEmpty(t, step.ToID, "Step[%d].ToID must not be empty", i)
	}

	// ------------------------------------------------
	// **NEW: Validate types match DB schema**
	// ------------------------------------------------
	validateSearchResponseForDB(t, resp)

	// ------------------------------------------------
	// **OPTIONAL: try insert into DB to confirm schema alignment**
	// ------------------------------------------------
	// ctx := context.Background()
	// pathID, err := s.InsertSearchResponse(ctx, resp)
	// require.NoError(t, err, "InsertSearchResponse failed")
	// t.Logf("Inserted path_id = %d", pathID)
}
