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

import joblib
import json

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
        Yc = self.yc_scaler.transform(self.yc_imputer.transform(df[y_cont_cols]))

        if y_bin_cols and len(y_bin_cols) > 0:
            Yb = self.yb_imputer.transform(df[y_bin_cols]).astype(np.float32)
        else:
            Yb = None

        return C.astype(np.float32), Yc.astype(np.float32), Yb

    def inverse_continuous(self, Yc_scaled: np.ndarray) -> np.ndarray:
        """Scaled -> original continuous units."""
        return self.yc_scaler.inverse_transform(Yc_scaled)

# ----------------------------
# Dataset
# ----------------------------
class CVAEDataset(Dataset):
    def __init__(self, C, Yc, Yb=None):
        self.C = C
        self.Yc = Yc
        self.Yb = Yb

    def __len__(self):
        return len(self.C)

    def __getitem__(self, idx):
        if self.Yb is None:
            return self.C[idx], self.Yc[idx]
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

        # Encoder takes [y_cont, c]
        self.encoder = MLP(
            in_dim=y_cont_dim + c_dim,
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

    def encode(self, y_cont, c):
        h = torch.cat([y_cont, c], dim=1)
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

    def forward(self, y_cont, c):
        mu, logvar = self.encode(y_cont, c)
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

    yc_hat_scaled = yc_hat_scaled.detach().cpu().numpy().reshape(n_rows, n_samples, -1)
    yc_hat = prep.inverse_continuous(
        yc_hat_scaled.reshape(-1, yc_hat_scaled.shape[-1])
    ).reshape(n_rows, n_samples, -1)

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
    yc_samples, _ = generate_for_rows(model, prep, df_sub, c_cols, n_samples=n_samples, device=device)

    flat = yc_samples.reshape(-1, yc_samples.shape[-1])
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

    if popularity_col not in df_train.columns or popularity_col not in df_eval.columns:
        # don't crash training if you haven't joined popularity yet
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
        if len(batch) == 2:
            c, yc = batch
            yb = None
        else:
            c, yc, yb = batch

        c = c.to(device)
        yc = yc.to(device)
        yb = yb.to(device) if yb is not None else None

        yc_hat, yb_logits, mu, logvar = model(yc, c)
        _, m = cvae_loss(yc_hat, yc, mu, logvar, yb_logits, yb, beta=beta, bin_weight=bin_weight)

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
            if len(batch) == 2:
                c, yc = batch # Conditional variables, y_conditionals
                yb = None     # y-bin conditional
            else:
                c, yc, yb = batch

            c = c.to(device)
            yc = yc.to(device)
            yb = yb.to(device) if yb is not None else None

            opt.zero_grad(set_to_none=True)
            yc_hat, yb_logits, mu, logvar = model(yc, c) # Predicted y_conditionals, y-bin logit predictions, error, logvariance
            loss, m = cvae_loss(yc_hat, yc, mu, logvar, yb_logits, yb, beta=beta, bin_weight=bin_weight)
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
        c_dim=len(c_cols),
        y_cont_dim=len(y_cont_cols),
        z_dim=z_dim,
        hidden=hidden,
        bin_dim=len(y_bin_cols),
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
        "version": CVAE_VERSION,
    }
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == '__main__':
    # This is just a production model
    # We will 1. Load in the existing model
    #         2. Load in features below
        #         a. Src - Dst tracks for label = 0
        #         b. Src tracks
        #         c. Dst tracks
        #         d. Src Embeddings, Dst Embeddings
    #         3. Load in the the negative src-dst for new predictions
    
    # ==================================
    # Fit the model and evaluate
    # ==================================
    ARTIST_EMBEDDINGS_X = './artist_embeddings_collab_neg.csv'
    artist_embeddings = pd.read_csv(ARTIST_EMBEDDINGS_X)

    conn = get_pg_conn()
    # Start with just the block features for now
    block_track_features = audio_features_join_artist_collab(conn,"high_level_track_audio_features")
    conn.close()
    
    # Join the artist connection embeddings to the track features to get our full dataset
    df = block_track_features.merge(artist_embeddings, on = ['src','dst'], how = 'left')
    sample_size = int(round(len(df) * 0.85, 0))

    df_train = df.sample(n=sample_size, axis="index", random_state=42)
    df_val = df.loc[~df.index.isin(df_train.index)]
    
    # ==================================
    # Fit the model and evaluate
    # ==================================
    model, prep, writer = fit_cvae(
        df_train, df_val,
        c_cols=c_cols,
        y_cont_cols=y_cont_cols,
        y_bin_cols=y_bin_cols,
        z_dim=16,
        hidden=(256, 256),
        dropout=0.1,
        batch_size=512,
        epochs=30,
        lr=1e-3,
        warmup_epochs=10,
        max_beta=1.0,
        bin_weight=1.0,
        log_root="runs",
        run_name=None,         # auto name with timestamp
        log_hists_every=0      # set to e.g. 5 to log histograms every 5 epochs
    )

    # Generate samples for a few candidate pairs/rows:
    y_cont_samples, y_bin_probs = generate_for_rows(
        model, prep, df_val.head(5), c_cols, n_samples=200
    )

    print("y_cont_samples:", y_cont_samples.shape)  # (n_rows, n_samples, y_cont_dim)
    print("y_bin_probs:", None if y_bin_probs is None else y_bin_probs.shape)

    # Close writer when done (good practice in notebooks)
    writer.close()
