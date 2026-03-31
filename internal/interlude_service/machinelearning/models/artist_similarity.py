"""This module contains the ArtistSimilarity model.
It calculates the similarity between artists based on their genre distribution embeddings
using the Aitchison distance metric.

Flow
1. Input: A source artist (or set of source artists) with genre distribution embeddings,
   and a set of candidate artists with their genre distribution embeddings.
2. Similarity Calculation: For each source artist, calculate the Aitchison distance
   to every candidate artist based on their genre distributions.
3. Output: A dictionary mapping each source artist to a sorted list of
   (candidate_artist_id, aitchison_score) tuples.
"""
from time import time

import numpy as np
import pandas as pd

from config.config import GENRE_TYPE_CLASSIFICATION
from features.pipeline_links import genre_type_proportions_column_names,get_genre_proportions_from_artist_list
from models.track_similarity import aitchison


class ArtistSimilarity:
    def __init__(
        self,
        source_artists: pd.DataFrame,
        candidate_artists: pd.DataFrame,
        genre_type: str | None = None,
    ):
        """
        Args:
            source_artists (pd.DataFrame): DataFrame with an 'artist_id' column and
                genre proportion columns for the source artist(s).
            candidate_artists (pd.DataFrame): DataFrame with an 'artist_id' column and
                genre proportion columns for the candidate artists to compare against.
            genre_type (str | None): Which genre classification to use
                ('dortmund', 'electronic', 'rosamerica', 'tzanetakis').
                Defaults to GENRE_TYPE_CLASSIFICATION from config.
        """
        self.genre_type = genre_type or GENRE_TYPE_CLASSIFICATION
        self.genre_cols = genre_type_proportions_column_names(self.genre_type)
        self.source_artists = get_genre_proportions_from_artist_list(source_artists.artist_id)
        self.candidate_artists = get_genre_proportions_from_artist_list(candidate_artists.artist_id)

        # self.source_artists = source_artists
        # self.candidate_artists = candidate_artists

        self.genre_scores = self.calculate_aitchison_scores(
            self.source_artists, self.candidate_artists
        )
        # self.sorted_genre_scores = self.sort_similarity_scores(
        #     self.genre_scores, method="ascending"
        # )

    def calculate_aitchison_scores(
        self,
        source_artists: pd.DataFrame,
        candidate_artists: pd.DataFrame,
    ) -> dict:
        """
        Calculate Aitchison distance scores between source artists and candidate artists
        based on their genre distribution embeddings.

        Args:
            source_artists (pd.DataFrame): DataFrame containing genre proportions for
                source artists. Must include 'artist_id' and the genre proportion columns.
            candidate_artists (pd.DataFrame): DataFrame containing genre proportions for
                candidate artists. Must include 'artist_id' and the genre proportion columns.

        Returns:
            dict: A dictionary in the format:
            {
                source_artist_id_1: [(candidate_id_1, score_1), (candidate_id_2, score_2), ...],
                source_artist_id_2: [(candidate_id_3, score_3), ...],
                ...
            }
        """
        print(f"Calculating Aitchison scores for {len(source_artists)} source artists "
              f"against {len(candidate_artists)} candidates using '{self.genre_type}' genre type.")

        # Use the prop_ prefixed columns from artist_genre_proportions table
        prop_cols = [f"prop_{g}" for g in self.genre_cols]

        # Determine which columns are actually present in the dataframes
        available_src = [c for c in prop_cols if c in source_artists.columns]
        available_cand = [c for c in prop_cols if c in candidate_artists.columns]

        # Fall back to the raw genre column names if prop_ columns aren't present
        if not available_src:
            available_src = [c for c in self.genre_cols if c in source_artists.columns]
        if not available_cand:
            available_cand = [c for c in self.genre_cols if c in candidate_artists.columns]

        # Use the intersection so both sides have matching columns
        cols = sorted(set(available_src) & set(available_cand))
        if not cols:
            raise ValueError(
                f"No matching genre columns found between source and candidate DataFrames. "
                f"Expected columns like {prop_cols[:3]}... or {self.genre_cols[:3]}..."
            )

        similarity_scores = {}
        start_time = time()

        # Pre-extract candidate matrix for vectorised inner loop
        cand_ids = candidate_artists['artist_id'].values
        cand_matrix = candidate_artists[cols].values

        for _, src_row in source_artists.iterrows():
            src_id = src_row['artist_id']
            src_dist = src_row[cols].values

            for j, cand_id in enumerate(cand_ids):
                score = aitchison(src_dist, cand_matrix[j])
                similarity_scores[(src_id, cand_id)] = score

        elapsed = time() - start_time
        print(f"Aitchison score calculation took {elapsed:.2f} seconds.")

        return similarity_scores

    def sort_similarity_scores(
        self, similarity_scores: dict, method: str = "ascending"
    ) -> dict:
        """
        Sort the similarity scores for each source artist.

        Args:
            similarity_scores (dict): Aitchison scores produced by calculate_aitchison_scores.
            method (str): 'ascending' (most similar first, lowest distance) or 'descending'.

        Returns:
            dict: Sorted version of the input dictionary.
        """
        reverse = method == "descending"
        return {
            src_id: sorted(scores, key=lambda x: x[1], reverse=reverse)
            for src_id, scores in similarity_scores.items()
        }
