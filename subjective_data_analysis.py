# subjective_analysis_from_wide.py
# Read your wide-format questionnaire sheet and produce tidy long-format,
# descriptive stats, Friedman/Wilcoxon tests, and figures.

import pandas as pd
import numpy as np
import itertools
import os
from datetime import datetime
import matplotlib.pyplot as plt
from scipy.stats import friedmanchisquare, wilcoxon

# ================== CONFIG ==================
XLSX = r"C:\Users\zhang\Unity\Interface design(1-6).xlsx"   # <- 改成你的路径
SHEET = 0
OUTROOT = "subjective_results"

# 条件映射（后缀 -> 条件名）
COND_MAP = {
    "":  "None",     # 无后缀 -> 基线
    "2": "Color",
    "3": "Audio",
    "4": "Gamepad",
}

# NASA-TLX 6 维度原始列前缀（和你的表头完全一致）
TLX_KEYS = [
    "Mental Demand: How mentally demanding was the task?",
    "Physical Demand: How physically demanding was the task?",
    "Temporal Demand: How hurried or rushed was the pace of the task?",
    "Performance: How successful were you in accomplishing what you were asked to do?",
    "Effort: How hard did you have to work to accomplish your level of performance?",
    "Frustration: How insecure, discouraged, irritated, stressed, and annoyed were you?",
]

# SSQ 7 项（与你的列名一致）
SSQ_KEYS = [
    "Nausea",
    "Eye strain",
    "Headache",
    "Dizziness (eyes open)",
    "Dizziness (eyes closed)",
    "Blurred vision",
    "Sweating",
]

# 三个模态的帮助感知题（注意有 \xa0）
HELP_COLOR_DIST = "COLOR FEEDBACK: How helpful was this feedback mode in perceiving the distance to the wall? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"
HELP_COLOR_COLL = "COLOR FEEDBACK:\xa0How helpful was this feedback mode in avoiding failure (collision)? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"

HELP_AUDIO_DIST = "AUDITORY FEEDBACK: How helpful was this feedback mode in perceiving the distance to the wall? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"
HELP_AUDIO_COLL = "AUDITORY FEEDBACK:\xa0How helpful was this feedback mode in avoiding failure (collision)? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"

HELP_HAPTIC_DIST = "HAPTIC FEEDBACK: How helpful was this feedback mode in perceiving the distance to the wall? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"
HELP_HAPTIC_COLL = "HAPTIC FEEDBACK:\xa0How helpful was this feedback mode in avoiding failure (collision)? (-7=Extremely worse, 1=Not helpful at all, 7=Extremely helpful)"

PREF_OPEN_ENDED = "Which feedback mode do you prefer for this task and why? (Open-ended)"

# =============== Helpers ===============
def get_participant_id(df):
    # 统一出一个 participant 列
    if "参与者编号" in df.columns:
        pid = df["参与者编号"].astype(str).str.strip()
    elif "ID" in df.columns:
        pid = df["ID"].astype(str).str.strip()
    else:
        pid = pd.Series(np.arange(1, len(df) + 1), index=df.index).astype(str)
    return pid

def get_column(df, name):
    # 容忍 NBSP / 清理左右空格
    name_clean = name.strip()
    cols = {c.strip(): c for c in df.columns}
    if name_clean in cols:
        return df[cols[name_clean]]
    # 尝试替换 \xa0 为普通空格
    name_nbsp = name_clean.replace("\xa0", " ")
    candidates = {c.replace("\xa0", " ").strip(): c for c in df.columns}
    if name_nbsp in candidates:
        return df[candidates[name_nbsp]]
    # 找不到则返回 None
    return None

def friedman_and_wilcoxon_long(df_long, value_col, cond_col="condition", pid_col="participant"):
    """对重复测量的长表做 Friedman + Wilcoxon（Bonferroni）。"""
    pivot = df_long.pivot(index=pid_col, columns=cond_col, values=value_col)
    # 保持条件顺序
    order = ["None", "Color", "Audio", "Gamepad"]
    pivot = pivot[[c for c in order if c in pivot.columns]]
    complete = pivot.dropna()
    friedman_res = None
    if complete.shape[0] >= 2 and complete.shape[1] >= 3:
        arrays = [complete[c].values for c in complete.columns]
        friedman_res = friedmanchisquare(*arrays)
    # pairwise
    pairs = []
    for a, b in itertools.combinations(complete.columns, 2):
        sub = complete[[a, b]].dropna()
        if len(sub) >= 2:
            try:
                stat, p = wilcoxon(sub[a], sub[b])
            except ValueError:
                stat, p = np.nan, np.nan
        else:
            stat, p = np.nan, np.nan
        pairs.append((a, b, len(sub), stat, p))
    m = len(pairs) if pairs else 1
    rows = []
    for a, b, n, stat, p in pairs:
        p_bonf = min(1.0, p * m) if pd.notna(p) else np.nan
        rows.append({"A": a, "B": b, "N_pairs": n, "W": stat, "p_raw": p, "p_bonf": p_bonf})
    posthoc = pd.DataFrame(rows)
    return friedman_res, posthoc, pivot

def save_boxplot(df_long, value_col, title, outpath, order=("None","Color","Audio","Gamepad")):
    plt.figure()
    data = [df_long.loc[df_long["condition"] == c, value_col].dropna().values for c in order if c in df_long["condition"].unique()]
    labels = [c for c in order if c in df_long["condition"].unique()]
    plt.boxplot(data, labels=labels, showmeans=True)
    plt.title(title)
    plt.ylabel(value_col)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()

# =============== MAIN ===============
df = pd.read_excel(XLSX, sheet_name=SHEET)

# 参与者 ID
df["participant"] = get_participant_id(df)

# ---- 构建 TLX/SSQ 四条件长表 ----
rows = []
for suffix, cond_name in COND_MAP.items():
    # TLX
    tlx_vals = {}
    for key in TLX_KEYS:
        colname = key + suffix
        if suffix == "":
            colname = key  # 无后缀
        if colname in df.columns:
            tlx_vals[key] = pd.to_numeric(df[colname], errors="coerce")
        else:
            tlx_vals[key] = np.nan

    # SSQ
    ssq_vals = {}
    for key in SSQ_KEYS:
        colname = key + suffix
        if suffix == "":
            colname = key
        if colname in df.columns:
            ssq_vals[key] = pd.to_numeric(df[colname], errors="coerce")
        else:
            ssq_vals[key] = np.nan

    # 汇总每个参与者
    for idx in df.index:
        row = {
            "participant": df.loc[idx, "participant"],
            "condition": cond_name,
        }
        # TLX 六维 + 总分
        tlx_dim_values = []
        for key in TLX_KEYS:
            val = tlx_vals[key].iloc[idx] if isinstance(tlx_vals[key], pd.Series) else np.nan
            row[f"TLX_{key.split(':')[0]}"] = val
            tlx_dim_values.append(val)
        row["TLX_overall"] = np.nanmean(tlx_dim_values)

        # SSQ 七项 + 三子量表（按常见 3 子量表直和；如需加权请替换为你的权重）
        ssq_item_vals = []
        for key in SSQ_KEYS:
            val = ssq_vals[key].iloc[idx] if isinstance(ssq_vals[key], pd.Series) else np.nan
            row[f"SSQ_{key}"] = val
            ssq_item_vals.append(val)

        # 简化版子量表划分（如需严格 SSQ 权重可自行替换）
        # 常见映射（简化示意）：Nausea 子量表（N, SW, …），Oculomotor（ES, H, BV），Disorientation（DO, DC）
        # 这里用直和示意：
        row["SSQ_Nausea_sub"]       = np.nansum([row.get("SSQ_Nausea"), row.get("SSQ_Sweating")])
        row["SSQ_Oculomotor_sub"]   = np.nansum([row.get("SSQ_Eye strain"), row.get("SSQ_Headache"), row.get("SSQ_Blurred vision")])
        row["SSQ_Disorientation_sub"]= np.nansum([row.get("SSQ_Dizziness (eyes open)"), row.get("SSQ_Dizziness (eyes closed)")])
        row["SSQ_total"]            = np.nansum(ssq_item_vals)

        rows.append(row)

long = pd.DataFrame(rows)

# ---- Helpful（仅三个模态）----
help_rows = []
for idx in df.index:
    pid = df.loc[idx, "participant"]

    def get_val(colname):
        s = get_column(df, colname)
        return pd.to_numeric(s.iloc[idx], errors="coerce") if s is not None else np.nan

    # Color
    help_rows.append({
        "participant": pid, "condition": "Color",
        "help_distance": get_val(HELP_COLOR_DIST),
        "help_collision": get_val(HELP_COLOR_COLL),
    })
    # Audio
    help_rows.append({
        "participant": pid, "condition": "Audio",
        "help_distance": get_val(HELP_AUDIO_DIST),
        "help_collision": get_val(HELP_AUDIO_COLL),
    })
    # Gamepad
    help_rows.append({
        "participant": pid, "condition": "Gamepad",
        "help_distance": get_val(HELP_HAPTIC_DIST),
        "help_collision": get_val(HELP_HAPTIC_COLL),
    })

help_long = pd.DataFrame(help_rows)

# ---- 输出目录 ----
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
outdir = os.path.join(OUTROOT, f"run_{stamp}")
os.makedirs(outdir, exist_ok=True)

# 保存整洁表
long.to_csv(os.path.join(outdir, "subjective_long_TLX_SSQ.csv"), index=False)
help_long.to_csv(os.path.join(outdir, "subjective_long_helpfulness.csv"), index=False)

# ==== 描述性统计（均值±SD）====
def save_desc(df_long, cols, name, include_none=True):
    order = ["None","Color","Audio","Gamepad"] if include_none else ["Color","Audio","Gamepad"]
    out = df_long.groupby("condition")[cols].agg(["mean","std"]).reindex(order)
    out.to_csv(os.path.join(outdir, f"desc_{name}.csv"))
    return out

# TLX overall + six dims
tlx_cols = ["TLX_overall"] + [c for c in long.columns if c.startswith("TLX_") and c!="TLX_overall"]
desc_tlx  = save_desc(long, tlx_cols, "TLX", include_none=True)

# SSQ
ssq_cols = [c for c in long.columns if c.startswith("SSQ_")]
desc_ssq  = save_desc(long, ssq_cols, "SSQ", include_none=True)

# Helpful（无 None）
desc_help = help_long.groupby("condition")[["help_distance","help_collision"]].agg(["mean","std"]).reindex(["Color","Audio","Gamepad"])
desc_help.to_csv(os.path.join(outdir, "desc_helpfulness.csv"))

# ==== 统计检验 ====
def run_stats_and_save(df_long, value_col, name, include_none=True):
    friedman_res, posthoc, pivot = friedman_and_wilcoxon_long(
        df_long if include_none else df_long[df_long["condition"]!="None"],
        value_col
    )
    pivot.to_csv(os.path.join(outdir, f"pivot_{name}.csv"))
    if friedman_res is not None:
        with open(os.path.join(outdir, f"friedman_{name}.txt"), "w") as f:
            f.write(str(friedman_res))
    posthoc.to_csv(os.path.join(outdir, f"posthoc_{name}.csv"), index=False)
    return friedman_res, posthoc, pivot

# TLX overall
run_stats_and_save(long, "TLX_overall", "TLX_overall", include_none=True)

# 每个 TLX 维度
for c in [k for k in tlx_cols if k!="TLX_overall"]:
    run_stats_and_save(long, c, c, include_none=True)

# SSQ total & subscales
for c in ["SSQ_total","SSQ_Nausea_sub","SSQ_Oculomotor_sub","SSQ_Disorientation_sub"]:
    run_stats_and_save(long, c, c, include_none=True)

# Helpful（只在三模态上做）
for c in ["help_distance","help_collision"]:
    run_stats_and_save(help_long, c, f"help_{c}", include_none=False)

# ==== 基本图 ====
# TLX overall 箱线图
save_boxplot(long, "TLX_overall", "NASA-TLX overall by condition", os.path.join(outdir,"TLX_overall_box.png"))

# SSQ total 箱线图
save_boxplot(long, "SSQ_total", "SSQ total by condition", os.path.join(outdir,"SSQ_total_box.png"))

# Helpfulness 柱状（均值±SD）
for metric, fname in [("help_distance","help_distance_bar.png"),("help_collision","help_collision_bar.png")]:
    m = help_long.groupby("condition")[metric].mean().reindex(["Color","Audio","Gamepad"])
    s = help_long.groupby("condition")[metric].std().reindex(["Color","Audio","Gamepad"])
    x = np.arange(len(m))
    plt.figure()
    plt.bar(x, m.values, yerr=s.values, capsize=5)
    plt.xticks(x, ["Color","Audio","Gamepad"])
    plt.ylabel(metric)
    plt.title(f"{metric} (mean ± SD)")
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, fname), dpi=200)
    plt.close()

print(f"\nDone. Outputs -> {outdir}")
print("\nTip: 在 Results 写法里，'None' 在 helpfulness 中缺失是预期情况（不参与这两道题）。")
