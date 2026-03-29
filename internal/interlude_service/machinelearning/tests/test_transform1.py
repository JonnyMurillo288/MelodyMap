'''
Testing for the Tranform functions that happen BEFORE Loading 
- Embeddings
'''
import unittest
import pandas as pd
from utils.database import get_pg_conn, get_artist_collab
from config.config import ARTIST_EDGES_CSV

artist_edges_df = pd.read_csv(ARTIST_EDGES_CSV)
conn = get_pg_conn()

class TestStringMethods(unittest.TestCase):

    def test_artist_edge_cols(self):
        self.assertGreater(artist_edges_df.shape[1],2)
        
    def test_artist_edge_rows(self):
        self.assertGreater(artist_edges_df.shape[0],10000)
        
    def test_last_fm_shape(self):
        q = """
        select count(*) from artist_embeddings_n2v;
        """
        self.assertGreater(pd.read_sql_query(q),10000)
        q = """
        select * from artist_embeddings_n2v limit 2;
        """
        self.assertGreater(pd.read_sql_query(q).shape[1],6)


if __name__ == '__main__':
    unittest.main()
    conn.close()