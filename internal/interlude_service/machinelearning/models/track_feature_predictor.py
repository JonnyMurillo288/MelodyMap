"""
Predict the track level features between your predicted links
High-level or Low-Level (Depending)

The following Front End Commands will be sent
- User Selects an Artist (A)
- We Return all the neighbors (N1...Nn)
- User can type or search through neighbors (B)
- Then we find if user selected the neighbor exists (B)
    - If the neighbor does not exist, predict A-B link
    - Then we predict Tracks that COULD Link A-B
    
This frontend - backend talk occurst from JS to GO frontend.
But the Loading and Application of the Logit Predictions & CVAE Track Features Occurrs here

"""
import os
import json
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from utils import get_pg_conn
import psycopg2
from psycopg2.extras import execute_values
from models.return_link_embeddings import (
    get_random_prediction_links,
    get_artist_predictions
)
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
from tqdm import tqdm
import pyarrow as pa
import pyarrow.parquet as pq

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
    PREDICTION_EMBEDDINGS_CSV,
    CVAE_ARTIFACT_PATH,
    TRACK_FEATURES_PARQUET,
    ARTIST_COLLAB_NEG_CSV,
    CVAE_TRACK_FEATURES_PARQUET,
    CVAE_COMBINED_EMBEDDINGS_PARQUET,
    CVAE_Z_DIM,
    CVAE_HIDDEN,
    CVAE_DROPOUT,
    CVAE_BATCH_SIZE,
    CVAE_EPOCHS,
    CVAE_LR,
    CVAE_WARMUP_EPOCHS,
    CVAE_MAX_BETA,
    CVAE_TRAIN_SAMPLE_SIZE,
    CVAE_VAL_SAMPLE_SIZE,
    BLOCK_TRACK_AUDIO_FEATURES_PARQUET,
)

from config.cvae_config import (
    C_COLS,
    Y_CONT_COLS,
    Y_BIN_COLS
)

# ============================
# CVAE Model 
# Predict high-level track features y from conditioning context c
# Supports:
#   - continuous targets (scaled)
#   - optional binary tag targets (0/1)
# Includes:
#   - preprocessing (impute + scale)
#   - dataset + dataloaders
#   - CVAE model
#   - training loop w/ KL warmup
#   - TensorBoard logging
#   - sampling + inverse transform back to original continuous units
#
# YOU MUST SET:
#   c_cols       : list[str] conditioning feature columns
#   y_cont_cols  : list[str] continuous target columns
#   y_bin_cols   : list[str] binary target columns (or [])
#   df_train, df_val : your split dataframes containing those columns
#
# Example:
#   c_cols = [...]
#   y_cont_cols = [...]
#   y_bin_cols = []  # or [...]
#   df_train = ...
#   df_val = ...
#   model, prep, writer = fit_cvae(df_train, df_val, c_cols, y_cont_cols, y_bin_cols, z_dim=16)
#   y_cont_samples, y_bin_probs = generate_for_rows(model, prep, df_val.head(3), c_cols, n_samples=200)
#
# Run TensorBoard:
#   tensorboard --logdir runs
#   open http://localhost:6006

import os
import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from torch.utils.tensorboard import SummaryWriter

# --- generative validation deps ---
from sklearn.metrics import pairwise_distances
from sklearn.linear_model import Ridge
from scipy.stats import pearsonr


# ----------------------------
# Seed
# ----------------------------
def set_seed(seed: int = 42):
    import random
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

# ----------------------------
# Preprocessing
# ----------------------------
class CVAEPreprocessor:
    """
    Fits on TRAIN ONLY:
      - conditioning: median impute + StandardScaler
      - continuous targets: median impute + StandardScaler
      - binary targets (optional): most_frequent impute, kept as 0/1
    """
    def __init__(self):
        self.c_imputer = SimpleImputer(strategy="median")
        self.c_scaler = StandardScaler()

        self.yc_imputer = SimpleImputer(strategy="median")
        self.yc_scaler = StandardScaler()

        self.yb_imputer = SimpleImputer(strategy="most_frequent")
        self.has_bin = False
        self.fitted_ = False

    def fit(self, df: pd.DataFrame, c_cols, y_cont_cols, y_bin_cols=None):
        # conditioning
        C = self.c_imputer.fit_transform(df[c_cols])
        self.c_scaler.fit(C)

        # continuous targets
        if y_cont_cols and len(y_cont_cols) > 0:
            Yc = self.yc_imputer.fit_transform(df[y_cont_cols])
            self.yc_scaler.fit(Yc)

        # binary targets
        if y_bin_cols and len(y_bin_cols) > 0:
            self.yb_imputer.fit(df[y_bin_cols])
            self.has_bin = True

        self.fitted_ = True
        return self

    def transform(self, df: pd.DataFrame, c_cols, y_cont_cols, y_bin_cols=None):
        assert self.fitted_, "Call fit() first."

        C = self.c_scaler.transform(self.c_imputer.transform(df[c_cols]))
        
        if y_cont_cols and len(y_cont_cols) > 0:
            Yc = self.yc_scaler.transform(self.yc_imputer.transform(df[y_cont_cols]))
        else:
            Yc = None
        
        if y_bin_cols and len(y_bin_cols) > 0:
            Yb = self.yb_imputer.transform(df[y_bin_cols]).astype(np.float32)
        else:
            Yb = None

        return C.astype(np.float32), Yc.astype(np.float32) if Yc is not None else None, Yb

    def inverse_continuous(self, Yc_scaled: np.ndarray) -> np.ndarray:
        """Scaled -> original continuous units."""
        return self.yc_scaler.inverse_transform(Yc_scaled)

# ----------------------------
# Dataset
# ----------------------------
class CVAEDataset(Dataset):
    def __init__(self, C, Yc, Yb=None):
        n = len(C)
        self.C = C
        self.Yc = Yc if Yc is not None else np.zeros((n, 0), dtype=np.float32)
        self.Yb = Yb if Yb is not None else np.zeros((n, 0), dtype=np.float32)

    def __len__(self):
        return len(self.C)

    def __getitem__(self, idx):
        return self.C[idx], self.Yc[idx], self.Yb[idx]

# ----------------------------
# Model
# ----------------------------
class MLP(nn.Module):
    def __init__(self, in_dim, hidden, out_dim, dropout=0.1):
        super().__init__()
        layers = []
        d = in_dim
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU(), nn.Dropout(dropout)]
            d = h
        layers.append(nn.Linear(d, out_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)

class CVAE(nn.Module):
    """
    Encoder: q(z | y_cont, c) -> mu, logvar
    Decoder: p(y_cont, y_bin | z, c)
    """
    def __init__(self, c_dim, y_cont_dim, z_dim=16, hidden=(256, 256), bin_dim=0, dropout=0.1):
        super().__init__()
        self.z_dim = z_dim
        self.c_dim = c_dim
        self.y_cont_dim = y_cont_dim
        self.bin_dim = bin_dim

        # Encoder takes [y_cont, y_bin, c]
        self.encoder = MLP(
            in_dim=y_cont_dim + bin_dim + c_dim,
            hidden=hidden,
            out_dim=2 * z_dim,
            dropout=dropout
        )

        # Decoder takes [z, c] -> y_cont
        self.decoder_y = MLP(
            in_dim=z_dim + c_dim,
            hidden=hidden,
            out_dim=y_cont_dim,
            dropout=dropout
        )

        # Optional binary head
        self.decoder_bin = None
        if bin_dim > 0:
            self.decoder_bin = MLP(
                in_dim=z_dim + c_dim,
                hidden=hidden,
                out_dim=bin_dim,
                dropout=dropout
            )

    def encode(self, y_cont, c, y_bin=None):
        parts = [y_cont, c] if y_bin is None else [y_cont, y_bin, c]
        h = torch.cat(parts, dim=1)
        params = self.encoder(h)
        mu, logvar = params[:, : self.z_dim], params[:, self.z_dim :]
        return mu, logvar

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z, c):
        h = torch.cat([z, c], dim=1)
        y_cont_hat = self.decoder_y(h)
        yb_logits = self.decoder_bin(h) if self.decoder_bin is not None else None
        return y_cont_hat, yb_logits

    def forward(self, y_cont, c, y_bin=None):
        mu, logvar = self.encode(y_cont, c, y_bin)
        z = self.reparameterize(mu, logvar)
        y_cont_hat, yb_logits = self.decode(z, c)
        return y_cont_hat, yb_logits, mu, logvar

# ----------------------------
# Loss
# ----------------------------
def kl_div(mu, logvar):
    # 0.5 * sum(exp(logvar) + mu^2 - 1 - logvar)
    return 0.5 * torch.sum(torch.exp(logvar) + mu**2 - 1.0 - logvar, dim=1)

def beta_schedule(epoch, warmup_epochs=10, max_beta=1.0):
    if warmup_epochs <= 0:
        return max_beta
    return max_beta * min(1.0, (epoch + 1) / warmup_epochs)

def cvae_loss(yc_hat, yc_true, mu, logvar, yb_logits=None, yb_true=None, beta=1.0, bin_weight=1.0):
    # reconstruction on scaled continuous targets
    rec_yc = F.mse_loss(yc_hat, yc_true, reduction="none").sum(dim=1)

    rec_yb = torch.zeros_like(rec_yc)
    if yb_logits is not None and yb_true is not None:
        rec_yb = F.binary_cross_entropy_with_logits(yb_logits, yb_true, reduction="none").sum(dim=1)

    kl = kl_div(mu, logvar)
    loss = rec_yc + bin_weight * rec_yb + beta * kl

    # Return mean + per-batch metrics
    return loss.mean(), {
        "loss": float(loss.mean().detach().cpu()),
        "rec_yc": float(rec_yc.mean().detach().cpu()),
        "rec_yb": float(rec_yb.mean().detach().cpu()) if (yb_logits is not None and yb_true is not None) else 0.0,
        "kl": float(kl.mean().detach().cpu()),
    }


# ----------------------------
# Generation helpers
# ----------------------------
@torch.no_grad()
def generate_for_rows(model, prep, df_rows: pd.DataFrame, c_cols, *, n_samples=100, device=None):
    """
    Given df_rows with conditioning columns, generate n_samples synthetic tracks per row.
    Returns:
      y_cont_samples_original_units: shape (n_rows, n_samples, y_cont_dim)
      y_bin_probs: shape (n_rows, n_samples, y_bin_dim) or None
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model.eval()
    model.to(device)

    # Transform conditioning only
    C = prep.c_scaler.transform(prep.c_imputer.transform(df_rows[c_cols])).astype(np.float32)

    C_t = torch.tensor(C, dtype=torch.float32, device=device)  # (n_rows, c_dim)
    n_rows = C_t.size(0)

    # Repeat each row n_samples times
    C_rep = C_t.unsqueeze(1).repeat(1, n_samples, 1).reshape(n_rows * n_samples, -1)
    z = torch.randn((n_rows * n_samples, model.z_dim), device=device)

    yc_hat_scaled, yb_logits = model.decode(z, C_rep)

    if model.y_cont_dim > 0:
        yc_hat_scaled = yc_hat_scaled.detach().cpu().numpy().reshape(n_rows, n_samples, -1)
        yc_hat = prep.inverse_continuous(
            yc_hat_scaled.reshape(-1, yc_hat_scaled.shape[-1])
        ).reshape(n_rows, n_samples, -1)
    else:
        yc_hat = np.empty((n_rows, n_samples, 0), dtype=np.float32)

    yb_probs = None
    if yb_logits is not None:
        yb_probs = torch.sigmoid(yb_logits).detach().cpu().numpy().reshape(n_rows, n_samples, -1)

    return yc_hat, yb_probs


# ///////////////////////////////////////////////////////////////////////////////////////////////////////
# ============================
# GENERATIVE VALIDATION
# Loss curves alone do NOT validate a generative model.
# This section adds:
#   1) Sample diversity metrics
#   2) Correlation vs real data
#   3) Downstream task performance (e.g. popularity ranking)
#
# These log into the SAME TensorBoard run created in fit_cvae.
# ============================

@torch.no_grad()
def log_sample_diversity_to_tb(
    writer,
    model,
    prep,
    df_eval,
    c_cols,
    epoch,
    *,
    n_rows=10,
    n_samples=100,
    device=None,
):
    """
    Sample diversity metrics
    Detects mode collapse.

    Logs:
      - gen/diversity_mean_feature_std
      - gen/diversity_mean_pairwise_dist
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    df_sub = df_eval.sample(min(n_rows, len(df_eval)))
    yc_samples, yb_probs = generate_for_rows(model, prep, df_sub, c_cols, n_samples=n_samples, device=device)

    # Use binary probs if no continuous targets
    samples = yc_samples if yc_samples.shape[-1] > 0 else yb_probs
    if samples is None or samples.shape[-1] == 0:
        writer.add_scalar("gen/diversity_mean_feature_std", 0.0, epoch)
        writer.add_scalar("gen/diversity_mean_pairwise_dist", 0.0, epoch)
        return

    flat = samples.reshape(-1, samples.shape[-1])
    mean_std = float(flat.std(axis=0).mean())

    # sample at most 200 points to avoid OOM
    if flat.shape[0] > 200:
        idx = np.random.choice(flat.shape[0], 200, replace=False)
        flat = flat[idx]

    mean_pwd = float(pairwise_distances(flat).mean())

    writer.add_scalar("gen/diversity_mean_feature_std", mean_std, epoch)
    writer.add_scalar("gen/diversity_mean_pairwise_dist", mean_pwd, epoch)


@torch.no_grad()
def log_correlation_to_tb(
    writer,
    model,
    prep,
    df_eval,
    c_cols,
    y_cont_cols,
    epoch,
    *,
    n_samples=100,
    device=None,
):
    """
    Correlation vs real data

    For each eval row:
      - generate samples
      - compare generated mean to real track
    Logs:
      - gen/mean_abs_feature_corr
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if not y_cont_cols or len(y_cont_cols) == 0:
        writer.add_scalar("gen/mean_abs_feature_corr", 0.0, epoch)
        return

    yc_samples, _ = generate_for_rows(model, prep, df_eval, c_cols, n_samples=n_samples, device=device)
    gen_mean = yc_samples.mean(axis=1)
    real = df_eval[y_cont_cols].values

    corrs = []
    for i in range(gen_mean.shape[1]):
        try:
            c, _ = pearsonr(gen_mean[:, i], real[:, i])
            if np.isfinite(c):
                corrs.append(abs(c))
        except Exception:
            pass

    mean_abs_corr = float(np.mean(corrs)) if corrs else 0.0
    writer.add_scalar("gen/mean_abs_feature_corr", mean_abs_corr, epoch)


def log_popularity_ranking_to_tb(
    writer,
    model,
    prep,
    df_train,
    df_eval,
    c_cols,
    y_cont_cols,
    popularity_col,
    epoch,
    *,
    n_samples=100,
    device=None,
):
    """
    Downstream task performance (e.g. popularity ranking)

    Trains a popularity regressor on REAL tracks,
    then evaluates ranking quality on GENERATED samples.

    Logs:
      - gen/popularity_rank_corr
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if (not y_cont_cols or len(y_cont_cols) == 0
            or popularity_col not in df_train.columns
            or popularity_col not in df_eval.columns):
        writer.add_scalar("gen/popularity_rank_corr", np.nan, epoch)
        return

    pop_model = Ridge(alpha=1.0)
    pop_model.fit(df_train[y_cont_cols], df_train[popularity_col])

    yc_samples, _ = generate_for_rows(model, prep, df_eval, c_cols, n_samples=n_samples, device=device)

    n_rows = yc_samples.shape[0]
    scores = pop_model.predict(yc_samples.reshape(-1, yc_samples.shape[-1]))
    scores = scores.reshape(n_rows, n_samples)

    best_synth = scores.max(axis=1)
    real_pop = df_eval[popularity_col].values

    try:
        corr, _ = pearsonr(best_synth, real_pop)
    except Exception:
        corr = np.nan

    writer.add_scalar("gen/popularity_rank_corr", float(corr), epoch)


# ----------------------------
# Train / Eval
# ----------------------------
@torch.no_grad()
def evaluate(model, loader, device, beta=1.0, bin_weight=1.0):
    model.eval()
    totals = {"loss": 0.0, "rec_yc": 0.0, "rec_yb": 0.0, "kl": 0.0}
    n = 0

    for batch in loader:
        c, yc, yb = batch

        c = c.to(device)
        yc = yc.to(device)
        yb = yb.to(device)

        yb_in = yb if model.bin_dim > 0 else None
        yc_hat, yb_logits, mu, logvar = model(yc, c, yb_in)
        _, m = cvae_loss(yc_hat, yc, mu, logvar, yb_logits, yb_in, beta=beta, bin_weight=bin_weight)

        bs = c.size(0)
        n += bs
        for k in totals:
            totals[k] += m[k] * bs

    return {k: totals[k] / max(n, 1) for k in totals}

def train_cvae(
    model,
    train_loader,
    val_loader,
    device,
    writer: SummaryWriter,
    epochs=30,
    lr=1e-3,
    warmup_epochs=10,
    max_beta=1.0,
    bin_weight=1.0,
    grad_clip=5.0,
    log_hists_every=0,
    y_cont_cols=None,
    prep=None,
    # --- additive only: used for generative validation logging ---
    df_train=None,
    df_val=None,
    c_cols=None,
    popularity_col="track_popularity",
    gen_eval_every=5,
    gen_eval_n_samples=100,
    gen_eval_n_rows=10,
):
    """
    log_hists_every:
      - 0 disables histogram logging
      - otherwise logs generated histograms every N epochs (requires y_cont_cols + prep)
    """
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)

    best = None
    best_state = None
    global_step = 0

    for epoch in range(epochs):
        model.train()
        beta = beta_schedule(epoch, warmup_epochs=warmup_epochs, max_beta=max_beta)

        totals = {"loss": 0.0, "rec_yc": 0.0, "rec_yb": 0.0, "kl": 0.0}
        n = 0

        for batch in train_loader:
            c, yc, yb = batch

            c = c.to(device)
            yc = yc.to(device)
            yb = yb.to(device)

            yb_in = yb if model.bin_dim > 0 else None
            opt.zero_grad(set_to_none=True)
            yc_hat, yb_logits, mu, logvar = model(yc, c, yb_in)
            loss, m = cvae_loss(yc_hat, yc, mu, logvar, yb_logits, yb_in, beta=beta, bin_weight=bin_weight)
            loss.backward()
            if grad_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            opt.step()

            bs = c.size(0)
            n += bs
            global_step += 1

            # accumulate epoch metrics
            for k in totals:
                totals[k] += m[k] * bs

        train_m = {k: totals[k] / max(n, 1) for k in totals}
        val_m = evaluate(model, val_loader, device, beta=1.0, bin_weight=bin_weight) if val_loader is not None else None

        # ---------------------------------------
        # TensorBoard scalar logging
        # ---------------------------------------
        writer.add_scalar("loss/train", train_m["loss"], epoch)
        writer.add_scalar("recon_yc/train", train_m["rec_yc"], epoch)
        writer.add_scalar("recon_yb/train", train_m["rec_yb"], epoch)
        writer.add_scalar("kl/train", train_m["kl"], epoch)
        writer.add_scalar("beta", beta, epoch)

        if val_m is not None:
            writer.add_scalar("loss/val", val_m["loss"], epoch)
            writer.add_scalar("recon_yc/val", val_m["rec_yc"], epoch)
            writer.add_scalar("recon_yb/val", val_m["rec_yb"], epoch)
            writer.add_scalar("kl/val", val_m["kl"], epoch)

        # Optional latent stats (useful for collapse debugging)
        # We log from the last batch of the epoch (good enough)
        with torch.no_grad():
            writer.add_scalar("latent/mu_mean", float(mu.mean().detach().cpu()), epoch)
            writer.add_scalar("latent/mu_std", float(mu.std().detach().cpu()), epoch)
            writer.add_scalar("latent/logvar_mean", float(logvar.mean().detach().cpu()), epoch)

        # Optional histogram logging (off by default)
        if log_hists_every and (epoch % log_hists_every == 0) and (prep is not None) and (y_cont_cols is not None):
            # Log histograms of reconstructed yc_hat (scaled space) for a quick view of collapse/noise
            # Use last batch's yc_hat
            yc_hat_np = yc_hat.detach().cpu().numpy()
            # unscale to original units for interpretability
            yc_hat_unscaled = prep.inverse_continuous(yc_hat_np)
            for j, feat in enumerate(y_cont_cols[: min(10, len(y_cont_cols))]):
                writer.add_histogram(f"recon_unscaled/{feat}", yc_hat_unscaled[:, j], epoch)

        # --------------------------------------------------
        # GENERATIVE VALIDATION (offline checks)
        # Loss curves alone cannot validate a generative model.
        # --------------------------------------------------
        if (
            gen_eval_every
            and (epoch % gen_eval_every == 0)
            and (prep is not None)
            and (y_cont_cols is not None)
            and (df_train is not None)
            and (df_val is not None)
            and (c_cols is not None)
        ):
            log_sample_diversity_to_tb(
                writer, model, prep, df_val, c_cols, epoch,
                n_rows=gen_eval_n_rows,
                n_samples=gen_eval_n_samples,
                device=device
            )
            log_correlation_to_tb(
                writer, model, prep, df_val, c_cols, y_cont_cols, epoch,
                n_samples=gen_eval_n_samples,
                device=device
            )
            log_popularity_ranking_to_tb(
                writer, model, prep,
                df_train, df_val,
                c_cols, y_cont_cols,
                popularity_col=popularity_col,
                epoch=epoch,
                n_samples=gen_eval_n_samples,
                device=device
            )

        score = val_m["loss"] if val_m is not None else train_m["loss"]
        if best is None or score < best:
            best = score
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        msg = (
            f"Epoch {epoch+1:02d}/{epochs} | "
            f"train loss {train_m['loss']:.4f} "
            f"(rec_yc {train_m['rec_yc']:.4f}, "
            f"rec_yb {train_m['rec_yb']:.4f}, "
            f"kl {train_m['kl']:.4f}, "
            f"beta {beta:.3f})"
        )
        if val_m is not None:
            msg += (
                f" | val loss {val_m['loss']:.4f} "
                f"(rec_yc {val_m['rec_yc']:.4f}, rec_yb {val_m['rec_yb']:.4f}, kl {val_m['kl']:.4f})"
            )
        print(msg)

    if best_state is not None:
        model.load_state_dict(best_state)
    return model

# ----------------------------
# Fit helper
# ----------------------------
def fit_cvae(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    c_cols,
    y_cont_cols,
    y_bin_cols=None,
    *,
    z_dim=16,
    hidden=(256, 256),
    dropout=0.1,
    batch_size=512,
    epochs=30,
    lr=1e-3,
    warmup_epochs=10,
    max_beta=1.0,
    bin_weight=1.0,
    num_workers=0,
    seed=42,
    log_root="runs",
    run_name=None,
    log_hists_every=0
):
    """
    Returns: (model, prep, writer)
    """
    set_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    y_bin_cols = y_bin_cols or []

    # Unique run dir
    if run_name is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_name = f"cvae_tracks_z{z_dim}_h{'-'.join(map(str, hidden))}_{ts}"
    log_dir = os.path.join(log_root, run_name)
    writer = SummaryWriter(log_dir=log_dir)

    # Fit preprocessors on TRAIN ONLY
    prep = CVAEPreprocessor().fit(df_train, c_cols, y_cont_cols, y_bin_cols)

    # Transform to numpy arrays
    C_tr, Yc_tr, Yb_tr = prep.transform(df_train, c_cols, y_cont_cols, y_bin_cols)
    C_va, Yc_va, Yb_va = prep.transform(df_val, c_cols, y_cont_cols, y_bin_cols)

    # Datasets / Loaders
    ds_tr = CVAEDataset(C_tr, Yc_tr, Yb_tr)
    ds_va = CVAEDataset(C_va, Yc_va, Yb_va)

    train_loader = DataLoader(ds_tr, batch_size=batch_size, shuffle=True, num_workers=num_workers, pin_memory=True)
    val_loader = DataLoader(ds_va, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=True)

    # Model
    model = CVAE(
        c_dim=C_tr.shape[1],
        y_cont_dim=Yc_tr.shape[1] if Yc_tr is not None else 0,
        z_dim=z_dim,
        hidden=hidden,
        bin_dim=Yb_tr.shape[1] if Yb_tr is not None else 0,
        dropout=dropout
    )

    # Train
    model = train_cvae(
        model,
        train_loader,
        val_loader,
        device=device,
        writer=writer,
        epochs=epochs,
        lr=lr,
        warmup_epochs=warmup_epochs,
        max_beta=max_beta,
        bin_weight=bin_weight,
        log_hists_every=log_hists_every,
        y_cont_cols=y_cont_cols,
        prep=prep,
        # --- generative validation wiring ---
        df_train=df_train,
        df_val=df_val,
        c_cols=c_cols,
        popularity_col="track_popularity",
        gen_eval_every=10,
        gen_eval_n_samples=50,
        gen_eval_n_rows=5
    )

    # Optional: log model graph (can fail in some cases; safe to skip)
    # try:
    #     example_c = torch.tensor(C_tr[:2], dtype=torch.float32, device=device)
    #     example_y = torch.tensor(Yc_tr[:2], dtype=torch.float32, device=device)
    #     writer.add_graph(model, (example_y, example_c))
    # except Exception:
    #     pass

    return model, prep, writer


def audio_features_join_artist_collab(
    conn: psycopg2.extensions.connection,
    features_table_name: str,
    src_dst_ids: list,
    num_p_comps: int = 2,
    chunksize: int = 50_000,
):
    """
    Stream track-level audio features joined to artist collaborations.
    Selects only Audio Features (af) columns containing 'PC1' through num_pcs (PCn). (If necessary)
    
    Parameters
    ----------
    conn : psycopg2.connection
        Database connection
    features_table_name: str,
        table that we want to select our features from
    src_dst_ids: list(tuple) [(src,dst),...]
        unique src-dst of our artist_collab table
    num_p_comps: int,
        number of principle components we want to get (Usually 2)
        VALUE SHOULD BE 0 IF YOU ARE NOT GETTING PRINCIPAL COMPONENT TABLES
        ONLY BLOCKED TF ARE PCs
    chunksize:
        for writing the output to parquet to be read instead of writing to disk

    Returns
    -------
    pd.DataFrame
        DataFrame src,dst,recording_id, artist_features...
    """

    allowed_tables = {
        "high_level_track_audio_features",
        "blocked_high_level_audio_features",
        "low_level_track_audio_features",
        "blocked_low_level_audio_features",
    }

    if features_table_name not in allowed_tables:
        raise ValueError(f"Invalid features table: {features_table_name}")

    # -------- build VALUES list for src,dst --------
    # src_dst_ids is e.g. [(src1,dst1), (src2,dst2), ...]
    values_clause = ", ".join(["(%s::int,%s::int)"] * len(src_dst_ids))
    flat_params = [x for pair in src_dst_ids for x in pair]

    # -------- build dynamic PC column selector --------
    if num_p_comps > 0:
        pc_predicates = [f"column_name ILIKE '%%PC{i+1}%%'" for i in range(num_p_comps)]
        pc_filter_clause = "AND (" + " OR ".join(pc_predicates) + ")"
    else:
        pc_filter_clause = ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            {pc_filter_clause}
            ORDER BY ordinal_position;
            """,
            (features_table_name,),
        )
        cols = [r[0] for r in cur.fetchall()]

    if not cols:
        raise RuntimeError(
            f"No PC1..PC{num_p_comps} columns found in '{features_table_name}'"
        )

    # ensure recording_gid is present
    # if "recording_gid" not in cols:
    #     cols = ["recording_gid"] + cols

    select_af_cols = ", ".join(f'af."{c}"' for c in cols if c != "recording_id")

    # ---- main query ----
    q = f"""
        -- Input MBID pairs
        WITH gid_pairs(src_id, dst_id) AS (
            VALUES {values_clause}
        ),

        -- Convert MBIDs → numeric artist IDs
        ac_pairs AS (
            SELECT
                a_src.id AS src_id,
                a_dst.id AS dst_id
            FROM gid_pairs gp
            JOIN artist a_src ON a_src.id = gp.src_id
            JOIN artist a_dst ON a_dst.id = gp.dst_id
        ),

        -- Lookup artist_collab rows
        ac AS (
            SELECT
                c.artist_id          AS src,
                c.neighbor_artist_id AS dst,
                c.recording_id
            FROM artist_collab c
            JOIN ac_pairs p
              ON (c.artist_id, c.neighbor_artist_id) =
                 (p.src_id, p.dst_id)
        )

        SELECT
            a_src.id AS src,
            a_dst.id AS dst,
            r.id     AS recording_id,
            {select_af_cols}
        FROM ac
        JOIN artist   a_src ON a_src.id = ac.src
        JOIN artist   a_dst ON a_dst.id = ac.dst
        JOIN recording r    ON r.id = ac.recording_id
        JOIN {features_table_name} af
          ON af.recording_id = r.id;
    """
    
    return pd.read_sql_query(
        q,
        con=conn,
        params=flat_params,
        chunksize=chunksize,
    )


def save_cvae_artifact(
    path,
    model,
    prep,
    *,
    c_cols,
    y_cont_cols,
    y_bin_cols,
    z_dim,
    hidden
):
    os.makedirs(path, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(path, "model.pt"))
    joblib.dump(prep, os.path.join(path, "prep.pkl"))

    meta = {
        "c_cols": c_cols,
        "y_cont_cols": y_cont_cols,
        "y_bin_cols": y_bin_cols,
        "z_dim": z_dim,
        "hidden": list(hidden),
        "model_type": "CVAE",
        "version": "v1",
    }
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def load_cvae_artifact(path, device="cpu"):
    import json, joblib, torch, os

    with open(os.path.join(path, "meta.json")) as f:
        meta = json.load(f)

    model = CVAE(
        c_dim=len(meta["c_cols"]),
        y_cont_dim=len(meta["y_cont_cols"]),
        z_dim=meta["z_dim"],
        hidden=tuple(meta["hidden"]),
        bin_dim=len(meta["y_bin_cols"]),
    )
    model.to(device)

    # --- load checkpoint ---
    ckpt = torch.load(os.path.join(path, "model.pt"), map_location=device)

    model_state = model.state_dict()
    filtered = {}
    skipped = []

    for k, v in ckpt.items():
        if k in model_state and v.shape == model_state[k].shape:
            filtered[k] = v
        else:
            skipped.append((k, getattr(v, "shape", None),
                            model_state.get(k, None).shape if k in model_state else None))

    print("Loaded weights:", len(filtered), " | Skipped:", len(skipped))
    for name, ck, cur in skipped:
        print(f" ⚠️ skipped {name}: checkpoint {ck}  !=  model {cur}")

    model.load_state_dict(filtered, strict=False)
    model.eval()

    prep = joblib.load(os.path.join(path, "prep.pkl"))

    return model, prep, meta

# ===========================
# Get the block_track_features that will be used to train the model
# ==============================

def get_block_track_features(artist_embeddings):
    """ This function generates the data needed for the block track features used to train the CVAE model """

    # ARTIST_EMBEDDINGS_X = './artist_embeddings_collab_neg.csv'
    # artist_ids = (
    #     artist_embeddings.src.unique().tolist()
    #     + artist_embeddings.dst.unique().tolist()
    # )
    artist_ids = [(int(r.src),int(r.dst)) for _,r in artist_embeddings[['src','dst']].iterrows()]
    artist_ids = set(artist_ids)

    conn = get_pg_conn()

    chunks = audio_features_join_artist_collab(
        conn,
        "high_level_track_audio_features",
        artist_ids,
        num_p_comps=0,
        chunksize=1_000,
    )

    parquet_path = BLOCK_TRACK_AUDIO_FEATURES_PARQUET
    writer = None

    for i, chunk in enumerate(tqdm(chunks, desc="Writing parquet chunks")):
        # Optional: drop obviously unneeded columns early
        # chunk = chunk[["src", "dst", "recording_gid", "danceability", "energy"]]

        table = pa.Table.from_pandas(chunk, preserve_index=False)

        if writer is None:
            writer = pq.ParquetWriter(
                parquet_path,
                table.schema,
                compression="snappy",
            )

        writer.write_table(table)

    if writer is not None:
        writer.close()

    conn.close()



def train_cvae_synth_tracks(
    artist_embeddings_path: str = None,
    track_features_path: str = None,
    combined_embeddings_path: str = None,
    output_artifact_path: str = None,
    train_sample_size: int = None,
    val_sample_size: int = None,
    z_dim: int = None,
    hidden: tuple = None,
    dropout: float = None,
    batch_size: int = None,
    epochs: int = None,
    lr: float = None,
    warmup_epochs: int = None,
    max_beta: float = None,
    seed: int = None,
    skip_data_prep: bool = False,
):
    """
    Train the CVAE model for synthetic track feature generation.

    This function:
    1. Loads artist embeddings and track features
    2. Merges them into a combined dataset
    3. Splits into train/validation sets
    4. Trains the CVAE model
    5. Saves model artifacts (model.pt, prep.pkl, meta.json)

    Parameters
    ----------
    artist_embeddings_path : str, optional
        Path to artist embeddings CSV. Defaults to ARTIST_COLLAB_NEG_CSV.
    track_features_path : str, optional
        Path to track features parquet. Defaults to CVAE_TRACK_FEATURES_PARQUET.
    combined_embeddings_path : str, optional
        Path to save/load combined embeddings. Defaults to CVAE_COMBINED_EMBEDDINGS_PARQUET.
    output_artifact_path : str, optional
        Path to save model artifacts. Defaults to CVAE_ARTIFACT_PATH.
    train_sample_size : int, optional
        Number of training samples. Defaults to CVAE_TRAIN_SAMPLE_SIZE.
    val_sample_size : int, optional
        Number of validation samples. Defaults to CVAE_VAL_SAMPLE_SIZE.
    z_dim : int, optional
        Latent dimension. Defaults to CVAE_Z_DIM.
    hidden : tuple, optional
        Hidden layer sizes. Defaults to CVAE_HIDDEN.
    dropout : float, optional
        Dropout rate. Defaults to CVAE_DROPOUT.
    batch_size : int, optional
        Training batch size. Defaults to CVAE_BATCH_SIZE.
    epochs : int, optional
        Number of training epochs. Defaults to CVAE_EPOCHS.
    lr : float, optional
        Learning rate. Defaults to CVAE_LR.
    warmup_epochs : int, optional
        KL warmup epochs. Defaults to CVAE_WARMUP_EPOCHS.
    max_beta : float, optional
        Maximum KL beta. Defaults to CVAE_MAX_BETA.
    seed : int, optional
        Random seed. Defaults to RANDOM_STATE.
    skip_data_prep : bool, optional
        If True, load combined_embeddings_path directly instead of merging.

    Returns
    -------
    tuple
        (model, prep, writer) - trained model, preprocessor, and TensorBoard writer.
    """
    # Apply defaults from config
    artist_embeddings_path = artist_embeddings_path or ARTIST_COLLAB_NEG_CSV
    track_features_path = track_features_path or BLOCK_TRACK_AUDIO_FEATURES_PARQUET#CVAE_TRACK_FEATURES_PARQUET
    combined_embeddings_path = combined_embeddings_path or CVAE_COMBINED_EMBEDDINGS_PARQUET
    output_artifact_path = output_artifact_path or CVAE_ARTIFACT_PATH
    train_sample_size = train_sample_size or CVAE_TRAIN_SAMPLE_SIZE
    val_sample_size = val_sample_size or CVAE_VAL_SAMPLE_SIZE
    z_dim = z_dim or CVAE_Z_DIM
    hidden = hidden or CVAE_HIDDEN
    dropout = dropout if dropout is not None else CVAE_DROPOUT
    batch_size = batch_size or CVAE_BATCH_SIZE
    epochs = epochs or CVAE_EPOCHS
    lr = lr or CVAE_LR
    warmup_epochs = warmup_epochs if warmup_epochs is not None else CVAE_WARMUP_EPOCHS
    max_beta = max_beta if max_beta is not None else CVAE_MAX_BETA
    seed = seed or RANDOM_STATE

    # -------------------------------------------------------------------------
    # Step 1: Load and merge data (or load pre-merged)
    # -------------------------------------------------------------------------
    if skip_data_prep and os.path.exists(combined_embeddings_path):
        print(f"Loading pre-merged data from {combined_embeddings_path}")
        df = pd.read_parquet(combined_embeddings_path)
    else:
        print(f"Loading artist embeddings from {artist_embeddings_path}")
        artist_embeddings = pd.read_csv(artist_embeddings_path)

        try: 
            print(f"Loading track features from {track_features_path}")
            track_features = pd.read_parquet(track_features_path)
        except FileNotFoundError:
            print("CVAE Blocked High Level Training Data Does Not Exist")
            print("=============================\nGetting block_track_features\n=============================")
            get_block_track_features(artist_embeddings)
            track_features = pd.read_parquet(track_features_path)

        # Deduplicate artist embeddings by src/dst (take mean of numeric cols)
        print("Deduplicating artist embeddings...")
        artist_embeddings_unique = (
            artist_embeddings
            .groupby(['src', 'dst'], as_index=False)
            .mean(numeric_only=True)
        )

        # Merge track features with artist embeddings
        print("Merging track features with artist embeddings...")
        df = track_features.merge(
            artist_embeddings_unique,
            on=['src', 'dst'],
            how='left',
            validate='many_to_one'
        )

        # Save combined embeddings for future runs
        print(f"Saving combined embeddings to {combined_embeddings_path}")
        print("Combined embeddings preview:")
        print(df.head())
        df.to_parquet(combined_embeddings_path)

    print(f"Combined dataset shape: {df.shape}")

    # -------------------------------------------------------------------------
    # Step 2: Train/validation split
    # -------------------------------------------------------------------------
    print("Splitting into train/validation sets...")

    # First do a rough 85/15 split
    sample_size = int(round(len(df) * 0.85, 0))
    df_train = df.sample(n=min(sample_size, len(df)), random_state=seed)
    df_val = df.loc[~df.index.isin(df_train.index)]

    # Then subsample to requested sizes
    if train_sample_size and len(df_train) > train_sample_size:
        df_train = df_train.sample(n=train_sample_size, random_state=seed + 25)
    if val_sample_size and len(df_val) > val_sample_size:
        df_val = df_val.sample(n=val_sample_size, random_state=seed + 25)

    print(f"Train size: {len(df_train)}, Val size: {len(df_val)}")
    print(f"Conditioning columns (c_cols): {len(C_COLS)}")
    print(f"Target columns (y_cont_cols): {len(Y_CONT_COLS)}")

    # -------------------------------------------------------------------------
    # Step 3: Train CVAE model
    # -------------------------------------------------------------------------
    print("\nTraining CVAE model...")
    print(f"  z_dim={z_dim}, hidden={hidden}, dropout={dropout}")
    print(f"  batch_size={batch_size}, epochs={epochs}, lr={lr}")
    print(f"  warmup_epochs={warmup_epochs}, max_beta={max_beta}")

    model, prep, writer = fit_cvae(
        df_train,
        df_val,
        c_cols=C_COLS,
        y_cont_cols=Y_CONT_COLS,
        y_bin_cols=Y_BIN_COLS if Y_BIN_COLS else None,
        z_dim=z_dim,
        hidden=hidden,
        dropout=dropout,
        batch_size=batch_size,
        epochs=epochs,
        lr=lr,
        warmup_epochs=warmup_epochs,
        max_beta=max_beta,
        seed=seed,
    )

    # -------------------------------------------------------------------------
    # Step 4: Save model artifacts
    # -------------------------------------------------------------------------
    print(f"\nSaving model artifacts to {output_artifact_path}")
    save_cvae_artifact(
        output_artifact_path,
        model,
        prep,
        c_cols=C_COLS,
        y_cont_cols=Y_CONT_COLS,
        y_bin_cols=Y_BIN_COLS if Y_BIN_COLS else [],
        z_dim=z_dim,
        hidden=hidden,
    )

    print("CVAE training complete!")
    return model, prep, writer


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Train CVAE model for synthetic track feature generation"
    )

    # Data paths
    parser.add_argument(
        "--artist-embeddings", type=str, default=None,
        help="Path to artist embeddings CSV (default: ARTIST_COLLAB_NEG_CSV)"
    )
    parser.add_argument(
        "--track-features", type=str, default=None,
        help="Path to track features parquet (default: CVAE_TRACK_FEATURES_PARQUET)"
    )
    parser.add_argument(
        "--combined-embeddings", type=str, default=None,
        help="Path to save/load combined embeddings (default: CVAE_COMBINED_EMBEDDINGS_PARQUET)"
    )
    parser.add_argument(
        "--output-artifact", type=str, default=None,
        help="Path to save model artifacts (default: CVAE_ARTIFACT_PATH)"
    )
    parser.add_argument(
        "--skip-data-prep", action="store_true",
        help="Skip data merging, load combined embeddings directly"
    )

    # Training parameters
    parser.add_argument(
        "--train-samples", type=int, default=None,
        help=f"Training sample size (default: {CVAE_TRAIN_SAMPLE_SIZE})"
    )
    parser.add_argument(
        "--val-samples", type=int, default=None,
        help=f"Validation sample size (default: {CVAE_VAL_SAMPLE_SIZE})"
    )
    parser.add_argument(
        "--z-dim", type=int, default=None,
        help=f"Latent dimension (default: {CVAE_Z_DIM})"
    )
    parser.add_argument(
        "--epochs", type=int, default=None,
        help=f"Training epochs (default: {CVAE_EPOCHS})"
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help=f"Batch size (default: {CVAE_BATCH_SIZE})"
    )
    parser.add_argument(
        "--lr", type=float, default=None,
        help=f"Learning rate (default: {CVAE_LR})"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help=f"Random seed (default: {RANDOM_STATE})"
    )

    args = parser.parse_args()

    train_cvae_synth_tracks(
        artist_embeddings_path=args.artist_embeddings,
        track_features_path=args.track_features,
        combined_embeddings_path=args.combined_embeddings,
        output_artifact_path=args.output_artifact,
        train_sample_size=args.train_samples,
        val_sample_size=args.val_samples,
        z_dim=args.z_dim,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        skip_data_prep=args.skip_data_prep,
    )

    