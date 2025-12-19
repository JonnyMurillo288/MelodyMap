# Database Loading for Node2Vec Embeddings

This guide explains how to load embeddings directly from the `artist_embeddings_n2v` PostgreSQL table instead of from a CSV file.

## Why Use Database Loading?

### Advantages
- ✅ **Production-ready**: No need to manage CSV files
- ✅ **Always up-to-date**: Embeddings update when you retrain
- ✅ **Simpler deployment**: One less file to manage
- ✅ **NULL handling**: Gracefully handles missing values
- ✅ **Faster startup**: Direct database query (< 5 seconds)

### CSV vs Database

| Feature | CSV | Database |
|---------|-----|----------|
| **Setup** | Copy file to server | Already in database |
| **Updates** | Manual file replacement | Automatic via SQL |
| **Consistency** | Can get out of sync | Always current |
| **NULL handling** | Requires preprocessing | Built-in |
| **Deployment** | Extra file artifact | No extra files |

## Database Schema

The `artist_embeddings_n2v` table should have this structure:

```sql
CREATE TABLE artist_embeddings_n2v (
    artist_id VARCHAR PRIMARY KEY,
    emb_0 DOUBLE PRECISION,
    emb_1 DOUBLE PRECISION,
    emb_2 DOUBLE PRECISION,
    -- ... (continue through emb_31)
    emb_31 DOUBLE PRECISION
);
```

Your Jupyter notebook already creates this table with:
```python
df_emb.to_csv("/tmp/artist_embeddings.csv", index=False)

# Then insert into database
import psycopg2
from psycopg2.extras import execute_values

DB_URL = "postgres://postgres:password@localhost:5432/musicbrainz_db"

with psycopg2.connect(DB_URL) as conn:
    with conn.cursor() as cur:
        execute_values(cur, sql, records, page_size=1000)
```

## Usage

### Basic Usage

```go
import "github.com/Jonnymurillo288/MelodyMap/internal/search"

func main() {
    // Open database
    store, err := search.Open("")
    if err != nil {
        log.Fatal(err)
    }
    defer store.Close()

    // Load embeddings from database
    err = search.InitEmbeddingsFromDB(store)
    if err != nil {
        log.Fatal(err)
    }

    fmt.Println("Embeddings loaded from database!")
}
```

### With Error Handling

```go
func initializeEmbeddings() error {
    store, err := search.Open("")
    if err != nil {
        return fmt.Errorf("database connection: %w", err)
    }
    defer store.Close()

    if err := search.InitEmbeddingsFromDB(store); err != nil {
        return fmt.Errorf("loading embeddings: %w", err)
    }

    return nil
}

func main() {
    if err := initializeEmbeddings(); err != nil {
        log.Fatalf("Failed to initialize: %v", err)
    }

    // Continue with application...
}
```

### Fallback Strategy

Load from database with CSV fallback:

```go
func initializeEmbeddings() error {
    // Try database first
    store, err := search.Open("")
    if err == nil {
        defer store.Close()
        if err := search.InitEmbeddingsFromDB(store); err == nil {
            fmt.Println("Loaded embeddings from database")
            return nil
        }
        fmt.Printf("Database load failed: %v, trying CSV...\n", err)
    }

    // Fall back to CSV
    if err := search.InitEmbeddings("/tmp/artist_embeddings.csv"); err != nil {
        return fmt.Errorf("both database and CSV loading failed: %w", err)
    }

    fmt.Println("Loaded embeddings from CSV")
    return nil
}
```

## Implementation Details

### Query Structure

The `LoadFromDB` method executes this query:

```sql
SELECT
    artist_id,
    emb_0, emb_1, emb_2, emb_3, emb_4, emb_5, emb_6, emb_7,
    emb_8, emb_9, emb_10, emb_11, emb_12, emb_13, emb_14, emb_15,
    emb_16, emb_17, emb_18, emb_19, emb_20, emb_21, emb_22, emb_23,
    emb_24, emb_25, emb_26, emb_27, emb_28, emb_29, emb_30, emb_31
FROM artist_embeddings_n2v
ORDER BY artist_id
```

### NULL Handling

The implementation uses `sql.NullFloat64` to safely handle NULL values:

```go
nullFloats := make([]sql.NullFloat64, es.dimension)

// Scan with NULL handling
rows.Scan(scanDest...)

// Convert, using 0.0 for NULL
for i := 0; i < es.dimension; i++ {
    if nullFloats[i].Valid {
        embedding[i] = nullFloats[i].Float64
    } else {
        embedding[i] = 0.0  // Default for missing values
    }
}
```

### Performance

Loading 583K embeddings:
- **Query time**: ~2-3 seconds
- **Memory allocation**: ~150 MB
- **Parsing**: ~1-2 seconds
- **Total**: ~5 seconds

Compared to CSV:
- **CSV parsing**: ~3-5 seconds
- **Similar performance**, no significant difference

### Thread Safety

Both `LoadFromDB` and `LoadFromCSV` use mutex locks:

```go
func (es *EmbeddingStore) LoadFromDB(store *Store) error {
    es.mu.Lock()
    defer es.mu.Unlock()

    // Safe concurrent access during load
}
```

## Testing

### Unit Tests

```bash
# Run quick tests (skip database integration)
go test ./internal/search -short

# Run integration tests (requires database)
go test ./internal/search -v
```

### Integration Test

Test database loading:

```go
func TestLoadFromDB(t *testing.T) {
    if testing.Short() {
        t.Skip("Skipping integration test")
    }

    store, err := search.Open("")
    if err != nil {
        t.Skipf("Database not available: %v", err)
    }
    defer store.Close()

    es := search.NewEmbeddingStore()
    err = es.LoadFromDB(store)
    if err != nil {
        t.Fatalf("LoadFromDB failed: %v", err)
    }

    if len(es.embeddings) == 0 {
        t.Error("No embeddings loaded")
    }
}
```

### Example Program

Run the database example:

```bash
# Make sure database is running
go run cmd/astar-example/main_db.go
```

## Production Deployment

### Application Startup

In [main/main.go](../main/main.go):

```go
func main() {
    // Initialize database
    store, err := search.Open("")
    if err != nil {
        log.Fatalf("Database connection failed: %v", err)
    }

    // Load embeddings at startup
    fmt.Println("Loading Node2Vec embeddings from database...")
    if err := search.InitEmbeddingsFromDB(store); err != nil {
        log.Printf("Warning: Failed to load embeddings: %v", err)
        log.Println("A* search will not be available")
    } else {
        fmt.Println("✓ Embeddings loaded successfully")
    }

    // Keep store open for application lifetime
    // (or close and reopen per request)

    // ... rest of application
}
```

### Health Check

Add a health check endpoint:

```go
func HandleHealthCheck(w http.ResponseWriter, r *http.Request) {
    health := map[string]interface{}{
        "status": "ok",
        "embeddings_loaded": search.GlobalEmbeddingStore != nil,
    }

    if search.GlobalEmbeddingStore != nil {
        health["embedding_count"] = len(search.GlobalEmbeddingStore.embeddings)
        health["embedding_dimension"] = search.GlobalEmbeddingStore.dimension
    }

    json.NewEncoder(w).Encode(health)
}
```

### Monitoring

Log embedding stats on load:

```go
if search.GlobalEmbeddingStore != nil {
    count := len(search.GlobalEmbeddingStore.embeddings)
    dim := search.GlobalEmbeddingStore.dimension

    log.Printf("Embeddings ready: %d artists × %d dimensions", count, dim)

    // Send to metrics system
    metrics.Gauge("embeddings.count", count)
    metrics.Gauge("embeddings.dimension", dim)
}
```

## Updating Embeddings

### Retrain and Update

1. **Retrain in Jupyter**:
   ```bash
   cd acousticbrainz
   jupyter notebook embeddings.ipynb
   # Run all cells
   ```

2. **Database automatically updated**:
   The notebook uses `ON CONFLICT DO UPDATE`, so the table is updated in place:
   ```python
   sql = f"""
   INSERT INTO artist_embeddings_n2v ({insert_cols})
   VALUES %s
   ON CONFLICT (artist_id)
   DO UPDATE SET {update_clause}
   """
   ```

3. **Restart application**:
   ```bash
   systemctl restart melodymap
   ```

Embeddings are reloaded on startup!

### Hot Reload (Advanced)

To reload without restarting:

```go
func HandleReloadEmbeddings(w http.ResponseWriter, r *http.Request) {
    // Require admin authentication
    if !isAdmin(r) {
        http.Error(w, "Unauthorized", 401)
        return
    }

    store, err := search.Open("")
    if err != nil {
        http.Error(w, "Database error", 500)
        return
    }
    defer store.Close()

    if err := search.InitEmbeddingsFromDB(store); err != nil {
        http.Error(w, err.Error(), 500)
        return
    }

    w.Write([]byte("Embeddings reloaded successfully"))
}
```

## Troubleshooting

### "Table does not exist"

**Problem**: `ERROR: relation "artist_embeddings_n2v" does not exist`

**Solution**: Run the Jupyter notebook to create and populate the table.

### "No embeddings loaded"

**Problem**: Table exists but is empty.

**Solution**: Check the notebook completed successfully:
```sql
SELECT COUNT(*) FROM artist_embeddings_n2v;
-- Should return ~583,000
```

### "Failed to scan embedding row"

**Problem**: Column type mismatch.

**Solution**: Verify column types:
```sql
\d artist_embeddings_n2v
-- All emb_* columns should be DOUBLE PRECISION or REAL
```

### Performance Issues

**Problem**: Loading takes > 30 seconds.

**Solution**: Add index on artist_id (should already be PRIMARY KEY):
```sql
CREATE INDEX IF NOT EXISTS idx_artist_embeddings_artist_id
ON artist_embeddings_n2v(artist_id);
```

## API Reference

### Functions

#### `LoadFromDB`
```go
func (es *EmbeddingStore) LoadFromDB(store *Store) error
```
Loads embeddings from `artist_embeddings_n2v` table.

**Parameters**:
- `store`: Database connection

**Returns**: Error if loading fails

**Example**:
```go
es := search.NewEmbeddingStore()
err := es.LoadFromDB(store)
```

#### `InitEmbeddingsFromDB`
```go
func InitEmbeddingsFromDB(store *Store) error
```
Convenience function to initialize global embedding store from database.

**Parameters**:
- `store`: Database connection

**Returns**: Error if loading fails

**Example**:
```go
store, _ := search.Open("")
search.InitEmbeddingsFromDB(store)
```

## Migration from CSV

To migrate from CSV to database loading:

1. **Current code** (CSV):
   ```go
   search.InitEmbeddings("/tmp/artist_embeddings.csv")
   ```

2. **New code** (Database):
   ```go
   store, _ := search.Open("")
   search.InitEmbeddingsFromDB(store)
   ```

3. **Remove CSV file dependency** from deployment scripts

4. **Update documentation** to reflect database loading

That's it! No other changes needed.

## Summary

- ✅ Load embeddings directly from PostgreSQL
- ✅ Simpler than CSV file management
- ✅ NULL-safe with `sql.NullFloat64`
- ✅ Same performance as CSV (~5 seconds)
- ✅ Production-ready with error handling
- ✅ Easy to update (just retrain + restart)

**Recommended for production deployments!**
