package machinelearning

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
	"github.com/google/uuid"
)

type Store struct {
	*search.Store
}

// Database connection to the Machine Learning Data
// Keep only the

func Open(dsn string) (*Store, error) {
	if dsn == "" {
		dsn = os.Getenv("PG_DSN")
	}

	log.Println("[DB] Opening DB with DSN:", dsn)

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	log.Println("[DB] DB opened, pinging...")

	err = withTimeout(func(ctx context.Context) error {
		return db.PingContext(ctx)
	}, 5*time.Second)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("db ping: %w", err)
	}

	log.Println("[DB] Ping OK")

	if _, err := db.Exec("SET search_path TO musicbrainz;"); err != nil {
		log.Printf("[DB] FAILED to set search_path: %v", err)
	} else {
		log.Println("[DB] search_path set to musicbrainz")
	}

	var cnt int
	err = db.QueryRow(`SELECT count(*) FROM artist_collab`).Scan(&cnt)
	if err != nil {
		log.Printf("[DB] artist_collab count FAILED: %v", err)
	} else {
		log.Printf("[DB] artist_collab rows detected: %d", cnt)
	}

	log.Println("[DB] Open() complete")

	// IMPORTANT FIX: Construct a search.Store FIRST
	searchStore := &search.Store{
		DB: db,
	}

	// Wrap it in an ML Store
	return &Store{
		Store: searchStore,
	}, nil
}

func (s *Store) Close() error {
	if s == nil || s.DB == nil {
		return nil
	}
	return s.DB.Close()
}

//
// ========================================================================
// Utility: context timeout
// ========================================================================
//

func withTimeout(fn func(ctx context.Context) error, d time.Duration) error {
	ctx, cancel := context.WithTimeout(context.Background(), d)
	defer cancel()
	return fn(ctx)
}

//
// ========================================================================
// Models
// ========================================================================
//

// TrackInfo used in path steps
type TrackInfo search.TrackInfo

// API JSON Format Output

type Step search.Step

// SearchResponse returned by background BFS and HTTP layer
type SearchResponse search.SearchResponse

//
// ========================================================================
// Return the Paths
// ========================================================================
//

//
// ========================================================================
// Upsert to the paths and path_steps databases
// ========================================================================
//

// Uploading into the path and path_step database the results of the Search Response
func (s *Store) InsertSearchResponse(ctx context.Context, resp SearchResponse) (int, error) {
	tx, err := s.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	// Insert into paths
	var pathID int

	startIdUUID, err := uuid.Parse(resp.StartID)
	if err != nil {
		fmt.Println("StartID must be valid UUID", resp.StartID)
		return 0, err
	}
	targetIdUUID, err := uuid.Parse(resp.TargetID)
	if err != nil {
		fmt.Println("TargetID must be valid UUID", resp.TargetID)
		return 0, err
	}

	err = tx.QueryRowContext(ctx, `
        INSERT INTO paths (start_artist_id, end_artist_id, num_hops)
        VALUES ($1, $2, $3)
        RETURNING id;
    `,
		startIdUUID,  // MUST be artist_id UUID
		targetIdUUID, // MUST be artist_id UUID
		resp.Hops,
	).Scan(&pathID)
	if err != nil {
		return 0, fmt.Errorf("insert path: %w", err)
	}

	// Prepare insert for path_steps
	stepStmt, err := tx.PrepareContext(ctx, `
        INSERT INTO path_steps (path_id, step_index, recording_id, artist_id, from_artist_id)
        VALUES ($1, $2, $3, $4, $5)
    `)
	if err != nil {
		return 0, err
	}
	defer stepStmt.Close()

	// For each step (hop) in resp.Path
	for stepIndex, step := range resp.Path {
		toArtistID, err := uuid.Parse(step.ToID)
		if err != nil {
			fmt.Println("ToID must be valid UUID", step.ToID)
			return 0, err
		}

		fromArtistID, err := uuid.Parse(step.FromID)
		if err != nil {
			fmt.Println("FromID must be valid UUID", step.FromID)
			return 0, err
		}

		fmt.Println("THIS IS A DEBUGGING CHECK:\n	==== toArtistID in UpsertSearchResponse Line 99:", toArtistID, " <- Should be an ID not a name")

		// Insert one row per track used in this hop
		for _, track := range step.Tracks {
			_, err := stepStmt.ExecContext(ctx,
				pathID,
				stepIndex,
				track.RecordingID, // recording_id
				toArtistID,        // artist_id
				fromArtistID,      // artist_id
			)
			if err != nil {
				return 0, fmt.Errorf("insert step %d: %w", stepIndex, err)
			}
		}
	}

	// Commit
	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit: %w", err)
	}

	return pathID, nil
}

// ========================================================================
// Retrieve Links for API (Quick Lookup of Paths)
// ========================================================================

// Returns the JSON of the Links for the path ID that we are searching up
func (s *Store) LookupSearchResponse(ctx context.Context, pathID int) (*SearchResponse, error) {

	// ============================================================
	// 1. Fetch path header info
	// ============================================================

	var resp SearchResponse
	err := s.DB.QueryRowContext(ctx, `
        SELECT start_artist_id, end_artist_id, num_hops
        FROM paths
        WHERE id = $1
    `, pathID).Scan(&resp.Start, &resp.Target, &resp.Hops)
	if err != nil {
		return nil, fmt.Errorf("lookup path header: %w", err)
	}

	// Initialize the slice with the correct number of hops
	resp.Path = make([]search.Step, resp.Hops)

	// Fill From values if desired (optional)
	// You currently store only "To" per hop.
	// Set From = previous To or Start.
	if resp.Hops > 0 {
		resp.Path[0].From = resp.Start
	}

	// ============================================================
	// 2. Fetch path steps (each row = one track for that hop)
	// ============================================================

	rows, err := s.DB.QueryContext(ctx, `
        SELECT step_index, artist_id, recording_id
        FROM path_steps
        WHERE path_id = $1
        ORDER BY step_index
    `, pathID)
	if err != nil {
		return nil, fmt.Errorf("lookup steps: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var (
			stepIndex   int
			toArtistID  string
			recordingID string
		)

		if err := rows.Scan(&stepIndex, &toArtistID, &recordingID); err != nil {
			return nil, fmt.Errorf("scan step row: %w", err)
		}

		// Ensure step exists
		if stepIndex >= len(resp.Path) {
			return nil, fmt.Errorf("invalid step_index %d > hops %d", stepIndex, resp.Hops)
		}

		// Update Step struct
		step := &resp.Path[stepIndex]
		step.To = toArtistID

		// Append track info
		step.Tracks = append(step.Tracks, search.TrackInfo{
			ID:          recordingID,
			RecordingID: recordingID,
		})
	}

	// Fill missing From values
	for i := 1; i < len(resp.Path); i++ {
		resp.Path[i].From = resp.Path[i-1].To
	}

	// If desired, you can pull names/photos here via JOINs or a second lookup

	resp.Status = 200
	resp.Message = "ok"

	return &resp, nil
}

// Returns a pathID for if the path already exists
func (s *Store) PathExistsAlready(ctx context.Context, startArtistID, endArtistID string) (int, error) {
	var pathID int

	err := s.DB.QueryRowContext(ctx, `
        SELECT id
        FROM paths
        WHERE start_artist_id = $1 AND end_artist_id = $2
        LIMIT 1;
    `, startArtistID, endArtistID).Scan(&pathID)

	if err == sql.ErrNoRows {
		return 0, nil // path does NOT exist
	}
	if err != nil {
		return 0, err
	}

	return pathID, nil // path exists
}

//
// ========================================================================
// Miigrate: How the database is created
// ========================================================================
//

func (s *Store) Migrate(ctx context.Context) error {

	tx, err := s.DB.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// ============================================
	// 1. Create paths table
	// ============================================
	_, err = tx.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS paths (
			id SERIAL PRIMARY KEY,
			start_artist_id UUID NOT NULL,
			end_artist_id   UUID NOT NULL,
			num_hops        INT NOT NULL,
			created_at      TIMESTAMP DEFAULT now()
		);
	`)
	if err != nil {
		return fmt.Errorf("create paths: %w", err)
	}

	_, err = tx.ExecContext(ctx, `
		CREATE INDEX IF NOT EXISTS idx_paths_start_end
		ON paths(start_artist_id, end_artist_id);
	`)
	if err != nil {
		return fmt.Errorf("index paths: %w", err)
	}

	// ============================================
	// 2. Create path_steps table
	// ============================================
	_, err = tx.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS path_steps (
			id SERIAL PRIMARY KEY,
			path_id INT NOT NULL REFERENCES paths(id) ON DELETE CASCADE,
			step_index INT NOT NULL,
			from_artist_id UUID,
			artist_id UUID NOT NULL,
			recording_id UUID
		);
	`)
	if err != nil {
		return fmt.Errorf("create path_steps: %w", err)
	}

	_, err = tx.ExecContext(ctx, `
		CREATE INDEX IF NOT EXISTS idx_path_steps_lookup
		ON path_steps(path_id, step_index);
	`)
	if err != nil {
		return fmt.Errorf("index path_steps: %w", err)
	}

	// ============================================
	// Commit migration
	// ============================================
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit migrate: %w", err)
	}

	return nil
}

// ============================================
// Returning random artists from the main database
// ============================================

func (s *Store) GetRandomArtistIDs(ctx context.Context, n int) ([]string, []string, error) {
	rows, err := s.DB.QueryContext(ctx, `
        SELECT id,name 
        FROM artist
        ORDER BY random()
        LIMIT $1
    `, n)
	if err != nil {
		return nil, nil, fmt.Errorf("query random artists: %w", err)
	}
	defer rows.Close()

	var ids []string
	var names []string
	for rows.Next() {
		var id string
		var name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, nil, fmt.Errorf("scan artist id: %w", err)
		}
		ids = append(ids, id)
		names = append(names, name)
	}

	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("row iteration: %w", err)
	}

	return ids, names, nil
}
