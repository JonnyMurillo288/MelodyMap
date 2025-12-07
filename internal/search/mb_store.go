package search

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

//
// ========================================================================
// Store Wrapper
// ========================================================================
//

type Store struct {
	DB *sql.DB
}

func Open(dsn string) (*Store, error) {
	if dsn == "" {
		dsn = os.Getenv("PG_DSN")
		if dsn == "" {
			dsn = "postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"
		}
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	err = withTimeout(func(ctx context.Context) error {
		return db.PingContext(ctx)
	}, 5*time.Second)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("db ping: %w", err)
	}

	_, _ = db.Exec("SET search_path TO musicbrainz;")

	return &Store{DB: db}, nil
}

func (s *Store) Close() error {
	if s == nil || s.DB == nil {
		return nil
	}
	return s.DB.Close()
}

//
// ========================================================================
// Models
// ========================================================================
//

type PerformerCredit struct {
	ID   string
	Name string
}

type DBTrack struct {
	RecordingMBID string
	RecordingName string
	TrackMBID     string
	TrackName     string
	CoverURL      string
	Performers    []PerformerCredit
}

type MBRecordingSearchDB struct {
	Recordings []DBTrack
}

//
// ========================================================================
// Internal Artist Lookup
// ========================================================================
//

type ArtistInternal struct {
	ID   int
	MBID string
	Name string
}

func (s *Store) LookupArtistByMBID(mbid string) (*ArtistInternal, error) {
	q := `
        SELECT id, gid::text, name
        FROM artist
        WHERE gid = $1
        LIMIT 1;
    `
	var a ArtistInternal
	err := s.DB.QueryRow(q, mbid).Scan(&a.ID, &a.MBID, &a.Name)
	if err != nil {
		return nil, err
	}
	return &a, nil
}

//
// ========================================================================
// Performer-only collaboration filter
// ========================================================================
//

const performerFilter = `
    'performer',
    'vocal',
    'instrument',
    'featured',
    'guest performer'
`

//
// ========================================================================
// GetArtistTracksDB — REAL tracks where artist performed
// ========================================================================
//

func (s *Store) GetArtistTracksDB(
	ctx context.Context,
	mbid string,
	limit int,
) (MBRecordingSearchDB, error) {

	var result MBRecordingSearchDB

	q := `
		WITH main_artist AS (
			SELECT id FROM artist WHERE gid = $1
		)
		SELECT
			r.gid::text        AS recording_mbid,
			r.name             AS recording_name,
			t.gid::text        AS track_mbid,
			t.name             AS track_name,
			rl.gid::text       AS release_mbid
		FROM track t
		JOIN recording r        ON r.id = t.recording
		JOIN medium m           ON m.id = t.medium
		JOIN release rl         ON rl.id = m.release
		JOIN artist_credit ac   ON ac.id = t.artist_credit
		JOIN artist_credit_name acn ON acn.artist_credit = ac.id
		WHERE acn.position = 0   -- PRIMARY ARTIST ONLY
		AND acn.artist = (SELECT id FROM main_artist)
		LIMIT $2;
	`

	rows, err := s.DB.QueryContext(ctx, q, mbid, limit)
	if err != nil {
		return result, err
	}
	defer rows.Close()

	for rows.Next() {
		var recMBID, recName, trackMBID, trackName, releaseMBID string

		if err := rows.Scan(
			&recMBID,
			&recName,
			&trackMBID,
			&trackName,
			&releaseMBID,
		); err != nil {
			return result, err
		}

		performers, err := s.GetRecordingPerformers(ctx, recMBID)
		if err != nil {
			return result, err
		}

		result.Recordings = append(result.Recordings, DBTrack{
			RecordingMBID: recMBID,
			RecordingName: recName,
			TrackMBID:     trackMBID,
			TrackName:     trackName,
			CoverURL:      "https://coverartarchive.org/release/" + releaseMBID + "/front",
			Performers:    performers,
		})
	}

	return result, nil
}

//
// ========================================================================
// GetRecordingPerformers — REAL performers on a recording
// ========================================================================
//

func (s *Store) GetRecordingPerformers(
	ctx context.Context,
	recordingMBID string,
) ([]PerformerCredit, error) {

	q := `
		SELECT DISTINCT
			a.gid::text,
			a.name
		FROM recording r
		JOIN artist_credit ac ON ac.id = r.artist_credit
		JOIN artist_credit_name acn ON acn.artist_credit = ac.id
		JOIN artist a ON a.id = acn.artist
		WHERE r.gid = $1;
	`

	rows, err := s.DB.QueryContext(ctx, q, recordingMBID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var performers []PerformerCredit

	for rows.Next() {
		var p PerformerCredit
		if err := rows.Scan(&p.ID, &p.Name); err != nil {
			return nil, err
		}
		performers = append(performers, p)
	}

	return performers, nil
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
// Migration if needed
// ========================================================================
//

func (s *Store) Migrate(ctx context.Context) error {
	q := `
		CREATE TABLE IF NOT EXISTS artist_collab (
			artist_id INT NOT NULL,
			neighbor_artist_id INT NOT NULL,
			recording_id INT NOT NULL,
			CONSTRAINT artist_collab_pk PRIMARY KEY (artist_id, neighbor_artist_id, recording_id)
		);`

	ind := `
	CREATE INDEX artist_collab_artist_idx
    ON artist_collab (artist_id);

	CREATE INDEX artist_collab_neighbor_idx
		ON artist_collab (neighbor_artist_id);

	CREATE INDEX artist_collab_rec_idx
		ON artist_collab (recording_id);
`

	ins := `
		INSERT INTO artist_collab (artist_id, neighbor_artist_id, recording_id)
		SELECT
			acn1.artist,
			acn2.artist,
			r.id
		FROM recording r
		JOIN artist_credit ac ON ac.id = r.artist_credit
		JOIN artist_credit_name acn1 ON acn1.artist_credit = ac.id
		JOIN artist_credit_name acn2 ON acn2.artist_credit = ac.id
		WHERE acn1.artist <> acn2.artist
		ON CONFLICT DO NOTHING;
		`

	_, err := s.DB.Query(q)
	if err != nil {
		return err
	}
	_, err = s.DB.Query(ind)
	if err != nil {
		return err
	}

	_, err = s.DB.Query(ins)
	if err != nil {
		return err
	}

	return nil
}
