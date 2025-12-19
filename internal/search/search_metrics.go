package search

import (
	"context"
	"fmt"
	"time"
)

// SearchMetric represents a single search execution for performance analysis
type SearchMetric struct {
	ID            int       `json:"id"`
	SearchType    string    `json:"search_type"`    // "BFS" or "ASTAR"
	StartArtistID string    `json:"start_artist_id"`
	StartArtist   string    `json:"start_artist"`
	EndArtistID   string    `json:"end_artist_id"`
	EndArtist     string    `json:"end_artist"`
	NumHops       int       `json:"num_hops"`
	DurationMs    int64     `json:"duration_ms"`    // milliseconds
	Success       bool      `json:"success"`
	ErrorMessage  string    `json:"error_message"`
	MaxDepth      int       `json:"max_depth"`
	CreatedAt     time.Time `json:"created_at"`
}

// SaveSearchMetric saves a search result to the database for performance analysis
func (s *Store) SaveSearchMetric(ctx context.Context, metric SearchMetric) error {
	query := `
		INSERT INTO search_metrics (
			search_type,
			start_artist_id,
			start_artist,
			end_artist_id,
			end_artist,
			num_hops,
			duration_ms,
			success,
			error_message,
			max_depth,
			created_at
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
		RETURNING id
	`

	err := s.DB.QueryRowContext(
		ctx,
		query,
		metric.SearchType,
		metric.StartArtistID,
		metric.StartArtist,
		metric.EndArtistID,
		metric.EndArtist,
		metric.NumHops,
		metric.DurationMs,
		metric.Success,
		metric.ErrorMessage,
		metric.MaxDepth,
		metric.CreatedAt,
	).Scan(&metric.ID)

	if err != nil {
		return fmt.Errorf("failed to save search metric: %w", err)
	}

	return nil
}

// GetSearchMetrics retrieves search metrics with optional filters
func (s *Store) GetSearchMetrics(ctx context.Context, searchType string, limit int) ([]SearchMetric, error) {
	query := `
		SELECT
			id,
			search_type,
			start_artist_id,
			start_artist,
			end_artist_id,
			end_artist,
			num_hops,
			duration_ms,
			success,
			COALESCE(error_message, '') as error_message,
			max_depth,
			created_at
		FROM search_metrics
		WHERE ($1 = '' OR search_type = $1)
		  AND success = true
		ORDER BY created_at DESC
		LIMIT $2
	`

	rows, err := s.DB.QueryContext(ctx, query, searchType, limit)
	if err != nil {
		return nil, fmt.Errorf("failed to query search metrics: %w", err)
	}
	defer rows.Close()

	var metrics []SearchMetric
	for rows.Next() {
		var m SearchMetric
		err := rows.Scan(
			&m.ID,
			&m.SearchType,
			&m.StartArtistID,
			&m.StartArtist,
			&m.EndArtistID,
			&m.EndArtist,
			&m.NumHops,
			&m.DurationMs,
			&m.Success,
			&m.ErrorMessage,
			&m.MaxDepth,
			&m.CreatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan metric row: %w", err)
		}
		metrics = append(metrics, m)
	}

	return metrics, nil
}

// CompareSearchPerformance returns average performance stats for BFS vs A*
func (s *Store) CompareSearchPerformance(ctx context.Context) (map[string]interface{}, error) {
	query := `
		SELECT
			search_type,
			COUNT(*) as total_searches,
			AVG(duration_ms) as avg_duration_ms,
			MIN(duration_ms) as min_duration_ms,
			MAX(duration_ms) as max_duration_ms,
			AVG(num_hops) as avg_hops,
			COUNT(CASE WHEN success = true THEN 1 END) as successful_searches
		FROM search_metrics
		WHERE success = true
		GROUP BY search_type
		ORDER BY search_type
	`

	rows, err := s.DB.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query performance comparison: %w", err)
	}
	defer rows.Close()

	results := make(map[string]interface{})
	for rows.Next() {
		var searchType string
		var totalSearches, successfulSearches int
		var avgDuration, minDuration, maxDuration float64
		var avgHops float64

		err := rows.Scan(
			&searchType,
			&totalSearches,
			&avgDuration,
			&minDuration,
			&maxDuration,
			&avgHops,
			&successfulSearches,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan comparison row: %w", err)
		}

		results[searchType] = map[string]interface{}{
			"total_searches":      totalSearches,
			"successful_searches": successfulSearches,
			"avg_duration_ms":     avgDuration,
			"min_duration_ms":     minDuration,
			"max_duration_ms":     maxDuration,
			"avg_hops":            avgHops,
		}
	}

	return results, nil
}

// CreateSearchMetricsTable creates the search_metrics table if it doesn't exist
func (s *Store) CreateSearchMetricsTable(ctx context.Context) error {
	query := `
		CREATE TABLE IF NOT EXISTS search_metrics (
			id SERIAL PRIMARY KEY,
			search_type VARCHAR(10) NOT NULL,  -- 'BFS' or 'ASTAR'
			start_artist_id VARCHAR(255) NOT NULL,
			start_artist VARCHAR(500) NOT NULL,
			end_artist_id VARCHAR(255) NOT NULL,
			end_artist VARCHAR(500) NOT NULL,
			num_hops INTEGER NOT NULL,
			duration_ms BIGINT NOT NULL,
			success BOOLEAN NOT NULL DEFAULT true,
			error_message TEXT,
			max_depth INTEGER,
			created_at TIMESTAMP NOT NULL DEFAULT NOW()
		);

		CREATE INDEX IF NOT EXISTS idx_search_metrics_type
			ON search_metrics(search_type);

		CREATE INDEX IF NOT EXISTS idx_search_metrics_created
			ON search_metrics(created_at DESC);

		CREATE INDEX IF NOT EXISTS idx_search_metrics_success
			ON search_metrics(success);

		CREATE INDEX IF NOT EXISTS idx_search_metrics_duration
			ON search_metrics(duration_ms);
	`

	_, err := s.DB.ExecContext(ctx, query)
	if err != nil {
		return fmt.Errorf("failed to create search_metrics table: %w", err)
	}

	return nil
}
