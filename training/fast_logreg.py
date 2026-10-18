"""Small learned model on top of the two fast-trend rules (second look, see notes/decisions.md).
Use when reproducing the logistic-regression comparison; training/train_fast.py calls fit_scores().

Inputs (6): per vital the distance-to-threshold score and the straight-line extrapolation score
(fast_features.vital_rule_scores). A missing score is filled with the training-row mean (neutral after
standardizing); no indicators. Standardized, L2 logistic regression, patient-weighted, positives up-weighted by
the weighted negative/positive ratio; C chosen by patient-grouped CV on training patients only."""
import numpy as np

from backend.risk_engine import fast_features as ff

C_GRID = (0.001, 0.01, 0.1, 1.0, 10.0)
INPUTS = [f"{k}_{v}" for k in ("distance", "extrap") for v in ff.VITALS]


def design(df):
    return np.array([ff.vital_rule_scores(r) for r in df[ff.FEATURE_NAMES].to_dict("records")], float)


def fit(X, y, w, C, fill=None, mean=None, scale=None):
    from sklearn.linear_model import LogisticRegression
    if fill is None:
        fill = np.nanmean(X, axis=0)
    Xf = np.where(np.isfinite(X), X, fill)
    if mean is None:
        mean, scale = Xf.mean(axis=0), Xf.std(axis=0) + 1e-9
    spw = (w[y == 0].sum()) / max(w[y == 1].sum(), 1e-9)
    sw = np.where(y == 1, w * spw, w)
    m = LogisticRegression(C=C, max_iter=1000).fit((Xf - mean) / scale, y, sample_weight=sw)
    return dict(model=m, fill=fill, mean=mean, scale=scale)


def decision(f, X):
    Xf = np.where(np.isfinite(X), X, f["fill"])
    return f["model"].decision_function((Xf - f["mean"]) / f["scale"])


def fit_scores(df, X, train_mask, valid, folds, weights_for, average_precision):
    """Return (scores for every live row, info). Training rows get out-of-fold scores, held-out rows the final fit."""
    tr = df[train_mask & valid]
    y_all = df.label.to_numpy()
    w_all = np.zeros(len(df))
    w_all[(train_mask & valid).to_numpy()] = weights_for(tr)
    cv = {}
    for C in C_GRID:
        aps = []
        for val_p in folds:
            vm = df.patient.isin(val_p).to_numpy()
            trn_i = (train_mask.to_numpy() & ~vm & valid.to_numpy())
            val_i = (train_mask.to_numpy() & vm & valid.to_numpy())
            f = fit(X[trn_i], y_all[trn_i], w_all[trn_i] / w_all[trn_i].mean(), C)
            aps.append(average_precision(y_all[val_i], decision(f, X[val_i])))
        cv[C] = float(np.mean(aps))
    best_C = max(cv, key=cv.get)
    scores = np.full(len(df), np.nan)
    for val_p in folds:
        vm = df.patient.isin(val_p).to_numpy()
        trn_i = (train_mask.to_numpy() & ~vm & valid.to_numpy())
        f = fit(X[trn_i], y_all[trn_i], w_all[trn_i] / w_all[trn_i].mean(), best_C)
        scores[vm] = decision(f, X[vm])
    ti = (train_mask & valid).to_numpy()
    final = fit(X[ti], y_all[ti], w_all[ti] / w_all[ti].mean(), best_C)
    scores[(~train_mask).to_numpy()] = decision(final, X[(~train_mask).to_numpy()])
    coef = final["model"].coef_[0] / final["scale"]          # per raw unit of each rule score
    info = dict(cv_auprc_by_C=cv, best_C=best_C, intercept=float(final["model"].intercept_[0]),
                coef_standardized=dict(zip(INPUTS, map(float, final["model"].coef_[0]))),
                coef_raw=dict(zip(INPUTS, map(float, coef))), fill=final["fill"].tolist(),
                mean=final["mean"].tolist(), scale=final["scale"].tolist())
    return scores, info, final
