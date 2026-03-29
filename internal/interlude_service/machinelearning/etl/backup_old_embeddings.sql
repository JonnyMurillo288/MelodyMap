-- This file will backup the old embeddings before we run the new embedding pipeline. 
-- This is a precautionary measure to ensure that we have a copy of the old embeddings in case anything goes wrong with the new pipeline.

-- The productiono database table is `artist_embeddings_n2v` 
-- Backup table will be `artist_embeddings_n2v_backup`

create table artist_embeddings_n2v_backup as artist_embeddings_n2v;

truncate table artist_embeddings_n2v;