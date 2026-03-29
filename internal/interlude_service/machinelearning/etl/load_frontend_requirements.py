"""
The following Front End Commands will be sent
- User Selects an Artist (A)
- We Return all the neighbors (N1...Nn)
- User can type or search through neighbors (B)
- Then we find if user selected the neighbor exists (B)
    - If the neighbor does not exist, predict A-B link
    - Then we predict Tracks that COULD Link A-B
    
This frontend - backend talk occurst from JS to GO frontend.
But the ETL and Application of the model Occurrs here
"""
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config.config import ARTIST_EMBEDDINGS_CSV, DB_URL


def load_embeddings_to_db():
    """
    Load embeddings from CSV into database
    """
    print(f"Loading embeddings from {ARTIST_EMBEDDINGS_CSV}...")
    df_emb = pd.read_csv(ARTIST_EMBEDDINGS_CSV)

    # Ensure correct column order
    emb_cols = [c for c in df_emb.columns if c.startswith("emb_")]
    cols = ["artist_id"] + emb_cols
    df_emb = df_emb[cols]

    records = df_emb.values.tolist()

    # Build SQL
    insert_cols = ",".join(cols)
    update_clause = ",".join([f"{c}=EXCLUDED.{c}" for c in emb_cols])

    sql = f"""
    INSERT INTO artist_embeddings_n2v ({insert_cols})
    VALUES %s
    ON CONFLICT (artist_id)
    DO UPDATE SET
    {update_clause}
    """

    # Execute
    print("Connecting to database...")
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            print("Inserting/updating embeddings...")
            execute_values(
                cur,
                sql,
                records,
                page_size=1000
            )

    print(f"Inserted/updated {len(records)} artist embeddings")


if __name__ == "__main__":
    load_embeddings_to_db()
