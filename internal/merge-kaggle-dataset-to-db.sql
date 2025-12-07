/******************************************************************************
 * SixDegrees Database ETL Pipeline
 * --------------------------------
 * This script ingests the Kaggle Spotify track dataset into a normalized
 * relational schema consisting of:
 *
 *      - artists
 *      - albums
 *      - tracks
 *      - track_artists (many-to-many explode)
 *
 * The pipeline:
 *      1. Loads raw CSV into staging table `tracks_features`
 *      2. Inserts albums and tracks (deduped)
 *      3. Explodes and inserts ALL artists (primary + featured)
 *      4. Builds track→artist role mapping (primary/featured)
 *
 * Author: Jonny
 *****************************************************************************/


/******************************************************************************
 * 0. Environment Setup
 *****************************************************************************/

-- Check MySQL secure file restrictions (required for LOAD DATA)
USE baseball2026;
SHOW VARIABLES LIKE 'secure_file_priv';

-- Switch to the main schema
USE sixdegrees;

-- Inspect existing tables (for debugging)
SHOW TABLES;
SELECT * FROM tracks LIMIT 10;


/******************************************************************************
 * 1. Create Staging Table (Raw Kaggle Data)
 *    No constraints, no FKs — used for bulk ingest and transformation.
 *****************************************************************************/

CREATE TABLE IF NOT EXISTS tracks_features (
    id                VARCHAR(255),
    name              VARCHAR(255),
    album             VARCHAR(255),
    album_id          VARCHAR(255),
    artists           TEXT,
    artist_ids        TEXT,
    track_number      INT,
    disc_number       INT,
    explicit          BOOLEAN,
    danceability      DOUBLE,
    energy            DOUBLE,
    key_signature     INT,
    loudness          DOUBLE,
    mode              INT,
    speechiness       DOUBLE,
    acousticness      DOUBLE,
    instrumentalness  DOUBLE,
    liveness          DOUBLE,
    valence           DOUBLE,
    tempo             DOUBLE,
    duration_ms       BIGINT,
    time_signature    DOUBLE,
    year              INT,
    release_date      VARCHAR(50)
);

-- Allow local file loading (one-time per MySQL install)
SET GLOBAL local_infile = 1;


/******************************************************************************
 * 2. Load Kaggle CSV into Staging Table
 *****************************************************************************/

LOAD DATA LOCAL INFILE '/tmp/tracks_features.csv'
INTO TABLE tracks_features
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 ROWS;

SELECT * FROM tracks_features LIMIT 10;


/******************************************************************************
 * 3. Insert ALBUMS
 *    Extract unique album IDs from staging table.
 *    Use ON DUPLICATE to safely update existing records.
 *****************************************************************************/

INSERT INTO albums (id, name, primary_artist_id)
SELECT DISTINCT
    album_id AS id,
    album AS name,
    TRIM(SUBSTRING_INDEX(artist_ids, ',', 1)) AS primary_artist_id
FROM tracks_features
WHERE album_id IS NOT NULL
  AND album     IS NOT NULL
  AND artist_ids IS NOT NULL
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    primary_artist_id = VALUES(primary_artist_id);


/******************************************************************************
 * 4. Insert TRACKS
 *    Load unique tracks from staging dataset.
 *    INSERT IGNORE is used because staging may contain duplicates.
 *****************************************************************************/

TRUNCATE TABLE tracks;

INSERT IGNORE INTO tracks (id, name, album_id, primary_artist_id)
SELECT DISTINCT
    TRIM(id) AS id,
    name,
    album_id,
    TRIM(SUBSTRING_INDEX(artist_ids, ',', 1)) AS primary_artist_id
FROM tracks_features
WHERE id IS NOT NULL;

SELECT COUNT(*) FROM tracks;


/******************************************************************************
 * 5. Insert ARTISTS (Primary + Featured)
 *    Explodes comma-separated lists into 1 row per artist.
 *    Important: This must occur BEFORE inserting into track_artists.
 *****************************************************************************/

TRUNCATE TABLE artists;

INSERT IGNORE INTO artists (id, name, popularity, genres)
SELECT DISTINCT
    TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(artist_ids, ',', n.n), ',', -1)) AS artist_id,
    TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(artists,    ',', n.n), ',', -1)) AS artist_name,
    0 AS popularity,
    '' AS genres
FROM tracks_features
JOIN (
    SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5
    UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10
) AS n
ON n.n <= 1 + LENGTH(artist_ids) - LENGTH(REPLACE(artist_ids, ',', ''))
WHERE artist_ids IS NOT NULL;

SELECT COUNT(*) FROM artists;


/******************************************************************************
 * 6. Insert TRACK_ARTISTS (Many-to-Many Explode)
 *    This maps every track to every artist in its comma-separated list.
 *    n = 1  → primary artist
 *    n >= 2 → featured artist
 *****************************************************************************/

TRUNCATE TABLE track_artists;

INSERT INTO track_artists (track_id, artist_id, role)
SELECT DISTINCT
    id AS track_id,
    TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(artist_ids, ',', n.n), ',', -1)) AS artist_id,
    CASE WHEN n.n = 1 THEN 'primary'
         ELSE 'featured'
    END AS role
FROM tracks_features
JOIN (
    SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5
    UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10
) AS n
ON n.n <= 1 + LENGTH(artist_ids) - LENGTH(REPLACE(artist_ids, ',', ''))
WHERE artist_ids IS NOT NULL;

SELECT COUNT(*) FROM track_artists;


/******************************************************************************
 * 7. Quality Checks
 *****************************************************************************/

-- Total unique tracks in normalized table
SELECT COUNT(DISTINCT id) FROM tracks;

-- Total tracks represented in track_artists (should match above or exceed slightly)
SELECT COUNT(DISTINCT track_id) FROM track_artists;
