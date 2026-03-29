# MBID → Spotify Artist ID Mapping Pipeline

## Goal
Produce a reliable mapping table:

```
artist_mbid (UUID)  → spotify_artist_id (string)
```
This will feed the Spotle-style debut year enrichment pipeline.

---

## DB Tables

### MBID → Spotify mapping table

```sql
CREATE TABLE artist_mbid_spotify (
    artist_mbid UUID PRIMARY KEY,
    spotify_artist_id TEXT,
    source TEXT DEFAULT 'mb_link',
    ambiguous BOOLEAN DEFAULT FALSE,
    similarity_score FLOAT,
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_artist_mbid_spotify_source
    ON artist_mbid_spotify(source);
```

- `similarity_score` holds how close Spotify name is to MB name
- `ambiguous = TRUE` for name search fallback

---

## Name similarity check

```python
import Levenshtein

def name_similarity(name1, name2):
    return 1 - Levenshtein.distance(name1.lower(), name2.lower()) / max(len(name1), len(name2))
```
- Returns 0.0–1.0
- Threshold ≥0.8 = good match
- Optional: use `rapidfuzz` for token-based fuzzy matching

---

## Mapping Logic (Python Skeleton)

```python
class MBIDtoSpotifyMapper:
    def __init__(self, mb_db, spotify_client, similarity_threshold=0.8):
        self.mb_db = mb_db  # your local MB DB connection
        self.spotify = spotify_client
        self.sim_threshold = similarity_threshold

    def from_mb_link(self, mbid):
        row = self.mb_db.query_spotify_link(mbid)
        if row:
            spotify_id = row['spotify_id']
            spotify_name = self.spotify.get_artist_name(spotify_id)
            mb_name = self.mb_db.get_artist_name(mbid)
            score = name_similarity(spotify_name, mb_name)
            ambiguous = score < self.sim_threshold
            return spotify_id, score, ambiguous
        return None, 0.0, True

    def from_spotify_name_search(self, mbid, mb_name):
        results = self.spotify.search_artist(mb_name)
        best_match = None
        best_score = 0
        for r in results:
            score = name_similarity(r['name'], mb_name)
            if score > best_score:
                best_score = score
                best_match = r
        if best_match and best_score >= self.sim_threshold:
            return best_match['id'], best_score, False
        return None, best_score, True

    def map_mbid(self, mbid):
        mb_name = self.mb_db.get_artist_name(mbid)

        spotify_id, score, ambiguous = self.from_mb_link(mbid)
        if spotify_id:
            return spotify_id, score, ambiguous, 'mb_link'

        spotify_id, score, ambiguous = self.from_spotify_name_search(mbid, mb_name)
        if spotify_id:
            return spotify_id, score, ambiguous, 'spotify_name'

        return None, 0.0, True, 'not_found'
```

---

## Pipeline Notes

- MB Link first → deterministic, high confidence
- Name search fallback → only use if missing MB link
- Similarity score threshold → ensures no obvious mismatches
- Log all ambiguous / failed cases → for manual review

---

## Batch processing / scaling

- Look Up the MBID from lastfm_artist_stats order by 'popularity' Desc
- 100k artists → process in batches of 500–1000
- Sleep ~0.1s between Spotify API requests to avoid rate limits
- Bulk insert into `artist_mbid_spotify` table every batch

---

## Optional Enhancements

- Store Spotify genres / popularity / followers → extra disambiguation info
- If multiple candidates exceed threshold → pick highest popularity
- Retry failed lookups later (token refresh / network errors)

---

## Decision Table: Which Option to Use When

| Source | When to Use | Confidence |
|--------|------------|------------|
| MB Link | If MusicBrainz has Spotify URL | High |
| Spotify MBID | Only fallback | Medium / ambiguous |
| Spotify Name | If no MBID match | Low–medium, must log |
| Manual review | Ambiguous / unmatched | Very high |

