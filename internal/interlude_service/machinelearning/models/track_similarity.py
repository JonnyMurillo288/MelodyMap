"""This module contains the TrackSimilarity model, 
It's used to calculate the similarity between two tracks based on their features.

The model uses a combination of features including:
- Atchison distance between track Genre distributions
- Popularity of the tracks
- One-hop neighborhood features (e.g., cosine similarity with neighbors)
- Two-hop neighborhood features (e.g., shared neighbors, Jaccard similarity)


Flow 
1. Data Preparation: The model takes in a dataset of track pairs along with their features.
2. Feature Extraction: The model extracts relevant features for each track pair, including genre similarity, popularity, and neighborhood features.
3. Similarity Calculation: The model calculates a similarity score for each track pair based on the extracted features.
4. Output: The model outputs a similarity score for each track pair, which can be used for various applications such as recommendation systems, playlist generation, etc.

0. Inputs:
    - [(src_artist_id_1, dst_artist_id_1, synthetic_track_id_1), ...2...3...]
1. Data Preparation:
     - The model will take in a dataset of src-dst-synthetic track pairs
2. Feature Extraction:
     - For each track pair, the model will extract the following features:
          - Synthetic Track High Level Features
          - One-hop neighborhood features (e.g., cosine similarity with neighbors)
          - Two-hop neighborhood features (e.g., shared neighbors, Jaccard similarity)
3. Similarity Calculation:
     - The model will calculate a similarity score for each track pair based on the extracted features.
4. Output:
     - Model will find tracks from high-level-track-features that are most similar to each synthetic track
     - {synthetic_track: [(similar_track_1, similarity_score_1), (similar_track_2, similarity_score_2), ...]}
"""
from time import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import numpy as np
import pandas as pd
from scipy.spatial.distance import norm
from config.config import GENRE_TYPE_CLASSIFICATION
from features.pipeline_links import genre_type_proportions_column_names
from utils import get_pg_conn




class TrackSimilarity:
    def __init__(self, frontend_inputs: list | None):
        if frontend_inputs is None:
            frontend_inputs = []
        self.inputs = frontend_inputs
        self.synthetic_features, self.neighbor_features = self.extract_features(self.inputs.input_tracks,depth_neighbors=0)
        
        # Now that we extracted the features, calculate the similarity scores for each synthetic track and its neighbors
        self.genre_scores = self.calculate_aitchson_scores_for_tracks(self.synthetic_features, self.neighbor_features)
        self.sorted_genre_scores = self.sort_similarity_scores(self.genre_scores, method="ascending")
        
        # TODO: After the genre scores, get the cosine similarity scores for the one-hop neighbors and the two-hop neighborhood features
        # This will be used in the final similarity calculation for the synthetic track and its neighbors
        # RIGHT NOW NOT USING THE NEIGHBORHOOD FEATURES, JUST THE GENRE SIMILARITY SCORE (AITCHISON DISTANCE)
        
    def extract_features(self, synth_track_ids, depth_neighbors: int = 0) -> pd.DataFrame:
        """
        Extract features for synthetic tracks and their neighborhood tracks.

        Args:
            synth_track_ids (list): A list of synthetic track IDs for which to extract features.
            depth_neighbors (int): The depth of neighbors to consider. Default is 0 (direct neighbors only).

        Returns:
            2 pd.DataFrame:
                - A DataFrame containing the features for the synthetic tracks.
                - A DataFrame containing the features for the neighborhood tracks.
        """
        print(f"Extracting features for synthetic track ids: {synth_track_ids} with depth_neighbors: {depth_neighbors}")

        conn = get_pg_conn()
        try:
            # 1. Batch lookup all track pairs in one query
            track_pairs_q = """
            SELECT track_id, src_artist_id, dst_artist_id
            FROM synthetic_tracks
            WHERE track_id = ANY(%s::int[])
            """
            track_pairs_df = pd.read_sql(track_pairs_q, conn, params=(synth_track_ids,))
            print(f"Extracted track pairs:\n{track_pairs_df}")

            tracks = [int(t) for t in track_pairs_df['track_id']]

            # 2. Get synthetic features for all tracks at once
            synth_q = """
            SELECT *
            FROM synthetic_tracks_high_level_features
            WHERE track_id = ANY(%s::int[])
            """
            synth_features = pd.read_sql(synth_q, conn, params=(tracks,))
            synth_features = synth_features.drop(columns=['prob'])
        finally:
            conn.close()

        # 3. Get neighbor features per unique (src, dst) pair — run concurrently
        unique_pairs = track_pairs_df[['src_artist_id', 'dst_artist_id']].drop_duplicates()
        src = [int(row['src_artist_id']) for _, row in unique_pairs.iterrows()][0]
        pairs_list = [src] + [(int(row['dst_artist_id'])) for _, row in unique_pairs.iterrows()]

        print(f"Running {len(pairs_list)} neighbor queries concurrently...")
        print("First pairs_list[:5]:", pairs_list[:5])
        start = time()

        unique_artist_ids = list(set(pairs_list))

        c = get_pg_conn()
        try:
            q = """
            WITH arts AS (
            SELECT DISTINCT neighbor_artist_id AS id
            FROM artist_collab
            WHERE artist_id = ANY(%s::int[])
            UNION
            SELECT DISTINCT artist_id AS id
            FROM artist_collab
            WHERE neighbor_artist_id = ANY(%s::int[])
        ),
        arts_tracks AS (
            SELECT DISTINCT rtr.recording_id AS rid
            FROM l_artist_recording lar
            JOIN recording_to_release rtr
                ON lar.entity1 = rtr.recording_id
            WHERE lar.entity0 IN (SELECT id FROM arts)
            AND rtr.release_status = 1  -- only official releases
        )
        SELECT *
        FROM high_level_track_audio_features
        WHERE recording_id IN (SELECT rid FROM arts_tracks)
            """

            hlf_features = pd.read_sql(q, c, params=(unique_artist_ids, unique_artist_ids))

        finally:
            c.close()

        hlf_features = (
            hlf_features
            .drop_duplicates(subset=['recording_id'])
            .rename(columns={'recording_id': 'track_id'})
        )

        print(f"Neighbor feature query took {time() - start:.2f}s")

        matching_cols = list(set(synth_features.columns).intersection(set(hlf_features.columns)))
        synth_features = synth_features[matching_cols]
        hlf_features = hlf_features[matching_cols]

        return synth_features, hlf_features

    def calculate_aitchson_scores_for_tracks(self, synthetic_features: pd.DataFrame, neighbor_features: pd.DataFrame) -> dict:
        """
        Calculate aitchson scores for the synthetic track to the tracks that exist.

        Args:
            synthetic_features (pd.DataFrame): A DataFrame containing the features for the synthetic track.
            neighbor_features (pd.DataFrame): A DataFrame containing the features for the src and dst artists tracks along with their neighbors.
        
        Returns:
            dict: A dictionary containing the similarity scores for the synthetic track and its neighbors.
        The dictionary will be in the format:
        
        {
            synthetic_track_id_1: [(neighbor_track_id_1, similarity_score_1), (neighbor_track_id_2, similarity_score_2), ...],
            synthetic_track_id_2: [(neighbor_track_id_3, similarity_score_3), (neighbor_track_id_4, similarity_score_4), ...],
            ...
        }   
        """
        print(f"Calculating Aitchison scores for synthetic tracks and their neighbors.")
        # For each synthetic track, calculate the Aitchison distance to each of the neighbor tracks based on their genre distributions
        similarity_scores = {}
        # Big O(n*m) where n is the number of synthetic tracks and m is the number of neighbor tracks.
        # Can we reduce this?
        start_time = time()
        for idx, synth_row in synthetic_features.iterrows():
            synth_track_id = synth_row['track_id']
            # The question here is do we want to only look at one genre distribution 
            # Or do we look at all genre distributions?
            
            gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
            synth_genre_dist = synth_row[gt].values
            similarity_scores[synth_track_id] = []
            
            for idx, neighbor_row in neighbor_features.iterrows():
                neighbor_track_id = neighbor_row['track_id']
                neighbor_genre_dist = neighbor_row[gt].values
                
                # Calculate Aitchison distance between the synthetic track and the neighbor track
                score = aitchison(synth_genre_dist, neighbor_genre_dist)
                similarity_scores[synth_track_id].append((neighbor_track_id, score))
        
        end_time = time()
        elapsed_time = end_time - start_time
        print(f"Aitchison score calculation took {elapsed_time:.2f} seconds.")
        
        return similarity_scores
    
    def sort_similarity_scores(self, similarity_scores: dict, method: str = "ascending") -> dict:
        """
        Sort the similarity scores for each synthetic track in ascending order (most similar first).

        Args:
            similarity_scores (dict): A dictionary containing the similarity scores for the synthetic track and its neighbors.
            method (str): The method to sort the similarity scores. Default is "ascending". Can also be "descending".
                "Ascending" means that the most similar tracks (lowest Aitchison distance) will be first, 
        Returns:
            dict: A dictionary containing the sorted similarity scores for the synthetic track and its neighbors.
        The dictionary will be in the format:
        {
            synthetic_track_id_1: [(neighbor_track_id_1, similarity_score_1), (neighbor_track_id_2, similarity_score_2), ...],
            synthetic_track_id_2: [(neighbor_track_id_3, similarity_score_3), (neighbor_track_id_4, similarity_score_4), ...],
            ...
        }   
        """
        sorted_similarity_scores = {}
        for synth_track_id, neighbor_scores in similarity_scores.items():
            sorted_neighbor_scores = sorted(neighbor_scores, key=lambda x: x[1])  # Sort by similarity score (ascending)
            sorted_similarity_scores[synth_track_id] = sorted_neighbor_scores
        return sorted_similarity_scores
    
    
def _replace_zeros(w, eps=1e-10):
    """Replace zeros and NaNs with a small epsilon and renormalize to maintain composition."""
    w = np.where((w == 0) | np.isnan(w), eps, w)
    w = w / w.sum()
    return w

def _validate_aitchison(w, u_v):
    if np.any(w[~np.isnan(w)] < 0):
        raise ValueError('Values in %s should be non-negative.' % u_v)
    return(w)

def _validate_vector(v):
    v = np.asarray(v, dtype=np.float64)
    if v.ndim != 1:
        raise ValueError('Input should be a 1-D array.')
    return(v)

def aitchison(u, v):
    """
    Computes the Aitchison distance between two 1-D arrays.
    The Aitchison distance between 1-D arrays `u` and `v`, is defined as
    .. math::
       {||log \left( \frac{u}{v} \right) - mean \left(log \left( \frac{u}{v} \right) \right) ||}_2
       
    Parameters
    ----------
    u : (N,) array_like
        Input array.
    v : (N,) array_like
        Input array.
    Returns
    -------
    aitchison : double
        The Aitchison distance between vectors `u` and `v`.
    """
    
    u = _validate_vector(u)
    v = _validate_vector(v)
    _validate_aitchison(u, 'u')
    _validate_aitchison(v, 'v')
    u = _replace_zeros(u)
    v = _replace_zeros(v)
    log_u_v = np.log(u / v)
    dist = norm(log_u_v - np.mean(log_u_v))
    return(dist)

