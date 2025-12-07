package main

// import (
// 	"context"
// 	"database/sql"
// 	"encoding/json"
// 	"errors"
// 	"fmt"
// 	"os"
// 	"strings"
// 	"time"

// 	sixdegrees "github.com/Jonnymurillo288/MelodyMap/sixDegrees"
// )

// // Store wraps a sql.DB and exposes helpers for reading/writing artists, albums, and tracks.
// //
// // DSN example (MySQL):
// //   user:pass@tcp(127.0.0.1:3306)/sixdegrees?parseTime=true&charset=utf8mb4
// // You can set MYSQL_DSN to override from environment.

// type Store struct {
// 	DB *sql.DB
// }

// // createDBTrack builds a DBTrack struct from a sixdegrees.Track
// func createDBTrack(t sixdegrees.Track, album string) DBTrack {
// 	return DBTrack{
// 		ID:              t.ID,
// 		Name:            t.Name,
// 		AlbumID:         sql.NullString{String: album, Valid: album != ""},
// 		PrimaryArtistID: sql.NullString{String: t.Artist.ID, Valid: t.Artist.ID != ""},
// 	}
// }

// // createDBAlbum builds a DBAlbum struct from Spotify album metadata
// func createDBAlbum(albumID, name, artist string) DBAlbum {
// 	return DBAlbum{
// 		ID:              albumID,
// 		Name:            sql.NullString{String: name, Valid: name != ""},
// 		PrimaryArtistID: sql.NullString{String: artist, Valid: artist != ""},
// 	}
// }

// // createDBArtist converts a sixdegrees.Artist into a DBArtist record.
// func createDBArtist(a sixdegrees.Artists) DBArtist {
// 	var genresJSON map[string]int

// 	// If the source has genres as a slice, convert to a simple map[int]bool or map[string]int
// 	if len(a.Genres) > 0 {
// 		genresJSON = make(map[string]int, len(a.Genres))
// 		for g := range a.Genres {
// 			genresJSON[g] = 1
// 		}
// 	}

// 	return DBArtist{
// 		ID:         a.ID,
// 		Name:       a.Name,
// 		Popularity: sql.NullInt64{Int64: int64(a.Popularity), Valid: a.Popularity > 0},
// 		Genres:     genresJSON,
// 	}
// }

// // Open creates a DB connection using the given DSN. If dsn == "", it uses MYSQL_DSN or a sensible default.
// func Open(dsn string) (*Store, error) {
// 	if dsn == "" {
// 		dsn = os.Getenv("MYSQL_DSN")
// 		if dsn == "" {
// 			dsn = "root:password@tcp(127.0.0.1:3306)/sixdegrees?parseTime=true&charset=utf8mb4"
// 		}
// 	}
// 	db, err := sql.Open("mysql", dsn)
// 	if err != nil {
// 		return nil, err
// 	}
// 	if err := withTimeout(func(ctx context.Context) error { return db.PingContext(ctx) }, 5*time.Second); err != nil {
// 		_ = db.Close()
// 		return nil, err
// 	}
// 	return &Store{DB: db}, nil
// }

// func (s *Store) Close() error {
// 	if s == nil || s.DB == nil {
// 		return nil
// 	}
// 	return s.DB.Close()
// }

// // Migrate creates the necessary tables and indexes if they do not exist.
// func (s *Store) Migrate(ctx context.Context) error {
// 	if s == nil || s.DB == nil {
// 		return errors.New("nil store")
// 	}
// 	stmts := []string{
// 		`CREATE TABLE IF NOT EXISTS artists (
// 			id VARCHAR(64) PRIMARY KEY,
// 			name VARCHAR(255) NOT NULL,
// 			popularity INT NULL,
// 			genres TEXT NULL,
// 			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
// 			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
// 			INDEX idx_artists_name (name)
// 		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
// 		`CREATE TABLE IF NOT EXISTS albums (
// 			id VARCHAR(64) PRIMARY KEY,
// 			name VARCHAR(255) NULL,
// 			primary_artist_id VARCHAR(64) NULL,
// 			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
// 			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
// 			INDEX idx_albums_name (name),
// 			INDEX idx_albums_primary_artist (primary_artist_id),
// 			FOREIGN KEY (primary_artist_id) REFERENCES artists(id) ON DELETE SET NULL ON UPDATE CASCADE
// 		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
// 		`CREATE TABLE IF NOT EXISTS tracks (
// 			id VARCHAR(64) PRIMARY KEY,
// 			name VARCHAR(255) NOT NULL,
// 			album_id VARCHAR(64) NULL,
// 			primary_artist_id VARCHAR(64) NULL,
// 			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
// 			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
// 			INDEX idx_tracks_name (name),
// 			INDEX idx_tracks_album (album_id),
// 			INDEX idx_tracks_primary_artist (primary_artist_id),
// 			FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE SET NULL ON UPDATE CASCADE,
// 			FOREIGN KEY (primary_artist_id) REFERENCES artists(id) ON DELETE SET NULL ON UPDATE CASCADE
// 		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
// 		`CREATE TABLE IF NOT EXISTS track_artists (
// 			track_id VARCHAR(64) NOT NULL,
// 			artist_id VARCHAR(64) NOT NULL,
// 			role ENUM('primary','featured') NOT NULL DEFAULT 'featured',
// 			PRIMARY KEY (track_id, artist_id),
// 			INDEX idx_track_artists_artist (artist_id),
// 			FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE ON UPDATE CASCADE,
// 			FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE ON UPDATE CASCADE
// 		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
// 		`CREATE TABLE IF NOT EXISTS album_artists (
// 			album_id  VARCHAR(64) NOT NULL,
// 			artist_id VARCHAR(64) NOT NULL,

// 			PRIMARY KEY (album_id, artist_id),

// 			INDEX idx_album_artists_album (album_id),
// 			INDEX idx_album_artists_artist (artist_id),

// 			FOREIGN KEY (album_id) REFERENCES albums(id)
// 				ON DELETE CASCADE ON UPDATE CASCADE,

// 			FOREIGN KEY (artist_id) REFERENCES artists(id)
// 				ON DELETE CASCADE ON UPDATE CASCADE
// 		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
// 		`CREATE TABLE IF NOT EXISTS MainHelper (
// 			ArtistID VARCHAR(50) NOT NULL,
// 			ArtistName VARCHAR(255),
// 			FeaturedID VARCHAR(50),
// 			FeaturedName VARCHAR(255),
// 			TrackIDLink VARCHAR(50),
// 			TrackNameLink VARCHAR(255),
// 			PopularityWeight SMALLINT,
// 			PRIMARY KEY (ArtistID, TrackIDLink)
// 		);`,
// 	}
// 	for _, q := range stmts {
// 		if _, err := s.DB.ExecContext(ctx, q); err != nil {
// 			return err
// 		}
// 	}
// 	return nil
// }

// // =============================== Data Models =============================== //

// type DBArtist struct {
// 	ID         string
// 	Name       string
// 	Popularity sql.NullInt64
// 	Genres     map[string]int // stored as JSON TEXT under-the-hood
// }

// type DBAlbum struct {
// 	ID              string
// 	Name            sql.NullString
// 	PrimaryArtistID sql.NullString
// }

// type DBTrack struct {
// 	ID              string
// 	Name            string
// 	AlbumID         sql.NullString
// 	PrimaryArtistID sql.NullString
// }

// // =============================== Upserts ================================== //

// func (s *Store) UpsertArtist(ctx context.Context, a DBArtist) error {
// 	if a.ID == "" || a.Name == "" {
// 		return errors.New("artist id and name required")
// 	}
// 	var genresJSON *string
// 	if a.Genres != nil {
// 		b, _ := json.Marshal(a.Genres)
// 		gj := string(b)
// 		genresJSON = &gj
// 	}
// 	q := `INSERT INTO artists (id, name, popularity, genres)
// 		VALUES (?,?,?,?)
// 		ON DUPLICATE KEY UPDATE name=VALUES(name), popularity=VALUES(popularity), genres=VALUES(genres)`
// 	_, err := s.DB.ExecContext(ctx, q, a.ID, a.Name, nullInt(a.Popularity), genresJSON)
// 	return err
// }

// func (s *Store) UpsertGraph(ctx context.Context, mh MainHelper) error {
// 	if mh.ArtistID == "" || mh.TrackIDLink == "" {
// 		return errors.New("artist id and track id required")
// 	}

// 	q := `INSERT INTO MainHelper
// 			(ArtistID, ArtistName, FeaturedID, FeaturedName, TrackIDLink,TrackNameLink, PopularityWeight)
// 		VALUES (?, ?, ?, ?, ?, ?, ?)
// 		ON DUPLICATE KEY UPDATE
// 			ArtistName = VALUES(ArtistName),
// 			FeaturedID = VALUES(FeaturedID),
// 			FeaturedName = VALUES(FeaturedName),
// 			PopularityWeight = VALUES(PopularityWeight)`

// 	_, err := s.DB.ExecContext(ctx, q,
// 		mh.ArtistID,
// 		mh.ArtistName,
// 		mh.FeaturedID,
// 		mh.FeaturedName,
// 		mh.TrackIDLink,
// 		mh.PopularityWeight,
// 	)
// 	return err
// }

// func (s *Store) UpsertAlbum(ctx context.Context, al DBAlbum) error {
// 	if al.ID == "" {
// 		return errors.New("album id required")
// 	}
// 	q := `INSERT INTO albums (id, name, primary_artist_id)
// 		VALUES (?,?,?)
// 		ON DUPLICATE KEY UPDATE name=VALUES(name), primary_artist_id=VALUES(primary_artist_id)`
// 	_, err := s.DB.ExecContext(ctx, q, al.ID, al.Name, al.PrimaryArtistID)
// 	return err
// }

// func (s *Store) UpsertTrack(ctx context.Context, t DBTrack) error {
// 	if t.ID == "" || t.Name == "" {
// 		return errors.New("track id and name required")
// 	}
// 	q := `INSERT INTO tracks (id, name, album_id, primary_artist_id)
// 		VALUES (?,?,?,?)
// 		ON DUPLICATE KEY UPDATE name=VALUES(name), album_id=VALUES(album_id), primary_artist_id=VALUES(primary_artist_id)`
// 	_, err := s.DB.ExecContext(ctx, q, t.ID, t.Name, t.AlbumID, t.PrimaryArtistID)
// 	return err
// }

// func (s *Store) AddTrackArtist(ctx context.Context, trackID, artistID, role string) error {
// 	if trackID == "" || artistID == "" {
// 		return errors.New("trackID and artistID required")
// 	}
// 	role = strings.ToLower(role)
// 	if role != "primary" && role != "featured" {
// 		role = "featured"
// 	}
// 	q := `INSERT INTO track_artists (track_id, artist_id, role)
// 		VALUES (?,?,?)
// 		ON DUPLICATE KEY UPDATE role=VALUES(role)`
// 	_, err := s.DB.ExecContext(ctx, q, trackID, artistID, role)
// 	return err
// }

// func (s *Store) AddAlbumArtist(ctx context.Context, albumID, artistID string) error {
// 	if albumID == "" || artistID == "" {
// 		return errors.New("albumID and artistID required")
// 	}

// 	q := `INSERT INTO album_artists (album_id, artist_id)
//           VALUES (?, ?)
//           ON DUPLICATE KEY UPDATE artist_id = VALUES(artist_id)`

// 	_, err := s.DB.ExecContext(ctx, q, albumID, artistID)
// 	return err
// }

// // ========================= Convenience Converters ========================= //

// // SaveArtistWithTracks persists a sixDegrees.Artists object and all its tracks,
// // including featured collaborators.
// //
// // - Upserts the primary artist with popularity and genres.
// // - Upserts each track and creates track_artists relations for primary and features.
// // - Upserts any discovered featured artists by their ID/Name if known (ID may be empty if not looked up yet).
// func (s *Store) SaveArtistWithTracks(ctx context.Context, a *sixdegrees.Artists) error {
// 	if a == nil || a.Name == "" {
// 		return errors.New("artist required")
// 	}
// 	// If ID is missing we still allow storing by name (but recommend having Spotify ID)
// 	artistID := a.ID
// 	if artistID == "" {
// 		artistID = strings.ToLower(strings.ReplaceAll(a.Name, " ", "_")) // fallback deterministic key
// 	}
// 	pop := sql.NullInt64{}
// 	if a.Popularity > 0 {
// 		pop = sql.NullInt64{Int64: int64(a.Popularity), Valid: true}
// 	}
// 	if err := s.UpsertArtist(ctx, DBArtist{ID: artistID, Name: a.Name, Popularity: pop, Genres: a.Genres}); err != nil {
// 		return fmt.Errorf("upsert artist: %w", err)
// 	}
// 	for _, t := range a.Tracks {
// 		trackID := t.ID
// 		if trackID == "" {
// 			// Some flows might not include IDs; derive a stable key on name + primary artist
// 			trackID = strings.ToLower(fmt.Sprintf("%s::%s", a.Name, t.Name))
// 		}
// 		if err := s.UpsertTrack(ctx, DBTrack{
// 			ID:   trackID,
// 			Name: t.Name,
// 			// album unknown here (nullable)
// 			PrimaryArtistID: sql.NullString{String: artistID, Valid: artistID != ""},
// 		}); err != nil {
// 			return fmt.Errorf("upsert track: %w", err)
// 		}
// 		// primary relation
// 		if err := s.AddTrackArtist(ctx, trackID, artistID, "primary"); err != nil {
// 			return fmt.Errorf("link primary artist: %w", err)
// 		}
// 		// featured relations
// 		for _, f := range t.Featured {
// 			if f == nil || f.Name == "" {
// 				continue
// 			}
// 			fid := f.ID
// 			if fid == "" {
// 				fid = strings.ToLower(strings.ReplaceAll(f.Name, " ", "_"))
// 			}
// 			if err := s.UpsertArtist(ctx, DBArtist{ID: fid, Name: f.Name}); err != nil {
// 				return fmt.Errorf("upsert featured artist: %w", err)
// 			}
// 			if err := s.AddTrackArtist(ctx, trackID, fid, "featured"); err != nil {
// 				return fmt.Errorf("link featured artist: %w", err)
// 			}
// 		}
// 	}
// 	return nil
// }

// // ================================ Reads =================================== //

// func (s *Store) GetArtistByID(ctx context.Context, id string) (DBArtist, error) {
// 	var row DBArtist
// 	if id == "" {
// 		return row, errors.New("id required")
// 	}
// 	q := `SELECT id, name, popularity, genres FROM artists WHERE id=?`
// 	var genres sql.NullString
// 	var pop sql.NullInt64
// 	if err := s.DB.QueryRowContext(ctx, q, id).Scan(&row.ID, &row.Name, &pop, &genres); err != nil {
// 		return row, err
// 	}
// 	row.Popularity = pop
// 	if genres.Valid && genres.String != "" {
// 		_ = json.Unmarshal([]byte(genres.String), &row.Genres)
// 	}
// 	return row, nil
// }

// func (s *Store) FindArtistByName(ctx context.Context, name string) (DBArtist, error) {
// 	var row DBArtist
// 	if name == "" {
// 		return row, errors.New("name required")
// 	}
// 	q := `SELECT id, name, popularity, genres FROM artists WHERE name=? LIMIT 1`
// 	var genres sql.NullString
// 	var pop sql.NullInt64
// 	if err := s.DB.QueryRowContext(ctx, q, name).Scan(&row.ID, &row.Name, &pop, &genres); err != nil {
// 		return row, err
// 	}
// 	row.Popularity = pop
// 	if genres.Valid && genres.String != "" {
// 		_ = json.Unmarshal([]byte(genres.String), &row.Genres)
// 	}
// 	return row, nil
// }

// func (s *Store) SearchArtistsByName(ctx context.Context, qstr string, limit int) ([]DBArtist, error) {
// 	if limit <= 0 || limit > 1000 {
// 		limit = 25
// 	}
// 	q := `SELECT id, name, popularity, genres FROM artists WHERE name LIKE ? ORDER BY name LIMIT ?`
// 	rows, err := s.DB.QueryContext(ctx, q, like(qstr), limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBArtist
// 	for rows.Next() {
// 		var a DBArtist
// 		var genres sql.NullString
// 		var pop sql.NullInt64
// 		if err := rows.Scan(&a.ID, &a.Name, &pop, &genres); err != nil {
// 			return nil, err
// 		}
// 		a.Popularity = pop
// 		if genres.Valid && genres.String != "" {
// 			_ = json.Unmarshal([]byte(genres.String), &a.Genres)
// 		}
// 		out = append(out, a)
// 	}
// 	return out, rows.Err()
// }

// func (s *Store) GetAlbumByID(ctx context.Context, id string) (DBAlbum, error) {
// 	var row DBAlbum
// 	if id == "" {
// 		return row, errors.New("id required")
// 	}
// 	q := `SELECT id, name, primary_artist_id FROM albums WHERE id=?`
// 	if err := s.DB.QueryRowContext(ctx, q, id).Scan(&row.ID, &row.Name, &row.PrimaryArtistID); err != nil {
// 		return row, err
// 	}
// 	return row, nil
// }

// func (s *Store) SearchAlbumsByName(ctx context.Context, qstr string, limit int) ([]DBAlbum, error) {
// 	if limit <= 0 || limit > 1000 {
// 		limit = 25
// 	}
// 	q := `SELECT id, name, primary_artist_id FROM albums WHERE name LIKE ? ORDER BY name LIMIT ?`
// 	rows, err := s.DB.QueryContext(ctx, q, like(qstr), limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBAlbum
// 	for rows.Next() {
// 		var a DBAlbum
// 		if err := rows.Scan(&a.ID, &a.Name, &a.PrimaryArtistID); err != nil {
// 			return nil, err
// 		}
// 		out = append(out, a)
// 	}
// 	return out, rows.Err()
// }

// // Returns the track given a trackID
// func (s *Store) GetTrackByID(ctx context.Context, id string) (DBTrack, error) {
// 	var row DBTrack
// 	if id == "" {
// 		return row, errors.New("id required")
// 	}
// 	q := `SELECT id, name, album_id, primary_artist_id FROM tracks WHERE id=?`
// 	if err := s.DB.QueryRowContext(ctx, q, id).Scan(&row.ID, &row.Name, &row.AlbumID, &row.PrimaryArtistID); err != nil {
// 		return row, err
// 	}
// 	return row, nil
// }

// func (s *Store) SearchTracksByName(ctx context.Context, qstr string, limit int) ([]DBTrack, error) {
// 	if limit <= 0 || limit > 1000 {
// 		limit = 25
// 	}
// 	q := `SELECT id, name, album_id, primary_artist_id FROM tracks WHERE name LIKE ? ORDER BY name LIMIT ?`
// 	rows, err := s.DB.QueryContext(ctx, q, like(qstr), limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBTrack
// 	for rows.Next() {
// 		var t DBTrack
// 		if err := rows.Scan(&t.ID, &t.Name, &t.AlbumID, &t.PrimaryArtistID); err != nil {
// 			return nil, err
// 		}
// 		out = append(out, t)
// 	}
// 	return out, rows.Err()
// }

// func (s *Store) ListTracksByArtistID(ctx context.Context, artistID string, limit int) ([]DBTrack, error) {
// 	if artistID == "" {
// 		return nil, errors.New("artistID required")
// 	}
// 	if limit <= 0 || limit > 1000 {
// 		limit = 50
// 	}
// 	q := `SELECT t.id, t.name, t.album_id, t.primary_artist_id
// 		FROM tracks t
// 		JOIN track_artists ta ON ta.track_id = t.id
// 		WHERE ta.artist_id = ?
// 		ORDER BY t.name LIMIT ?`
// 	rows, err := s.DB.QueryContext(ctx, q, artistID, limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBTrack
// 	for rows.Next() {
// 		var t DBTrack
// 		if err := rows.Scan(&t.ID, &t.Name, &t.AlbumID, &t.PrimaryArtistID); err != nil {
// 			return nil, err
// 		}
// 		out = append(out, t)
// 	}
// 	return out, rows.Err()
// }

// func (s *Store) ListAlbumsByArtistID(ctx context.Context, artistID string, limit int) ([]DBAlbum, error) {
// 	if artistID == "" {
// 		return nil, errors.New("artistID required")
// 	}
// 	if limit <= 0 || limit > 1000 {
// 		limit = 50
// 	}
// 	q := `SELECT DISTINCT a.id, a.name, a.primary_artist_id
// 		FROM albums a
// 		LEFT JOIN tracks t ON t.album_id = a.id
// 		LEFT JOIN track_artists ta ON ta.track_id = t.id
// 		WHERE a.primary_artist_id = ? OR ta.artist_id = ?
// 		ORDER BY a.name LIMIT ?`
// 	rows, err := s.DB.QueryContext(ctx, q, artistID, artistID, limit)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBAlbum
// 	for rows.Next() {
// 		var a DBAlbum
// 		if err := rows.Scan(&a.ID, &a.Name, &a.PrimaryArtistID); err != nil {
// 			return nil, err
// 		}
// 		out = append(out, a)
// 	}
// 	return out, rows.Err()
// }

// func (s *Store) ListTracksByAlbumID(ctx context.Context, album_id string) ([]DBTrack, error) {
// 	if album_id == "" {
// 		return nil, errors.New("artistID required")
// 	}

// 	q := `SELECT DISTINCT id, name, album_id, primary_artist_id
// 		FROM tracks
// 		WHERE album_id = ?
// 		`
// 	rows, err := s.DB.QueryContext(ctx, q, album_id)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBTrack
// 	for rows.Next() {
// 		var a DBTrack
// 		if err := rows.Scan(&a.ID, &a.Name, &a.AlbumID, &a.PrimaryArtistID); err != nil {
// 			return nil, err
// 		}
// 		out = append(out, a)
// 	}
// 	return out, rows.Err()
// }

// func (s *Store) ListFeaturedArtistsForTrack(ctx context.Context, trackID string) ([]DBArtist, error) {
// 	if trackID == "" {
// 		return nil, errors.New("trackID required")
// 	}
// 	q := `SELECT ar.id, ar.name, ar.popularity, ar.genres
// 		FROM track_artists ta
// 		JOIN artists ar ON ar.id = ta.artist_id
// 		WHERE ta.track_id = ? AND ta.role = 'featured'`
// 	rows, err := s.DB.QueryContext(ctx, q, trackID)
// 	if err != nil {
// 		return nil, err
// 	}
// 	defer rows.Close()
// 	var out []DBArtist
// 	for rows.Next() {
// 		var a DBArtist
// 		var genres sql.NullString
// 		var pop sql.NullInt64
// 		if err := rows.Scan(&a.ID, &a.Name, &pop, &genres); err != nil {
// 			return nil, err
// 		}
// 		a.Popularity = pop
// 		if genres.Valid && genres.String != "" {
// 			_ = json.Unmarshal([]byte(genres.String), &a.Genres)
// 		}
// 		out = append(out, a)
// 	}
// 	return out, rows.Err()
// }

// // ============================ DBA to Spotify Object ============================ //

// func (s *Store) DBArtistsToArtists(dbArtist DBArtist) (*sixdegrees.Artists, error) {

// 	return sixdegrees.CreateArtists(dbArtist.Name, dbArtist.ID), nil
// }
