"""
This is the file for returning the embeddings for the existing Link Predictions
Not creating links, just returning them
"""
import os
import json
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from utils import get_pg_conn
from psycopg2.extras import execute_values
from features.pipeline_links import build_link_prediction_features, build_link_prediction_embeddings_from_artist_list
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegressionCV, LogisticRegression
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    log_loss,
    brier_score_loss,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report
)

from config.config import (
    LINK_PREDICTION_FEATURES,
    LOGIT_L1_RATIOS,
    LOGIT_CS_MIN,
    LOGIT_CS_MAX,
    LOGIT_CS_NUM,
    LOGIT_CV,
    LOGIT_MAX_ITER,
    LOGIT_THRESHOLD,
    TEST_SIZE,
    RANDOM_STATE,
    MODEL_ENGINEERING_DIR,
    LOGIT_NUM_PREDICTIONS,
    LOGIT_MODEL_ID,
    LOGIT_MODEL_DESC,
    LOGIT_MODEL_VERSION,
    PREDICTION_EMBEDDINGS_CSV
)


def predict_links(
    THRESHOLD = .5,
    num_negs = 1000000,
):
    """
    Apply the prediction's from the model
    Get ALL of the artists that SHOULD have a connection


    Parameters
    ----------
    artist_embeddings_df : pd.DataFrame
        Artist Embeddings DataFrame
    features : list, optional
        List of feature names to use. If None, uses LINK_PREDICTION_FEATURES
    threshold : float, optional
        Classification threshold
    num_negs : float, optional
        Test set proportion
    random_state : int, optional
        Random seed
    create: bool 
        If Create: create new sets of predictions
        If Not Create: Only get random set of predictions

    Returns
    -------
    Dataframe
        link_prediction_features
    """
    
    conn = get_pg_conn()

    # TODO: Eventually we will allow the user to input their prefered input artist(s) and we can get that here 
    preds = get_random_prediction_links(conn,num_negs,LOGIT_MODEL_ID)
    # breakpoint()
    artist_id = [(i.src,i.dst) for _,i in preds.iterrows()]
    artist_embeddings = build_link_prediction_embeddings_from_artist_list(artist_list=artist_id)
    artist_embeddings['prob'] = preds['prob']
    
    return artist_embeddings

def get_random_prediction_links(
    conn, limit: int = 50,
    model_id: int = 1
    ) -> pd.DataFrame:
    """
    Go into the prediction_connection DB and return random prediction links
    
    :param conn: Description
    :param limit: Description
    :type limit: int
    :return: Description
    :rtype: DataFrame
    
    """
    q = f"""
        SELECT src, dst, prob
        FROM prediction_connections
        WHERE model_id = {model_id}
        ORDER BY RANDOM()
        LIMIT {limit}
    """
    
    return pd.read_sql_query(q,conn)

def get_artist_predictions(
    artist_a: int, artist_b: int, limit: int =15
):
    """
    Given an artist (or pair of artists) get the prediciton of how likely they are to have a song together, 
    and N number of songs that they would have created together
    
    Parameters 
    ----------
    artist_a: int
        artist_id (int) for the input artist
        
    artist_b: int (optional)
        artist_id (int) for the target artist
        
    limit: (int)
        number of tracks that they would create together
    """
    conn = get_pg_conn()
    
    if not artist_b or artist_b < 0:
        q = f"""
            SELECT src, dst, prob
            FROM prediction_connections
            WHERE src = {artist_a}
            OR dst = {artist_a};
        """
    if artist_b:
        q = f"""
            SELECT src, dst, prob
            FROM prediction_connections
            WHERE (src = {artist_a} AND dst = {artist_b})
            OR (src = {artist_b} AND dst = {artist_a});
        """
    df = pd.read_sql_query(q,conn)
    conn.close()
    
    artist_id = [(i.src,i.dst) for i in df.iterrows()]
    artist_embeddings = build_link_prediction_embeddings_from_artist_list(artist_list=artist_id)

    # Put back the src - dst pairs
    res = pd.DataFrame({
        "src": artist_embeddings["src"],
        "dst": artist_embeddings["dst"],
        "prob": artist_embeddings['prob'],
    })
    conn.close()
    # keep only edges above threshold
    return res.reset_index(drop=True)


def load_logit_model(
    model_path: str, 
):
    """
    Load the model used to predict probabilities
    
    :param model_path: Description
    :type model_path: str
    """
    
    return

if __name__ == "__main__":
    from config.config import ARTIST_COLLAB_NEG_CSV, LOGIT_MODEL_VERSION
        
    # Now we will save the model predictions 
    res = predict_links(THRESHOLD=LOGIT_THRESHOLD,num_negs=LOGIT_NUM_PREDICTIONS)

    # Save to CSV
    res.to_csv(PREDICTION_EMBEDDINGS_CSV, index=False)
    print(f"Saved features to {PREDICTION_EMBEDDINGS_CSV}")
