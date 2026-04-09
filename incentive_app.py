"""
IndiaMart Incentive Calculator — April 2026

Changes in this version:
  - Employee Name is picked from the L1 column in Renewal file
  - All incentive slab ranges are loaded from Slab_Config.xlsx (no code changes needed)

Files needed:
  1. Receipt file
  2. Refund file
  3. Renewal file         ← Employee Name (L1 col) + CMR% calculated here
  4. Employee Config      ← auto-generated, fill Vintage/Team/Client Count
  5. Slab Config          ← download once, edit ranges anytime (no coding needed)

Run:  streamlit run incentive_app.py
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="IndiaMart Incentive Calculator", layout="wide", page_icon="💰")

# ═══════════════════════════════════════════════════════════════
# SS+ KEYWORDS (not in slab config — product classification)
# ═══════════════════════════════════════════════════════════════
SS_PLUS_KEYWORDS  = ["IM STAR", "IM LEADER", "STAR", "LEADER", "PREF STAR", "PREF LEADER"]
INSTA_KEYWORDS    = ["INSTA"]          # IM Insta = 0.5 productivity (KCD/CSD SPS)
HALF_YEAR_MODES   = ["HALF-YEARLY", "HALF YEARLY", "HY", "6M", "6 MONTHS"]
POP_CMR_FLOOR     = 55.0              # CSD: min CMR% to earn PoP
CALC_DATE         = __import__("datetime").date(2026, 4, 30)  # reference date for days-since-joining


# ═══════════════════════════════════════════════════════════════
# SLAB CONFIG LOADER
# ═══════════════════════════════════════════════════════════════

def build_default_slab_config():
    """
    Returns a dict of DataFrames representing every slab table.
    Used to (a) create the downloadable template and (b) as fallback if no config uploaded.
    """
    # ── CSD New Joiner (0-30D and 31-90D) ──
    csd_new = pd.DataFrame([
        {"PCDV_Threshold": 2800, "Payout": 10500},
        {"PCDV_Threshold": 2400, "Payout": 7000},
        {"PCDV_Threshold": 2100, "Payout": 5100},
        {"PCDV_Threshold": 1800, "Payout": 3100},
    ])
    csd_new_incr = pd.DataFrame([
        {"Parameter": "Incremental_Threshold", "Value": 2800},
        {"Parameter": "Incremental_Rate_%",    "Value": 3.0},
        {"Parameter": "Slab2_CMR_Multiplier_%","Value": 120},
        {"Parameter": "Min_Txn_0_30D",         "Value": 2},
        {"Parameter": "Min_Txn_31_90D",         "Value": 3},
    ])

    # ── CSD SPS 91-270D ──
    csd_sps_91 = pd.DataFrame([
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2400, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])

    # ── CSD SPS 270D+ ──
    csd_sps_270 = pd.DataFrame([
        {"PCDV_Threshold": 3000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])

    # ── CSD SPS Multipliers ──
    csd_sps_mult = pd.DataFrame([
        {"Parameter": "MDC1_Above_%",      "Value": 35,  "Multiplier_%": 120},
        {"Parameter": "MDC1_Between_%",    "Value": 25,  "Multiplier_%": 100},
        {"Parameter": "MDC1_Below_%",      "Value": 0,   "Multiplier_%": 50},
        {"Parameter": "Booster_TAT_Below", "Value": 1,   "Multiplier_%": 120},
        {"Parameter": "Booster_60D_Below", "Value": 10,  "Multiplier_%": 120},
    ])

    # ── CSD Spot (Apr 1-16) ──
    csd_spot = pd.DataFrame([
        {"Parameter": "Min_NR_Upsell_AMR",   "Value": 3},
        {"Parameter": "Base_Reward",          "Value": 1500},
        {"Parameter": "Per_Txn_After_Min",    "Value": 750},
    ])

    # ── Power of Productivity ──
    pop = pd.DataFrame([
        {"Product_Keywords": "MDC,MDC1,MDC-1,MDC 1,TS 1,TS1",                              "Incentive_Per_Txn": 500},
        {"Product_Keywords": "MDC2,MDC 2,MDC3,MDC 3,TS 2,TS2,MAXI ANNUAL,MAXIMISER,VE,IVE,WS-A", "Incentive_Per_Txn": 1000},
        {"Product_Keywords": "TS 3,TS3,MAXI 2,WS-M",                                        "Incentive_Per_Txn": 1500},
    ])

    # ── KCD Regular (270D+) ──
    kcd_270 = pd.DataFrame([
        {"PCDV_Threshold": 19000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 16000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 13000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD Regular (91-270D) ──
    kcd_91_270 = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD Regular (0-90D) ──
    kcd_0_90 = pd.DataFrame([
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 8000,  "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD HVRI ──
    kcd_hvri = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 10000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD Nagpur Pharma ──
    kcd_nagpur = pd.DataFrame([
        {"PCDV_Threshold": 32000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 28000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 24000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD Incremental Rates ──
    kcd_incr = pd.DataFrame([
        {"Vintage":  "270D+",   "Incr_Threshold": 19000, "Incr_Rate_%": 1.4},
        {"Vintage":  "91-270D", "Incr_Threshold": 17000, "Incr_Rate_%": 1.4},
        {"Vintage":  "31-90D",  "Incr_Threshold": 14000, "Incr_Rate_%": 1.4},
        {"Vintage":  "0-30D",   "Incr_Threshold": 14000, "Incr_Rate_%": 1.4},
        {"Vintage":  "HVRI",    "Incr_Threshold": 17000, "Incr_Rate_%": 1.4},
        {"Vintage":  "Nagpur",  "Incr_Threshold": 32000, "Incr_Rate_%": 0.85},
    ])

    # ── KCD Listing Slabs (% target) ──
    kcd_listing = pd.DataFrame([
        {"Target_Pct": 140, "CMR70_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"Target_Pct": 120, "CMR70_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 100, "CMR70_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_listing_rates = pd.DataFrame([
        {"Vintage":  "270D+",   "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage":  "91-270D", "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage":  "31-90D",  "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
        {"Vintage":  "0-30D",   "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
    ])

    # ── KCD Catalog Slabs ──
    kcd_catalog = pd.DataFrame([
        {"Target_Pct": 140, "CMR72_Per_Txn": 3250, "CMR80_Per_Txn": 3600},
        {"Target_Pct": 120, "CMR72_Per_Txn": 2750, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 100, "CMR72_Per_Txn": 2250, "CMR80_Per_Txn": 2400},
    ])

    # ── KCD Spot ──
    kcd_spot = pd.DataFrame([
        {"Spot_Key": "Listing_270D",  "PCDV_Threshold": 11000, "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Listing_other", "PCDV_Threshold": 7500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Catalog_270D",  "PCDV_Threshold": 3500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Catalog_other", "PCDV_Threshold": 2500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "ROI_Exec",      "PCDV_Threshold": 4000,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "KCD_0_90D",     "PCDV_Threshold": 4000,  "Base_Reward": 2500, "Per_1K_After": 1000},
    ])

    return {
        "CSD_New_Slabs":        csd_new,
        "CSD_New_Params":       csd_new_incr,
        "CSD_SPS_91_270D":      csd_sps_91,
        "CSD_SPS_270D_Plus":    csd_sps_270,
        "CSD_SPS_Multipliers":  csd_sps_mult,
        "CSD_Spot":             csd_spot,
        "Power_of_Productivity":pop,
        "KCD_Regular_270D":     kcd_270,
        "KCD_Regular_91_270D":  kcd_91_270,
        "KCD_Regular_0_90D":    kcd_0_90,
        "KCD_HVRI":             kcd_hvri,
        "KCD_Nagpur_Pharma":    kcd_nagpur,
        "KCD_Incremental_Rates":kcd_incr,
        "KCD_Listing_Slabs":    kcd_listing,
        "KCD_Listing_Rates":    kcd_listing_rates,
        "KCD_Catalog_Slabs":    kcd_catalog,
        "KCD_Spot":             kcd_spot,
    }


def load_slab_config(uploaded_file):
    """
    Load slab config from uploaded Excel.
    Returns dict of DataFrames, one per sheet.
    Falls back to defaults for any missing sheet.
    """
    defaults = build_default_slab_config()
    if uploaded_file is None:
        return defaults

    xl = pd.ExcelFile(uploaded_file)
    config = {}
    for sheet_name, default_df in defaults.items():
        if sheet_name in xl.sheet_names:
            # header=1 skips the note row written at row 0 in the template
            df_loaded = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=1)
            # Drop completely empty rows that may appear after the note
            df_loaded = df_loaded.dropna(how="all")
            config[sheet_name] = df_loaded
        else:
            config[sheet_name] = default_df   # fall back to default
    return config


def parse_slabs(cfg):
    """Convert loaded config DataFrames into the tuples the calculation functions expect."""

    # ── CSD New ──────────────────────────────────────────────
    csd_new_slabs = [
        (int(r["PCDV_Threshold"]), int(r["Payout"]))
        for _, r in cfg["CSD_New_Slabs"].iterrows()
    ]
    params = cfg["CSD_New_Params"].set_index("Parameter")["Value"].to_dict()
    csd_new_incr_thresh  = float(params.get("Incremental_Threshold", 2800))
    csd_new_incr_rate    = float(params.get("Incremental_Rate_%", 3.0)) / 100
    csd_slab2_mult       = float(params.get("Slab2_CMR_Multiplier_%", 120)) / 100
    min_txn_0_30         = int(params.get("Min_Txn_0_30D", 2))
    min_txn_31_90        = int(params.get("Min_Txn_31_90D", 3))

    # ── CSD SPS ──────────────────────────────────────────────
    csd_sps_91_270 = [
        (int(r["PCDV_Threshold"]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
        for _, r in cfg["CSD_SPS_91_270D"].iterrows()
    ]
    csd_sps_270p = [
        (int(r["PCDV_Threshold"]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
        for _, r in cfg["CSD_SPS_270D_Plus"].iterrows()
    ]

    # ── CSD SPS Multipliers ──────────────────────────────────
    mult_rows = cfg["CSD_SPS_Multipliers"].set_index("Parameter")
    mdc1_above  = float(mult_rows.loc["MDC1_Above_%",   "Value"])
    mdc1_between= float(mult_rows.loc["MDC1_Between_%", "Value"])
    mdc1_mult_hi= float(mult_rows.loc["MDC1_Above_%",   "Multiplier_%"]) / 100
    mdc1_mult_md= float(mult_rows.loc["MDC1_Between_%", "Multiplier_%"]) / 100
    mdc1_mult_lo= float(mult_rows.loc["MDC1_Below_%",   "Multiplier_%"]) / 100
    boost_tat   = float(mult_rows.loc["Booster_TAT_Below", "Value"])
    boost_d60   = float(mult_rows.loc["Booster_60D_Below", "Value"])
    boost_mult  = float(mult_rows.loc["Booster_TAT_Below", "Multiplier_%"]) / 100

    # ── CSD Spot ─────────────────────────────────────────────
    spot_params = cfg["CSD_Spot"].set_index("Parameter")["Value"].to_dict()
    csd_spot_min     = int(spot_params.get("Min_NR_Upsell_AMR", 3))
    csd_spot_base    = int(spot_params.get("Base_Reward", 1500))
    csd_spot_per_txn = int(spot_params.get("Per_Txn_After_Min", 750))

    # ── Power of Productivity ────────────────────────────────
    prod_to_pop = {}
    for _, r in cfg["Power_of_Productivity"].iterrows():
        for kw in str(r["Product_Keywords"]).split(","):
            prod_to_pop[kw.strip().upper()] = int(r["Incentive_Per_Txn"])

    # ── KCD Regular ──────────────────────────────────────────
    def to_kcd_slabs(sheet_key):
        return [
            (int(r["PCDV_Threshold"]), int(r["CMR72_Per_Txn"]), int(r["CMR80_Per_Txn"]))
            for _, r in cfg[sheet_key].iterrows()
        ]
    kcd_270_slabs    = to_kcd_slabs("KCD_Regular_270D")
    kcd_91_270_slabs = to_kcd_slabs("KCD_Regular_91_270D")
    kcd_0_90_slabs   = to_kcd_slabs("KCD_Regular_0_90D")
    kcd_hvri_slabs   = to_kcd_slabs("KCD_HVRI")
    kcd_nagpur_slabs = to_kcd_slabs("KCD_Nagpur_Pharma")

    # ── KCD Incremental Rates ────────────────────────────────
    kcd_incr = {}
    for _, r in cfg["KCD_Incremental_Rates"].iterrows():
        kcd_incr[str(r["Vintage"])] = (float(r["Incr_Threshold"]), float(r["Incr_Rate_%"]) / 100)

    # ── KCD Listing ──────────────────────────────────────────
    kcd_listing_slabs = [
        (int(r["Target_Pct"]), int(r["CMR70_Per_Txn"]), int(r["CMR80_Per_Txn"]))
        for _, r in cfg["KCD_Listing_Slabs"].iterrows()
    ]
    kcd_listing_rates = {}
    for _, r in cfg["KCD_Listing_Rates"].iterrows():
        kcd_listing_rates[str(r["Vintage"])] = (float(r["Base_Client_Rate"]), float(r["Listing_Client_Rate"]))

    # ── KCD Catalog ──────────────────────────────────────────
    kcd_catalog_slabs = [
        (int(r["Target_Pct"]), int(r["CMR72_Per_Txn"]), int(r["CMR80_Per_Txn"]))
        for _, r in cfg["KCD_Catalog_Slabs"].iterrows()
    ]

    # ── KCD Spot ─────────────────────────────────────────────
    kcd_spot = {}
    for _, r in cfg["KCD_Spot"].iterrows():
        kcd_spot[str(r["Spot_Key"])] = {
            "thresh": int(r["PCDV_Threshold"]),
            "base":   int(r["Base_Reward"]),
            "per1k":  int(r["Per_1K_After"]),
        }

    return {
        # CSD New
        "csd_new_slabs":       csd_new_slabs,
        "csd_new_incr_thresh": csd_new_incr_thresh,
        "csd_new_incr_rate":   csd_new_incr_rate,
        "csd_slab2_mult":      csd_slab2_mult,
        "min_txn_0_30":        min_txn_0_30,
        "min_txn_31_90":       min_txn_31_90,
        # CSD SPS
        "csd_sps_91_270":      csd_sps_91_270,
        "csd_sps_270p":        csd_sps_270p,
        "mdc1_above":          mdc1_above,
        "mdc1_between":        mdc1_between,
        "mdc1_mult_hi":        mdc1_mult_hi,
        "mdc1_mult_md":        mdc1_mult_md,
        "mdc1_mult_lo":        mdc1_mult_lo,
        "boost_tat":           boost_tat,
        "boost_d60":           boost_d60,
        "boost_mult":          boost_mult,
        # CSD Spot
        "csd_spot_min":        csd_spot_min,
        "csd_spot_base":       csd_spot_base,
        "csd_spot_per_txn":    csd_spot_per_txn,
        # PoP
        "prod_to_pop":         prod_to_pop,
        # KCD Regular
        "kcd_270_slabs":       kcd_270_slabs,
        "kcd_91_270_slabs":    kcd_91_270_slabs,
        "kcd_0_90_slabs":      kcd_0_90_slabs,
        "kcd_hvri_slabs":      kcd_hvri_slabs,
        "kcd_nagpur_slabs":    kcd_nagpur_slabs,
        "kcd_incr":            kcd_incr,
        # KCD Listing/Catalog
        "kcd_listing_slabs":   kcd_listing_slabs,
        "kcd_listing_rates":   kcd_listing_rates,
        "kcd_catalog_slabs":   kcd_catalog_slabs,
        # KCD Spot
        "kcd_spot":            kcd_spot,
    }


def make_slab_config_excel():
    """Generate the downloadable Slab_Config.xlsx template."""
    defaults = build_default_slab_config()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        hdr_fmt  = w.book.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF", "border": 1})
        note_fmt = w.book.add_format({"italic": True, "font_color": "#595959", "text_wrap": True})
        for sheet_name, df in defaults.items():
            # Row 0 = note, Row 1 = headers (written by startrow=1), Row 2+ = data
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws = w.sheets[sheet_name]
            ws.set_column(0, len(df.columns) - 1, 22)
            # Overwrite header row with blue formatting
            for col_num, col_name in enumerate(df.columns):
                ws.write(1, col_num, col_name, hdr_fmt)
            # Note row above headers
            ws.write(0, 0, f"NOTE — Sheet: {sheet_name} | Edit values in rows below. Do NOT rename columns.", note_fmt)
            ws.set_row(0, 18)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# CMR AUTO-CALCULATION
# ═══════════════════════════════════════════════════════════════

def find_col(df, candidates):
    """Return the first column name from candidates that exists in df, or None."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def load_structure_dump(uploaded_file):
    """
    Load the Employee Structure Dump file.
    Derives Vintage, Team, Client Count, Joining Date from it automatically.
    Returns a dict keyed by Employee ID string.
    """
    if uploaded_file is None:
        return {}

    df = load_excel(uploaded_file)
    df.columns = df.columns.str.strip()

    emp_col     = find_col(df, ["Employee ID", "Emp ID", "EmpID"])
    name_col    = find_col(df, ["Employee Name", "Name"])
    vertical_col= find_col(df, ["IIL Vertical Name", "Vertical", "IIL Vertical"])
    location_col= find_col(df, ["Location", "LOCATION"])
    joining_col = find_col(df, ["Joining Date", "DOJ", "Date of Joining"])
    final_grp   = find_col(df, ["Final Group", "FinalGroup"])
    vintage_bkt = find_col(df, ["Vintage Bucket", "VintageBucket"])
    remarks_col = find_col(df, ["Remarks"])
    client_a    = find_col(df, ["Client-A", "Client A", "ClientA", "Actual Client"])
    client_c    = find_col(df, ["Client-C", "Client C", "ClientC", "Calculated Client"])
    l2_col      = find_col(df, ["L2 Name", "L2Name", "L2"])
    l3_col      = find_col(df, ["L3 Name", "L3Name", "L3"])
    l4_col      = find_col(df, ["L4 Name", "L4Name", "L4"])
    l5_col      = find_col(df, ["L5 Name", "L5Name", "L5"])

    result = {}
    for _, row in df.iterrows():
        if not emp_col:
            break
        eid = str(row[emp_col]).strip()
        if not eid or eid.lower() in ("nan", ""):
            continue

        vertical = str(row[vertical_col]).strip().upper() if vertical_col else ""
        location = str(row[location_col]).strip()        if location_col else ""
        vintage  = str(row[final_grp]).strip()           if final_grp    else "91-270D"
        vbucket  = str(row[vintage_bkt]).strip()         if vintage_bkt  else ""
        remarks  = str(row[remarks_col]).strip()         if remarks_col  else "-"
        loc_up   = location.upper()
        vbucket_up = vbucket.upper()
        rem_up   = remarks.upper()

        # ── Derive Team from Vertical + Vintage Bucket + Remarks + Location ──
        if "CSD" in vertical:
            if any(x in vbucket_up for x in ["SPS", "90+ DAYS", "90+DAYS"]):
                team = "SPS (CSD 91D+)"
            elif any(x in vbucket_up for x in ["0-90 DAYS", "0-90DAYS", "CSD ROI"]):
                team = "0-90 Days (CSD new)"
            else:
                team = "SPS (CSD 91D+)"          # fallback for CSD
        elif "KCD" in vertical:
            if rem_up == "LISTING":
                team = "Listing (KCD)"
            elif rem_up == "CATALOG":
                team = "Catalog (KCD)"
            elif "ROI" in vbucket_up or "ROI" in loc_up:
                team = "ROI KCD"
            elif any(c in loc_up for c in ["HYDERABAD", "VASHI", "RAIPUR", "INDORE"]):
                team = "HVRI KCD"
            elif "NAGPUR" in loc_up:
                team = "Nagpur Pharma KCD"
            else:
                team = "Regular KCD"
        else:
            team = "Regular KCD"

        # ── Client Count: Calculated (CSD) or Actual (KCD) ──
        if "CSD" in vertical:
            raw_cc = row[client_c] if client_c else None
            cc = max(float(raw_cc) if raw_cc and str(raw_cc) not in ("nan","") else 100, 50)
        else:
            raw_cc = row[client_a] if client_a else None
            cc = float(raw_cc) if raw_cc and str(raw_cc) not in ("nan","") else 100

        # ── Joining Date ──
        jd = None
        if joining_col:
            jd_raw = row[joining_col]
            if jd_raw and str(jd_raw).strip() not in ("", "nan", "NaT"):
                jd = jd_raw

        result[eid] = {
            "Employee Name": str(row[name_col]).strip() if name_col else "",
            "Vertical":      str(row[vertical_col]).strip() if vertical_col else "",
            "Location":      location,
            "Joining Date":  jd,
            "Vintage":       vintage,
            "Team":          team,
            "Client Count":  cc,
            "L2 Name":       str(row[l2_col]).strip() if l2_col else "",
            "L3 Name":       str(row[l3_col]).strip() if l3_col else "",
            "L4 Name":       str(row[l4_col]).strip() if l4_col else "",
            "L5 Name":       str(row[l5_col]).strip() if l5_col else "",
            "Vintage Bucket":vbucket,
            "Remarks":       remarks,
        }
    return result


def is_insta(prod_str):
    """IM Insta products count as 0.5 productivity."""
    return any(k in str(prod_str).upper() for k in INSTA_KEYWORDS)


def calc_productivity(rnl_prods, rnl_modes, scheme_type):
    """
    Calculate weighted productivity score from received renewals.

    scheme_type:
      "csd_new"  → CSD 0-30D/31-90D: Annual+MYR only; IM Insta excluded
      "csd_sps"  → CSD 91D+/270D+:   all received; IM Insta = 0.5
      "kcd"      → KCD:               all received; IM Insta = 0.5

    Returns (float score, int insta_count, int regular_count)
    """
    score = 0.0
    insta_count = 0
    regular_count = 0

    for prod, mode in zip(rnl_prods, rnl_modes):
        mode_up = str(mode).upper().strip()
        prod_up = str(prod).upper().strip()

        if scheme_type == "csd_new":
            # Only Annual & Multi Year; IM Insta excluded completely
            if mode_up not in ("ANNUAL", "MULTI YEAR", "MULTIYEAR", "MYR"):
                continue
            if is_insta(prod_up):
                continue          # IM Insta: NOT counted for CSD 0-90D PoP
            score += 1.0
            regular_count += 1

        elif scheme_type in ("csd_sps", "kcd"):
            if is_insta(prod_up):
                score += 0.5
                insta_count += 1
            else:
                score += 1.0
                regular_count += 1

    return score, insta_count, regular_count


def load_cmr_targets(uploaded_file):
    """
    Load per-employee CMR% slab targets from the targets file.
    Expected columns: Employee ID, Slab 1, Slab 2
    Returns dict: { emp_id_str: {"slab1": float, "slab2": float} }
    """
    if uploaded_file is None:
        return {}
    try:
        df = load_excel(uploaded_file)
        df.columns = df.columns.str.strip()

        emp_col   = find_col(df, ["Employee ID", "Emp ID", "EmpID", "ID"])
        slab1_col = find_col(df, ["Slab 1", "Slab1", "SLAB 1", "slab1",
                                  "CMR Slab 1", "Target Slab 1"])
        slab2_col = find_col(df, ["Slab 2", "Slab2", "SLAB 2", "slab2",
                                  "CMR Slab 2", "Target Slab 2"])

        if not emp_col:
            st.warning("CMR Targets file: could not find Employee ID column.")
            return {}

        result = {}
        for _, row in df.iterrows():
            eid = str(row[emp_col]).strip()
            if not eid or eid.lower() in ("nan", ""):
                continue
            s1 = float(row[slab1_col]) if slab1_col and pd.notna(row[slab1_col]) else 0.70
            s2 = float(row[slab2_col]) if slab2_col and pd.notna(row[slab2_col]) else 0.80
            # Excel stores percentages as decimals (70% → 0.70)
            # Convert to 0-100 scale if values are in 0-1 range
            if s1 <= 1.0:
                s1 = round(s1 * 100, 4)
            if s2 <= 1.0:
                s2 = round(s2 * 100, 4)
            result[eid] = {"slab1": s1, "slab2": s2}
        return result
    except Exception as e:
        st.error(f"Error loading CMR Targets file: {e}")
        return {}


def calc_cmr_per_employee(renewal_df):
    if renewal_df is None:
        return {}

    df = renewal_df.copy()

    # ── Detect column names flexibly ─────────────────────────
    emp_id_col  = find_col(df, ["EMP ID", "Emp ID", "EmpID", "Employee ID", "EMPID"])
    status_col  = find_col(df, ["Status", "STATUS", "status"])
    product_col = find_col(df, ["DCR Services", "WS/MDC Main", "WS/MDC", "Product",
                                "PRODUCT", "Prod", "Service", "SERVICE", "WS MDC Main"])
    l1_col      = find_col(df, ["L1", "L1 Name", "L1Name", "l1", "Sales Rep",
                                "Sales Rep.", "Sales Executive"])
    mode_col    = find_col(df, ["Mode", "MODE", "Deal Mode", "Renewal Mode"])

    if emp_id_col is None:
        st.warning("⚠️ Renewal file: could not find Employee ID column. "
                   f"Available columns: {list(df.columns)}")
        return {}

    df[emp_id_col] = df[emp_id_col].astype(str)

    # Status: received flag
    if status_col:
        df["_received"] = df[status_col].astype(str).str.upper().str.contains("RECEIVED", na=False)
    else:
        df["_received"] = False

    # SS+ product flag
    if product_col:
        df["_is_ss_plus"] = df[product_col].astype(str).str.upper().apply(
            lambda p: any(k in p for k in SS_PLUS_KEYWORDS)
        )
    else:
        df["_is_ss_plus"] = False

    result = {}
    for emp_id, grp in df.groupby(emp_id_col):
        total_sent     = len(grp)
        total_received = int(grp["_received"].sum())
        cmr_pct        = round(total_received / total_sent * 100, 2) if total_sent > 0 else 0.0

        ss_grp      = grp[grp["_is_ss_plus"]]
        ss_sent     = len(ss_grp)
        ss_received = int(ss_grp["_received"].sum())
        ss_cmr_pct  = round(ss_received / ss_sent * 100, 2) if ss_sent > 0 else 0.0

        # L1 name — first non-blank value
        l1_name = ""
        if l1_col:
            names = grp[l1_col].dropna().astype(str).str.strip()
            names = names[names != ""]
            l1_name = names.iloc[0] if len(names) > 0 else ""

        result[str(emp_id)] = {
            "cmr_pct":          cmr_pct,
            "ss_cmr_pct":       ss_cmr_pct,
            "renewal_sent":     int(total_sent),
            "renewal_received": total_received,
            "ss_sent":          int(ss_sent),
            "ss_received":      ss_received,
            "l1_name":          l1_name,
        }
    return result


def get_cmr_slab(cmr_pct, sent_count, slab1_target, slab2_target):
    if sent_count <= 3:
        return 1, "Forced Slab 1 (≤3 sent)"
    if cmr_pct >= slab2_target:
        return 2, f"Slab 2 (CMR {cmr_pct:.1f}% ≥ {slab2_target}%)"
    if cmr_pct >= slab1_target:
        return 1, f"Slab 1 (CMR {cmr_pct:.1f}% ≥ {slab1_target}%)"
    return 0, f"Below Slab 1 (CMR {cmr_pct:.1f}% < {slab1_target}%)"


def get_kcd_cmr_col(cmr_pct, sent_count, slab1_target, slab2_target):
    if sent_count <= 3:
        return 1, "Forced col 1 (≤3 sent)"
    if cmr_pct >= slab2_target:
        return 2, f"CMR {cmr_pct:.1f}% ≥ {slab2_target}%"
    if cmr_pct >= slab1_target:
        return 1, f"CMR {cmr_pct:.1f}% ≥ {slab1_target}%"
    return 0, f"CMR {cmr_pct:.1f}% < {slab1_target}%"


# ═══════════════════════════════════════════════════════════════
# CALCULATION FUNCTIONS  (all values come from parsed slab config)
# ═══════════════════════════════════════════════════════════════

def pcdv_slab(pcdv, slabs, col):
    for thresh, r1, r2 in slabs:
        if pcdv >= thresh:
            return thresh, (r2 if col == 2 else r1)
    return 0, 0


def pop_for_product(prod_str, prod_to_pop):
    p = str(prod_str).upper().strip()
    for key, val in prod_to_pop.items():
        if key in p:
            return val
    return 0


def calc_csd_new(pcdv, client_c, cmr_slab, cmr_pct_achieved,
                 rnl_prods, rnl_modes, vintage, S):
    """
    CSD 0-30D / 31-90D base + PoP.
    - Base: fixed PCDV slab, CMR slab multiplier (slab 0 still earns at 100%)
    - PoP:  Annual/MYR only, IM Insta excluded, min CMR 55% gate
    """
    min_txn = S["min_txn_0_30"] if vintage == "0-30D" else S["min_txn_31_90"]

    # Base incentive
    base  = next((r for t, r in S["csd_new_slabs"] if pcdv >= t), 0)
    incr  = (pcdv - S["csd_new_incr_thresh"]) * client_c * S["csd_new_incr_rate"]             if pcdv > S["csd_new_incr_thresh"] else 0
    mult  = S["csd_slab2_mult"] if cmr_slab == 2 else 1.0
    base_total = (base + incr) * mult

    # Productivity (Annual + MYR only; IM Insta excluded)
    prod_score, _, reg_count = calc_productivity(rnl_prods, rnl_modes, "csd_new")

    # PoP eligibility: min transactions AND min 55% CMR
    pop = 0
    pop_reason = ""
    if cmr_pct_achieved < POP_CMR_FLOOR:
        pop_reason = f"PoP blocked: CMR {cmr_pct_achieved:.1f}% < {POP_CMR_FLOOR}% min"
    elif prod_score < min_txn:
        pop_reason = f"PoP blocked: {prod_score} txns < {min_txn} min"
    else:
        eligible = [p for p, m in zip(rnl_prods, rnl_modes)
                    if str(m).upper() in ("ANNUAL", "MULTI YEAR", "MULTIYEAR", "MYR")
                    and not is_insta(p)]
        pop = sum(pop_for_product(p, S["prod_to_pop"]) for p in eligible)
        pop_reason = f"PoP earned: {prod_score} txns × CMR {cmr_pct_achieved:.1f}%"

    notes = (f"CSD {vintage} | PCDV:{round(pcdv)} | clients:{int(client_c)} | "
             f"CMR slab:{cmr_slab} | {pop_reason}")
    return round(base_total, 0), round(pop, 0), notes


def calc_csd_sps(pcdv, rnl_prods, rnl_modes, cmr_slab, vintage,
                mdc1_cmr, ext_tat, d60, S):
    """
    CSD SPS 91-270D / 270D+.
    - No PoP scheme for this vintage.
    - Productivity includes IM Insta as 0.5.
    - CMR slab 0 → per_txn = 0 → incentive = 0.
    """
    slabs = S["csd_sps_270p"] if vintage == "270D+" else S["csd_sps_91_270"]
    _, per_txn = pcdv_slab(pcdv, slabs, cmr_slab)

    # Use weighted productivity (Insta = 0.5) for transaction count
    prod_score, insta_cnt, reg_cnt = calc_productivity(rnl_prods, rnl_modes, "csd_sps")
    # Use actual received renewal count as txn_count for incentive calc
    txn_count = len(rnl_prods)

    if mdc1_cmr > S["mdc1_above"]:
        mdc1_mult = S["mdc1_mult_hi"]
    elif mdc1_cmr >= S["mdc1_between"]:
        mdc1_mult = S["mdc1_mult_md"]
    else:
        mdc1_mult = S["mdc1_mult_lo"]

    booster = S["boost_mult"] if (ext_tat is not None and d60 is not None
                                  and ext_tat < S["boost_tat"]
                                  and d60 < S["boost_d60"]) else 1.0

    total = per_txn * txn_count * mdc1_mult * booster
    notes = (f"CSD SPS {vintage} | PCDV:{round(pcdv)} | CMR slab:{cmr_slab} | "
             f"₹{per_txn}/txn×{txn_count} (score:{prod_score:.1f} incl {insta_cnt}×Insta) | "
             f"MDC1:{mdc1_mult} boost:{booster} | No PoP")
    return round(total, 0), notes


def calc_kcd_regular(pcdv, txn_count, cmr_col_val, vintage, location, ss_cmr_pct, S):
    loc = str(location).upper()
    if "NAGPUR" in loc:
        _, per_txn = pcdv_slab(pcdv, S["kcd_nagpur_slabs"], cmr_col_val)
        i_thresh, i_rate = S["kcd_incr"].get("Nagpur", (32000, 0.0085))
        incr = (pcdv - i_thresh) * i_rate if pcdv > i_thresh else 0
    elif any(c in loc for c in ["HYDERABAD", "VASHI", "RAIPUR", "INDORE"]):
        _, per_txn = pcdv_slab(pcdv, S["kcd_hvri_slabs"], cmr_col_val)
        i_thresh, i_rate = S["kcd_incr"].get("HVRI", (17000, 0.014))
        incr = (pcdv - i_thresh) * i_rate if pcdv > i_thresh else 0
    else:
        slabs = {"270D+": S["kcd_270_slabs"], "91-270D": S["kcd_91_270_slabs"]}.get(
            vintage, S["kcd_0_90_slabs"])
        _, per_txn = pcdv_slab(pcdv, slabs, cmr_col_val)
        i_thresh, i_rate = S["kcd_incr"].get(vintage, (14000, 0.014))
        incr = (pcdv - i_thresh) * i_rate if pcdv > i_thresh else 0
    ss_mult = 1.0 if ss_cmr_pct >= 72 else 0.5
    return round((per_txn * txn_count + incr) * ss_mult, 0), \
           f"KCD Regular {vintage} | PCDV:{round(pcdv)} | ₹{per_txn}/txn | SS+:{ss_mult}"


def calc_kcd_listing(net_dv, base_c, list_c, txn_count, cmr_col_val, vintage, ss_cmr_pct, S):
    rates  = S["kcd_listing_rates"].get(vintage, (7000, 22000))
    target = base_c * rates[0] + list_c * rates[1]
    if target == 0:
        return 0, "Target=0"
    achv    = (net_dv / target) * 100
    per_txn = next((r2 if cmr_col_val == 2 else r1
                    for t, r1, r2 in S["kcd_listing_slabs"] if achv >= t), 0)
    incr    = ((achv - 140) / 100 * target * 0.014) if achv > 140 else 0
    ss_mult = 1.0 if ss_cmr_pct >= 72 else 0.5
    return round((per_txn * txn_count + incr) * ss_mult, 0), \
           f"KCD Listing {vintage} | Achv:{round(achv,1)}% | SS+:{ss_mult}"


def calc_kcd_catalog(net_dv, base_c, list_c, txn_count, cmr_col_val, vintage, btl_sales, ss_cmr_pct, S):
    rates  = S["kcd_listing_rates"].get(vintage, (7000, 22000))
    target = base_c * rates[0] + list_c * rates[1]
    if target == 0:
        return 0, "Target=0"
    achv    = (net_dv / target) * 100
    per_txn = next((r2 if cmr_col_val == 2 else r1
                    for t, r1, r2 in S["kcd_catalog_slabs"] if achv >= t), 0)
    incr     = ((achv - 140) / 100 * target * 0.014) if achv > 140 else 0
    btl_mult = 1.2 if btl_sales >= 2 else 1.0
    ss_mult  = 1.0 if ss_cmr_pct >= 72 else 0.5
    return round((per_txn * txn_count + incr) * btl_mult * ss_mult, 0), \
           f"KCD Catalog {vintage} | Achv:{round(achv,1)}% | BTL:{btl_mult} | SS+:{ss_mult}"


def calc_spot_kcd(pcdv, spot_key, mult_met, S):
    cfg = S["kcd_spot"].get(spot_key, {})
    if not cfg or pcdv < cfg["thresh"]:
        return 0
    raw = cfg["base"] + max(0, int((pcdv - cfg["thresh"]) / 1000)) * cfg["per1k"]
    return round(raw * (1.25 if mult_met else 0.5), 0)


def calc_spot_csd(nr_upsell, S):
    if nr_upsell < S["csd_spot_min"]:
        return 0
    return S["csd_spot_base"] + (nr_upsell - S["csd_spot_min"]) * S["csd_spot_per_txn"]


# ═══════════════════════════════════════════════════════════════
# DATA HELPERS
# ═══════════════════════════════════════════════════════════════

@st.cache_data
def load_excel(f):
    """Load xlsx or xlsb files."""
    name = f.name if hasattr(f, "name") else str(f)
    if name.lower().endswith(".xlsb"):
        try:
            return pd.read_excel(f, engine="pyxlsb")
        except Exception:
            st.error("Reading .xlsb files requires pyxlsb. Run: pip install pyxlsb")
            return pd.DataFrame()
    return pd.read_excel(f)


def clean_receipt(df):
    df = df.copy()
    if "B/C" in df.columns:
        df = df[df["B/C"].isna() | (df["B/C"].astype(str).str.strip() == "")]
    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.upper().str.strip() == "CLEARED"]
    prod_col = find_col(df, ["Prod", "Product", "PRODUCT"])
    if "MODE" in df.columns and prod_col:
        nach = (df["MODE"].astype(str).str.upper().str.contains("NACH", na=False)) & \
               (df[prod_col].astype(str).str.upper().str.contains("BALANCE|BL", na=False))
        df = df[~nach]
    return df


def build_emp_list(receipt_df):
    cols  = {"Sales Exec ID": "Employee ID",
             "Manager": "L2 Name", "HOD - 1": "L3 Name", "HOD": "L4 Name",
             "Location": "Location", "Vertical": "Vertical"}
    avail = {k: v for k, v in cols.items() if k in receipt_df.columns}
    emp   = receipt_df[list(avail.keys())].rename(columns=avail).drop_duplicates("Employee ID")
    emp["Employee ID"] = emp["Employee ID"].astype(str)
    return emp.reset_index(drop=True)


def get_transactions(receipt_df, refund_df, renewal_df, emp_id):
    eid       = int(emp_id) if str(emp_id).isdigit() else emp_id
    rec       = receipt_df[receipt_df["Sales Exec ID"] == eid]
    total_dv  = rec["WT AMT"].fillna(0).sum()
    txn_count = len(rec)
    _prod_col = find_col(receipt_df, ["Prod", "Product", "PRODUCT"])
    prods     = rec[_prod_col].fillna("").tolist() if _prod_col else []
    ref       = refund_df[refund_df["Sales Ex. ID"] == eid]
    total_ref = ref["WT Amount"].fillna(0).sum()
    rnl_prods = []
    rnl_modes = []
    rnl_count = 0
    if renewal_df is not None:
        _eid_col     = find_col(renewal_df, ["EMP ID", "Emp ID", "EmpID", "Employee ID"])
        _status_col  = find_col(renewal_df, ["Status", "STATUS"])
        _product_col = find_col(renewal_df, ["DCR Services", "WS/MDC Main", "WS/MDC",
                                             "Product", "Prod", "Service", "WS MDC Main"])
        _mode_col    = find_col(renewal_df, ["Mode", "MODE", "Deal Mode", "Renewal Mode"])
        if _eid_col and _status_col:
            rnl = renewal_df[
                (renewal_df[_eid_col] == eid) &
                (renewal_df[_status_col].astype(str).str.upper().str.contains("RECEIVED", na=False))
            ]
            rnl_prods = rnl[_product_col].fillna("").tolist() if _product_col else []
            rnl_modes = rnl[_mode_col].fillna("").tolist()    if _mode_col    else []
            rnl_count = len(rnl)
    # Also fetch ALL renewal rows (not just received) for sent-count calculation
    all_rnl_count = 0
    if renewal_df is not None:
        _eid_all = find_col(renewal_df, ["EMP ID", "Emp ID", "EmpID", "Employee ID"])
        if _eid_all:
            all_rnl_count = len(renewal_df[renewal_df[_eid_all] == eid])

    return total_dv - total_ref, txn_count, prods, rnl_prods, rnl_modes, rnl_count, total_ref, all_rnl_count


def resolve_emp_name(emp_id, cfg_row, emp_cmr, emp_row):
    """
    Name priority:
      1. L1 column in Renewal file   (most accurate — actual employee name)
      2. Employee Config file
      3. Receipt file Sales Rep. column
      4. Empty string
    """
    l1_name  = emp_cmr.get("l1_name", "").strip()
    cfg_name = str(cfg_row.get("Employee Name", "")).strip()
    rec_name = str(emp_row.get("Employee Name", "")).strip()  # was Sales Rep. in receipt
    return l1_name or cfg_name or rec_name or ""


def route_calc(emp_row, cfg_row, cmr_data, net_dv, txn_count, prods,
               rnl_prods, rnl_modes, rnl_count, sb, S, joining_date=None):
    """
    Main routing. All fixes applied:
    - Days Since Joining calculated
    - Productivity uses weighted score (Insta=0.5)
    - PoP only for CSD 0-30D/31-90D; gated by 55% CMR floor
    - CMR slab 0 kills incentive for SPS (per-txn = 0)
    - IM Insta excluded from CSD 0-90D PoP; counted as 0.5 for SPS/KCD
    """
    vertical   = str(cfg_row.get("Vertical", emp_row.get("Vertical", ""))).upper()
    location   = str(cfg_row.get("Location", emp_row.get("Location", "")))
    vintage    = str(cfg_row.get("Vintage",   "91-270D"))
    team       = str(cfg_row.get("Team",      ""))
    client_cnt = max(float(cfg_row.get("Client Count", 100) or 100),
                     50 if "CSD" in vertical else 1)
    pcdv       = net_dv / client_cnt if client_cnt > 0 else 0

    cmr_pct    = cmr_data.get("cmr_pct",    0.0)
    ss_cmr_pct = cmr_data.get("ss_cmr_pct", 0.0)
    rnl_sent   = cmr_data.get("renewal_sent", 0)   # total sent (all statuses)

    # Days since joining
    days_since_joining = ""
    if joining_date:
        try:
            import datetime
            jd = joining_date if isinstance(joining_date, datetime.date) else                  __import__("pandas").to_datetime(joining_date).date()
            days_since_joining = (CALC_DATE - jd).days
        except Exception:
            days_since_joining = ""

    # Productivity scores
    prod_score_new, _, _  = calc_productivity(rnl_prods, rnl_modes, "csd_new")  # for CSD 0-90D
    prod_score_sps, insta_cnt_sps, _ = calc_productivity(rnl_prods, rnl_modes, "csd_sps")

    base_inc = pop_inc = spot_inc = 0
    notes = cmr_note = ""

    # ── CSD ──────────────────────────────────────────────────
    if "CSD" in vertical:
        cmr_slab, cmr_note = get_cmr_slab(
            cmr_pct, rnl_sent, sb["csd_slab1_target"], sb["csd_slab2_target"])

        if vintage in ("0-30D", "31-90D"):
            # PoP scheme only for new joiners
            base_inc, pop_inc, notes = calc_csd_new(
                pcdv, client_cnt, cmr_slab, cmr_pct,
                rnl_prods, rnl_modes, vintage, S)
        else:
            # SPS — no PoP; Insta = 0.5; productivity from renewal file
            base_inc, notes = calc_csd_sps(
                pcdv, rnl_prods, rnl_modes, cmr_slab, vintage,
                sb["mdc1_cmr"], sb["ext_tat"], sb["d60"], S)
            spot_inc = calc_spot_csd(sb["nr_upsell"], S)

    # ── KCD ──────────────────────────────────────────────────
    elif "KCD" in vertical:
        kcd_col, cmr_note = get_kcd_cmr_col(
            cmr_pct, rnl_sent, sb["kcd_slab1_target"], sb["kcd_slab2_target"])
        team_up = team.upper()

        # KCD productivity (Insta = 0.5)
        kcd_prod_score, kcd_insta_cnt, _ = calc_productivity(rnl_prods, rnl_modes, "kcd")

        if "LISTING" in team_up:
            star_c = sum(1 for p in rnl_prods
                         if any(k in str(p).upper() for k in ["STAR", "LEADER", "PREF"]))
            list_c = max(star_c, 1); base_c = max(client_cnt - list_c, 1)
            base_inc, notes = calc_kcd_listing(
                net_dv, base_c, list_c, rnl_count or txn_count,
                kcd_col, vintage, ss_cmr_pct, S)
            spot_inc = calc_spot_kcd(
                pcdv, "Listing_270D" if vintage == "270D+" else "Listing_other",
                sb["spot_met"], S)
        elif "CATALOG" in team_up:
            star_c = sum(1 for p in rnl_prods
                         if any(k in str(p).upper() for k in ["STAR", "LEADER", "PREF"]))
            list_c = max(star_c, 1); base_c = max(client_cnt - list_c, 1)
            base_inc, notes = calc_kcd_catalog(
                net_dv, base_c, list_c, rnl_count or txn_count,
                kcd_col, vintage, sb["btl_sales"], ss_cmr_pct, S)
            spot_inc = calc_spot_kcd(
                pcdv, "Catalog_270D" if vintage == "270D+" else "Catalog_other",
                sb["spot_met"], S)
        elif "ROI" in team_up:
            base_inc, notes = calc_kcd_regular(
                pcdv, txn_count, kcd_col, vintage, location, ss_cmr_pct, S)
            spot_inc = calc_spot_kcd(pcdv, "ROI_Exec", sb["spot_met"], S)
        else:
            base_inc, notes = calc_kcd_regular(
                pcdv, txn_count, kcd_col, vintage, location, ss_cmr_pct, S)
            if vintage in ("0-30D", "31-90D"):
                spot_inc = calc_spot_kcd(pcdv, "KCD_0_90D", sb["spot_met"], S)

    return {
        "Days Since Joining":  days_since_joining,
        "CMR% (auto)":         round(cmr_pct, 1),
        "SS+ CMR% (auto)":     round(ss_cmr_pct, 1),
        "Renewals Sent":       rnl_sent,
        "Renewals Received":   cmr_data.get("renewal_received", 0),
        "CMR Slab":            cmr_note,
        "Productivity Score":  round(prod_score_new if "CSD" in vertical
                                     and vintage in ("0-30D","31-90D")
                                     else prod_score_sps, 1),
        "Insta Txns (0.5×)":   insta_cnt_sps,
        "Base Incentive (₹)":  int(base_inc),
        "PoP Incentive (₹)":   int(pop_inc),
        "Spot Incentive (₹)":  int(spot_inc),
        "Total Incentive (₹)": int(base_inc + pop_inc + spot_inc),
        "Net Deal Value (₹)":  int(net_dv),
        "PCDV":                round(pcdv, 0),
        "Receipt Txns":        txn_count,
        "Renewal Txns":        rnl_count,
        "Scheme":              notes,
    }
# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════

st.title("💰 IndiaMart Incentive Calculator — April 2026")
st.caption("Employee name from Renewal L1 column | CMR% auto-calculated | Slabs editable via config file")

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Files")
    receipt_file    = st.file_uploader("1. Receipt file",           type=["xlsx"])
    refund_file     = st.file_uploader("2. Refund file",            type=["xlsx"])
    renewal_file    = st.file_uploader("3. Renewal file",           type=["xlsx"])
    structure_file  = st.file_uploader("4. Employee Structure Dump",type=["xlsx"])
    slab_cfg_file   = st.file_uploader("5. Slab Config (optional)", type=["xlsx"])

    st.divider()
    st.header("🎯 CMR% Targets File")
    st.caption("Upload the monthly targets file (xlsx or xlsb).")
    cmr_target_file = st.file_uploader("6. CMR Targets file", type=["xlsx", "xlsb"])
    st.info("Individual Slab 1 & 2 targets are loaded per employee from this file.\n\n≤3 renewals sent → auto-forced Slab 1", icon="ℹ️")

    st.divider()
    st.header("⚙️ Other Parameters")
    with st.expander("CSD SPS (91D+ vintage)"):
        def_mdc1 = st.number_input("MDC-1 CMR+1%",   0.0, 100.0, 30.0)
        def_tat  = st.number_input("Ext. Ticket TAT", 0.0, 10.0,  1.5)
        def_d60  = st.number_input("60D Not Met %",   0.0, 100.0, 12.0)
    with st.expander("Spot Rate (Apr 1–16 only)"):
        def_nr   = st.number_input("CSD NR Upsell/AMR count", 0, 50, 0)
        def_btl  = st.number_input("KCD Base-to-Listing sales", 0, 20, 0)
        def_spot = st.checkbox("KCD Spot multiplier met (≥2 SS+ sales)?")

    sb = dict(mdc1_cmr=def_mdc1, ext_tat=def_tat, d60=def_d60,
              nr_upsell=def_nr, btl_sales=def_btl, spot_met=def_spot)

    st.divider()
    calc_btn = st.button("▶ Calculate", type="primary", use_container_width=True)


# ── Slab Config download ──────────────────────────────────────
st.subheader("Step 0 — Download Slab Config (one-time setup)")
with st.expander("What is the Slab Config file?", expanded=not slab_cfg_file):
    st.markdown("""
The **Slab Config** is an Excel file with one sheet per incentive table.
Edit any value in it — PCDV thresholds, payout amounts, incremental rates — and
upload it in the sidebar. The app will use your updated values immediately.
**You never need to touch the Python code to change incentive ranges.**

Sheets included:
| Sheet | What it controls |
|---|---|
| CSD_New_Slabs | PCDV thresholds + fixed payouts for 0-30D and 31-90D |
| CSD_New_Params | Incremental rate, CMR multiplier, min transaction counts |
| CSD_SPS_91_270D | Per-txn rates for 91-270D vintage |
| CSD_SPS_270D_Plus | Per-txn rates for 270D+ vintage |
| CSD_SPS_Multipliers | MDC-1 multiplier thresholds + booster conditions |
| CSD_Spot | NR Upsell min count, base reward, per-txn reward |
| Power_of_Productivity | Product keywords → PoP incentive amount |
| KCD_Regular_270D/91_270D/0_90D | KCD PCDV slabs per vintage |
| KCD_HVRI | Hyderabad/Vashi/Raipur/Indore specific slabs |
| KCD_Nagpur_Pharma | Nagpur Pharma specific slabs |
| KCD_Incremental_Rates | Incremental threshold + rate per vintage |
| KCD_Listing_Slabs + Rates | Listing team % achievement payouts |
| KCD_Catalog_Slabs | Catalog team % achievement payouts |
| KCD_Spot | Spot rate thresholds + rewards |
    """)

st.download_button(
    "⬇️ Download Slab Config template",
    data=make_slab_config_excel(),
    file_name="Slab_Config.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# Load and parse slab config (uses defaults if not uploaded)
slab_cfg_raw = load_slab_config(slab_cfg_file)
S = parse_slabs(slab_cfg_raw)

if slab_cfg_file:
    st.success("✅ Custom Slab Config loaded — using your edited values.")
else:
    st.info("No Slab Config uploaded — using built-in default values.", icon="ℹ️")


# ── Step 1: Structure Dump info ──────────────────────────────
st.subheader("Step 1 — Upload your Employee Structure file")

with st.expander("What columns does the app read from this file?", expanded=True):
    st.markdown("""
| Column | Used for |
|--------|----------|
| **Employee ID** | Links to Receipt, Refund, Renewal files |
| **IIL Vertical Name** | Routes to CSD or KCD scheme |
| **Location** | HVRI / Nagpur Pharma / ROI detection for KCD |
| **Joining Date** | Calculates Days Since Joining |
| **Final Group** | Vintage: `0-30D` / `31-90D` / `91-270D` / `270D+` |
| **Vintage Bucket** | Team scheme: `SPS` / `0-90 Days` / `Delhi KCD` etc. |
| **Remarks** | KCD sub-team: `Listing` / `Catalog` / `-` |
| **Client-C** | Calculated clients → CSD PCDV denominator |
| **Client-A** | Actual clients → KCD PCDV denominator |
| **L2–L6 Name** | Manager hierarchy in report |
    """)

if structure_file:
    struct_map = load_structure_dump(structure_file)
    if struct_map is not None and len(struct_map) > 0:
        struct_preview = pd.DataFrame([
            {"Employee ID": k, "Name": v["Employee Name"],
             "Vertical": v["Vertical"], "Vintage": v["Vintage"],
             "Team": v["Team"], "Client Count": v["Client Count"],
             "Location": v["Location"],
             "Joining Date": str(v["Joining Date"])[:10] if v["Joining Date"] else ""}
            for k, v in struct_map.items()
        ])
        st.success(f"✅ Structure file loaded — {len(struct_map)} employees auto-configured")
        with st.expander("Preview auto-derived settings per employee"):
            st.dataframe(struct_preview, use_container_width=True, hide_index=True)
    else:
        st.error("Could not read the structure file. Check column names.")
else:
    st.info("Upload the Employee Structure Dump in the sidebar to continue.", icon="⬆️")

st.subheader("Step 2 — Calculate Incentives")

# ── Step 2: Calculate ─────────────────────────────────────────
st.subheader("Step 2 — Calculate Incentives")

if not (receipt_file and refund_file and renewal_file and structure_file):
    st.info("4 files required: Receipt + Refund + Renewal + Employee Structure Dump. "
            "CMR Targets and Slab Config are optional.", icon="📂")
    st.stop()

receipt_df  = clean_receipt(load_excel(receipt_file))
refund_df   = load_excel(refund_file)
renewal_df  = load_excel(renewal_file)
struct_map  = load_structure_dump(structure_file)
cmr_targets = load_cmr_targets(cmr_target_file)

if not struct_map:
    st.error("Could not read Employee Structure Dump. Check the file format.")
    st.stop()
if not cmr_targets:
    st.warning("⚠️ No CMR Targets file — fallback defaults: Slab 1=70%, Slab 2=80% applied.", icon="⚠️")

# Normalise EMP ID column in renewal file
_eid = find_col(renewal_df, ["EMP ID", "Emp ID", "EmpID", "Employee ID"])
if _eid:
    renewal_df[_eid] = renewal_df[_eid].astype(str)
cmr_map = calc_cmr_per_employee(renewal_df)

# Build emp_df for receipt-side hierarchy fallback
emp_df = build_emp_list(receipt_df)

with st.expander("Loaded file summary"):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Employees (structure)", len(struct_map))
    c2.metric("Receipt rows",          len(receipt_df))
    c3.metric("Refund rows",           len(refund_df))
    c4.metric("Renewal rows",          len(renewal_df))
    c5.metric("CMR% auto-calc for",    len(cmr_map))
    if cmr_targets:
        st.success(f"✅ CMR Targets loaded for {len(cmr_targets)} employees")
    else:
        st.warning("⚠️ No CMR Targets — fallback 70%/80% applied")

if calc_btn:
    results = []
    prog    = st.progress(0, "Calculating…")

    emp_ids = list(struct_map.keys())
    for i, emp_id in enumerate(emp_ids):
        s = struct_map[emp_id]          # all employee details from structure dump

        emp_cmr = cmr_map.get(emp_id, {
            "cmr_pct": 0.0, "ss_cmr_pct": 0.0,
            "renewal_sent": 0, "renewal_received": 0,
            "ss_sent": 0, "ss_received": 0, "l1_name": "",
        })

        # Employee name: L1 from renewal > structure dump name
        emp_name = emp_cmr.get("l1_name", "").strip() or s["Employee Name"]

        # Per-employee CMR targets
        emp_targets = cmr_targets.get(emp_id, {"slab1": 70.0, "slab2": 80.0})
        emp_sb = {**sb,
                  "csd_slab1_target": emp_targets["slab1"],
                  "csd_slab2_target": emp_targets["slab2"],
                  "kcd_slab1_target": emp_targets["slab1"],
                  "kcd_slab2_target": emp_targets["slab2"]}

        net_dv, txn_count, prods, rnl_prods, rnl_modes, rnl_count, total_ref, all_rnl_count = \
            get_transactions(receipt_df, refund_df, renewal_df, emp_id)

        # Build cfg_row and emp_row from structure map
        cfg_row = {
            "Vertical":     s["Vertical"],
            "Location":     s["Location"],
            "Vintage":      s["Vintage"],
            "Team":         s["Team"],
            "Client Count": s["Client Count"],
            "Joining Date": s["Joining Date"],
        }
        emp_row = {
            "Vertical":     s["Vertical"],
            "Location":     s["Location"],
            "L2 Name":      s["L2 Name"],
            "L3 Name":      s["L3 Name"],
            "L4 Name":      s["L4 Name"],
            "L5 Name":      s["L5 Name"],
        }

        inc = route_calc(emp_row, cfg_row, emp_cmr,
                         net_dv, txn_count, prods,
                         rnl_prods, rnl_modes, rnl_count,
                         emp_sb, S, joining_date=s["Joining Date"])

        results.append({
            "Employee ID":        emp_id,
            "Employee Name":      emp_name,
            "Vertical":           s["Vertical"],
            "Vintage":            s["Vintage"],
            "Team":               s["Team"],
            "Vintage Bucket":     s["Vintage Bucket"],
            "Location":           s["Location"],
            "L2":                 s["L2 Name"],
            "L3":                 s["L3 Name"],
            "CMR Slab1 Target":   emp_targets["slab1"],
            "CMR Slab2 Target":   emp_targets["slab2"],
            "Refund (₹)":         int(total_ref),
            **inc,
        })
        prog.progress((i + 1) / len(emp_ids), f"Processing {i+1}/{len(emp_ids)}…")

    prog.empty()
    res = pd.DataFrame(results)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Employees",        len(res))
    m2.metric("Total Payout",     f"₹{res['Total Incentive (₹)'].sum():,.0f}")
    m3.metric("Avg per Employee", f"₹{res['Total Incentive (₹)'].mean():,.0f}")
    m4.metric("Total Deal Value", f"₹{res['Net Deal Value (₹)'].sum():,.0f}")
    m5.metric("Avg CMR%",         f"{res['CMR% (auto)'].mean():.1f}%")

    st.markdown("#### CMR% Distribution")
    d1, d2, d3 = st.columns(3)
    d1.metric("Slab 2", len(res[res["CMR Slab"].str.contains("Slab 2", na=False)]))
    d2.metric("Slab 1", len(res[res["CMR Slab"].str.contains("Slab 1", na=False)]))
    d3.metric("Forced / Below", len(res[res["CMR Slab"].str.contains("Forced|Below", na=False)]))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Incentive by Vertical**")
        st.bar_chart(res.groupby("Vertical")["Total Incentive (₹)"].sum())
    with col2:
        st.markdown("**Incentive by Vintage**")
        st.bar_chart(res.groupby("Vintage")["Total Incentive (₹)"].sum())
    with col3:
        st.markdown("**CMR% by Vertical**")
        st.bar_chart(res.groupby("Vertical")["CMR% (auto)"].mean())

    st.subheader("Employee-wise Breakdown")
    f1, f2, f3 = st.columns(3)
    vf    = f1.multiselect("Vertical", res["Vertical"].unique(), default=res["Vertical"].unique())
    vint  = f2.multiselect("Vintage",  res["Vintage"].unique(),  default=res["Vintage"].unique())
    min_i = f3.number_input("Min Incentive ≥ ₹", 0, int(res["Total Incentive (₹)"].max() or 1), 0)
    filtered = res[res["Vertical"].isin(vf) & res["Vintage"].isin(vint)
                   & (res["Total Incentive (₹)"] >= min_i)]

    display_cols = [c for c in [
        "Employee ID", "Employee Name", "Vertical", "Vintage", "Team",
        "Vintage Bucket", "Location", "L2", "Days Since Joining",
        "CMR% (auto)", "CMR Slab1 Target", "CMR Slab2 Target",
        "SS+ CMR% (auto)", "Renewals Sent", "Renewals Received", "CMR Slab",
        "Productivity Score", "Insta Txns (0.5×)",
        "Receipt Txns", "Renewal Txns", "Net Deal Value (₹)", "Refund (₹)", "PCDV",
        "Base Incentive (₹)", "PoP Incentive (₹)", "Spot Incentive (₹)",
        "Total Incentive (₹)", "Scheme",
    ] if c in filtered.columns]

    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        res.to_excel(w, sheet_name="Incentives", index=False)
        res.groupby(["Vertical", "Vintage", "Team"]).agg(
            Employees=("Employee ID", "count"),
            Avg_CMR=("CMR% (auto)", "mean"),
            Total_Incentive=("Total Incentive (₹)", "sum"),
            Avg_Incentive=("Total Incentive (₹)", "mean"),
        ).reset_index().to_excel(w, sheet_name="Summary", index=False)
        res[["Employee ID", "Employee Name", "Vertical", "Vintage",
             "CMR% (auto)", "SS+ CMR% (auto)", "Renewals Sent",
             "Renewals Received", "CMR Slab"]].to_excel(
            w, sheet_name="CMR Details", index=False)
        z = res[res["Total Incentive (₹)"] == 0]
        if len(z):
            z.to_excel(w, sheet_name="Zero Incentive", index=False)

    st.download_button("⬇️ Download Full Report (Excel)", out.getvalue(),
                       f"Incentives_{datetime.today().strftime('%d%m%Y')}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.expander(f"Zero incentive employees ({len(res[res['Total Incentive (₹)']==0])})"):
        z = res[res["Total Incentive (₹)"] == 0]
        if z.empty:
            st.success("All employees earned an incentive.")
        else:
            st.dataframe(z[["Employee ID", "Employee Name", "Vertical", "Vintage",
                             "CMR% (auto)", "CMR Slab", "Net Deal Value (₹)", "Scheme"]],
                         use_container_width=True, hide_index=True)
