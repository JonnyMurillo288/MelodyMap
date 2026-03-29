"""
Load embeddings from CSV back into database
"""
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config.config import ARTIST_EMBEDDINGS_CSV, DB_URL


def load_embeddings_to_db():
    """
    Load embeddings from CSV into database, creating/replacing table as needed
    """
    print(f"Loading embeddings from {ARTIST_EMBEDDINGS_CSV}...")
    df_emb = pd.read_csv(ARTIST_EMBEDDINGS_CSV)
    
    # Identify embedding columns
    emb_cols = [c for c in df_emb.columns if c.startswith("emb_")]
    cols = ["artist_id"] + emb_cols
    df_emb = df_emb[cols]
    
    # Connect to database
    print("Connecting to database...")
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # Create or replace table with correct schema
            print("Creating/replacing table...")
            emb_col_defs = ",\n        ".join([f"{c} REAL" for c in emb_cols])
            create_table_sql = f"""
            DROP TABLE IF EXISTS artist_embeddings_n2v CASCADE;
            CREATE TABLE artist_embeddings_n2v (
                artist_id INT PRIMARY KEY,
                {emb_col_defs}
            );
            """
            cur.execute(create_table_sql)
            
            # Prepare data for insertion
            records = df_emb.values.tolist()
            
            # Build insert SQL
            insert_cols = ",".join(cols)
            placeholders = ",".join(["%s"] * len(cols))
            insert_sql = f"""
            INSERT INTO artist_embeddings_n2v ({insert_cols})
            VALUES %s
            """
            
            # Execute bulk insert
            print(f"Inserting {len(records)} artist embeddings...")
            execute_values(
                cur,
                insert_sql,
                records,
                page_size=1000
            )
            
    print(f"Successfully loaded {len(records)} artist embeddings")

if __name__ == "__main__":
    load_embeddings_to_db()
