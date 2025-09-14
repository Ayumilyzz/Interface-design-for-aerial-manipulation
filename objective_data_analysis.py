import os
from datetime import datetime
import itertools
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import friedmanchisquare, wilcoxon, binomtest

# ============== CONFIG ==============
CSV_PATH = r"C:\Users\zhang\Unity\end_effector_not_touch_trials.csv"  # 改成你的CSV
CONDITION_ORDER = ["None", "Color", "Audio", "Gamepad"]
PRECISION_DELTAS = [0.03, 0.04]  # meters
EXPORT_NA_AS_BLANK = True
SIMPLE_PLOTS = True  # True=论文主图；False=附加图也导出
RNG_SEED = 42
# ====================================

# ---------- Helpers ----------
def normalize_modes(df, col="mode"):
    """把 mode 名称统一为: None/Color/Audio/Gamepad"""
    s = (df[col].astype(str)
                  .str.normalize("NFKC")
                  .str.replace(r"\s+", " ", regex=True)
                  .str.strip()
                  .str.lower())
    mapping = {
        "none": "None", "no feedback": "None", "no-feedback": "None",
        "nofeedback": "None", "baseline": "None", "control": "None", "nf":"None",
        "visual": "Color", "vision": "Color", "colour": "Color", "color": "Color",
        "audio": "Audio", "sound": "Audio", "beep": "Audio", "beeps": "Audio",
        "haptic": "Gamepad", "gamepad": "Gamepad", "vibration": "Gamepad",
        "rumble":"Gamepad", "vibrotactile":"Gamepad", "vibro":"Gamepad"
    }
    s = s.map(mapping).fillna(s)

    def canon(x: str) -> str:
        t = str(x).lower()
        if ("no" in t and "feed" in t) or t in {"baseline","control","nf"}:
            return "None"
        if any(k in t for k in ["visual","vision","colour","color"]):
            return "Color"
        if any(k in t for k in ["audio","sound","beep"]):
            return "Audio"
        if any(k in t for k in ["haptic","gamepad","vibration","rumble","vibro"]):
            return "Gamepad"
        return x
    df[col] = s.apply(canon)
    return df

def reorder_columns(wide_df, order=CONDITION_ORDER):
    front = [c for c in order if c in wide_df.columns]
    back  = [c for c in wide_df.columns if c not in order]
    return wide_df[front + back]

def bootstrap_mean_ci(arr, n_boot=5000, alpha=0.05, rng=None):
    """Bootstrap mean ±95%CI（自动忽略NaN）"""
    rng = np.random.default_rng(rng)
    arr = np.asarray(arr, float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return np.nan, (np.nan, np.nan)
    boots = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    lo, hi = np.quantile(boots, [alpha/2, 1-alpha/2])
    return float(np.mean(arr)), (float(lo), float(hi))

def friedman_on_complete(wide_df):
    """Friedman 检验（仅对完整行）"""
    complete = wide_df.dropna()
    if complete.shape[0] >= 2 and complete.shape[1] >= 3:
        arrays = [complete[c].values for c in complete.columns]
        return friedmanchisquare(*arrays), complete
    return None, complete

def pairwise_wilcoxon(df_wide_complete):
    """
    成对 Wilcoxon（两两条件），Bonferroni 校正；
    丢弃差值为0的配对；如有效样本过少，回退符号检验。
    """
    results = []
    cols = list(df_wide_complete.columns)
    for a, b in itertools.combinations(cols, 2):
        sub = df_wide_complete[[a, b]].dropna()
        if len(sub) == 0:
            results.append((a, b, 0, np.nan, np.nan, np.nan, 0))
            continue
        d = (sub[a] - sub[b]).values
        nz = d != 0
        n_nonzero = int(nz.sum())
        zeros = int((~nz).sum())
        if n_nonzero < 2:
            pos = int((d[nz] > 0).sum())
            neg = int((d[nz] < 0).sum())
            n_eff = pos + neg
            sign_p = binomtest(min(pos, neg), n_eff, 0.5).pvalue if n_eff > 0 else np.nan
            results.append((a, b, int(len(sub)), np.nan, np.nan, sign_p, zeros))
            continue
        x = sub[a].values[nz]
        y = sub[b].values[nz]
        try:
            stat, p = wilcoxon(x, y, zero_method="wilcox", method="exact")
        except TypeError:
            stat, p = wilcoxon(x, y, zero_method="wilcox")
        pos = int((x - y > 0).sum())
        neg = int((x - y < 0).sum())
        n_eff = pos + neg
        sign_p = binomtest(min(pos, neg), n_eff, 0.5).pvalue if n_eff > 0 else np.nan
        results.append((a, b, int(len(sub)), stat, p, sign_p, zeros))

    m = max(1, len(results))
    rows = []
    for a, b, n, stat, p, sign_p, zeros in results:
        p_bonf = min(1.0, p * m) if pd.notna(p) else np.nan
        rows.append({"A":a, "B":b, "N_pairs":n, "Zeros_dropped":zeros,
                     "W":stat, "p_raw":p, "p_bonf":p_bonf, "p_sign":sign_p})
    return pd.DataFrame(rows)

def export_report_friendly(df, path, na_as_blank=True, fmt=".3f", na_str="N/A"):
    """论文友好导出：NaN 输出为空白/自定义字符串"""
    def fmt_cell(x):
        if pd.isna(x): return "" if na_as_blank else na_str
        try: return f"{float(x):{fmt}}"
        except Exception: return str(x)
    try:
        out = df.map(fmt_cell)   # pandas 2.2+
    except Exception:
        out = df.applymap(fmt_cell)
    out.to_csv(path, index=True)

# ---------- Plot helpers (无连线) ----------
def plot_dot_ci_with_swarm(wide, ylabel, title, out_png, ci_rng=RNG_SEED):
    """
    每个条件一个均值点 + 95%CI；背景是个体散点（jitter）。不连线。
    wide: index=participant, columns=conditions
    """
    rng = np.random.default_rng(ci_rng)
    x = np.arange(len(wide.columns))
    fig, ax = plt.subplots(figsize=(6.5, 4))

    # 背景个体散点
    for i, col in enumerate(wide.columns):
        y = wide[col].values.astype(float)
        jitter = (rng.random(len(y)) - 0.5) * 0.18
        ax.scatter(np.full_like(y, x[i]) + jitter, y, s=24, alpha=0.45, color="grey")

    # 均值 + 95%CI
    means, los, his = [], [], []
    for col in wide.columns:
        m, (lo, hi) = bootstrap_mean_ci(wide[col].values, rng=ci_rng)
        means.append(m); los.append(lo); his.append(hi)
    means, los, his = np.array(means), np.array(los), np.array(his)
    yerr = np.vstack([means - los, his - means])

    ax.errorbar(x, means, yerr=yerr, fmt='o', capsize=5, linewidth=1.8)
    ax.set_xticks(x); ax.set_xticklabels(wide.columns)
    ax.set_ylabel(ylabel); ax.set_title(title)
    ax.grid(True, axis='y', alpha=0.2)
    plt.tight_layout(); plt.savefig(out_png, dpi=220); plt.close()

def plot_heatmap01(wide, title, out_png, cmap="magma"):
    """0..1 范围的热力图（行=participant, 列=condition）"""
    fig, ax = plt.subplots(figsize=(6, 0.5*len(wide.index)+1))
    im = ax.imshow(wide.values, vmin=0, vmax=1, aspect="auto", cmap=cmap)
    ax.set_yticks(np.arange(len(wide.index)))
    ax.set_yticklabels([f"P{p}" for p in wide.index])
    ax.set_xticks(np.arange(len(wide.columns)))
    ax.set_xticklabels(list(wide.columns))
    ax.set_title(title)
    cbar = plt.colorbar(im, ax=ax); cbar.set_label("Rate (0..1)")
    plt.tight_layout(); plt.savefig(out_png, dpi=220); plt.close()

# ---------- 1) Load ----------
df = pd.read_csv(CSV_PATH)
df["participant"] = df["participant"].astype(str).str.strip()
df["failure"]     = df["failure"].astype(str).str.strip().str.lower()
df["gap_to_wall"] = pd.to_numeric(df["gap_to_wall"], errors="coerce")

# ---------- 2) Normalize modes ----------
df = normalize_modes(df, "mode")

# ---------- 3) Outdir ----------
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
outdir = f"results_{timestamp}"
os.makedirs(outdir, exist_ok=True)

# ---------- 4) Safety: collision rate ----------
coll_rate = (
    df.assign(is_fail=(df["failure"]=="yes").astype(int))
      .groupby(["participant","mode"], as_index=False)["is_fail"]
      .mean()
      .rename(columns={"is_fail":"collision_rate"})
)
coll_wide = coll_rate.pivot(index="participant", columns="mode", values="collision_rate")
coll_wide = reorder_columns(coll_wide)
succ_wide = 1.0 - coll_wide  # success rate

# Stats
friedman_coll, coll_complete = friedman_on_complete(coll_wide)
pair_coll = pairwise_wilcoxon(coll_complete) if friedman_coll is not None else pd.DataFrame()

# ---------- 5) Precision: median safe distance（成功试次） ----------
success = df[df["failure"]=="no"].copy()
prec = (success.groupby(["participant","mode"], as_index=False)["gap_to_wall"]
        .median().rename(columns={"gap_to_wall":"median_safe_distance"}))
prec_wide = prec.pivot(index="participant", columns="mode", values="median_safe_distance")
prec_wide = reorder_columns(prec_wide)

friedman_prec, prec_complete = friedman_on_complete(prec_wide)
pair_prec = pairwise_wilcoxon(prec_complete) if friedman_prec is not None else pd.DataFrame()
n_contrib_prec = prec_wide.notna().sum(axis=0)

# ---------- 6) Precision-at-delta ----------
prec_at = {}
for d in PRECISION_DELTAS:
    ok = (df["failure"]=="no") & (df["gap_to_wall"]<=d)
    rate = (df.assign(hit=ok.astype(int))
              .groupby(["participant","mode"], as_index=False)["hit"]
              .mean()
              .rename(columns={"hit":f"precision_at_{d:.3f}m"}))
    wide = rate.pivot(index="participant", columns="mode",
                      values=f"precision_at_{d:.3f}m")
    wide = reorder_columns(wide)
    prec_at[d] = wide

# ---------- 7) Save tables ----------
coll_wide.to_csv(os.path.join(outdir, "collision_rate_per_participant.csv"))
succ_wide.to_csv(os.path.join(outdir, "success_rate_per_participant.csv"))
prec_wide.to_csv(os.path.join(outdir, "median_safe_distance_per_participant_raw.csv"))
export_report_friendly(
    prec_wide,
    os.path.join(outdir, "median_safe_distance_per_participant.csv"),
    na_as_blank=EXPORT_NA_AS_BLANK, fmt=".3f", na_str="N/A"
)
for d, wide in prec_at.items():
    wide.to_csv(os.path.join(outdir, f"precision_at_{d:.3f}m_per_participant.csv"))

if friedman_coll is not None:
    with open(os.path.join(outdir, "friedman_collision.txt"), "w") as f:
        f.write(str(friedman_coll))
if friedman_prec is not None:
    with open(os.path.join(outdir, "friedman_precision.txt"), "w") as f:
        f.write(str(friedman_prec))
pair_coll.to_csv(os.path.join(outdir, "pairwise_wilcoxon_collisions.csv"), index=False)
pair_prec.to_csv(os.path.join(outdir, "pairwise_wilcoxon_precision.csv"), index=False)

# ---------- 8) FIGURES ----------
# 8.1 主图：碰撞率（mean点+95%CI + 背景个体散点）
plot_dot_ci_with_swarm(
    coll_wide,
    ylabel="Collision rate (0..1)",
    title=f"Collision rate by condition (mean ±95% CI; N={coll_wide.shape[0]})",
    out_png=os.path.join(outdir, "collision_rate_mean_ci_swarm.png"),
    ci_rng=RNG_SEED
)

# 8.2 主图：Precision@delta（每个阈值各一张）
for d, wide in prec_at.items():
    thr_cm = int(round(d*100))
    plot_dot_ci_with_swarm(
        wide,
        ylabel="Rate (0..1)",
        title=f"Precision @ ≤{thr_cm} cm (mean ±95% CI)",
        out_png=os.path.join(outdir, f"precision_at_{thr_cm}cm_mean_ci_swarm.png"),
        ci_rng=RNG_SEED
    )

# 8.3 主图：中位安全距离（成功试次）箱线图 + 个体散点
plt.figure(figsize=(6.8,4.2))
box_data = [prec_wide[c].dropna().values for c in prec_wide.columns]
labels   = [f"{c}\n(n={int(n_contrib_prec[c])})" for c in prec_wide.columns]
plt.boxplot(box_data, tick_labels=labels, showmeans=True)
# 叠加散点
rng = np.random.default_rng(RNG_SEED)
for i, c in enumerate(prec_wide.columns, start=1):
    y = prec_wide[c].dropna().values
    jitter = (rng.random(len(y)) - 0.5) * 0.18
    plt.scatter(np.full_like(y, i) + jitter, y, s=22, alpha=0.55, color="grey")
plt.ylabel("Median safe distance (m)")
plt.title("Median safe distance by condition (successful trials only)")
plt.grid(True, axis='y', alpha=0.2)
plt.tight_layout()
plt.savefig(os.path.join(outdir, "safe_distance_box_scatter.png"), dpi=220)
plt.close()

# 8.4 附加图（可选）
if not SIMPLE_PLOTS:
    # 碰撞率热力图
    plot_heatmap01(coll_wide, "Collision rate (heatmap)",
                   os.path.join(outdir, "collision_rate_heatmap.png"))
    # Precision@delta 热力图
    for d, wide in prec_at.items():
        thr_cm = int(round(d*100))
        plot_heatmap01(wide, f"Precision @ ≤{thr_cm} cm (heatmap)",
                       os.path.join(outdir, f"precision_at_{thr_cm}cm_heatmap.png"))

# ---------- 9) Console summary ----------
print("\n=== SUMMARY ===")
print("Output dir:", outdir)
print("\nCollision rate (per participant):\n", coll_wide)
print("\nSuccess rate (per participant):\n", succ_wide)
print("\nMedian safe distance (per participant, successful only):\n", prec_wide)
if friedman_coll is not None: print("\nFriedman (collision):", friedman_coll)
if friedman_prec is not None: print("\nFriedman (precision):", friedman_prec)
print("\nPairwise Wilcoxon (collision):\n", pair_coll)
print("\nPairwise Wilcoxon (precision):\n", pair_prec)