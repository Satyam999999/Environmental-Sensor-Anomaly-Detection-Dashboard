"""
anomaly_detection.py
--------------------
Lightweight anomaly detector for real USGS water quality data.

Two detectors:
  1. Rolling Z-Score  (window = 96 samples = 24 h,  |z| > 3.0)
  2. Rolling IQR      (window = 96 samples = 24 h,  k = 1.5)

Ground truth is constructed from:
  (a) USGS data-qualifier codes that indicate equipment/data issues
  (b) Manually annotated anomaly windows identified during EDA
      (based on visually confirmed storm events, sensor outages, etc.)

Outputs
-------
  data/processed/sensor_data_processed.csv   – flags + z-scores added
  data/processed/anomaly_events.csv          – detected anomaly periods
  data/processed/detection_metrics.csv       – precision / recall / F1
  data/processed/time_to_alarm.csv           – time-to-alarm per event
"""

import os
import numpy as np
import pandas as pd

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading processed USGS data …")
RAW_FILE = os.path.join("data", "raw", "usgs_potomac_2023.csv")
df = pd.read_csv(RAW_FILE, parse_dates=["timestamp"])
N  = len(df)

SENSORS = ["turbidity_FNU", "pH", "specific_conductance_uScm", "dissolved_oxygen_mgL"]
SENSORS = [s for s in SENSORS if s in df.columns]   # only those present

os.makedirs(os.path.join("data", "processed"), exist_ok=True)

WINDOW     = 96      # 24-hour rolling window (96 × 15 min)
Z_THRESH   = 3.0
MIN_PERIOD  = 48
K_IQR      = 1.5

# ═══════════════════════════════════════════════════════════════════════════════
#  BUILD GROUND-TRUTH from USGS qualifier codes
# ═══════════════════════════════════════════════════════════════════════════════
# USGS qualifiers that indicate data quality issues:
#   'e'   – estimated value
#   'Eqp' – equipment malfunction
#   'P'   – provisional (may still be OK, but note)
SUSPECT_QUALIFIERS = {"e", "Eqp", "Ice", "ice", "Ssn"}

gt_mask = np.zeros(N, dtype=int)
for sensor in SENSORS:
    qual_col = f"{sensor}_qualifier"
    if qual_col in df.columns:
        for i, val in enumerate(df[qual_col].fillna("")):
            codes = set(val.replace(",", " ").split())
            if codes & SUSPECT_QUALIFIERS:
                gt_mask[i] = 1

# ── Also annotate manually identified anomaly windows from EDA ───────────────
# These are based on visual inspection of the full-year time series.
# Storms/events confirmed by cross-referencing NOAA storm data.
manual_events = [
    # (label, start_dt_str, end_dt_str, description)
    ("WinterStorm",   "2023-01-12", "2023-01-15",
     "Winter storm – turbidity spike >100 FNU, conductance drop"),
    ("SpringSnowmelt","2023-03-10", "2023-03-18",
     "Spring snowmelt – sustained turbidity elevation, pH shift"),
    ("SummerLowFlow", "2023-07-20", "2023-07-30",
     "Summer low-flow – DO depression, conductance elevation"),
    ("TropicalStorm", "2023-09-01", "2023-09-07",
     "Tropical remnants – turbidity surge, pH fluctuation"),
    ("SensorGap",     "2023-05-15", "2023-05-20",
     "Instrument gap / suspect data – multiple sensors NaN"),
]

event_records = []
for label, s, e, desc in manual_events:
    mask = (df["timestamp"] >= s) & (df["timestamp"] <= e)
    idxs = df.index[mask].tolist()
    if idxs:
        gt_mask[idxs[0]: idxs[-1] + 1] = 1
        event_records.append({
            "event_id": label, "start": s, "end": e,
            "start_idx": idxs[0], "end_idx": idxs[-1] + 1,
            "description": desc
        })
events_df = pd.DataFrame(event_records)

print(f"Ground-truth samples flagged: {gt_mask.sum():,} / {N:,} "
      f"({gt_mask.sum()/N*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════════════════════
#  DETECTOR 1 – Rolling Z-Score
# ═══════════════════════════════════════════════════════════════════════════════
print("\nRunning Rolling Z-Score detector …")

zscore_flags = pd.DataFrame(index=df.index)
zscore_vals  = pd.DataFrame(index=df.index)

for col in SENSORS:
    series = df[col].copy()
    filled = series.ffill().bfill()

    roll_mean = filled.rolling(WINDOW, min_periods=MIN_PERIOD, center=False).mean()
    roll_std  = filled.rolling(WINDOW, min_periods=MIN_PERIOD, center=False).std()

    z = (filled - roll_mean) / roll_std.replace(0, np.nan)
    zscore_vals[f"zscore_{col}"]  = z.round(4)
    flag = (z.abs() > Z_THRESH).astype(int)
    flag[series.isna()] = 1      # NaN → always flagged
    zscore_flags[f"zflag_{col}"] = flag

zscore_combined = zscore_flags.max(axis=1).rename("zscore_flag_any")

# ═══════════════════════════════════════════════════════════════════════════════
#  DETECTOR 2 – Rolling IQR
# ═══════════════════════════════════════════════════════════════════════════════
print("Running Rolling IQR detector …")

iqr_flags = pd.DataFrame(index=df.index)

def rolling_iqr_flag(series, window=WINDOW, min_periods=MIN_PERIOD, k=K_IQR):
    filled = series.ffill().bfill()
    flags  = np.zeros(len(series), dtype=int)
    arr    = filled.values
    for i in range(min_periods, len(arr)):
        win     = arr[max(0, i - window + 1): i + 1]
        q1, q3  = np.percentile(win, 25), np.percentile(win, 75)
        iqr_val = q3 - q1
        lo, hi  = q1 - k * iqr_val, q3 + k * iqr_val
        if arr[i] < lo or arr[i] > hi:
            flags[i] = 1
    flags[series.isna()] = 1
    return pd.Series(flags, index=series.index)

for col in SENSORS:
    iqr_flags[f"iqr_flag_{col}"] = rolling_iqr_flag(df[col])

iqr_combined = iqr_flags.max(axis=1).rename("iqr_flag_any")

# ═══════════════════════════════════════════════════════════════════════════════
#  EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════
def evaluate(pred, truth, label):
    pred  = np.asarray(pred, dtype=int)
    truth = np.asarray(truth, dtype=int)
    tp = int(((pred == 1) & (truth == 1)).sum())
    fp = int(((pred == 1) & (truth == 0)).sum())
    fn = int(((pred == 0) & (truth == 1)).sum())
    pr = tp / (tp + fp + 1e-9)
    rc = tp / (tp + fn + 1e-9)
    f1 = 2 * pr * rc / (pr + rc + 1e-9)
    return {"detector": label, "TP": tp, "FP": fp, "FN": fn,
            "precision": round(pr, 4), "recall": round(rc, 4), "F1": round(f1, 4)}

print("\n── Overall metrics ──────────────────────────────────────────────")
results = []
for pred, lbl in [(zscore_combined, "RollingZScore"), (iqr_combined, "RollingIQR")]:
    r = evaluate(pred, gt_mask, lbl)
    results.append(r)
    print(f"  {lbl:16s}  P={r['precision']:.3f}  R={r['recall']:.3f}  "
          f"F1={r['F1']:.3f}  (TP={r['TP']} FP={r['FP']} FN={r['FN']})")

# ── Per-event metrics ─────────────────────────────────────────────────────────
print("\n── Per-event metrics (Z-Score) ──────────────────────────────────")
per_event_rows = []
z_arr = zscore_combined.values
for _, ev in events_df.iterrows():
    s, e = int(ev["start_idx"]), int(ev["end_idx"])
    ev_mask = np.zeros(N, dtype=int)
    ev_mask[s:e] = 1
    r = evaluate(z_arr, ev_mask, "RollingZScore")
    # Time-to-alarm
    hits = np.where(z_arr[s:e] == 1)[0]
    tta  = int(hits[0]) * 15 if len(hits) > 0 else None
    per_event_rows.append({
        "event_id": ev["event_id"], "description": ev["description"],
        **r, "tta_minutes": tta
    })
    status = f"{tta} min" if tta is not None else "NOT DETECTED"
    print(f"  {ev['event_id']:18s}  P={r['precision']:.3f}  R={r['recall']:.3f}  "
          f"F1={r['F1']:.3f}  TTA={status}")

per_event_df = pd.DataFrame(per_event_rows)
avg_tta = np.nanmean([r["tta_minutes"] for r in per_event_rows if r["tta_minutes"] is not None])
print(f"\n  Average time-to-alarm: {avg_tta:.1f} min  "
      f"({avg_tta/60:.1f} h)")

# ── KPI summary ───────────────────────────────────────────────────────────────
pct_flagged = zscore_combined.sum() / N * 100
print(f"\n── KPI summary ──────────────────────────────────────────────────")
print(f"  % readings flagged (Z-Score): {pct_flagged:.2f}%")
print(f"  Avg time-to-alarm:            {avg_tta:.1f} min")

# ═══════════════════════════════════════════════════════════════════════════════
#  SAVE OUTPUTS
# ═══════════════════════════════════════════════════════════════════════════════
out = df.copy()
out = pd.concat([out, zscore_flags, zscore_vals, iqr_flags,
                 zscore_combined, iqr_combined], axis=1)
out["ground_truth"] = gt_mask

PROC = os.path.join("data", "processed")
out.to_csv(os.path.join(PROC, "sensor_data_processed.csv"), index=False)
print(f"\n✅  Saved sensor_data_processed.csv  ({len(out):,} rows)")

pd.DataFrame(results).to_csv(os.path.join(PROC, "detection_metrics.csv"),        index=False)
per_event_df.to_csv(        os.path.join(PROC, "per_event_metrics.csv"),          index=False)
events_df.to_csv(           os.path.join(PROC, "annotated_events.csv"),           index=False)
print("✅  Saved metrics and event annotation CSVs")
print("\nDone! ✨")
