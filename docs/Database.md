# Database Documentation

This document describes the database layer used to persist and query artists, albums, and tracks derived from Spotify data. It covers the schema, relationships, connection and migration, and the available helper functions for reading and writing data.

Package: db
File: db/store.go
Driver: github.com/go-sql-driver/mysql


## Overview

- Purpose: Store Spotify-derived artists, albums, and tracks, and expose read/query functions used by the sixDegrees search and other components.
- Engine: MySQL (InnoDB, utf8mb4). Can be adapted to other databases if needed.
- Access API: A thin wrapper around database/sql with explicit upsert and search helpers.


## Connection and configuration

- DSN format (MySQL example):
  user:pass@tcp(127.0.0.1:3306)/sixdegrees?parseTime=true&charset=utf8mb4

- The package exposes Open(dsn string) (*Store, error). If dsn is empty, it reads MYSQL_DSN from the environment or uses a sensible default.

- Example usage:
  - s, err := db.Open("")
  - defer s.Close()
  - _ = s.Migrate(context.Background())

Note: The Open function pings the database with a timeout to verify connectivity.


## Schema

The schema is created by Store.Migrate and contains four tables.

1) artists
- id VARCHAR(64) PRIMARY KEY
  - Expected to be the Spotify artist ID when available
- name VARCHAR(255) NOT NULL
- popularity INT NULL (0..100 from Spotify)
- genres TEXT NULL (JSON: map[string]int)
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
- Indexes: idx_artists_name(name)

2) albums
- id VARCHAR(64) PRIMARY KEY (Spotify album ID when available)
- name VARCHAR(255) NULL
- primary_artist_id VARCHAR(64) NULL (FK → artists.id)
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
- Indexes: idx_albums_name(name), idx_albums_primary_artist(primary_artist_id)
- Constraints: FOREIGN KEY (primary_artist_id) REFERENCES artists(id) ON DELETE SET NULL ON UPDATE CASCADE

3) tracks
- id VARCHAR(64) PRIMARY KEY (Spotify track ID when available)
- name VARCHAR(255) NOT NULL
- album_id VARCHAR(64) NULL (FK → albums.id)
- primary_artist_id VARCHAR(64) NULL (FK → artists.id)
- created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
- Indexes: idx_tracks_name(name), idx_tracks_album(album_id), idx_tracks_primary_artist(primary_artist_id)
- Constraints:
  - FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE SET NULL ON UPDATE CASCADE
  - FOREIGN KEY (primary_artist_id) REFERENCES artists(id) ON DELETE SET NULL ON UPDATE CASCADE

4) track_artists
- track_id VARCHAR(64) NOT NULL (FK → tracks.id)
- artist_id VARCHAR(64) NOT NULL (FK → artists.id)
- role ENUM('primary','featured') NOT NULL DEFAULT 'featured'
- PRIMARY KEY(track_id, artist_id)
- Indexes: idx_track_artists_artist(artist_id)
- Constraints:
  - FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE ON UPDATE CASCADE
  - FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE ON UPDATE CASCADE


## Relationships

- artists ↔ albums
  - albums.primary_artist_id → artists.id (optional)

- artists ↔ tracks
  - tracks.primary_artist_id → artists.id (optional)
  - track_artists bridges many-to-many relationships:
    - (track_id, artist_id, role) with role = 'primary' or 'featured'

- albums ↔ tracks
  - tracks.album_id → albums.id (optional)

Cardinalities:
- One artist may have many albums and tracks.
- One track may have one primary artist and many featured artists.
- Many artists can feature on many tracks (via track_artists).


## Migrations

- Call Store.Migrate(ctx) after opening the Store to ensure all tables and indexes exist.
- Migrate is idempotent and uses CREATE TABLE IF NOT EXISTS. Foreign keys, indexes, and character sets are applied on first creation.


## Write helpers

- UpsertArtist(ctx, DBArtist) error
  - Inserts or updates an artist by id.
  - DBArtist fields: ID, Name, Popularity (sql.NullInt64), Genres (map[string]int as JSON in DB).

- UpsertAlbum(ctx, DBAlbum) error
  - Inserts or updates an album by id.
  - DBAlbum fields: ID, Name (sql.NullString), PrimaryArtistID (sql.NullString).

- UpsertTrack(ctx, DBTrack) error
  - Inserts or updates a track by id.
  - DBTrack fields: ID, Name, AlbumID (sql.NullString), PrimaryArtistID (sql.NullString).

- AddTrackArtist(ctx, trackID, artistID, role) error
  - Creates/updates the relationship between a track and an artist in track_artists.
  - role: 'primary' or 'featured'. Defaults to 'featured' if invalid.

- SaveArtistWithTracks(ctx, *sixdegrees.Artists) error
  - Persists a sixDegrees.Artists object and all its Tracks:
    - Upserts the primary artist with popularity and genres.
    - Upserts each track, associates primary artist, and links each featured artist.
    - Upserts any featured artist discovered by name/ID.
  - ID fallback behavior: if an object lacks a Spotify ID, a deterministic key is generated from the name. Prefer real Spotify IDs for consistent foreign keys.


## Read helpers

- GetArtistByID(ctx, id) (DBArtist, error)
- FindArtistByName(ctx, name) (DBArtist, error)
- SearchArtistsByName(ctx, q string, limit int) ([]DBArtist, error)

- GetAlbumByID(ctx, id) (DBAlbum, error)
- SearchAlbumsByName(ctx, q string, limit int) ([]DBAlbum, error)

- GetTrackByID(ctx, id) (DBTrack, error)
- SearchTracksByName(ctx, q string, limit int) ([]DBTrack, error)

- ListTracksByArtistID(ctx, artistID string, limit int) ([]DBTrack, error)
  - Returns tracks associated to the given artist via track_artists.

- ListAlbumsByArtistID(ctx, artistID string, limit int) ([]DBAlbum, error)
  - Returns distinct albums where the artist is primary or appears on any track.

- ListFeaturedArtistsForTrack(ctx, trackID string) ([]DBArtist, error)
  - Lists artists with role = 'featured' for the specified track.


## Data flow from Spotify objects

- sixDegrees.Artists → DB:
  - ID: preferred Spotify artist ID (artists.id)
  - Name: from Spotify Search
  - Popularity: from Spotify Search
  - Genres: frequency map built during search

- sixDegrees.Track → DB:
  - Name and ID (if present)
  - Primary artist: the owning Artists
  - Featured artists: converted into track_artists rows
  - Album linkage: not automatically set by SaveArtistWithTracks unless known; can be populated by calling UpsertAlbum/UpsertTrack with AlbumID when album IDs are available.


## Operational notes

- Indexes: name fields are indexed to support LIKE queries used by Search* helpers.
- Charset: utf8mb4 for full Unicode support (emoji, etc.).
- Foreign keys: ON DELETE CASCADE is used on track_artists, and SET NULL on tracks/albums to preserve records if the referenced artist/album/track is deleted.
- Timeouts: Open() verifies connectivity with a short timeout. Wrap long operations with context deadlines if needed.
- Transactions: SaveArtistWithTracks currently performs best-effort upserts per row. For atomic multi-row writes, consider adding a transactional variant (begin/commit/rollback).


## Setup checklist

1) Provision a MySQL instance and create a database (e.g., sixdegrees).
2) Set MYSQL_DSN in your environment or pass an explicit DSN to Open().
3) Call Migrate() once at startup.
4) Use SaveArtistWithTracks, Upsert*, and Search* helpers in your ingestion/search flows.


## Extending the schema

- Add album and track metadata (release_date, duration, explicit flag, popularity) as additional columns.
- Normalize genres into a separate table if you need to query them individually.
- Add collaboration counts or materialized views for faster graph expansion.
- Add unique constraints and additional indexes to match query patterns.


## Portability

- The current schema uses MySQL-specific features (ENUM). When porting to PostgreSQL, switch role to TEXT with a CHECK constraint and adjust DDL and DSN accordingly. SQLite can also be supported with minor changes (foreign keys, enums, timestamps).
