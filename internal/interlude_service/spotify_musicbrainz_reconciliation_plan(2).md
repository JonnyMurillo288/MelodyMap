# Spotify Search Reconciliation Update Plan (Strict Field Query Version)

## Overview

This version of the plan assumes that every Spotify query will be
executed using strict field filters:

    track:"<track_name>" artist:"<artist1>" artist:"<artist2>"

Where: - `artist2` may sometimes be an empty string (`""`). - If
`artist2` is empty, only `artist1` should be included in the query.

The goal is to improve match reliability while retaining strict Spotify
field-based querying.

------------------------------------------------------------------------

## Root Problems

### 1. Artist Name Formatting Differences

MusicBrainz often provides full credit strings including featured
artists, while Spotify separates artists into structured arrays.

Example: - MusicBrainz: `Styles P feat. Marsha from Floetry` - Spotify
stores: - `Styles P` - `Marsha Ambrosius`

If you pass the full MusicBrainz credit string into `artist:"..."`,
Spotify will fail to match.

------------------------------------------------------------------------

### 2. Track Version Formatting Differences

MusicBrainz and Spotify frequently store version text differently.

Examples: - MB: `Dream lantern (English ver.)` - Spotify:
`Dream Lantern - English Version`

Strict `track:"..."` filtering requires normalized track names.

------------------------------------------------------------------------

### 3. Unicode and Character Normalization

Differences include: - Curly quotes vs straight quotes - Full-width vs
half-width characters - NFC vs NFKC normalization

Strict filtering makes normalization mandatory.

------------------------------------------------------------------------

## Required Architecture Changes

### Stage 1: Extract Structured MusicBrainz Metadata

Do NOT use flattened artist credit strings.

Extract: - Recording title - Structured artist list from:

    artist-credit[].artist.name

Never pass raw credit strings like:

    Styles P feat. Marsha from Floetry

Instead, split into individual artists.

------------------------------------------------------------------------

### Stage 2: Normalize Metadata Before Query

Because strict Spotify filtering is used, normalization must happen
BEFORE constructing the query.

------------------------------------------------------------------------

### Normalize Unicode

Use:

``` go
import "golang.org/x/text/unicode/norm"
```

Normalize all strings to NFC or NFKC.

------------------------------------------------------------------------

### Clean Artist Names

Remove feature markers and join phrases before passing to Spotify.

``` go
func cleanArtist(a string) string {
    lower := strings.ToLower(a)
    lower = strings.Split(lower, " feat")[0]
    lower = strings.Split(lower, " featuring")[0]
    lower = strings.Split(lower, "&")[0]
    return strings.TrimSpace(lower)
}
```

If multiple structured artists exist from MusicBrainz:

-   `artist1 = first artist`
-   `artist2 = second artist (if exists)`
-   If only one artist exists → `artist2 = ""`

------------------------------------------------------------------------

### Clean Track Names

Strip version formatting and normalize punctuation.

``` go
func cleanTrack(t string) string {
    lower := strings.ToLower(t)
    lower = strings.ReplaceAll(lower, "’", "'")
    lower = regexp.MustCompile(`\(.+?\)`).ReplaceAllString(lower, "")
    return strings.TrimSpace(lower)
}
```

------------------------------------------------------------------------

## Query Construction Rules

### Case 1: Two Artists

If both artists exist:

    track:"<clean_track>" artist:"<clean_artist1>" artist:"<clean_artist2>"

### Case 2: Only One Artist

If `artist2 == ""`:

    track:"<clean_track>" artist:"<clean_artist1>"

Do NOT include an empty artist filter.

------------------------------------------------------------------------

## Post-Search Validation

Even with strict filtering, Spotify search is not perfectly exact.

After receiving results:

1.  Verify normalized track name match.
2.  Verify both artists exist in Spotify's returned artist array.
3.  Reject partial matches.
4.  Return best validated candidate.

------------------------------------------------------------------------

## Updated Iterative Workflow

For each MusicBrainz recording:

1.  Extract structured artist array.
2.  Assign:
    -   artist1 = first artist
    -   artist2 = second artist or ""
3.  Normalize track + artists.
4.  Construct strict Spotify field query.
5.  Execute search.
6.  Validate returned results manually.
7.  Return best validated match.
8.  Log failures for reconciliation review.

------------------------------------------------------------------------

## Important Constraints

Because strict filtering is used:

-   Normalization errors will cause total failure.
-   Feature text must never be included in artist filters.
-   Unicode inconsistencies must be resolved before query.
-   Version text in parentheses should be stripped.

------------------------------------------------------------------------

## Expected Outcomes

After implementing this update:

-   Improved success rate when using strict Spotify field filters
-   Reduced false negatives caused by formatting differences
-   Controlled reconciliation logic while preserving strict matching
    semantics
