"""
Feature engineering pipeline for link prediction
"""
import pandas as pd
from utils.database import (
    get_pg_conn,
    get_artist_collab,
    get_artist_embeddings,
    get_artist_k_neighbors_full_random
)
from features.build_features import (
    build_embedding_lookup,
    build_neighbors_dict,
    build_features_for_pairs
)
from features.sampling import get_training_test
from config.config import ARTIST_COLLAB_NEG_CSV, FEATURE_GROUPS, PREDICTION_EMBEDDINGS_CSV, GENRE_TYPE_CLASSIFICATION, LINK_PREDICTION_FEATURES


def get_id_from_mbid(artist_id: str) -> int:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT id
        FROM artist
        WHERE gid = %s::uuid;
    """
    # print(f"Getting {artist_id}")

    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    try:
        res = df['id'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for ID from MBID not successful, there is no rows in the dataframe")
    
    return res


def build_link_prediction_embeddings_from_artist_list(
    artist_list: list,
) -> pd.DataFrame:
    
    """
    Build the embeddings DataFrame for the link predictions.
    This takes in link predictions (src,dst) and returns the embeddings summary features
    OR: the context (C) used as an input to the CVAE model
    
    TODO: Allow the user to input which context variables to get specifically.
    
    Parameters 
    ----------
    artist_list : list of tuples
        Input the list of prediction connections from our Logistic Regression model 
        MBID
    Returns 
    ----------
    pd.DataFrame
        The src,dst, and context variables used in CVAE
    """
    
    # Check correct input type
    if type(artist_list[0]) != tuple and len(artist_list) == 0:
        raise TypeError(f"Incorrect input type for artist list: {type(artist_list[0])} should be type Tuple")
    
    # Get the embeddings for each artist,
    
    artist_ids = [i[0] for i in artist_list] + [i[1] for i in artist_list]
    artist_ids = set(artist_ids)
    # print(artist_list[0])
    
    conn = get_pg_conn()
    embeddings = get_artist_embeddings(conn, artist_ids)

    # print("Sampling k neighbors for each artist...")
    # neighbors_src = get_artist_k_neighbors_full_random(conn, df.src.tolist(), k=3)
    # neighbors_dst = get_artist_k_neighbors_full_random(conn, df.dst.tolist(), k=3)
    # artist_collab_3 = pd.concat([neighbors_src, neighbors_dst])

    # Single database call
    artist_collab_3 = get_artist_k_neighbors_full_random(conn, artist_id=artist_ids, k=3)
    artist_collab_3 = artist_collab_3.rename(
        columns={
            artist_collab_3.columns[0]: "src",
            artist_collab_3.columns[1]: "dst",
        }
    )
    
    # print("Building embedding lookup...")
    embeddings = embeddings.loc[:, ~embeddings.columns.duplicated()] #TODO: FIX ROOT PROBLEM OF THIS 
    embedding_lookup = build_embedding_lookup(embeddings)

    # print("Building neighbors dictionary...")
    neighbors = build_neighbors_dict(artist_collab_3)
    artist_id_converted_list = [(i[0],i[1]) for i in artist_list]
    df = pd.DataFrame(artist_id_converted_list,columns = ['src','dst'])

    # print(f"Building features for {len(artist_list)} pairs...")
    # print(f"[DEBUG]: embedding_lookup:",[(k,v) for k,v in embedding_lookup.items()])
    df_features = build_features_for_pairs(
        pairs_df=df,
        embedding_lookup=embedding_lookup,
        neighbors=neighbors,
        target_col='label',
        topk=3,
        verbose=True
    )
    # LINK_PREDICTION_FEATURES = list(set(LINK_PREDICTION_FEATURES))

    # print(f"Generated {len(df_features)} feature rows")
    
    # Here we will input the genre similarity features if available
    # print("Fetching genre proportions for artists...")
    genre_df = get_genre_proportions_from_artist_list(list(artist_ids))
    print("[DEBUG] df_features dataframe columns:", df_features.columns)
    
    # Since the genre features will be so correlated if we had all 4 groups (dortmund, electronic, rosamerica, tzanetakis)
    # We are goin to make the user choose which group to use for the similarity features
    # Set in the config but 
    if not genre_df.empty:
        # print("Calculating genre similarity features...")
        src_df = df_features[['src']].merge(genre_df, left_on='src', right_on='artist_id', how='left')
        dst_df = df_features[['dst']].merge(genre_df, left_on='dst', right_on = 'artist_id', how='left')
        src_df = src_df.drop(columns=['artist_id']).rename(columns={'src_x':'src'})
        dst_df = dst_df.drop(columns=['artist_id']).rename(columns={'dst_x':'dst'})
        # Now we will subtract the genre proportions to get similarity
        res = pd.DataFrame(src_df.iloc[:,1:].to_numpy() - dst_df.iloc[:,1:].to_numpy(),columns=dst_df.columns[1:])
        res['src'] = df_features['src']
        res['dst'] = df_features['dst']
        
        gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
        gt = ["similarity_prop_" + i for i in gt]
        # print(f"Genre Type Proportions features: {gt}")
        FEATURE_GROUPS['genre_similarity'] = gt[1:]
        # Guard: only extend if not already present (list is global and mutates on each call)
        for f in gt[1:]:
            if f not in LINK_PREDICTION_FEATURES:
                LINK_PREDICTION_FEATURES.append(f)
        
        
        # Now rename to similarity features for our model
        for col in res.columns:
            # print("Merging genre similarity features with main feature dataframe...\n",res.columns)
            if col not in ['src','dst']:
                res = res.rename(columns={col: f"similarity_{col}"})
                # print("Renamed column", col, "to", f"similarity_{col}")
        res = res[['src','dst'] + gt[1:]]
        # print("Genre similarity features calculated. Sample:\n", res.head())
        df_features = df_features.merge(res, on=['src','dst'], how='left')
    # print("Added genre similarity features to dataset.")
    # print("[DEBUG] Final feature columns:", df_features.columns.tolist())
    # print("genre similarity features added:", [col for col in df_features.columns if col.startswith("similarity_")])

    return df_features

def get_id_from_mbid(artist_id: str) -> int:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT id
        FROM artist
        WHERE gid = %s::uuid;
    """
    # print(f"Getting {artist_id}")

    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    try:
        res = df['id'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for ID from MBID not successful, there is no rows in the dataframe")
    
    return res

def build_link_prediction_features_from_input_artist(
    input_artist_id: str | int,
    num_candidates: int = 10000,
) -> pd.DataFrame:
    """
    Build the embeddings DataFrame for the link predictions.
    """
    conn = get_pg_conn()
    if type(input_artist_id) == str:
        input_artist_id = get_id_from_mbid(input_artist_id)
    input_artist_id = int(input_artist_id)
    src = input_artist_id
    
    # Step 1: Get the source artist's popularity
    target_pop_query = """
        SELECT las.popularity_score
        FROM artist a
        JOIN lastfm_artist_stats las ON a.gid = las.artist_mbid
        WHERE a.id = %s
    """
    target_pop = pd.read_sql_query(target_pop_query, conn, params=(input_artist_id,))
    print(f"Target popularity data for artist {src}:", target_pop)
    
    # Fallback if no popularity data
    if target_pop.empty or pd.isna(target_pop['popularity_score'].iloc[0]):
        print(f"No popularity data for artist {src}, using fallback random selection")
        fallback_query = """
            SELECT DISTINCT a.id as dst
            FROM artist a
            WHERE a.id != %s
              AND NOT EXISTS (
                  SELECT 1 FROM artist_collab ac 
                  WHERE (ac.artist_id = %s AND ac.neighbor_artist_id = a.id)
                     OR (ac.artist_id = a.id AND ac.neighbor_artist_id = %s)
              )
            ORDER BY RANDOM()
            LIMIT %s
        """
        res = pd.read_sql_query(fallback_query, conn, params=(input_artist_id, input_artist_id, input_artist_id, num_candidates))
    else:
        target_score = float(target_pop['popularity_score'].iloc[0])
        
        # Step 2: Get artists with similar popularity, excluding existing collabs
        q = """
            SELECT a.id as dst,
                   CASE 
                       WHEN las.popularity_score IS NOT NULL 
                       THEN ABS(las.popularity_score - %s)
                       ELSE 999999
                   END as pop_diff
            FROM artist a
            LEFT JOIN lastfm_artist_stats las ON a.gid = las.artist_mbid
            WHERE a.id != %s
              AND NOT EXISTS (
                  SELECT 1 FROM artist_collab ac 
                  WHERE (ac.artist_id = %s AND ac.neighbor_artist_id = a.id)
                     OR (ac.artist_id = a.id AND ac.neighbor_artist_id = %s)
              )
            ORDER BY pop_diff ASC
            LIMIT %s
        """
        res = pd.read_sql_query(
            q, 
            conn, 
            params=(target_score, input_artist_id, input_artist_id, input_artist_id, num_candidates)
        )
        # Drop the temporary ordering column
        res = res[['dst']]
    
    print(f"Candidate artists for artist {src}:", len(res))
    conn.close()
    
    # Add source column
    res['src'] = src
    
    # Ensure we have enough results
    if len(res) < num_candidates:
        print(f"Warning: Only found {len(res)} candidates, supplementing with random artists")
        supplement_query = """
            SELECT a.id as dst
            FROM artist a
            WHERE a.id != %s
              AND a.id NOT IN %s
              AND NOT EXISTS (
                  SELECT 1 FROM artist_collab ac 
                  WHERE (ac.artist_id = %s AND ac.neighbor_artist_id = a.id)
                     OR (ac.artist_id = a.id AND ac.neighbor_artist_id = %s)
              )
            ORDER BY RANDOM()
            LIMIT %s
        """
        existing_dsts = tuple(res['dst'].tolist()) if len(res) > 0 else (-1,)
        conn2 = get_pg_conn()
        supplement = pd.read_sql_query(
            supplement_query, 
            conn2, 
            params=(input_artist_id, existing_dsts, input_artist_id, input_artist_id, num_candidates - len(res))
        )
        conn2.close()
        supplement['src'] = src
        res = pd.concat([res, supplement], ignore_index=True)
    
    print(f"Final candidate count: {len(res)}")
    print(res.head())
    return res


def calculate_genre_similarity_features(
    list_of_genre_proportions: list,
    src_genres: pd.DataFrame,
    dst_genres: pd.DataFrame,
) -> dict:
    """
    Need to pass through the following
    src1 [ 1 1 1 1 0 0 0 0 ... ] and dst1 [0 0 0 0 1 1 1 1 ...]
    then 
    src2 [ 0 1 0 1 0 1 0 1 ... ] and dst2 [1 0 1 0 1 0 1 0 ...]
    etc for each genre proportion column
    
    
    THIS IS NOT IN PRODUCTION YET - WORK IN PROGRESS
    WILL RETURN WHEN THERE IS A NEED TO DO
    Returns the similarity score between two artists based on their genre proportions.
    Parameters
    ----------
        src_genres : pd.DataFrame
            List of genres proportions for source artist
        dst_genres : pd.DataFrame
            List of genres proportions for destination artist
            Dortmund                      Electronic                    Rosamerica                    Tzanetakis
    genre_dortmund_alternative    genre_electronic_ambient      genre_rosamerica_cla          genre_tzanetakis_blu
    genre_dortmund_blues          genre_electronic_dnb          genre_rosamerica_dan          genre_tzanetakis_cla
    genre_dortmund_electronic     genre_electronic_house        genre_rosamerica_hip          genre_tzanetakis_cou
    genre_dortmund_folkcountry    genre_electronic_techno       genre_rosamerica_jaz          genre_tzanetakis_dis
    genre_dortmund_funksoulrnb    genre_electronic_trance       genre_rosamerica_pop          genre_tzanetakis_hip
    genre_dortmund_jazz                                         genre_rosamerica_rhy          genre_tzanetakis_jaz
    genre_dortmund_pop                                          genre_rosamerica_roc          genre_tzanetakis_met
    genre_dortmund_raphiphop                                    genre_rosamerica_spe          genre_tzanetakis_pop
    genre_dortmund_rock                                                                       genre_tzanetakis_reg


    Returns
    -------
        dict
            Dictionary of genre similarity features
    """
    
    if not list_of_genre_proportions:
        list_of_genre_proportions = [
            # Dortmund genres
            'genre_dortmund_alternative',
            'genre_dortmund_blues',
            'genre_dortmund_electronic',
            'genre_dortmund_folkcountry',
            'genre_dortmund_funksoulrnb',
            'genre_dortmund_jazz',
            'genre_dortmund_pop',
            'genre_dortmund_raphiphop',
            'genre_dortmund_rock',
            # Electronic genres
            'genre_electronic_ambient',
            'genre_electronic_dnb',
            'genre_electronic_house',
            'genre_electronic_techno',
            'genre_electronic_trance',
            # Rosamerica genres
            'genre_rosamerica_cla',
            'genre_rosamerica_dan',
            'genre_rosamerica_hip',
            'genre_rosamerica_jaz',
            'genre_rosamerica_pop',
            'genre_rosamerica_rhy',
            'genre_rosamerica_roc',
            'genre_rosamerica_spe',
            # Tzanetakis genres
            'genre_tzanetakis_blu',
            'genre_tzanetakis_cla',
            'genre_tzanetakis_cou',
            'genre_tzanetakis_dis',
            'genre_tzanetakis_hip',
            'genre_tzanetakis_jaz',
            'genre_tzanetakis_met',
            'genre_tzanetakis_pop',
            'genre_tzanetakis_reg',
            'genre_tzanetakis_roc',
        ]        
        
    if len(src_genres) != len(list_of_genre_proportions) or len(dst_genres) != len(list_of_genre_proportions):
        raise ValueError("Genre proportions length does not match the provided genre list length")
    
    if len(src_genres) != len(dst_genres):
        raise ValueError("Source and destination genre lists must be of the same length")
    
    # For each genre, get the column from the dataframe as list and calculate similarity
    similarity_features = {}
    for i in range(len(list_of_genre_proportions)):
        feature_name = f"genre_sim_feature_{list_of_genre_proportions[i]}"
        similarity = 1 - abs(src_genres[i] - dst_genres[i])
        similarity_features[feature_name] = similarity
        

    # Need to add the genre similarity features to the global config so the model will train and be trained on genre features
    FEATURE_GROUPS['genre_similarity'] = list(similarity_features.keys())
    return similarity_features

def genre_type_proportions_column_names(genre_type: str) -> list:
    # This function should return the list of genre proportion column names
    if genre_type not in ['dortmund', 'electronic', 'rosamerica', 'tzanetakis']:
        raise ValueError("Invalid genre type. Must be one of: 'dortmund', 'electronic', 'rosamerica', 'tzanetakis'")
    
    if genre_type == 'dortmund':    
        dortmund_genres = [
            'genre_dortmund_alternative',
            'genre_dortmund_blues',
            'genre_dortmund_electronic',
            'genre_dortmund_folkcountry',
            'genre_dortmund_funksoulrnb',
            'genre_dortmund_jazz',
            'genre_dortmund_pop',
            'genre_dortmund_raphiphop',
            'genre_dortmund_rock',
        ]   
        return dortmund_genres
    elif genre_type == 'electronic':

        electronic_genres = [
            'genre_electronic_ambient',
            'genre_electronic_dnb',
            'genre_electronic_house',
            'genre_electronic_techno',
            'genre_electronic_trance',
        ]

    elif genre_type == 'rosamerica':
        
        rosamerica_genres = [
            'genre_rosamerica_cla',
            'genre_rosamerica_dan',
            'genre_rosamerica_hip',
            'genre_rosamerica_jaz',
            'genre_rosamerica_pop',
            'genre_rosamerica_rhy',
            'genre_rosamerica_roc',
            'genre_rosamerica_spe',
        ]
        return rosamerica_genres
    elif genre_type == 'tzanetakis':
        tzanetakis_genres = [
            'genre_tzanetakis_blu',
            'genre_tzanetakis_cla',
            'genre_tzanetakis_cou',
            'genre_tzanetakis_dis',
            'genre_tzanetakis_hip',
            'genre_tzanetakis_jaz',
            'genre_tzanetakis_met',
            'genre_tzanetakis_pop',
            'genre_tzanetakis_reg',
            'genre_tzanetakis_roc',
        ]
        return tzanetakis_genres

def get_genre_proportions_from_artist_list(
    artist_ids: list,
) -> pd.DataFrame:
    """
    returns the genre proportions for a list of artists
    ----------
    artist_ids : list
        List of artist IDs to fetch genre proportions for
    Returns
    -------
    dict
        Dictionary of genre similarity features
    """
    
    """ For this function we need to get the genres for each artist
    This is not something that is precomputed, so we will need to query the database
    to get the genres for each artist based on their artist_id."""
    
    """ Returning proporiton of the following genres for the list of artists given 
    
        Dortmund                      Electronic                    Rosamerica                    Tzanetakis
    genre_dortmund_alternative    genre_electronic_ambient      genre_rosamerica_cla          genre_tzanetakis_blu
    genre_dortmund_blues          genre_electronic_dnb          genre_rosamerica_dan          genre_tzanetakis_cla
    genre_dortmund_electronic     genre_electronic_house        genre_rosamerica_hip          genre_tzanetakis_cou
    genre_dortmund_folkcountry    genre_electronic_techno       genre_rosamerica_jaz          genre_tzanetakis_dis
    genre_dortmund_funksoulrnb    genre_electronic_trance       genre_rosamerica_pop          genre_tzanetakis_hip
    genre_dortmund_jazz                                         genre_rosamerica_rhy          genre_tzanetakis_jaz
    genre_dortmund_pop                                          genre_rosamerica_roc          genre_tzanetakis_met
    genre_dortmund_raphiphop                                    genre_rosamerica_spe          genre_tzanetakis_pop
    genre_dortmund_rock                                                                       genre_tzanetakis_reg
    
    """
    
    q = """
    SELECT *
    FROM artist_genre_proportions
    WHERE artist_id = ANY(%s);
    """
    conn = get_pg_conn()
    artist_ids = [int(x) for x in artist_ids]
    df = pd.read_sql_query(q, conn, params=(artist_ids,))
    
    conn.close()
    
    if df.empty:
        print("No genre data found for given artists.")
        
    return df
    
def build_link_prediction_features(
    num_true_samples=10000,
    neg_ratio=0.15,
    random_state=42,
    save = True,
):
    """
    Build features for link prediction task
    TODO: Modify to include the following features:
        - Genre similarity (if genre data is available) [IN PROGRESS]
        - Temporal collaboration patterns (if timestamp data is available)

    Parameters
    ----------
    num_true_samples : int
        Number of positive samples
    neg_ratio : float
        Ratio of negative to positive samples
    random_state : int
        Random seed

    Returns
    -------
    pd.DataFrame
        Features with label column
    """
    print("Connecting to database...")
    conn = get_pg_conn()

    print("Loading artist collaboration edges...")
    # Right here I am getting too many values, redo logic to get only a sample from artist_collab
    # acd = get_artist_collab(conn)

    print(f"Generating balanced dataset with {num_true_samples} positive samples...")
    df = get_training_test(
        conn=conn,
        num_true_samples=num_true_samples,
        neg_ratio=neg_ratio,
        random_state=random_state,
        pos_tablesample_pct=50,
        neg_tablesample_pct=60,
    )
    print(f"Created dataset with {len(df)} samples")
    # print(f"Label distribution:\n{df.label.value_counts()}")

    # del acd

    artist_ids = df.src.unique().tolist() + df.dst.unique().tolist()
    artist_ids = [int(x) for x in artist_ids]

    print("Loading artist embeddings and popularity...")
    embeddings = get_artist_embeddings(conn, artist_ids)


    print("Sampling k neighbors for each artist...")
    # neighbors_src = get_artist_k_neighbors_full_random(conn, df.src.tolist(), k=3)
    # neighbors_dst = get_artist_k_neighbors_full_random(conn, df.dst.tolist(), k=3)
    # artist_collab_3 = pd.concat([neighbors_src, neighbors_dst])
    
    # Get all unique artists once
    all_artist_ids = df[["src", "dst"]].values.flatten()
    unique_artists = pd.unique(all_artist_ids)

    # Single database call
    artist_collab_3 = get_artist_k_neighbors_full_random(conn, unique_artists, k=3)
    artist_collab_3 = artist_collab_3.rename(
        columns={
            artist_collab_3.columns[0]: "src",
            artist_collab_3.columns[1]: "dst",
        }
    )

    conn.close()

    print("Building embedding lookup...")
    embeddings = embeddings.loc[:, ~embeddings.columns.duplicated()] #TODO: FIX ROOT PROBLEM OF THIS 
    embedding_lookup = build_embedding_lookup(embeddings)

    print("Building neighbors dictionary...")
    neighbors = build_neighbors_dict(artist_collab_3)

    print(f"Building features for {len(df)} pairs...")
    df_features = build_features_for_pairs(
        pairs_df=df,
        embedding_lookup=embedding_lookup,
        neighbors=neighbors,
        target_col='label',
        topk=3,
        verbose=True
    )

    print(f"Generated {len(df_features)} feature rows")
    
    # Here we will input the genre similarity features if available
    print("Fetching genre proportions for artists...")
    genre_df = get_genre_proportions_from_artist_list(artist_ids)
    gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
    gt = ["similarity_prop_" + i for i in gt]
    # FEATURE_GROUPS['genre_similarity'] = gt[1:] # Drop the first column to remove colinearity
    # for col in FEATURE_GROUPS['genre_similarity']:
    #     if col not in LINK_PREDICTION_FEATURES and col != 'artist_id' and "genre" in col and GENRE_TYPE_CLASSIFICATION in col:
    #         print(f"Adding genre proportion column to features: {col}")
    #         LINK_PREDICTION_FEATURES.append(col)
    # for col in genre_df.columns:
    
    
    # Since the genre features will be so correlated if we had all 4 groups (dortmund, electronic, rosamerica, tzanetakis)
    # We are goin to make the user choose which group to use for the similarity features
    # Set in the config but 
    if not genre_df.empty:
        print("Calculating genre similarity features...")
        src_df = df_features[['src']].merge(genre_df, left_on='src', right_on='artist_id', how='left')
        dst_df = df_features[['dst']].merge(genre_df, left_on='dst', right_on = 'artist_id', how='left')
        src_df = src_df.drop(columns=['artist_id']).rename(columns={'src_x':'src'})
        dst_df = dst_df.drop(columns=['artist_id']).rename(columns={'dst_x':'dst'})
        # Now we will subtract the genre proportions to get similarity
        res = pd.DataFrame(src_df.iloc[:,1:].to_numpy() - dst_df.iloc[:,1:].to_numpy(),columns=dst_df.columns[1:])
        res['src'] = df_features['src']
        res['dst'] = df_features['dst']
        
        # Now rename to similarity features for our model
        for col in res.columns:
            if col not in ['src','dst']:
                res = res.rename(columns={col: f"similarity_{col}"})
        df_features = df_features.merge(res, on=['src','dst'], how='left')

        print("Added genre similarity features to dataset.")
    
    # breakpoint()
    # Save to CSV
    if save:
        df_features.to_csv(ARTIST_COLLAB_NEG_CSV, index=False)
        print(f"Saved features to {ARTIST_COLLAB_NEG_CSV}")

    return df_features


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build link prediction features")
    parser.add_argument("--num-samples", type=int, default=10000,
                       help="Number of positive samples")
    parser.add_argument("--neg-ratio", type=float, default=0.15,
                       help="Ratio of negative to positive samples")
    parser.add_argument("--random-state", type=int, default=42,
                       help="Random seed")

    args = parser.parse_args()

    df_features = build_link_prediction_features(
        num_true_samples=args.num_samples,
        neg_ratio=args.neg_ratio,
        random_state=args.random_state
    )
    gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
    FEATURE_GROUPS['genre_similarity'] = gt[1:] # Drop the first column to remove colinearity
    LINK_PREDICTION_FEATURES.extend(FEATURE_GROUPS['genre_similarity'])

    print(f"\nFeature shape: {df_features.shape}")
    print(f"\nLabel distribution:\n{df_features.label.value_counts()}")
