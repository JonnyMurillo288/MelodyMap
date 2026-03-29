'''
Test the following Feature Engineering Feature Engineering (6 files)
- `features/build_features.py` - Core feature engineering functions
- `features/sampling.py` - Data sampling utilities (positive/negative sampling)
- `features/pipeline_hops.py` - Hop prediction feature pipeline
- `features/pipeline_links.py` - Link prediction feature pipeline
- `features/__init__.py` - Module exports
'''
import unittest
import pandas as pd
from utils.database import get_pg_conn, get_artist_collab
from config.config import ARTIST_EDGES_CSV, NODE2VEC_DIM

artist_edges_df = pd.read_csv(ARTIST_EDGES_CSV)
conn = get_pg_conn()

class TestStringMethods(unittest.TestCase):

    def test_last_fm_shape(self):
        q = """
        select count(*) from lastfm_artist_stats;
        """
        self.assertGreater(pd.read_sql_query(q),10000)
        q = """
        select * from lastfm_artist_stats limit 2;
        """
        self.assertEquals(pd.read_sql_query(q).shape[1],NODE2VEC_DIM+1) # Add 1 for the artist_id column


if __name__ == '__main__':
    unittest.main()
    conn.close()