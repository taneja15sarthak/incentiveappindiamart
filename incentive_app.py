"""
IndiaMart Incentive Calculator — April 2026

Changes in this version (v19):
  - Fix 1: MDC1_PRODUCTS — removed MDC 2 Year / MDC 3 Year (multi-year, not MDC-1)
            → MDC-1 CMR% per employee now accurate → correct 1.2×/1.0×/0.5× multiplier
  - Fix 2: SPS Booster — auto 1.2× for Vintage Bucket = 'SPS' employees (not sidebar-gated)
            Pune TAT/60D override still works for non-SPS employees
  - Fix 3: CSD Spot — per-employee NR upsell count from receipt (replaces global sidebar)
  - Fix 4: KCD transaction count — uses prod_score_receipt (productive rows only)
            not txn_count (all receipt rows) → base incentive now matches sir's calc
  - Fix 5: KCD SS+ penalty — only applied when ss_sent ≥ 3 AND ss_cmr < 70%
            (≤2 SS+ sent = no penalty, not enough data)
  - Fix 6: KCD Incremental — (Net_Deal_Val − Collection_Target) × 1.4%
            Collection_Target = PCR_Target × ClientA from structure dump
  - Fix 7: Listing/Catalog — use collection_target directly (not base_c×rate + list_c×rate)

Files needed:
  1. Receipt file
  2. Refund file
  3. Renewal file         ← Employee Name (L1 col) + CMR% calculated here
  4. Employee Structure Dump
  5. CMR Targets file     ← per-employee Slab 1 / Slab 2 targets
  6. Slab Config (optional) ← download once, edit ranges anytime

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

# ── Productivity tier mapping (Receipt file: Product + Upsell columns) ──
# Maps to PoP incentive: Tier1=₹500, Tier2=₹1000, Tier3=₹1500
PURE_RENEWAL_PRODUCTS = {
    "Renewal","TS1Renewal","TS2Renewal","TS3Renewal","WS Renewal","IVE Renewal",
    "SS Renewal","IM SS Renewal","LS Renewal","IM LS Renewal","Pref SS Renewal",
    "Pref LS Renewal","FPL Renewal","IM IL Renewal","CL Renewal","IL Renewal",
    "Pref IL Renewal","Adv Renewal","Adv WS Renewal","Adv SS Renewal",
    "Adv LS Renewal","Adv IM SS Renewal","Adv IM LS Renewal","Adv IVE Renewal",
    "IM Insta Renewal","Adv Pref Renewal","Adv Pref SS Renewal",
}

# Upsell column values → service tier
UPSELL_TIER1 = {"Combo 1YR","TS Pro-1","Maxi Pro-1","TS pro-1"}
UPSELL_TIER2 = {
    "MYR","Combo 2YR","Maximiser","TS Pro-2","Maxi Pro-2",
    "VEXPS-MYR","VEXPG-12","VEXPS-12","VEXPS-6","VEXPD-6",
    "VEXPD-12","VEXPG-6","VEXPG-MYR","VEXPP-12","VEXPP-MYR","VEXPD-MYR",
}
UPSELL_TIER3 = {
    "Combo 3YR","TS Pro-3","Maxi Pro-3","Maximiser-3","Maxi pro-3","Maximiser-2",
    "IM Star Pro","Preferred Star Pro","IM Leader Pro","Preferred Leader Pro",
}

# Product column values → service tier (when Upsell is blank)
PROD_TIER1 = {"Renewal","MDC Annual","TS1Renewal","TS Pro-1","TS pro-1","Maxi Pro-1"}
PROD_TIER2 = {"TS2Renewal","WS Renewal","IVE Renewal","Combo 2YR","Maxi Pro-2",
              "TS Pro-2","Maximiser","VEXPS-12","VEXPS-MYR","VEXPG-12","VEXPG-MYR",
              "VEXPD-12","VEXPD-MYR","VEXPP-12","VEXPP-MYR","Adv WS Renewal","Adv IVE Renewal"}
PROD_TIER3 = {"TS3Renewal","SS Renewal","IM SS Renewal","LS Renewal","IM LS Renewal",
              "Pref SS Renewal","Pref LS Renewal","CL Renewal","IL Renewal",
              "IM IL Renewal","Pref IL Renewal","Combo 3YR","TS Pro-3","Maxi Pro-3",
              "Maximiser-3","Maxi pro-3","Adv SS Renewal","Adv LS Renewal",
              "Adv IM SS Renewal","Adv IM LS Renewal","Adv Pref SS Renewal",
              "IM Star Pro","Preferred Star Pro","IM Leader Pro","Preferred Leader Pro"}

TIER_REWARD = {1: 500, 2: 1000, 3: 1500}

# IM Insta products (0.5 productivity)
INSTA_PRODUCTS = {"IM InstaDiamond","IM InstaGold","IM InstaPlatinum",
                  "IM insta Diamond","IM Insta Renewal"}
INSTA_KEYWORDS    = ["INSTA"]          # IM Insta = 0.5 productivity (KCD/CSD SPS)

# MDC-1 products for per-employee MDC-1 CMR% calculation (CSD SPS)
# Only true 1-year / annual MDC products — MDC 2 Year / MDC 3 Year are multi-year, NOT MDC-1
MDC1_PRODUCTS = {
    "Mini Dynamic Catalog.", "Mini Dynamic Catalog", "MDC Annual",
    "Mini Dynamic Catalog Pro", "MDC 1 Year", "MDC-1", "MDC1",
    "MDC Annual Renewal",
}
HALF_YEAR_MODES   = ["HALF-YEARLY", "HALF YEARLY", "HY", "6M", "6 MONTHS"]
POP_CMR_FLOOR     = 55.0              # CSD: min CMR% to earn PoP
CALC_DATE         = __import__("datetime").date(2026, 4, 30)  # reference date for days-since-joining
EXCEL_EPOCH       = __import__("datetime").date(1899, 12, 30)  # Excel serial date base

def _to_date(val):
    """Convert any date-like value to a Python date object.
    Handles: Excel serial ints, pandas Timestamp, datetime, date string."""
    import datetime as _dt
    import pandas as _pd
    if val is None:
        return None
    if isinstance(val, _dt.date) and not isinstance(val, _dt.datetime):
        return val
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _pd.Timestamp):
        return val.date()
    # Excel serial number (xlsb stores dates as integers ~40000-50000 for 2009-2036)
    try:
        fval = float(val)
        if not (fval != fval):  # not NaN
            if 30000 < fval < 60000:  # reasonable Excel serial range for 1982-2064
                return EXCEL_EPOCH + __import__("datetime").timedelta(days=int(fval))
    except (TypeError, ValueError):
        pass
    # Try string parsing
    try:
        return _pd.to_datetime(str(val)).date()
    except Exception:
        return None


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

    # ── CSD Relationship Manager slabs (Mar'26: PCR 3800/4300/4800) ──
    # Slab1 = CMR 55%, Slab2 = CMR 60%
    csd_rm = pd.DataFrame([
        {"PCDV_Threshold": 4800, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1750},
        {"PCDV_Threshold": 4300, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 3800, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
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
        "CSD_RM":               csd_rm,
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
    # CSD Relationship Manager slabs (different from Exec slabs)
    csd_rm_slabs = [
        (int(r["PCDV_Threshold"]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
        for _, r in cfg.get("CSD_RM", cfg["CSD_SPS_91_270D"]).iterrows()
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
        "csd_rm_slabs":        csd_rm_slabs,
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



def build_march_slab_config():
    """March 2026 scheme slabs (PCR-based)."""
    import pandas as pd

    # CSD New 0-30D and 31-90D (PCR)
    csd_new = pd.DataFrame([
        {"PCDV_Threshold": 5000, "Payout": 10500},
        {"PCDV_Threshold": 4500, "Payout": 7000},
        {"PCDV_Threshold": 4000, "Payout": 5100},
        {"PCDV_Threshold": 3500, "Payout": 3100},
        {"PCDV_Threshold": 3000, "Payout": 3100},
    ])
    csd_new_params = pd.DataFrame([
        {"Parameter": "Incremental_Threshold", "Value": 5000},
        {"Parameter": "Incremental_Rate_%",    "Value": 3.0},
        {"Parameter": "Slab2_CMR_Multiplier_%","Value": 120},
        {"Parameter": "Min_Txn_0_30D",         "Value": 3},
        {"Parameter": "Min_Txn_31_90D",         "Value": 4},
    ])
    # CSD SPS 91-270D (PCR)
    csd_sps_91 = pd.DataFrame([
        {"PCDV_Threshold": 5000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 4500, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 4000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])
    # CSD SPS 270D+ (PCR)
    csd_sps_270 = pd.DataFrame([
        {"PCDV_Threshold": 6000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 5500, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 5000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])
    # CSD Relationship Manager (March'26 PCR slabs)
    csd_rm = pd.DataFrame([
        {"PCDV_Threshold": 4800, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1750},
        {"PCDV_Threshold": 4300, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 3800, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
    ])
    csd_sps_mult = pd.DataFrame([
        {"Parameter": "MDC1_Above_%",      "Value": 35, "Multiplier_%": 120},
        {"Parameter": "MDC1_Between_%",    "Value": 25, "Multiplier_%": 100},
        {"Parameter": "MDC1_Below_%",      "Value": 0,  "Multiplier_%": 50},
        {"Parameter": "Booster_TAT_Below", "Value": 1,  "Multiplier_%": 120},
        {"Parameter": "Booster_60D_Below", "Value": 10, "Multiplier_%": 120},
    ])
    csd_spot = pd.DataFrame([
        {"Parameter": "Min_NR_Upsell_AMR", "Value": 3},
        {"Parameter": "Base_Reward",        "Value": 1500},
        {"Parameter": "Per_Txn_After_Min",  "Value": 750},
    ])
    pop = pd.DataFrame([
        {"Product_Keywords": "MDC,MDC1,MDC-1,MDC 1,TS 1,TS1", "Incentive_Per_Txn": 500},
        {"Product_Keywords": "MDC2,MDC 2,MDC3,MDC 3,TS 2,TS2,MAXI ANNUAL,MAXIMISER,VE,IVE,WS-A", "Incentive_Per_Txn": 1000},
        {"Product_Keywords": "TS 3,TS3,MAXI 2,WS-M", "Incentive_Per_Txn": 1500},
    ])
    # KCD March (PCR-based)
    kcd_270 = pd.DataFrame([
        {"PCDV_Threshold": 32000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 29000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 26000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_91_270 = pd.DataFrame([
        {"PCDV_Threshold": 30000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 25000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 22000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_0_90 = pd.DataFrame([
        {"PCDV_Threshold": 21000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 18000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 15000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_hvri = pd.DataFrame([
        {"PCDV_Threshold": 30000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 25000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 22000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_nagpur = pd.DataFrame([
        {"PCDV_Threshold": 88000, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"PCDV_Threshold": 84000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 80000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
    ])
    kcd_incr = pd.DataFrame([
        {"Vintage": "270D+",   "Incr_Threshold": 32000, "Incr_Rate_%": 1.4},
        {"Vintage": "91-270D", "Incr_Threshold": 30000, "Incr_Rate_%": 1.4},
        {"Vintage": "31-90D",  "Incr_Threshold": 21000, "Incr_Rate_%": 1.4},
        {"Vintage": "0-30D",   "Incr_Threshold": 21000, "Incr_Rate_%": 1.4},
        {"Vintage": "HVRI",    "Incr_Threshold": 30000, "Incr_Rate_%": 1.4},
        {"Vintage": "Nagpur",  "Incr_Threshold": 88000, "Incr_Rate_%": 0.85},
    ])
    kcd_listing = pd.DataFrame([
        {"Target_Pct": 140, "CMR70_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"Target_Pct": 120, "CMR70_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 100, "CMR70_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"Target_Pct": 95,  "CMR70_Per_Txn": 1750, "CMR80_Per_Txn": 2000},
    ])
    kcd_listing_rates = pd.DataFrame([
        {"Vintage": "270D+",   "Base_Client_Rate": 8500, "Listing_Client_Rate": 48000},
        {"Vintage": "91-270D", "Base_Client_Rate": 8500, "Listing_Client_Rate": 48000},
        {"Vintage": "31-90D",  "Base_Client_Rate": 6000, "Listing_Client_Rate": 34000},
        {"Vintage": "0-30D",   "Base_Client_Rate": 6000, "Listing_Client_Rate": 34000},
    ])
    kcd_catalog = pd.DataFrame([
        {"Target_Pct": 140, "CMR72_Per_Txn": 3250, "CMR80_Per_Txn": 3600},
        {"Target_Pct": 120, "CMR72_Per_Txn": 2750, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 100, "CMR72_Per_Txn": 2250, "CMR80_Per_Txn": 2400},
        {"Target_Pct": 90,  "CMR72_Per_Txn": 1750, "CMR80_Per_Txn": 2000},
    ])
    kcd_spot = pd.DataFrame([
        {"Spot_Key": "Listing_270D",  "PCDV_Threshold": 11000, "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Listing_other", "PCDV_Threshold": 7500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Catalog_270D",  "PCDV_Threshold": 3500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "Catalog_other", "PCDV_Threshold": 2500,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "ROI_Exec",      "PCDV_Threshold": 4000,  "Base_Reward": 2500, "Per_1K_After": 1000},
        {"Spot_Key": "KCD_0_90D",     "PCDV_Threshold": 4000,  "Base_Reward": 2500, "Per_1K_After": 1000},
    ])
    return {
        "CSD_New_Slabs": csd_new, "CSD_New_Params": csd_new_params,
        "CSD_SPS_91_270D": csd_sps_91, "CSD_SPS_270D_Plus": csd_sps_270,
        "CSD_RM": csd_rm,
        "CSD_SPS_Multipliers": csd_sps_mult, "CSD_Spot": csd_spot,
        "Power_of_Productivity": pop,
        "KCD_Regular_270D": kcd_270, "KCD_Regular_91_270D": kcd_91_270,
        "KCD_Regular_0_90D": kcd_0_90, "KCD_HVRI": kcd_hvri,
        "KCD_Nagpur_Pharma": kcd_nagpur, "KCD_Incremental_Rates": kcd_incr,
        "KCD_Listing_Slabs": kcd_listing, "KCD_Listing_Rates": kcd_listing_rates,
        "KCD_Catalog_Slabs": kcd_catalog, "KCD_Spot": kcd_spot,
    }

@st.cache_data(show_spinner=False)
def make_slab_config_excel():
    """Generate the downloadable Slab_Config.xlsx template. Cached — only built once."""
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


@st.cache_data(show_spinner=False)
def make_march_slab_config_excel():
    """Generate the downloadable March 2026 Slab_Config.xlsx. Cached — only built once."""
    defaults = build_march_slab_config()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        hdr_fmt  = w.book.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF", "border": 1})
        note_fmt = w.book.add_format({"italic": True, "font_color": "#595959"})
        for sheet_name, df in defaults.items():
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws = w.sheets[sheet_name]
            ws.set_column(0, len(df.columns) - 1, 22)
            for col_num, col_name in enumerate(df.columns):
                ws.write(1, col_num, col_name, hdr_fmt)
            ws.write(0, 0, f"MARCH 2026 (PCR) — {sheet_name} | Edit values below, do NOT rename columns.", note_fmt)
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




def get_available_months(receipt_df, renewal_df):
    """Return sorted list of available months as 'Mon-YY' strings."""
    months = set()
    # From receipt Entry Date
    date_col = find_col(receipt_df, ["Entry Date", "Clear Date", "Receipt Date"])
    if date_col:
        dates = pd.to_datetime(receipt_df[date_col], errors="coerce").dropna()
        for d in dates:
            months.add(d.strftime("%b-%y"))
    # From renewal Month column (format: "Feb'26")
    if renewal_df is not None:
        rnl_month_col = find_col(renewal_df, ["Month", "MONTH"])
        if rnl_month_col:
            for m in renewal_df[rnl_month_col].dropna().unique():
                try:
                    parsed = pd.to_datetime(str(m), format="%b'%y", errors="coerce")
                    if pd.notna(parsed):
                        months.add(parsed.strftime("%b-%y"))
                except Exception:
                    pass
    return sorted(months, key=lambda x: pd.to_datetime(x, format="%b-%y"))


def filter_by_month(receipt_df, refund_df, renewal_df, selected_month):
    """
    Filter all three dataframes to the selected month.
    selected_month format: 'Feb-26'
    """
    target = pd.to_datetime(selected_month, format="%b-%y")
    target_month = target.month
    target_year  = target.year
    target_str   = target.strftime("%b'%y")   # e.g. "Feb'26" for renewal

    # ── Receipt: filter by Entry Date ────────────────────────
    r = receipt_df.copy()
    date_col = find_col(r, ["Entry Date", "Clear Date", "Receipt Date"])
    if date_col:
        r[date_col] = pd.to_datetime(r[date_col], errors="coerce")
        r = r[r[date_col].dt.month == target_month]
        r = r[r[date_col].dt.year  == target_year]

    # ── Refund: filter by Clear Date ─────────────────────────
    ref = refund_df.copy()
    ref_date = find_col(ref, ["Clear Date", "Month"])
    if ref_date:
        ref[ref_date] = pd.to_datetime(ref[ref_date], errors="coerce")
        mask = (ref[ref_date].dt.month == target_month) &                (ref[ref_date].dt.year  == target_year)
        ref = ref[mask]

    # ── Renewal: filter by Month column ──────────────────────
    rnl = renewal_df.copy() if renewal_df is not None else None
    if rnl is not None:
        rnl_m = find_col(rnl, ["Month", "MONTH"])
        if rnl_m:
            # Renewal Month format is "Feb'26" / "Mar'26" etc.
            def _match(val):
                try:
                    s = str(val).strip()
                    parsed = pd.to_datetime(s, format="%b'%y", errors="coerce")
                    if pd.notna(parsed):
                        return parsed.month == target_month and parsed.year == target_year
                except Exception:
                    pass
                return False
            rnl = rnl[rnl[rnl_m].apply(_match)]

    return r, ref, rnl

def enrich_receipt(df):
    """
    Add Productivity (1/0) and Service_Tier (1/2/3/0) columns to receipt df.
    Mirrors the script logic using actual column names in receipt file.

    Productivity = 1 if:
      - Upsell column is not blank  (upsell deal)
      - OR Product is pure renewal AND no upsell exists for that receipt ID

    Service_Tier:
      1 = MDC Annual / TS-1 / Combo 1YR  → ₹500 PoP
      2 = MYR / TS-2 / Maxi Annual / VE  → ₹1,000 PoP
      3 = TS-3 / Maxi-2 / SS / LS        → ₹1,500 PoP
      0 = Insta (0.5), Balance, TDS etc.
    """
    df = df.copy()

    # Normalise columns
    prod_col   = find_col(df, ["Product", "Prod", "PRODUCT"])
    upsell_col = find_col(df, ["Upsell", "UPSELL", "Unique", "UNIQUE"])  # March receipt uses "Unique"
    rcpt_id    = find_col(df, ["Receipts ID", "Receipt ID", "ReceiptID"])

    def _str(val):
        return str(val).strip() if val is not None and str(val).strip() != "nan" else ""

    # Step 1: flag upsell rows
    if upsell_col:
        df["_is_upsell"] = df[upsell_col].apply(lambda x: _str(x) != "")
    else:
        df["_is_upsell"] = False

    # Step 2: flag pure renewal rows
    if prod_col:
        df["_is_pure_renewal"] = df[prod_col].apply(
            lambda x: _str(x) in PURE_RENEWAL_PRODUCTS)
    else:
        df["_is_pure_renewal"] = False

    # Step 3: set of receipt IDs that have a REAL upsell (WT AMT > 0)
    # A zero-WT-AMT upsell row is a tagging row only; the renewal on same receipt
    # still counts as its own productive transaction (confirmed from sir's calc).
    wt_col = find_col(df, ["WT AMT", "WT_AMT", "WTAMT"])
    if rcpt_id and wt_col:
        real_upsell_mask = df["_is_upsell"].astype(bool) & (df[wt_col].fillna(0) > 0)
        real_upsell_ids  = set(df.loc[real_upsell_mask, rcpt_id].tolist())
        df["_has_upsell_on_receipt"] = df[rcpt_id].isin(real_upsell_ids)
    elif rcpt_id:
        upsell_ids = set(df.loc[df["_is_upsell"].astype(bool), rcpt_id].tolist())
        df["_has_upsell_on_receipt"] = df[rcpt_id].isin(upsell_ids)
    else:
        df["_has_upsell_on_receipt"] = df["_is_upsell"].astype(bool)

    # Step 4: Productivity — cast to bool first (Arrow-backed pandas fix)
    is_upsell        = df["_is_upsell"].astype(bool)
    is_pure_renewal  = df["_is_pure_renewal"].astype(bool)
    has_upsell       = df["_has_upsell_on_receipt"].astype(bool)

    df["Productivity"] = (
        is_upsell | (is_pure_renewal & ~has_upsell)
    ).astype(int)

    # Step 5: Service tier
    def _tier(row):
        if row["Productivity"] != 1:
            prod = _str(row[prod_col]) if prod_col else ""
            if prod in INSTA_PRODUCTS:
                return 0.5   # Insta = 0.5 productivity
            return 0

        upsell = _str(row[upsell_col]) if upsell_col else ""
        prod   = _str(row[prod_col])   if prod_col   else ""

        if upsell:
            if upsell in UPSELL_TIER1:  return 1
            if upsell in UPSELL_TIER2:  return 2
            if upsell in UPSELL_TIER3:  return 3
            if "MYR" in upsell.upper(): return 2
            return 3   # unknown upsell → highest tier
        else:
            if prod in PROD_TIER1: return 1
            if prod in PROD_TIER2: return 2
            if prod in PROD_TIER3: return 3
            return 0

    df["Service_Tier"] = df.apply(_tier, axis=1)

    # Cleanup helper cols
    df.drop(columns=["_is_upsell","_is_pure_renewal","_has_upsell_on_receipt"],
            inplace=True, errors="ignore")
    return df


def calc_mdc1_cmr_per_employee(renewal_df, mdc_client_counts=None):
    """
    Calculate MDC-1 CMR% per employee from renewal file.
    MDC-1 products = Mini Dynamic Catalog / MDC Annual etc. (Annual mode only, not Multi Year)
    
    mdc_client_counts: optional dict {emp_id_str: int} from structure file's MDC column.
                       If provided, used as the sent denominator (more accurate than row count).
    Returns dict: { emp_id_str: {"mdc1_sent", "mdc1_recd", "mdc1_cmr_pct"} }
    """
    if renewal_df is None:
        return {}

    emp_col     = find_col(renewal_df, ["EMP ID","Emp ID","EmpID","Employee ID"])
    status_col  = find_col(renewal_df, ["Status","STATUS"])
    product_col = find_col(renewal_df, ["WS/MDC Main","DCR Services","Product","Prod","Service"])
    mode_col    = find_col(renewal_df, ["Mode","MODE","Deal Mode","Renewal Mode"])

    if not emp_col or not product_col:
        return {}

    df = renewal_df.copy()
    df[emp_col] = df[emp_col].astype(str)

    # Only Annual MDC products count for MDC-1 CMR (not Multi Year)
    is_mdc1_prod = df[product_col].apply(
        lambda p: any(k.upper() in str(p).upper() for k in MDC1_PRODUCTS)
    )
    if mode_col:
        is_annual = df[mode_col].astype(str).str.upper().isin(
            ["ANNUAL", "ANNUAL ", " ANNUAL"])
        df_mdc1 = df[is_mdc1_prod & is_annual].copy()
    else:
        df_mdc1 = df[is_mdc1_prod].copy()

    if status_col:
        df_mdc1["_recv"] = df_mdc1[status_col].astype(str).str.upper().str.contains(
            "RECEIVED", na=False)
    else:
        df_mdc1["_recv"] = False

    result = {}
    for emp_id, grp in df_mdc1.groupby(emp_col):
        eid_str = str(emp_id)
        recd    = int(grp["_recv"].sum())
        # Denominator: use structure file MDC client count if available, else row count
        if mdc_client_counts and eid_str in mdc_client_counts:
            sent = mdc_client_counts[eid_str]
        else:
            sent = len(grp)
        pct = round(recd / sent * 100, 2) if sent > 0 else 0.0
        result[eid_str] = {"mdc1_sent": sent, "mdc1_recd": recd, "mdc1_cmr_pct": pct}
    
    # Also handle employees with MDC clients in structure but 0 received in renewal
    if mdc_client_counts:
        for eid_str, cnt in mdc_client_counts.items():
            if eid_str not in result and cnt > 0:
                result[eid_str] = {"mdc1_sent": cnt, "mdc1_recd": 0, "mdc1_cmr_pct": 0.0}
    return result

def load_structure_dump(uploaded_file):
    """
    Load the Employee Structure Dump file.
    Derives Vintage, Team, Client Count, Joining Date from it automatically.
    Returns a dict keyed by Employee ID string.
    """
    if uploaded_file is None:
        return {}

    df = _read_file(uploaded_file)
    df.columns = df.columns.str.strip()

    # Normalise column names to lowercase for flexible matching
    df.columns = [str(c).strip() for c in df.columns]

    emp_col     = find_col(df, ["Employee ID", "Emp ID", "EmpID", "employeeid"])
    name_col    = find_col(df, ["Employee Name", "Name", "employeename"])
    vertical_col= find_col(df, ["IIL Vertical Name", "Vertical", "IIL Vertical",
                                "emp_vertical_name", "emp_fun_area_name"])
    location_col= find_col(df, ["Location", "LOCATION", "emp_loc"])
    joining_col = find_col(df, ["Joining Date", "DOJ", "Date of Joining",
                                "emp_joining_date"])
    # "New Location/ROI Location" / "Textile Group & CSD KCD & NSD to CSD" carry the vintage
    # string (270D+, 91-270D, 31-90D, 0-30D) in the employee_structure.xlsx format
    final_grp   = find_col(df, ["Final Group", "FinalGroup", "bucket",
                                "Textile Group & CSD KCD & NSD to CSD",
                                "New Location/ROI Location"])
    # "L2 Promoted 0-90D" carries the sub-bucket label (SPS, 90+ Days, CSD ROI, 0-90 Days …)
    # — this is the key column for SPS booster detection
    vintage_bkt = find_col(df, ["Vintage Bucket", "VintageBucket",
                                "L2 Promoted 0-90D", "bucket", "emp_level"])
    remarks_col = find_col(df, ["Remarks", "Team"])
    client_a    = find_col(df, ["Client-A", "Client A", "ClientA",
                                "Actual Client", "Total Client"])
    client_c    = find_col(df, ["Client-C", "Client C", "ClientC",
                                "Calculated Client", "Total Client"])
    # Listing/Catalog client counts (for KCD)
    list_c_col  = find_col(df, ["Listing Client", "ListingClient"])
    cat_c_col   = find_col(df, ["Catalog Client", "CatalogClient"])
    l2_col      = find_col(df, ["L2 Name", "L2Name", "L2",
                                "level2_name", "emp_manager_name"])
    l3_col      = find_col(df, ["L3 Name", "L3Name", "L3", "level3_name"])
    l4_col      = find_col(df, ["L4 Name", "L4Name", "L4", "level4_name"])
    l5_col      = find_col(df, ["L5 Name", "L5Name", "L5", "level5_name"])
    desig_col   = find_col(df, ["Designation", "designation", "Role",
                                "Employee Role", "emp_designation"])

    # Determine vertical from emp_vertical_name or emp_fun_area_name
    # (Delhi structure uses emp_fun_area_name = "Client Servicing" + emp_vertical_name = "KCD/CSD")
    if vertical_col is None:
        vertical_col = find_col(df, ["emp_vertical_name", "emp_fun_area_name"])

    result = {}
    for _, row in df.iterrows():
        if not emp_col:
            break
        eid = str(row[emp_col]).strip()
        if not eid or eid.lower() in ("nan", ""):
            continue

        vertical = str(row[vertical_col]).strip().upper() if vertical_col else ""
        location = str(row[location_col]).strip()        if location_col else ""
        vintage  = str(row[final_grp]).strip()  if final_grp  else "91-270D"
        vbucket  = str(row[vintage_bkt]).strip() if vintage_bkt else ""
        loc_up   = location.upper()
        vbucket_up = vbucket.upper()

        # Map bucket values from Delhi structure to standard Final Group
        # Delhi file 'bucket' column may have values like "0-30D","31-90D","91-270D","270D+"
        # or older labels — normalise them
        bucket_map = {
            "0-30D": "0-30D", "0-30": "0-30D",
            "31-90D": "31-90D", "31-90": "31-90D",
            "91-270D": "91-270D", "91-270": "91-270D",
            "270D+": "270D+", "270+": "270D+",
            # Values from employee_structure.xlsx "L2 Promoted 0-90D" column:
            "SPS": "91-270D",          # SPS → 91D+ vintage (booster applies)
            "90+ DAYS": "270D+",       # 90+ Days → 270D+ vintage (no booster)
            "90+DAYS": "270D+",
            "0-90 DAYS": "31-90D",     # 0-90 Days → new joiner scheme
            "0-90DAYS": "31-90D",
            "CSD ROI": "91-270D",      # CSD ROI → 91D+ scheme (no booster)
            # Kept from Delhi xlsb format:
            "SPS	": "91-270D", "0-90 DAYS	": "31-90D",
        }
        vintage_up = vintage.upper().strip()
        if vintage_up in bucket_map:
            vintage = bucket_map[vintage_up]
        elif any(vintage_up.startswith(k) for k in bucket_map):
            for k, v in bucket_map.items():
                if vintage_up.startswith(k):
                    vintage = v
                    break

        # ── Remarks column (Listing/Catalog/- for KCD) ──────────
        # Delhi structure uses "Team" column with Listing/Catalog
        team_from_file = str(row[remarks_col]).strip() if remarks_col else ""
        remarks = team_from_file  # alias used when building result dict
        rem_up = team_from_file.upper()

        # ── Derive Team from Vertical + Vintage Bucket + Remarks + Location ──
        if "CSD" in vertical:
            if any(x in vbucket_up for x in ["SPS", "90+ DAYS", "90+DAYS", "CSD ROI"]):
                team = "SPS (CSD 91D+)"
            elif any(x in vbucket_up for x in ["0-90 DAYS", "0-90DAYS"]):
                team = "0-90 Days (CSD new)"
            elif vintage in ("0-30D", "31-90D"):
                team = "0-90 Days (CSD new)"
            else:
                team = "SPS (CSD 91D+)"
        elif "KCD" in vertical:
            if rem_up == "LISTING" or "LISTING" in vbucket_up:
                team = "Listing (KCD)"
            elif rem_up == "CATALOG" or "CATALOG" in vbucket_up:
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

        # ── Client Count ──────────────────────────────────────
        def _safe_float(val, default=100):
            try:
                v = float(val)
                return v if not (v != v) else default  # NaN check
            except (TypeError, ValueError):
                return default

        if "CSD" in vertical:
            cc = max(_safe_float(row[client_c] if client_c else None), 50)
        elif "KCD" in vertical:
            # Prefer Total Client, or sum Listing + Catalog if available
            if client_a and str(row[client_a]).strip() not in ("nan",""):
                cc = _safe_float(row[client_a])
            elif list_c_col and cat_c_col:
                lc = _safe_float(row[list_c_col], 0)
                cc_val = _safe_float(row[cat_c_col], 0)
                cc = lc + cc_val if (lc + cc_val) > 0 else 100
            else:
                cc = 100
        else:
            cc = 100

        # ── Joining Date — convert Excel serials (from xlsb) to proper dates ──
        jd = None
        if joining_col:
            jd_raw = row[joining_col]
            raw_str = str(jd_raw).strip()
            if raw_str not in ("", "nan", "NaT", "None"):
                jd = _to_date(jd_raw)

        # Collection Target = PCR/PCDV target × client count (if available in structure)
        coll_target = 0.0
        pcr_target_col = find_col(df, ["PCR Target","PCDV Target","PCR_Target","Collection Target"])
        if pcr_target_col:
            try:
                coll_target = float(row[pcr_target_col]) * cc
            except Exception:
                coll_target = 0.0

        # MDC client count (for MDC-1 CMR denominator in CSD SPS)
        mdc_col = find_col(df, ["MDC.1", "MDC", "mdc_client", "MDC Client"])
        mdc_client_cnt = 0
        if mdc_col:
            try:
                mdc_client_cnt = int(float(row[mdc_col])) if not (str(row[mdc_col]) in ("nan","")) else 0
            except (TypeError, ValueError):
                mdc_client_cnt = 0

        # Designation (used to route Rel Mgr vs Exec CSD scheme)
        desig_val = str(row[desig_col]).strip() if desig_col and pd.notna(row[desig_col]) else ""

        result[eid] = {
            "Employee Name":     str(row[name_col]).strip() if name_col else "",
            "Designation":       desig_val,
            "Vertical":          str(row[vertical_col]).strip() if vertical_col else "",
            "Location":          location,
            "Joining Date":      jd,
            "Vintage":           vintage,
            "Team":              team,
            "Client Count":      cc,
            "Collection Target": coll_target,
            "L2 Name":           str(row[l2_col]).strip() if l2_col else "",
            "L3 Name":           str(row[l3_col]).strip() if l3_col else "",
            "L4 Name":           str(row[l4_col]).strip() if l4_col else "",
            "L5 Name":           str(row[l5_col]).strip() if l5_col else "",
            "Vintage Bucket":    vbucket,
            "Remarks":           remarks,
            "MDC Client Count":  mdc_client_cnt,
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
        df = _read_file(uploaded_file)
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
                 rnl_prods, rnl_modes, vintage, S, svc_tiers=None,
                 pop_cmr_floor=None, metric_label="PCDV"):
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
    _pop_floor = pop_cmr_floor if pop_cmr_floor is not None else POP_CMR_FLOOR
    if cmr_pct_achieved < _pop_floor:
        pop_reason = f"PoP blocked: CMR {cmr_pct_achieved:.1f}% < {_pop_floor}% min"
    elif prod_score < min_txn:
        pop_reason = f"PoP blocked: {prod_score} txns < {min_txn} min"
    else:
        # Use service tiers from enriched receipt (accurate) if available
        if svc_tiers:
            pop = sum(TIER_REWARD.get(int(t), 0) for t in svc_tiers
                      if isinstance(t, (int, float)) and t in (1, 2, 3))
            pop_reason = f"PoP: {len([t for t in svc_tiers if t in (1,2,3)])} txns (receipt tiers)"
        else:
            eligible = [p for p, m in zip(rnl_prods, rnl_modes)
                        if str(m).upper() in ("ANNUAL","MULTI YEAR","MULTIYEAR","MYR")
                        and not is_insta(p)]
            pop = sum(pop_for_product(p, S["prod_to_pop"]) for p in eligible)
            pop_reason = f"PoP: {prod_score} txns × CMR {cmr_pct_achieved:.1f}%"

    notes = (f"CSD {vintage} | {metric_label}:{round(pcdv)} | clients:{int(client_c)} | "
             f"CMR slab:{cmr_slab} | {pop_reason}")
    return round(base_total, 0), round(pop, 0), notes


def calc_csd_sps(pcdv, prod_score, txn_count, cmr_slab, vintage,
                mdc1_cmr, ext_tat, d60, S, metric_label="PCDV", is_sps=False):
    """
    CSD SPS 91-270D / 270D+.
    - is_sps=True  → Vintage Bucket = 'SPS' in structure file → 1.2× booster always applied.
    - is_sps=False → 91-270D / 270D+ / CSD ROI bucket → booster only via Pune TAT/60D conditions.
    - CMR slab 0 → per_txn = 0 → incentive = 0.
    """
    slabs = S["csd_sps_270p"] if vintage == "270D+" else S["csd_sps_91_270"]
    _, per_txn = pcdv_slab(pcdv, slabs, cmr_slab)

    eff_txn_count = max(int(prod_score), 0) if prod_score > 0 else txn_count

    if mdc1_cmr > S["mdc1_above"]:
        mdc1_mult = S["mdc1_mult_hi"]
    elif mdc1_cmr >= S["mdc1_between"]:
        mdc1_mult = S["mdc1_mult_md"]
    else:
        mdc1_mult = S["mdc1_mult_lo"]

    # Booster: auto 1.2× for SPS-bucket employees; Pune-override for others
    if is_sps:
        booster = S["boost_mult"]
    elif (ext_tat is not None and d60 is not None
          and ext_tat < S["boost_tat"] and d60 < S["boost_d60"]):
        booster = S["boost_mult"]
    else:
        booster = 1.0

    total = per_txn * eff_txn_count * mdc1_mult * booster
    notes = (f"CSD SPS {vintage} | {metric_label}:{round(pcdv)} | CMR slab:{cmr_slab} | "
             f"₹{per_txn}/txn×{eff_txn_count} | MDC1:{mdc1_mult:.1f}({mdc1_cmr:.0f}%) "
             f"boost:{booster} | No PoP")
    return round(total, 0), notes


def get_cmr_plus1_2d_mult(cmr_pct, mdc1_pct, cmr_slab1, cmr_slab2):
    """
    2D CMR+1 multiplier table for Relationship Manager CSD employees.
    Looks up the incentive payout % from (Overall CMR%, MDC1 CMR%) grid.
    Returns a float multiplier (e.g. 1.10 for 110%).

    Grid (from March scheme PPT slide 8):
         MDC1 < 35%   35%  40%  45%+
    CMR >= slab1   50%  50% 100% 110%
    CMR >= slab2   75%  75% 110% 120%
    CMR >= 65%    100% 100% 120% 130%

    Slab1/Slab2 targets come from per-employee CMR targets file.
    65% is a hard-coded third tier above slab2 for March.
    """
    # MDC1 band
    if   mdc1_pct >= 45:  mdc1_band = 3
    elif mdc1_pct >= 40:  mdc1_band = 2
    elif mdc1_pct >= 35:  mdc1_band = 1
    else:                  mdc1_band = 0   # < 35%

    # CMR tier (slab1 < slab2 < 65%)
    if   cmr_pct >= 65:   cmr_tier = 2
    elif cmr_pct >= cmr_slab2: cmr_tier = 1
    elif cmr_pct >= cmr_slab1: cmr_tier = 0
    else:                       return 0.0   # below slab1 → no incentive

    # 2D lookup (rows = cmr_tier, cols = mdc1_band)
    table = [
        # tier 0 (CMR≥slab1):   <35%  35%  40%  45%+
        [0.50, 0.50, 1.00, 1.10],
        # tier 1 (CMR≥slab2):   <35%  35%  40%  45%+
        [0.75, 0.75, 1.10, 1.20],
        # tier 2 (CMR≥65%):     <35%  35%  40%  45%+
        [1.00, 1.00, 1.20, 1.30],
    ]
    return table[cmr_tier][mdc1_band]


def calc_csd_rel_mgr(pcdv, prod_score, txn_count, cmr_pct, mdc1_cmr,
                     cmr_slab1_target, cmr_slab2_target,
                     ext_tat, d60, S, metric_label="PCDV", is_sps=False, vintage="91-270D"):
    """
    CSD Relationship Manager scheme.
    Uses a 2D multiplier table (Overall CMR% × MDC1 CMR%) instead of the simple
    3-band MDC1 multiplier used for Exec employees.
    Formula: NetInc = PerTxn × Prod × 2D_mult × SPS_booster
    """
    # Use RM slab table if available, else fall back to SPS slab
    rm_slabs = S.get("csd_rm_slabs", S.get("csd_sps_91_270"))
    _, per_txn = pcdv_slab(pcdv, rm_slabs, 1)  # RM scheme has CMR 55%/60% column

    eff_prod = max(int(prod_score), 0) if prod_score > 0 else txn_count

    # 2D CMR+1 multiplier
    cmr_plus1_mult = get_cmr_plus1_2d_mult(cmr_pct, mdc1_cmr,
                                            cmr_slab1_target, cmr_slab2_target)

    # SPS booster (same logic as Exec)
    if is_sps:
        booster = S["boost_mult"]
    elif (ext_tat is not None and d60 is not None
          and ext_tat < S["boost_tat"] and d60 < S["boost_d60"]):
        booster = S["boost_mult"]
    else:
        booster = 1.0

    total = per_txn * eff_prod * cmr_plus1_mult * booster
    notes = (f"CSD RM {vintage} | {metric_label}:{round(pcdv)} | "
             f"₹{per_txn}/txn×{eff_prod} | CMR+1:{cmr_plus1_mult:.2f}({cmr_pct:.0f}%CMR,{mdc1_cmr:.0f}%MDC1) "
             f"boost:{booster}")
    return round(total, 0), notes


def calc_kcd_regular(pcdv, txn_count, cmr_col_val, vintage, location,
                    ss_cmr_pct, ss_sent, S, collection_target=0, metric_label="PCDV"):
    """
    KCD Regular incentive.
    txn_count        = productive receipt rows (prod_score_receipt).
    collection_target= PCR_Target × Client_A from structure dump (used for incremental).
    ss_cmr_pct       = SS+ CMR% for penalty check.
    ss_sent          = SS+ renewals sent (penalty only applies if ss_sent >= 3).
    """
    loc = str(location).upper()
    if "NAGPUR" in loc:
        _, per_txn = pcdv_slab(pcdv, S["kcd_nagpur_slabs"], cmr_col_val)
    elif any(c in loc for c in ["HYDERABAD", "VASHI", "RAIPUR", "INDORE"]):
        _, per_txn = pcdv_slab(pcdv, S["kcd_hvri_slabs"], cmr_col_val)
    else:
        slabs = {"270D+": S["kcd_270_slabs"], "91-270D": S["kcd_91_270_slabs"]}.get(
            vintage, S["kcd_0_90_slabs"])
        _, per_txn = pcdv_slab(pcdv, slabs, cmr_col_val)

    # SS+ penalty: only when ss_sent >= 3 AND ss_cmr < 70%
    # ss_sent <= 2 → no penalty (not enough data to penalise)
    if ss_sent >= 3 and ss_cmr_pct < 70:
        ss_mult = 0.5
    else:
        ss_mult = 1.0

    base = per_txn * txn_count * ss_mult
    return round(base, 0), \
           f"KCD Regular {vintage} | {metric_label}:{round(pcdv)} | ₹{per_txn}/txn×{txn_count} | SS+:{ss_mult}"


def calc_kcd_listing(net_dv, txn_count, cmr_col_val, vintage,
                    ss_cmr_pct, ss_sent, collection_target, S,
                    base_clients=1, list_clients=1):
    """
    KCD Listing incentive.
    - collection_target from structure dump (PCR_Target × ClientA) when available.
    - Fallback: derive target from slab config rates × client counts.
    - txn_count = productive receipt rows (prod_score_receipt).
    - Incremental = (Net_DV - collection_target) × 1.4%.
    - SS penalty only when ss_sent >= 3 AND ss_cmr < 70%.
    """
    # If collection_target not in structure, derive from slab rates × client split
    if collection_target <= 0:
        rates  = S["kcd_listing_rates"].get(vintage, (7000, 22000))
        collection_target = base_clients * rates[0] + list_clients * rates[1]
    if collection_target <= 0:
        return 0, "KCD Listing — target=0"
    achv    = (net_dv / collection_target) * 100
    per_txn = next((r2 if cmr_col_val == 2 else r1
                    for t, r1, r2 in S["kcd_listing_slabs"] if achv >= t), 0)
    incr    = max(0, net_dv - collection_target) * 0.014
    if ss_sent >= 3 and ss_cmr_pct < 70:
        ss_mult = 0.5
    else:
        ss_mult = 1.0
    base = per_txn * txn_count * ss_mult
    return round(base + incr, 0), \
           f"KCD Listing {vintage} | Achv:{round(achv,1)}% | ₹{per_txn}/txn×{txn_count} | SS+:{ss_mult}"


def calc_kcd_catalog(net_dv, txn_count, cmr_col_val, vintage,
                    btl_sales, ss_cmr_pct, ss_sent, collection_target, S,
                    base_clients=1, list_clients=1):
    """
    KCD Catalog incentive.
    - collection_target from structure dump (PCR_Target × ClientA) when available.
    - Fallback: derive target from slab config rates × client counts.
    - txn_count = productive receipt rows (prod_score_receipt).
    - Incremental = (Net_DV - collection_target) × 1.4%.
    - SS penalty only when ss_sent >= 3 AND ss_cmr < 70%.
    """
    if collection_target <= 0:
        rates  = S["kcd_listing_rates"].get(vintage, (7000, 22000))
        collection_target = base_clients * rates[0] + list_clients * rates[1]
    if collection_target <= 0:
        return 0, "KCD Catalog — target=0"
    achv    = (net_dv / collection_target) * 100
    per_txn = next((r2 if cmr_col_val == 2 else r1
                    for t, r1, r2 in S["kcd_catalog_slabs"] if achv >= t), 0)
    incr     = max(0, net_dv - collection_target) * 0.014
    btl_mult = 1.2 if btl_sales >= 2 else 1.0
    if ss_sent >= 3 and ss_cmr_pct < 70:
        ss_mult = 0.5
    else:
        ss_mult = 1.0
    base = per_txn * txn_count * ss_mult * btl_mult
    return round(base + incr, 0), \
           f"KCD Catalog {vintage} | Achv:{round(achv,1)}% | ₹{per_txn}/txn×{txn_count} | BTL:{btl_mult} | SS+:{ss_mult}"


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

@st.cache_data(show_spinner=False)
def load_excel(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Load xlsx or xlsb files from raw bytes. Cached to avoid re-reading on every re-run."""
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else "xlsx"
    buf = io.BytesIO(file_bytes)
    try:
        if ext == "xlsb":
            return pd.read_excel(buf, engine="pyxlsb")
        else:
            return pd.read_excel(buf, engine="openpyxl")
    except Exception as e:
        err = str(e)
        if "pyxlsb" in err or "xlsb" in err.lower():
            st.error("📦 Reading .xlsb files requires pyxlsb. "
                     "Run in your terminal: `pip install pyxlsb`")
        else:
            st.error(f"Could not read file '{file_name}': {err}")
        return pd.DataFrame()


def _read_file(f):
    """Helper: read an st.UploadedFile into the cached load_excel."""
    if f is None:
        return pd.DataFrame()
    return load_excel(f.getvalue(), f.name)


def clean_receipt(df):
    """
    Filter receipt file to valid cleared rows only.
    Robust: if Status filter would remove everything, keeps all rows and warns.
    """
    df = df.copy()
    # ── B/C filter: remove Bounced / Cancelled rows ──────────────────────────
    if "B/C" in df.columns:
        df = df[df["B/C"].isna() | (df["B/C"].astype(str).str.strip() == "")]

    # ── Status filter: keep only CLEARED rows ────────────────────────────────
    status_col = find_col(df, ["Status", "STATUS", "PAYMENT STATUS", "Payment Status"])
    if status_col:
        cleared = df[df[status_col].astype(str).str.upper().str.strip() == "CLEARED"]
        if len(cleared) > 0:
            df = cleared
        else:
            # Status column exists but has no "CLEARED" rows — show warning and keep all
            unique_vals = df[status_col].astype(str).str.upper().str.strip().unique()[:8]
            st.warning(
                f"⚠️ Receipt file: column '{status_col}' has no 'Cleared' rows. "
                f"Found: {list(unique_vals)}. Using all rows (no status filter). "
                "Check that you uploaded the correct receipt file.",
                icon="⚠️"
            )
            # keep df as-is (no status filter applied)

    # ── NACH balance payment filter ───────────────────────────────────────────
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
    # Use string comparison to handle both int and string EMP IDs across files
    eid_str   = str(int(float(emp_id))) if str(emp_id).replace(".","").isdigit() else str(emp_id)
    eid       = int(eid_str) if eid_str.isdigit() else eid_str
    rec       = receipt_df[receipt_df["Sales Exec ID"] == eid]
    total_dv  = rec["WT AMT"].fillna(0).sum()               # collection (WT AMT)
    txn_count = len(rec)

    # Deal Value (WT) = deal value column (different from collection)
    dv_col    = find_col(receipt_df, ["Deal Val (WT)", "Deal Value (WT)", "DealVal_WT"])
    gross_deal_val = rec[dv_col].fillna(0).sum() if dv_col else 0.0
    _prod_col = find_col(receipt_df, ["Prod", "Product", "PRODUCT"])
    prods     = rec[_prod_col].fillna("").tolist() if _prod_col else []
    # Productive rows only — with their service tier
    prod_rows  = rec[rec["Productivity"] == 1] if "Productivity" in rec.columns else rec
    svc_tiers  = prod_rows["Service_Tier"].tolist() if "Service_Tier" in prod_rows.columns else []
    insta_rows = rec[rec["Service_Tier"] == 0.5] if "Service_Tier" in rec.columns else rec.iloc[0:0]
    insta_count_receipt = len(insta_rows)
    prod_score_receipt  = (len(prod_rows) + insta_count_receipt * 0.5 - insta_count_receipt
                          ) if "Productivity" in rec.columns else txn_count
    ref_id_col = find_col(refund_df, ["Sales Ex. ID", "Sales Exec ID", "EMP ID"])
    ref       = refund_df[refund_df[ref_id_col].astype(str) == eid_str] if ref_id_col else refund_df.iloc[0:0]
    total_ref = ref["WT Amount"].fillna(0).sum()
    # Deal Loss is always 0 — it is a separate manual entry and not derived from the refund file.
    # Net Deal Value = Deal Value - 0 = Deal Value (before refund).
    deal_loss = 0
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
            # Compare as string to handle int/string mismatch from xlsb files
            rnl = renewal_df[
                (renewal_df[_eid_col].astype(str) == eid_str) &
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

    gross_collection = total_dv           # WT AMT before refund
    net_collection   = total_dv - total_ref
    net_deal_val     = gross_deal_val - deal_loss

    # Per-employee NR Upsell count for CSD Spot incentive
    # Counts productive upsell rows (Upsell/Unique not blank AND WT AMT > 0)
    if "Productivity" in rec.columns and "_is_upsell" not in rec.columns:
        # enrich_receipt already ran; productive upsell = rows where Productivity=1 AND it's an upsell
        upsell_col_name = find_col(receipt_df, ["Upsell", "UPSELL", "Unique", "UNIQUE"])
        if upsell_col_name:
            wt_col_name = find_col(receipt_df, ["WT AMT", "WT_AMT", "WTAMT"])
            upsell_mask = (rec[upsell_col_name].fillna("").astype(str).str.strip() != "")
            if wt_col_name:
                upsell_mask = upsell_mask & (rec[wt_col_name].fillna(0) > 0)
            nr_upsell_count = int(upsell_mask.sum())
        else:
            nr_upsell_count = 0
    else:
        nr_upsell_count = 0

    return (net_collection, txn_count, prods,
            rnl_prods, rnl_modes, rnl_count, total_ref, all_rnl_count,
            svc_tiers, insta_count_receipt, prod_score_receipt,
            gross_collection, gross_deal_val, deal_loss, net_deal_val,
            nr_upsell_count)


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
               rnl_prods, rnl_modes, rnl_count, sb, S, joining_date=None,
               svc_tiers=None, prod_score_receipt=None, mdc1_cmr_pct=None,
               nr_upsell_count=0, net_deal_val=0, collection_target=0,
               vintage_bucket=""):
    """
    Main routing — all fixes applied:
    - SPS booster: auto 1.2× when vintage_bucket='SPS'; Pune TAT/60D override for others
    - MDC-1 CMR: per-employee from renewal file (MDC 2/3 Year excluded from product set)
    - CSD Spot: per-employee NR upsell count from receipt data
    - KCD txn count: prod_score_receipt (productive receipt rows, not all rows)
    - KCD SS penalty: only when ss_sent >= 3 AND ss_cmr < 70%
    - KCD incremental: (Net_Deal_Val - Collection_Target) × 1.4%
    - PoP only for CSD 0-30D/31-90D; gated by CMR floor (55% Apr / 50% Mar)
    """
    vertical   = str(cfg_row.get("Vertical", emp_row.get("Vertical", ""))).upper()
    location   = str(cfg_row.get("Location", emp_row.get("Location", "")))
    vintage    = str(cfg_row.get("Vintage",   "91-270D"))
    team       = str(cfg_row.get("Team",      ""))
    client_cnt = max(float(cfg_row.get("Client Count", 100) or 100),
                     50 if "CSD" in vertical else 1)
    # Always compute BOTH PCR and PCDV for every employee (CSD and KCD).
    # PCR  = Net Collection / Client count  (collection-based)
    # PCDV = Net Deal Value  / Client count  (deal-value-based)
    # The sidebar toggle selects which one drives the slab lookup.
    # For March the slabs are calibrated to PCR; for April to PCDV.
    use_pcr = sb.get("use_pcr", False)

    dv_for_pcdv = net_deal_val if net_deal_val > 0 else net_dv   # prefer deal value
    pcr_val  = (net_dv       / client_cnt) if client_cnt > 0 else 0   # always collection
    pcdv_val = (dv_for_pcdv  / client_cnt) if client_cnt > 0 else 0   # always deal value

    # slab_metric = the metric used for incentive slab lookup (sidebar-controlled)
    slab_metric  = pcr_val if use_pcr else pcdv_val
    metric_label = "PCR"  if use_pcr else "PCDV"
    pcdv = slab_metric   # internal name kept for compatibility with calc functions

    cmr_pct    = cmr_data.get("cmr_pct",    0.0)
    ss_cmr_pct = cmr_data.get("ss_cmr_pct", 0.0)
    rnl_sent   = cmr_data.get("renewal_sent", 0)   # total sent (all statuses)

    # Days since joining (handles Excel serial ints from xlsb files)
    days_since_joining = ""
    if joining_date is not None:
        try:
            jd = _to_date(joining_date)
            if jd is not None:
                days_since_joining = (CALC_DATE - jd).days
        except Exception:
            days_since_joining = ""

    # Productivity scores
    prod_score_new, _, _  = calc_productivity(rnl_prods, rnl_modes, "csd_new")  # for CSD 0-90D
    prod_score_sps, insta_cnt_sps, _ = calc_productivity(rnl_prods, rnl_modes, "csd_sps")

    base_inc = pop_inc = spot_inc = 0
    kcd_base_only   = 0   # KCD: base incentive before incremental
    kcd_incremental = 0   # KCD: incremental DV amount
    notes = cmr_note = ""

    # ── CSD ──────────────────────────────────────────────────
    if "CSD" in vertical:
        cmr_slab, cmr_note = get_cmr_slab(
            cmr_pct, rnl_sent, sb.get("csd_slab1_target", 50), sb.get("csd_slab2_target", 60))

        if vintage in ("0-30D", "31-90D"):
            # PoP scheme only for new joiners
            base_inc, pop_inc, notes = calc_csd_new(
                pcdv, client_cnt, cmr_slab, cmr_pct,
                rnl_prods, rnl_modes, vintage, S,
                svc_tiers=svc_tiers,
                pop_cmr_floor=sb.get("pop_cmr_floor", POP_CMR_FLOOR),
                metric_label=metric_label)
        else:
            # SPS — no PoP; Insta = 0.5; productivity from receipt
            # MDC-1 CMR: per-employee from renewal file (MDC 2/3 Year excluded)
            # Use per-employee MDC1 CMR% from renewal file if available
            # Fallback to 0 (not sidebar default) so wrong band is obvious in output
            emp_mdc1_cmr = mdc1_cmr_pct if mdc1_cmr_pct is not None else 0.0
            # is_sps: True for ALL "SPS (CSD 91D+)" team employees
            # SPS booster applies to the whole SPS team unconditionally per scheme.
            # When structure file has "L2 Promoted 0-90D" col (values: SPS/90+ Days/CSD ROI),
            # vintage_bucket will be "SPS" for booster employees and "" for others.
            # When that column is absent, we fall back to team membership.
            is_sps_by_bucket = str(vintage_bucket).upper().strip() == "SPS"
            is_sps_by_team   = "SPS" in str(team).upper()
            is_sps_employee  = is_sps_by_bucket or is_sps_by_team

            # Relationship Managers use the 2D CMR+1 table (PPT slides 8-11)
            # Execs/Sr.Execs/AMs/Mgrs use the simple 3-band MDC1 multiplier (slides 2-7)
            _is_rel_mgr = any(k in str(designation).upper()
                              for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"])
            if _is_rel_mgr:
                base_inc, notes = calc_csd_rel_mgr(
                    pcdv, prod_score_receipt or 0, txn_count,
                    cmr_pct, emp_mdc1_cmr,
                    float(sb.get("csd_slab1_target", 55)),
                    float(sb.get("csd_slab2_target", 60)),
                    sb.get("ext_tat"), sb.get("d60"),
                    S, metric_label=metric_label, is_sps=is_sps_employee, vintage=vintage)
            else:
                base_inc, notes = calc_csd_sps(
                    pcdv, prod_score_receipt or 0, txn_count, cmr_slab, vintage,
                    emp_mdc1_cmr, sb.get("ext_tat", 99), sb.get("d60", 99), S,
                    metric_label=metric_label, is_sps=is_sps_employee)
            # Spot: per-employee NR upsell count from receipt (not global sidebar)
            # CSD Spot Rate applies only for April (Apr 1-16); other months = no spot
            _month = str(sb.get("sel_month", "")).upper()
            if "APR" in _month:
                spot_inc = calc_spot_csd(nr_upsell_count, S)
            else:
                spot_inc = 0

    # ── KCD ──────────────────────────────────────────────────
    elif "KCD" in vertical:
        kcd_col, cmr_note = get_kcd_cmr_col(
            cmr_pct, rnl_sent, sb.get("kcd_slab1_target", 72), sb.get("kcd_slab2_target", 80))
        team_up = team.upper()

        # KCD uses productive receipt count (not all receipt rows, not renewal count)
        kcd_txn = prod_score_receipt if prod_score_receipt and prod_score_receipt > 0 else txn_count

        # SS+ sent count for penalty determination
        ss_sent_count = cmr_data.get("ss_sent", 0)

        # KCD: use Net Deal Value for incremental (not Net Collection)
        kcd_net_dv = net_deal_val if net_deal_val > 0 else net_dv

        # Track base vs incremental separately for KCD output columns
        kcd_base_only  = 0
        kcd_incremental = 0
        if "LISTING" in team_up:
            star_c_list = sum(1 for p in rnl_prods
                              if any(k in str(p).upper() for k in ["STAR","LEADER","PREF"]))
            list_c_l  = max(star_c_list, 1)
            base_c_l  = max(client_cnt - list_c_l, 1)
            base_inc, notes = calc_kcd_listing(
                kcd_net_dv, kcd_txn, kcd_col, vintage,
                ss_cmr_pct, ss_sent_count, collection_target, S,
                base_clients=base_c_l, list_clients=list_c_l)
            # Decompose: listing/catalog funcs already merge base+incr; re-derive incr
            kcd_incremental = round(max(0, kcd_net_dv - (collection_target or 0)) * 0.014, 0) if (collection_target or 0) > 0 else 0
            kcd_base_only   = base_inc - kcd_incremental
            spot_inc = calc_spot_kcd(
                pcdv, "Listing_270D" if vintage == "270D+" else "Listing_other",
                sb.get("spot_met", False), S)
        elif "CATALOG" in team_up:
            star_c_cat = sum(1 for p in rnl_prods
                             if any(k in str(p).upper() for k in ["STAR","LEADER","PREF"]))
            list_c_c  = max(star_c_cat, 1)
            base_c_c  = max(client_cnt - list_c_c, 1)
            base_inc, notes = calc_kcd_catalog(
                kcd_net_dv, kcd_txn, kcd_col, vintage,
                sb.get("btl_sales", 0), ss_cmr_pct, ss_sent_count, collection_target, S,
                base_clients=base_c_c, list_clients=list_c_c)
            kcd_incremental = round(max(0, kcd_net_dv - (collection_target or 0)) * 0.014, 0) if (collection_target or 0) > 0 else 0
            kcd_base_only   = base_inc - kcd_incremental
            spot_inc = calc_spot_kcd(
                pcdv, "Catalog_270D" if vintage == "270D+" else "Catalog_other",
                sb.get("spot_met", False), S)
        elif "ROI" in team_up:
            kcd_base_only, notes = calc_kcd_regular(
                pcdv, kcd_txn, kcd_col, vintage, location,
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            kcd_incremental = round(max(0, kcd_net_dv - collection_target) * 0.014, 0) if collection_target > 0 else 0
            base_inc = kcd_base_only + kcd_incremental
            spot_inc = calc_spot_kcd(pcdv, "ROI_Exec", sb.get("spot_met", False), S)
        else:
            kcd_base_only, notes = calc_kcd_regular(
                pcdv, kcd_txn, kcd_col, vintage, location,
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            kcd_incremental = round(max(0, kcd_net_dv - collection_target) * 0.014, 0) if collection_target > 0 else 0
            base_inc = kcd_base_only + kcd_incremental
            if vintage in ("0-30D", "31-90D"):
                spot_inc = calc_spot_kcd(pcdv, "KCD_0_90D", sb.get("spot_met", False), S)

    # ── Decompose values matching sir's FSF column layout ────────────────────
    _prod_score = round(prod_score_receipt or (
                        prod_score_new if "CSD" in vertical and vintage in ("0-30D","31-90D")
                        else prod_score_sps), 1)

    # CSD breakdown: expose intermediate values to match sir's FSF column layout
    _is_csd_sps = "CSD" in vertical and "SPS" in team
    _is_csd_rm  = "CSD" in vertical and any(k in str(designation).upper()
                                            for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"])
    _is_csd     = "CSD" in vertical

    import re as _re

    # Extract booster from scheme notes string
    _bm = _re.search(r'boost:([0-9.]+)', notes)
    _boost_val = float(_bm.group(1)) if _bm else 1.0

    # Extract MDC1 multiplier from scheme notes
    _mdc1_m = _re.search(r'MDC1:([0-9.]+)', notes)
    _mdc1_mult_val = float(_mdc1_m.group(1)) if _mdc1_m else 1.0

    # For Rel Mgr, extract 2D CMR+1 multiplier
    _cmrp1_m = _re.search(r'CMR[+]1:([0-9.]+)', notes)
    _cmrp1_mult_val = float(_cmrp1_m.group(1)) if _cmrp1_m else _mdc1_mult_val

    # Net Incentive = base before booster
    _net_inc_before_boost = round(base_inc / _boost_val, 0) if _boost_val != 0 else base_inc

    # Per-txn rate: net_inc_before_boost / (prod × mdc1_mult)
    _effective_mult = _cmrp1_mult_val if _is_csd_rm else _mdc1_mult_val
    if _is_csd and _prod_score > 0 and _effective_mult > 0:
        _per_txn_rate = round(_net_inc_before_boost / (_prod_score * _effective_mult), 0)
    else:
        _per_txn_rate = 0

    # Incentive Payout Multiplier = combined multiplier for the incentive row
    # For Exec: this is the 3-band MDC1 mult (1.2/1.0/0.5)
    # For Rel Mgr: this is the 2D table result
    _inc_payout_mult = _cmrp1_mult_val if _is_csd_rm else _mdc1_mult_val

    # KCD breakdown
    _kcd_base   = int(kcd_base_only)   if "KCD" in vertical else 0
    _kcd_incr   = int(kcd_incremental) if "KCD" in vertical else 0
    _kcd_ss_mult = (0.5 if (cmr_data.get("ss_sent", 0) >= 3 and ss_cmr_pct < 70) else 1.0) if "KCD" in vertical else 1.0

    return {
        "Days Since Joining":  days_since_joining,
        "CMR% (auto)":         round(cmr_pct, 1),
        "SS+ CMR% (auto)":     round(ss_cmr_pct, 1),
        "CMR Slab1 Target":    sb.get("csd_slab1_target", sb.get("kcd_slab1_target", "")),
        "CMR Slab2 Target":    sb.get("csd_slab2_target", sb.get("kcd_slab2_target", "")),
        "Renewals Sent":       rnl_sent,
        "Renewals Received":   cmr_data.get("renewal_received", 0),
        "CMR Slab":            cmr_note,
        "SS+ Sent":            cmr_data.get("ss_sent", 0),
        "SS+ Received":        cmr_data.get("ss_received", 0),
        "MDC-1 CMR%":          round(mdc1_cmr_pct, 1) if mdc1_cmr_pct is not None else "",
        "PCR":                 round(pcr_val, 0),
        "PCDV":                round(pcdv_val, 0),
        "Slab Metric Used":    metric_label,   # which one drove the slab lookup
        "Productivity Score":  _prod_score,
        "Insta Txns (0.5×)":   insta_cnt_sps,
        "Receipt Txns":        txn_count,
        "Renewal Txns":        rnl_count,
        # ── CSD SPS columns (match sir's csd_calc.xlsx) ──────────
        # ── CSD detailed breakdown (matches sir's csd_calc columns) ───
        "MDC1 CMR+1%":         round(mdc1_cmr_pct, 1) if (_is_csd and mdc1_cmr_pct is not None) else "",
        "CMR+1 Multiplier":    _inc_payout_mult if _is_csd else "",
        "Inc. Payout Mult":    _inc_payout_mult if _is_csd else "",
        "Inc. Per Txn (₹)":    int(_per_txn_rate) if _is_csd and _prod_score > 0 else "",
        "Net Incentive (₹)":   int(_net_inc_before_boost) if _is_csd else "",
        "SPS Booster":         _boost_val if _is_csd else "",
        "Gross Inc w/ Boost (₹)": int(base_inc) if _is_csd else "",
        # ── KCD columns (match sir's kcd_calc.xlsx) ──────────────
        "KCD Base Incentive (₹)":    _kcd_base,
        "KCD Incremental (₹)":       _kcd_incr,
        "KCD SS+ CMR%":              round(ss_cmr_pct, 1) if "KCD" in vertical else "",
        "KCD SS+ Sent":              cmr_data.get("ss_sent", 0) if "KCD" in vertical else "",
        "KCD SS+ Recd":              cmr_data.get("ss_received", 0) if "KCD" in vertical else "",
        "KCD SS+Ren Mult":           _kcd_ss_mult if "KCD" in vertical else "",
        "KCD SS+ Penalty Applied":   "Yes (50%)" if (_kcd_ss_mult == 0.5) else ("No" if "KCD" in vertical else ""),
        "KCD Gross Incentive (₹)":   int(base_inc) if "KCD" in vertical else "",
        # ── Common output columns ─────────────────────────────────
        "Base Incentive (₹)":  int(base_inc),
        "PoP Incentive (₹)":   int(pop_inc),
        "Spot Incentive (₹)":  int(spot_inc),
        "Total Incentive (₹)": int(base_inc + pop_inc + spot_inc),
        "Net Deal Value (₹)":  int(net_dv),
        "Scheme":              notes,
    }
# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════

st.title("💰 IndiaMart Incentive Calculator — v25")
st.caption("Employee name from Renewal L1 column | CMR% auto-calculated | Slabs editable via config file")

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Files")
    receipt_file    = st.file_uploader("1. Receipt file",           type=["xlsx", "xlsb"])
    refund_file     = st.file_uploader("2. Refund file",            type=["xlsx", "xlsb"])
    renewal_file    = st.file_uploader("3. Renewal file",           type=["xlsx", "xlsb"])
    structure_file  = st.file_uploader("4. Employee Structure Dump",type=["xlsx", "xlsb"])
    slab_cfg_file   = st.file_uploader("5. Slab Config (optional)",   type=["xlsx", "xlsb"])

    st.divider()
    st.header("🎯 CMR% Targets File")
    st.caption("Upload the monthly targets file (xlsx or xlsb).")
    cmr_target_file = st.file_uploader("6. CMR Targets file", type=["xlsx", "xlsb"])
    st.info("Individual Slab 1 & 2 targets are loaded per employee from this file.\n\n≤3 renewals sent → auto-forced Slab 1", icon="ℹ️")

    st.divider()
    st.header("⚙️ Scheme Settings")

    metric_mode = st.radio(
        "Base metric",
        ["PCDV (Per Client Deal Value)", "PCR (Per Client Collection)"],
        index=0,
        help="PCDV uses deal value; PCR uses actual collection. Both use WT AMT column — "
             "select to match the month's scheme. Change slabs via Slab Config file."
    )
    use_pcr = metric_mode.startswith("PCR")

    pop_cmr_floor = st.number_input(
        "Min CMR% to earn PoP",
        0.0, 100.0, 55.0, 1.0,
        help="CSD 0-90D: minimum CMR% employee must achieve to earn Power of Productivity. "
             "Apr=55%, Mar=50%"
    )

    with st.expander("CSD SPS (91D+ vintage)"):
        def_mdc1 = st.number_input("MDC-1 CMR+1%",   0.0, 100.0, 30.0)
        def_tat  = st.number_input("Ext. Ticket TAT", 0.0, 10.0,  1.5)
        def_d60  = st.number_input("60D Not Met %",   0.0, 100.0, 12.0)
    with st.expander("Spot Rate"):
        def_nr   = st.number_input("CSD NR Upsell/AMR count", 0, 50, 0)
        def_btl  = st.number_input("KCD Base-to-Listing sales", 0, 20, 0)
        def_spot = st.checkbox("KCD Spot multiplier met (≥2 SS+ sales)?")

    sb = dict(mdc1_cmr=def_mdc1, ext_tat=def_tat, d60=def_d60,
              nr_upsell=def_nr, btl_sales=def_btl, spot_met=def_spot,
              use_pcr=use_pcr, pop_cmr_floor=pop_cmr_floor)

    st.divider()
    st.header("📅 Select Month")
    selected_month = st.selectbox(
        "Calculate incentives for",
        options=["(Upload files first)"],
        key="month_selector",
        help="All calculations — PCDV, CMR%, Productivity — will be for this month only"
    )
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

col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "⬇️ Download April 2026 Slab Config (PCDV)",
        data=make_slab_config_excel(),
        file_name="Slab_Config_April2026_PCDV.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with col_b:
    st.download_button(
        "⬇️ Download March 2026 Slab Config (PCR)",
        data=make_march_slab_config_excel(),
        file_name="Slab_Config_March2026_PCR.xlsx",
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


if not (receipt_file and refund_file and renewal_file and structure_file):
    st.info("4 files required: Receipt + Refund + Renewal + Employee Structure Dump. "
            "CMR Targets and Slab Config are optional.", icon="📂")
    st.stop()

# ── Load all files (cached — only re-reads when file actually changes) ────
receipt_df_raw  = clean_receipt(_read_file(receipt_file))
refund_df_raw   = _read_file(refund_file)
renewal_df_raw  = _read_file(renewal_file)
struct_map      = load_structure_dump(structure_file)
cmr_targets     = load_cmr_targets(cmr_target_file)

if not struct_map or len(struct_map) == 0:
    st.error("Could not read the structure file. Check column names.")
    st.stop()
if not cmr_targets:
    st.warning("⚠️ No CMR Targets file — fallback: Slab 1=70%, Slab 2=80%", icon="⚠️")

# ── Step 1 preview — reuse already-loaded struct_map (no second file parse) ──
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

# ── Step 2: Calculate ─────────────────────────────────────────
st.subheader("Step 2 — Calculate Incentives")

# ── Normalise EMP ID in renewal (keep as string for consistent comparison) ──
_eid = find_col(renewal_df_raw, ["EMP ID","Emp ID","EmpID","Employee ID"])
if _eid:
    renewal_df_raw[_eid] = renewal_df_raw[_eid].apply(
        lambda x: str(int(float(x))) if str(x).replace(".","").isdigit() else str(x))

# ── Month selector: show available months dynamically ─────────
available_months = get_available_months(receipt_df_raw, renewal_df_raw)
if available_months:
    sel_month = st.sidebar.selectbox(
        "Calculate incentives for",
        options=available_months,
        index=len(available_months)-1,
        key="month_selector_live",
        help="All calculations (PCDV, CMR%, Productivity) will be for this month only"
    )
else:
    sel_month = None
    st.warning("Could not detect months from the uploaded files.", icon="⚠️")

# ── Filter all files to selected month ───────────────────────
if sel_month:
    receipt_df, refund_df, renewal_df = filter_by_month(
        receipt_df_raw, refund_df_raw, renewal_df_raw, sel_month)
    if len(receipt_df) == 0 and len(receipt_df_raw) > 0:
        st.error(
            f"📅 **{sel_month}** — Receipt: **0 rows** after month filter "
            f"(raw has {len(receipt_df_raw)} rows). "
            "The receipt file may not contain data for this month. "
            "Check that you uploaded the correct receipt file for this period.",
            icon="🚨"
        )
    elif len(receipt_df) == 0 and len(receipt_df_raw) == 0:
        st.error(
            "Receipt file returned 0 rows after Status=Cleared filter. "
            "Check the Status column values in your receipt file.",
            icon="🚨"
        )
    else:
        st.info(f"📅 **{sel_month}** — "
                f"Receipt: {len(receipt_df)} rows | "
                f"Refund: {len(refund_df)} rows | "
                f"Renewal: {len(renewal_df) if renewal_df is not None else 0} rows")
else:
    receipt_df, refund_df, renewal_df = receipt_df_raw, refund_df_raw, renewal_df_raw

# ── Enrich receipt: Productivity + Service_Tier ───────────────
receipt_df = enrich_receipt(receipt_df)

# ── CMR% from month-filtered renewal data ────────────────────
cmr_map     = calc_cmr_per_employee(renewal_df)
# Build per-employee MDC client count from structure file
mdc_client_counts_map = {
    eid: s.get("MDC Client Count", 0)
    for eid, s in struct_map.items()
    if s.get("MDC Client Count", 0) > 0
}
mdc1_cmr_map = calc_mdc1_cmr_per_employee(renewal_df, mdc_client_counts_map or None)

# Build emp hierarchy fallback from receipt
emp_df = build_emp_list(receipt_df)

with st.expander("Loaded file summary"):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Employees (structure)", len(struct_map))
    c2.metric("Receipt rows (filtered)", len(receipt_df),
              help="Rows after Status=Cleared filter + month filter. If 0: check receipt file Status column.")
    c3.metric("Receipt rows (raw)",    len(receipt_df_raw),
              help="Rows after clean_receipt only (before month filter). If 0: receipt file may have wrong Status values.")
    c4.metric("Refund rows",           len(refund_df))
    c5.metric("Renewal rows",          len(renewal_df) if renewal_df is not None else 0)
    st.metric("CMR% auto-calc for",    len(cmr_map))
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
                  "kcd_slab2_target": emp_targets["slab2"],
                  "sel_month": sel_month if sel_month else ""}

        (net_dv, txn_count, prods, rnl_prods, rnl_modes,
         rnl_count, total_ref, all_rnl_count,
         svc_tiers, insta_cnt_receipt, prod_score_receipt,
         gross_collection, gross_deal_val, deal_loss, net_deal_val,
         nr_upsell_count) = \
            get_transactions(receipt_df, refund_df, renewal_df, emp_id)

        # Build cfg_row and emp_row from structure map
        cfg_row = {
            "Vertical":     s.get("Vertical", ""),
            "Location":     s.get("Location", ""),
            "Vintage":      s.get("Vintage", ""),
            "Team":         s.get("Team", ""),
            "Client Count": s.get("Client Count", 1),
            "Joining Date": s.get("Joining Date", None),
        }
        emp_row = {
            "Vertical":  s.get("Vertical", ""),
            "Location":  s.get("Location", ""),
            "L2 Name":   s.get("L2 Name", ""),
            "L3 Name":   s.get("L3 Name", ""),
            "L4 Name":   s.get("L4 Name", ""),
            "L5 Name":   s.get("L5 Name", ""),
        }

        emp_mdc1 = mdc1_cmr_map.get(emp_id, {})
        try:
            inc = route_calc(emp_row, cfg_row, emp_cmr,
                             net_dv, txn_count, prods,
                             rnl_prods, rnl_modes, rnl_count,
                             emp_sb, S, joining_date=s.get("Joining Date"),
                             svc_tiers=svc_tiers,
                             prod_score_receipt=prod_score_receipt,
                             mdc1_cmr_pct=emp_mdc1.get("mdc1_cmr_pct", None),
                             nr_upsell_count=nr_upsell_count,
                             net_deal_val=net_deal_val,
                             collection_target=s.get("Collection Target", 0),
                             vintage_bucket=s.get("Vintage Bucket", ""),
                             designation=s.get("Designation", ""))
        except Exception as _e:
            inc = {"Base Incentive (₹)": 0, "PoP Incentive (₹)": 0,
                   "Spot Incentive (₹)": 0, "Total Incentive (₹)": 0,
                   "Scheme": f"ERROR: {_e}", "CMR% (auto)": 0,
                   "SS+ CMR% (auto)": 0, "Renewals Sent": 0,
                   "Renewals Received": 0, "CMR Slab": "Error",
                   "Productivity Score": 0, "Receipt Txns": 0,
                   "Renewal Txns": 0, "Net Deal Value (₹)": 0,
                   "PCR": 0, "PCDV": 0, "Days Since Joining": ""}

        results.append({
            "Employee ID":        emp_id,
            "Employee Name":      emp_name,
            "Designation":        s.get("Designation", ""),
            "Calc Month":         sel_month if sel_month else "All",
            "Collection (₹)":     int(gross_collection),
            "Refund (₹)":         int(total_ref),
            "Net Collection (₹)": int(net_dv),
            "Collection Target (₹)": int(s.get("Collection Target", 0)),
            "Deal Value (₹)":     int(gross_deal_val),
            "Deal Loss (₹)":      int(deal_loss),
            "Net Deal Value (₹)": int(net_deal_val),
            "Vertical":           s["Vertical"],
            "Vintage":            s["Vintage"],
            "Team":               s["Team"],
            "Vintage Bucket":     s["Vintage Bucket"],
            "Location":           s["Location"],
            "L2":                 s["L2 Name"],
            "L3":                 s["L3 Name"],
            "CMR Slab1 Target":   emp_targets["slab1"],
            "CMR Slab2 Target":   emp_targets["slab2"],
            **inc,
            "SPS Group":  "SPS" if ("SPS" in str(s.get("Vintage Bucket","")).upper() or
                                     "SPS" in str(s.get("Team","")).upper()) else "No",
            "MDC1 Sent":  mdc1_cmr_map.get(emp_id, {}).get("mdc1_sent", 0),
            "MDC1 Recd":  mdc1_cmr_map.get(emp_id, {}).get("mdc1_recd", 0),
            "Collection Target (₹)": int(s.get("Collection Target", 0)),
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
        "SPS Group", "Vintage Bucket", "Location", "L2", "Days Since Joining",
        "Collection (₹)", "Refund (₹)", "Net Collection (₹)",
        "Collection Target (₹)",
        "Deal Value (₹)", "Deal Loss (₹)", "Net Deal Value (₹)",
        "PCR", "PCDV", "Slab Metric Used",
        "CMR% (auto)", "CMR Slab1 Target", "CMR Slab2 Target",
        "SS+ CMR% (auto)", "SS+ Sent", "SS+ Received",
        "Renewals Sent", "Renewals Received", "CMR Slab",
        "MDC-1 CMR%", "MDC1 CMR+1%", "CMR+1 Multiplier", "Inc. Payout Mult", "MDC1 Sent", "MDC1 Recd",
        "Productivity Score", "Insta Txns (0.5×)", "Receipt Txns", "Renewal Txns",
        "Inc. Per Txn (₹)", "Net Incentive (₹)", "SPS Booster", "Gross Inc w/ Boost (₹)",
        "KCD Base Incentive (₹)", "KCD Incremental (₹)", "KCD SS+Ren Mult", "KCD Gross Incentive (₹)",
        "Base Incentive (₹)", "PoP Incentive (₹)", "Spot Incentive (₹)",
        "Total Incentive (₹)", "Scheme",
    ] if c in filtered.columns]

    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        wb  = w.book
        hdr = wb.add_format({"bold": True, "bg_color": "#1F4E79",
                              "font_color": "#FFFFFF", "border": 1, "font_size": 10})
        grn = wb.add_format({"bold": True, "bg_color": "#375623",
                              "font_color": "#FFFFFF", "border": 1, "font_size": 10})
        org = wb.add_format({"bold": True, "bg_color": "#843C0C",
                              "font_color": "#FFFFFF", "border": 1, "font_size": 10})
        num_fmt = wb.add_format({"num_format": "#,##0", "font_size": 9})
        pct_fmt = wb.add_format({"num_format": "0.0%", "font_size": 9})

        def write_sheet(df, sheet_name, col_fmt=None, header_fmt=None):
            """Write df to sheet with blue header row."""
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws = w.sheets[sheet_name]
            hf = header_fmt or hdr
            for ci, col in enumerate(df.columns):
                ws.write(1, ci, col, hf)
                ws.set_column(ci, ci, max(14, len(str(col)) + 2))
            ws.write(0, 0, f"{sheet_name} — auto-generated by IndiaMart Incentive Calculator")
            ws.freeze_panes(2, 0)

        # ── Sheet 1: FSF (Final Settlement File) — all employees ─────────────
        fsf_cols = [c for c in [
            "Employee ID","Employee Name","Calc Month","Vertical","Vintage",
            "Team","Designation","Vintage Bucket","SPS Group","Location","L2","L3",
            "Days Since Joining",
            "Collection (₹)","Refund (₹)","Net Collection (₹)",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)",
            "PCR","PCDV","Slab Metric Used",
            "CMR Slab1 Target","CMR Slab2 Target",
            "CMR% (auto)","SS+ CMR% (auto)","SS+ Sent","SS+ Received",
            "Renewals Sent","Renewals Received","CMR Slab",
            "MDC-1 CMR%","MDC1 CMR+1%","CMR+1 Multiplier","Inc. Payout Mult","MDC1 Sent","MDC1 Recd",
            "Productivity Score","Insta Txns (0.5×)","Receipt Txns","Renewal Txns",
            "Inc. Per Txn (₹)","Net Incentive (₹)","SPS Booster","Gross Inc w/ Boost (₹)",
            "KCD SS+ CMR%","KCD SS+ Sent","KCD SS+ Recd","KCD SS+Ren Mult","KCD SS+ Penalty Applied",
            "KCD Base Incentive (₹)","KCD Incremental (₹)","KCD Gross Incentive (₹)",
            "Base Incentive (₹)","PoP Incentive (₹)","Spot Incentive (₹)",
            "Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        write_sheet(res[fsf_cols], "FSF", header_fmt=hdr)

        # ── Sheet 2: Exec-CSD — CSD employees only ────────────────────────────
        csd_res = res[res["Vertical"] == "CSD"].copy() if "Vertical" in res.columns else res.iloc[0:0]
        csd_cols = [c for c in [
            "Employee ID","Employee Name","Designation","Location","SPS Group","Vintage Bucket",
            "Collection (₹)","Refund (₹)","Net Collection (₹)","PCR","PCDV","Slab Metric Used",
            "CMR Slab1 Target","CMR Slab2 Target","CMR% (auto)",
            "Renewals Sent","Renewals Received",
            "MDC-1 CMR%","MDC1 CMR+1%","CMR+1 Multiplier","Inc. Payout Mult","MDC1 Sent","MDC1 Recd",
            "Productivity Score","Insta Txns (0.5×)","Receipt Txns",
            "Inc. Per Txn (₹)","Net Incentive (₹)","SPS Booster","Gross Inc w/ Boost (₹)",
            "Base Incentive (₹)","PoP Incentive (₹)","Spot Incentive (₹)",
            "Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        if not csd_res.empty:
            write_sheet(csd_res[csd_cols], "Exec-CSD", header_fmt=grn)

        # ── Sheet 3: KCD-Exec — KCD employees only ────────────────────────────
        kcd_res = res[res["Vertical"] == "KCD"].copy() if "Vertical" in res.columns else res.iloc[0:0]
        kcd_cols = [c for c in [
            "Employee ID","Employee Name","Location","Team","Vintage",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCR","PCDV","Slab Metric Used",
            "Collection Target (₹)",
            "CMR% (auto)","SS+ CMR% (auto)","SS+ Sent","SS+ Received",
            "KCD SS+ CMR%","KCD SS+ Sent","KCD SS+ Recd","KCD SS+Ren Mult","KCD SS+ Penalty Applied",
            "Renewals Sent","Renewals Received",
            "Productivity Score","Insta Txns (0.5×)","Receipt Txns",
            "KCD Base Incentive (₹)","KCD Incremental (₹)","KCD Gross Incentive (₹)",
            "Spot Incentive (₹)","Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        if not kcd_res.empty:
            write_sheet(kcd_res[kcd_cols], "KCD-Exec", header_fmt=org)

        # ── Sheet 4: CMR Validation — renewal CMR details ────────────────────
        cmr_cols = [c for c in [
            "Employee ID","Employee Name","Vertical","Vintage","Team","Location",
            "CMR Slab1 Target","CMR Slab2 Target",
            "Renewals Sent","Renewals Received","CMR% (auto)","CMR Slab",
            "SS+ Sent","SS+ Received","SS+ CMR% (auto)",
            "MDC-1 CMR%","MDC1 Sent","MDC1 Recd",
        ] if c in res.columns]
        write_sheet(res[cmr_cols], "CMR Validation")

        # ── Sheet 5: Summary by team ──────────────────────────────────────────
        summary_df = res.groupby(["Vertical","Vintage","Team"]).agg(
            Employees       = ("Employee ID", "count"),
            Avg_PCR         = ("PCR",  "mean"),
            Avg_PCDV        = ("PCDV", "mean"),
            Avg_CMR_pct     = ("CMR% (auto)", "mean"),
            Total_Collection= ("Net Collection (₹)", "sum"),
            Total_NDV       = ("Net Deal Value (₹)", "sum"),
            Total_Base_Inc  = ("Base Incentive (₹)", "sum"),
            Total_PoP       = ("PoP Incentive (₹)", "sum"),
            Total_Spot      = ("Spot Incentive (₹)", "sum"),
            Total_Incentive = ("Total Incentive (₹)", "sum"),
            Avg_Incentive   = ("Total Incentive (₹)", "mean"),
        ).reset_index()
        write_sheet(summary_df, "Summary")

        # ── Sheet 6: Zero Incentive employees ────────────────────────────────
        zero_df = res[res["Total Incentive (₹)"] == 0].copy()
        if not zero_df.empty:
            zero_cols = [c for c in [
                "Employee ID","Employee Name","Vertical","Vintage","Team","Location",
                "PCR","PCDV","CMR% (auto)","CMR Slab",
                "Productivity Score","Receipt Txns","Scheme",
            ] if c in zero_df.columns]
            write_sheet(zero_df[zero_cols], "Zero Incentive")

        # ── Sheet 7: Paid vs Balance tracking ────────────────────────────────
        paid_df = res[["Employee ID","Employee Name","Vertical","Team",
                        "Total Incentive (₹)"]].copy()
        paid_df["Paid Incentive (₹)"]    = 0
        paid_df["Balance Incentive (₹)"] = paid_df["Total Incentive (₹)"]
        paid_df["Remarks"] = ""
        write_sheet(paid_df, "Paid & Balance")

        export_cols = fsf_cols   # keep for compatibility

        # ── Source data sheets — raw input files used for calculation ──────────
        grey = wb.add_format({"bold": True, "bg_color": "#595959",
                               "font_color": "#FFFFFF", "border": 1, "font_size": 10})

        # Receipt Data (month-filtered, enriched columns stripped)
        try:
            rec_exp = receipt_df.copy()
            rec_exp = rec_exp.drop(columns=[c for c in
                ["Productivity","Service_Tier","_is_upsell",
                 "_is_pure_renewal","_has_upsell_on_receipt"]
                if c in rec_exp.columns])
            if len(rec_exp) > 100_000:
                rec_exp = rec_exp.head(100_000)
            write_sheet(rec_exp, "Receipt Data", header_fmt=grey)
        except Exception:
            pass

        # Refund Data
        try:
            ref_exp = refund_df.copy()
            if len(ref_exp) > 100_000:
                ref_exp = ref_exp.head(100_000)
            write_sheet(ref_exp, "Refund Data", header_fmt=grey)
        except Exception:
            pass

        # Renewal Data (month-filtered)
        try:
            if renewal_df is not None and len(renewal_df) > 0:
                rnl_exp = renewal_df.copy()
                if len(rnl_exp) > 100_000:
                    rnl_exp = rnl_exp.head(100_000)
                write_sheet(rnl_exp, "Renewal Data", header_fmt=grey)
        except Exception:
            pass

        # Structure Dump (flattened from struct_map dict)
        try:
            struct_rows = [
                {"Employee ID": eid,
                 "Employee Name":    v.get("Employee Name",""),
                 "Vertical":         v.get("Vertical",""),
                 "Location":         v.get("Location",""),
                 "Joining Date":     str(v.get("Joining Date",""))[:10],
                 "Vintage":          v.get("Vintage",""),
                 "Team":             v.get("Team",""),
                 "Vintage Bucket":   v.get("Vintage Bucket",""),
                 "Client Count":     v.get("Client Count",0),
                 "Collection Target":v.get("Collection Target",0),
                 "MDC Client Count": v.get("MDC Client Count",0),
                 "L2 Name":          v.get("L2 Name",""),
                 "L3 Name":          v.get("L3 Name",""),
                 "L4 Name":          v.get("L4 Name",""),
                 "Remarks":          v.get("Remarks",""),
                }
                for eid, v in struct_map.items()
            ]
            write_sheet(pd.DataFrame(struct_rows), "Structure Dump", header_fmt=grey)
        except Exception:
            pass

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
