""" This script just does the link prediction on time, good for saving a new model"""

from pyexpat import model
from zipfile import Path
from config.config import LOGIT_MODEL_ID, LOGIT_NUM_PREDICTIONS, LOGIT_THRESHOLD, RANDOM_STATE,LOGIT_MODEL_DESC
from models.link_predictor import (
    LinkPredictor,
    predict_links,
    LINK_PREDICTION_FEATURES,
)
from utils.database import get_pg_conn
from psycopg2.extras import execute_values
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
import numpy as np 
import os
from config.config import MODEL_ENGINEERING_DIR, LOGIT_MODEL_VERSION
import joblib
from pathlib import Path

def load_logit_model(model_version: str, model_path: str):
    # TODO: load from artifacts/
    """
    Load the model used to predict probabilities

    :param model_path: Description
    :type model_path: str
    """
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    model_data = joblib.load(path)
    # The saved model is a dict with 'pipeline' key containing the actual sklearn model
    if isinstance(model_data, dict) and 'pipeline' in model_data:
        return model_data['pipeline']
    return model_data

 
logit_path = os.path.join(MODEL_ENGINEERING_DIR,'logit_model_v1.joblib')
pop_model = load_logit_model(LOGIT_MODEL_VERSION,logit_path)


res = predict_links(pop_model,LINK_PREDICTION_FEATURES,THRESHOLD=LOGIT_THRESHOLD,num_negs=LOGIT_NUM_PREDICTIONS,random_state=RANDOM_STATE,create=True)
print("Shape of predictions:", res.shape)

conn = get_pg_conn()

rows = [
    (LOGIT_MODEL_ID, row.src, row.dst, float(row.prob))
    for row in res.itertuples(index=False)
]

with conn, conn.cursor() as cur:

    # ---- insert / update model metadata ----
    cur.execute(
        """
        INSERT INTO predict_connection_model (model_id, model_date, model_desc)
        OVERRIDING SYSTEM VALUE
        VALUES (%s, NOW(), %s)
        ON CONFLICT (model_id)
        DO UPDATE SET
            model_date = EXCLUDED.model_date,
            model_desc = EXCLUDED.model_desc
        """,
        (LOGIT_MODEL_ID, LOGIT_MODEL_DESC),
    )

    # ---- bulk insert predictions ----
    execute_values(
        cur,
        """
        INSERT INTO prediction_connections (model_id, src, dst, prob)
        VALUES %s
        ON CONFLICT DO NOTHING
        """,
        rows,
    )

conn.commit()
conn.close()

