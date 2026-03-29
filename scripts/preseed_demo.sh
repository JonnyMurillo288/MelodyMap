#!/usr/bin/env bash
# preseed_demo.sh — Pre-compute predictions for popular artists
# so the demo page feels instant when leads click through.
#
# Usage:
#   ./scripts/preseed_demo.sh https://your-domain.com YOUR_INTERNAL_SECRET
#
# Or for local dev:
#   ./scripts/preseed_demo.sh http://localhost:8002

set -euo pipefail

BASE_URL="${1:-http://localhost:8002}"
SECRET="${2:-${INTERNAL_SERVICE_SECRET:-}}"

# Header args
AUTH_HEADER=""
if [ -n "$SECRET" ]; then
    AUTH_HEADER="-H X-Internal-Secret:${SECRET}"
fi

echo "=== MelodyMap Demo Pre-seed ==="
echo "Target: $BASE_URL"
echo ""

# 1. Health check
echo "[1/4] Health check..."
curl -sf "$BASE_URL/api/v1/health" | python3 -m json.tool 2>/dev/null || echo "(health check returned non-JSON)"
echo ""

# 2. Populate daily predictions (triggers full ML pipeline per genre)
echo "[2/4] Populating daily predictions (this runs the ML pipeline for 12 genres)..."
curl -sf -X POST "$BASE_URL/api/v1/internal/populate-daily" \
    -H "Content-Type: application/json" \
    $AUTH_HEADER \
    | python3 -m json.tool 2>/dev/null || echo "(populate-daily completed or failed — check logs)"
echo ""

# 3. Pre-compute neighbor predictions for well-known artists
echo "[3/4] Pre-computing neighbors for popular artists..."

ARTISTS=(
    "Drake"
    "Taylor Swift"
    "Kendrick Lamar"
    "Radiohead"
    "Billie Eilish"
    "The Weeknd"
    "Bad Bunny"
    "Dua Lipa"
    "Tyler, the Creator"
    "SZA"
    "Beyonce"
    "Frank Ocean"
    "Kanye West"
    "Arctic Monkeys"
    "Tame Impala"
    "Adele"
    "Ed Sheeran"
    "Post Malone"
    "Travis Scott"
    "Rihanna"
    "Jay-Z"
    "Eminem"
    "Lady Gaga"
    "The Beatles"
    "David Bowie"
    "Queen"
    "Pink Floyd"
    "Nirvana"
    "Bob Marley"
    "Miles Davis"
)

for artist in "${ARTISTS[@]}"; do
    echo "  → $artist"
    curl -sf -X POST "$BASE_URL/api/v1/predict/neighbors" \
        -H "Content-Type: application/json" \
        $AUTH_HEADER \
        -d "{\"artist\": \"$artist\", \"limit\": 10}" \
        > /dev/null 2>&1 || echo "    (failed or not found — skipping)"
done
echo ""

# 4. Pre-compute a few interesting what-if scenarios
echo "[4/4] Pre-computing what-if scenarios..."

whatif_pairs=(
    '["Radiohead", "Kendrick Lamar"]'
    '["Taylor Swift", "Bad Bunny"]'
    '["Frank Ocean", "Tame Impala"]'
    '["Billie Eilish", "The Weeknd"]'
    '["Drake", "Arctic Monkeys"]'
    '["Beyonce", "Daft Punk"]'
    '["Adele", "Ed Sheeran"]'
    '["Miles Davis", "Kanye West"]'
)

for pair in "${whatif_pairs[@]}"; do
    echo "  → $pair"
    curl -sf -X POST "$BASE_URL/api/v1/explore/what-if" \
        -H "Content-Type: application/json" \
        $AUTH_HEADER \
        -d "{\"artists\": $pair, \"num_tracks\": 3, \"num_similar\": 3}" \
        > /dev/null 2>&1 || echo "    (failed — skipping)"
done

echo ""
echo "=== Pre-seed complete ==="
echo "Demo page should now have cached results for instant loading."
