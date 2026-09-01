"""
load_data.py
------------
Downloads real water-quality time-series data for a full year (2023) from the
USGS National Water Information System (NWIS) Instantaneous Values API.

Station  : Potomac River at Chain Bridge, DC  (USGS site 01645704)
Parameters:
  00095 – Specific conductance (µS/cm @ 25°C)
  00300 – Dissolved oxygen (mg/L)
  00400 – pH (standard units)
  63680 – Turbidity (FNU)

License   : U.S. Public Domain – USGS data carry no copyright restriction.
            https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
Source URL: https://waterservices.usgs.gov/nwis/iv/

Output    : data/raw/usgs_potomac_2023.csv
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── Configuration ─────────────────────────────────────────────────────────────
SITE       = "01645704"          # Potomac River at Chain Bridge, DC
SITE_NAME  = "Potomac River at Chain Bridge, DC"
PARAMS     = ["00095", "00300", "00400", "63680"]
PARAM_NAMES = {
    "00095": "specific_conductance_uScm",
    "00300": "dissolved_oxygen_mgL",
    "00400": "pH",
    "63680": "turbidity_FNU",
}
BASE_URL   = "https://waterservices.usgs.gov/nwis/iv/"
NODATA_VAL = -999999.0

START_DATE = "2023-01-01"
END_DATE   = "2023-12-31"

OUT_DIR    = os.path.join("data", "raw")
OUT_FILE   = os.path.join(OUT_DIR, "usgs_potomac_2023.csv")

os.makedirs(OUT_DIR, exist_ok=True)

# ── Fetch in monthly chunks to stay within API limits ───────────────────────

def month_ranges(start: str, end: str):
    """Yield (start_dt, end_dt) pairs in monthly chunks."""
    cur = datetime.strptime(start, "%Y-%m-%d")
    fin = datetime.strptime(end,   "%Y-%m-%d")
    while cur <= fin:
        # Last day of month
        if cur.month == 12:
            nxt = datetime(cur.year + 1, 1, 1)
        else:
            nxt = datetime(cur.year, cur.month + 1, 1)
        chunk_end = min(nxt - timedelta(days=1), fin)
        yield cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        cur = nxt


def fetch_chunk(site: str, params: list, start: str, end: str) -> dict:
    """Fetch a single time-range chunk from USGS NWIS IV API."""
    url = (
        f"{BASE_URL}?sites={site}"
        f"&parameterCd={','.join(params)}"
        f"&startDT={start}&endDT={end}"
        f"&format=json&siteStatus=all"
    )
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"  ⚠  Attempt {attempt+1} failed: {exc}")
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {start}–{end}")


def parse_timeseries(data: dict) -> pd.DataFrame:
    """Extract all time series from a USGS JSON response into a wide DataFrame."""
    ts_list = data["value"]["timeSeries"]
    frames = {}
    for ts in ts_list:
        pcode  = ts["variable"]["variableCode"][0]["value"]
        if pcode not in PARAM_NAMES:
            continue
        col    = PARAM_NAMES[pcode]
        unit   = ts["variable"]["unit"]["unitCode"]
        values = ts["values"][0]["value"]
        if not values:
            continue
        rows = []
        for v in values:
            val = float(v["value"])
            if val == NODATA_VAL:
                val = float("nan")
            rows.append({
                "timestamp":  v["dateTime"],
                col:          val,
                f"{col}_qualifier": ",".join(v["qualifiers"]),
            })
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        frames[col] = df
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames.values(), axis=1)
    return merged.reset_index()


# ── Main download loop ────────────────────────────────────────────────────────
print(f"Downloading USGS NWIS data for site {SITE} ({SITE_NAME})")
print(f"Period: {START_DATE} → {END_DATE}")
print(f"Parameters: {list(PARAM_NAMES.values())}\n")

all_chunks = []
for start, end in month_ranges(START_DATE, END_DATE):
    print(f"  Fetching {start} → {end} …", end=" ")
    raw   = fetch_chunk(SITE, PARAMS, start, end)
    chunk = parse_timeseries(raw)
    if chunk.empty:
        print("no data")
    else:
        all_chunks.append(chunk)
        print(f"{len(chunk):,} rows")
    time.sleep(0.3)   # be polite to the API

# ── Combine and clean ─────────────────────────────────────────────────────────
df = pd.concat(all_chunks, ignore_index=True)
df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

# Normalise to UTC → local (US/Eastern) → drop tz info for simplicity
df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York").dt.tz_localize(None)

sensor_cols = list(PARAM_NAMES.values())
qual_cols   = [f"{c}_qualifier" for c in sensor_cols]

# Keep only columns that actually exist
sensor_cols = [c for c in sensor_cols if c in df.columns]
qual_cols   = [c for c in qual_cols   if c in df.columns]

df = df[["timestamp"] + sensor_cols + qual_cols]

print(f"\n── Combined dataset ──────────────────────────────────────────────")
print(f"Total rows : {len(df):,}")
print(f"Date range : {df['timestamp'].min()} → {df['timestamp'].max()}")
print(f"Columns    : {df.columns.tolist()}")
print(f"\nMissing values per sensor:")
for col in sensor_cols:
    n_miss = df[col].isna().sum()
    pct    = n_miss / len(df) * 100
    print(f"  {col:35s}  {n_miss:5,} ({pct:5.1f}% NaN)")

print(f"\nSensor statistics:")
print(df[sensor_cols].describe().round(3))

df.to_csv(OUT_FILE, index=False)
print(f"\n✅  Saved → {OUT_FILE}  ({len(df):,} rows)")

# ── Write metadata sidecar ────────────────────────────────────────────────────
meta = {
    "source":        "USGS National Water Information System (NWIS)",
    "station_id":    SITE,
    "station_name":  SITE_NAME,
    "api_url":       f"{BASE_URL}",
    "license":       "U.S. Public Domain – no copyright restriction",
    "license_url":   "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    "parameters":    PARAM_NAMES,
    "period":        f"{START_DATE} to {END_DATE}",
    "interval":      "15 minutes (instantaneous values)",
    "downloaded_at": datetime.utcnow().isoformat() + "Z",
    "rows":          len(df),
}
with open(os.path.join(OUT_DIR, "metadata.json"), "w") as f:
    json.dump(meta, f, indent=2)
print(f"✅  Saved → {os.path.join(OUT_DIR, 'metadata.json')}")
