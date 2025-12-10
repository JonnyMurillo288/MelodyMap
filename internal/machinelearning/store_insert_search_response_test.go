package machinelearning_test

// import (
// 	"context"
// 	"testing"

// 	machinelearning "github.com/Jonnymurillo288/MelodyMap/internal/machine_learning"
// 	"github.com/Jonnymurillo288/MelodyMap/internal/search"
// 	"github.com/stretchr/testify/require"
// 	"github.com/testcontainers/testcontainers-go"
// 	"github.com/testcontainers/testcontainers-go/modules/postgres"
// 	"github.com/testcontainers/testcontainers-go/wait"
// )

// // ----------------------------------------------------
// // SETUP: Spin up real Postgres via Testcontainers
// // ----------------------------------------------------
// func setupTestDB(t *testing.T) (*machinelearning.Store, func()) {
// 	ctx := context.Background()

// 	pgContainer, err := postgres.Run(ctx,
// 		testcontainers.WithImage("postgres:16"),
// 		postgres.WithDatabase("testdb"),
// 		postgres.WithUsername("testuser"),
// 		postgres.WithPassword("testpass"),
// 		postgres.WithWaitStrategy(wait.ForLog("database system is ready")),
// 	)
// 	require.NoError(t, err)

// 	connStr, err := pgContainer.ConnectionString(ctx, "sslmode=disable")
// 	require.NoError(t, err)

// 	s, err := machinelearning.Open(connStr)
// 	require.NoError(t, err)

// 	require.NoError(t, s.Migrate(ctx))

// 	cleanup := func() { pgContainer.Terminate(ctx) }
// 	return s, cleanup
// }

// // ----------------------------------------------------
// // TEST: InsertSearchResponse with STRING IDs
// // ----------------------------------------------------
// func TestInsertSearchResponse(t *testing.T) {
// 	ctx := context.Background()
// 	s, cleanup := setupTestDB(t)
// 	defer cleanup()

// 	// Fake *string* IDs (not UUID types)
// 	startArtist := "artist-start-123"
// 	endArtist := "artist-end-456"
// 	fromArtist := "artist-from-789"
// 	toArtist := "artist-to-101112"
// 	recordingID := "recording-xyz-999"

// 	resp := machinelearning.SearchResponse{
// 		StartID:  startArtist,
// 		TargetID: endArtist,
// 		Hops:     1,
// 		Path: []search.Step{
// 			{
// 				FromID: fromArtist,
// 				ToID:   toArtist,
// 				Tracks: []search.TrackInfo{
// 					{
// 						RecordingID: recordingID,
// 					},
// 				},
// 			},
// 		},
// 	}

// 	// ---- Insert into DB ----
// 	pathID, err := s.InsertSearchResponse(ctx, resp)
// 	require.NoError(t, err)
// 	require.Greater(t, pathID, 0)

// 	// ------------------------------------------------
// 	// VERIFY paths row
// 	// ------------------------------------------------
// 	var count int
// 	err = s.DB.QueryRow(`SELECT COUNT(*) FROM paths WHERE id = $1`, pathID).Scan(&count)
// 	require.NoError(t, err)
// 	require.Equal(t, 1, count)

// 	// ------------------------------------------------
// 	// VERIFY path_steps row
// 	// ------------------------------------------------
// 	err = s.DB.QueryRow(`
// 		SELECT COUNT(*)
// 		FROM path_steps
// 		WHERE path_id = $1
// 		  AND artist_id = $2
// 		  AND from_artist_id = $3
// 		  AND recording_id = $4`,
// 		pathID,
// 		toArtist,
// 		fromArtist,
// 		recordingID,
// 	).Scan(&count)

// 	require.NoError(t, err)
// 	require.Equal(t, 1, count)
// }
