"""
IndiaMart Incentive Calculator -- April 2026

Changes in this version (v19):
  - Fix 1: MDC1_PRODUCTS -- removed MDC 2 Year / MDC 3 Year (multi-year, not MDC-1)
            -> MDC-1 CMR% per employee now accurate -> correct 1.2x/1.0x/0.5x multiplier
  - Fix 2: SPS Booster -- auto 1.2x for Vintage Bucket = 'SPS' employees (not sidebar-gated)
            Pune TAT/60D override still works for non-SPS employees
  - Fix 3: CSD Spot -- per-employee NR upsell count from receipt (replaces global sidebar)
  - Fix 4: KCD transaction count -- uses prod_score_receipt (productive rows only)
            not txn_count (all receipt rows) -> base incentive now matches sir's calc
  - Fix 5: KCD SS+ penalty -- only applied when ss_sent ≥ 3 AND ss_cmr < 70%
            (≤2 SS+ sent = no penalty, not enough data)
  - Fix 6: KCD Incremental -- (Net_Deal_Val − Collection_Target) x 1.4%
            Collection_Target = PCR_Target x ClientA from structure dump
  - Fix 7: Listing/Catalog -- use collection_target directly (not base_cxrate + list_cxrate)

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
# SS+ KEYWORDS (not in slab config -- product classification)
# ═══════════════════════════════════════════════════════════════
SS_PLUS_KEYWORDS  = ["IM STAR", "IM LEADER", "STAR", "LEADER", "PREF STAR", "PREF LEADER"]

# ── Productivity tier mapping (Receipt file: Product + Upsell columns) ──
# Maps to PoP incentive: Tier1=₹500, Tier2=₹1000, Tier3=₹1500
PURE_RENEWAL_PRODUCTS = {
    "Renewal","TS1Renewal","TS2Renewal","TS3Renewal","WS Renewal","IVE Renewal",
    "SS Renewal","IM SS Renewal","LS Renewal","IM LS Renewal","Pref SS Renewal",
    "Pref LS Renewal","FPL Renewal","IM IL Renewal","CL Renewal","IL Renewal",
    "Pref IL Renewal"
}

# Upsell column values → service tier
UPSELL_TIER1 = {"Combo 1YR","TS Pro-1","TS pro-1"}
UPSELL_TIER2 = {
    "MYR","Combo 2YR","Maxi Pro-1","Maximiser","TS Pro-2","Maxi Pro-2",
    "VEXPS-MYR","VEXPG-12","VEXPS-12","VEXPS-6","VEXPD-6",
    "VEXPD-12","VEXPG-6","VEXPG-MYR","VEXPP-12","VEXPP-MYR","VEXPD-MYR",
}
UPSELL_TIER3 = {
    "Combo 3YR","TS Pro-3","Maxi Pro-3","Maximiser-3","Maxi Pro-2","Maxi pro-3","Maximiser-2",
    "IM Star Pro","Preferred Star Pro","IM Leader Pro","Preferred Leader Pro",
}

# Product column values → service tier (when Upsell is blank)
PROD_TIER1 = {"Renewal","MDC Annual","TS1Renewal","TS Pro-1","TS pro-1","Maxi Pro-1"}
PROD_TIER2 = {"TS2Renewal","WS Renewal","IVE Renewal","Combo 2YR","Maxi Pro-2",
              "TS Pro-2","Maximiser","MYR","myr","Combo 2YR",
              "VEXPS-12","VEXPS-MYR","VEXPG-12","VEXPG-MYR",
              "VEXPD-12","VEXPD-MYR","VEXPP-12","VEXPP-MYR"}
PROD_TIER3 = {"TS3Renewal","SS Renewal","IM SS Renewal","LS Renewal","IM LS Renewal",
              "Pref SS Renewal","Pref LS Renewal","CL Renewal","IL Renewal",
              "IM IL Renewal","Pref IL Renewal","Combo 3YR","TS Pro-3","Maxi Pro-3",
              "Maximiser-3","Maxi pro-3",
              "IM Star Pro","Preferred Star Pro","IM Leader Pro","Preferred Leader Pro"}

TIER_REWARD = {1: 500, 2: 1000, 3: 1500}

# IM Star Pro+ products for 28-30 Apr spot (BX="Yes" flag in sir's FSF receipt)
# Applicable: Relationship Manager (CSD) / Sr. Account Manager (KCD) - ₹1000/sale
IM_STAR_PRO_PRODUCTS = {
    "IM Star Pro", "IM Leader Pro", "Preferred Leader Pro", "Preferred Star Pro",
    "IM Star Pro+", "Preferred Star Pro+",
}

# KCD WK-1 Power of Productivity spot product categories (01-09 May)
# Maps product name keywords → category key used in kcd_wk1_spot config
WK1_PRODUCT_CATEGORIES = {
    "IM_STAR_PRO":   ["IM Star Pro", "IM Star/Pro"],
    "IM_LEADER_PRO": ["IM Leader Pro", "IM Leader/Pro"],
    "PREF_SS_PRO":   ["Preferred Star Pro", "Pref SS", "Pref Star Pro", "Pref SS/Pro"],
    "PREF_LS_PRO":   ["Preferred Leader Pro", "Pref LS", "Pref Leader Pro", "Pref LS/Pro"],
    "VALUE_PLUS":    ["Value+", "Value Plus"],
    "PL_PLUS":       ["PL+", "PL Plus", "Preferred Leader Plus"],
}

# IM Insta products (0.5 productivity)
INSTA_PRODUCTS = {"IM InstaDiamond","IM InstaGold","IM InstaPlatinum",
                  "IM insta Diamond","IM Insta Renewal",
                  "Lead Manager Pro Gold","Lead Manager Pro Platinum"}
INSTA_KEYWORDS    = ["INSTA"]          # IM Insta = 0.5 productivity (KCD/CSD SPS)

# MDC-1 products for per-employee MDC-1 CMR% calculation (CSD SPS)
# Only true 1-year / annual MDC products -- MDC 2 Year / MDC 3 Year are multi-year, NOT MDC-1
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
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
        {"PCDV_Threshold": 2400, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
    ])

    # ── CSD SPS 270D+ (May'26) ── thresholds: 2600/3000/3200, lower per-txn rates
    csd_sps_270 = pd.DataFrame([
        {"PCDV_Threshold": 3200, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 3000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
    ])

    # ── CSD Relationship Manager slabs (May'26) ──────────────────────────────
    # May PPT slide 6: PCDV 2500/2700/2900 → Slab1(53-60%)/Slab2(65%+), lower per-txn rates
    csd_rm = pd.DataFrame([
        {"PCR_Threshold": 2900, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCR_Threshold": 2700, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCR_Threshold": 2500, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    # RM CMR slab targets — May eligibility: 53-59.9%→50%, 60-64.9%→Slab1, 65%+→Slab2
    csd_rm_params = pd.DataFrame([
        {"Parameter": "CMR_Slab1_Target_%", "Value": 60},
        {"Parameter": "CMR_Slab2_Target_%", "Value": 65},
        {"Parameter": "CMR_Min_Eligible_%",  "Value": 53},
    ])

    # ── KCD SAM (L2) -- Sr. Account Manager slabs (May'26) ──────────────────
    # May: all per-txn rates reduced by one tier vs April
    kcd_sam_regular = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 1250, "CMR80_Per_Txn": 1500},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 1000, "CMR80_Per_Txn": 1200},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn":  750, "CMR80_Per_Txn":  900},
    ])
    kcd_sam_roi = pd.DataFrame([
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 1250, "CMR80_Per_Txn": 1500},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn": 1000, "CMR80_Per_Txn": 1200},
        {"PCDV_Threshold":  8000, "CMR72_Per_Txn":  750, "CMR80_Per_Txn":  900},
    ])
    kcd_sam_hvri = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 1250, "CMR80_Per_Txn": 1500},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 1000, "CMR80_Per_Txn": 1200},
        {"PCDV_Threshold": 10000, "CMR72_Per_Txn":  750, "CMR80_Per_Txn":  900},
    ])
    kcd_sam_nagpur = pd.DataFrame([
        {"PCDV_Threshold": 32000, "CMR72_Per_Txn": 1250, "CMR80_Per_Txn": 1500},
        {"PCDV_Threshold": 28000, "CMR72_Per_Txn": 1000, "CMR80_Per_Txn": 1200},
        {"PCDV_Threshold": 24000, "CMR72_Per_Txn":  750, "CMR80_Per_Txn":  900},
    ])
    kcd_sam_listing = pd.DataFrame([
        {"Target_Pct": 140, "CMR72_Per_Txn": 1250, "CMR80_Per_Txn": 1500},
        {"Target_Pct": 120, "CMR72_Per_Txn": 1000, "CMR80_Per_Txn": 1200},
        {"Target_Pct": 95,  "CMR72_Per_Txn":  750, "CMR80_Per_Txn":  900},
    ])
    kcd_sam_catalog = kcd_sam_listing.copy()

    # SAM-ILP incentive % rates (standard variant; upload separate for L-variant)
    kcd_sam_ilp = pd.DataFrame([
        {"Target_Achievement_%": 120, "Incentive_Rate_%": 0.80},
        {"Target_Achievement_%": 100, "Incentive_Rate_%": 0.75},
        {"Target_Achievement_%": 95,  "Incentive_Rate_%": 0.65},
    ])
    # SAM Incremental rates (lower than L1)
    kcd_sam_incr = pd.DataFrame([
        {"Team": "Regular", "Incr_Threshold_PCDV": 17000, "Incr_Rate_%": 0.65},
        {"Team": "ROI",     "Incr_Threshold_PCDV": 14000, "Incr_Rate_%": 0.65},
        {"Team": "HVRI",    "Incr_Threshold_PCDV": 17000, "Incr_Rate_%": 0.65},
        {"Team": "Nagpur",  "Incr_Threshold_PCDV": 32000, "Incr_Rate_%": 0.45},
        {"Team": "Listing", "Incr_Threshold_Pct":  140,   "Incr_Rate_%": 0.65},
        {"Team": "Catalog", "Incr_Threshold_Pct":  140,   "Incr_Rate_%": 0.65},
    ])

    # ── CSD SPS Multipliers ──
    csd_sps_mult = pd.DataFrame([
        {"Parameter": "MDC1_Above_%",      "Value": 35,  "Multiplier_%": 120},
        {"Parameter": "MDC1_Between_%",    "Value": 25,  "Multiplier_%": 100},
        {"Parameter": "MDC1_Below_%",      "Value": 0,   "Multiplier_%": 50},
        {"Parameter": "Booster_TAT_Below", "Value": 1,   "Multiplier_%": 120},
        {"Parameter": "Booster_60D_Below", "Value": 10,  "Multiplier_%": 120},
    ])

    # ── CSD Spot (May 1-16 FNT-1) — May'26 ── base increased vs April
    # L1 (90+ vintage only): ≥3 prods → ₹2000 base + ₹750/txn after 3
    # RM: ≥2.5 prods → ₹3000 base + ₹500/txn after 2.5
    csd_spot = pd.DataFrame([
        {"Parameter": "Min_NR_Upsell_AMR",   "Value": 3},
        {"Parameter": "Base_Reward",          "Value": 2000},
        {"Parameter": "Per_Txn_After_Min",    "Value": 750},
        {"Parameter": "RM_Base_Reward",       "Value": 3000},
        {"Parameter": "RM_Per_Txn_After_Min", "Value": 500},
        {"Parameter": "RM_Min_Prod_Ratio",    "Value": 2.5},
        {"Parameter": "Only_90Plus_Vintage",  "Value": 1},
    ])

    # ── Power of Productivity ──
    pop = pd.DataFrame([
        {"Product_Keywords": "MDC,MDC1,MDC-1,MDC 1,TS 1,TS1",                              "Incentive_Per_Txn": 500},
        {"Product_Keywords": "MDC2,MDC 2,MDC3,MDC 3,TS 2,TS2,MAXI ANNUAL,MAXIMISER,VE,IVE,WS-A", "Incentive_Per_Txn": 1000},
        {"Product_Keywords": "TS 3,TS3,MAXI 2,WS-M",                                        "Incentive_Per_Txn": 1500},
    ])

    # ── KCD Regular (270D+) — May'26 ── same thresholds, lower per-txn rates
    kcd_270 = pd.DataFrame([
        {"PCDV_Threshold": 19000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 16000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"PCDV_Threshold": 13000, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
    ])

    # ── KCD Regular (91-270D) — May'26 ──
    kcd_91_270 = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
    ])

    # ── KCD Regular (0-90D / CSD-to-KCD new joined after Jan'26) — May'26 ──
    kcd_0_90 = pd.DataFrame([
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 11000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"PCDV_Threshold":  8000, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
    ])

    # ── KCD HVRI — May'26 ──
    kcd_hvri = pd.DataFrame([
        {"PCDV_Threshold": 17000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 14000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"PCDV_Threshold": 10000, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
    ])

    # ── KCD Nagpur Pharma — May'26 ──
    kcd_nagpur = pd.DataFrame([
        {"PCDV_Threshold": 32000, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"PCDV_Threshold": 28000, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"PCDV_Threshold": 24000, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
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

    # ── KCD Listing Slabs — May'26 ── (lower per-txn rates)
    kcd_listing = pd.DataFrame([
        {"Target_Pct": 140, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 120, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"Target_Pct": 100, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
    ])
    kcd_listing_rates = pd.DataFrame([
        {"Vintage":  "270D+",   "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage":  "91-270D", "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage":  "31-90D",  "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
        {"Vintage":  "0-30D",   "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
    ])

    # ── KCD Catalog Slabs — May'26 ── (identical to Listing per May PPT)
    kcd_catalog = pd.DataFrame([
        {"Target_Pct": 140, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 120, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"Target_Pct": 100, "CMR72_Per_Txn": 1500, "CMR80_Per_Txn": 1800},
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

    # ── Scheme Parameters — must be defined before return ────────────────────
    scheme_params = pd.DataFrame([
        {"Parameter": "CSD_NewJoiner_Cap",         "Value": 20000, "Description": "Max PCDV+PoP incentive for 0-90D employees (₹)"},
        {"Parameter": "CSD_PoP_Min_CMR_Pct",       "Value": 55.0,  "Description": "Min CMR% to earn PoP (0-90D)"},
        {"Parameter": "CSD_NewJoiner_Incr_Rate_%",  "Value": 3.0,   "Description": "% of incremental DV above top PCDV slab (0-90D)"},
        {"Parameter": "CSD_PoP_Min_Txn_0_30D",     "Value": 2,     "Description": "Min productivity count to qualify PoP (0-30D)"},
        {"Parameter": "CSD_PoP_Min_Txn_31_90D",    "Value": 3,     "Description": "Min productivity count to qualify PoP (31-90D)"},
        {"Parameter": "CSD_PoP_Use_Slab_Gate",     "Value": 0,     "Description": "PoP CMR gate: 0=flat CMR% floor (Apr/Mar), 1=Slab1 target must be achieved (May+)"},
        {"Parameter": "CSD_BothAchievers_On",      "Value": 0,     "Description": "Both Achievers PoP mult: 0=off (Apr/Mar), 1=on (May+)→PCDV+CMR=125% CMR-only=50%"},
        {"Parameter": "CSD_BothAchievers_Pct",     "Value": 125,   "Description": "Both Achievers full payout % (when PCDV slab + CMR Slab1 both achieved)"},
        {"Parameter": "CSD_OnlyCMR_Achiever_Pct",  "Value": 50,    "Description": "Only CMR Achiever payout % (CMR Slab1 hit but PCDV slab not hit)"},
        {"Parameter": "CSD_MDC1_Mid_Threshold_%",   "Value": 25,   "Description": "MDC-1 CMR% between Mid and High → Mid_Mult; below → Low_Mult"},
        {"Parameter": "CSD_MDC1_High_Mult_%",       "Value": 120,  "Description": "MDC-1 multiplier (%) when above High threshold"},
        {"Parameter": "CSD_MDC1_Mid_Mult_%",        "Value": 100,  "Description": "MDC-1 multiplier (%) when between thresholds"},
        {"Parameter": "CSD_MDC1_Low_Mult_%",        "Value": 50,   "Description": "MDC-1 multiplier (%) when below Mid threshold"},
        {"Parameter": "CSD_Booster_TAT_Below",      "Value": 1,    "Description": "SPS Booster: Ext Ticket TAT must be below this"},
        {"Parameter": "CSD_Booster_60D_Below_%",    "Value": 10,   "Description": "SPS Booster: 60D Not Met must be below this %"},
        {"Parameter": "CSD_Booster_Mult_%",         "Value": 120,  "Description": "SPS Booster multiplier when both criteria met (%)"},
        {"Parameter": "CSD_RM_CMR_Min_%",           "Value": 53,   "Description": "CSD RM min CMR% to be eligible (below = no incentive)"},
        {"Parameter": "CSD_RM_CMR_Slab1_%",         "Value": 60,   "Description": "CSD RM Slab1 CMR threshold (100% payout)"},
        {"Parameter": "CSD_RM_CMR_Slab2_%",         "Value": 65,   "Description": "CSD RM Slab2 CMR threshold (120% payout)"},
        {"Parameter": "KCD_SS_Plus_Threshold_%",    "Value": 72,   "Description": "KCD SS+ gate: ≥ this CMR% → 100% payout, else 50%"},
        {"Parameter": "KCD_CMR_Slab2_%",            "Value": 80,   "Description": "KCD higher CMR slab for top per-txn rate"},
        {"Parameter": "KCD_Min_Prod_Week",          "Value": 2,    "Description": "Min productivity per week to unlock base incentive"},
        {"Parameter": "KCD_Min_Prod_Month",         "Value": 8,    "Description": "Min monthly productivity (established employees)"},
        {"Parameter": "KCD_Min_Prod_Month_New",     "Value": 6,    "Description": "Min monthly productivity (CSD-to-KCD / new joiners)"},
        {"Parameter": "KCD_Incr_Rate_Regular_%",    "Value": 1.4,  "Description": "KCD incremental % above threshold (Regular/ROI/HVRI/Listing)"},
        {"Parameter": "KCD_Incr_Rate_Nagpur_%",     "Value": 0.85, "Description": "KCD Nagpur L1 incremental % above 32K PCDV"},
        {"Parameter": "KCD_SAM_Incr_Rate_%",        "Value": 0.65, "Description": "KCD SAM (L2) incremental % above threshold"},
        {"Parameter": "KCD_SAM_Nagpur_Incr_%",      "Value": 0.45, "Description": "KCD SAM Nagpur incremental % above 32K PCDV"},
        {"Parameter": "IM_Insta_L1_Rate",           "Value": 300,  "Description": "IM Insta spot per qualifying sale (L1, ₹)"},
        {"Parameter": "IM_Insta_L2_Rate",           "Value": 150,  "Description": "IM Insta spot per qualifying sale (L2 SAM, ₹)"},
        {"Parameter": "IM_Insta_Min_Week",          "Value": 2,    "Description": "Min IM Insta prods in any one week to qualify"},
        {"Parameter": "IM_Insta_Min_Month",         "Value": 7,    "Description": "Min IM Insta prods total in the month to qualify"},
        {"Parameter": "MCATs_L1_Rate",              "Value": 1000, "Description": "MCATs spot per MCAT from 3rd onwards (L1, ₹)"},
        {"Parameter": "MCATs_L2_Rate",              "Value": 500,  "Description": "MCATs spot per MCAT from 3rd onwards (L2 SAM, ₹)"},
        {"Parameter": "MCATs_Min_Count",            "Value": 2,    "Description": "MCATs count before spot starts (spot from count+1)"},
        {"Parameter": "IM_Star_Pro_Spot_Rate",      "Value": 1000, "Description": "IM Star Pro+/Leader Pro/Pref spot per new sale (₹)"},
        {"Parameter": "IM_Star_Pro_From_Day",       "Value": 28,   "Description": "Day-of-month from which IM Star Pro+ spot is active"},
        # ─ Excellent Incentive Spot (single day) ──────────────────────────────
        {"Parameter": "Excellent_Spot_L1_Rate",    "Value": 750,  "Description": "Excellent Spot: Rs/txn for CSD/KCD L1 (90+ vintage only)"},
        {"Parameter": "Excellent_Spot_L2_Rate",    "Value": 400,  "Description": "Excellent Spot: Rs/txn for L2 (RM/SAM) from 2nd txn"},
        {"Parameter": "Excellent_Spot_Day",        "Value": 4,    "Description": "Day-of-month on which Excellent Incentive Spot applies"},
        {"Parameter": "KCD_HC_Mult_Regular",        "Value": 21000,"Description": "HC = Client-A × this (Regular / Listing / Catalog L1)"},
        {"Parameter": "KCD_HC_Mult_ROI",            "Value": 14000,"Description": "HC multiplier for ROI L1"},
        {"Parameter": "KCD_HC_Mult_HVRI",           "Value": 17000,"Description": "HC multiplier for HVRI L1"},
        {"Parameter": "KCD_HC_Mult_Nagpur",         "Value": 32000,"Description": "HC multiplier for Nagpur L1"},
        {"Parameter": "KCD_HC_Mult_SAM",            "Value": 17000,"Description": "HC multiplier for SAM / L2 (all teams)"},
        # ─ BM / RM AOP Scheme (L3 = BM, L4 = RM) ─────────────────────────────
        {"Parameter": "CSD_BM_AOP_Rate_%",          "Value": 1.00,  "Description": "CSD BM (L3) base rate: % of Net Deal Value"},
        {"Parameter": "CSD_RM_AOP_Rate_%",          "Value": 0.70,  "Description": "CSD RM (L4) base rate: % of Net Deal Value"},
        {"Parameter": "CSD_BM_AOP_Cap_%",           "Value": 5.00,  "Description": "CSD BM max payout as % of Deal Value"},
        {"Parameter": "CSD_RM_AOP_Cap_%",           "Value": 4.00,  "Description": "CSD RM max payout as % of Deal Value"},
        {"Parameter": "KCD_BM_AOP_Rate_%",          "Value": 0.50,  "Description": "KCD BM (L3) base rate: % of Net Deal Value"},
        {"Parameter": "KCD_RM_AOP_Rate_%",          "Value": 0.35,  "Description": "KCD RM (L4) base rate: % of Net Deal Value"},
        {"Parameter": "KCD_BM_AOP_Cap_%",           "Value": 2.00,  "Description": "KCD BM max payout as % of Deal Value"},
        {"Parameter": "KCD_RM_AOP_Cap_%",           "Value": 2.00,  "Description": "KCD RM max payout as % of Deal Value"},
        {"Parameter": "AOP_Min_Achievement_%",       "Value": 95,    "Description": "Minimum AOP achievement % to be eligible"},
        {"Parameter": "AOP_Mult_95_100_%",           "Value": 100,   "Description": "AOP multiplier for 95-100% achievement"},
        {"Parameter": "AOP_Mult_100_105_%",          "Value": 110,   "Description": "AOP multiplier for 100-105% achievement"},
        {"Parameter": "AOP_Mult_105_110_%",          "Value": 120,   "Description": "AOP multiplier for 105-110% achievement"},
        {"Parameter": "AOP_Mult_110_Plus_%",         "Value": 130,   "Description": "AOP multiplier for 110%+ achievement"},
        {"Parameter": "CSD_BM_CMR_Min_%",           "Value": 53,    "Description": "CSD BM/RM min CMR% to be eligible"},
        {"Parameter": "CSD_BM_CMR_Slab1_%",         "Value": 60,    "Description": "CSD BM/RM CMR: 50% payout (53-60%)"},
        {"Parameter": "CSD_BM_CMR_Slab2_%",         "Value": 65,    "Description": "CSD BM/RM CMR: 100% (60-65%), 120% above"},
        {"Parameter": "KCD_BM_CMR_Min_%",           "Value": 72,    "Description": "KCD BM/RM min CMR% to be eligible"},
        {"Parameter": "KCD_BM_CMR_Slab1_%",         "Value": 75,    "Description": "KCD BM/RM CMR: 75% payout (72-75%)"},
        {"Parameter": "KCD_BM_CMR_Slab2_%",         "Value": 80,    "Description": "KCD BM/RM CMR: 100% (75-80%), 120% above"},
        {"Parameter": "KCD_BM_SS_Plus_Min_%",        "Value": 72,    "Description": "KCD BM/RM SS+ gate: ≥ this → 100%, else 50%"},
        # ─ KCD Collection Target per-client rates (auto-derived when no target file uploaded) ─
        {"Parameter": "KCD_Target_Regular_91_270",    "Value": 11000, "Description": "KCD Regular 91-270D: target per client (₹) — lowest slab"},
        {"Parameter": "KCD_Target_Regular_270",       "Value": 13000, "Description": "KCD Regular 270D+: target per client (₹)"},
        {"Parameter": "KCD_Target_Regular_0_90",      "Value": 8000,  "Description": "KCD Regular 0-90D / New: target per client (₹)"},
        {"Parameter": "KCD_Target_ROI",               "Value": 8000,  "Description": "KCD ROI: target per client (₹)"},
        {"Parameter": "KCD_Target_HVRI",              "Value": 10000, "Description": "KCD HVRI: target per client (₹)"},
        {"Parameter": "KCD_Target_Nagpur",            "Value": 24000, "Description": "KCD Nagpur: target per client (₹)"},
        {"Parameter": "KCD_Target_Listing_Base",      "Value": 7000,  "Description": "KCD Listing/Catalog: target per base client (₹) 91D+"},
        {"Parameter": "KCD_Target_Listing_Client",    "Value": 22000, "Description": "KCD Listing/Catalog: target per listing client (₹) 91D+"},
        {"Parameter": "KCD_Target_Listing_Base_New",  "Value": 5000,  "Description": "KCD Listing/Catalog: target per base client (₹) 0-90D"},
        {"Parameter": "KCD_Target_Listing_Client_New","Value": 15000, "Description": "KCD Listing/Catalog: target per listing client (₹) 0-90D"},
    ])

    return {
        "CSD_New_Params":       csd_new_incr,
        "CSD_SPS_91_270D":      csd_sps_91,
        "CSD_SPS_270D_Plus":    csd_sps_270,
        "CSD_RM":               csd_rm,
        "CSD_RM_Params":        csd_rm_params,
        "CSD_SPS_Multipliers":  csd_sps_mult,
        "CSD_Spot":             csd_spot,
        "Power_of_Productivity":pop,
        "KCD_SAM_Regular":      kcd_sam_regular,
        "KCD_SAM_ROI":          kcd_sam_roi,
        "KCD_SAM_HVRI":         kcd_sam_hvri,
        "KCD_SAM_Nagpur":       kcd_sam_nagpur,
        "KCD_SAM_Listing":      kcd_sam_listing,
        "KCD_SAM_Catalog":      kcd_sam_catalog,
        "KCD_SAM_Incr_Rates":   kcd_sam_incr,
        "KCD_SAM_ILP":          kcd_sam_ilp,
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
        "Scheme_Params":        scheme_params,
    }


def load_slab_config(uploaded_file):
    """
    Load slab config from uploaded Excel.
    Returns dict of DataFrames, one per sheet.
    Falls back to defaults (March) if not uploaded.
    Upload an April config file to switch to April slabs.
    """
    defaults = build_default_slab_config()
    if uploaded_file is None:
        return defaults

    def _read_sheet(f, sheet):
        """Read a sheet with header=1 (data starts row 2). Fall back to header=0 if
        the sheet has too few rows (ValueError: Passed header=1 but only N lines)."""
        try:
            df = pd.read_excel(f, sheet_name=sheet, header=1)
            df = df.dropna(how="all")
            # Sanity-check: if all columns are Unnamed the header row was actually row 0
            if len(df.columns) > 0 and all(str(c).startswith("Unnamed") for c in df.columns):
                raise ValueError("header row appears to be row 0")
            return df
        except Exception:
            try:
                df = pd.read_excel(f, sheet_name=sheet, header=0)
                return df.dropna(how="all")
            except Exception:
                return pd.DataFrame()   # empty DF — caller falls back to default

    xl = pd.ExcelFile(uploaded_file)
    config = {}
    # Standard sheets — use loaded version or fall back to default
    for sheet_name, default_df in defaults.items():
        if sheet_name in xl.sheet_names:
            _loaded = _read_sheet(uploaded_file, sheet_name)
            config[sheet_name] = _loaded if (_loaded is not None and not _loaded.empty) else default_df
        else:
            config[sheet_name] = default_df

    # Any extra sheets in the uploaded file (Apr/May variants etc.)
    for sheet_name in xl.sheet_names:
        if sheet_name not in config:
            _extra = _read_sheet(uploaded_file, sheet_name)
            if _extra is not None and not _extra.empty:
                config[sheet_name] = _extra

    return config


def parse_slabs(cfg):
    """Convert loaded config DataFrames into the tuples the calculation functions expect."""

    # ── Scheme_Params: single source of truth for all key numbers ────────────
    _sp_df = cfg.get("Scheme_Params", pd.DataFrame())
    _sp = {}
    if len(_sp_df) > 0 and "Parameter" in _sp_df.columns:
        _sp = _sp_df.set_index("Parameter")["Value"].to_dict()
    def _p(key, default):
        """Read a param from Scheme_Params with a fallback default."""
        return float(_sp[key]) if key in _sp else float(default)

    # Extract all scheme parameters (used throughout the S dict and calculations)
    _nj_cap          = _p("CSD_NewJoiner_Cap",         20000)
    _pop_cmr_floor   = _p("CSD_PoP_Min_CMR_Pct",        55.0)
    _nj_incr_rate    = _p("CSD_NewJoiner_Incr_Rate_%",    3.0) / 100
    _pop_min_0_30    = int(_p("CSD_PoP_Min_Txn_0_30D",    2))
    _pop_min_31_90   = int(_p("CSD_PoP_Min_Txn_31_90D",   3))
    _pop_slab_gate   = bool(int(_p("CSD_PoP_Use_Slab_Gate",   0)))   # False=flat floor, True=Slab1 gate
    _both_achiev_on  = bool(int(_p("CSD_BothAchievers_On",    0)))   # False=off (Apr), True=on (May)
    _both_achiev_pct = _p("CSD_BothAchievers_Pct",   125) / 100      # 1.25
    _cmr_only_pct    = _p("CSD_OnlyCMR_Achiever_Pct", 50) / 100     # 0.50
    _mdc1_hi_thr     = _p("CSD_MDC1_High_Threshold_%",   35)
    _mdc1_mid_thr    = _p("CSD_MDC1_Mid_Threshold_%",    25)
    _mdc1_hi_mult    = _p("CSD_MDC1_High_Mult_%",       120) / 100
    _mdc1_mid_mult   = _p("CSD_MDC1_Mid_Mult_%",        100) / 100
    _mdc1_low_mult   = _p("CSD_MDC1_Low_Mult_%",         50) / 100
    _boost_tat       = _p("CSD_Booster_TAT_Below",        1)
    _boost_60d       = _p("CSD_Booster_60D_Below_%",     10)
    _boost_mult      = _p("CSD_Booster_Mult_%",         120) / 100
    _rm_cmr_min      = _p("CSD_RM_CMR_Min_%",           53)
    _rm_cmr_s1       = _p("CSD_RM_CMR_Slab1_%",         60)
    _rm_cmr_s2       = _p("CSD_RM_CMR_Slab2_%",         65)
    _kcd_ss_thr      = _p("KCD_SS_Plus_Threshold_%",    72)
    _kcd_cmr_s2      = _p("KCD_CMR_Slab2_%",            80)
    _kcd_min_w       = int(_p("KCD_Min_Prod_Week",        2))
    _kcd_min_m       = int(_p("KCD_Min_Prod_Month",       8))
    _kcd_min_m_new   = int(_p("KCD_Min_Prod_Month_New",   6))
    _kcd_incr_reg    = _p("KCD_Incr_Rate_Regular_%",    1.4) / 100
    _kcd_incr_nag    = _p("KCD_Incr_Rate_Nagpur_%",    0.85) / 100
    _kcd_sam_incr    = _p("KCD_SAM_Incr_Rate_%",       0.65) / 100
    _kcd_sam_nag_i   = _p("KCD_SAM_Nagpur_Incr_%",     0.45) / 100
    _insta_l1        = int(_p("IM_Insta_L1_Rate",       300))
    _insta_l2        = int(_p("IM_Insta_L2_Rate",       150))
    _insta_min_w     = int(_p("IM_Insta_Min_Week",        2))
    _insta_min_m     = int(_p("IM_Insta_Min_Month",       7))
    _mcats_l1        = int(_p("MCATs_L1_Rate",         1000))
    _mcats_l2        = int(_p("MCATs_L2_Rate",          500))
    _mcats_min       = int(_p("MCATs_Min_Count",          2))
    _star_rate       = int(_p("IM_Star_Pro_Spot_Rate",  1000))
    _star_from_day   = int(_p("IM_Star_Pro_From_Day",    28))
    _hc_regular      = int(_p("KCD_HC_Mult_Regular",  21000))
    _hc_roi          = int(_p("KCD_HC_Mult_ROI",      14000))
    _hc_hvri         = int(_p("KCD_HC_Mult_HVRI",     17000))
    _hc_nagpur       = int(_p("KCD_HC_Mult_Nagpur",   32000))
    _hc_sam          = int(_p("KCD_HC_Mult_SAM",      17000))
    # BM/RM AOP scheme params
    _csd_bm_rate     = _p("CSD_BM_AOP_Rate_%",  1.00) / 100
    _csd_rm_rate     = _p("CSD_RM_AOP_Rate_%",  0.70) / 100
    _csd_bm_cap      = _p("CSD_BM_AOP_Cap_%",   5.00) / 100
    _csd_rm_cap      = _p("CSD_RM_AOP_Cap_%",   4.00) / 100
    _kcd_bm_rate     = _p("KCD_BM_AOP_Rate_%",  0.50) / 100
    _kcd_rm_rate     = _p("KCD_RM_AOP_Rate_%",  0.35) / 100
    _kcd_bm_cap      = _p("KCD_BM_AOP_Cap_%",   2.00) / 100
    _kcd_rm_cap      = _p("KCD_RM_AOP_Cap_%",   2.00) / 100
    _aop_min         = _p("AOP_Min_Achievement_%",    95)
    _aop_m1          = _p("AOP_Mult_95_100_%",       100) / 100
    _aop_m2          = _p("AOP_Mult_100_105_%",      110) / 100
    _aop_m3          = _p("AOP_Mult_105_110_%",      120) / 100
    _aop_m4          = _p("AOP_Mult_110_Plus_%",     130) / 100
    _csd_bm_cmr_min  = _p("CSD_BM_CMR_Min_%",         53)
    _csd_bm_cmr_s1   = _p("CSD_BM_CMR_Slab1_%",       60)
    _csd_bm_cmr_s2   = _p("CSD_BM_CMR_Slab2_%",       65)
    _kcd_bm_cmr_min  = _p("KCD_BM_CMR_Min_%",         72)
    _kcd_bm_cmr_s1   = _p("KCD_BM_CMR_Slab1_%",       75)
    _kcd_bm_cmr_s2   = _p("KCD_BM_CMR_Slab2_%",       80)
    _kcd_bm_ss_min   = _p("KCD_BM_SS_Plus_Min_%",     72)

    # ── CSD New (April or March slabs) ───────────────────────
    _new_slab_key   = ("CSD_New_Slabs_Apr" if "CSD_New_Slabs_Apr" in cfg
                       else "CSD_New_Slabs"  if "CSD_New_Slabs"    in cfg else None)
    _new_params_key = ("CSD_New_Params_Apr" if "CSD_New_Params_Apr" in cfg
                       else "CSD_New_Params" if "CSD_New_Params"    in cfg else None)
    _ns_df = cfg.get(_new_slab_key, pd.DataFrame()) if _new_slab_key else pd.DataFrame()
    csd_new_slabs = (
        [(int(r["PCDV_Threshold"]), int(r["Payout"])) for _, r in _ns_df.iterrows()]
        if len(_ns_df) > 0 else [(2800,10500),(2400,7000),(2100,5100),(1800,3100)]
    )
    _np_df = cfg.get(_new_params_key, pd.DataFrame()) if _new_params_key else pd.DataFrame()
    params = ({str(r["Parameter"]): float(r["Value"]) for _, r in _np_df.iterrows()}
              if len(_np_df) > 0 and "Parameter" in _np_df.columns else {})
    csd_new_incr_thresh  = float(params.get("Incremental_Threshold", 2800))
    csd_new_incr_rate    = _nj_incr_rate if "CSD_NewJoiner_Incr_Rate_%" in _sp else float(params.get("Incremental_Rate_%", 3.0)) / 100
    csd_slab2_mult       = float(params.get("Slab2_CMR_Multiplier_%", 120)) / 100
    min_txn_0_30         = _pop_min_0_30 if "CSD_PoP_Min_Txn_0_30D" in _sp else int(params.get("Min_Txn_0_30D", 2))
    min_txn_31_90        = _pop_min_31_90 if "CSD_PoP_Min_Txn_31_90D" in _sp else int(params.get("Min_Txn_31_90D", 3))
    new_joiner_cap       = _nj_cap

    # ── CSD SPS (May → April → March fallback) ──────────────────
    def _csd_sps_slabs(may_key, apr_key, mar_key):
        k = (may_key if may_key in cfg else
             apr_key  if apr_key  in cfg else mar_key)
        df = cfg.get(k, pd.DataFrame())
        if df is None or len(df) == 0:
            return []
        return [(int(r["PCDV_Threshold"]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
                for _, r in df.iterrows()]
    csd_sps_91_270 = _csd_sps_slabs("CSD_SPS_91_270_May", "CSD_SPS_91_270_Apr", "CSD_SPS_91_270D")
    csd_sps_270p   = _csd_sps_slabs("CSD_SPS_270_May",    "CSD_SPS_270_Apr",    "CSD_SPS_270D_Plus")
    # CSD RM: May → Apr → default
    _rm_df = cfg.get("CSD_RM_May", cfg.get("CSD_RM", cfg.get("CSD_SPS_91_270D", pd.DataFrame())))
    _rm_thresh_col = ("PCR_Threshold" if "PCR_Threshold" in _rm_df.columns
                      else "PCDV_Threshold" if "PCDV_Threshold" in _rm_df.columns
                      else (_rm_df.columns[0] if len(_rm_df.columns) > 0 else "PCR_Threshold"))
    csd_rm_slabs = [
        (int(r[_rm_thresh_col]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
        for _, r in _rm_df.iterrows() if _rm_thresh_col in _rm_df.columns
    ]
    # RM CMR slab targets (configurable)
    _rm_params = cfg.get("CSD_RM_Params_May", cfg.get("CSD_RM_Params", pd.DataFrame()))
    _rm_params_dict = {}
    if len(_rm_params) > 0 and "Parameter" in _rm_params.columns:
        _rm_params_dict = {str(r["Parameter"]): float(r["Value"]) for _, r in _rm_params.iterrows()}
    rm_cmr_slab1 = _rm_params_dict.get("CMR_Slab1_Target_%", 55)
    rm_cmr_slab2 = _rm_params_dict.get("CMR_Slab2_Target_%", 60)

    # ── CSD SPS Multipliers — now driven by Scheme_Params, legacy sheet optional ──
    _mult_df = cfg.get("CSD_SPS_Multipliers", pd.DataFrame())
    # All values come from Scheme_Params; legacy sheet ignored if Scheme_Params present
    mdc1_above   = _mdc1_hi_thr
    mdc1_between = _mdc1_mid_thr
    mdc1_mult_hi = _mdc1_hi_mult
    mdc1_mult_md = _mdc1_mid_mult
    mdc1_mult_lo = _mdc1_low_mult
    boost_tat    = _boost_tat
    boost_d60    = _boost_60d
    boost_mult   = _boost_mult

    # ── CSD Spot ─────────────────────────────────────────────
    _csd_spot_df = cfg.get("CSD_Spot", pd.DataFrame())
    spot_params = {}
    if len(_csd_spot_df) > 0 and "Parameter" in _csd_spot_df.columns:
        spot_params = _csd_spot_df.set_index("Parameter")["Value"].to_dict()
    csd_spot_min     = int(spot_params.get("Min_NR_Upsell_AMR", 3))
    csd_spot_base    = int(spot_params.get("Base_Reward", 2000))
    csd_spot_per_txn = int(spot_params.get("Per_Txn_After_Min", 750))

    # ── CSD Spot April (FNT-1 / FNT-2 rates from config) ────
    csd_spot_apr_rows = {}   # keyed by "FNT1" / "FNT2"
    if "CSD_Spot_Apr" in cfg:
        for _, r in cfg["CSD_Spot_Apr"].iterrows():
            period = str(r.get("Period", "")).strip().upper()
            if period:
                csd_spot_apr_rows[period] = {
                    "min_prod":     int(r.get("Min_Prod", 3)),
                    "base":         int(r.get("Base_Amount", 0)),
                    "per_txn":      int(r.get("Per_Txn_After", 0)),
                }
    # May spot config: CSD_Spot_May overrides April defaults
    if "CSD_Spot_May" in cfg:
        for _, r in cfg["CSD_Spot_May"].iterrows():
            spot_type = str(r.get("Spot_Type", "")).strip().upper()
            if "L1" in spot_type:
                csd_spot_apr_rows["FNT1"] = {
                    "min_prod": int(r.get("Min_Prod", 3)),
                    "base":     int(r.get("Base_Reward", 2000)),
                    "per_txn":  int(r.get("Per_Txn", 750)),
                }
            elif "RM" in spot_type:
                csd_spot_apr_rows["RM_FNT1"] = {
                    "min_prod": float(r.get("Min_Prod", 2.5)),
                    "min_val":  float(r.get("Min_Prod", 2.5)),
                    "base":     int(r.get("Base_Reward", 3000)),
                    "per_txn":  int(r.get("Per_Txn", 500)),
                }
        # No FNT-2 in May — explicitly zero it out
        csd_spot_apr_rows["FNT2"] = {"min_prod": 999, "base": 0, "per_txn": 0}
    # Defaults if not in config
    if "FNT1" not in csd_spot_apr_rows:
        csd_spot_apr_rows["FNT1"] = {"min_prod": 3, "base": 2000, "per_txn": 750}
    if "FNT2" not in csd_spot_apr_rows:
        csd_spot_apr_rows["FNT2"] = {"min_prod": 3, "base": 2500, "per_txn": 1000}
    if "RM_FNT1" not in csd_spot_apr_rows:
        csd_spot_apr_rows["RM_FNT1"] = {"min_prod": 2.5, "min_val": 2.5, "base": 3000, "per_txn": 500}
    if "RM_FNT2" not in csd_spot_apr_rows:
        csd_spot_apr_rows["RM_FNT2"] = {"min_prod": 2.5, "min_val": 2.5, "base": 0, "per_txn": 0}

    # ── KCD Spot April (FNT rates per team/vintage key from config) ──
    kcd_spot_apr_rows = {}   # keyed by "ROI_0_90", "ROI_90p", "CAT_0_90", etc.
    if "KCD_Spot_Apr" in cfg:
        for _, r in cfg["KCD_Spot_Apr"].iterrows():
            key = str(r.get("Key", "")).strip()
            if key:
                kcd_spot_apr_rows[key] = {
                    "fnt1": (int(r.get("FNT1_Thresh",0)), int(r.get("FNT1_Base",0)),
                             int(r.get("FNT1_Unit",1000)), int(r.get("FNT1_Size",1000))),
                    "fnt2": (int(r.get("FNT2_Thresh",0)), int(r.get("FNT2_Base",0)),
                             int(r.get("FNT2_Unit",1000)), int(r.get("FNT2_Size",1000))),
                }

    # ── Power of Productivity ────────────────────────────────
    prod_to_pop = {}
    _pop_df = cfg.get("Power_of_Productivity", pd.DataFrame())
    if len(_pop_df) > 0 and "Product_Keywords" in _pop_df.columns:
        for _, r in _pop_df.iterrows():
            for kw in str(r["Product_Keywords"]).split(","):
                prod_to_pop[kw.strip().upper()] = int(r.get("Incentive_Per_Txn", 0))

    # ── KCD Regular (April or March slabs) ──────────────────
    def to_kcd_slabs(sheet_key):
        df = cfg.get(sheet_key, pd.DataFrame())
        if df is None or len(df) == 0:
            return []
        try:
            if "Slab1_Per_Txn" in df.columns:
                return [(int(r["PCDV_Threshold"]), int(r["Slab1_Per_Txn"]), int(r["Slab2_Per_Txn"]))
                        for _, r in df.iterrows()]
            else:
                return [(int(r["PCDV_Threshold"]), int(r["CMR72_Per_Txn"]), int(r["CMR80_Per_Txn"]))
                        for _, r in df.iterrows()]
        except Exception:
            return []
    def _kcd_key(may_key, apr_key, mar_key):
        return may_key if may_key in cfg else (apr_key if apr_key in cfg else mar_key)
    kcd_270_slabs    = to_kcd_slabs(_kcd_key("KCD_Regular_270_May",    "KCD_Regular_270_Apr",    "KCD_Regular_270D"))
    kcd_91_270_slabs = to_kcd_slabs(_kcd_key("KCD_Regular_91_270_May", "KCD_Regular_91_270_Apr", "KCD_Regular_91_270D"))
    kcd_0_90_slabs   = to_kcd_slabs(_kcd_key("KCD_New_0_90_May",       "KCD_New_0_90_Apr",       "KCD_Regular_0_90D"))
    if not kcd_0_90_slabs:  # Fallback to hardcoded default when sheet missing in Slab Config
        kcd_0_90_slabs = to_kcd_slabs("KCD_Regular_0_90D") if "KCD_Regular_0_90D" in cfg else [(14000,2500,3000),(11000,2000,2400),(8000,1500,1800)]
    kcd_hvri_slabs   = to_kcd_slabs(_kcd_key("KCD_HVRI_May",           "KCD_HVRI_Apr",           "KCD_HVRI"))
    kcd_nagpur_slabs = to_kcd_slabs(_kcd_key("KCD_Nagpur_May",         "KCD_Nagpur_Apr",         "KCD_Nagpur_Pharma"))

    # ── KCD Incremental Rates ────────────────────────────────
    kcd_incr = {}
    _kcd_incr_df = cfg.get("KCD_Incremental_Rates", pd.DataFrame())
    if len(_kcd_incr_df) > 0 and "Vintage" in _kcd_incr_df.columns:
        for _, r in _kcd_incr_df.iterrows():
            kcd_incr[str(r["Vintage"])] = (float(r.get("Incr_Threshold", 0)),
                                            float(r.get("Incr_Rate_%", 1.4)) / 100)

    # ── KCD Listing ──────────────────────────────────────────
    _ls_key = ("KCD_Listing_May" if "KCD_Listing_May" in cfg
               else "KCD_Listing_Slabs" if "KCD_Listing_Slabs" in cfg else None)
    _ls_df = cfg.get(_ls_key, pd.DataFrame()) if _ls_key else pd.DataFrame()
    _ls_c1 = ("CMR72_Per_Txn" if "CMR72_Per_Txn" in _ls_df.columns
              else "Slab1_Per_Txn" if "Slab1_Per_Txn" in _ls_df.columns
              else (_ls_df.columns[1] if len(_ls_df.columns) > 1 else None))
    _ls_c2 = ("CMR80_Per_Txn" if "CMR80_Per_Txn" in _ls_df.columns
              else "Slab2_Per_Txn" if "Slab2_Per_Txn" in _ls_df.columns else None)
    kcd_listing_slabs = (
        [(int(r["Target_Pct"]), int(r[_ls_c1]), int(r[_ls_c2]))
         for _, r in _ls_df.iterrows()]
        if (_ls_c1 and _ls_c2 and len(_ls_df) > 0) else []
    )
    kcd_listing_rates = {}
    _lr_df = cfg.get("KCD_Listing_Rates", pd.DataFrame())
    if len(_lr_df) > 0 and "Vintage" in _lr_df.columns:
        for _, r in _lr_df.iterrows():
            kcd_listing_rates[str(r["Vintage"])] = {
                "base_rate":    float(r.get("Base_Client_Rate", 7000)),
                "listing_rate": float(r.get("Listing_Client_Rate", 22000)),
            }

    # ── KCD Catalog ──────────────────────────────────────────
    _cat_key = ("KCD_Catalog_May" if "KCD_Catalog_May" in cfg
                else "KCD_Catalog_Slabs" if "KCD_Catalog_Slabs" in cfg else None)
    _cat_df = cfg.get(_cat_key, pd.DataFrame()) if _cat_key else pd.DataFrame()
    _cat_c1 = ("CMR72_Per_Txn" if "CMR72_Per_Txn" in _cat_df.columns
               else "Slab1_Per_Txn" if "Slab1_Per_Txn" in _cat_df.columns
               else (_cat_df.columns[1] if len(_cat_df.columns) > 1 else None))
    _cat_c2 = ("CMR80_Per_Txn" if "CMR80_Per_Txn" in _cat_df.columns
               else "Slab2_Per_Txn" if "Slab2_Per_Txn" in _cat_df.columns else None)
    kcd_catalog_slabs = (
        [(int(r["Target_Pct"]), int(r[_cat_c1]), int(r[_cat_c2]))
         for _, r in _cat_df.iterrows()]
        if (_cat_c1 and _cat_c2 and len(_cat_df) > 0) else []
    )

    # ── KCD Spot ─────────────────────────────────────────────
    kcd_spot = {}
    _kcd_spot_df = cfg.get("KCD_Spot", pd.DataFrame())
    if len(_kcd_spot_df) > 0 and "Spot_Key" in _kcd_spot_df.columns:
        for _, r in _kcd_spot_df.iterrows():
            kcd_spot[str(r["Spot_Key"])] = {
                "thresh": int(r.get("PCDV_Threshold", 0)),
                "base":   int(r.get("Base_Reward", 0)),
                "per1k":  int(r.get("Per_1K_After", 0)),
            }

    # ── KCD WK-1 Power of Productivity Spot (May 01-09) ──────
    # Per-product-type spot: {product_key: {"l1_annual": N, "l1_myr": N}}
    kcd_wk1_spot = {}
    _wk1_df = cfg.get("KCD_WK1_Spot_May", pd.DataFrame())
    for _, r in _wk1_df.iterrows():
        key = str(r.get("Product_Key", "")).strip().upper()
        if key:
            kcd_wk1_spot[key] = {
                "l1_annual": int(r.get("L1_Annual", 0)),
                "l1_myr":    int(r.get("L1_MYR",    0)),
                "l2_annual": int(r.get("L2_Annual",  0)),
                "l2_myr":    int(r.get("L2_MYR",     0)),
            }

    # ── SAM slab parsing helpers ─────────────────────────────
    def _sam_kcd_slabs(key_may, key_apr, key_mar):
        k = key_may if key_may in cfg else (key_apr if key_apr in cfg else key_mar)
        df = cfg.get(k)
        if df is None or len(df) == 0: return []
        c1 = "Slab1_Per_Txn" if "Slab1_Per_Txn" in df.columns else "CMR72_Per_Txn"
        c2 = "Slab2_Per_Txn" if "Slab2_Per_Txn" in df.columns else "CMR80_Per_Txn"
        t_col = ("PCR_Threshold" if "PCR_Threshold" in df.columns
                 else "PCDV_Threshold" if "PCDV_Threshold" in df.columns
                 else df.columns[0])
        return [(int(r[t_col]), int(r[c1]), int(r[c2])) for _, r in df.iterrows()]
    def _sam_listing_slabs(key_may, key_apr):
        k = key_may if key_may in cfg else key_apr
        df = cfg.get(k)
        if df is None or len(df) == 0: return []
        c1 = "CMR72_Per_Txn" if "CMR72_Per_Txn" in df.columns else "Slab1_Per_Txn"
        c2 = "CMR80_Per_Txn" if "CMR80_Per_Txn" in df.columns else "Slab2_Per_Txn"
        t_col = "Target_Pct" if "Target_Pct" in df.columns else "PCDV_Threshold"
        return [(int(r[t_col]), int(r[c1]), int(r[c2])) for _, r in df.iterrows()]
    _sam_incr_df = cfg.get("KCD_SAM_Incr_Rates", pd.DataFrame())
    _sam_incr = _sam_incr_df.to_dict("records") if len(_sam_incr_df) > 0 else []
    sam_regular_slabs = _sam_kcd_slabs("KCD_SAM_Regular_May", "KCD_SAM_Regular", "KCD_Regular_91_270D")
    sam_roi_slabs     = _sam_kcd_slabs("KCD_SAM_ROI_May",     "KCD_SAM_ROI",     "KCD_Regular_0_90D")
    sam_hvri_slabs    = _sam_kcd_slabs("KCD_SAM_HVRI_May",    "KCD_SAM_HVRI",    "KCD_HVRI")
    sam_nagpur_slabs  = _sam_kcd_slabs("KCD_SAM_Nagpur_May",  "KCD_SAM_Nagpur",  "KCD_Nagpur_Pharma")
    sam_listing_slabs = _sam_listing_slabs("KCD_SAM_Listing_May", "KCD_SAM_Listing")
    sam_catalog_slabs = _sam_listing_slabs("KCD_SAM_Catalog_May", "KCD_SAM_Catalog")


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
        "rm_cmr_slab1":        rm_cmr_slab1,
        "rm_cmr_slab2":        rm_cmr_slab2,
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
        "csd_spot_apr":        csd_spot_apr_rows,   # FNT1/FNT2 rates from April config
        "kcd_spot_apr":        kcd_spot_apr_rows,   # per-key rates from April config
        # PoP
        "prod_to_pop":         prod_to_pop,
        # KCD Regular
        "kcd_270_slabs":       kcd_270_slabs,
        "kcd_91_270_slabs":    kcd_91_270_slabs,
        "kcd_0_90_slabs":      kcd_0_90_slabs,
        "kcd_hvri_slabs":      kcd_hvri_slabs,
        "kcd_nagpur_slabs":    kcd_nagpur_slabs,
        "kcd_incr":            kcd_incr,
        # KCD ROI (lower PCDV thresholds, same per-txn rates as Regular)
        "kcd_roi_270_slabs":   to_kcd_slabs(_kcd_key("KCD_ROI_May", "KCD_ROI_Apr", "KCD_ROI"))
                               if _kcd_key("KCD_ROI_May", "KCD_ROI_Apr", "KCD_ROI") in cfg
                               else kcd_270_slabs,
        "kcd_roi_91_270_slabs": to_kcd_slabs(_kcd_key("KCD_ROI_May", "KCD_ROI_Apr", "KCD_ROI"))
                                if _kcd_key("KCD_ROI_May", "KCD_ROI_Apr", "KCD_ROI") in cfg
                                else kcd_91_270_slabs,
        # KCD Listing/Catalog
        "kcd_listing_slabs":   kcd_listing_slabs,
        "kcd_listing_rates":   kcd_listing_rates,
        "kcd_catalog_slabs":   kcd_catalog_slabs,
        # KCD Spot
        "kcd_wk1_spot":        kcd_wk1_spot,   # May WK-1 per-product spot
        # Config-detection flags (True when the config has April-specific tables)
        "has_apr_spot":        "CSD_Spot_Apr" in cfg,
        "has_may_spot":        "CSD_Spot_May" in cfg,
        "has_mar_spot":        "CSD_Spot" in cfg and "CSD_Spot_Apr" not in cfg and "CSD_Spot_May" not in cfg,
        # KCD SAM (L2) slabs
        "kcd_sam_regular":     sam_regular_slabs,
        "kcd_sam_roi":         sam_roi_slabs,
        "kcd_sam_hvri":        sam_hvri_slabs,
        "kcd_sam_nagpur":      sam_nagpur_slabs,
        "kcd_sam_listing":     sam_listing_slabs,
        "kcd_sam_catalog":     sam_catalog_slabs,
        "kcd_sam_incr":        _sam_incr,
        "kcd_sam_ilp_rates":   [(int(r.get("Target_Achievement_%", 0)),
                                  float(r.get("Incentive_Rate_%", 0))/100
                                  if float(r.get("Incentive_Rate_%", 0)) > 1
                                  else float(r.get("Incentive_Rate_%", 0)))
                                 for r in cfg.get("KCD_SAM_ILP", pd.DataFrame()).to_dict("records")]
                                or [(120, 0.008), (100, 0.0075), (95, 0.0065)],
        # ── All scheme params — derived from Scheme_Params sheet ───────────────
        # CSD
        "new_joiner_cap":      _nj_cap,
        "pop_cmr_floor":       _pop_cmr_floor,
        "pop_use_slab_gate":   _pop_slab_gate,
        "both_achievers_on":   _both_achiev_on,
        "both_achievers_pct":  _both_achiev_pct,
        "cmr_only_pct":        _cmr_only_pct,
        "mdc1_hi_thr":         _mdc1_hi_thr,
        "mdc1_mid_thr":        _mdc1_mid_thr,
        "mdc1_hi_mult":        _mdc1_hi_mult,
        "mdc1_mid_mult":       _mdc1_mid_mult,
        "mdc1_low_mult":       _mdc1_low_mult,
        "boost_tat_thr":       _boost_tat,
        "boost_60d_thr":       _boost_60d,
        "rm_cmr_min":          _rm_cmr_min,
        # KCD
        "kcd_ss_threshold":    _kcd_ss_thr,
        "kcd_slab2_target":    _kcd_cmr_s2,
        "kcd_min_prod_week":   _kcd_min_w,
        "kcd_min_prod_month":  _kcd_min_m,
        "kcd_min_prod_new":    _kcd_min_m_new,
        "kcd_incr_rate":       _kcd_incr_reg,
        "kcd_incr_nagpur":     _kcd_incr_nag,
        "kcd_sam_incr_rate":   _kcd_sam_incr,
        "kcd_sam_nagpur_incr": _kcd_sam_nag_i,
        # IM Insta
        "insta_l1_rate":       _insta_l1,
        "insta_l2_rate":       _insta_l2,
        "insta_min_week":      _insta_min_w,
        "insta_min_month":     _insta_min_m,
        # MCATs
        "mcats_l1_rate":       _mcats_l1,
        "mcats_l2_rate":       _mcats_l2,
        "mcats_min_count":     _mcats_min,
        # IM Star Pro+
        "im_star_rate":        _star_rate,
        "im_star_from_day":    _star_from_day,
        # KCD HC multipliers
        "hc_mult_regular":     _hc_regular,
        "hc_mult_roi":         _hc_roi,
        "hc_mult_hvri":        _hc_hvri,
        "hc_mult_nagpur":      _hc_nagpur,
        "hc_mult_sam":         _hc_sam,
        # BM/RM AOP scheme
        "CSD_BM_AOP_Rate_%":   _csd_bm_rate,
        "CSD_RM_AOP_Rate_%":   _csd_rm_rate,
        "CSD_BM_AOP_Cap_%":    _csd_bm_cap,
        "CSD_RM_AOP_Cap_%":    _csd_rm_cap,
        "KCD_BM_AOP_Rate_%":   _kcd_bm_rate,
        "KCD_RM_AOP_Rate_%":   _kcd_rm_rate,
        "KCD_BM_AOP_Cap_%":    _kcd_bm_cap,
        "KCD_RM_AOP_Cap_%":    _kcd_rm_cap,
        "AOP_Min_Achievement_%": _aop_min,
        "AOP_Mult_95_100_%":   _aop_m1,
        "AOP_Mult_100_105_%":  _aop_m2,
        "AOP_Mult_105_110_%":  _aop_m3,
        "AOP_Mult_110_Plus_%": _aop_m4,
        "CSD_BM_CMR_Min_%":    _csd_bm_cmr_min,
        "CSD_BM_CMR_Slab1_%":  _csd_bm_cmr_s1,
        "CSD_BM_CMR_Slab2_%":  _csd_bm_cmr_s2,
        "KCD_BM_CMR_Min_%":    _kcd_bm_cmr_min,
        "KCD_BM_CMR_Slab1_%":  _kcd_bm_cmr_s1,
        "KCD_BM_CMR_Slab2_%":  _kcd_bm_cmr_s2,
        "KCD_BM_SS_Plus_Min_%":_kcd_bm_ss_min,
    }



def build_april_slab_config():
    """April 2026 incentive slab configuration derived from scheme documents."""
    import pandas as _pd

    # CSD 0-30D and 31-90D -- April slabs
    # PCDV: 1800→3100, 2100→5100, 2400→7000, 2800→10500
    # Incremental: 3% on deal value above PCDV 2800 (threshold = 2800, not 5000)
    # CMR slab targets: 55%/65% (individual, same as March)
    # PoP: same tiers (500/1000/1500); min 2 for 0-30D, min 3 for 31-90D
    # Cap: ₹20,000
    csd_new_apr = _pd.DataFrame([
        {"PCDV_Threshold": 2800, "Payout": 10500},
        {"PCDV_Threshold": 2400, "Payout": 7000},
        {"PCDV_Threshold": 2100, "Payout": 5100},
        {"PCDV_Threshold": 1800, "Payout": 3100},
    ])
    csd_new_params_apr = _pd.DataFrame([
        {"Parameter": "Incremental_Threshold", "Value": 2800},  # PCDV threshold
        {"Parameter": "Incremental_Rate_%",    "Value": 3.0},
        {"Parameter": "Slab2_CMR_Multiplier_%","Value": 120},
        {"Parameter": "Min_Txn_0_30D",         "Value": 2},
        {"Parameter": "Min_Txn_31_90D",        "Value": 3},
        {"Parameter": "Pop_CMR_Floor_%",        "Value": 55},
        {"Parameter": "Max_Incentive",          "Value": 20000},
    ])

    # CSD Spot April -- NR Upsell/AMR based (NOT PCDV bullet like March)
    # FNT-1 (Apr 1-16): ≥3 upsells → ₹1500 base + ₹750/txn after 3
    # FNT-2 (Apr 20-30): ≥3 upsells → ₹2500 base + ₹1000/txn after 3
    # Both require PCDV & CMR targets met
    csd_spot_apr = _pd.DataFrame([
        {"Period": "FNT1", "Min_Prod": 3, "Base_Amount": 1500, "Per_Txn_After": 750},
        {"Period": "FNT2", "Min_Prod": 3, "Base_Amount": 2500, "Per_Txn_After": 1000},
    ])

    # KCD Spot April -- PCDV-based with FNT periods and SS/LS multiplier
    # Structure: {team_vintage_key: {fnt1: (thresh, base, per_unit, unit_size), fnt2: ...}}
    kcd_spot_apr = _pd.DataFrame([
        # Regular/ROI 0-90D
        {"Key": "ROI_0_90",    "FNT1_Thresh": 4000, "FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 4000, "FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 1000},
        # Regular/ROI 90+
        {"Key": "ROI_90p",     "FNT1_Thresh": 6000, "FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 6000, "FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 1000},
        # Catalog 0-90D
        {"Key": "CAT_0_90",    "FNT1_Thresh": 2500, "FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 2500, "FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 1000},
        # Catalog 90+
        {"Key": "CAT_90p",     "FNT1_Thresh": 3500, "FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 3500, "FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 1000},
        # Listing 0-90D
        {"Key": "LIST_0_90",   "FNT1_Thresh": 7500, "FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 7500, "FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 2000},
        # Listing 90+
        {"Key": "LIST_90p",    "FNT1_Thresh": 11000,"FNT1_Base": 2500, "FNT1_Unit": 1000, "FNT1_Size": 1000,
                                "FNT2_Thresh": 11000,"FNT2_Base": 4000, "FNT2_Unit": 1000, "FNT2_Size": 2000},
    ])

    # CSD SPS April base slabs (per-txn, per PCDV tier)
    # 91-270D: 2400→1250/1500, 2600→2000/2400, 2800→2500/3000
    csd_sps_91_270_apr = _pd.DataFrame([
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2400, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])
    # 270D+: 2600→1250/1500, 2800→2000/2400, 3000→2500/3000
    csd_sps_270_apr = _pd.DataFrame([
        {"PCDV_Threshold": 3000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
    ])
    # ROI 91-270D (from Slide 4 in image(7)): same as SPS 91-270D
    csd_roi_91_270_apr = csd_sps_91_270_apr.copy()
    # ROI 270D+ (from Slide 5): same as SPS 270D+
    csd_roi_270_apr = csd_sps_270_apr.copy()

    # KCD April base slabs (PCDV per-txn by vintage, CMR 72%/80%)
    kcd_91_270_apr = _pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    kcd_270_apr = _pd.DataFrame([
        {"PCDV_Threshold": 19000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 16000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 13000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    kcd_roi_apr = _pd.DataFrame([
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold":  8000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    kcd_hvri_apr = _pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 10000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    kcd_nagpur_apr = _pd.DataFrame([
        {"PCDV_Threshold": 32000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 28000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 24000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    # CSD-to-KCD new joined (after Dec'25): same as ROI rates
    kcd_new_0_90_apr = _pd.DataFrame([
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 3000, "Slab2_Per_Txn": 3600},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold":  8000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
    ])
    # KCD incremental rates for April (per-team)
    kcd_incr_apr = _pd.DataFrame([
        {"Team": "Regular_91_270", "Incr_Threshold": 17000, "Incr_Rate_%": 1.40},
        {"Team": "Regular_270",    "Incr_Threshold": 19000, "Incr_Rate_%": 1.40},
        {"Team": "ROI",            "Incr_Threshold": 14000, "Incr_Rate_%": 1.40},
        {"Team": "HVRI",           "Incr_Threshold": 17000, "Incr_Rate_%": 1.40},
        {"Team": "Nagpur",         "Incr_Threshold": 32000, "Incr_Rate_%": 0.85},
        {"Team": "New_KCD",        "Incr_Threshold": 14000, "Incr_Rate_%": 1.40},
    ])

    return {
        "CSD_New_Slabs_Apr":      csd_new_apr,
        "CSD_New_Params_Apr":     csd_new_params_apr,
        "CSD_Spot_Apr":           csd_spot_apr,
        "KCD_Spot_Apr":           kcd_spot_apr,
        "CSD_SPS_91_270_Apr":     csd_sps_91_270_apr,
        "CSD_SPS_270_Apr":        csd_sps_270_apr,
        "KCD_Regular_91_270_Apr": kcd_91_270_apr,
        "KCD_Regular_270_Apr":    kcd_270_apr,
        "KCD_ROI_Apr":            kcd_roi_apr,
        "KCD_HVRI_Apr":           kcd_hvri_apr,
        "KCD_Nagpur_Apr":         kcd_nagpur_apr,
        "KCD_New_0_90_Apr":       kcd_new_0_90_apr,
        "KCD_Incr_Rates_Apr":     kcd_incr_apr,
    }


def build_may_slab_config():
    """May 2026 scheme slabs. All L1/L2 per-txn rates reduced vs April.
    CSD SPS 270D+ thresholds shifted up. Catalog L1 now same as Listing.
    CSD RM slab1/2 targets: 60%/65%. No FNT-2 for CSD. KCD WK-1 is per-product spot."""
    import pandas as pd

    # ── CSD New (0-30D and 31-90D) — SAME as April ──────────────────────────
    csd_new = pd.DataFrame([
        {"PCDV_Threshold": 2800, "Payout": 10500},
        {"PCDV_Threshold": 2400, "Payout": 7000},
        {"PCDV_Threshold": 2100, "Payout": 5100},
        {"PCDV_Threshold": 1800, "Payout": 3100},
    ])
    csd_new_params = pd.DataFrame([
        {"Parameter": "Incremental_Threshold", "Value": 2800},
        {"Parameter": "Incremental_Rate_%",    "Value": 3.0},
        {"Parameter": "Slab2_CMR_Multiplier_%","Value": 120},
        {"Parameter": "Min_Txn_0_30D",         "Value": 2},
        {"Parameter": "Min_Txn_31_90D",         "Value": 3},
    ])

    # ── CSD SPS slabs — May'26 ───────────────────────────────────────────────
    csd_sps_91_270_may = pd.DataFrame([
        {"PCDV_Threshold": 2800, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
        {"PCDV_Threshold": 2400, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
    ])
    csd_sps_270_may = pd.DataFrame([
        {"PCDV_Threshold": 3200, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 3000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
        {"PCDV_Threshold": 2600, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
    ])

    # ── CSD RM slabs — May'26 ────────────────────────────────────────────────
    csd_rm_may = pd.DataFrame([
        {"PCR_Threshold": 2900, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCR_Threshold": 2700, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCR_Threshold": 2500, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    csd_rm_params_may = pd.DataFrame([
        {"Parameter": "CMR_Slab1_Target_%", "Value": 60},
        {"Parameter": "CMR_Slab2_Target_%", "Value": 65},
        {"Parameter": "CMR_Min_Eligible_%",  "Value": 53},
    ])

    # ── CSD FNT-1 spot (May 1-16) — L1 base 2000, RM base 3000; NO FNT-2 ───
    csd_spot_may = pd.DataFrame([
        {"Spot_Type": "L1_FNT1",  "Min_Prod": 3,   "Base_Reward": 2000, "Per_Txn": 750},
        {"Spot_Type": "RM_FNT1",  "Min_Prod": 2.5,  "Base_Reward": 3000, "Per_Txn": 500},
    ])

    # ── KCD L1 slabs — May'26 (all per-txn rates reduced by one tier) ────────
    kcd_91_270_may = pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_270_may = pd.DataFrame([
        {"PCDV_Threshold": 19000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 16000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 13000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_roi_may = pd.DataFrame([
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold":  8000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_hvri_may = pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 10000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_nagpur_may = pd.DataFrame([
        {"PCDV_Threshold": 32000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 28000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold": 24000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_new_0_90_may = pd.DataFrame([  # CSD-to-KCD / new joined after Jan'26
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"PCDV_Threshold":  8000, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])

    # ── KCD Listing/Catalog L1 — May'26 (Catalog now same as Listing) ────────
    kcd_listing_may = pd.DataFrame([
        {"Target_Pct": 140, "Slab1_Per_Txn": 2500, "Slab2_Per_Txn": 3000},
        {"Target_Pct": 120, "Slab1_Per_Txn": 2000, "Slab2_Per_Txn": 2400},
        {"Target_Pct": 100, "Slab1_Per_Txn": 1500, "Slab2_Per_Txn": 1800},
    ])
    kcd_catalog_may = kcd_listing_may.copy()

    # ── KCD SAM slabs — May'26 ───────────────────────────────────────────────
    kcd_sam_regular_may = pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    kcd_sam_roi_may = pd.DataFrame([
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 11000, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCDV_Threshold":  8000, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    kcd_sam_hvri_may = pd.DataFrame([
        {"PCDV_Threshold": 17000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 14000, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCDV_Threshold": 10000, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    kcd_sam_nagpur_may = pd.DataFrame([
        {"PCDV_Threshold": 32000, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"PCDV_Threshold": 28000, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"PCDV_Threshold": 24000, "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    kcd_sam_listing_may = pd.DataFrame([
        {"Target_Pct": 140, "Slab1_Per_Txn": 1250, "Slab2_Per_Txn": 1500},
        {"Target_Pct": 120, "Slab1_Per_Txn": 1000, "Slab2_Per_Txn": 1200},
        {"Target_Pct": 95,  "Slab1_Per_Txn":  750, "Slab2_Per_Txn":  900},
    ])
    kcd_sam_catalog_may = kcd_sam_listing_may.copy()

    # ── KCD WK-1 Power of Productivity Spot (May 01-09) ─────────────────────
    # Per-product-type spot: NR Upsell / Upsell on Ren; min 2 prods in WK-1
    # 50% if monthly base not achieved; SAM = half L1 rates
    kcd_wk1_spot = pd.DataFrame([
        {"Product_Key": "IM_STAR_PRO",    "L1_Annual": 500,  "L1_MYR": 1000, "L2_Annual": 250, "L2_MYR": 500},
        {"Product_Key": "IM_LEADER_PRO",  "L1_Annual": 750,  "L1_MYR": 1500, "L2_Annual": 400, "L2_MYR": 750},
        {"Product_Key": "PREF_SS_PRO",    "L1_Annual": 500,  "L1_MYR": 1000, "L2_Annual": 250, "L2_MYR": 500},
        {"Product_Key": "PREF_LS_PRO",    "L1_Annual": 1000, "L1_MYR": 2000, "L2_Annual": 500, "L2_MYR": 1000},
        {"Product_Key": "VALUE_PLUS",     "L1_Annual": 500,  "L1_MYR": 1000, "L2_Annual": 250, "L2_MYR": 500},
        {"Product_Key": "PL_PLUS",        "L1_Annual": 1500, "L1_MYR": 3000, "L2_Annual": 750, "L2_MYR": 1500},
    ])

    # KCD incremental rates — same as April
    kcd_incr_may = pd.DataFrame([
        {"Team": "Regular_91_270", "Incr_Threshold": 17000, "Incr_Rate_%": 1.40},
        {"Team": "Regular_270",    "Incr_Threshold": 19000, "Incr_Rate_%": 1.40},
        {"Team": "ROI",            "Incr_Threshold": 14000, "Incr_Rate_%": 1.40},
        {"Team": "HVRI",           "Incr_Threshold": 17000, "Incr_Rate_%": 1.40},
        {"Team": "Nagpur",         "Incr_Threshold": 32000, "Incr_Rate_%": 0.85},
        {"Team": "New_KCD",        "Incr_Threshold": 14000, "Incr_Rate_%": 1.40},
        {"Team": "Listing_140pct", "Incr_Threshold": 140,   "Incr_Rate_%": 1.40},
        {"Team": "Catalog_140pct", "Incr_Threshold": 140,   "Incr_Rate_%": 1.40},
    ])

    return {
        "CSD_New_Slabs_May":      csd_new,
        "CSD_New_Params_May":     csd_new_params,
        "CSD_SPS_91_270_May":     csd_sps_91_270_may,
        "CSD_SPS_270_May":        csd_sps_270_may,
        "CSD_RM_May":             csd_rm_may,
        "CSD_RM_Params_May":      csd_rm_params_may,
        "CSD_Spot_May":           csd_spot_may,
        "KCD_Regular_91_270_May": kcd_91_270_may,
        "KCD_Regular_270_May":    kcd_270_may,
        "KCD_ROI_May":            kcd_roi_may,
        "KCD_HVRI_May":           kcd_hvri_may,
        "KCD_Nagpur_May":         kcd_nagpur_may,
        "KCD_New_0_90_May":       kcd_new_0_90_may,
        "KCD_Listing_May":        kcd_listing_may,
        "KCD_Catalog_May":        kcd_catalog_may,
        "KCD_SAM_Regular_May":    kcd_sam_regular_may,
        "KCD_SAM_ROI_May":        kcd_sam_roi_may,
        "KCD_SAM_HVRI_May":       kcd_sam_hvri_may,
        "KCD_SAM_Nagpur_May":     kcd_sam_nagpur_may,
        "KCD_SAM_Listing_May":    kcd_sam_listing_may,
        "KCD_SAM_Catalog_May":    kcd_sam_catalog_may,
        "KCD_WK1_Spot_May":       kcd_wk1_spot,
        "KCD_Incr_Rates_May":     kcd_incr_may,
        "Scheme_Params":          pd.DataFrame([
            # Copy all params from default — user edits values for May
            {"Parameter": "CSD_NewJoiner_Cap",         "Value": 20000, "Description": "Max PCDV+PoP incentive for 0-90D employees (₹)"},
            {"Parameter": "CSD_PoP_Min_CMR_Pct",       "Value": 55.0,  "Description": "Min CMR% to earn PoP (0-90D)"},
            {"Parameter": "CSD_NewJoiner_Incr_Rate_%",  "Value": 3.0,   "Description": "% of incr DV above top PCDV slab (0-90D)"},
            {"Parameter": "CSD_PoP_Min_Txn_0_30D",     "Value": 2,     "Description": "Min productivity count to qualify PoP (0-30D)"},
            {"Parameter": "CSD_PoP_Min_Txn_31_90D",    "Value": 3,     "Description": "Min productivity count to qualify PoP (31-90D)"},
            # May'26: PoP gate = CMR Slab1 achieved; Both Achievers multiplier ON
            {"Parameter": "CSD_PoP_Use_Slab_Gate",     "Value": 1,     "Description": "PoP CMR gate: 1=Slab1 target must be achieved (May scheme)"},
            {"Parameter": "CSD_BothAchievers_On",      "Value": 1,     "Description": "Both Achievers PoP mult ON for May: PCDV+CMR=125%, CMR-only=50%"},
            {"Parameter": "CSD_BothAchievers_Pct",     "Value": 125,   "Description": "Both Achievers full payout % (PCDV slab + CMR Slab1 both achieved)"},
            {"Parameter": "CSD_OnlyCMR_Achiever_Pct",  "Value": 50,    "Description": "Only CMR Achiever payout % (CMR Slab1 hit, PCDV slab not hit)"},
            {"Parameter": "CSD_MDC1_Mid_Threshold_%",   "Value": 25,   "Description": "MDC-1 CMR% between Mid and High → Mid_Mult; below → Low_Mult"},
            {"Parameter": "CSD_MDC1_High_Mult_%",       "Value": 120,  "Description": "MDC-1 multiplier (%) when above High threshold"},
            {"Parameter": "CSD_MDC1_Mid_Mult_%",        "Value": 100,  "Description": "MDC-1 multiplier (%) when between thresholds"},
            {"Parameter": "CSD_MDC1_Low_Mult_%",        "Value": 50,   "Description": "MDC-1 multiplier (%) when below Mid threshold"},
            {"Parameter": "CSD_Booster_TAT_Below",      "Value": 1,    "Description": "SPS Booster: Ext Ticket TAT must be below this"},
            {"Parameter": "CSD_Booster_60D_Below_%",    "Value": 10,   "Description": "SPS Booster: 60D Not Met must be below this %"},
            {"Parameter": "CSD_Booster_Mult_%",         "Value": 120,  "Description": "SPS Booster multiplier when both criteria met (%)"},
            {"Parameter": "CSD_RM_CMR_Min_%",           "Value": 53,   "Description": "CSD RM min CMR% to be eligible"},
            {"Parameter": "CSD_RM_CMR_Slab1_%",         "Value": 60,   "Description": "CSD RM Slab1 CMR threshold (100% payout)"},
            {"Parameter": "CSD_RM_CMR_Slab2_%",         "Value": 65,   "Description": "CSD RM Slab2 CMR threshold (120% payout)"},
            {"Parameter": "KCD_SS_Plus_Threshold_%",    "Value": 72,   "Description": "KCD SS+ gate: ≥ this CMR% → 100%, else 50%"},
            {"Parameter": "KCD_CMR_Slab2_%",            "Value": 80,   "Description": "KCD higher CMR slab for top per-txn rate"},
            {"Parameter": "KCD_Min_Prod_Week",          "Value": 2,    "Description": "Min weekly productivity to unlock base incentive"},
            {"Parameter": "KCD_Min_Prod_Month",         "Value": 8,    "Description": "Min monthly productivity (established)"},
            {"Parameter": "KCD_Min_Prod_Month_New",     "Value": 6,    "Description": "Min monthly productivity (new / CSD-to-KCD)"},
            {"Parameter": "KCD_Incr_Rate_Regular_%",    "Value": 1.4,  "Description": "KCD incremental % (Regular/ROI/HVRI/Listing)"},
            {"Parameter": "KCD_Incr_Rate_Nagpur_%",     "Value": 0.85, "Description": "KCD Nagpur L1 incremental % above 32K"},
            {"Parameter": "KCD_SAM_Incr_Rate_%",        "Value": 0.65, "Description": "KCD SAM incremental %"},
            {"Parameter": "KCD_SAM_Nagpur_Incr_%",      "Value": 0.45, "Description": "KCD SAM Nagpur incremental %"},
            {"Parameter": "IM_Insta_L1_Rate",           "Value": 300,  "Description": "IM Insta spot per qualifying sale (L1, ₹)"},
            {"Parameter": "IM_Insta_L2_Rate",           "Value": 150,  "Description": "IM Insta spot per qualifying sale (L2, ₹)"},
            {"Parameter": "IM_Insta_Min_Week",          "Value": 2,    "Description": "Min IM Insta prods in a week to qualify"},
            {"Parameter": "IM_Insta_Min_Month",         "Value": 7,    "Description": "Min IM Insta prods in month to qualify"},
            {"Parameter": "MCATs_L1_Rate",              "Value": 1000, "Description": "MCATs spot per MCAT from 3rd onwards (L1, ₹)"},
            {"Parameter": "MCATs_L2_Rate",              "Value": 500,  "Description": "MCATs spot per MCAT from 3rd onwards (L2, ₹)"},
            {"Parameter": "MCATs_Min_Count",            "Value": 2,    "Description": "MCATs count before spot starts"},
            {"Parameter": "IM_Star_Pro_Spot_Rate",      "Value": 1000, "Description": "IM Star Pro+/Pref spot per new sale (₹)"},
            {"Parameter": "IM_Star_Pro_From_Day",       "Value": 28,   "Description": "Day-of-month from which IM Star Pro+ spot is active"},
            # Excellent Incentive Spot
            {"Parameter": "Excellent_Spot_L1_Rate",    "Value": 750,  "Description": "Excellent Spot Rs/txn L1 (90+ vintage)"},
            {"Parameter": "Excellent_Spot_L2_Rate",    "Value": 400,  "Description": "Excellent Spot Rs/txn L2 from 2nd txn"},
            {"Parameter": "Excellent_Spot_Day",        "Value": 4,    "Description": "Day-of-month Excellent Spot applies"},
            {"Parameter": "KCD_HC_Mult_Regular",        "Value": 21000,"Description": "HC = Client-A × this (Regular/Listing/Catalog L1)"},
            {"Parameter": "KCD_HC_Mult_ROI",            "Value": 14000,"Description": "HC multiplier for ROI L1"},
            {"Parameter": "KCD_HC_Mult_HVRI",           "Value": 17000,"Description": "HC multiplier for HVRI L1"},
            {"Parameter": "KCD_HC_Mult_Nagpur",         "Value": 32000,"Description": "HC multiplier for Nagpur L1"},
            {"Parameter": "KCD_HC_Mult_SAM",            "Value": 17000,"Description": "HC multiplier for SAM / L2 (all teams)"},
            # ─ BM / RM AOP Scheme (L3 = BM, L4 = RM) ────────────────────────────
            {"Parameter": "CSD_BM_AOP_Rate_%",          "Value": 1.00,  "Description": "CSD BM (L3) base rate: % of Net Deal Value"},
            {"Parameter": "CSD_RM_AOP_Rate_%",          "Value": 0.70,  "Description": "CSD RM (L4) base rate: % of Net Deal Value"},
            {"Parameter": "CSD_BM_AOP_Cap_%",           "Value": 5.00,  "Description": "CSD BM max payout as % of Deal Value"},
            {"Parameter": "CSD_RM_AOP_Cap_%",           "Value": 4.00,  "Description": "CSD RM max payout as % of Deal Value"},
            {"Parameter": "KCD_BM_AOP_Rate_%",          "Value": 0.50,  "Description": "KCD BM (L3) base rate: % of Net Deal Value"},
            {"Parameter": "KCD_RM_AOP_Rate_%",          "Value": 0.35,  "Description": "KCD RM (L4) base rate: % of Net Deal Value"},
            {"Parameter": "KCD_BM_AOP_Cap_%",           "Value": 2.00,  "Description": "KCD BM/RM max payout as % of Deal Value"},
            {"Parameter": "KCD_RM_AOP_Cap_%",           "Value": 2.00,  "Description": "KCD RM max payout as % of Deal Value"},
            {"Parameter": "AOP_Min_Achievement_%",       "Value": 95,    "Description": "Minimum AOP achievement % to be eligible"},
            {"Parameter": "AOP_Mult_95_100_%",           "Value": 100,   "Description": "AOP multiplier % for 95-100% achievement"},
            {"Parameter": "AOP_Mult_100_105_%",          "Value": 110,   "Description": "AOP multiplier % for 100-105% achievement"},
            {"Parameter": "AOP_Mult_105_110_%",          "Value": 120,   "Description": "AOP multiplier % for 105-110% achievement"},
            {"Parameter": "AOP_Mult_110_Plus_%",         "Value": 130,   "Description": "AOP multiplier % for 110%+ achievement"},
            {"Parameter": "CSD_BM_CMR_Min_%",           "Value": 53,    "Description": "CSD BM/RM min CMR% to be eligible"},
            {"Parameter": "CSD_BM_CMR_Slab1_%",         "Value": 60,    "Description": "CSD BM/RM CMR Slab1: 50% payout (53-60%)"},
            {"Parameter": "CSD_BM_CMR_Slab2_%",         "Value": 65,    "Description": "CSD BM/RM CMR Slab2: 100% (60-65%), 120% above"},
            {"Parameter": "KCD_BM_CMR_Min_%",           "Value": 72,    "Description": "KCD BM/RM min CMR% to be eligible"},
            {"Parameter": "KCD_BM_CMR_Slab1_%",         "Value": 75,    "Description": "KCD BM/RM CMR: 75% payout (72-75%)"},
            {"Parameter": "KCD_BM_CMR_Slab2_%",         "Value": 80,    "Description": "KCD BM/RM CMR: 100% (75-80%), 120% above"},
            {"Parameter": "KCD_BM_SS_Plus_Min_%",        "Value": 72,    "Description": "KCD BM/RM SS+ gate: ≥ this → 100%, else 50%"},
        ]),
    }
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
        {"Target_Pct": 140, "CMR72_Per_Txn": 3000, "CMR80_Per_Txn": 3600},
        {"Target_Pct": 120, "CMR72_Per_Txn": 2500, "CMR80_Per_Txn": 3000},
        {"Target_Pct": 100, "CMR72_Per_Txn": 2000, "CMR80_Per_Txn": 2400},
        {"Target_Pct": 95,  "CMR72_Per_Txn": 1750, "CMR80_Per_Txn": 2000},
    ])
    # KCD Collection Target rates: Base_Client_Rate * base_clients + Listing_Client_Rate * list_clients
    # April PPT: Listing/Catalog 270D+/91-270D = 7K base + 22K listing
    #            CSD-to-KCD new joiners = 5K base + 15K listing
    # March FSF: 8500 + 48000 (different -- configurable via slab config)
    kcd_listing_rates = pd.DataFrame([
        {"Vintage": "270D+",   "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage": "91-270D", "Base_Client_Rate": 7000, "Listing_Client_Rate": 22000},
        {"Vintage": "31-90D",  "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
        {"Vintage": "0-30D",   "Base_Client_Rate": 5000, "Listing_Client_Rate": 15000},
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
    """Generate the downloadable Slab_Config.xlsx template. Cached -- only built once."""
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
            ws.write(0, 0, f"NOTE -- Sheet: {sheet_name} | Edit values in rows below. Do NOT rename columns.", note_fmt)
            ws.set_row(0, 18)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def make_may_slab_config_excel():
    """Generate the downloadable May 2026 Slab_Config.xlsx with May-specific sheets."""
    may_cfg = build_may_slab_config()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        hdr_fmt  = w.book.add_format({"bold": True, "bg_color": "#375623", "font_color": "#FFFFFF", "border": 1})
        note_fmt = w.book.add_format({"italic": True, "font_color": "#595959"})
        for sheet_name, df in may_cfg.items():
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws = w.sheets[sheet_name]
            ws.set_column(0, len(df.columns) - 1, 22)
            for col_num, col_name in enumerate(df.columns):
                ws.write(1, col_num, col_name, hdr_fmt)
            ws.write(0, 0, f"May'26 Scheme | {sheet_name} | Do NOT rename columns.", note_fmt)
            ws.set_row(0, 18)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def make_april_slab_config_excel():
    """Generate the downloadable April 2026 Slab_Config.xlsx with April-specific sheets."""
    march_base = build_default_slab_config()
    april_ext  = build_april_slab_config()
    combined   = {**march_base, **april_ext}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        hdr_fmt  = w.book.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF", "border": 1})
        note_fmt = w.book.add_format({"italic": True, "font_color": "#595959"})
        for sheet_name, df in combined.items():
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws = w.sheets[sheet_name]
            ws.set_column(0, len(df.columns) - 1, 22)
            for col_num, col_name in enumerate(df.columns):
                ws.write(1, col_num, col_name, hdr_fmt)
            ws.write(0, 0, f"APRIL 2026 -- {sheet_name} | Edit values below, do NOT rename columns.", note_fmt)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def make_march_slab_config_excel():
    """Generate the downloadable March 2026 Slab_Config.xlsx. Cached -- only built once."""
    defaults = build_default_slab_config()
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
            ws.write(0, 0, f"MARCH 2026 (PCR) -- {sheet_name} | Edit values below, do NOT rename columns.", note_fmt)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# CMR AUTO-CALCULATION
# ═══════════════════════════════════════════════════════════════

def find_col(df, candidates):
    """Return the first column name from candidates that exists in df, or None.
    Normalises column names: lower-case, collapse whitespace/newlines to single space."""
    def norm(s): return ' '.join(str(s).lower().split())
    normalised = {norm(c): c for c in df.columns}
    for cand in candidates:
        nc = norm(cand)
        if nc in normalised:
            return normalised[nc]
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
    Handles both proper datetime columns AND Excel serial number columns (float/int).
    selected_month format: 'Mar-26'
    """
    target = pd.to_datetime(selected_month, format="%b-%y")
    target_month = target.month
    target_year  = target.year

    def _to_datetime_robust(series):
        """
        Convert a series to datetime, handling:
          1. Already proper datetime/timestamp
          2. Excel serial numbers (float like 46082.0) → 1899-12-30 + N days
          3. String dates
        Returns a datetime Series.
        """
        # Try standard parse first
        parsed = pd.to_datetime(series, errors="coerce")
        # Check if result looks like epoch (1970) -- sign of float serial misparse
        epoch_count = (parsed.dt.year == 1970).sum() if parsed.notna().any() else 0
        valid_count = parsed.notna().sum()
        if epoch_count > valid_count * 0.5:
            # More than half parsed as 1970 → these are Excel serials
            nums = pd.to_numeric(series, errors="coerce")
            excel_base = pd.Timestamp("1899-12-30")
            parsed = nums.apply(
                lambda x: excel_base + pd.Timedelta(days=int(x))
                if pd.notna(x) and x > 0 else pd.NaT
            )
        return parsed

    # ── Receipt: filter by Entry Date (fallback: Receipt Date) ───────────────
    r = receipt_df.copy()
    date_col = find_col(r, ["Entry Date", "Clear Date", "Receipt Date"])
    if date_col:
        r_dates = _to_datetime_robust(r[date_col])
        r = r[(r_dates.dt.month == target_month) & (r_dates.dt.year == target_year)]

    # ── Refund: filter by Clear Date ─────────────────────────────────────────
    ref = refund_df.copy()
    ref_date = find_col(ref, ["Clear Date", "Month"])
    if ref_date:
        ref_dates = _to_datetime_robust(ref[ref_date])
        ref = ref[(ref_dates.dt.month == target_month) & (ref_dates.dt.year == target_year)]

    # ── Renewal: filter by Month column ──────────────────────────────────────
    rnl = renewal_df.copy() if renewal_df is not None else None
    if rnl is not None:
        rnl_m = find_col(rnl, ["Month", "MONTH"])
        if rnl_m:
            def _match(val):
                s = str(val).strip()
                for fmt in ("%b'%y", "%b-%y", "%b/%y", "%B'%y", "%B-%y"):
                    try:
                        parsed = pd.to_datetime(s, format=fmt, errors="coerce")
                        if pd.notna(parsed):
                            return parsed.month == target_month and parsed.year == target_year
                    except Exception:
                        pass
                return False
            n_before = len(rnl)
            rnl = rnl[rnl[rnl_m].apply(_match)]
            n_after = len(rnl)
            # Store count in a module-level var for debugging
            import builtins
            builtins._renewal_filter_debug = (n_before, n_after, selected_month)

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

    # Step 4: Productivity -- cast to bool first (Arrow-backed pandas fix)
    is_upsell        = df["_is_upsell"].astype(bool)
    is_pure_renewal  = df["_is_pure_renewal"].astype(bool)
    has_upsell       = df["_has_upsell_on_receipt"].astype(bool)

    # Rnl Remarks = "Retention" → NOT productive (these are retention renewals, not new upsells)
    _rnl_rem_col = find_col(df, ["Rnl Remarks", "RnlRemarks", "Renewal Remarks", "Rnl_Remarks"])
    _is_retention = pd.Series(False, index=df.index)
    if _rnl_rem_col:
        _is_retention = df[_rnl_rem_col].astype(str).str.strip().str.lower() == "retention"

    df["Productivity"] = (
        (is_upsell | (is_pure_renewal & ~has_upsell)) & ~_is_retention
    ).astype(int)

    # ── NR Upsell/AMR column ──────────────────────────────────────────────
    # "Yes" when: Rem col = "Upsell-NR" OR Rnl Remarks = CMR/CMR+1/CMR+2/CMR+3
    if "NR Upsell/AMR" not in df.columns:
        _rem_col2 = find_col(df, ["Rem", "Remarks", "REM", "REMARKS"])
        _rnl_rem2 = find_col(df, ["Rnl Remarks", "RnlRemarks", "Renewal Remarks", "Rnl_Remarks"])
        _cmr_vals = {"CMR", "CMR+1", "CMR+2", "CMR+3"}
        def _nr_upsell_amr(row):
            rem_val = str(row[_rem_col2]).strip().upper() if _rem_col2 else ""
            rnl_val = str(row[_rnl_rem2]).strip().upper() if _rnl_rem2 else ""
            if rem_val == "UPSELL-NR":
                return "Yes"
            if rnl_val in {v.upper() for v in _cmr_vals}:
                return "Yes"
            return "No"
        df["NR Upsell/AMR"] = df.apply(_nr_upsell_amr, axis=1)

    # Step 5: Service tier
    def _tier(row):
        if row["Productivity"] != 1:
            prod = _str(row[prod_col]) if prod_col else ""
            if prod in INSTA_PRODUCTS:
                return 0.5   # Insta = 0.5 productivity
            return 0

        upsell = _str(row[upsell_col]) if upsell_col else ""
        prod   = _str(row[prod_col])   if prod_col   else ""

        # If upsell col is a boolean flag ("Yes"/"No") from pre-enriched file,
        # it carries no tier info — fall through to product-based lookup.
        _upsell_is_flag = upsell.strip().lower() in ("yes", "no", "1", "true")
        if upsell and not _upsell_is_flag:
            if upsell in UPSELL_TIER1:  return 1
            if upsell in UPSELL_TIER2:  return 2
            if upsell in UPSELL_TIER3:  return 3
            if "MYR" in upsell.upper(): return 2
            return 3   # unknown upsell product name → T3
        # Use product column for tier (covers pure renewals + boolean-flag upsell rows)
        if prod in PROD_TIER1: return 1
        if prod in PROD_TIER2: return 2
        if prod in PROD_TIER3: return 3
        return 0

    df["Service_Tier"] = df.apply(_tier, axis=1)

    # ── April-specific enrichment columns ─────────────────────────────────
        # FNT / WK: derive from Entry Date using configurable date ranges
    # If period_dates set in session_state, use those; else fall back to day-based defaults
    date_col_fnt = find_col(df, ["Entry Date", "Receipt Date", "Date"])
    if date_col_fnt:
        _pd = {}
        try:
            import streamlit as _st2
            _pd = _st2.session_state.get("period_dates", {})
        except: pass
        import datetime as _dtt

        def _assign_period(v, col_name):
            """Assign FNT-1/FNT-2/WK-1..WK-4 based on configurable date ranges."""
            try:
                dt = pd.to_datetime(v, errors='coerce')
                if pd.isna(dt):
                    dt = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(float(str(v))))
                d = dt.date()
                if col_name in _pd:
                    s, e = _pd[col_name]
                    return col_name if s <= d <= e else ""
                # Fallback day-based defaults
                if col_name == "FNT-1": return "FNT-1" if dt.day <= 16 else ""
                if col_name == "FNT-2": return "FNT-2" if dt.day >= 17 else ""
                if col_name == "WK-1":  return "WK-1"  if 1  <= dt.day <= 9  else ""
                if col_name == "WK-2":  return "WK-2"  if 10 <= dt.day <= 16 else ""
                if col_name == "WK-3":  return "WK-3"  if 17 <= dt.day <= 23 else ""
                if col_name == "WK-4":  return "WK-4"  if dt.day >= 24       else ""
                return ""
            except: return ""

        for _pname in ["FNT-1","FNT-2","WK-1","WK-2","WK-3","WK-4"]:
            _col_label = _pname.replace("-","_")  # internal col name
            if _pname not in df.columns and "FNT" not in _pname.split("-")[0] or True:
                pass  # assign below

        # Assign combined FNT column (each row gets one label or "")
        if "FNT" not in df.columns:
            def _fnt(v):
                try:
                    dt = pd.to_datetime(v, errors='coerce')
                    if pd.isna(dt):
                        dt = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(float(str(v))))
                    d = dt.date()
                    for pname in ["FNT-1","FNT-2"]:
                        if pname in _pd:
                            s, e = _pd[pname]
                            if s <= d <= e: return pname
                    # Fallback
                    if dt.day <= 16: return "FNT-1"
                    return "FNT-2"
                except: return ""
            df["FNT"] = df[date_col_fnt].apply(_fnt)

        # Assign WK-1..WK-4 columns
        for _wk, _day_range in [("WK-1",(1,9)),("WK-2",(10,16)),("WK-3",(17,23)),("WK-4",(24,31))]:
            if _wk not in df.columns:
                def _make_wk(v, wk=_wk, dr=_day_range):
                    try:
                        dt = pd.to_datetime(v, errors='coerce')
                        if pd.isna(dt):
                            dt = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(float(str(v))))
                        d = dt.date()
                        if wk in _pd:
                            s, e = _pd[wk]
                            return wk if s <= d <= e else ""
                        return wk if dr[0] <= dt.day <= dr[1] else ""
                    except: return ""
                df[_wk] = df[date_col_fnt].apply(_make_wk)

    # AMR: MYR Remarks column (non-blank = AMR/MYR row)
    if "AMR" not in df.columns:
        myr_col = find_col(df, ["MYR Remarks", "MYR_Remarks"])
        if myr_col:
            df["AMR"] = df[myr_col].fillna("").astype(str).str.strip().apply(
                lambda x: "Yes" if x not in ("", "nan") else "No")
        else:
            df["AMR"] = "No"

    # Pref SS+: Unique/Upsell col contains Star/Leader/Pref products
    if "Pref SS+" not in df.columns:
        upsell_c = find_col(df, ["Unique", "Upsell", "UNIQUE"])
        if upsell_c:
            _ss_kw = {"STAR", "LEADER", "PREF"}
            df["Pref SS+"] = df[upsell_c].fillna("").astype(str).str.upper().apply(
                lambda x: "Yes" if any(k in x for k in _ss_kw) else "No")
        else:
            df["Pref SS+"] = "No"

    # Base to List Sale: Prod/Upsell contains Listing-style products
    if "Base to List Sale" not in df.columns:
        prod_c2 = find_col(df, ["Prod", "Product"])
        if prod_c2:
            _btl_kw = {"MAXIMIS", "MAXI", "TS PRO", "TS1", "TS2", "TS3", "LISTING"}
            df["Base to List Sale"] = df[prod_c2].fillna("").astype(str).str.upper().apply(
                lambda x: "Yes" if any(k in x for k in _btl_kw) else "No")
        else:
            df["Base to List Sale"] = "No"

    # IM Varient: Unique col contains IM Star/Leader/Pref Star
    if "IM Varient" not in df.columns:
        upsell_c2 = find_col(df, ["Unique", "Upsell", "UNIQUE"])
        if upsell_c2:
            _im_kw = {"IM STAR", "IM LEADER", "PREF STAR", "PREF LEADER", "PREFERRED STAR", "PREFERRED LEADER"}
            df["IM Varient"] = df[upsell_c2].fillna("").astype(str).str.upper().apply(
                lambda x: "Yes" if any(k in x for k in _im_kw) else "No")
        else:
            df["IM Varient"] = "No"

    # Deal Val (WOT): alias for Deal Val (WT) when WOT not present
    if "Deal Val (WOT)" not in df.columns:
        dwt_col = find_col(df, ["Deal Val (WT)", "Deal Value", "Deal Val"])
        if dwt_col:
            df["Deal Val (WOT)"] = pd.to_numeric(df[dwt_col], errors='coerce').fillna(0)

    # Cleanup helper cols
    df.drop(columns=["_is_upsell","_is_pure_renewal","_has_upsell_on_receipt"],
            inplace=True, errors="ignore")
    return df


def calc_all_cmr_per_employee(renewal_df, emp_col_override=None):
    """
    Calculate CMR% per employee from ALL renewal rows for a given month.
    Sir's FSF Exec-CSD formula (columns AU/AV/AW):
      Sent     = COUNTIFS(Renewal.EmpID, Renewal.Month=sel_month)       -- ALL renewals
      Received = COUNTIFS(Renewal.EmpID, Renewal.Month=sel_month, Status="Received")
      CMR%     = Received / Sent
    No product filter applied.
    emp_col_override: group by this column instead of EMP ID (used for CSD L2 name lookup).
    Returns dict: { key_val: {"cmr_sent", "cmr_recd", "cmr_pct"} }
    """
    if renewal_df is None or len(renewal_df) == 0:
        return {}
    emp_col    = emp_col_override or find_col(renewal_df, ["EMP ID", "Emp ID", "EmpID", "Employee ID"])
    status_col = find_col(renewal_df, ["Status", "STATUS"])
    if not emp_col:
        return {}
    df = renewal_df.copy()
    df[emp_col] = df[emp_col].astype(str).str.split('.').str[0].str.strip()
    if status_col:
        df["_recv"] = df[status_col].astype(str).str.upper().str.contains("RECEIVED", na=False)
    else:
        df["_recv"] = False
    result = {}
    for emp_id, grp in df.groupby(emp_col):
        eid = str(emp_id).split('.')[0].strip()
        sent = len(grp)
        recd = int(grp["_recv"].sum())
        result[eid] = {"cmr_sent": sent, "cmr_recd": recd,
                       "cmr_pct": round(recd / sent * 100, 2) if sent > 0 else 0.0}
    return result


def calc_mdc1_cmr_per_employee(renewal_df, mdc_client_counts=None, emp_col_override=None,
                               month_offset=0, sel_month_str=None):
    """
    MDC-1 CMR% and CMR+1% per employee.

    Sir's exact formula (April FSF):
      MDC-1 Sent     = COUNTIFS(Renewal.EmpID, EmpID, Renewal.Month, "Apr'26")
                       → ALL current-month renewals, no extra filter.
      CMR+1 Sent     = COUNTIFS(Renewal.EmpID, EmpID, Renewal.Month, "May'26",
                                 Renewal."Remarks(New)", "MDC-1")
                       → NEXT month's renewals tagged "MDC-1".

    Parameters:
      month_offset=0  → MDC-1 CMR%:  count ALL rows in sel_month (current month filter only)
      month_offset=1  → CMR+1%:      next month's rows tagged "MDC-1" (Month = next month AND
                                      Remarks(New)="MDC-1"; fallback: Inv Due Date = month+2)

    Returns dict: { emp_id_str: {"mdc1_sent", "mdc1_recd", "mdc1_cmr_pct"} }
    """
    if renewal_df is None:
        return {}

    emp_col    = emp_col_override or find_col(renewal_df, ["EMP ID","Emp ID","EmpID","Employee ID"])
    status_col = find_col(renewal_df, ["Status.1","Status","STATUS"])
    month_col  = find_col(renewal_df, ["Month","month"])
    remarks_col= find_col(renewal_df, ["Remarks (New)","Remarks(New)","Remarks_New","AS"])

    if not emp_col:
        return {}

    # Month name mapping
    _MO = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
           "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    _MO_REV = {v:k for k,v in _MO.items()}

    def _month_num(s):
        return _MO.get(str(s).strip()[:3], None)

    cur_mo = _month_num(sel_month_str) if sel_month_str else None

    df = renewal_df.copy()
    df[emp_col] = df[emp_col].astype(str).str.split('.').str[0].str.strip()

    # ── Filter rows ───────────────────────────────────────────────────────────
    if month_offset == 0:
        # MDC-1 CMR%: ALL rows in the current month
        if cur_mo and month_col and month_col in df.columns:
            _cur_tag = f"{_MO_REV.get(cur_mo,'')}'26"
            _cur_tag2 = f"{_MO_REV.get(cur_mo,'')}'2026"
            df_filtered = df[df[month_col].astype(str).str.upper().str[:3] ==
                             _MO_REV.get(cur_mo,'').upper()].copy()
            if len(df_filtered) == 0:  # try full month name
                df_filtered = df.copy()  # fallback: all rows
        else:
            df_filtered = df.copy()   # no month filter: use all rows
    else:
        # CMR+1%: NEXT month's data tagged "MDC-1"
        # target = current month + month_offset
        if cur_mo:
            next_mo = (cur_mo % 12) + 1
            _next_abbr = _MO_REV.get(next_mo,'')
            if month_col and month_col in df.columns:
                df_next = df[df[month_col].astype(str).str.upper().str[:3] ==
                              _next_abbr.upper()].copy()
            else:
                df_next = pd.DataFrame()

            if remarks_col and remarks_col in df_next.columns and len(df_next) > 0:
                df_filtered = df_next[df_next[remarks_col].astype(str).str.strip().str.upper()
                                      == "MDC-1"].copy()
            elif len(df_next) > 0:
                # Next month rows exist but no MDC-1 tag → use all next-month rows
                df_filtered = df_next.copy()
            else:
                # No next-month data: fall back to Inv Due Date = month+2 in current data
                due_col = find_col(renewal_df, ["Inv Due Date","InvDueDate","Due Date"])
                if due_col and due_col in df.columns:
                    _due_dates = pd.to_datetime(df[due_col], errors='coerce')
                    _target_mo = ((cur_mo) % 12) + 1   # month+1 (one ahead of next month)
                    df_filtered = df[_due_dates.dt.month == _target_mo].copy()
                else:
                    return {}  # no data available for CMR+1
        else:
            return {}

    if len(df_filtered) == 0:
        return {}

    # ── Received flag ─────────────────────────────────────────────────────────
    recv_col = status_col
    if recv_col and recv_col in df_filtered.columns:
        df_filtered["_recv"] = (df_filtered[recv_col].astype(str).str.upper()
                                .str.contains("RECEIVED", na=False))
    else:
        df_filtered["_recv"] = False

    # ── Aggregate per employee ────────────────────────────────────────────────
    result = {}
    for emp_id, grp in df_filtered.groupby(emp_col):
        eid_str = str(emp_id).split('.')[0].strip()
        sent = len(grp)
        recd = int(grp["_recv"].sum())
        pct  = round(recd / sent * 100, 2) if sent > 0 else 0.0
        result[eid_str] = {"mdc1_sent": sent, "mdc1_recd": recd, "mdc1_cmr_pct": pct}

    return result


def load_structure_dump(uploaded_file):
    """
    Load the Employee Structure Dump file.
    Derives Vintage, Team, Client Count, Joining Date from it automatically.
    Returns a dict keyed by Employee ID string.
    Only CSD and KCD employees are loaded.
    Automatically reads the FSF_TA sheet if present in multi-sheet Excel files.
    """
    if uploaded_file is None:
        return {}

    # Prefer FSF_TA sheet if available (multi-sheet HRMS-style exports)
    df = None
    try:
        _xl = pd.ExcelFile(uploaded_file)
        _sheets_norm = [s.strip().upper() for s in _xl.sheet_names]
        if "FSF_TA" in _sheets_norm:
            _target_sheet = _xl.sheet_names[_sheets_norm.index("FSF_TA")]
            df = pd.read_excel(uploaded_file, sheet_name=_target_sheet)
        uploaded_file.seek(0)
    except Exception:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    if df is None:
        df = _read_file(uploaded_file)
    df.columns = df.columns.str.strip()

    # Normalise column names to lowercase for flexible matching
    df.columns = [str(c).strip() for c in df.columns]

    emp_col     = find_col(df, ["Employee ID", "Emp ID", "EmpID", "employeeid"])
    name_col    = find_col(df, ["Employee Name", "Name", "employeename"])
    vertical_col= find_col(df, ["IIL Vertical Name", "Vertical", "IIL Vertical",
                                "emp_vertical_name", "emp_fun_area_name"])
    location_col= find_col(df, ["Location", "LOCATION", "emp_loc"])
    joining_col = find_col(df, ["Move/Join Date", "Move Join Date",
                                "Joining Date", "DOJ", "Date of Joining",
                                "emp_joining_date"])
    # "New Location/ROI Location" / "Textile Group & CSD KCD & NSD to CSD" carry the vintage
    # string (270D+, 91-270D, 31-90D, 0-30D) in the employee_structure.xlsx format
    final_grp   = find_col(df, ["Vintage", "Final Group", "FinalGroup", "bucket",
                                "Textile Group & CSD KCD & NSD to CSD",
                                "New Location/ROI Location"])
    # "L2 Promoted 0-90D" carries the sub-bucket label (SPS, 90+ Days, CSD ROI, 0-90 Days …)
    # -- this is the key column for SPS booster detection
    vintage_bkt = find_col(df, ["Vintage Bucket",
            "Scheme Type", "VintageBucket",
                                "L2 Promoted 0-90D", "Remarks", "bucket", "emp_level"])
    remarks_col = find_col(df, ["Rem", "Remarks", "Group", "Team", "rem", "group", "team",
                                "KCD Group", "Employee Group", "Product Group"])
    client_a    = find_col(df, ["Client-A", "Client A", "ClientA",
                                "Actual Client", "Total Client"])
    client_c    = find_col(df, ["Client-C", "Client C", "ClientC",
                                "Calculated Client", "Total Client"])
    # Listing/Catalog client counts (for KCD)
    list_c_col  = find_col(df, ["Listing Client", "Listing\nClient", "ListingClient",
                                "Listing Clients", "listing", "Listing", "L_Client",
                                "Listing C", "Pref Star Client", "Preferred Star Client",
                                "list_client", "listing_client"])
    cat_c_col   = find_col(df, ["Catalog Client", "Catalog\nClient", "CatalogClient",
                                "Catalog Clients", "catalog", "Catalog", "C_Client",
                                "Catalog C", "Base Client", "BaseClient",
                                "cat_client", "catalog_client"])
    l2_col      = find_col(df, ["L2 Name", "L2Name", "L2",
                                "level2_name", "emp_manager_name"])
    l3_col      = find_col(df, ["L3 Name", "L3Name", "L3", "level3_name"])
    l4_col      = find_col(df, ["L4 Name", "L4Name", "L4", "level4_name"])
    l5_col      = find_col(df, ["L5 Name", "L5Name", "L5", "level5_name"])
    # ID counterparts (separate columns in FSF_TA)
    l2_id_col_fsf = find_col(df, ["L2 ID", "L2ID", "l2_id", "emp_manager_id"])
    l3_id_col_fsf = find_col(df, ["L3 ID", "L3ID", "l3_id"])
    l4_id_col_fsf = find_col(df, ["L4 ID", "L4ID", "l4_id"])
    l5_id_col_fsf = find_col(df, ["L5 ID", "L5ID", "l5_id"])
    l6_id_col_fsf = find_col(df, ["L6 ID", "L6ID", "l6_id"])
    l6_col        = find_col(df, ["L6 Name", "L6Name", "L6", "level6_name"])
    # Warn if this looks like an HRMS dump rather than incentive structure file
    _required_incentive_cols = ["Client-A", "Vintage", "Remarks", "L2 ID"]
    _missing_incentive_cols  = [c for c in _required_incentive_cols
                                 if not any(c.lower() in col.lower() for col in df.columns)]
    if len(_missing_incentive_cols) >= 3:
        st.warning(
            f"⚠️ Structure file appears to be an HRMS export, not the Incentive Structure Dump. "
            f"Missing columns: {', '.join(_missing_incentive_cols)}. "
            f"Please upload the file with columns: Employee ID, Vintage, Client-A, Client-C, "
            f"Remarks, Group, L2 ID, Move/Join Date.",
            icon="⚠️"
        )

    desig_col   = find_col(df, ["Designation", "designation", "Role",
                                "Employee Role", "emp_designation"])

    # New FSF_TA format (May 2026+): Group and Sub Group columns
    group_col    = find_col(df, ["Group", "group", "EmpGroup"])
    subgroup_col = find_col(df, ["Sub Group", "SubGroup", "sub_group", "Sub_Group"])
    # Move/Joining date (used for vintage calculation in new format)
    move_join_col = find_col(df, ["Move/Joining", "Move/Join", "MoveJoining", "Joining"])

    # Determine vertical from emp_vertical_name or emp_fun_area_name
    if vertical_col is None:
        vertical_col = find_col(df, ["emp_vertical_name", "emp_fun_area_name"])

    result = {}
    for _, row in df.iterrows():
        if not emp_col:
            break
        eid = str(row[emp_col]).split(".")[0].strip()
        if not eid or eid.lower() in ("nan", ""):
            continue

        vertical = str(row[vertical_col]).strip().upper() if vertical_col else ""

        # Only process CSD and KCD employees
        if vertical_col and "CSD" not in vertical and "KCD" not in vertical:
            continue

        location = str(row[location_col]).strip()        if location_col else ""
        vintage  = str(row[final_grp]).strip()  if final_grp  else "91-270D"
        vbucket  = str(row[vintage_bkt]).strip() if vintage_bkt else ""
        loc_up   = location.upper()
        vbucket_up = vbucket.upper()

        # Map bucket values from Delhi structure to standard Final Group
        # Delhi file 'bucket' column may have values like "0-30D","31-90D","91-270D","270D+"
        # or older labels -- normalise them
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

        # ── Read Group and Sub Group (new May 2026 format) ─────────────────────
        grp_val    = str(row[group_col]).strip()    if group_col    else ""
        subgrp_val = str(row[subgroup_col]).strip() if subgroup_col else ""
        grp_up     = grp_val.upper()
        sub_up     = subgrp_val.upper()

        # ── Derive Team and Vintage from Group + Sub Group when present ─────────
        # Group/SubGroup mapping (from actual FSF_TA data):
        #
        # CSD:
        #   Group=SPS,  SubGroup=270D+    → CSD SPS 270D+ (with booster)
        #   Group=SPS,  SubGroup=91-270D  → CSD SPS 91-270D (with booster)
        #   Group=90+D, SubGroup=270D+    → CSD SPS 270D+ (no booster, 90+ Days)
        #   Group=90+D, SubGroup=91-270D  → CSD SPS 91-270D (no booster)
        #   Group=0-90D,SubGroup=31-90D   → CSD New Joiner 31-90D
        #   Group=0-90D,SubGroup=0-30D    → CSD New Joiner 0-30D
        #
        # KCD:
        #   Group=DAP,       SubGroup=Catalog   → KCD Catalog
        #   Group=DAP,       SubGroup=Listing   → KCD Listing
        #   Group=DAP 0-90D, SubGroup=Catalog   → KCD Catalog 0-90D
        #   Group=DAP 0-90D, SubGroup=Listing   → KCD Listing 0-90D
        #   Group=90+D,      SubGroup=270D+     → KCD Regular 270D+
        #   Group=90+D,      SubGroup=91-270D   → KCD Regular 91-270D
        #   Group=0-90,      SubGroup=CSD to KCD→ KCD Regular 0-90D
        #   Group=ROI        → KCD ROI
        #   Group=HVRI       → KCD HVRI
        #   Group=Pharma     → KCD Nagpur Pharma
        #   Group=Non Pharma → KCD Non-Pharma
        #   Group=SAM-ILP    → KCD SAM ILP
        #   Group=- (Tele Annual) → skip

        _has_group_data = bool(grp_val and grp_val not in ("-",""))

        # Helper: derive vintage from date when both Sub Group and Vintage are "-"
        def _vintage_from_date():
            """Calculate vintage bucket from Move/Joining date → Joining Date fallback."""
            _ref_date = None
            if move_join_col:
                _mv = row.get(move_join_col)
                try:
                    _ref_date = pd.to_datetime(_mv, errors='coerce')
                    if pd.isna(_ref_date): _ref_date = None
                except Exception:
                    pass
            if _ref_date is None:
                _jd = row.get("Joining Date") or row.get("Move/Joining")
                try:
                    _ref_date = pd.to_datetime(_jd, errors='coerce')
                except Exception:
                    pass
            if _ref_date is None or pd.isna(_ref_date):
                return "270D+"   # safe default for 90+D/SPS employees
            _days = (pd.Timestamp.today() - _ref_date).days
            if _days >= 270:   return "270D+"
            elif _days >= 91:  return "91-270D"
            elif _days >= 31:  return "31-90D"
            else:              return "0-30D"

        def _resolve_vintage(sub_grp_val, fallback_vintage):
            """Use Sub Group value if valid, else fallback, else compute from date."""
            _VALID = ("270D+", "91-270D", "31-90D", "0-30D")
            if sub_grp_val.strip() in _VALID:
                return sub_grp_val.strip()
            if fallback_vintage.strip() in _VALID:
                return fallback_vintage.strip()
            return _vintage_from_date()

        if _has_group_data:
            # ── CSD routing from Group ──────────────────────────────────────────
            if "CSD" in vertical:
                if grp_up == "SPS":
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = "SPS"
                    team    = "SPS (CSD 91D+)"
                elif grp_up == "90+D":
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = "90+ Days"
                    team    = "90+ Days (CSD)"     # distinct from SPS — no booster eligibility
                elif grp_up in ("0-90D", "0-90"):
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    if vintage not in ("0-30D","31-90D"): vintage = "31-90D"
                    vbucket = vintage
                    team    = "0-90 Days (CSD new)"
                else:
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    team    = "SPS (CSD 91D+)"
            # ── KCD routing from Group ──────────────────────────────────────────
            elif "KCD" in vertical:
                _is_0_90 = "0-90" in grp_up
                if "DAP" in grp_up:
                    team    = "Catalog (KCD)" if "CATALOG" in sub_up else ("Listing (KCD)" if "LISTING" in sub_up else "Catalog (KCD)")
                    vintage = "31-90D" if _is_0_90 else _resolve_vintage(subgrp_val, vintage)
                    vbucket = "0-90D" if _is_0_90 else vintage
                elif grp_up == "ROI":
                    team    = "ROI KCD"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = vintage
                elif grp_up == "HVRI":
                    team    = "HVRI KCD"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = vintage
                elif grp_up in ("PHARMA","NON PHARMA"):
                    team    = "Nagpur Pharma KCD"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    if vintage not in ("270D+","91-270D"): vintage = "270D+"
                    vbucket = vintage
                elif grp_up in ("SAM-ILP","SAM ILP"):
                    team    = "KCD SAM ILP"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = vintage
                elif grp_up == "0-90":
                    team    = "Regular KCD"
                    vintage = "31-90D"
                    vbucket = "0-90D"
                elif grp_up == "90+D":
                    team    = "Regular KCD"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = vintage
                else:
                    team    = "Regular KCD"
                    vintage = _resolve_vintage(subgrp_val, vintage)
                    vbucket = vintage
        else:
            # ── Fallback: old derivation (Remarks/Location/Vintage columns) ───────
            # ── Remarks column (Listing/Catalog/- for KCD) ──────────────────────
            team_from_file = str(row[remarks_col]).strip() if remarks_col else ""
            remarks = team_from_file
            rem_up  = team_from_file.upper()

            if "CSD" in vertical:
                if vintage in ("0-30D", "31-90D"):
                    team = "0-90 Days (CSD new)"
                elif any(x in vbucket_up for x in ["SPS", "90+ DAYS", "90+DAYS", "CSD ROI"]):
                    team = "SPS (CSD 91D+)"
                elif any(x in vbucket_up for x in ["0-90 DAYS", "0-90DAYS"]):
                    team = "0-90 Days (CSD new)"
                elif "90+ DAYS" in vbucket_up or "90+DAYS" in vbucket_up or vbucket_up == "90+ DAYS":
                    team = "90+ Days (CSD)"         # non-SPS 90+ Days
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
                    _lc_raw  = _safe_float(row[list_c_col], 0) if list_c_col and str(row[list_c_col]).strip() not in ("nan","") else 0
                    _cat_raw = _safe_float(row[cat_c_col], 0) if cat_c_col and str(row[cat_c_col]).strip() not in ("nan","") else 0
                    _ca_raw  = _safe_float(row[client_a], 0) if client_a and str(row[client_a]).strip() not in ("nan","") else 0
                    if _ca_raw > 0 and _lc_raw / _ca_raw >= 0.60:
                        team = "Listing (KCD)"
                    elif _ca_raw > 0 and _cat_raw / _ca_raw >= 0.60:
                        team = "Catalog (KCD)"
                    else:
                        team = "Regular KCD"
            else:
                team = "Regular KCD"

        # remarks for display (show Group+SubGroup when available, else raw remarks col)
        if _has_group_data:
            remarks = f"{grp_val}/{subgrp_val}" if subgrp_val and subgrp_val != "-" else grp_val
        else:
            remarks = team_from_file if 'team_from_file' in dir() else ""
        def _safe_float(val, default=0):
            try:
                v = float(val)
                return v if not (v != v) else default  # NaN check
            except (TypeError, ValueError):
                return default

        # Read Client-A and Client-C directly from FSF_TA columns (pre-computed in sheet)
        raw_client_a = _safe_float(row[client_a] if client_a else None, 0)
        raw_client_c = _safe_float(row[client_c] if client_c else None, 0)

        if "CSD" in vertical:
            # CSD: Client Count = Client-A (actual clients)
            #      Client-C = Calculated clients (weighted, pre-computed in FSF_TA)
            # Enforce minimum of 50 per scheme FAQ Q11
            cc = max(raw_client_a, 50) if raw_client_a > 0 else 50
            stored_client_c = max(raw_client_c, 50) if raw_client_c > 0 else cc
        elif "KCD" in vertical:
            # KCD: Client Count = Client-A (overall count)
            #      Client-C not used for KCD (uses Listing/Catalog split separately)
            if raw_client_a > 0:
                cc = raw_client_a
            elif list_c_col and cat_c_col:
                lc = _safe_float(row[list_c_col], 0)
                cc_val = _safe_float(row[cat_c_col], 0)
                cc = lc + cc_val if (lc + cc_val) > 0 else 100
            else:
                cc = 100
            stored_client_c = raw_client_c  # KCD Client-C shown in output but not used for PCDV
        else:
            cc = 100
            stored_client_c = 0

        # ── Joining Date -- convert Excel serials (from xlsb) to proper dates ──
        jd = None
        if joining_col:
            jd_raw = row[joining_col]
            raw_str = str(jd_raw).strip()
            if raw_str not in ("", "nan", "NaT", "None"):
                jd = _to_date(jd_raw)

        # Collection Target: if column is "PCR Target" (per-client) → multiply by client count
        # If column is "Collection Target" (absolute value) → use directly, derive PCR Target
        coll_target = 0.0
        pcr_target_raw = 0.0
        pcr_col = find_col(df, ["PCR Target","PCDV Target","PCR_Target"])
        ct_col  = find_col(df, ["Collection Target"])
        if pcr_col:
            try:
                pcr_target_raw = float(row[pcr_col])
                coll_target = pcr_target_raw * cc
            except Exception:
                coll_target = 0.0
        elif ct_col:
            try:
                _ct = float(row[ct_col])
                if _ct > 0:
                    coll_target = _ct          # already absolute value
                    pcr_target_raw = _ct / cc if cc > 0 else 0   # derive per-client rate
            except Exception:
                coll_target = 0.0

        # Read Listing/Catalog client splits for KCD Collection Target derivation
        lc_val  = _safe_float(row[list_c_col], 0) if list_c_col and str(row[list_c_col]).strip() not in ("nan","") else 0
        cat_val = _safe_float(row[cat_c_col], 0)  if cat_c_col  and str(row[cat_c_col]).strip()  not in ("nan","") else 0

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
            "Client Count":      cc,           # Client-A (actual clients, used for KCD + CSD as denominator)
            "Client-A":          raw_client_a, # raw Client-A straight from FSF_TA
            "Client-C":          stored_client_c,  # Calculated clients from FSF_TA (for CSD PCDV)
            "Listing Clients":   lc_val,
            "Catalog Clients":   cat_val,
            "PCR Target":        pcr_target_raw,
            "Collection Target": coll_target,
            "L2 ID":             str(row[l2_id_col_fsf]).split('.')[0].strip() if l2_id_col_fsf and pd.notna(row[l2_id_col_fsf]) else "",
            "L2 Name":           str(row[l2_col]).strip() if l2_col else "",
            "L3 ID":             str(row[l3_id_col_fsf]).split('.')[0].strip() if l3_id_col_fsf and pd.notna(row[l3_id_col_fsf]) else "",
            "L3 Name":           str(row[l3_col]).strip() if l3_col else "",
            "L4 ID":             str(row[l4_id_col_fsf]).split('.')[0].strip() if l4_id_col_fsf and pd.notna(row[l4_id_col_fsf]) else "",
            "L4 Name":           str(row[l4_col]).strip() if l4_col else "",
            "L5 ID":             str(row[l5_id_col_fsf]).split('.')[0].strip() if l5_id_col_fsf and pd.notna(row[l5_id_col_fsf]) else "",
            "L5 Name":           str(row[l5_col]).strip() if l5_col else "",
            "L6 ID":             str(row[l6_id_col_fsf]).split('.')[0].strip() if l6_id_col_fsf and pd.notna(row[l6_id_col_fsf]) else "",
            "L6 Name":           str(row[l6_col]).strip() if l6_col else "",
            "Vintage Bucket":    vbucket,
            "Remarks":           remarks,
            "Group":             grp_val,
            "Sub Group":         subgrp_val,
            "MDC Client Count":  mdc_client_cnt,
        }

    # ── Aggregate L1 client counts onto L2 employees ─────────────────────────
    # FSF formula: L2 Client-A = SUMIFS(L1 Client-A, L1.Manager_ID = L2.EmpID)
    # The structure file has "L2 ID" column on L1 rows = their direct manager.
    # L2 employees' own rows have Client-A=0; we must build it from L1 subordinates.
    l2_id_col = find_col(df, ["L2 ID", "L2ID", "Manager ID", "ManagerID"])
    if l2_id_col:
        # Include ALL designation rows (not just L1) so that RM's own clients are counted
        # Sir's FSF: SUMIFS(Client-C, L2_ID=RM_ID) — no designation filter!
        all_rows = df.copy() if desig_col else pd.DataFrame()
        # BUT for L1 count and team size, we need only L1 rows
        l1_rows = df[df[desig_col].astype(str).str.upper().str.strip() == "L1"].copy() if desig_col else pd.DataFrame()
        if len(all_rows) > 0:
            for col in [client_a, client_c, "Base", "Listing"]:
                if col and col in all_rows.columns:
                    all_rows[col] = pd.to_numeric(all_rows[col], errors='coerce').fillna(0)
            all_rows["_l2_id"] = all_rows[l2_id_col].astype(str).str.split('.').str[0].str.strip()

            # Build aggregation per L2 ID and vertical (ALL rows for Client-A/C sums)
            vert_col_name = find_col(df, ["IIL Vertical Name", "Vertical", "vertical"])
            if vert_col_name:
                all_rows["_vert"] = all_rows[vert_col_name].astype(str).str.upper().str.strip()
            else:
                all_rows["_vert"] = ""

            # L1 count aggregation (separate, uses only L1 rows)
            if len(l1_rows) > 0:
                l1_rows["_l2_id"] = l1_rows[l2_id_col].astype(str).str.split('.').str[0].str.strip()
                l1_rows["_vert"]  = all_rows.loc[l1_rows.index, "_vert"] if "_vert" in all_rows.columns else ""
                _id_col = "Employee ID" if "Employee ID" in l1_rows.columns else l1_rows.columns[0]
                l1_cnt_agg = l1_rows.groupby(["_l2_id", "_vert"])[_id_col].count().reset_index()
                l1_cnt_agg.columns = ["_l2_id", "_vert", "_l1_count"]
            else:
                l1_cnt_agg = pd.DataFrame(columns=["_l2_id","_vert","_l1_count"])

            _sum_cols = {c: 'sum' for c in ([client_a, client_c] + (["Base","Listing"] if "Base" in all_rows.columns else []))
                         if c and c in all_rows.columns}
            _cnt_col = "_l1_count"
            l2_agg = all_rows.groupby(["_l2_id", "_vert"]).agg(_sum_cols).reset_index()
            l2_agg.columns = ["_l2_id", "_vert"] + list(_sum_cols.keys())
            l2_agg = l2_agg.merge(l1_cnt_agg, on=["_l2_id","_vert"], how="left")
            l2_agg["_l1_count"] = l2_agg["_l1_count"].fillna(0).astype(int)

            # Patch L2 employees in result dict
            for eid, emp_data in result.items():
                desig_v = str(emp_data.get("Designation", "")).upper().strip()
                if desig_v not in ("L2", "ILP"):
                    continue
                vert_v = str(emp_data.get("Vertical", "")).upper().strip()
                # Find matching row in aggregation
                mask = (l2_agg["_l2_id"] == eid)
                if vert_v:
                    vert_mask = l2_agg["_vert"].str.contains(vert_v[:3], na=False)
                    if vert_mask.any():
                        mask = mask & vert_mask
                matched = l2_agg[mask]
                if len(matched) == 0:
                    # Try without vert filter (fallback)
                    matched = l2_agg[l2_agg["_l2_id"] == eid]
                if len(matched) == 0:
                    continue
                row_agg = matched.iloc[0]
                if client_a and client_a in row_agg.index:
                    result[eid]["Client Count"] = float(row_agg[client_a])
                    result[eid]["Client-A"]     = float(row_agg[client_a])
                if client_c and client_c in row_agg.index:
                    result[eid]["Client-C"] = float(row_agg[client_c])
                if "Listing" in row_agg.index:
                    result[eid]["Listing Clients"] = float(row_agg.get("Listing", 0))
                if "Base" in row_agg.index:
                    result[eid]["Base Clients"] = float(row_agg.get("Base", 0))
                # L1 count — try merged column first, fallback to direct count
                if _cnt_col in row_agg.index and row_agg[_cnt_col] > 0:
                    l1_cnt = int(row_agg[_cnt_col])
                else:
                    # Direct count from l1_cnt_agg
                    _direct = l1_cnt_agg[l1_cnt_agg["_l2_id"] == eid]
                    l1_cnt = int(_direct["_l1_count"].sum()) if len(_direct) > 0 else 0
                eff_team = (4 if (result[eid].get("Client Count", 0) > 375 and l1_cnt < 4)
                            else max(3, l1_cnt))
                result[eid]["L1 Count"] = l1_cnt
                result[eid]["Effective Team Size"] = eff_team

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
    Reads ALL sheets (Sheet1=L1, Sheet2=L2, etc.) and merges them.
    Returns dict: { emp_id_str: {"slab1": float, "slab2": float} }
    """
    if uploaded_file is None:
        return {}
    try:
        # Read all sheets and combine (Sheet1=L1 targets, Sheet2=L2 targets)
        try:
            all_sheets = pd.read_excel(uploaded_file, sheet_name=None,
                                       engine="pyxlsb" if str(getattr(uploaded_file,"name","")).endswith(".xlsb") else None)
            uploaded_file.seek(0)
            df = pd.concat([s for s in all_sheets.values() if len(s) > 0], ignore_index=True)
        except Exception:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
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
            eid = str(row[emp_col]).split(".")[0].strip()
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


def load_sam_ilp_targets(uploaded_file):
    """Load SAM-ILP individual DV targets from uploaded file.

    Supports sir's May 2026 format (xlsb or xlsx):
      Sheet: 'ILP Team'  (or first sheet)
      Headers start at row 5 (1-indexed), data from row 6 onwards
      Columns: Employee ID, Employee Name, L4/Direct Name, ZM,
               Joining Date, Vertical, Design., Total (Client-A),
               Catalog, SS/LS (= Listing), ILP Client, Target (In Lac)

      Target (In Lac) = Deal Value target in Lacs → multiply × 1,00,000

    Also accepts simpler formats:
      Columns: Employee ID, DV_Target / Target / Overall Target

    Returns dict: {emp_id: {"target": float, "catalog": int, "listing": int,
                             "ilp_client": int, "client_a": int, "rate_95": None}}
    """
    if uploaded_file is None:
        return {}
    try:
        fname = getattr(uploaded_file, "name", str(uploaded_file)).lower()
        df = None

        # ── Handle xlsb separately (pyxlsb) ─────────────────────────────────
        if fname.endswith(".xlsb"):
            try:
                import pyxlsb, io
                raw = uploaded_file.read()
                with pyxlsb.open_workbook(io.BytesIO(raw)) as wb:
                    sheet_name = "ILP Team" if "ILP Team" in wb.sheets else wb.sheets[0]
                    with wb.get_sheet(sheet_name) as ws:
                        all_rows = [[c.v for c in row] for row in ws.rows()]

                # Find header row: look for row containing 'Employee ID'
                hdr_idx = None
                for i, row in enumerate(all_rows):
                    if any("employee id" in str(v).lower() for v in row if v):
                        hdr_idx = i
                        break
                if hdr_idx is None:
                    st.warning("SAM-ILP xlsb: could not find 'Employee ID' header row")
                    return {}

                headers = all_rows[hdr_idx]
                data_rows = [dict(zip(headers, r)) for r in all_rows[hdr_idx+1:]
                             if any(v is not None for v in r)]
                df = pd.DataFrame(data_rows)
            except ImportError:
                st.warning("SAM-ILP targets: xlsb format requires pyxlsb. Install with: pip install pyxlsb")
                return {}
            except Exception as e:
                st.warning(f"SAM-ILP xlsb read error: {e}")
                return {}
        else:
            df = _read_file(uploaded_file)

        if df is None or len(df) == 0:
            return {}

        df.columns = [str(c).strip() if c else "" for c in df.columns]
        df = df.dropna(how="all")

        # ── Column detection ─────────────────────────────────────────────────
        emp_col = find_col(df, ["Employee ID", "Emp ID", "EmpID", "ID"])
        tgt_col = find_col(df, [
            "Target (In Lac)", "Target (In Lacs)", "Target_Lac", "DV_Target",
            "DV Target", "Deal Value Target", "Target", "Overall Target",
        ])
        cat_col  = find_col(df, ["Catalog", "Catalog C", "CatalogClient"])
        list_col = find_col(df, ["SS/LS", "Listing", "SS/Listing", "Listing C", "ListingClient"])
        ilp_col  = find_col(df, ["ILP Client", "ILP", "ILPClient"])
        ca_col   = find_col(df, ["Total", "Client-A", "Client A", "Total Clients"])

        if not emp_col or not tgt_col:
            st.warning(f"SAM-ILP targets: found columns {list(df.columns[:10])} — "
                       f"need 'Employee ID' and 'Target (In Lac)' columns")
            return {}

        result = {}
        for _, row in df.iterrows():
            eid = str(row.get(emp_col, "")).strip().split('.')[0]
            if not eid or eid.lower() in ('nan', '', 'none', 'employee id'):
                continue
            try:
                raw_tgt = float(row[tgt_col])
            except (TypeError, ValueError):
                continue

            # Convert target: if > 1000 assume already in ₹; if < 10000 assume Lacs
            if raw_tgt < 10000:
                target = raw_tgt * 100_000   # Lacs → ₹
            else:
                target = raw_tgt

            result[eid] = {
                "target":     target,
                "catalog":    int(float(row[cat_col]))  if cat_col  and pd.notna(row.get(cat_col))  else 0,
                "listing":    int(float(row[list_col])) if list_col and pd.notna(row.get(list_col)) else 0,
                "ilp_client": int(float(row[ilp_col]))  if ilp_col  and pd.notna(row.get(ilp_col))  else 0,
                "client_a":   int(float(row[ca_col]))   if ca_col   and pd.notna(row.get(ca_col))   else 0,
                "rate_95":    None,
            }
        if result:
            st.toast(f"✅ SAM-ILP targets loaded: {len(result)} employees")
        return result

    except Exception as e:
        st.warning(f"SAM-ILP targets file error: {e}")
        return {}


def load_kcd_targets(uploaded_file):
    """Load per-employee KCD targets from multiple sheet formats.
    Supports:
    - Classic kcd_calc style: Employee ID, Client-A, Listing Client, Catalog Client, Target
    - Incentive L1/L2 style (multi-sheet): employeeid, Catalog C, Listing C, Overall, Target, Ctarget, Ltarget
    Returns dict: {emp_id_str: {client_a, listing, catalog, pcr_target, coll_target, team}}
    """
    if uploaded_file is None:
        return {}
    result = {}
    try:
        xl = pd.ExcelFile(uploaded_file)
        # Try Incentive_L1_L2 style (multi-sheet: 0-90D L1, 90D+ L1, SAM)
        target_sheets = [s for s in xl.sheet_names
                         if any(k in s.lower() for k in ['0-90', '90d', 'l1', 'sam', 'l2'])]
        if target_sheets:
            for sh in xl.sheet_names:
                try:
                    df = pd.read_excel(uploaded_file, sheet_name=sh)
                    df.columns = [str(c).strip() for c in df.columns]
                    emp_col = find_col(df, ["employeeid","Employee ID","EmpID","Emp ID","level2_id"])
                    if not emp_col: continue
                    for _, row in df.iterrows():
                        eid = str(row[emp_col]).split(".")[0].strip().split('.')[0]
                        if not eid or eid.lower() in ("nan","direct",""): continue
                        def _n(keys):
                            for k in keys:
                                if k in row.index and pd.notna(row[k]):
                                    try: return float(row[k])
                                    except: pass
                            return 0.0
                        _ca   = _n(["Overall","Client-A","Total Client","total_client"])
                        _lc   = _n(["Listing C","Listing Client","Listing Clients","listing_client"])
                        _cc   = _n(["Catalog C","Catalog Client","Catalog Clients","catalog_client"])
                        _ct   = _n(["Target","Collection Target","Overall Target","overall_target"])
                        _lt   = _n(["Ltarget","Listing Target","listing_target"])
                        _catt = _n(["Ctarget","Catalog Target","catalog_target"])
                        if _ct == 0: _ct = _lt + _catt
                        _pcr  = _ct / _ca if _ca > 0 else 0
                        _team = str(row["Team"]).strip() if "Team" in row.index and pd.notna(row.get("Team")) else ""
                        if eid not in result or _ca > result[eid].get("client_a", 0):
                            result[eid] = {"client_a": _ca, "listing": _lc, "catalog": _cc,
                                           "pcr_target": _pcr, "coll_target": _ct, "team": _team}
                except Exception:
                    continue
            return result
        # Fallback: single-sheet classic format
        df = _read_file(uploaded_file)
        df.columns = [str(c).strip().replace('\n', ' ') for c in df.columns]
        emp_col = find_col(df, ["Employee ID","Emp ID","EmpID","ID","employeeid"])
        if not emp_col: return {}
        ca_col    = find_col(df, ["Client-A","Client A","Overall","Total Client"])
        lc_col    = find_col(df, ["Listing Client","Listing Clients","Listing C"])
        cc_col    = find_col(df, ["Catalog Client","Catalog Clients","Catalog C"])
        ct_col    = find_col(df, ["Collection Target","Target","Overall Target"])
        lt_col    = find_col(df, ["Listing Target","Ltarget"])
        cat_t_col = find_col(df, ["Catalog Target","Ctarget"])
        for _, row in df.iterrows():
            eid = str(row[emp_col]).split(".")[0].strip().split('.')[0]
            if not eid or eid.lower() in ("nan", ""): continue
            def _nv(c):
                if not c: return 0.0
                try: return float(row[c])
                except: return 0.0
            _ct = _nv(ct_col)
            if _ct == 0 and lt_col and cat_t_col:
                _ct = _nv(lt_col) + _nv(cat_t_col)
            _ca = _nv(ca_col)
            _pcr_t = _ct / _ca if _ca > 0 else 0
            result[eid] = {"client_a": _ca, "listing": _nv(lc_col), "catalog": _nv(cc_col),
                           "pcr_target": _pcr_t, "coll_target": _ct, "team": ""}
        return result
    except Exception as e:
        st.warning(f"KCD Targets file error: {e}")
        return {}


def calc_cmr_per_employee_by_col(renewal_df, group_col):
    """Group renewal data by a custom column (e.g. L2 name) instead of EMP ID.
    Used for CSD L2 Rel Mgr whose renewals are tagged with their NAME in the 'L2' column.
    Returns dict keyed by the group_col values (name strings).
    """
    if renewal_df is None or group_col not in renewal_df.columns:
        return {}
    df = renewal_df.copy()
    status_col  = find_col(df, ["Status", "STATUS"])
    product_col = find_col(df, ["WS/MDC Main", "DCR Services", "Product", "Service"])
    df["_key"] = df[group_col].astype(str).str.strip()
    df["_received"] = df[status_col].astype(str).str.upper().str.contains("RECEIVED", na=False) if status_col else False
    df["_is_ss_plus"] = df[product_col].astype(str).str.upper().apply(
        lambda p: any(k in p for k in SS_PLUS_KEYWORDS)) if product_col else False
    result = {}
    for key, grp in df.groupby("_key"):
        key_str = str(key).strip()
        if not key_str or key_str.lower() in ("nan", "none", "direct", ""):
            continue
        total_sent     = len(grp)
        total_received = int(grp["_received"].sum())
        ss_sent        = int(grp["_is_ss_plus"].sum())
        ss_received    = int((grp["_is_ss_plus"] & grp["_received"]).sum())
        result[key_str] = {
            "renewal_sent": total_sent, "renewal_received": total_received,
            "cmr_pct": round(total_received / total_sent * 100, 2) if total_sent > 0 else 0.0,
            "ss_sent": ss_sent, "ss_received": ss_received,
            "ss_cmr_pct": round(ss_received / ss_sent * 100, 2) if ss_sent > 0 else 0.0,
        }
    return result


def calc_cmr_per_employee(renewal_df):
    if renewal_df is None:
        return {}

    df = renewal_df.copy()

    # ── Detect column names flexibly ─────────────────────────
    emp_id_col  = find_col(df, ["EMP ID", "Emp ID", "EmpID", "Employee ID", "EMPID", "Emp_ID", "emp id", "EMPLOYEEID", "CC Emp ID"])
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

        # L1 name -- first non-blank value
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
    """
    Per FAQ Q3: CMR col based on overall CMR sent/received.
    Sent 0 → col1 (100%); Sent 1 → 1 rcvd → col1; Sent 2 → ≥1 rcvd → col1;
    Sent 3 → ≥2 rcvd → col1; Sent ≥4 → use actual CMR%.
    col=0 means CMR not achieved → per_txn=0.
    """
    recd = round(cmr_pct * sent_count / 100)   # approximate received from %
    if sent_count == 0:
        return 1, "No CMR sent (forced col 1)"
    elif sent_count == 1:
        if recd >= 1: return 1, "Sent 1, rcvd 1 (forced col 1)"
        return 0, "Sent 1, rcvd 0"
    elif sent_count == 2:
        if recd >= 1: return 1, "Sent 2, rcvd ≥1 (forced col 1)"
        return 0, f"Sent 2, rcvd {recd}<1"
    elif sent_count == 3:
        if recd >= 2: return 1, "Sent 3, rcvd ≥2 (forced col 1)"
        return 0, f"Sent 3, rcvd {recd}<2"
    else:  # sent >= 4: use actual CMR%
        if cmr_pct >= slab2_target:
            return 2, f"CMR {cmr_pct:.1f}% ≥ {slab2_target}%"
        if cmr_pct >= slab1_target:
            return 1, f"CMR {cmr_pct:.1f}% ≥ {slab1_target}%"
        return 0, f"CMR {cmr_pct:.1f}% < {slab1_target}%"


# ═══════════════════════════════════════════════════════════════
# CALCULATION FUNCTIONS  (all values come from parsed slab config)
# ═══════════════════════════════════════════════════════════════

def pcdv_slab(pcdv, slabs, col):
    """col=0: CMR below slab1 → 0; col=1: slab1 rate; col=2: slab2 rate"""
    if col == 0:
        return 0, 0   # CMR not achieved → no per-txn incentive
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
                 pop_cmr_floor=None, metric_label="PCDV",
                 prod_score_receipt=None):
    """
    CSD 0-30D / 31-90D base + PoP.
    - Base: fixed PCDV slab × CMR multiplier
    - PoP: T1×500 + T2×1000 + T3×1500 from RECEIPT service tiers (sir's formula)
    - min_txn gate uses RECEIPT productive count (svc_tiers), NOT renewal count
    - _final_pcdv = PCDV_slab + Incremental (BEFORE CMR mult) — matches FSF col
    - Returns 9 values: base_total, pop, notes, tier1, tier2, tier3, pcdv_amt, incr_amt, final_pcdv
    """
    min_txn = S["min_txn_0_30"] if vintage == "0-30D" else S["min_txn_31_90"]

    # Base incentive: fixed payout from PCDV slab table
    _slabs = S["csd_new_slabs"]  # [(threshold, payout), ...] sorted descending
    base   = next((r for t, r in _slabs if pcdv >= t), 0)
    _pcdv_slab_hit = base > 0
    _incr_threshold = _slabs[0][0] if _slabs else 2800
    incr  = max(0, pcdv - _incr_threshold) * client_c * S["csd_new_incr_rate"] if pcdv > _incr_threshold else 0
    # CMR multiplier: Slab 2 → 120%, Slab 1 → 100%, below Slab 1 → 0%
    mult  = S["csd_slab2_mult"] if cmr_slab == 2 else (1.0 if cmr_slab >= 1 else 0.0)
    _base_before_cap = (base + incr) * mult
    base_total = round(_base_before_cap, 0)   # combined cap with PoP applied in route_calc

    # Tier counts from receipt (sir's MDC-Annual||TS-1 / MDC-MYR||... / TS-3||... cols)
    _tier1 = len([t for t in (svc_tiers or []) if t == 1])
    _tier2 = len([t for t in (svc_tiers or []) if t == 2])
    _tier3 = len([t for t in (svc_tiers or []) if t == 3])
    _receipt_prod_count = _tier1 + _tier2 + _tier3

    # PoP min-txn gate: use RECEIPT tier count (not renewal-based prod_score)
    # Key fix: 123024 has 7 receipt txns but 0 received Annual renewals → was wrongly blocked
    if svc_tiers is not None:
        prod_score_for_gate = _receipt_prod_count
    else:
        prod_score_for_gate, _, _ = calc_productivity(rnl_prods, rnl_modes, "csd_new")

    # For 0-90D: PoP gate is always CMR Slab1 achieved (scheme says "First Slab of CMR target eligibility")
    # _use_slab_gate / _both_achiev_on are NOT used for 0-90D PoP — removed from here

    pop = 0
    pop_reason = ""
    # CMR gate: Slab 1 must be achieved (cmr_slab >= 1) — regardless of flat floor %
    _cmr_qualified = (cmr_slab >= 1)

    if not _cmr_qualified:
        pop_reason = f"PoP blocked: CMR Slab 1 not achieved (slab={cmr_slab}, {cmr_pct_achieved:.1f}%)"
    elif prod_score_for_gate < min_txn:
        pop_reason = f"PoP blocked: {prod_score_for_gate} txns < {min_txn} min"
    else:
        # PoP = T1×₹500 + T2×₹1000 + T3×₹1500 (sir's formula from receipt tiers)
        if svc_tiers is not None:
            pop = _tier1 * 500 + _tier2 * 1000 + _tier3 * 1500
            pop_reason = f"PoP: T1={_tier1}x500 + T2={_tier2}x1000 + T3={_tier3}x1500 = {pop}"
        else:
            eligible = [p for p, m in zip(rnl_prods, rnl_modes)
                        if str(m).upper() in ("ANNUAL","MULTI YEAR","MULTIYEAR","MYR")
                        and not is_insta(p)]
            pop = sum(pop_for_product(p, S["prod_to_pop"]) for p in eligible)
            pop_reason = f"PoP: {prod_score_for_gate} txns x CMR {cmr_pct_achieved:.1f}%"

        # 0-90D PoP: NO multiplier — full amount if CMR Slab1 achieved and min txns met
        # "Both Achievers" multiplier applies to 90+ SPS base incentive only, not 0-90D PoP
        pop_reason += " | PoP: full amount (CMR Slab1 achieved)"

    notes = (f"CSD {vintage} | {metric_label}:{round(pcdv)} | clients:{int(client_c)} | "
             f"CMR slab:{cmr_slab} | {pop_reason}")
    # PCDV breakdown matching FSF Exec-CSD columns
    _pcdv_amount = round(base, 0)          # FSF col: "PCDV Amount"
    _incr_amount = round(incr, 2)          # FSF col: "Incremental 3% Amount"
    _final_pcdv  = round(base + incr, 2)  # FSF col: "Final PCDV Amount" (BEFORE CMR mult)
    return round(base_total, 0), round(pop, 0), notes, _tier1, _tier2, _tier3, _pcdv_amount, _incr_amount, _final_pcdv


def calc_csd_sps(pcdv, prod_score, txn_count, cmr_slab, vintage,
                mdc1_cmr, ext_tat, d60, S, metric_label="PCDV", is_sps=False,
                mdc1_cmr_plus1=None):
    """
    CSD SPS 91-270D / 270D+.
    - is_sps=True  
    mdc1_cmr      = current month MDC-1 CMR% (April, for display as "MDC-1 CMR%")
    mdc1_cmr_plus1 = next month MDC-1 CMR% (May, used for the multiplier)
                     If None or sent=0 → 100% (no clients due = no penalty)
    """
    # Use next-month MDC-1 for the multiplier (scheme: "MDC 1- CMR+1% Multiplier")
    # mdc1_cmr_plus1=None means sent=0 → 100% (no MDC-1 clients due next month = no penalty)
    # mdc1_cmr = CURRENT month's MDC-1 CMR% (display only, not used for multiplier)
    _mdc1_for_mult = mdc1_cmr_plus1 if mdc1_cmr_plus1 is not None else 100.0
    slabs = S.get("csd_sps_270p", []) if vintage == "270D+" else S.get("csd_sps_91_270", [])
    # cmr_slab=0 means employee is below Slab1 CMR target → no per-txn incentive
    if cmr_slab == 0:
        per_txn = 0
    else:
        _, per_txn = pcdv_slab(pcdv, slabs, cmr_slab)

    eff_txn_count = max(int(prod_score), 0) if prod_score > 0 else txn_count

    # MDC-1 Multiplier is based on mdc1_cmr_plus1 (NEXT month's MDC-1 CMR%)
    # NOT on mdc1_cmr (current month all-renewals CMR%)
    hi = S.get("mdc1_above", 35); mid = S.get("mdc1_between", 25)
    if _mdc1_for_mult > hi:
        mdc1_mult = S.get("mdc1_mult_hi", 1.2)
    elif _mdc1_for_mult >= mid:
        mdc1_mult = S.get("mdc1_mult_md", 1.0)
    else:
        mdc1_mult = S.get("mdc1_mult_lo", 0.5)

    mdc1_cmr_display = mdc1_cmr if mdc1_cmr is not None else 0.0  # for scheme notes only

    # Booster: FSF AN = IF(AND(SPS, ext_tat<1, 60D<10%, base>=1), base*1.2, base)
    # Must be SPS group AND meet BOTH criteria. Non-SPS (90+ Days) never get booster.
    if (is_sps
            and ext_tat is not None and float(ext_tat) < S.get("boost_tat_thr", 1)
            and d60 is not None     and float(d60)     < S.get("boost_60d_thr", 10)):
        booster = S.get("boost_mult", 1.2)
    else:
        booster = 1.0

    # ── Both Achievers / Only CMR (per KCD & CSD Magnificent May PPT) ──────────
    # "Both Achievers (PCDV+CMR) earn 125% & Only CMR Achievers will get 50% Payout"
    # Step 1: compute pre-BA base = per_txn × txns
    # Step 2: apply BothAchievers (×125%) or OnlyCMR (50% of lowest CMR-slab rate × txns)
    # Step 3: × mdc1_mult × booster
    _ba_note = ""
    if S.get("both_achievers_on", False) and cmr_slab >= 1:
        _pcdv_hit = per_txn > 0  # PCDV cleared at least the lowest slab threshold
        if _pcdv_hit:
            # Both Achievers: PCDV slab + CMR slab both achieved → ×125%
            raw_base = per_txn * eff_txn_count * S.get("both_achievers_pct", 1.25)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        else:
            # Only CMR Achiever: PCDV below all slabs → 50% of lowest-threshold rate for this CMR slab
            _lowest_slab_rate = (slabs[-1][2] if cmr_slab == 2 else slabs[-1][1]) if slabs else 0
            raw_base = _lowest_slab_rate * eff_txn_count * S.get("cmr_only_pct", 0.50)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"
    elif cmr_slab == 0:
        raw_base = 0  # Below CMR slab 1 → no incentive
    else:
        raw_base = per_txn * eff_txn_count  # both_achievers_on=False → plain per-txn

    total = round(raw_base * mdc1_mult * booster, 0)

    notes = (f"CSD SPS {vintage} | {metric_label}:{round(pcdv)} | CMR slab:{cmr_slab} | "
             f"₹{per_txn}/txn×{eff_txn_count} | MDC1:{mdc1_mult:.1f}(CMR+1:{_mdc1_for_mult:.0f}%|CMR:{mdc1_cmr_display:.0f}%) "
             f"boost:{booster}{_ba_note} | No PoP")
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


def calc_csd_rel_mgr(pcr, pcdv, prod_raw, cmr_pct, mdc1_cmr_pct,
                     cmr_plus1_pct, ext_tat, d60, is_sps, S,
                     emp_cmr_slab1=None, emp_cmr_slab2=None):
    """
    CSD Relationship Manager incentive (Slide 6-7 of CSD_Magnificent_May_Scheme.pptx).

    Logic:
    1. PCDV slab lookup gives (r1=Slab1_rate, r2=Slab2_rate)
    2. CMR tier:  >= slab2 target → use r2; >= slab1 target → use r1; else → 0
       The rate ENCODES the CMR tier — no separate cmr_mult or cross 2D table.
    3. Both Achievers (PCDV hit + CMR hit) → per_txn × prod × 1.25
       Only CMR (PCDV not hit, CMR hit) → lowest_slab_rate × prod × 0.50
       PCDV hit, CMR not hit → Base = 0
       Neither → Base = 0
    4. × CMR+1 multiplier (>35%→1.2, 25-35%→1.0, <25%→0.5)
    5. × Booster (SPS: if ext_tat<1 AND 60D<10%)
    """
    cmr_pct_v = cmr_pct * 100 if cmr_pct <= 1 else cmr_pct

    # Individual CMR slab targets (per-employee, from email/config)
    _cmr_slab1 = float(emp_cmr_slab1) if emp_cmr_slab1 is not None else S.get("rm_cmr_slab1", 60)
    _cmr_slab2 = float(emp_cmr_slab2) if emp_cmr_slab2 is not None else S.get("rm_cmr_slab2", 65)

    # ── PCDV slab → (r1, r2) rates ──────────────────────────────────────────
    slabs = S.get("rm_slabs", [])
    if not slabs:
        slabs = [(2900, 1250, 1500), (2700, 1000, 1200), (2500, 750, 900)]

    r1, r2 = 0, 0
    _pcdv_hit = False
    for thresh, _r1, _r2 in sorted(slabs, reverse=True):
        if pcdv >= thresh:
            r1, r2, _pcdv_hit = _r1, _r2, True
            break

    # ── Select per_txn based on CMR tier ──────────────────────────────────
    _cmr_slab2_hit = cmr_pct_v >= _cmr_slab2
    _cmr_slab1_hit = cmr_pct_v >= _cmr_slab1
    _cmr_hit = _cmr_slab1_hit  # either slab qualifies as "CMR achieved"

    if _cmr_slab2_hit:
        per_txn = r2   # top rate
    elif _cmr_slab1_hit:
        per_txn = r1   # base rate
    else:
        per_txn = 0    # CMR not achieved

    # per_txn_eff for display (same as per_txn — no separate cmr_mult)
    per_txn_eff = per_txn

    # ── Both Achievers / Only CMR / Zero ────────────────────────────────────
    _ba_note = ""
    prod = float(prod_raw or 0)
    if S.get("both_achievers_on", False):
        if _pcdv_hit and _cmr_hit:
            # Both hit → 125%
            raw_base = per_txn * prod * S.get("both_achievers_pct", 1.25)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and not _pcdv_hit:
            # Only CMR (PCDV not hit, CMR hit) → 50% of lowest slab rate for CMR tier
            _lowest = (slabs[-1][2] if _cmr_slab2_hit else slabs[-1][1]) if slabs else 0
            raw_base = _lowest * prod * S.get("cmr_only_pct", 0.50)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"
        else:
            # PCDV hit but CMR not hit, OR neither hit → 0
            raw_base = 0
    else:
        raw_base = per_txn * prod

    # ── CMR+1 (MDC-1 next-month renewal) multiplier ─────────────────────────
    cp1 = cmr_plus1_pct * 100 if cmr_plus1_pct <= 1 else cmr_plus1_pct
    if raw_base >= 1:
        if cp1 > 35:    ak = raw_base * 1.20
        elif cp1 >= 25: ak = raw_base * 1.00
        else:           ak = raw_base * 0.50
    else:
        ak = 0.0

    # ── SPS Booster ──────────────────────────────────────────────────────────
    if is_sps and float(ext_tat or 99) < 1 and float(d60 or 100) < 10 and ak >= 1:
        total = round(ak * 1.20, 0)
        _boost_note = " | Boost:120%"
    else:
        total = round(ak, 0)
        _boost_note = ""

    notes = (f"CSD RM | PCR:{pcr:.0f} | CMR:{cmr_pct_v:.0f}% | MDC1:{mdc1_cmr_pct*100 if mdc1_cmr_pct<=1 else mdc1_cmr_pct:.0f}% | "
             f"PerTxn:{per_txn_eff} | Prod:{prod_raw:.1f} | "
             f"CMR+1:{cp1:.0f}% | SPS:{is_sps}{_ba_note}{_boost_note} | Total:{total:.0f}")
    return total, notes



def calc_kcd_sam(pcr_val, pcdv_val, net_dv, net_coll, txn_prod_raw,
                 cmr_pct, ss_cmr_pct, ss_sent, btl_sales,
                 team, location, vintage,
                 client_a, listing_c, catalog_c, collection_target, S, l1_count=4,
                 cmr_col_val=1):
    """
    KCD Sr. Account Manager (L2) incentive -- exact FSF KCD-SAM formula.

    Two types based on team:
    TYPE A  Regular / HVRI / ROI / Nagpur:
       Per-txn threshold uses PCR (net collection / client-A)
       Incremental = (Net_DV - Highest_Coll) * rate%  when PCR > threshold
       Highest Collection = Client-A * 32000
    TYPE B  Listing / Catalog:
       Per-txn threshold uses PCR% (PCR / PCR_Target)
       Incremental = (Net_DV - Collection_Target) * 0.65%  when PCR% > 140%
       Highest Collection = Client-A * 18000
       Collection Target = Listing*8500 + Catalog*48000

    Productivity: RAW total weekly productivity (not divided by L1 count).
    SS+ multiplier: Sent>=3 -> 100% or 50%; Sent<3 -> no penalty (AY unchanged).
    """
    team_up = str(team).upper()
    loc_up  = str(location).upper()
    is_hvri    = any(c in loc_up for c in ["HYDERABAD","VASHI","RAIPUR","INDORE"]) or "HVRI" in team_up
    is_roi     = "ROI" in team_up
    is_nagpur  = "NAGPUR" in team_up or "PHARMA" in team_up
    is_listing = "LISTING" in team_up
    is_catalog = "CATALOG" in team_up

    # ── Type B: Listing / Catalog ─────────────────────────────────────────────
    if is_listing or is_catalog:
        # Highest Collection = Client-A * 17000 (April FSF: AA = L*17000)
        highest_coll = float(client_a or 0) * 17000
        # Collection Target from structure file or slab config rates (not hardcoded)
        if not collection_target or collection_target <= 0:
            _lv3 = str(vintage)
            _r3  = S.get("kcd_listing_rates", {})
            _rv3 = _r3.get(_lv3, _r3.get("270D+", {}))
            _bc3 = max(0, float(client_a or 0) - float(listing_c or 0) - float(catalog_c or 0))
            _lc3 = float(listing_c or 0) + float(catalog_c or 0)
            collection_target = (_bc3 * float(_rv3.get("base_rate", 7000))
                                 + _lc3 * float(_rv3.get("listing_rate", 22000)))
        pcr_target = (collection_target / client_a) if client_a > 0 else 0
        pcr_pct_val = (pcr_val / pcr_target * 100) if pcr_target > 0 else 0

        # Per-txn: threshold is PCR% (95%/120%/140%) and CMR%
        # FSF AX row7: IF(PCR%>=140% AND CMR>=80%,1800, IF(>=140% AND >=72%,1500,
        #               IF(>=120% AND >=80%,1500, IF(>=120% AND >=72%,1250,
        #               IF(>=95% AND >=80%,1200, IF(>=95% AND >=72%,1000, 0)))))
        slabs = S.get("kcd_sam_listing" if is_listing else "kcd_sam_catalog", [])
        is_cmr80 = cmr_pct >= 80
        per_txn = 0
        if cmr_col_val > 0:   # col=0 means CMR not achieved → per_txn stays 0
            for (thresh_pct, r1, r2) in sorted(slabs, reverse=True):
                if pcr_pct_val >= thresh_pct:
                    per_txn = r2 if is_cmr80 else r1
                    break

        # Incremental = IF(PCR% > 140%, (Net_DV - CT) * SAM_incr_rate, 0)
        incr_rate = next((float(r.get("Incr_Rate_%",0.65))/100
                          for r in S.get("kcd_sam_incr",[])
                          if str(r.get("Team","")).upper() in
                          ("LISTING" if is_listing else "CATALOG")),
                         S.get("kcd_sam_incr_rate", 0.0065))
        incremental = round(max(0, net_dv - collection_target) * incr_rate, 0) \
                      if pcr_pct_val > 140 else 0

        # BTL (Base-to-Listing): FSF AP = btl_sales / L1_count, threshold 1 or 2
        # FSF BA = IF(AP>=2,(AY+AQ)*1.2, IF(AP>=1,AY+AQ, 0)) where AQ=incremental
        # AY already includes AQ; BA adds AQ again -- this is exact FSF behaviour
        _btl_per_l1 = float(btl_sales or 0) / max(1, int(l1_count or 1))
        _ay = per_txn * float(txn_prod_raw or 0) + incremental   # AY = (AX*AJ) + AQ
        if is_catalog:
            if _btl_per_l1 >= 2:
                base_before_ss = round((_ay + incremental) * 1.2, 0)
            elif _btl_per_l1 >= 1:
                base_before_ss = round(_ay + incremental, 0)
            else:
                base_before_ss = 0   # must have >=1 BTL/L1 sale to earn
        else:
            base_before_ss = round(_ay, 0)   # Listing: no BTL mult

        # SS+ mult
        if ss_sent >= 3:
            ss_mult = 1.0 if ss_cmr_pct >= S.get("kcd_ss_threshold", 72) else 0.5
        else:
            ss_mult = 1.0
        total = round(base_before_ss * ss_mult, 0)

        # Both Achievers / Only CMR (KCD Listing/Catalog: "DV+CMR" per PPT)
        _ba_note = ""
        if S.get("both_achievers_on", False):
            _dv_hit  = per_txn > 0
            _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
            if _dv_hit and _cmr_hit:
                total = round(total * S.get("both_achievers_pct", 1.25), 0)
                _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
            elif _cmr_hit and not _dv_hit:
                _lowest_r = (slabs[-1][2] if ss_cmr_pct >= 80 else slabs[-1][1]) if slabs else 0
                total = round(_lowest_r * float(txn_prod_raw or 0) * ss_mult * S.get("cmr_only_pct", 0.50), 0)
                _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

        notes = (f"KCD SAM {'Listing' if is_listing else 'Catalog'} {vintage} | "
                 f"PCR%:{pcr_pct_val:.1f}% | Rs{per_txn}/txn*{txn_prod_raw:.1f} | "
                 f"Incr:{incremental:.0f} | SS+:{ss_mult}{_ba_note}")
        return total, notes

    # ── Type A: Regular / HVRI / ROI / Nagpur ────────────────────────────────
    # Highest Collection = Client-A * 17000 (April FSF KCD-SAM: AA = L*17000)
    highest_coll = float(client_a or 0) * 17000

    # Per-txn: threshold is PCDV (per PPT slides 14-17: "PCDV" column heading)
    # NOT PCR — SAM Type A uses the same PCDV thresholds as KCD Exec L1
    if is_nagpur:
        slabs = S.get("kcd_sam_nagpur", [])
    elif is_hvri:
        slabs = S.get("kcd_sam_hvri", [])
    elif is_roi:
        slabs = S.get("kcd_sam_roi", [])
    else:
        slabs = S.get("kcd_sam_regular", [])

    is_cmr80 = cmr_pct >= 80
    per_txn = 0
    if cmr_col_val > 0:   # col=0 = CMR not achieved
        for (thresh_pcdv, r1, r2) in sorted(slabs, reverse=True):
            if pcdv_val >= thresh_pcdv:          # ← PCDV not PCR
                per_txn = r2 if is_cmr80 else r1
                break

    # Incremental: (Net_DV - Highest_Coll) * rate% when PCDV > highest slab threshold
    _team_key = ("NAGPUR" if is_nagpur else "HVRI" if is_hvri else
                 "ROI" if is_roi else "REGULAR")
    _incr_rec = next((r for r in S.get("kcd_sam_incr",[])
                      if str(r.get("Team","")).upper() == _team_key), {})
    incr_thresh_pcdv = float(_incr_rec.get("Incr_Threshold_PCDV", 0) or
                              _incr_rec.get("Incr_Threshold_PCR", 0) or 0)
    incr_rate        = float(_incr_rec.get("Incr_Rate_%", 0.65) or 0.65) / 100
    incremental = 0.0
    if incr_thresh_pcdv > 0 and pcdv_val > incr_thresh_pcdv and net_dv > highest_coll:
        incremental = round((net_dv - highest_coll) * incr_rate, 0)

    # Base = per_txn * raw_wk_productivity + incremental
    base_before_ss = round(per_txn * float(txn_prod_raw or 0) + incremental, 0)

    # SS+ mult: SS sent >= 3 and cmr < 72% → 50% penalty; else no penalty
    if ss_sent >= 3:
        ss_mult = 1.0 if ss_cmr_pct >= S.get("kcd_ss_threshold", 72) else 0.5
    else:
        ss_mult = 1.0
    total = round(base_before_ss * ss_mult, 0)

    # Both Achievers / Only CMR
    _ba_note = ""
    if S.get("both_achievers_on", False):
        _pcdv_hit = per_txn > 0
        _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
        if _pcdv_hit and _cmr_hit:
            total = round(total * S.get("both_achievers_pct", 1.25), 0)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and not _pcdv_hit:
            _lowest_r = (slabs[-1][2] if is_cmr80 else slabs[-1][1]) if slabs else 0
            total = round(_lowest_r * txn_prod_raw * ss_mult * S.get("cmr_only_pct", 0.50), 0)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

    notes = (f"KCD SAM {'Nagpur' if is_nagpur else 'HVRI' if is_hvri else 'ROI' if is_roi else 'Regular'}"
             f" {vintage} | PCDV:{pcdv_val:.0f} | Rs{per_txn}/txn*{txn_prod_raw:.1f} | "
             f"HC:{highest_coll:.0f} | Incr:{incremental:.0f} | SS+:{ss_mult}{_ba_note}")
    return total, notes
def calc_kcd_roi(pcdv, txn_count, cmr_col_val, vintage,
                 ss_cmr_pct, ss_sent, S, collection_target=0, metric_label="PCDV"):
    """KCD ROI incentive — same rates as Regular but lower PCDV thresholds (8K/11K/14K)."""
    slabs = {"270D+":   S.get("kcd_roi_270_slabs",    S.get("kcd_270_slabs",   [])),
             "91-270D": S.get("kcd_roi_91_270_slabs", S.get("kcd_91_270_slabs",[]))}.get(
        vintage, S.get("kcd_0_90_slabs", []))
    _, per_txn = pcdv_slab(pcdv, slabs, cmr_col_val)
    ss_mult = 0.5 if (ss_sent >= 3 and ss_cmr_pct < S.get("kcd_ss_threshold", 72)) else 1.0
    base = per_txn * txn_count * ss_mult

    # Both Achievers / Only CMR (KCD ROI PPT: "Both Achievers (PCDV+CMR) → 125%")
    _ba_note = ""
    if S.get("both_achievers_on", False):
        _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
        if per_txn > 0 and _cmr_hit:
            base = round(base * S.get("both_achievers_pct", 1.25), 0)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and per_txn == 0:
            _lowest_r = (slabs[-1][2] if cmr_col_val == 2 else slabs[-1][1]) if slabs else 0
            base = round(_lowest_r * txn_count * ss_mult * S.get("cmr_only_pct", 0.50), 0)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

    return round(base, 0),            f"KCD ROI {vintage} | {metric_label}:{round(pcdv)} | ₹{per_txn}/txn×{txn_count} | SS+:{ss_mult}{_ba_note}"


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
        slabs = S.get("kcd_nagpur_slabs", [])
    elif any(c in loc for c in ["HYDERABAD", "VASHI", "RAIPUR", "INDORE"]):
        slabs = S.get("kcd_hvri_slabs", [])
    else:
        slabs = {"270D+": S.get("kcd_270_slabs", []),
                 "91-270D": S.get("kcd_91_270_slabs", [])}.get(
            vintage, S.get("kcd_0_90_slabs", []))
    _, per_txn = pcdv_slab(pcdv, slabs, cmr_col_val)

    # SS+ penalty: only when ss_sent >= 3 AND ss_cmr < 70%
    # ss_sent <= 2 → no penalty (not enough data to penalise)
    # SS+ CMR gate per FAQ Q5: for <4 sent, use minimum received counts
    _ss_thr = S.get("kcd_ss_threshold", 72)
    if ss_sent == 0:   ss_mult = 1.0
    elif ss_sent == 1: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 2: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 3: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 2 else 0.5
    else:              ss_mult = 1.0 if ss_cmr_pct >= _ss_thr else 0.5  # sent >=4: use %

    base = per_txn * txn_count * ss_mult

    # Both Achievers (May): PCDV slab hit + CMR (SS+) hit → 125%; Only CMR → 50%
    _ba_note = ""
    if S.get("both_achievers_on", False):
        _pcdv_hit = per_txn > 0
        _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
        if _pcdv_hit and _cmr_hit:
            base = round(base * S.get("both_achievers_pct", 1.25), 0)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and not _pcdv_hit:
            # Only CMR: 50% of lowest slab rate for employee's CMR column
            _lowest_r = (slabs[-1][2] if cmr_col_val == 2 else slabs[-1][1]) if slabs else 0
            base = round(_lowest_r * txn_count * ss_mult * S.get("cmr_only_pct", 0.50), 0)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

    return round(base, 0), \
           f"KCD Regular {vintage} | {metric_label}:{round(pcdv)} | ₹{per_txn}/txn×{txn_count} | SS+:{ss_mult}{_ba_note}"


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
        # Use kcd_listing_rates from slab config (configurable, not hardcoded)
        _lv = str(vintage)
        _r  = S.get("kcd_listing_rates", {})
        _rv = _r.get(_lv, _r.get("270D+", {}))
        collection_target = (base_clients * float(_rv.get("base_rate", 7000))
                             + list_clients * float(_rv.get("listing_rate", 22000)))
    if collection_target <= 0:
        return 0, "KCD Listing -- target=0"
    achv    = (net_dv / collection_target) * 100
    if cmr_col_val == 0:
        per_txn = 0   # CMR not achieved → no per-txn incentive
    else:
        per_txn = next((r2 if cmr_col_val == 2 else r1
                        for t, r1, r2 in S.get("kcd_listing_slabs", []) if achv >= t), 0)
    incr    = max(0, net_dv - collection_target) * S.get("kcd_incr_rate", 0.014)
    # SS+ CMR gate per FAQ Q5: for <4 sent, use minimum received counts
    _ss_thr = S.get("kcd_ss_threshold", 72)
    if ss_sent == 0:   ss_mult = 1.0
    elif ss_sent == 1: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 2: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 3: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 2 else 0.5
    else:              ss_mult = 1.0 if ss_cmr_pct >= _ss_thr else 0.5  # sent >=4: use %
    base = per_txn * txn_count * ss_mult

    # Both Achievers (May): DV target + CMR → 125%; Only CMR → 50%
    _ba_note = ""
    if S.get("both_achievers_on", False):
        _dv_hit  = per_txn > 0
        _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
        if _dv_hit and _cmr_hit:
            base = round(base * S.get("both_achievers_pct", 1.25), 0)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and not _dv_hit:
            _min_rate = min((r1 for _, r1, _ in S.get("kcd_listing_slabs", [(0,0,0)]) if r1 > 0), default=0)
            base = round(_min_rate * txn_count * ss_mult * S.get("cmr_only_pct", 0.50), 0)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

    return round(base, 0), \
           f"KCD Listing {vintage} | Achv:{round(achv,1)}% | ₹{per_txn}/txn×{txn_count} | SS+:{ss_mult}{_ba_note}"


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
        # Use kcd_listing_rates from slab config (configurable, not hardcoded)
        _lv2 = str(vintage)
        _r2  = S.get("kcd_listing_rates", {})
        _rv2 = _r2.get(_lv2, _r2.get("270D+", {}))
        collection_target = (base_clients * float(_rv2.get("base_rate", 7000))
                             + list_clients * float(_rv2.get("listing_rate", 22000)))
    if collection_target <= 0:
        return 0, "KCD Catalog -- target=0"
    achv    = (net_dv / collection_target) * 100
    if cmr_col_val == 0:
        per_txn = 0   # CMR not achieved → no per-txn incentive
    else:
        per_txn = next((r2 if cmr_col_val == 2 else r1
                        for t, r1, r2 in S.get("kcd_catalog_slabs", []) if achv >= t), 0)
    # Incremental computed separately in route_calc (needs PCR% gate not NDV% gate)
    btl_mult = 1.2 if btl_sales >= 2 else (1.0 if btl_sales == 1 else 0.0)
    # SS+ CMR gate per FAQ Q5: for <4 sent, use minimum received counts
    _ss_thr = S.get("kcd_ss_threshold", 72)
    if ss_sent == 0:   ss_mult = 1.0
    elif ss_sent == 1: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 2: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 1 else 0.5
    elif ss_sent == 3: ss_mult = 1.0 if (ss_cmr_pct * ss_sent / 100) >= 2 else 0.5
    else:              ss_mult = 1.0 if ss_cmr_pct >= _ss_thr else 0.5  # sent >=4: use %

    # CATALOG: BTL=0 → 0 incentive (FAQ Q14 confirmed)
    if btl_mult == 0.0:
        return 0.0, f"KCD Catalog {vintage} | Achv:{round(achv,1)}% | BTL=0 → No incentive"

    base = per_txn * txn_count * ss_mult * btl_mult

    # Both Achievers (May): DV target + CMR → 125%; Only CMR → 50%
    _ba_note = ""
    if S.get("both_achievers_on", False):
        _dv_hit  = per_txn > 0
        _cmr_hit  = (cmr_col_val > 0) and (ss_cmr_pct >= S.get("kcd_ss_threshold", 72))
        if _dv_hit and _cmr_hit:
            base = round(base * S.get("both_achievers_pct", 1.25), 0)
            _ba_note = f" | BothAchievers×{S.get('both_achievers_pct',1.25):.0%}"
        elif _cmr_hit and not _dv_hit:
            _min_rate = min((r1 for _, r1, _ in S.get("kcd_catalog_slabs", [(0,0,0)]) if r1 > 0), default=0)
            base = round(_min_rate * txn_count * ss_mult * btl_mult * S.get("cmr_only_pct", 0.50), 0)
            _ba_note = f" | OnlyCMR×{S.get('cmr_only_pct',0.50):.0%}"

    return round(base, 0), \
           f"KCD Catalog {vintage} | Achv:{round(achv,1)}% | ₹{per_txn}/txn×{txn_count} | BTL:{btl_mult} | SS+:{ss_mult}{_ba_note}"


def _spot_bullet(wk_pcdv, table, per_extra=None):
    """Generic bullet spot: table=[(thresh,reward)...] descending, per_extra=(top,unit,size)."""
    base = next((r for t, r in table if wk_pcdv >= t), 0)
    if base and per_extra:
        top, unit, size = per_extra
        if wk_pcdv > top:
            base += int((wk_pcdv - top) / size) * unit
    return base


def calc_spot_march_csd(weekly_dv, client_c, vintage):
    """
    CSD PCDV Bullet Spot for March (WK1–WK4).
    Weekly PCDV = that week's Deal Value / Client-C.
    WK3/WK4 only apply to 90+ vintage (SPS/270D+/91-270D).
    """
    if not client_c or client_c <= 0:
        return 0
    is_90plus = vintage in ("91-270D", "270D+", "SPS")
    tables = {
        1: ([(2000,4100),(1500,3100),(1000,2100)], None),
        2: ([(2500,4100),(2000,3100),(1200,2100)], None),
        3: ([(2500,4100),(2000,3100),(1500,2100)], (2500,750,1000)),
        4: ([(5500,4100),(4500,3100),(3200,2100)], (5500,750,1000)),
    }
    total = 0
    for wk, dv in weekly_dv.items():
        if wk in (3, 4) and not is_90plus:
            continue
        wk_pcdv = dv / client_c
        tbl, extra = tables[wk]
        total += _spot_bullet(wk_pcdv, tbl, extra)
    return int(total)


def calc_spot_march_kcd(weekly_dv, client_a, team, location, vintage):
    """
    KCD PCDV Bullet Spot for March (WK1–WK4).
    Weekly PCDV = that week's Deal Value / Client-A.
    Routes to the right table by team and location.
    Delhi Listing/Catalog tables apply only WK3-4.
    """
    if not client_a or client_a <= 0:
        return 0
    team_up = str(team).upper()
    loc_up  = str(location).upper()
    is_delhi = "DELHI" in loc_up or "NCR" in loc_up or "PEERAGARHI" in loc_up or "SHAHDARA" in loc_up
    # Nagpur Pharma uses Regular KCD spot table (not ROI), so exclude NAGPUR from ROI check
    is_roi   = "ROI" in team_up or any(c in loc_up for c in ["HYDERABAD","VASHI","RAIPUR","INDORE"])
    is_listing = "LISTING" in team_up
    is_catalog = "CATALOG" in team_up

    # Table definitions: {wk: ([(thresh,reward),...], per_extra or None)}
    if is_listing and is_delhi:
        tables = {
            1: None, 2: None,
            3: ([(21000,7100),(17000,5100),(14000,3100)], (21000,1000,1000)),
            4: ([(29000,7100),(25000,5100),(21000,3100)], (29000,1000,5000)),
        }
    elif is_catalog and is_delhi:
        tables = {
            1: None, 2: None,
            3: ([(4500,7100),(4000,5100),(3500,3100)], (4500,1000,1000)),
            4: ([(8000,7100),(6500,5100),(5000,3100)], (8000,1000,2000)),
        }
    elif is_roi:
        tables = {
            1: ([(9000,7100),(7000,5100),(5000,3100)], None),
            2: ([(13000,7100),(10000,5100),(6000,3100)], None),
            3: ([(13000,7100),(10000,5100),(7000,3100)], (13000,1000,1000)),
            4: ([(21000,7100),(17000,5100),(13000,3100)], (21000,1000,5000)),
        }
    else:  # Regular KCD / HVRI / 0-90D
        tables = {
            1: ([(11000,7100),(9000,5100),(7000,3100)], None),
            2: ([(15000,7100),(12000,5100),(8000,3100)], None),
            3: ([(15000,7100),(12000,5100),(9000,3100)], (15000,1000,1000)),
            4: ([(25000,7100),(21000,5100),(17000,3100)], (25000,1000,5000)),
        }
    total = 0
    for wk, dv in weekly_dv.items():
        if not tables.get(wk):
            continue
        wk_pcdv = dv / client_a
        tbl, extra = tables[wk]
        total += _spot_bullet(wk_pcdv, tbl, extra)
    return int(total)


def calc_spot_april_csd(nr_upsell_count, S, fnt1_count=0, fnt2_count=0,
                        is_rm=False, monthly_base_inc=0, team_size=1):
    """
    CSD April spot: NR Upsell/AMR productivity based.
    FNT-1 (Apr 1-16): ≥3 prods → ₹1500 + ₹750/txn above 3
    FNT-2 (Apr 20-30): ≥3 prods → ₹2500 + ₹1000/txn above 3
    Uses exact FNT counts when available (from FNT column in receipt).
    Returns (total_spot, fnt1_spot, fnt2_spot).
    """
    _csd_spot_apr = S.get("csd_spot_apr", {})
    if is_rm:
        fnt1_cfg = _csd_spot_apr.get("RM_FNT1", {"min_prod": 3, "base": 2000, "per_txn": 500, "min_val": 2.5})
        fnt2_cfg = _csd_spot_apr.get("RM_FNT2", {"min_prod": 3, "base": 3500, "per_txn": 500, "min_val": 2.5})
    else:
        fnt1_cfg = _csd_spot_apr.get("FNT1", {"min_prod": 3, "base": 1500, "per_txn": 750})
        fnt2_cfg = _csd_spot_apr.get("FNT2", {"min_prod": 3, "base": 2500, "per_txn": 1000})
    fnt1_spot = 0
    fnt2_spot = 0
    # For RM: threshold is per-team-member (count / team_size >= 2.5)
    # Sir's formula: AX = count/team_size, trigger if AX >= 2.5
    _ts = max(1, int(team_size)) if is_rm else 1
    _fnt1_thresh = fnt1_cfg.get("min_val", 2.5) * _ts if is_rm else fnt1_cfg["min_prod"]
    _fnt2_thresh = fnt2_cfg.get("min_val", 2.5) * _ts if is_rm else fnt2_cfg["min_prod"]
    if fnt1_count >= _fnt1_thresh:
        fnt1_spot = fnt1_cfg["base"] + int(fnt1_count - (_ts * fnt1_cfg.get("min_val", 2.5))) * fnt1_cfg["per_txn"]
    if fnt2_count >= _fnt2_thresh:
        _fnt2_excess = int(fnt2_count - (_ts * fnt2_cfg.get("min_val", 2.5))) if is_rm else (fnt2_count - fnt2_cfg["min_prod"])
        _fnt2_raw = fnt2_cfg["base"] + _fnt2_excess * fnt2_cfg["per_txn"]
        # FNT-2 Monthly Base Incentive Multiplier: qualified (base>0)=100%, not=50%
        _fnt2_mult = 1.0 if monthly_base_inc > 0 else 0.5
        fnt2_spot = int(_fnt2_raw * _fnt2_mult)
    spot = fnt1_spot + fnt2_spot
    # Fallback: ONLY when no FNT-period data exists at all (both counts zero/not supplied)
    # If we have actual FNT split counts, don't use the total count fallback
    _has_fnt_data = (fnt1_count > 0 or fnt2_count > 0)
    if spot == 0 and not _has_fnt_data and nr_upsell_count >= fnt2_cfg["min_prod"]:
        spot = fnt2_cfg["base"] + (nr_upsell_count - fnt2_cfg["min_prod"]) * fnt2_cfg["per_txn"]
        fnt2_spot = spot  # attribute to FNT-2 as fallback

    # CSD Productivity Spot gate: Monthly Base Incentive is MANDATORY (PPT)
    # If base incentive = 0, spot = 0 (hard block, not 50%)
    if spot > 0 and monthly_base_inc == 0:
        return 0, 0, 0
    return spot, fnt1_spot, fnt2_spot


def calc_spot_april_kcd(monthly_pcdv, client_a, team, location, vintage, S,
                        fnt1_pcdv=0, fnt2_pcdv=0,
                        pref_ss_count=0, btl_count=0, im_var_count=0,
                        is_l2_sam=False, monthly_base_inc=0):
    """
    KCD April spot: PCDV-based with FNT periods + SS/LS multiplier.

    FNT-1 (Apr 1-16): base + per_1K PCDV after threshold; SS/BTL/Pref mult ≥2→125% (<2→50%)
      L2 SAM FNT-1: higher base (3500 vs 2500), higher per1K (1500), mult ≥1→125%
    FNT-2 (Apr 20-30): higher base + Monthly Base Incentive Multiplier (qualified=100%, not=50%)
      L2 SAM FNT-2: base 6000 vs L1 4000

    PPT thresholds by team (L1 / L2):
      Regular/ROI 0-90D: 4000 / same
      Regular/ROI 90+:   6000 / 4000 (ROI SAM uses 4000 threshold)
      Catalog 0-90D:     2500 / same
      Catalog 90+:       3500 / 3500
      Listing 0-90D:     7500 / same
      Listing 90+:       11000 / 11000
    """
    if not client_a or client_a <= 0 or monthly_pcdv <= 0:
        return 0, 0, 0
    team_up = str(team).upper()
    loc_up  = str(location).upper()
    is_0_90    = vintage in ("0-30D", "31-90D")
    is_listing = "LISTING" in team_up
    is_catalog = "CATALOG" in team_up
    is_roi     = "ROI" in team_up or any(c in loc_up for c in ["HYDERABAD","VASHI","RAIPUR","INDORE"])

    _apr_rows = S.get("kcd_spot_apr", {})
    def _get_cfg(key_0_90, key_90p):
        k = key_0_90 if is_0_90 else key_90p
        if k in _apr_rows:
            return _apr_rows[k]["fnt1"], _apr_rows[k]["fnt2"]
        return None, None

    # L1 and L2 SAM FNT configs (thresh, base, per_unit, unit_size)
    if is_listing:
        fnt1_c, fnt2_c = _get_cfg("LIST_0_90", "LIST_90p")
        if is_0_90:
            fnt1 = fnt1_c or (7500, 2500, 1000, 1000)
            fnt2 = fnt2_c or (7500, 4000, 1000, 2000)
            fnt1_l2 = fnt1;  fnt2_l2 = fnt2  # 0-90D: no SAM slide, use L1 rates
        else:
            fnt1 = fnt1_c or (11000, 2500, 1000, 1000)
            fnt2 = fnt2_c or (11000, 4000, 1000, 2000)
            fnt1_l2 = (11000, 3500, 1500, 1000)   # SAM FNT-1 slide 12
            fnt2_l2 = (11000, 6000, 1500, 2000)   # SAM FNT-2 slide 8
        _mult_count = pref_ss_count
        _l2_mult_threshold = 1
    elif is_catalog:
        fnt1_c, fnt2_c = _get_cfg("CAT_0_90", "CAT_90p")
        if is_0_90:
            fnt1 = fnt1_c or (2500, 2500, 1000, 1000)
            fnt2 = fnt2_c or (2500, 4000, 1000, 1000)
            fnt1_l2 = fnt1;  fnt2_l2 = fnt2
        else:
            fnt1 = fnt1_c or (3500, 2500, 1000, 1000)
            fnt2 = fnt2_c or (3500, 4000, 1000, 1000)
            fnt1_l2 = (3500, 3500, 1500, 1000)    # SAM FNT-1 slide 9
            fnt2_l2 = (3500, 6000, 1500, 1000)    # SAM FNT-2 slide 6
        _mult_count = btl_count
        _l2_mult_threshold = 1
    elif is_roi:
        fnt1_c, fnt2_c = _get_cfg("ROI_0_90", "ROI_90p")
        fnt1 = fnt1_c or ((4000, 2500, 1000, 1000) if is_0_90 else (4000, 2500, 1000, 1000))
        fnt2 = fnt2_c or ((4000, 4000, 1000, 1000) if is_0_90 else (4000, 4000, 1000, 1000))
        fnt1_l2 = (4000, 3500, 1500, 1000)        # SAM FNT-1 slide 6
        fnt2_l2 = (4000, 6000, 1500, 1000)        # SAM FNT-2 slide 3
        _mult_count = im_var_count
        _l2_mult_threshold = 1
    else:   # Regular KCD
        fnt1_c, fnt2_c = _get_cfg("ROI_0_90", "ROI_90p")
        fnt1 = fnt1_c or ((4000, 2500, 1000, 1000) if is_0_90 else (6000, 2500, 1000, 1000))
        fnt2 = fnt2_c or ((4000, 4000, 1000, 1000) if is_0_90 else (6000, 4000, 1000, 1000))
        fnt1_l2 = ((4000, 3500, 1500, 1000) if is_0_90 else (6000, 3500, 1500, 1000))  # slide 5
        fnt2_l2 = ((4000, 6000, 1500, 1000) if is_0_90 else (6000, 6000, 1500, 1000))  # slide 4
        _mult_count = im_var_count
        _l2_mult_threshold = 1

    # Choose config based on L1 vs L2
    _fnt1 = fnt1_l2 if is_l2_sam else fnt1
    _fnt2 = fnt2_l2 if is_l2_sam else fnt2

    def _bullet(pcdv, cfg):
        thresh, base, per_unit, unit_size = cfg
        if pcdv < thresh:
            return 0
        return base + int((pcdv - thresh) / unit_size) * per_unit

    _pcdv1 = fnt1_pcdv if fnt1_pcdv > 0 else monthly_pcdv / 2
    _pcdv2 = fnt2_pcdv if fnt2_pcdv > 0 else monthly_pcdv / 2
    fnt1_spot = _bullet(_pcdv1, _fnt1)
    fnt2_spot = _bullet(_pcdv2, _fnt2)

    # FNT-2 Monthly Base Incentive Multiplier (qualified=100%, not qualified=50%)
    if fnt2_spot > 0:
        _monthly_qual = monthly_base_inc > 0
        fnt2_spot = int(fnt2_spot * (1.0 if _monthly_qual else 0.5))

    raw_spot = int(fnt1_spot + fnt2_spot)
    if raw_spot == 0:
        return 0, 0, 0

    # SS/LS Upsell Multiplier
    _threshold = _l2_mult_threshold if is_l2_sam else 2
    ss_mult = 1.25 if _mult_count >= _threshold else 0.5
    _total = int(raw_spot * ss_mult)
    _fnt1_final = int(fnt1_spot * ss_mult)
    _fnt2_final = int(fnt2_spot * ss_mult)
    return _total, _fnt1_final, _fnt2_final



def calc_kcd_sam_ilp(net_dv, dv_target, cmr_pct=0, cmr_sent=0, cmr_recd=0,
                     ss_cmr_pct=0, big_ticket_count=0,
                     emp_rate_95=None, S=None):
    """
    KCD SAM-ILP incentive -- exact FSF ' KCD-SAM ILP' formula.

    FSF column chain:
      AG = eligible  = (DV_in_Lac >= Target) i.e. net_dv >= dv_target
      AT = base      = IF(eligible, IF(achv>=120%, DV*r120, IF(>=100%, DV*r100,
                                       IF(>=95%, DV*r95, 0))), 0)
      AV = CMR_mult  = complex count-based logic (see below)
      AW = AT * AV
      AX = IF(big_ticket>=4, AW*1.2, AW)
      AY = IF(SS_CMR%>=75%, AX, AX*0.5)

    Rates are per-employee (from upload file column Rate_%):
      Variant A: r95=0.60%, r100=0.65%, r120=0.75%
      Variant B: r95=0.65%, r100=0.75%, r120=0.80%  (default)
    """
    if S is None:
        S = {}
    if not dv_target or dv_target <= 0:
        return 0, "KCD SAM-ILP -- no DV target set"

    achv_pct = net_dv / dv_target * 100

    # AG: must reach 100% to be eligible
    eligible = (net_dv >= dv_target)

    # Per-employee rates (from upload file, or config default)
    if emp_rate_95 and float(emp_rate_95 or 0) > 0:
        r95  = float(emp_rate_95)
        r100 = r95 + 0.0005
        r120 = r95 + 0.0015
    else:
        ilp_rates = S.get("kcd_sam_ilp_rates", [(120, 0.0080), (100, 0.0075), (95, 0.0065)])
        r_map = {t: r for t, r in ilp_rates}
        r95  = r_map.get(95,  0.0065)
        r100 = r_map.get(100, 0.0075)
        r120 = r_map.get(120, 0.0080)

    # AT: base incentive
    if eligible:
        if   achv_pct >= 120: at = net_dv * r120
        elif achv_pct >= 100: at = net_dv * r100
        elif achv_pct >= 95:  at = net_dv * r95
        else:                 at = 0
    else:
        at = 0

    if at == 0:
        return 0, f"KCD SAM-ILP -- achv {achv_pct:.1f}% (eligible:{eligible})"

    # AV: CMR multiplier -- exact FSF AV formula
    _sent = int(cmr_sent or 0)
    _recd = int(cmr_recd or 0)
    _cpct = float(cmr_pct) * 100 if float(cmr_pct or 0) <= 1 else float(cmr_pct or 0)
    if   (_sent == 3 and _recd >= 2): av = 1.00
    elif (_sent == 2 and _recd >= 1): av = 1.00
    elif (_sent == 1 and _recd == 1): av = 1.00
    elif (_sent == 0 and _recd == 0): av = 1.00  # no clients to renew -> still eligible
    elif _cpct >= 80:                 av = 1.00
    elif _cpct >= 72:                 av = 0.75
    else:                             av = 0.00

    aw = round(at * av, 0)

    # AX: Big Ticket (>=4 deals of 10L+)
    ax = round(aw * 1.2 if int(big_ticket_count or 0) >= 4 else aw, 0)

    # AY: SS+ CMR multiplier
    _ss = float(ss_cmr_pct) * 100 if float(ss_cmr_pct or 0) <= 1 else float(ss_cmr_pct or 0)
    ay = round(ax if _ss >= 75 else ax * 0.5, 0)

    notes = (f"KCD SAM-ILP | Achv:{achv_pct:.1f}% | "
             f"r95:{r95*100:.2f}%/r100:{r100*100:.2f}%/r120:{r120*100:.2f}% | "
             f"CMR_mult:{av:.0%}(sent={_sent},recd={_recd}) | "
             f"BT:{int(big_ticket_count or 0)} | SS+:{_ss:.0f}%")
    return int(ay), notes


def calc_mcats_renewal(im_star_amr_count, S, is_l2=False):
    """KCD 'More MCATs on Renewals' spot. Rates and min count from Scheme_Params."""
    _min = int(S.get("mcats_min_count", 2))
    if im_star_amr_count <= _min:
        return 0
    rate = int(S.get("mcats_l2_rate", 500) if is_l2 else S.get("mcats_l1_rate", 1000))
    return (im_star_amr_count - _min) * rate


def calc_spot_kcd(pcdv, spot_key, mult_met, S):
    _kcd_spot_dict = S.get("kcd_spot", {})
    cfg = _kcd_spot_dict.get(spot_key, {}) if _kcd_spot_dict else {}
    if not cfg or pcdv < cfg.get("thresh", 0):
        return 0
    raw = cfg.get("base", 0) + max(0, int((pcdv - cfg.get("thresh", 0)) / 1000)) * cfg.get("per1k", 0)
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
    """Load xlsx or xlsb files from raw bytes. Auto-detects note rows in enriched files."""
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else "xlsx"
    buf = io.BytesIO(file_bytes)
    try:
        if ext == "xlsb":
            df = pd.read_excel(buf, engine="pyxlsb")
        else:
            # Try header=0 first; if first cell looks like a note (long string), use header=1
            df0 = pd.read_excel(buf, engine="openpyxl", header=0, nrows=2)
            first_cell = str(df0.columns[0]).strip()
            if len(first_cell) > 50 or first_cell.lower().startswith("receipt"):
                # Row 0 is a note/title — real headers are in row 1
                buf.seek(0)
                df = pd.read_excel(buf, engine="openpyxl", header=1)
            else:
                buf.seek(0)
                df = pd.read_excel(buf, engine="openpyxl", header=0)
        df.columns = [str(c).strip() for c in df.columns]
        # Drop fully empty columns
        df = df.loc[:, df.columns.astype(str).str.strip() != ""]
        df = df.loc[:, ~df.columns.astype(str).str.lower().str.startswith("unnamed")]
        return df
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
    Filter receipt file:
    - EXCLUDE rows where B/C = Bounced or Cancelled
    - INCLUDE both Status=Cleared AND Status=Pending (Pending not yet bounced/cancelled counts)
    """
    df = df.copy()
    # ── B/C filter: remove Bounced / Cancelled rows ──────────────────────────
    _bc_col = find_col(df, ["B/C", "BC", "B_C", "Bounce/Cancel"])
    if _bc_col:
        _bc_vals = df[_bc_col].astype(str).str.strip().str.upper()
        df = df[~_bc_vals.isin(["BOUNCED", "CANCELLED", "CANCELED", "BOUNCE", "CANCEL"])]

    # ── Status filter: keep CLEARED and PENDING (exclude blanks/unknown) ─────
    status_col = find_col(df, ["Status", "STATUS", "PAYMENT STATUS", "Payment Status"])
    if status_col:
        _status_vals = df[status_col].astype(str).str.upper().str.strip()
        valid = _status_vals.isin(["CLEARED", "PENDING"])
        valid_rows = df[valid]
        if len(valid_rows) > 0:
            df = valid_rows
        else:
            unique_vals = _status_vals.unique()[:8]
            st.warning(
                f"⚠️ Receipt file: no Cleared/Pending rows in '{status_col}'. "
                f"Found: {list(unique_vals)}. Using all rows.",
                icon="⚠️"
            )

    # ── NACH balance payment filter ───────────────────────────────────────────
    prod_col = find_col(df, ["Prod", "Product", "PRODUCT"])
    if "MODE" in df.columns and prod_col:
        nach = (df["MODE"].astype(str).str.upper().str.contains("NACH", na=False)) & \
               (df[prod_col].astype(str).str.upper().str.contains("BALANCE|BL", na=False))
        df = df[~nach]
    return df


def build_emp_list(receipt_df):
    # Flexible Employee ID column — try multiple names
    eid_src = next((c for c in ["Sales Exec ID","EMP ID","Emp ID","L1 ID","Employee ID"]
                    if c in receipt_df.columns), None)
    if eid_src is None:
        return pd.DataFrame(columns=["Employee ID"])

    cols  = {eid_src: "Employee ID",
             "Manager": "L2 Name", "HOD - 1": "L3 Name", "HOD": "L4 Name",
             "Location": "Location", "Vertical": "Vertical"}
    avail = {k: v for k, v in cols.items() if k in receipt_df.columns}
    emp   = receipt_df[list(avail.keys())].rename(columns=avail).drop_duplicates("Employee ID")
    emp["Employee ID"] = emp["Employee ID"].astype(str).str.split('.').str[0].str.strip()
    return emp.reset_index(drop=True)


def get_transactions(receipt_df, refund_df, renewal_df, emp_id, client_a=0,
                     is_l2=False, emp_name=""):
    """
    Fetch all transactions for one employee.
    For CSD L2 (Rel Mgr): receipt filtered by Manager Id col (not EMP ID),
    matching FSF Rel Mgr-CSD formula using AS col (L2 ID) in FSF receipt.
    """
    # Use string comparison to handle both int and string EMP IDs across files
    eid_str   = str(int(float(emp_id))) if str(emp_id).replace(".","").isdigit() else str(emp_id)
    eid       = int(eid_str) if eid_str.isdigit() else eid_str

    # Detect employee ID column once (flexible — works with enriched receipt too)
    _eid_col  = find_col(receipt_df, ["Sales Exec ID","EMP ID","Emp ID","L1 ID","Employee ID"])

    # For CSD L2 Rel Mgr: use HOD-3 / L2-ID column to get ALL team receipts
    if is_l2:
        _mgr_col = find_col(receipt_df, ["Old Sales HOD-3 ID", "Manager Id"])
        if _mgr_col:
            _mask = receipt_df[_mgr_col].astype(str).str.split(".").str[0].str.strip() == eid_str
            rec = receipt_df[_mask]
            rec = receipt_df[_mask]
        elif _eid_col:
            rec = receipt_df[receipt_df[_eid_col].astype(str).str.split(".").str[0].str.strip() == eid_str]
        else:
            rec = receipt_df.iloc[0:0]  # empty
    else:
        if _eid_col:
            rec = receipt_df[receipt_df[_eid_col].astype(str).str.split(".").str[0].str.strip() == eid_str]
        else:
            rec = receipt_df.iloc[0:0]  # empty — no ID column found
    # --- Collection amount (WT AMT / WT Amt(A)) ---
    _wt_col   = find_col(receipt_df, ["WT AMT","WT Amt(A)","WT_AMT","Receipt Amount","Total Amount"])
    total_dv  = rec[_wt_col].fillna(0).sum() if _wt_col else 0.0
    txn_count = len(rec)

    # Deal Value (WT) = deal value column (different from collection)
    dv_col    = find_col(receipt_df, ["Deal Val (WT)", "Deal Val (WOT)", "Deal Value (WT)", "Deal Value", "DealVal_WT"])
    gross_deal_val = rec[dv_col].fillna(0).sum() if dv_col else 0.0
    _prod_col = find_col(receipt_df, ["Prod", "Product", "PRODUCT"])
    prods     = rec[_prod_col].fillna("").tolist() if _prod_col else []
    # Productive rows -- use file's Productivity column if present (1.0=full, 0.5=insta)
    # New receipt format pre-computes this; old format uses enrich_receipt output
    if "Productivity" in rec.columns:
        _prod_vals = rec["Productivity"].fillna(0).astype(float)
        prod_rows  = rec[_prod_vals > 0]
        if "Service_Tier" in prod_rows.columns:
            svc_tiers = prod_rows["Service_Tier"].tolist()
        elif "Service" in prod_rows.columns:
            # Enriched receipt has Service string (e.g. "MDC-Annual||TS-1") but not int tier
            def _svc_to_tier(s):
                s = str(s)
                if "MDC-Annual" in s or "TS-1" in s: return 1
                if "MDC-MYR" in s or "TS-2" in s:   return 2
                if "TS-3" in s or "Maxi-2" in s:    return 3
                return 0
            svc_tiers = [_svc_to_tier(v) for v in prod_rows["Service"].tolist()]
            svc_tiers = [t for t in svc_tiers if t > 0]  # drop 0s (non-tier rows)
        else:
            svc_tiers = []
        # Count insta rows by product name (Productivity=0 in file, not 0.5)
        _insta_prod_mask = rec[_prod_col].isin(INSTA_PRODUCTS) if _prod_col else pd.Series(False, index=rec.index)
        insta_cnt_receipt    = int(_insta_prod_mask.sum()) or int((_prod_vals == 0.5).sum())

        prod_score_receipt     = float(_prod_vals.sum())
        prod_score_receipt_int = int((_prod_vals == 1.0).sum())
        _date_col = find_col(receipt_df, ["Entry Date", "Receipt Date", "Date"])
        weekly_prod_counts = {}
        if _date_col and len(prod_rows) > 0:
            _dates = pd.to_datetime(prod_rows[_date_col], errors='coerce')
            _weeks = _dates.apply(lambda d: (1 if d.day<=7 else 2 if d.day<=14
                                             else 3 if d.day<=21 else 4)
                                  if pd.notna(d) else 0)
            for w, cnt in _weeks.value_counts().items():
                if w > 0:
                    weekly_prod_counts[int(w)] = int(cnt)
    else:
        prod_rows              = rec
        svc_tiers              = []
        insta_cnt_receipt    = 0
        prod_score_receipt     = txn_count
        prod_score_receipt_int = txn_count
        weekly_prod_counts     = {}
    ref_id_col = find_col(refund_df, ["Sales Ex. ID", "Sales Exec ID", "EMP ID"])
    if is_l2:
        # For ALL L2 employees: sum L1 refunds via L2 NAME column in refund file
        _ref_l2_name_col = find_col(refund_df, ["L2 NAME", "L2 Name", "L2Name"])
        if _ref_l2_name_col and emp_name:
            ref = refund_df[refund_df[_ref_l2_name_col].astype(str).str.strip() == emp_name.strip()]
        elif ref_id_col:
            ref = refund_df[refund_df[ref_id_col].astype(str).str.split('.').str[0].str.strip() == eid_str]
        else:
            ref = refund_df.iloc[0:0]
    else:
        ref = refund_df[refund_df[ref_id_col].astype(str) == eid_str] if ref_id_col else refund_df.iloc[0:0]
    _ref_wt_col = find_col(refund_df, ["WT Amount","WT AMT","WT_AMT","Refund Amount","Amount"])
    _reason_col = find_col(refund_df, ["Reason","REASON","Refund Reason"])
    if _ref_wt_col and len(ref) > 0 and _ref_wt_col in ref.columns:
        _wt_vals = ref[_ref_wt_col].fillna(0).astype(float).copy()
        if _reason_col and _reason_col in ref.columns:
            # "Order verification failed" -> WT Amount x 2 (per scheme rule)
            _ovf_mask = ref[_reason_col].astype(str).str.strip().str.lower().str.contains(
                "order verification failed", na=False)
            _wt_vals[_ovf_mask] = _wt_vals[_ovf_mask] * 2
        total_ref = _wt_vals.sum()
    else:
        total_ref = 0.0
    # Deal Loss is always 0 -- it is a separate manual entry and not derived from the refund file.
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

    # Weekly productivity (AR values) and transaction counts per week (sir's WK-1/2/3/4)
    # Sir's formula: SUMIFS(Receipt.AR, EmpID, Tagged, Vertical, Week=WK-x)
    # AR = 1.0 for regular, 0.5 for Insta → WK columns = weighted productivity per week
    weekly_dv  = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    weekly_txn = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}   # sum of AR values per week (sir's formula)
    _wk_col    = find_col(receipt_df, ["Week", "WEEK"])
    _rcol_w    = find_col(receipt_df, ["Receipt Date", "ReceiptDate", "Entry Date"])
    _dv_col_w  = dv_col
    _wk_map    = {"WK-1":1,"WK-2":2,"WK-3":3,"WK-4":4,"WK1":1,"WK2":2,"WK3":3,"WK4":4}
    # AR (Productivity weight) column
    _ar_col    = find_col(receipt_df, ["Productivity"]) if "Productivity" in receipt_df.columns else None

    if _wk_col and len(rec) > 0:
        _ar_vals = rec[_ar_col].fillna(1.0).astype(float).values if _ar_col and _ar_col in rec.columns else None
        for _wi, _wlabel in enumerate(rec[_wk_col].fillna("").values):
            _wn = _wk_map.get(str(_wlabel).strip().upper())
            if _wn:
                _ar = float(_ar_vals[_wi]) if _ar_vals is not None else 1.0
                weekly_txn[_wn] += _ar  # sum of AR weights (sir's SUMIFS)
                if _dv_col_w and _dv_col_w in rec.columns:
                    weekly_dv[_wn] += float(rec.iloc[_wi].get(_dv_col_w, 0) or 0)
    elif _rcol_w and len(rec) > 0:
        try:
            _rd   = pd.to_numeric(rec[_rcol_w], errors='coerce').fillna(0).astype(int)
            _dv   = rec[_dv_col_w].fillna(0) if _dv_col_w else pd.Series(0, index=rec.index)
            _ar_s = rec[_ar_col].fillna(1.0).astype(float) if _ar_col and _ar_col in rec.columns else pd.Series(1.0, index=rec.index)
            _base = pd.Timestamp('1899-12-30')
            for _x, _v, _ar in zip(_rd.values, _dv.values, _ar_s.values):
                if _x > 0:
                    _dt = _base + pd.Timedelta(days=int(_x))
                    if _dt.year == 2026:
                        _wk = (1 if _dt.day <= 9 else 2 if _dt.day <= 16
                               else 3 if _dt.day <= 23 else 4)
                        weekly_txn[_wk] += float(_ar)
                        weekly_dv[_wk]  += float(_v)
        except Exception:
            pass

    # Per-FNT deal value for KCD PCDV Bullet Spot (April)
    fnt1_dv = 0.0; fnt2_dv = 0.0
    _fnt_col = find_col(receipt_df, ["FNT", "Fortnight"])
    _dv_col  = find_col(receipt_df, ["Deal Val (WOT)","Deal Val","Deal Val (WT)","WT AMT","WT Amt(A)","WT_AMT"])
    if _fnt_col and _dv_col and len(rec) > 0:
        _fnt_vals = rec[_fnt_col].fillna("").astype(str).str.upper().str.strip()
        _dv_vals  = pd.to_numeric(rec[_dv_col], errors='coerce').fillna(0)
        fnt1_dv = float(_dv_vals[_fnt_vals == "FNT-1"].sum())
        fnt2_dv = float(_dv_vals[_fnt_vals == "FNT-2"].sum())
    # Per-client FNT PCDV (for KCD spot threshold comparison)
    # Use same min-50-client rule as base PCDV for KCD spot
    _client_a_eff = max(50, client_a) if client_a > 0 else 50
    fnt1_pcdv = (fnt1_dv / _client_a_eff) if _client_a_eff > 0 else 0
    fnt2_pcdv = (fnt2_dv / _client_a_eff) if _client_a_eff > 0 else 0

    # Per-employee NR Upsell count for CSD Spot incentive
    # Also compute AMR count and FNT-split counts for accurate April spot
    fnt1_prod_count = 0   # productive rows in FNT-1 (CSD spot)
    fnt2_prod_count = 0   # productive rows in FNT-2 (CSD spot)
    pref_ss_count   = 0   # KCD Regular/ROI SS/LS upsell count (for 125%/50% mult)
    btl_count       = 0   # KCD Catalog Base-to-Listing sale count
    im_var_count    = 0   # KCD Listing Pref Star/Leader count

    if "Productivity" in rec.columns and "_is_upsell" not in rec.columns:
        upsell_col_name = find_col(receipt_df, ["Upsell", "UPSELL", "Unique", "UNIQUE"])
        if upsell_col_name:
            wt_col_name = find_col(receipt_df, ["WT AMT","WT Amt(A)","WT_AMT","WTAMT","Receipt Amount"])
            upsell_mask = (rec[upsell_col_name].fillna("").astype(str).str.strip() != "")
            if wt_col_name:
                upsell_mask = upsell_mask & (rec[wt_col_name].fillna(0) > 0)
            nr_upsell_count = int(upsell_mask.sum())
        else:
            nr_upsell_count = 0

        # Use pre-computed NR Upsell/AMR column from enriched receipt if available
        _nr_amr_col = find_col(receipt_df, ["NR Upsell/AMR"])
        if _nr_amr_col and _nr_amr_col in rec.columns:
            _prod2     = rec["Productivity"].fillna(0).astype(float) > 0
            _is_nr_amr = rec[_nr_amr_col].astype(str).str.strip().str.upper() == "YES"
            _spot_q2   = _prod2 & _is_nr_amr
            _date_c2   = find_col(receipt_df, ["Entry Date", "Receipt Date", "Date"])
            _dates_q2  = pd.to_datetime(rec[_date_c2], errors="coerce") if _date_c2 else pd.Series(dtype="datetime64[ns]")
            # Use session_state period_dates if available
            _pd2 = {}
            try:
                import streamlit as _stq; _pd2 = _stq.session_state.get("period_dates", {})
            except: pass
            def _in_period(dates_series, pname, def_range):
                if pname in _pd2:
                    import datetime as _dtp
                    s, e = _pd2[pname]
                    return dates_series.dt.date.between(s, e)
                return dates_series.dt.day.between(def_range[0], def_range[1])
            fnt1_prod_count = int((_spot_q2 & _in_period(_dates_q2, "FNT-1", (1,  16))).sum())
            fnt2_prod_count = int((_spot_q2 & _in_period(_dates_q2, "FNT-2", (17, 31))).sum())
            nr_upsell_count = int(_spot_q2.sum())

        # FNT-based spot counts (April)
        fnt_col = find_col(receipt_df, ["FNT", "Fortnight"])
        amr_col = find_col(receipt_df, ["AMR"])
        prod_col = "Productivity"
        if fnt_col and amr_col:
            _prod = rec[prod_col].fillna(0).astype(float) > 0
            _amr  = rec[amr_col].fillna("").astype(str).str.upper().str.strip() == "YES"
            _fnt  = rec[fnt_col].fillna("").astype(str).str.upper().str.strip()
            fnt1_prod_count = int((_prod & _amr & (_fnt == "FNT-1")).sum())
            fnt2_prod_count = int((_prod & _amr & (_fnt == "FNT-2")).sum())
        # Always derive FNT from Rem+Rnl Remarks (sir's exact spot logic)
        # NR = Rem="Upsell-NR"; AMR = Rem="Renewal" AND Rnl Remarks in CMR set
        _rem_col  = find_col(receipt_df, ["Rem", "REM"])
        _rnl_col  = find_col(receipt_df, ["Rnl Remarks", "RnlRemarks", "Renewal Remarks"])
        _date_col2 = find_col(receipt_df, ["Entry Date", "Receipt Date", "Date"])
        if _rem_col and _date_col2:
            _AMR_VALS = {"CMR", "CMR+1", "CMR+2", "CMR+3"}
            _is_nr  = rec[_rem_col].astype(str).str.strip() == "Upsell-NR"
            if _rnl_col:
                _is_amr = ((rec[_rem_col].astype(str).str.strip() == "Renewal") &
                           (rec[_rnl_col].astype(str).str.strip().isin(_AMR_VALS)))
            else:
                _is_amr = pd.Series(False, index=rec.index)
            _spot_qual = _is_nr | _is_amr
            _dates2    = pd.to_datetime(rec[_date_col2], errors='coerce')
            fnt1_prod_count = int((_spot_qual & (_dates2.dt.day <= 16)).sum())
            fnt2_prod_count = int((_spot_qual & (_dates2.dt.day >= 17)).sum())
            nr_upsell_count = int(_spot_qual.sum())
        elif upsell_col_name:
            _date_col = find_col(receipt_df, ["Entry Date", "Receipt Date", "Date"])
            if _date_col:
                _dates = pd.to_datetime(rec[_date_col], errors='coerce')
                fnt1_prod_count = int((upsell_mask & (_dates.dt.day <= 16)).sum())
                fnt2_prod_count = int((upsell_mask & (_dates.dt.day >= 17)).sum())

        # KCD multiplier counts
        pref_ss_col = find_col(receipt_df, ["Pref SS+", "PrefSS", "SS+"])
        btl_col     = find_col(receipt_df, ["Base to List Sale", "Base to Listing", "BTL"])
        im_col      = find_col(receipt_df, ["IM Varient", "IM Variant", "IM Upsell"])
        if pref_ss_col:
            pref_ss_count = int((rec[pref_ss_col].fillna("").astype(str).str.upper().str.strip() == "YES").sum())
        # BTL (Base-to-Listing) productivity for KCD Catalog:
        # Rows where Base Client Type in {MDC, WS, MDC-TS, IVE}
        # OR Unique col in {IM Star Pro, Preferred Star Pro, Preferred Leader Pro,
        #                   IM Leader Pro, Preferred Star}
        _btl_base_types = {'MDC', 'WS', 'MDC-TS', 'IVE'}
        _btl_unique_prods = {'IM Star Pro', 'Preferred Star Pro', 'Preferred Leader Pro',
                              'IM Leader Pro', 'Preferred Star'}
        _bct_col    = find_col(receipt_df, ["Base Client Type", "Base_Client_Type", "BaseClientType"])
        _unique_col = find_col(receipt_df, ["Unique", "UNIQUE"])
        _bct_mask   = rec[_bct_col].isin(_btl_base_types) if _bct_col else pd.Series(False, index=rec.index)
        _uniq_mask  = rec[_unique_col].isin(_btl_unique_prods) if _unique_col else pd.Series(False, index=rec.index)
        btl_count   = int((_bct_mask & _uniq_mask).sum())  # AND: both criteria must be met
        if im_col:
            im_var_count = int((rec[im_col].fillna("").astype(str).str.upper().str.strip() == "YES").sum())
    else:
        nr_upsell_count = 0

    # IM Star Pro+ count for 28-30 spot (BX="Yes" equivalent)
    im_star_pro_count = 0
    _unique_col_sp = find_col(receipt_df, ["Unique", "UNIQUE"])
    _date_col_sp   = find_col(receipt_df, ["Entry Date", "Receipt Date", "Date"])
    if _unique_col_sp and _date_col_sp and len(rec) > 0:
        try:
            _days_sp = pd.to_datetime(rec[_date_col_sp], errors='coerce').dt.day
            _is_28_30 = _days_sp >= 28
            _is_star_pro = rec[_unique_col_sp].apply(
                lambda v: any(p.upper() in str(v).upper() for p in IM_STAR_PRO_PRODUCTS)
            )
            im_star_pro_count = int((_is_28_30 & _is_star_pro).sum())
        except Exception:
            im_star_pro_count = 0

    # KCD WK-1 Power of Productivity Spot (01-09 May): per-product-type count
    # Only NR Upsell / Upsell on Renewal; must have ≥2 productivity in the week
    wk1_prod_counts = {k: 0 for k in WK1_PRODUCT_CATEGORIES}  # {category: count}
    if _unique_col_sp and len(rec) > 0:
        try:
            _uq_vals = rec[_unique_col_sp].fillna("").astype(str)
            # Date gate: 01-09 May (day <= 9); use _date_col_sp if available
            if _date_col_sp:
                _days_wk1 = pd.to_datetime(rec[_date_col_sp], errors='coerce').dt.day
                _is_wk1   = _days_wk1 <= 9
            else:
                _is_wk1 = pd.Series([True] * len(rec), index=rec.index)
            # Check for NR Upsell / AMR (same gate as nr_upsell_count)
            _nr_mask = _uq_vals.str.upper().str.contains("UPSELL|AMR|NR", na=False)
            _wk1_rec = rec[_is_wk1 & _nr_mask]
            for cat, keywords in WK1_PRODUCT_CATEGORIES.items():
                _cat_mask = _wk1_rec[_unique_col_sp].apply(
                    lambda v: any(kw.upper() in str(v).upper() for kw in keywords)
                )
                wk1_prod_counts[cat] = int(_cat_mask.sum())
        except Exception:
            pass

    # KCD WK-1 per-product type counts (already computed above)
    # Excellent Incentive Spot count: transactions on day 4 of month
    excellent_txn_count = 0
    if _date_col_sp and len(rec) > 0:
        try:
            _exc_days = pd.to_datetime(rec[_date_col_sp], errors='coerce').dt.day
            excellent_txn_count = int((_exc_days == 4).sum())
        except Exception:
            pass

    # Computed Client-C: distinct clients who transacted in the month
    # Used as PCDV denominator for CSD L1 (Calculated Client)
    # Try to find a client/buyer ID column in the receipt
    computed_client_c = 0
    if len(rec) > 0:
        _cid_col = find_col(rec, [
            "Client GLID", "ClientGLID", "Buyer GLID", "BuyerGLID",
            "Client ID", "ClientID", "Buyer ID", "BuyerID",
            "GLID", "glid", "Member ID", "MemberID",
            "Cust ID", "CustID", "Customer ID",
        ])
        if _cid_col:
            computed_client_c = int(rec[_cid_col].dropna().nunique())
        else:
            # No client ID column — use productive receipt count as proxy
            # (each productive receipt ≈ one client transaction)
            computed_client_c = int(prod_score_receipt) if prod_score_receipt else txn_count

    return (net_collection, txn_count, prods,
            rnl_prods, rnl_modes, rnl_count, total_ref, all_rnl_count,
            svc_tiers, insta_cnt_receipt, prod_score_receipt,
            gross_collection, gross_deal_val, deal_loss, net_deal_val,
            nr_upsell_count, weekly_dv, weekly_txn,
            fnt1_prod_count, fnt2_prod_count,
            pref_ss_count, btl_count, im_var_count,
            fnt1_pcdv, fnt2_pcdv,
            weekly_prod_counts, im_star_pro_count,
            wk1_prod_counts, excellent_txn_count,
            computed_client_c, prod_score_receipt_int)


def resolve_emp_name(emp_id, cfg_row, emp_cmr, emp_row):
    """
    Name priority:
      1. L1 column in Renewal file   (most accurate -- actual employee name)
      2. Employee Config file
      3. Receipt file Sales Rep. column
      4. Empty string
    """
    l1_name  = emp_cmr.get("l1_name", "").strip()
    cfg_name = str(cfg_row.get("Employee Name", "")).strip()
    rec_name = str(emp_row.get("Employee Name", "")).strip()  # was Sales Rep. in receipt
    return l1_name or cfg_name or rec_name or ""


def calc_bm_rm_aop(net_deal_val, aop_target, cmr_pct, ss_cmr_pct,
                   vertical, level, S):
    """
    AOP-based incentive for L3 (BM) and L4 (RM) employees.

    CSD BM  : 1.00% of DV × AOP mult × CMR mult; cap 5% DV
    CSD RM  : 0.70% of DV × AOP mult × CMR mult; cap 4% DV
    KCD BM  : 0.50% of DV × AOP mult × CMR mult × SS+ mult; cap 2% DV
    KCD RM  : 0.35% of DV × AOP mult × CMR mult × SS+ mult; cap 2% DV

    CMR eligibility (CSD):
      <53%  → 0%
      53-60% → 50%  60-65% → 100%  65%+ → 120%

    CMR eligibility (KCD):
      <72%  → 0%
      72-75% → 75%  75-80% → 100%  80%+ → 120%

    AOP achievement multiplier:
      <95%    → not eligible (0)
      95-100% → 100%
      100-105%→ 110%
      105-110%→ 120%
      ≥110%   → 130%

    SS+ multiplier (KCD only):
      ≥72% → 100%; <72% → 50%
    """
    if aop_target <= 0 or net_deal_val <= 0:
        return 0.0, "No AOP target or no Deal Value"

    aop_pct = (net_deal_val / aop_target) * 100

    # AOP gate and multiplier — from Scheme_Params
    _aop_min = S.get("AOP_Min_Achievement_%", 95)
    if aop_pct < _aop_min:
        return 0.0, f"AOP {aop_pct:.1f}% < {_aop_min:.0f}% — not eligible"
    elif aop_pct < 100:
        aop_mult = S.get("AOP_Mult_95_100_%", 100) / 100
    elif aop_pct < 105:
        aop_mult = S.get("AOP_Mult_100_105_%", 110) / 100
    elif aop_pct < 110:
        aop_mult = S.get("AOP_Mult_105_110_%", 120) / 100
    else:
        aop_mult = S.get("AOP_Mult_110_Plus_%", 130) / 100

    v_up = str(vertical).upper()
    l_up = str(level).upper()
    is_bm = "BM" in l_up or "L3" in l_up

    if "CSD" in v_up:
        base_rate = S.get("CSD_BM_AOP_Rate_%", 1.00) / 100 if is_bm else S.get("CSD_RM_AOP_Rate_%", 0.70) / 100
        cap_rate  = S.get("CSD_BM_AOP_Cap_%",  5.00) / 100 if is_bm else S.get("CSD_RM_AOP_Cap_%",  4.00) / 100
        cmr_min   = S.get("CSD_BM_CMR_Min_%", 53)
        cmr_s1    = S.get("CSD_BM_CMR_Slab1_%", 60)
        cmr_s2    = S.get("CSD_BM_CMR_Slab2_%", 65)
        cmr_v = cmr_pct * 100 if cmr_pct <= 1 else cmr_pct
        if cmr_v < cmr_min:
            return 0.0, f"CMR {cmr_v:.1f}% < {cmr_min:.0f}% — not eligible"
        elif cmr_v < cmr_s1:
            cmr_mult = 0.50
        elif cmr_v < cmr_s2:
            cmr_mult = 1.00
        else:
            cmr_mult = 1.20
        ss_mult = 1.0
    else:  # KCD
        base_rate = S.get("KCD_BM_AOP_Rate_%", 0.50) / 100 if is_bm else S.get("KCD_RM_AOP_Rate_%", 0.35) / 100
        cap_rate  = S.get("KCD_BM_AOP_Cap_%",  2.00) / 100 if is_bm else S.get("KCD_RM_AOP_Cap_%",  2.00) / 100
        cmr_min   = S.get("KCD_BM_CMR_Min_%", 72)
        cmr_s1    = S.get("KCD_BM_CMR_Slab1_%", 75)
        cmr_s2    = S.get("KCD_BM_CMR_Slab2_%", 80)
        ss_gate   = S.get("KCD_BM_SS_Plus_Min_%", 72)
        cmr_v = cmr_pct * 100 if cmr_pct <= 1 else cmr_pct
        if cmr_v < cmr_min:
            return 0.0, f"CMR {cmr_v:.1f}% < {cmr_min:.0f}% — not eligible"
        elif cmr_v < cmr_s1:
            cmr_mult = 0.75
        elif cmr_v < cmr_s2:
            cmr_mult = 1.00
        else:
            cmr_mult = 1.20
        ss_v = ss_cmr_pct * 100 if ss_cmr_pct <= 1 else ss_cmr_pct
        ss_mult = 1.0 if ss_v >= ss_gate else 0.5

    raw_incentive = net_deal_val * base_rate * aop_mult * cmr_mult * ss_mult
    cap           = net_deal_val * cap_rate
    incentive     = min(raw_incentive, cap)

    notes = (f"{vertical} {'BM' if 'BM' in l_up or 'L3' in l_up else 'RM'} | "
             f"AOP:{aop_pct:.1f}% | DV:{net_deal_val:,.0f} | Rate:{base_rate:.2%} | "
             f"AOPMult:{aop_mult:.0%} | CMR:{cmr_v:.1f}%→{cmr_mult:.0%} | "
             f"SS+:{ss_mult:.0%} | Raw:{raw_incentive:,.0f} | Cap:{cap:,.0f} | "
             f"Final:{incentive:,.0f}")
    return round(incentive, 0), notes


def route_calc(emp_row, cfg_row, cmr_data, net_dv, txn_count, prods,
               rnl_prods, rnl_modes, rnl_count, sb, S, joining_date=None,
               svc_tiers=None, prod_score_receipt=None, mdc1_cmr_pct=None, cmr_plus1_pct=0.0,
               all_cmr_pct=None, all_cmr_sent=0,
               nr_upsell_count=0, net_deal_val=0, collection_target=0,
               vintage_bucket="", designation="", weekly_dv=None,
               cmr_plus1_sent=0, wk1_prod_counts=None, excellent_txn_count=0):
    """
    Main routing -- all fixes applied:
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
    # Use collection_target from cfg_row if not passed directly
    if not collection_target:
        collection_target = float(cfg_row.get("Collection Target", 0) or 0)

    client_cnt = max(float(cfg_row.get("Client Count", 100) or 100),
                     50)   # both CSD and KCD use 50 as minimum client count
    listing_c    = float(cfg_row.get("Listing Clients", 0) or 0)
    catalog_c    = float(cfg_row.get("Catalog Clients",  0) or 0)
    # If listing/catalog client counts not in structure file but team is identified as Listing/Catalog,
    # estimate from team type and client_cnt (all clients treated as listing/catalog type)
    _team_up_lc = str(team).upper()
    if listing_c == 0 and catalog_c == 0:
        if "LISTING" in _team_up_lc:
            listing_c = client_cnt
        elif "CATALOG" in _team_up_lc:
            catalog_c = client_cnt
    pcr_target_v = float(cfg_row.get("PCR Target",       0) or 0)
    # Highest Collection = PCR_Target × Client-A (from structure)
    highest_coll = pcr_target_v * client_cnt if pcr_target_v > 0 else 0
    # Always compute BOTH PCR and PCDV for every employee (CSD and KCD).
    # PCR  = Net Collection / Client count  (collection-based)
    # PCDV = Net Deal Value  / Client count  (deal-value-based)
    # The sidebar toggle selects which one drives the slab lookup.
    # For March the slabs are calibrated to PCR; for April to PCDV.
    use_pcr = sb.get("use_pcr", False)

    # PCR = Net Collection / Client-A (actual clients)
    # PCDV = Net Deal Value / Client-A (deal value based, NOT collection)
    # KCD T&C: "PCDV = Net Deal Value / Client-A" — never fall back to Net Collection for KCD
    dv_for_pcdv = net_deal_val if net_deal_val > 0 else (net_dv if not "KCD" in vertical else 0)
    _client_c_val = float(cfg_row.get("Client-C", 0) or 0)
    _is_csd = "CSD" in vertical

    # PCR denominator: Client-C for CSD (per sir's FSF formula: =Net_Collection/Client_C)
    #                  Client-A for KCD (actual, min 50)
    _pcr_denom  = (_client_c_val if (_is_csd and _client_c_val > 0) else client_cnt)
    _pcr_denom  = _pcr_denom if _pcr_denom > 0 else 1
    pcr_val     = (net_dv / _pcr_denom) if _pcr_denom > 0 else 0

    # PCDV denominator: Client-C for ALL CSD (FSF: Z = Net_DV / L = Client-C)
    #                   Client-A for KCD (KCD uses actual clients)
    _pcdv_denom = (_client_c_val if (_is_csd and _client_c_val > 0) else client_cnt)
    pcdv_val    = (dv_for_pcdv / _pcdv_denom) if _pcdv_denom > 0 else 0

    # slab_metric = the metric used for incentive slab lookup (sidebar-controlled)
    slab_metric  = pcr_val if use_pcr else pcdv_val
    metric_label = "PCR"  if use_pcr else "PCDV"
    pcdv = slab_metric   # internal name kept for compatibility with calc functions

    # KCD Highest Collection (HC):
    # Listing/Catalog: HC = base_clients × base_rate + listing_clients × listing_rate
    #                       (base = CA - cat - lst; rates 7k/22k for 91D+, 5k/15k for 0-90D)
    # Regular/HVRI/ROI/Nagpur: HC = max slab threshold × client_cnt
    _is_kcd_sam = str(designation).upper().strip() == "L2" and "KCD" in vertical
    _t_up_hc = str(team).upper()
    _is_lst_cat_hc = ("LISTING" in _t_up_hc or "CATALOG" in _t_up_hc) and "KCD" in vertical
    if _is_lst_cat_hc:
        # PPT Slide 4/5: "Deal Value Target = Base Client × 7K + Listing Client × 22K"
        # "Base Client" = Catalog clients (7000/client for 91D+; 5000 for 0-90D)
        # "Listing Client" = Listing clients (22000/client for 91D+; 15000 for 0-90D)
        _is_new_kcd_hc  = vintage in ("0-30D", "31-90D")
        _cat_rate_hc    = int(S.get("KCD_Target_Listing_Base_New",   5000) if _is_new_kcd_hc else S.get("KCD_Target_Listing_Base",   7000))
        _lst_rate_hc    = int(S.get("KCD_Target_Listing_Client_New",15000) if _is_new_kcd_hc else S.get("KCD_Target_Listing_Client",22000))
        _lst_hc = float(cfg_row.get("Listing Client", cfg_row.get("Listing Clients", 0)) or 0)
        _cat_hc = float(cfg_row.get("Catalog Client", cfg_row.get("Catalog Clients", 0)) or 0)
        # Base clients earn at catalog rate (7k); listing at 22k
        _base_hc = max(0, client_cnt - _cat_hc - _lst_hc)
        highest_coll = (_base_hc + _cat_hc) * _cat_rate_hc + _lst_hc * _lst_rate_hc
        if highest_coll == 0:   # no client split → use all as base rate
            highest_coll = client_cnt * _cat_rate_hc
    elif _is_kcd_sam:
        _hc_mult = S.get("hc_mult_sam", 17000)
        highest_coll = client_cnt * _hc_mult
    elif "ROI" in _t_up_hc:
        _hc_mult = S.get("hc_mult_roi", 14000)
        highest_coll = client_cnt * _hc_mult
    elif any(h in _t_up_hc for h in ["HVRI","HYDERABAD","VASHI","RAIPUR","INDORE"]):
        _hc_mult = S.get("hc_mult_hvri", 17000)
        highest_coll = client_cnt * _hc_mult
    elif "NAGPUR" in _t_up_hc or "PHARMA" in _t_up_hc:
        _hc_mult = S.get("hc_mult_nagpur", 32000)
        highest_coll = client_cnt * _hc_mult
    else:
        _hc_mult = S.get("hc_mult_regular", 21000)
        highest_coll = client_cnt * _hc_mult

    # Derive Collection Target from scheme slab thresholds when not provided by target file
    # KCD Collection Target = Client-A × per-client target (lowest slab threshold for that team)
    # Targets per May PPT:
    #   Regular 91-270D: 11,000/client  |  Regular 270D+: 13,000/client
    #   ROI: 8,000/client               |  HVRI: 10,000/client
    #   Nagpur: 24,000/client           |  New/0-90D: 8,000/client
    #   Listing/Catalog 91D+: lowest slab threshold = 100% of collection target
    #     → HC × 7,000 (base) + ListingClients × 22,000  (270D+/91D)
    #     → HC × 5,000 (base) + ListingClients × 15,000  (0-90D)
    if collection_target == 0 and "KCD" in vertical:
        _t_up2 = str(team).upper()
        _is_new_kcd = vintage in ("0-30D", "31-90D")

        if "LISTING" in _t_up2 or "CATALOG" in _t_up2:
            _base_rate    = int(S.get("KCD_Target_Listing_Base_New",  5000) if _is_new_kcd else S.get("KCD_Target_Listing_Base",  7000))
            _listing_rate = int(S.get("KCD_Target_Listing_Client_New",15000) if _is_new_kcd else S.get("KCD_Target_Listing_Client",22000))
            _lc2  = float(cfg_row.get("Listing Clients", 0) or 0)
            _cc2  = float(cfg_row.get("Catalog Clients",  0) or 0)
            _lc_all = _lc2 + _cc2
            if _lc_all == 0:
                _lc_all = client_cnt
            _base_c = max(0, client_cnt - _lc_all)
            collection_target = _base_c * _base_rate + _lc_all * _listing_rate

        elif "NAGPUR" in _t_up2 or "PHARMA" in _t_up2:
            _slab_thresh = int(S.get("KCD_Target_Nagpur", 24000))
            _nag_slabs = S.get("kcd_nagpur_slabs", [])
            if _nag_slabs:
                _slab_thresh = min(t for t, _, _ in _nag_slabs)
            collection_target = client_cnt * _slab_thresh

        elif any(h in _t_up2 for h in ("HVRI","HYDERABAD","VASHI","RAIPUR","INDORE")):
            _slab_thresh = int(S.get("KCD_Target_HVRI", 10000))
            _hvri_slabs = S.get("kcd_hvri_slabs", [])
            if _hvri_slabs:
                _slab_thresh = min(t for t, _, _ in _hvri_slabs)
            collection_target = client_cnt * _slab_thresh

        elif "ROI" in _t_up2:
            _slab_thresh = int(S.get("KCD_Target_ROI", 8000))
            _roi_slabs = S.get("kcd_roi_91_270_slabs", S.get("kcd_91_270_slabs", []))
            if _roi_slabs:
                _slab_thresh = min(t for t, _, _ in _roi_slabs)
            collection_target = client_cnt * _slab_thresh

        else:  # Regular KCD
            if _is_new_kcd:
                _slab_thresh = int(S.get("KCD_Target_Regular_0_90", 8000))
                _reg_slabs = S.get("kcd_0_90_slabs", [])
            elif vintage == "270D+":
                _slab_thresh = int(S.get("KCD_Target_Regular_270", 13000))
                _reg_slabs = S.get("kcd_270_slabs", [])
            else:
                _slab_thresh = int(S.get("KCD_Target_Regular_91_270", 11000))
                _reg_slabs = S.get("kcd_91_270_slabs", [])
            if _reg_slabs:
                _slab_thresh = min(t for t, _, _ in _reg_slabs)
            collection_target = client_cnt * _slab_thresh

    # PCR% = PCR / PCR_Target (achievement % of per-client collection target)
    # PCDV Target per client = Collection Target / Client-A (sir's FSF col AF/AB)
    # Update AFTER derivation block so collection_target is always populated for KCD
    if "KCD" in vertical and client_cnt > 0:
        pcr_target_v = collection_target / client_cnt
    # PCDV% (KCD) = PCDV / PCDV_Target  — deal-value based achievement
    # PCR%  (CSD) = PCR  / PCR_Target   — collection based achievement
    pcr_pct = ((pcdv_val / pcr_target_v) if "KCD" in vertical
               else (pcr_val / pcr_target_v)) if pcr_target_v > 0 else 0

    # spot_client: client count for PCDV Bullet Spot calculation.
    # Must be raw (non-floored) actual client count so weekly DV / spot_client = true weekly PCDV.
    # Derived from total Deal Value / monthly PCDV when structure file value is missing/default.
    _raw_c = float(cfg_row.get("Client Count", 0) or 0)
    if _raw_c > 1:
        spot_client = _raw_c
    elif pcdv_val > 0 and dv_for_pcdv > 0:
        spot_client = dv_for_pcdv / pcdv_val   # back-derive from DV and PCDV
    else:
        spot_client = max(client_cnt, 1)

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
    _pop_tier1 = _pop_tier2 = _pop_tier3 = 0
    _pcdv_amount = _incr_amount = _final_pcdv = 0
    # Compute MDC tier counts for ALL CSD employees (shown in Exec-CSD cols 21-23)
    if svc_tiers is not None:
        _pop_tier1 = len([t for t in svc_tiers if t == 1])
        _pop_tier2 = len([t for t in svc_tiers if t == 2])
        _pop_tier3 = len([t for t in svc_tiers if t == 3])
    _fnt1_spot = _fnt2_spot = _im_star_spot = 0  # Spot bifurcation tracking
    _im_insta_spot        = 0   # KCD only
    _mcats_spot           = 0   # KCD only
    _im_star_pro_spot_kcd = 0   # KCD SAM only (28-30 Apr IM Star Pro+)
    _wk1_spot             = 0   # KCD WK-1 Power of Productivity (01-09 May)
    _excellent_spot       = 0   # Excellent Incentive Spot (04 May)
    kcd_base_only   = 0   # KCD: base incentive before incremental
    kcd_incremental = 0   # KCD: incremental DV amount
    notes = cmr_note = ""

    # ── CSD ──────────────────────────────────────────────────
    # Only L1 employees use L1 CSD scheme; L2+ use their own logic
    _desig_str = str(designation).upper().strip()
    _is_l1 = _desig_str in ("L1", "EXEC", "SR EXEC", "SR. EXEC", "EXECUTIVE",
                              "SENIOR EXECUTIVE", "AM", "MGR", "MANAGER", "") or not _desig_str
    _is_l2_csd = _desig_str == "L2"

    if "CSD" in vertical:
        # 0-30D new joiners: no individual CMR targets yet → default 55%/65%
        # 31-90D and 91D+: individual targets from CMR file (via sb)
        if vintage == "0-30D":
            _s1, _s2 = 55.0, 65.0   # FSF default for brand-new employees
        else:
            _s1 = float(sb.get("csd_slab1_target", 55))
            _s2 = float(sb.get("csd_slab2_target", 65))
        cmr_slab, cmr_note = get_cmr_slab(cmr_pct, rnl_sent, _s1, _s2)

        # ── Relationship Manager check: applies to ALL vintages ─────────────────
        # An RM who joined <30 days ago is still an RM, not a new-joiner exec.
        # Designation=="L2" is the canonical flag set by load_structure_dump.
        _is_rm_any_vintage = (str(designation).upper().strip() == "L2" or
                              any(k in str(designation).upper()
                                  for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"]))
        if "CSD" in vertical and _is_rm_any_vintage:
            # Sir's formula: cross-mult uses CURRENT month all-renewals CMR%
            # mdc1_cmr_pct is MDC-1 specific CMR% (used for MDC-1 multiplier display)
            # If mdc1_cmr_pct=None (no MDC-1 renewal data), treat as 100% (no MDC-1 clients → no penalty)
            emp_all_cmr  = all_cmr_pct if all_cmr_pct is not None else 0.0
            emp_mdc1_cmr = (mdc1_cmr_pct if mdc1_cmr_pct is not None
                            else (100.0 if all_cmr_sent == 0 else 0.0))
            is_sps_employee = "SPS" in str(vintage_bucket).upper() or "SPS" in str(team).upper()
            _cmr_plus1 = (100.0 if cmr_plus1_sent == 0
                          else cmr_plus1_pct * 100 if cmr_plus1_pct <= 1 else cmr_plus1_pct)
            base_inc, notes = calc_csd_rel_mgr(
                pcr=pcr_val, pcdv=pcdv, prod_raw=prod_score_receipt or 0,
                cmr_pct=cmr_pct, mdc1_cmr_pct=emp_mdc1_cmr,
                cmr_plus1_pct=_cmr_plus1,
                ext_tat=sb.get("ext_tat", S.get("boost_tat_thr", 1)), d60=sb.get("d60", S.get("boost_60d_thr", 10)),
                is_sps=is_sps_employee, S=S,
                emp_cmr_slab1=emp_targets.get("slab1"),
                emp_cmr_slab2=emp_targets.get("slab2"))
            pop_inc = 0
            if S.get("has_apr_spot") or S.get("has_may_spot"):
                spot_inc, _fnt1_spot, _fnt2_spot = calc_spot_april_csd(
                    nr_upsell_count, S,
                    fnt1_count=fnt1_prod_count, fnt2_count=fnt2_prod_count,
                    is_rm=True, monthly_base_inc=base_inc,
                    team_size=cfg_row.get("Effective Team Size", 1))
                _im_star_spot = int(im_star_pro_count * S.get("im_star_rate", 1000))
                spot_inc = int(spot_inc) + _im_star_spot
        elif vintage == "0-30D":
            # 0-30D: fixed slab base + PoP, combined cap = 20,000
            # CSD 0-30D: incremental uses Client-C (calculated), not Client-A
            _csd_client_c = _client_c_val if _client_c_val > 0 else client_cnt
            base_inc, pop_inc, notes, _pop_tier1, _pop_tier2, _pop_tier3, _pcdv_amount, _incr_amount, _final_pcdv = calc_csd_new(
                pcdv, _csd_client_c, cmr_slab, cmr_pct,
                rnl_prods, rnl_modes, vintage, S,
                svc_tiers=svc_tiers,
                pop_cmr_floor=S.get("pop_cmr_floor", POP_CMR_FLOOR),
                metric_label=metric_label,
                prod_score_receipt=prod_score_receipt)
            # Combined cap: min(PCDV*CMR_mult + PoP, 20000) per FSF
            _cap = S.get("new_joiner_cap", 20000)
            if base_inc + pop_inc > _cap:
                notes += f" | COMBINED_CAP:{_cap}"
        elif vintage == "31-90D":
            # 31-90D: SAME fixed PCDV slab formula as 0-30D (NOT per-txn)
            # Scheme doc: PCDV 1800/2100/2400/2800 -> fixed Rs. payout + 3% incr above 2800
            # CMR Slab1=100%, Slab2=120%. No MDC-1 multiplier.
            # L2 Rel Mgr exception still applies
            # all_cmr: all-renewals CMR% for current month (FSF AW column - slab multiplier)
            # mdc1_cmr: MDC-1 only CMR% (not used in L1 slab mult - only for reference)
            emp_all_cmr  = all_cmr_pct if all_cmr_pct is not None else (mdc1_cmr_pct if mdc1_cmr_pct is not None else 0.0)
            emp_all_cmr  = all_cmr_pct if all_cmr_pct is not None else (mdc1_cmr_pct if mdc1_cmr_pct is not None else 0.0)
            emp_mdc1_cmr = (mdc1_cmr_pct if mdc1_cmr_pct is not None
                            else (100.0 if all_cmr_sent == 0 else 0.0))
            is_sps_by_bucket = str(vintage_bucket).upper().strip() == "SPS"
            is_sps_by_team   = "SPS" in str(team).upper()
            is_sps_employee  = is_sps_by_bucket or is_sps_by_team
            _is_rel_mgr_31 = (str(designation).upper().strip() == "L2" or
                              any(k in str(designation).upper()
                                  for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"]))
            if _is_rel_mgr_31:
                # sent=0 for next month → no MDC-1 clients due → 100% (no penalty)
                # sent≥1 but pct=0 → 0% (none received)
                _cmr_plus1_31 = (100.0 if cmr_plus1_sent == 0
                                 else cmr_plus1_pct * 100 if cmr_plus1_pct <= 1 else cmr_plus1_pct)
                base_inc, notes = calc_csd_rel_mgr(
                    pcr=pcr_val, pcdv=pcdv, prod_raw=prod_score_receipt or 0,
                    cmr_pct=cmr_pct, mdc1_cmr_pct=emp_mdc1_cmr,
                    cmr_plus1_pct=_cmr_plus1_31,
                    ext_tat=sb.get("ext_tat", S.get("boost_tat_thr", 1)), d60=sb.get("d60", S.get("boost_60d_thr", 10)),
                    is_sps=is_sps_employee, S=S)
                pop_inc = 0
            else:
                # Use calc_csd_new -- same fixed PCDV slab as 0-30D
                # CSD 31-90D: incremental uses Client-C (calculated), not Client-A
                _csd_client_c = _client_c_val if _client_c_val > 0 else client_cnt
                base_inc, pop_inc, notes, _pop_tier1, _pop_tier2, _pop_tier3, _pcdv_amount, _incr_amount, _final_pcdv = calc_csd_new(
                    pcdv, _csd_client_c, cmr_slab, cmr_pct,
                    rnl_prods, rnl_modes, vintage, S,
                    svc_tiers=svc_tiers,
                    pop_cmr_floor=S.get("pop_cmr_floor", POP_CMR_FLOOR),
                    metric_label=metric_label,
                    prod_score_receipt=prod_score_receipt)
            # Combined cap: min(PCDV*CMR_mult + PoP, 20000) per FSF
            if not _is_rel_mgr_31:
                _cap_31 = S.get("new_joiner_cap", 20000)
                if base_inc + pop_inc > _cap_31:
                    notes += f" | COMBINED_CAP:{_cap_31}"
            # RM Spot applies regardless of vintage (scheme slide 3: "Applicable: RM" — no vintage restriction)
            if _is_rel_mgr_31 and S.get("has_apr_spot") or S.get("has_may_spot"):
                spot_inc, _fnt1_spot, _fnt2_spot = calc_spot_april_csd(
                    nr_upsell_count, S,
                    fnt1_count=fnt1_prod_count, fnt2_count=fnt2_prod_count,
                    is_rm=True, monthly_base_inc=base_inc,
                    team_size=cfg_row.get("Effective Team Size", 1))
                _im_star_spot = int(im_star_pro_count * S.get("im_star_rate", 1000))
                spot_inc = int(spot_inc) + _im_star_spot
        else:
            # SPS -- no PoP; Insta = 0.5; productivity from receipt
            # all_cmr: ALL-renewals CMR% (sir's AW column) - used for MDC-1 multiplier
            emp_all_cmr  = all_cmr_pct if all_cmr_pct is not None else (mdc1_cmr_pct if mdc1_cmr_pct is not None else 0.0)
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
            # CSD L2 = Relationship Manager (from Designation column)
            _is_rel_mgr = (str(designation).upper().strip() == "L2" or
                           any(k in str(designation).upper()
                               for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"]))
            if _is_rel_mgr:
                # CMR+1% = next month MDC-1 for March calc;
                # for April (no May data), fall back to current month MDC-1
                # sent=0 for next month → no MDC-1 clients due → 100% (no penalty)
                _cmr_plus1 = (100.0 if cmr_plus1_sent == 0
                              else cmr_plus1_pct * 100 if cmr_plus1_pct <= 1 else cmr_plus1_pct)
                base_inc, notes = calc_csd_rel_mgr(
                    pcr=pcr_val, pcdv=pcdv, prod_raw=prod_score_receipt or 0,
                    cmr_pct=cmr_pct, mdc1_cmr_pct=emp_mdc1_cmr,
                    cmr_plus1_pct=_cmr_plus1,
                    ext_tat=sb.get("ext_tat", S.get("boost_tat_thr", 1)), d60=sb.get("d60", S.get("boost_60d_thr", 10)),
                    is_sps=is_sps_employee, S=S)
                _pcdv_amount = round(pcdv, 0)
                _incr_amount = 0
                _final_pcdv  = round(pcdv, 0)
            else:
                base_inc, notes = calc_csd_sps(
                    pcdv, prod_score_receipt or 0, txn_count, cmr_slab, vintage,
                    emp_all_cmr,
                    sb.get("ext_tat", S.get("boost_tat_thr", 1)),
                    sb.get("d60",     S.get("boost_60d_thr", 10)),
                    S,
                    metric_label=metric_label, is_sps=is_sps_employee,
                    mdc1_cmr_plus1=(cmr_plus1_pct * 100 if cmr_plus1_pct <= 1
                                    else cmr_plus1_pct) if cmr_plus1_sent > 0 else None)
                # PCDV breakdown for 90+ SPS output columns
                _pcdv_amount = round(pcdv, 0)    # PCDV value used for slab lookup
                _incr_amount = 0                  # No incremental 3% for 90+ SPS scheme
                _final_pcdv  = round(pcdv, 0)    # Same as PCDV for 90+
            # Spot: config-driven -- April config has "CSD_Spot_Apr"; March has "CSD_Spot"
            # CSD RM has a SEPARATE spot scheme (slides 3+): min 2.5 prod, base 2000/3500
            if S.get("has_apr_spot") or S.get("has_may_spot"):
                _is_90plus_csd = vintage not in ("0-30D", "31-90D")
                _is_rm_desig   = (_desig_str == "L2")
                # May spot: L1 Exec eligible only for 90+ vintage (per PPT)
                # May spot: FNT2 (17-31 May) has NO spot, so pass fnt2_count=0
                _fnt2_for_spot = 0 if S.get("has_may_spot") else fnt2_prod_count
                # L1 Exec: skip spot if May and 0-90D vintage (only 90+ eligible in May)
                if not _is_rm_desig and S.get("has_may_spot") and not _is_90plus_csd:
                    spot_inc, _fnt1_spot, _fnt2_spot = 0, 0, 0
                else:
                    spot_inc, _fnt1_spot, _fnt2_spot = calc_spot_april_csd(
                        nr_upsell_count, S,
                        fnt1_count=fnt1_prod_count, fnt2_count=_fnt2_for_spot,
                        is_rm=_is_rm_desig,
                        monthly_base_inc=base_inc,
                        team_size=cfg_row.get("Effective Team Size", 1) if _is_rm_desig else 1)
                # IM Star Pro+ New Sale Spot: Rel Mgr only, ₹1000/sale (April only)
                if _is_rm_desig and S.get("has_apr_spot") and not S.get("has_may_spot"):
                    _im_star_spot = int(im_star_pro_count * S.get("im_star_rate", 1000))
                    spot_inc = int(spot_inc) + _im_star_spot
            elif S.get("has_mar_spot"):
                _wdv = weekly_dv if weekly_dv else {1:0,2:0,3:0,4:0}
                spot_inc = calc_spot_march_csd(_wdv, spot_client, vintage)
            else:
                spot_inc = 0

    # ── KCD ──────────────────────────────────────────────────
    elif "KCD" in vertical:
        # Minimum productivity gate: 2 in any week OR N total per month
        # N = 6 for CSD-to-KCD new joiners (0-30D/31-90D), N = 8 for all others
        _kcd_monthly_min = 6 if vintage in ("0-30D", "31-90D") else 8
        _has_2_in_a_week = any(v >= 2 for v in weekly_prod_counts.values())
        _total_prod_kcd  = float(prod_score_receipt or txn_count or 0)
        if _has_2_in_a_week:
            _prod_gate_met  = True
            _prod_gate_note = f"2+/wk (max={max(weekly_prod_counts.values()) if weekly_prod_counts else 0})"
        elif _total_prod_kcd >= _kcd_monthly_min:
            _prod_gate_met  = True
            _prod_gate_note = f"{_total_prod_kcd:.0f}>={_kcd_monthly_min}/mo"
        else:
            _prod_gate_met  = False
            _prod_gate_note = (f"max_wk={max(weekly_prod_counts.values()) if weekly_prod_counts else 0}<2"
                               f" AND total={_total_prod_kcd:.0f}<{_kcd_monthly_min}")

        # Check if this is an L2 (SAM) or ILP employee using Designation field
        _desig_up = str(designation).upper().strip()
        # Primary check: Designation column (L1/L2/ILP from structure file)
        _is_sam   = _desig_up == "L2" or any(k in _desig_up for k in
                    ("SAM", "SR. ACCOUNT", "SR.ACCOUNT", "SENIOR ACCOUNT MANAGER"))
        _is_ilp_desig = _desig_up == "ILP" or "ILP" in _desig_up
        # Init KCD pre-dict vars so they are never unbound
        _kcd_pcdv_tgt = 0.0; _kcd_pcdv_pct = 0.0; _kcd_pcdv_pct_early = 0.0
        _kcd_hc_slab = 0; _kcd_coll_tgt = 0; _kcd_is_slab = False; _kcd_is_lst_cat = False
        if not _is_sam and "SAM" in str(team).upper(): _is_sam = True
        if not _is_ilp_desig and "ILP" in str(team).upper(): _is_ilp_desig = True

        team_up = team.upper()

        # KCD uses productive receipt count (not all receipt rows, not renewal count)
        kcd_txn = prod_score_receipt if prod_score_receipt and prod_score_receipt > 0 else txn_count

        # SS+ sent count for penalty determination — used for kcd_col (NOT overall CMR)
        ss_sent_count = cmr_data.get("ss_sent", 0)

        # CMR col from OVERALL CMR% and overall renewal sent (FAQ Q3)
        # SS+CMR% only affects the ss_mult penalty (100%/50%) via get_kcd_cmr_col separately
        kcd_col, cmr_note = get_kcd_cmr_col(
            cmr_pct, rnl_sent, sb.get("kcd_slab1_target", 72), sb.get("kcd_slab2_target", 80))

        # KCD: use Net Deal Value for incremental (not Net Collection)
        kcd_net_dv = net_deal_val if net_deal_val > 0 else net_dv

        # Track base vs incremental separately for KCD output columns
        kcd_base_only  = 0
        kcd_incremental = 0

        def _kcd_spot(is_l2_sam=False, monthly_base_inc=0):
            """Config-driven spot: April FNT (PCDV-based) if April config; March.
            For May config, KCD spot is WK-1 per-product (handled separately).
            Returns (total, fnt1, fnt2)."""
            if S.get("has_apr_spot") and not S.get("has_may_spot"):
                # April PCDV-based FNT spot
                return calc_spot_april_kcd(
                    pcdv_val, spot_client, team, location, vintage, S,
                    fnt1_pcdv=fnt1_pcdv, fnt2_pcdv=fnt2_pcdv,
                    pref_ss_count=pref_ss_count, btl_count=btl_count,
                    is_l2_sam=is_l2_sam, monthly_base_inc=monthly_base_inc,
                    im_var_count=im_var_count)
            elif S.get("has_mar_spot") and not S.get("has_may_spot"):
                _wdv = weekly_dv if weekly_dv else {1:0,2:0,3:0,4:0}
                _s = calc_spot_march_kcd(_wdv, spot_client, team, location, vintage)
                return _s, 0, 0
            # May: WK-1 per-product spot is computed separately (_wk1_spot); return 0 here
            return 0, 0, 0

        if _is_sam:
            # Detect SAM-ILP vs regular SAM
            _is_ilp = _is_ilp_desig or "ILP" in team_up
            if _is_ilp:
                # SAM-ILP: % of DV against individual target
                _ilp_rec  = sam_ilp_targets.get(emp_id, {})
                _ilp_tgt  = _ilp_rec.get("target", 0) if isinstance(_ilp_rec, dict) else float(_ilp_rec or 0)
                _ilp_rate = _ilp_rec.get("rate_95") if isinstance(_ilp_rec, dict) else None
                _bt_count = int(btl_count or sb.get("btl_sales", 0))  # from receipt (Base Client Type AND Unique)
                # Use client breakdown from ILP target file when available
                if isinstance(_ilp_rec, dict):
                    catalog_c  = float(_ilp_rec.get("catalog",  catalog_c)  or catalog_c)
                    listing_c  = float(_ilp_rec.get("listing",  listing_c)  or listing_c)
                    _ilp_ca    = float(_ilp_rec.get("client_a", 0) or 0)
                    if _ilp_ca > 0: client_cnt = _ilp_ca  # override with ILP file's Client-A
                base_inc, notes = calc_kcd_sam_ilp(
                    kcd_net_dv, _ilp_tgt,
                    cmr_pct=cmr_pct,
                    cmr_sent=cmr_data.get("renewal_sent", 0),
                    cmr_recd=cmr_data.get("renewal_received", 0),
                    ss_cmr_pct=ss_cmr_pct,
                    big_ticket_count=_bt_count,
                    emp_rate_95=_ilp_rate, S=S)
                kcd_base_only   = base_inc
                kcd_incremental = 0
                spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
            else:
                # L2 SAM scheme -- lower per-txn rates, 0.65%/0.45% incremental
                base_inc, notes = calc_kcd_sam(
                pcr_val=pcr_val, pcdv_val=pcdv,
                net_dv=kcd_net_dv, net_coll=net_dv,
                txn_prod_raw=prod_score_receipt or txn_count,
                cmr_pct=cmr_pct,
                ss_cmr_pct=ss_cmr_pct, ss_sent=ss_sent_count,
                btl_sales=sb.get("btl_sales", 0),
                team=team, location=location, vintage=vintage,
                client_a=client_cnt, listing_c=listing_c, catalog_c=catalog_c,
                collection_target=collection_target, S=S,
                l1_count=int(sb.get("L1 Count", 4) or 4),
                cmr_col_val=kcd_col)
            kcd_base_only   = base_inc
            _kcd_pcdv_pct_early = (round(kcd_net_dv / collection_target * 100, 2) if collection_target > 0 else 0.0)  # for Listing/Catalog gate
            kcd_incremental = 0  # already inside calc_kcd_sam
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(is_l2_sam=True, monthly_base_inc=base_inc)
        elif "LISTING" in team_up:
            # Use structure file Listing Clients; fall back to (total-1) if absent
            _list_c = listing_c if listing_c > 0 else max(1, client_cnt - 1)
            _base_c = max(client_cnt - _list_c, 1)
            base_inc, notes = calc_kcd_listing(
                kcd_net_dv, kcd_txn, kcd_col, vintage,
                ss_cmr_pct, ss_sent_count, collection_target, S,
                base_clients=_base_c, list_clients=_list_c)
            # Incremental: gate on PCR% > 140% (collection-based), compute on Net DV
            kcd_incremental = round(max(0, kcd_net_dv - (collection_target or 0)) * S.get("kcd_incr_rate", 0.014), 0) \
                              if (_kcd_pcdv_pct_early > 140 and (collection_target or 0) > 0) else 0
            kcd_base_only = base_inc
            base_inc = kcd_base_only + kcd_incremental
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
            if spot_inc == 0:
                spot_inc = calc_spot_kcd(pcdv, "Listing_270D" if vintage == "270D+" else "Listing_other",
                    sb.get("spot_met", False), S)
        elif "CATALOG" in team_up:
            # Use structure file Catalog Clients; fall back to (total-1) if absent
            _cat_c  = catalog_c if catalog_c > 0 else max(1, client_cnt - 1)
            _base_c = max(client_cnt - _cat_c, 1)
            base_inc, notes = calc_kcd_catalog(
                kcd_net_dv, kcd_txn, kcd_col, vintage,
                (btl_count or sb.get("btl_sales", 0)), ss_cmr_pct, ss_sent_count, collection_target, S,
                base_clients=_base_c, list_clients=_cat_c)
            kcd_incremental = round(max(0, kcd_net_dv - (collection_target or 0)) * S.get("kcd_incr_rate", 0.014), 0) \
                              if (_kcd_pcdv_pct_early > 140 and (collection_target or 0) > 0) else 0
            kcd_base_only = base_inc
            base_inc = kcd_base_only + kcd_incremental
            # BTL multiplier applied to total (base + incremental) per FAQ Q14:
            # BTL=0 → BTL gate (no incentive); BTL=1 → 100%; BTL>=2 → 120%
            _btl_c = btl_count or sb.get("btl_sales", 0)
            if _btl_c == 0:
                base_inc = 0   # BTL=0 → no incentive per FAQ Q14
            elif _btl_c >= 2:
                base_inc = round(base_inc * 1.2, 0)
            # BTL=1 → 100% (no change)
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
            if spot_inc == 0:
                spot_inc = calc_spot_kcd(pcdv, "Catalog_270D" if vintage == "270D+" else "Catalog_other",
                    sb.get("spot_met", False), S)
        elif "ROI" in team_up:
            kcd_base_only, notes = calc_kcd_roi(
                pcdv, kcd_txn, kcd_col, vintage,
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            kcd_incremental = round(max(0, kcd_net_dv - highest_coll) * S.get("kcd_incr_rate", 0.014), 0) \
                              if (kcd_net_dv > highest_coll and highest_coll > 0) else 0
            base_inc = kcd_base_only + kcd_incremental
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
            if spot_inc == 0:
                spot_inc = calc_spot_kcd(pcdv, "ROI_Exec", sb.get("spot_met", False), S)
        elif any(h in team_up for h in ("HVRI","HYDERABAD","VASHI","RAIPUR","INDORE")):
            # HVRI: calc_kcd_regular already uses HVRI slabs based on location
            kcd_base_only, notes = calc_kcd_regular(
                pcdv, kcd_txn, kcd_col, vintage, "HVRI",
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            notes = notes.replace("KCD Regular", "KCD HVRI")
            kcd_incremental = round(max(0, kcd_net_dv - highest_coll) * S.get("kcd_incr_rate", 0.014), 0) \
                              if (kcd_net_dv > highest_coll and highest_coll > 0) else 0
            base_inc = kcd_base_only + kcd_incremental
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
        elif "NAGPUR" in team_up or "PHARMA" in team_up:
            # Nagpur Pharma: uses Nagpur-specific slabs
            kcd_base_only, notes = calc_kcd_regular(
                pcdv, kcd_txn, kcd_col, vintage, "NAGPUR",
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            notes = notes.replace("KCD Regular", "KCD Nagpur")
            kcd_incremental = round(max(0, kcd_net_dv - highest_coll) * S.get("kcd_incr_nagpur", 0.0085), 0) \
                              if (kcd_net_dv > highest_coll and highest_coll > 0) else 0
            base_inc = kcd_base_only + kcd_incremental
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
        else:
            kcd_base_only, notes = calc_kcd_regular(
                pcdv, kcd_txn, kcd_col, vintage, location,
                ss_cmr_pct, ss_sent_count, S, collection_target, metric_label)
            # Nagpur uses 0.85% incremental, all others use regular rate
            _incr_rate = (S.get("kcd_incr_nagpur", 0.0085)
                          if ("NAGPUR" in team_up or "PHARMA" in team_up)
                          else S.get("kcd_incr_rate", 0.014))
            kcd_incremental = round(max(0, kcd_net_dv - highest_coll) * _incr_rate, 0) \
                              if (kcd_net_dv > highest_coll and highest_coll > 0) else 0
            base_inc = kcd_base_only + kcd_incremental
            spot_inc, _fnt1_spot, _fnt2_spot = _kcd_spot(monthly_base_inc=base_inc)
            if spot_inc == 0:
                _legacy_spot = (calc_spot_kcd(pcdv, "KCD_0_90D", sb.get("spot_met", False), S)
                                if vintage in ("0-30D", "31-90D") else 0)
                spot_inc = _legacy_spot

        # ── IM Star Pro+ New Sale Spot (28-30 Apr): SAM only ₹1000/sale ─────────
        _im_star_pro_spot_kcd = int(im_star_pro_count * S.get("im_star_rate", 1000)) if _is_sam else 0

        # ── KCD WK-1 Power of Productivity Spot (01-09 May) ─────────────────────
        _wk1_spot = 0
        _wk1_rates = S.get("kcd_wk1_spot", {})
        _wk1_counts = wk1_prod_counts or {}
        if _wk1_rates and _wk1_counts:
            _wk1_base_mult = 0.5 if base_inc == 0 else 1.0  # 50% if base not achieved (PPT)
            _wk1_total_prods = sum(_wk1_counts.values())
            if _wk1_total_prods >= 2:  # min 2 prods in WK-1 period
                for cat, rate_info in _wk1_rates.items():
                    _cat_count = _wk1_counts.get(cat, 0)
                    _cat_myr   = _wk1_counts.get(cat + "_MYR", 0)  # MYR sub-count if tracked
                    _cat_ann   = _cat_count - _cat_myr  # annual count
                    if _cat_count > 0:
                        if isinstance(rate_info, dict):
                            _pref = "l2" if _is_sam else "l1"
                            _ann_rate = rate_info.get(f"{_pref}_annual", 0)
                            _myr_rate = rate_info.get(f"{_pref}_myr",    0)
                        else:
                            _ann_rate = int(rate_info) if not _is_sam else int(rate_info) // 2
                            _myr_rate = _ann_rate * 2  # MYR = 2× annual (per PPT pattern)
                        # If MYR tracking not available, use annual rate for all
                        _wk1_spot += (_cat_ann * _ann_rate) + (_cat_myr * _myr_rate)
                _wk1_spot = int(_wk1_spot * _wk1_base_mult)  # 50% if monthly base not achieved

        # ── Excellent Incentive Spot (04 May only) ───────────────────────────────
        # Uses pre-computed per-employee count (passed via parameter to avoid full-df scan)
        _excellent_spot = 0
        _exc_day   = int(S.get("Excellent_Spot_Day", 4))
        _exc_l1    = int(S.get("Excellent_Spot_L1_Rate", 750))
        _exc_l2    = int(S.get("Excellent_Spot_L2_Rate", 400))
        if _exc_day > 0 and excellent_txn_count > 0:
            if _is_sam or str(designation).upper().strip() == "L2":
                if excellent_txn_count >= 2:
                    _excellent_spot = (excellent_txn_count - 1) * _exc_l2
            else:
                _is_90plus = vintage not in ("0-30D", "31-90D")
                if _is_90plus:
                    _excellent_spot = excellent_txn_count * _exc_l1

        # ── KCD IM Insta Spot ─────────────────────────────────────────────────
        _insta_min_w = S.get("insta_min_week", 2); _insta_min_m = S.get("insta_min_month", 7)
        _insta_elig = (any(v >= _insta_min_w for v in weekly_prod_counts.values())
                       or (prod_score_receipt or 0) >= _insta_min_m)
        _insta_rate   = S.get("insta_l2_rate", 150) if _is_sam else S.get("insta_l1_rate", 300)
        # Monthly Base Incentive mandatory for IM Insta spot (same gate as other KCD spots)
        _im_insta_spot = int(insta_cnt_receipt * _insta_rate) if (base_inc > 0 and _insta_elig and insta_cnt_receipt) else 0

        # ── KCD MCATs Renewals Spot ───────────────────────────────────────────
        # FAQ Q6: Monthly Base Incentive is mandatory to earn MCATs incentive
        _mcats_spot = calc_mcats_renewal(int(sb.get("btl_sales", 0)), S, is_l2=_is_sam) if base_inc > 0 else 0

        # ── KCD Min Productivity Gate (L1 only) ──────────────────────────────
        # Scheme: min 2 per week OR 8/month (6/month for CSD-to-KCD new joiners)
        # SAM/ILP handle their own eligibility separately
        if "KCD" in vertical and not _is_sam:
            if not _prod_gate_met:
                kcd_base_only   = 0
                kcd_incremental = 0
                base_inc        = 0
                notes           = (notes or "") + f" | MIN_PROD_NOT_MET ({_prod_gate_note})"

    # ── Decompose values matching sir's FSF column layout ────────────────────
    # Productivity Score for display — matches sir's FSF formula:
    #   CSD 0-30D/31-90D : COUNTIFS(AR="1") = integer count, Insta excluded (sir col AP)
    #   CSD SPS 91D+     : SUMIFS(AR)       = weighted (1.0 + 0.5×Insta)  (sir col BJ)
    #   KCD / all others : SUMIFS(AR)       = weighted                    (sir col AH/AG)
    _is_new_joiner = vintage in ("0-30D", "31-90D")
    _prod_score = round(float(
        prod_score_receipt_int if _is_new_joiner   # exact int count for 0-90D
        else (prod_score_receipt or 0)             # weighted SUMIFS for SPS/KCD
    ), 1)

    # CSD breakdown: expose intermediate values to match sir's FSF column layout
    _is_csd_sps = "CSD" in vertical and "SPS" in team
    _is_csd_rm  = "CSD" in vertical and (str(designation).upper().strip() == "L2" or
                  any(k in str(designation).upper()
                                            for k in ["REL MGR","RELATIONSHIP MANAGER","RM-"]))
    _is_csd     = "CSD" in vertical

    import re as _re

    # KCD team classification for column logic
    _kcd_t_up  = str(team).upper()
    _is_kcd    = "KCD" in vertical
    _kcd_is_lst_cat = _is_kcd and ("LISTING" in _kcd_t_up or "CATALOG" in _kcd_t_up)
    _kcd_is_slab    = _is_kcd and not _kcd_is_lst_cat   # Regular/ROI/HVRI/Nagpur
    # HC per vintage for slab-based teams (per sir's PPT)
    _kcd_hc_mult = (
        32000 if ("NAGPUR" in _kcd_t_up or "PHARMA" in _kcd_t_up) else
        17000 if "ROI" in _kcd_t_up else
        17000 if "HVRI" in _kcd_t_up else
        (14000 if vintage in ("0-30D","31-90D") else
         17000 if vintage == "91-270D" else 19000)  # Regular
    ) if _kcd_is_slab else 0
    _kcd_hc_slab = int(client_cnt * _kcd_hc_mult) if _kcd_is_slab else 0   # Highest Collection for slab teams
    # Collection target for formula-based teams (Listing/Catalog)
    _is_new_kcd = vintage in ("0-30D","31-90D")
    _kcd_cat_rate_ct = int(S.get("KCD_Target_Listing_Base_New",   5000) if _is_new_kcd else S.get("KCD_Target_Listing_Base",   7000))
    _kcd_lst_rate_ct = int(S.get("KCD_Target_Listing_Client_New",15000) if _is_new_kcd else S.get("KCD_Target_Listing_Client",22000))
    _kcd_lst_c_ct  = float(cfg_row.get("Listing Client",  cfg_row.get("Listing Clients",  0)) or 0)
    _kcd_cat_c_ct  = float(cfg_row.get("Catalog Client",  cfg_row.get("Catalog Clients",  0)) or 0)
    if _kcd_is_lst_cat:
        # Base clients = CA - catalog_clients - listing_clients; they earn at catalog rate (7k)
        _kcd_base_c = max(0, client_cnt - _kcd_cat_c_ct - _kcd_lst_c_ct)
        _kcd_coll_tgt = int((_kcd_base_c + _kcd_cat_c_ct) * _kcd_cat_rate_ct
                            + _kcd_lst_c_ct * _kcd_lst_rate_ct)
        if _kcd_coll_tgt == 0:   # no client split → all at catalog/base rate
            _kcd_coll_tgt = int(client_cnt * _kcd_cat_rate_ct)
    else:
        _kcd_coll_tgt = 0
    # PCDV Target = HC/CA (slab) OR Collection_Target/CA (formula)
    _kcd_pcdv_tgt = (round(_kcd_hc_slab / client_cnt, 0) if (_kcd_is_slab and client_cnt > 0) else
                     round(_kcd_coll_tgt / client_cnt, 0) if (_kcd_is_lst_cat and client_cnt > 0) else 0)
    # KCD PCDV% = PCDV / PCDV_Target × 100
    _kcd_pcdv_pct = round(pcdv_val / _kcd_pcdv_tgt * 100, 2) if _kcd_pcdv_tgt > 0 else 0.0

    # CMR+1 Sent/Recd: from next-month (June) renewal data via cmr_plus1_map
    _c1_map = cmr_plus1_map.get(emp_id, {})
    _c1_sent = _c1_map.get("mdc1_sent", 0)

    # Both Achievers / Only CMR multiplier label (extracted from scheme notes)
    _ba_m = _re.search(r'BothAchievers×([0-9.%]+)', notes)
    _oc_m = _re.search(r'OnlyCMR×([0-9.%]+)', notes)
    if _ba_m:
        _ba_mult_str = f"Both Achievers {_ba_m.group(1)}"
    elif _oc_m:
        _ba_mult_str = f"Only CMR {_oc_m.group(1)}"
    else:
        _ba_mult_str = ""

    # Extract booster from scheme notes string — try multiple patterns
    _bm = _re.search(r'boost:([0-9.]+)', notes) or _re.search(r'Booster×([0-9.]+)', notes) or _re.search(r'boost.*?([0-9.]+)', notes)
    _boost_val = float(_bm.group(1)) if _bm else 1.0
    # Fallback: if booster not in notes, derive from ext_tat/d60 inputs directly
    if _boost_val == 1.0 and _is_csd and "SPS" in str(team).upper():
        _ext_tat_val = float(sb.get("ext_tat", S.get("boost_tat_thr", 1)))
        _d60_val     = float(sb.get("d60",     S.get("boost_60d_thr", 10)))
        if _ext_tat_val < S.get("boost_tat_thr", 1) and _d60_val < S.get("boost_60d_thr", 10):
            _boost_val = S.get("boost_mult", 1.2)

    # SPS vintage flag: MDC1 multiplier only applies to 91D+ employees, not new joiners
    _is_sps_vintage = vintage not in ("0-30D", "31-90D")  # MDC-1 mult only for 91D+

    if _is_csd_rm:
        # ── CSD Rel Mgr output values ──
        _pt_m = _re.search(r'PerTxn:([0-9]+)', notes)
        _inc_payout_mult = int(_pt_m.group(1)) if _pt_m else 0
        # Show the slab rate even if base=0 (helps diagnose why it's 0)
        # Per Txn = slab_rate × productivity (shows what it would be if CMR met)
        _per_txn_rate = _inc_payout_mult  # show the base slab rate (before CMR mult)
        # Extract CMR+1% from Rel Mgr scheme notes "CMR+1:NNN%" → map to multiplier
        _cmr1_pct_m = __import__("re").search(r"CMR[+]1:([0-9.]+)%", notes)
        if _cmr1_pct_m:
            _cmr1_pct_val = float(_cmr1_pct_m.group(1))
            if _cmr1_pct_val > 35:   _cmr1_from_notes = 1.20
            elif _cmr1_pct_val >= 25: _cmr1_from_notes = 1.00
            else:                     _cmr1_from_notes = 0.50
        else:
            _cmr1_from_notes = 0.0
        _net_inc_before_boost = round(base_inc / _boost_val, 0) if _boost_val != 0 else base_inc
        _mdc1_mult_val = 0.0
    else:
        # ── CSD L1 (Exec) output values ──
        # Extract MDC1 multiplier from scheme notes string
        # Pattern: "MDC1:1.2(60%)" or "MDC1:0.5(20%)"
        _mdc1_m = _re.search(r'MDC1:([0-9.]+)', notes)
        _mdc1_mult_val = float(_mdc1_m.group(1)) if _mdc1_m else 0.0
        # Fallback: derive from mdc1_cmr_pct -- only for SPS (91D+), not new joiners
        if _mdc1_mult_val == 0.0 and _is_csd and _is_sps_vintage:
            _mdc1_pct_raw = mdc1_cmr_pct if mdc1_cmr_pct is not None else 0.0
            _mdc1_mult_val = (S.get("mdc1_hi_mult", 1.2) if _mdc1_pct_raw > S.get("mdc1_hi_thr", 35)
                              else S.get("mdc1_mid_mult", 1.0) if _mdc1_pct_raw >= S.get("mdc1_mid_thr", 25)
                              else S.get("mdc1_low_mult", 0.5))
        elif not _is_sps_vintage:
            _mdc1_mult_val = 0.0  # N/A for 0-30D new joiners

        # Net Incentive = base before booster
        _net_inc_before_boost = round(base_inc / _boost_val, 0) if _boost_val != 0 else base_inc

        # Per-txn rate: extract directly from scheme notes "₹NNNN/txn"
        _per_txn_m = _re.search(r'₹([0-9]+)/txn', notes)
        if _per_txn_m:
            _per_txn_rate = int(_per_txn_m.group(1))
        elif _is_sps_vintage and _is_csd and _prod_score > 0 and _mdc1_mult_val > 0 and _boost_val > 0:
            _per_txn_rate = round(_net_inc_before_boost / (_prod_score * _mdc1_mult_val), 0)
        else:
            _per_txn_rate = 0

        # Incentive Payout Multiplier = per-txn slab rate in ₹ (e.g. 2000, 2400)
        # This is the base rate from the PCDV slab table, before MDC1 mult and booster
        _inc_payout_mult = (int(_per_txn_rate) if _is_sps_vintage else 0)

    # Add IM Insta and MCATs to KCD spot total
    if "KCD" in vertical:
        spot_inc = int(spot_inc) + _im_insta_spot + _mcats_spot + _im_star_pro_spot_kcd + _wk1_spot + _excellent_spot

    # KCD breakdown -- extract per-txn rate from scheme notes
    _kcd_base   = int(kcd_base_only)   if "KCD" in vertical else 0
    _kcd_incr   = int(kcd_incremental) if "KCD" in vertical else 0
    _kcd_ss_mult = (0.5 if (cmr_data.get("ss_sent", 0) >= 3 and ss_cmr_pct < S.get("kcd_ss_threshold", 72)) else 1.0) if "KCD" in vertical else 1.0
    # Total productive txns used (same variable used in KCD calc)
    _kcd_prod   = (prod_score_receipt or txn_count) if "KCD" in vertical else 0
    # Per-txn rate: extract from scheme notes "₹{rate}/txn×"
    _kcd_per_txn_m = _re.search(r"₹([0-9]+)/txn", notes) if "KCD" in vertical else None
    _kcd_per_txn   = int(_kcd_per_txn_m.group(1)) if _kcd_per_txn_m else 0
    # For OnlyCMR employees (per_txn=0), also extract the effective rate from notes
    # and show the OnlyCMR rate so user can see what rate was applied
    if _kcd_per_txn == 0 and "OnlyCMR" in notes:
        _onlycmr_m = _re.search(r"Rs([0-9.]+)/txn", notes)
        if not _onlycmr_m: _onlycmr_m = _re.search(r"₹([0-9]+)/txn\*([0-9.]+) \| .* \| OnlyCMR", notes)
        # Fall back: show 0 but note BA_Multiplier column will show "Only CMR 50%"
        _kcd_per_txn = 0  # per_txn=0 is correct; BA Multiplier shows the context

    return {
        "CMR% (auto)":         round(cmr_pct, 1),
        "SS+ CMR% (auto)":     round(ss_cmr_pct, 1),
        "CMR Slab1 Target":    sb.get("csd_slab1_target", sb.get("kcd_slab1_target", "")),
        "CMR Slab2 Target":    sb.get("csd_slab2_target", sb.get("kcd_slab2_target", "")),
        "CMR Sent":       rnl_sent,
        "CMR Received":   cmr_data.get("renewal_received", 0),
        "CMR Slab":            cmr_note,
        "SS+ Sent":            cmr_data.get("ss_sent", 0),
        "SS+ Received":        cmr_data.get("ss_received", 0),
        "MDC-1 CMR%":          ("NA" if (_is_new_joiner and _is_csd)
                         else (round(float(mdc1_cmr_pct) * 100 if float(mdc1_cmr_pct) <= 1 else float(mdc1_cmr_pct), 1)
                               if (mdc1_cmr_pct is not None and _is_csd) else "")),
        "PCR":                 round(pcr_val, 2),
        "PCDV":                round(pcdv_val, 2),
        "Slab Metric Used":    metric_label,
        "Productivity Score":  _prod_score,
        "Insta Txns (0.5×)":   insta_cnt_receipt,  # receipt-based (sir's col AR Insta rows)
        "Receipt Txns":        txn_count,
        "Renewal Txns":        rnl_count,
        # CMR+1 / SPS block -> "NA" for 0-90D (these columns only apply to SPS 91D+)
        "CMR+1 Sent":          ("NA" if (_is_new_joiner and _is_csd and not _is_csd_rm) else
                                (_c1_sent if (_is_csd and _c1_sent > 0) else "")),
        "CMR+1 Recd":          ("NA" if (_is_new_joiner and _is_csd and not _is_csd_rm) else
                                (_c1_map.get("mdc1_recd", 0) if (_is_csd and _c1_sent > 0) else "")),
        "MDC1 CMR+1%":         ("NA" if (_is_new_joiner and _is_csd) else
                                (round(float(cmr_plus1_pct) * 100 if float(cmr_plus1_pct) <= 1 else float(cmr_plus1_pct), 1)
                                 if (cmr_plus1_sent > 0 and _is_csd) else "")),
        "CMR+1 Multiplier":    ("NA" if (_is_new_joiner and _is_csd) else
                                (_cmr1_from_notes if _is_csd_rm
                                 else (_mdc1_mult_val if (_is_csd and _is_sps_vintage) else ""))),
        "Inc. Payout Mult":    ("NA" if (_is_new_joiner and _is_csd) else
                                (_inc_payout_mult if _is_csd else "")),
        "Inc. Per Txn (₹)":    ("NA" if (_is_new_joiner and _is_csd) else
                                (int(_per_txn_rate) if _is_csd and _prod_score > 0 else "")),
        "Net Incentive (₹)":   ("NA" if (_is_new_joiner and _is_csd) else
                                (int(_net_inc_before_boost) if _is_csd else "")),
        # SPS Booster: NA for 0-90D, value for SPS 91D+ employees
        "SPS Booster":         ("NA" if (_is_new_joiner and _is_csd) else
                                (_boost_val if (_is_csd and _is_sps_vintage) else "")),
        "Gross Inc w/ Boost (₹)": ("NA" if (_is_new_joiner and _is_csd) else
                                   (int(base_inc) if _is_csd else "")),
        # ── KCD columns matching sir's kcd_calc.xlsx layout ────────
        # Collection Target: formula teams (Listing/Catalog) only; slab teams → "-"
        "KCD Collection Target (₹)": (_kcd_coll_tgt if _kcd_is_lst_cat else ("-" if _is_kcd else "")),
        # Highest Collection: slab teams only (Regular/ROI/HVRI/Nagpur); formula teams → "-"
        "KCD Highest Collection (₹)": (_kcd_hc_slab if _kcd_is_slab else ("-" if _is_kcd else "")),
        # PCDV Target = HC/CA (slab) or Coll_Tgt/CA (formula)
        "KCD PCDV Target":            (_kcd_pcdv_tgt if _is_kcd else ""),
        # KCD PCDV% = PCDV / PCDV_Target × 100
        "KCD PCDV%":                  (_kcd_pcdv_pct if _is_kcd else ""),
        # WK productive transaction counts
        "BTL Productivity Count":   (int(btl_count) if ("KCD" in vertical and ("CATALOG" in str(team).upper() or "LISTING" in str(team).upper())) else ""),
        "KCD WK-1 Txns":  weekly_txn.get(1, 0) if ("KCD" in vertical and weekly_txn) else "",
        "KCD WK-2 Txns":  weekly_txn.get(2, 0) if ("KCD" in vertical and weekly_txn) else "",
        "KCD WK-3 Txns":  weekly_txn.get(3, 0) if ("KCD" in vertical and weekly_txn) else "",
        "KCD WK-4 Txns":  weekly_txn.get(4, 0) if ("KCD" in vertical and weekly_txn) else "",
        "KCD WK Total Txns": round(_kcd_prod, 1)       if "KCD" in vertical else "",
        "KCD BTL":           int(sb.get("btl_sales", 0)) if "KCD" in vertical else "",
        "KCD CMR Sent":      rnl_sent if "KCD" in vertical else "",
        "KCD CMR Recd":      cmr_data.get("renewal_received", 0) if "KCD" in vertical else "",
        "KCD CMR Ren%":      round(cmr_pct, 1) if "KCD" in vertical else "",
        "KCD SS+ Sent":      cmr_data.get("ss_sent", 0) if "KCD" in vertical else "",
        "KCD SS+ Recd":      cmr_data.get("ss_received", 0) if "KCD" in vertical else "",
        "KCD SS+ CMR%":      round(ss_cmr_pct, 1) if "KCD" in vertical else "",  # after SS+ Recd (issue 11)
        "KCD SS+Ren Mult":   _kcd_ss_mult if "KCD" in vertical else "",
        "KCD SS+ Penalty Applied": "Yes (50%)" if (_kcd_ss_mult == 0.5) else ("No" if "KCD" in vertical else ""),
        "KCD Incentive Multiplier": int(_kcd_per_txn)  if "KCD" in vertical else "",
        "KCD Base Incentive (₹)":   _kcd_base,
        "KCD Incremental (₹)":      _kcd_incr,
        "KCD Total Incentive (₹)":  int(_kcd_base + _kcd_incr + spot_inc) if "KCD" in vertical else "",
        "KCD Gross Incentive (₹)":  int(base_inc)  if "KCD" in vertical else "",
        "KCD Paid Incentive (₹)":   0              if "KCD" in vertical else "",
        "KCD Balance Incentive (₹)":int(base_inc)  if "KCD" in vertical else "",
        # Aliases matching sir's exact column names in kcd_calc.xlsx
        "Incentive Multiplier":     int(_kcd_per_txn) if "KCD" in vertical else "",
        "Incentive":                _kcd_base          if "KCD" in vertical else "",
        "SS+Ren Multiplier":        _kcd_ss_mult       if "KCD" in vertical else "",
        "Total Incentive (KCD)":    int(_kcd_base)     if "KCD" in vertical else "",
        "Gross Incentive (KCD)":    int(base_inc)      if "KCD" in vertical else "",
        "KCD Group":                str(team) if "KCD" in vertical else "",
        "KCD Delhi Loc Incentive":  ("Yes" if ("DELHI" in str(location).upper() and "KCD" in vertical) else "No") if "KCD" in vertical else "",
        "KCD Rem":                  ("Listing" if "LISTING" in str(team).upper() else
                                     "Catalog" if "CATALOG" in str(team).upper() else
                                     "ROI" if "ROI" in str(team).upper() else
                                     "Pharma" if "NAGPUR" in str(team).upper() else "-") if "KCD" in vertical else "",
        # ── Common output columns ─────────────────────────────────
        "Collection (₹)":      round(float(gross_collection or 0), 2),
        "Refund (₹)":          round(float(total_ref or 0), 2),
        "Net Collection (₹)":  round(float(net_dv or 0), 2),  # net_dv = net_collection from get_transactions
        "Deal Value (₹)":      round(float(gross_deal_val or 0), 2),
        "Deal Loss (₹)":       round(float(deal_loss or 0), 2),
        "Net Deal Value (₹)":  round(float(net_deal_val or 0), 2),
        "Client-A (aggregated)": int(client_cnt) if _is_l2_csd or (_desig_str == "L2" and "KCD" in vertical) else "",
        "Client-C (aggregated)": int(_client_c_val) if (_is_l2_csd and _client_c_val > 0) else "",
        "Catalog Client":      int(catalog_c) if catalog_c >= 0 else "",
        "Listing Client":      int(listing_c) if listing_c >= 0 else "",
        "Base Incentive (₹)":  int(base_inc),
        "PoP Incentive (₹)":   int(pop_inc),
        # Gross Incentive = min(Base+PoP, 20000) for 0-90D CSD; base+pop for all others
        "BA Multiplier":       _ba_mult_str if (_is_csd or "KCD" in vertical) else "",
        "Gross Incentive (₹)": (int(min(base_inc + pop_inc, S.get("new_joiner_cap", 20000)))
                                if (_is_new_joiner and _is_csd)
                                else int(base_inc + pop_inc)),
        # ── PoP tier counts (ALL CSD: filled; non-CSD: blank) — FSF cols 21-23 ──
        "MDC-Annual||TS-1":           (_pop_tier1 if _is_csd else ""),
        "MDC-MYR||TS-2||Maxi-A||VE": (_pop_tier2 if _is_csd else ""),
        "TS-3||Maxi-2":               (_pop_tier3 if _is_csd else ""),
        # ── PCDV breakdown (0-90D CSD: filled; SPS CSD: blank) — FSF cols 33-35 ──
        "PCDV Amount":           (int(_pcdv_amount)       if (_is_new_joiner and _is_csd) else ("-" if _is_csd else "")),
        "Incremental 3% Amount": (round(_incr_amount, 2)  if (_is_new_joiner and _is_csd) else ("-" if _is_csd else "")),
        "Final PCDV Amount":     (round(_final_pcdv, 2)   if (_is_new_joiner and _is_csd) else ("-" if _is_csd else "")),
        # ── Spot bifurcation ────────────────────────────────────────
        "FNT-1 Prod Count":    fnt1_prod_count,
        "FNT-1 Spot (₹)":     int(_fnt1_spot),
        "FNT-2 Prod Count":    fnt2_prod_count,
        "FNT-2 Spot (₹)":     int(_fnt2_spot),
        "IM Star Pro+ Spot (₹)": int(_im_star_spot) if _im_star_spot > 0 else (int(_im_star_pro_spot_kcd) if _im_star_pro_spot_kcd > 0 else 0),
        "WK-1 Prod Spot (₹)":   int(_wk1_spot),
        "Excellent Spot (₹)":   int(_excellent_spot),
        "IM Insta Spot (₹)":   int(_im_insta_spot),
        "MCATs Spot (₹)":      int(_mcats_spot),
        "Spot Incentive (₹)":  int(spot_inc),
        "Total Incentive (₹)": (int(min(base_inc + pop_inc, S.get("new_joiner_cap", 20000)) + spot_inc)
                               if (_is_new_joiner and _is_csd)
                               else int(base_inc + pop_inc + spot_inc)),
        "Scheme":              notes,
        "Scheme Type":         _derive_scheme_type(vintage, team, vertical, designation),
    }


def _derive_scheme_type(vintage, team, vertical, designation):
    """Human-readable scheme branch label shown in Scheme Type column."""
    _t = str(team).upper(); _v = str(vertical).upper(); _d = str(designation).upper().strip()
    if "CSD" in _v:
        if vintage in ("0-30D","31-90D") and _d not in ("L2",) and "REL" not in _d and "RM-" not in _d:
            return f"New Joiner {vintage}"
        if _d == "L2" or "REL" in _d or "RM-" in _d:
            return "Rel Mgr SPS" if "SPS" in _t else "Rel Mgr 31-90D"
        if "90+ DAYS" in _t.replace("_"," ") or "90+DAYS" in _t.replace(" ",""):
            return f"CSD 90+D {vintage}"     # Non-SPS 90+ days group
        if "SPS" in _t or vintage in ("91-270D","270D+","SPS"):
            return f"CSD SPS {vintage}"
        return f"CSD {vintage}"
    if "KCD" in _v:
        if "LISTING" in _t:  return f"KCD Listing {vintage}"
        if "CATALOG" in _t:  return f"KCD Catalog {vintage}"
        if "NAGPUR" in _t or "PHARMA" in _t: return f"KCD Nagpur {vintage}"
        if "HVRI" in _t:     return f"KCD HVRI {vintage}"
        if "ROI" in _t:      return f"KCD ROI {vintage}"
        if _d == "L2":       return f"KCD SAM {vintage}"
        return f"KCD Regular {vintage}"
    return _v or "Unknown"
# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════

st.title("💰 IndiaMart Incentive Calculator -- v31")
st.caption("Employee name from Renewal L1 column | CMR% auto-calculated | Slabs editable via config file")

# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Files")
    receipt_file    = st.file_uploader("1. Receipt file",           type=["xlsx", "xlsb"])
    refund_file     = st.file_uploader("2. Refund file",            type=["xlsx", "xlsb"])
    renewal_file    = st.file_uploader("3. Renewal file",           type=["xlsx", "xlsb"])
    if renewal_file:
        st.sidebar.caption(f"📎 Renewal: {renewal_file.name}")
    structure_file  = st.file_uploader("4. Employee Structure Dump",type=["xlsx", "xlsb"])
    slab_cfg_file   = st.file_uploader("5. Slab Config (optional)",   type=["xlsx", "xlsb"])

    st.divider()
    st.header("🎯 CMR% Targets File")
    st.caption("Upload the monthly targets file (xlsx or xlsb).")
    cmr_target_file = st.file_uploader("6. CMR Targets file", type=["xlsx", "xlsb"])
    kcd_target_file = st.file_uploader(
        "7. KCD Targets file (optional) -- upload kcd_calc-style file with "
        "Collection Target, PCR Target, Client-A, Listing/Catalog counts",
        type=["xlsx", "xlsb", "csv"])
    st.info("Individual Slab 1 & 2 targets are loaded per employee from this file.\n\n≤3 renewals sent → auto-forced Slab 1", icon="ℹ️")

    sam_ilp_file = st.file_uploader(
        "8. SAM-ILP Targets (optional) — ILP_Team_Deal_Value_Target.xlsb "
        "or any file with Employee ID + Target (In Lac) columns.",
        type=["xlsx", "xlsb", "csv"])

    st.divider()
    st.header("⚙️ Scheme Settings")

    # ── Period Date Ranges ────────────────────────────────────────────────
    with st.expander("📅 Period Date Ranges", expanded=False):
        st.caption("Set start/end dates for each period. Used to assign FNT and weekly labels to receipt rows.")
        _cur_month = sel_month if 'sel_month' in dir() else "May-26"
        # Default: May 2026
        _def_yr, _def_mo = 2026, 5
        try:
            import datetime as _dt
            _def_dt = pd.to_datetime(f"01-{_cur_month}", format="%d-%b-%y", errors="coerce")
            if pd.notna(_def_dt):
                _def_yr, _def_mo = _def_dt.year, _def_dt.month
        except: pass

        import datetime as _dt2
        _periods = {
            "FNT-1":  (_dt2.date(_def_yr, _def_mo, 1),  _dt2.date(_def_yr, _def_mo, 16)),
            "FNT-2":  (_dt2.date(_def_yr, _def_mo, 17), _dt2.date(_def_yr, _def_mo, 31) if _def_mo in [1,3,5,7,8,10,12] else _dt2.date(_def_yr, _def_mo, 30)),
            "WK-1":   (_dt2.date(_def_yr, _def_mo, 1),  _dt2.date(_def_yr, _def_mo, 9)),
            "WK-2":   (_dt2.date(_def_yr, _def_mo, 10), _dt2.date(_def_yr, _def_mo, 16)),
            "WK-3":   (_dt2.date(_def_yr, _def_mo, 17), _dt2.date(_def_yr, _def_mo, 23)),
            "WK-4":   (_dt2.date(_def_yr, _def_mo, 24), _dt2.date(_def_yr, _def_mo, 31) if _def_mo in [1,3,5,7,8,10,12] else _dt2.date(_def_yr, _def_mo, 30)),
        }
        _period_dates = {}
        _cols2 = st.columns(2)
        for pi, (pname, (pdef_s, pdef_e)) in enumerate(_periods.items()):
            with _cols2[pi % 2]:
                st.write(f"**{pname}**")
                _s = st.date_input(f"{pname} start", value=pdef_s, key=f"pd_{pname}_s",
                                   label_visibility="collapsed")
                _e = st.date_input(f"{pname} end",   value=pdef_e, key=f"pd_{pname}_e",
                                   label_visibility="collapsed")
                _period_dates[pname] = (_s, _e)
        # Store in session state for use in enrich_receipt
        st.session_state["period_dates"] = _period_dates

    metric_mode = st.radio(
        "Base metric",
        ["PCDV (Per Client Deal Value)", "PCR (Per Client Collection)"],
        index=0,
        help="PCDV uses deal value; PCR uses actual collection. Both use WT AMT column -- "
             "select to match the month's scheme. Change slabs via Slab Config file."
    )
    use_pcr = metric_mode.startswith("PCR")

    with st.expander("⚙️ Advanced overrides (normally set by Slab Config)"):
        st.caption("These override the Slab Config values only for this session. "
                   "For permanent changes, edit the **Scheme_Params** sheet in the Slab Config Excel.")
        def_tat  = st.number_input("Ext. Ticket TAT threshold (SPS booster)", 0.0, 10.0,
                                   1.0, 0.5,
                                   help="SPS booster applies when ext ticket TAT is below this. Default=1.0 (set in Scheme_Params)")
        def_d60  = st.number_input("60D Not Met % threshold (SPS booster)", 0.0, 100.0,
                                   10.0, 1.0,
                                   help="SPS booster applies when 60D not met % is below this. Default=10 (set in Scheme_Params)")

    with st.expander("Spot Rate"):
        def_nr   = st.number_input("CSD NR Upsell/AMR count", 0, 50, 0)
        def_btl  = st.number_input("KCD Base-to-Listing sales", 0, 20, 0)
        def_spot = st.checkbox("KCD Spot multiplier met (≥2 SS+ sales)?")

    sb = dict(ext_tat=def_tat, d60=def_d60,
              nr_upsell=def_nr, btl_sales=def_btl, spot_met=def_spot,
              use_pcr=use_pcr)

    st.divider()
    st.header("📅 Select Month")
    selected_month = st.selectbox(
        "Calculate incentives for",
        options=["(Upload files first)"],
        key="month_selector",
        help="All calculations -- PCDV, CMR%, Productivity -- will be for this month only"
    )
    st.divider()
    col_calc, col_enrich = st.columns(2)
    with col_calc:
        calc_btn = st.button("▶ Calculate Incentives", type="primary", use_container_width=True)
    with col_enrich:
        enrich_btn = st.button("📋 Generate Enriched Receipt",
                               use_container_width=True,
                               help="Generate receipt file with all computed columns (Day, Week, Productivity, AMR etc.) for review/editing. Upload the edited file back as Receipt to recalculate.")


# ── Slab Config download ──────────────────────────────────────
st.subheader("Step 0 -- Download Slab Config (one-time setup)")
with st.expander("What is the Slab Config file?", expanded=not slab_cfg_file):
    st.markdown("""
The **Slab Config** is an Excel file with one sheet per incentive table.
Edit any value in it -- PCDV thresholds, payout amounts, incremental rates -- and
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

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.download_button(
        "⬇️ Download May 2026 Slab Config",
        data=make_may_slab_config_excel(),
        file_name="Slab_Config_May2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with col_b:
    st.download_button(
        "⬇️ Download April 2026 Slab Config",
        data=make_april_slab_config_excel(),
        file_name="Slab_Config_April2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with col_c:
    st.download_button(
        "⬇️ Download March 2026 Slab Config (PCR)",
        data=make_march_slab_config_excel(),
        file_name="Slab_Config_March2026_PCR.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# Load and parse slab config (uses defaults if not uploaded)
slab_cfg_raw = load_slab_config(slab_cfg_file)
S = parse_slabs(slab_cfg_raw)

# ── Detect which month config is loaded ──────────────────────────────────────
_is_may_cfg = "CSD_SPS_91_270_May" in slab_cfg_raw or "CSD_Spot_May" in slab_cfg_raw
_is_apr_cfg = "CSD_Spot_Apr" in slab_cfg_raw or "CSD_SPS_91_270_Apr" in slab_cfg_raw
if _is_may_cfg:
    _cfg_label = "May 2026"
elif _is_apr_cfg:
    _cfg_label = "April 2026"
else:
    _cfg_label = "March 2026 (default)"

if slab_cfg_file:
    st.success(f"✅ Slab Config loaded — **{_cfg_label}** scheme values active.")
else:
    st.info(f"📋 No config uploaded — using built-in **{_cfg_label}** defaults. "
            "Download the May 2026 config above, edit if needed, then upload.", icon="ℹ️")

with st.expander("📊 Active Scheme Parameters (click to verify before calculating)", expanded=False):
    st.caption("These are the values currently being used in calculations. "
               "Edit the **Scheme_Params** sheet in your Slab Config to change any of these.")
    _sp_display = [
        ("🏦 CSD New Joiner Cap (₹)",            S.get("new_joiner_cap", 20000)),
        ("📊 CSD PoP min CMR% gate",              S.get("pop_cmr_floor", 55)),
        ("📈 CSD New Joiner Incremental Rate",    f"{S.get('new_joiner_cap', 20000) and '3%'} above top PCDV slab"),
        ("🎯 CSD MDC-1 High threshold%",          S.get("mdc1_hi_thr", 35)),
        ("🎯 CSD MDC-1 Mid threshold%",           S.get("mdc1_mid_thr", 25)),
        ("✖️ CSD MDC-1 High / Mid / Low mult",    f"{S.get('mdc1_hi_mult',1.2):.0%} / {S.get('mdc1_mid_mult',1.0):.0%} / {S.get('mdc1_low_mult',0.5):.0%}"),
        ("🚀 CSD SPS Booster (TAT < / 60D <)",   f"{S.get('boost_tat_thr',1)} / {S.get('boost_60d_thr',10)}%  → {S.get('boost_mult',1.2):.0%}"),
        ("💼 CSD RM CMR min / Slab1 / Slab2",    f"{S.get('rm_cmr_min',53):.0f}% / {S.get('rm_cmr_slab1',60):.0f}% / {S.get('rm_cmr_slab2',65):.0f}%"),
        ("🟢 KCD SS+ threshold%",                 S.get("kcd_ss_threshold", 72)),
        ("🟢 KCD CMR Slab2 threshold%",           S.get("kcd_slab2_target", 80)),
        ("📦 KCD Min Prod / week / month / new",  f"{S.get('kcd_min_prod_week',2)} / {S.get('kcd_min_prod_month',8)} / {S.get('kcd_min_prod_new',6)}"),
        ("📈 KCD Incremental rate (Regular / Nagpur)", f"{S.get('kcd_incr_rate',0.014):.2%} / {S.get('kcd_incr_nagpur',0.0085):.2%}"),
        ("📈 KCD SAM Incremental (Regular / Nagpur)",  f"{S.get('kcd_sam_incr_rate',0.0065):.2%} / {S.get('kcd_sam_nagpur_incr',0.0045):.2%}"),
        ("⚡ IM Insta L1 / L2 rate (₹)",          f"₹{S.get('insta_l1_rate',300)} / ₹{S.get('insta_l2_rate',150)}"),
        ("⚡ IM Insta min week / month",           f"{S.get('insta_min_week',2)} / {S.get('insta_min_month',7)}"),
        ("🏆 MCATs L1 / L2 rate (₹)",             f"₹{S.get('mcats_l1_rate',1000)} / ₹{S.get('mcats_l2_rate',500)}  from {S.get('mcats_min_count',2)+1}th MCAT"),
        ("⭐ IM Star Pro+ spot rate (₹)",          f"₹{S.get('im_star_rate',1000)} from day {S.get('im_star_from_day',28)}"),
        ("🏔️ KCD HC mult Regular / ROI / HVRI / Nagpur / SAM",
         f"×{S.get('hc_mult_regular',21000):,} / ×{S.get('hc_mult_roi',14000):,} / ×{S.get('hc_mult_hvri',17000):,} / ×{S.get('hc_mult_nagpur',32000):,} / ×{S.get('hc_mult_sam',17000):,}"),
        ("📐 CSD BM/RM AOP rates (% of DV)",  f"BM={S.get('CSD_BM_AOP_Rate_%',0.01):.2%}  RM={S.get('CSD_RM_AOP_Rate_%',0.007):.2%}  |  Cap: BM={S.get('CSD_BM_AOP_Cap_%',0.05):.0%} RM={S.get('CSD_RM_AOP_Cap_%',0.04):.0%}"),
        ("📐 KCD BM/RM AOP rates (% of DV)",  f"BM={S.get('KCD_BM_AOP_Rate_%',0.005):.3%}  RM={S.get('KCD_RM_AOP_Rate_%',0.0035):.3%}  |  Cap: {S.get('KCD_BM_AOP_Cap_%',0.02):.0%}"),
        ("📊 AOP achievement multipliers",     f"95-100%→{S.get('AOP_Mult_95_100_%',1.0):.0%}  100-105%→{S.get('AOP_Mult_100_105_%',1.1):.0%}  105-110%→{S.get('AOP_Mult_105_110_%',1.2):.0%}  110%+→{S.get('AOP_Mult_110_Plus_%',1.3):.0%}"),
    ]
    col1, col2 = st.columns(2)
    for i, (label, val) in enumerate(_sp_display):
        (col1 if i % 2 == 0 else col2).metric(label, val)


# ── Step 1: Structure Dump info ──────────────────────────────
st.subheader("Step 1 -- Upload your Employee Structure file")

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

# ── Load all files (cached -- only re-reads when file actually changes) ────
receipt_df_raw  = clean_receipt(_read_file(receipt_file))
refund_df_raw   = _read_file(refund_file)
renewal_df_raw  = _read_file(renewal_file)
struct_map      = load_structure_dump(structure_file)
cmr_targets     = load_cmr_targets(cmr_target_file)
kcd_targets     = load_kcd_targets(kcd_target_file) if kcd_target_file else {}
sam_ilp_targets = load_sam_ilp_targets(sam_ilp_file) if sam_ilp_file else {}

if not struct_map or len(struct_map) == 0:
    st.error("Could not read the structure file. Check column names.")
    st.stop()
if not cmr_targets:
    st.warning("⚠️ No CMR Targets file -- fallback: Slab 1=70%, Slab 2=80%", icon="⚠️")

# ── Step 1 preview -- reuse already-loaded struct_map (no second file parse) ──
struct_preview = pd.DataFrame([
    {"Employee ID": k, "Name": v["Employee Name"],
     "Vertical": v["Vertical"], "Vintage": v["Vintage"],
     "Team": v["Team"], "Client Count": v["Client Count"],
     "Location": v["Location"],
     "Joining Date": str(v["Joining Date"])[:10] if v["Joining Date"] else ""}
    for k, v in struct_map.items()
])
st.success(f"✅ Structure file loaded -- {len(struct_map)} employees auto-configured")
with st.expander("Preview auto-derived settings per employee"):
    st.dataframe(struct_preview, use_container_width=True, hide_index=True)

# ── Step 2: Calculate ─────────────────────────────────────────
st.subheader("Step 2 -- Calculate Incentives")

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
            f"📅 **{sel_month}** -- Receipt: **0 rows** after month filter "
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
        rnl_count = len(renewal_df) if renewal_df is not None else 0
        if rnl_count == 0 and renewal_df_raw is not None and len(renewal_df_raw) > 0:
            st.warning(
                f"⚠️ **{sel_month}** -- Renewal: **0 rows** after month filter "
                f"(raw has {len(renewal_df_raw)} rows). "
                "The renewal file month format may not match. "
                "Check that months in the renewal file are formatted as e.g. May apostrophe 26.",
                icon="⚠️")
        else:
            _p1 = int((receipt_df["Productivity"]==1).sum()) if "Productivity" in receipt_df.columns else "N/A"
            st.info(f"📅 **{sel_month}** -- "
                    f"Receipt: {len(receipt_df)} rows | "
                    f"Refund: {len(refund_df)} rows | "
                    f"Renewal: {rnl_count} rows | Productive: {_p1}")
else:
    receipt_df, refund_df, renewal_df = receipt_df_raw, refund_df_raw, renewal_df_raw

# ── Enrich receipt: Productivity + Service_Tier ───────────────
# If the uploaded receipt is pre-enriched (already has Productivity column),
# use its values directly — don't re-compute and overwrite them.
_prod_col_existing = find_col(receipt_df, ["Productivity", "PRODUCTIVITY"])
_is_pre_enriched = (
    _prod_col_existing is not None
    and receipt_df[_prod_col_existing].notna().sum() > 0
    and receipt_df[_prod_col_existing].dtype in [int, float, 'int64', 'float64',
                                                  'Int64', 'Int32', 'object']
    and receipt_df[_prod_col_existing].astype(str).str.strip().isin(['0','1','0.0','0.5','1.0']).mean() > 0.7
)
if _is_pre_enriched:
    # Pre-enriched: standardise column name to "Productivity" but trust the values
    if _prod_col_existing != "Productivity":
        receipt_df = receipt_df.rename(columns={_prod_col_existing: "Productivity"})
    # Still run enrich to fill Service_Tier if missing, but do NOT overwrite existing columns
    _svc_col_existing = find_col(receipt_df, ["Service_Tier","Service","SERVICE_TIER"])
    # Cols written by enrich_receipt that we want to preserve from the uploaded enriched file
    _enrich_written = ["Productivity","Service_Tier","Base to List Sale","AMR","IM Varient","Pref SS+","FNT","Deal Val (WOT)","_has_upsell_on_receipt","_is_pure_renewal","_is_upsell"]
    _saved_cols = {c: receipt_df[c].copy() for c in _enrich_written if c in receipt_df.columns}
    if _svc_col_existing is None and "Service_Tier" not in _saved_cols:
        _enriched_temp = enrich_receipt(receipt_df)
        receipt_df["Service_Tier"] = _enriched_temp.get("Service_Tier", 0)
    # Restore all pre-enriched columns (don't let enrich_receipt overwrite them)
    for _c, _vals in _saved_cols.items():
        receipt_df[_c] = _vals
    _prod_after = int((receipt_df['Productivity']==1).sum())
    _svc_present = "Service_Tier" in _saved_cols
    st.sidebar.caption(f"✅ Pre-enriched: {_prod_after} productive rows | "
                       f"saved_cols={list(_saved_cols.keys())[:4]} | svc_in_saved={_svc_present}")
else:
    receipt_df = enrich_receipt(receipt_df)

# ── CMR% from month-filtered renewal data ────────────────────
cmr_map     = calc_cmr_per_employee(renewal_df)
# For CSD L2 Rel Mgr: CMR uses L2 name col in renewal (FSF Renewal.AX = L2 ID mapped to name)
_rnl_l2_col = find_col(renewal_df, ["L2", "L2 Name", "L2Name", "RM Name"]) if (
    renewal_df is not None and isinstance(renewal_df, pd.DataFrame) and len(renewal_df) > 0) else None
if _rnl_l2_col and struct_map:
    try:
        _l2_cmr_by_name = calc_cmr_per_employee_by_col(renewal_df, _rnl_l2_col)
        for _eid3, _sd3 in struct_map.items():
            if str(_sd3.get("Designation","")).upper() == "L2":
                _nm3 = str(_sd3.get("Employee Name","")).strip()
                if _nm3 and _nm3 in _l2_cmr_by_name:
                    cmr_map[_eid3] = _l2_cmr_by_name[_nm3]
    except Exception:
        pass
# Build per-employee MDC client count from structure file
mdc_client_counts_map = {
    eid: s.get("MDC Client Count", 0)
    for eid, s in struct_map.items()
    if s.get("MDC Client Count", 0) > 0
}
# Current month CMR% (all renewals) - for CSD L1 slab multiplier (FSF AW column)
all_cmr_map  = calc_all_cmr_per_employee(renewal_df)
# For CSD L2 Rel Mgr: renewal uses L2 name col (not EMP ID) - FSF AX col = L2 ID
_l2_name_col_rnl = None
if renewal_df is not None and isinstance(renewal_df, pd.DataFrame) and len(renewal_df) > 0:
    _l2_name_col_rnl = find_col(renewal_df, ["L2", "L2 Name", "L2Name", "RM Name"])
if _l2_name_col_rnl and struct_map:
    try:
        _l2_name_cmr = calc_all_cmr_per_employee(renewal_df, emp_col_override=_l2_name_col_rnl)
        for _eid2, _sdata2 in struct_map.items():
            if str(_sdata2.get("Designation","")).upper() == "L2":
                _l2name2 = str(_sdata2.get("Employee Name","")).strip()
                if _l2name2 and _l2name2 in _l2_name_cmr:
                    all_cmr_map[_eid2] = _l2_name_cmr[_l2name2]
    except Exception:
        pass

mdc1_cmr_map = calc_mdc1_cmr_per_employee(renewal_df, mdc_client_counts_map or None,
                                           month_offset=0, sel_month_str=sel_month)
if _l2_name_col_rnl and struct_map:
    try:
        _l2_name_mdc1 = calc_mdc1_cmr_per_employee(renewal_df, emp_col_override=_l2_name_col_rnl)
        for _eid2, _sdata2 in struct_map.items():
            if str(_sdata2.get("Designation","")).upper() == "L2":
                _l2name2 = str(_sdata2.get("Employee Name","")).strip()
                if _l2name2 and _l2name2 in _l2_name_mdc1:
                    mdc1_cmr_map[_eid2] = _l2_name_mdc1[_l2name2]
    except Exception:
        pass
# CMR+1% = NEXT month's renewals (sir's formula: Month="Jun'26" when May calc)
# Use renewal_df_raw (unfiltered) so June rows are visible when renewal_df only has May
_rnl_for_plus1 = renewal_df_raw if (renewal_df_raw is not None and len(renewal_df_raw) > 0) else renewal_df
cmr_plus1_map = calc_mdc1_cmr_per_employee(_rnl_for_plus1, mdc_client_counts_map or None,
                                            month_offset=1, sel_month_str=sel_month)
# Add L2 RM CMR+1 via employee name column in renewal file
# Always run this (not gated on cmr_plus1_map being empty) so Rel Mgr always gets CMR+1
_l2_plus1_mdc1 = {}
if _l2_name_col_rnl and struct_map:
    try:
        _l2_plus1_mdc1 = calc_mdc1_cmr_per_employee(_rnl_for_plus1,
                                                      emp_col_override=_l2_name_col_rnl,
                                                      month_offset=1, sel_month_str=sel_month)
    except Exception:
        pass
# Also try L2 by EMP ID directly (same as L1 — renewal file may have L2 IDs)
for _eid3, _sd3 in struct_map.items():
    if str(_sd3.get("Designation","")).upper() == "L2":
        if _eid3 not in cmr_plus1_map:
            # Try match by employee name
            _n3 = str(_sd3.get("Employee Name","")).strip()
            if _n3 and _n3 in _l2_plus1_mdc1:
                cmr_plus1_map[_eid3] = _l2_plus1_mdc1[_n3]
        # If still not found, cmr_plus1_map[_eid3] remains empty (no fallback to MDC1)

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
    import builtins as _bt
    _fdbg = getattr(_bt, '_renewal_filter_debug', None)
    _rnl_rows = len(renewal_df) if renewal_df is not None else 0
    if len(cmr_map) == 0:
        _eid_debug = find_col(renewal_df, ["EMP ID", "Emp ID", "EmpID", "Employee ID", "EMPID", "CC Emp ID", "emp id"]) if _rnl_rows > 0 else None
        st.warning(
            f"⚠️ CMR map empty! "
            f"renewal_df={_rnl_rows} rows (filter: {_fdbg}). "
            f"EMP ID col: {_eid_debug!r}. "
            f"Cols: {list(renewal_df.columns[:5]) if _rnl_rows > 0 else 'N/A'}",
            icon="⚠️")
    else:
        # Spot check: look up specific employees in cmr_map
        st.caption(f"✅ cmr_map={len(cmr_map)} employees | renewal_df={_rnl_rows} rows")
    if cmr_targets:
        st.success(f"✅ CMR Targets loaded for {len(cmr_targets)} employees")
    else:
        st.warning("⚠️ No CMR Targets -- fallback 70%/80% applied")


# ── Step 1: Generate Enriched Receipt ─────────────────────────────────────────
if enrich_btn:
    if not receipt_file:
        st.error("Please upload a Receipt file first (sidebar → Input Files → Receipt).")
    else:
        with st.spinner("Enriching receipt file with computed columns…"):
            try:
                import io as _io
                rec_raw = _read_file(receipt_file)
                rec_raw.columns = [str(c).strip() for c in rec_raw.columns]
                rec_raw = rec_raw.loc[:, ~rec_raw.columns.astype(str).str.lower().str.startswith("unnamed")]
                rec_raw = rec_raw.loc[:, rec_raw.columns.astype(str).str.strip() != ""]

                # Use sir's exact enrichment function (enrich_receipt)
                rec_enriched = enrich_receipt(rec_raw)

                prod_col_e   = find_col(rec_enriched, ["Prod","Product","PRODUCT"])
                upsell_col_e = find_col(rec_enriched, ["Unique","Upsell","UNIQUE"])
                rcpt_id_e    = find_col(rec_enriched, ["Receipts ID","Receipt ID","ReceiptID"])

                def _se(v): return str(v).strip() if pd.notna(v) and str(v).strip()!="nan" else ""

                # Upsell column: "Yes" if Unique not blank (sir step 2)
                if upsell_col_e:
                    rec_enriched["Upsell"] = rec_enriched[upsell_col_e].apply(
                        lambda x: "Yes" if _se(x)!="" else "")

                # Pure Renewal column: "Yes" if Prod in renewal list (sir step 3)
                if prod_col_e:
                    rec_enriched["Pure Renewal"] = rec_enriched[prod_col_e].apply(
                        lambda x: "Yes" if _se(x) in PURE_RENEWAL_PRODUCTS else "")

                # all Upsell: "Yes" for all rows on a receipt that has any upsell (sir step 4)
                if rcpt_id_e and "Upsell" in rec_enriched.columns:
                    _ups_ids = set(rec_enriched.loc[rec_enriched["Upsell"]=="Yes", rcpt_id_e].tolist())
                    rec_enriched["all Upsell"] = rec_enriched[rcpt_id_e].apply(
                        lambda x: "Yes" if x in _ups_ids else "")

                # Service column: MDC tier label (sir's assign_service)
                def _svc(row):
                    if row.get("Productivity",0) != 1: return ""
                    u = _se(row[upsell_col_e]) if upsell_col_e else ""
                    p = _se(row[prod_col_e]) if prod_col_e else ""
                    e = _se(row.get("Exp",""))
                    if u in ("", "Yes", "No", "yes", "no"):
                        # Generic boolean flag — no tier info, use product
                        pass
                    elif u == "Combo 1YR": return "MDC-Annual||TS-1"
                    elif u in UPSELL_TIER1: return "MDC-Annual||TS-1"
                    elif u in UPSELL_TIER2: return "MDC-MYR||TS-2||Maxi-A||VE"
                    elif "MYR" in u.upper(): return "MDC-MYR||TS-2||Maxi-A||VE"
                    elif u in UPSELL_TIER3: return "TS-3||Maxi-2"
                    elif u != "": return "TS-3||Maxi-2"
                    if p in PROD_TIER1: return "MDC-Annual||TS-1"
                    if p in PROD_TIER2: return "MDC-MYR||TS-2||Maxi-A||VE"
                    if p in PROD_TIER3: return "TS-3||Maxi-2"
                    return ""
                rec_enriched["Service"] = rec_enriched.apply(_svc, axis=1)

                # L2-L6 hierarchy
                _p_c_e = find_col(rec_enriched, ["Sales Exec ID","EMP ID","L1 ID"])
                if _p_c_e and 'struct_map' in dir() and struct_map:
                    def _he(v):
                        s=struct_map.get(str(v).split('.')[0].strip(),{})
                        return {k: s.get(k,"") for k in
                                ["L2 ID","L2 Name","L3 ID","L3 Name","L4 ID","L4 Name","L5 ID","L5 Name"]}
                    _hdf_e = rec_enriched[_p_c_e].apply(lambda v: pd.Series(_he(v)))
                    for _hc_e in _hdf_e.columns:
                        if _hc_e not in rec_enriched.columns:
                            rec_enriched[_hc_e] = _hdf_e[_hc_e]

                # Write output
                _buf = _io.BytesIO()
                with pd.ExcelWriter(_buf, engine="xlsxwriter") as _w:
                    rec_enriched.to_excel(_w, sheet_name="Receipt Data", index=False, startrow=1)
                    _ws = _w.sheets["Receipt Data"]
                    _hf = _w.book.add_format({"bold":True,"bg_color":"#595959","font_color":"#FFFFFF","font_size":10})
                    _yel= _w.book.add_format({"italic":True,"bg_color":"#FFF2CC","font_color":"#595959","font_size":8})
                    _ws.write(0, 0, "Receipt Data — edit computed columns then re-upload as Receipt to recalculate.")
                    _EDIT = {"Productivity","Upsell","Pure Renewal","all Upsell","Service",
                             "AMR","L2 ID","L2 Name","L3 ID","L3 Name","L4 ID","L4 Name"}
                    for _ci, _col in enumerate(rec_enriched.columns):
                        _ws.write(1, _ci, _col, _hf)
                        _ws.set_column(_ci, _ci, max(14, len(str(_col))+2))
                        if _col in _EDIT:
                            _ws.write(0, _ci, f"↓ {_col}", _yel)
                    _ws.freeze_panes(2, 0)

                st.download_button(
                    label="⬇ Download Enriched Receipt",
                    data=_buf.getvalue(),
                    file_name=f"Receipt_Enriched_{pd.Timestamp.now().strftime('%d%m%Y')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                _pc = int((rec_enriched.get("Productivity",pd.Series(0))==1).sum())
                st.success(f"✅ {len(rec_enriched):,} rows | {_pc:,} productive rows")
                st.info(
                    "**Sir's exact logic (matches sir's Python script):**\n"
                    "- **Upsell** = Yes if `Unique` not blank\n"
                    "- **Pure Renewal** = Yes if `Prod` is in the renewal product list\n"
                    "- **all Upsell** = Yes for every row whose Receipt ID has any upsell\n"
                    "- **Productivity** = 1 if Upsell=Yes OR (Pure Renewal=Yes AND all Upsell=\'\')\n"
                    "- **Service** = MDC-Annual||TS-1 / MDC-MYR||TS-2||Maxi-A||VE / TS-3||Maxi-2\n\n"
                    "Upload edited file back as Receipt then click **▶ Calculate Incentives**.")
            except Exception as _e:
                st.error(f"Error: {_e}")
                import traceback; st.code(traceback.format_exc())


if calc_btn:
    results = []
    prog    = st.progress(0, "Calculating…")

    emp_ids = list(struct_map.keys())
    for i, emp_id in enumerate(emp_ids):
        s = struct_map[emp_id]          # all employee details from structure dump

        # ── Exclude employees that don't run through L1/L2 incentive scheme ──
        _desig_main = str(s.get("Designation","")).upper().strip()
        _vert_main  = str(s.get("Vertical","")).upper()

        # L3 (BM) and L4 (RM) are handled by build_bm_rm_rows separately
        if _desig_main in ("L3","L4"):
            continue

        # Tele Annual, Inside Sales, etc. — no incentive scheme
        if any(excl in _vert_main for excl in
               ["TELE ANNUAL","TELEANNUAL","INSIDE SALES","TELESALES","INBOUND"]):
            continue

        emp_cmr = cmr_map.get(emp_id, {
            "cmr_pct": 0.0, "ss_cmr_pct": 0.0,
            "renewal_sent": 0, "renewal_received": 0,
            "ss_sent": 0, "ss_received": 0, "l1_name": "",
        })

        # Employee name: L1 from renewal > structure dump name
        emp_name = emp_cmr.get("l1_name", "").strip() or s["Employee Name"]

        # Per-employee CMR targets
        emp_targets = cmr_targets.get(emp_id, {"slab1": 70.0, "slab2": 80.0})
        # Apply KCD targets override (from uploaded kcd_targets file)
        if s.get("Vertical","") == "KCD" and kcd_targets.get(emp_id):
            _kt = kcd_targets[emp_id]
            s = dict(s)
            # Always apply client counts and targets from the dedicated target file
            if _kt.get("client_a", 0) > 0:
                s["Client Count"]      = _kt["client_a"]
            if _kt.get("listing", 0) > 0:
                s["Listing Clients"]   = _kt["listing"]
            if _kt.get("catalog", 0) > 0:
                s["Catalog Clients"]   = _kt["catalog"]
            if _kt.get("coll_target", 0) > 0:
                s["Collection Target"] = _kt["coll_target"]
                s["PCR Target"]        = _kt["pcr_target"]
            # Apply team from target file if not already set in structure file
            if _kt.get("team", "") and not any(
                    k in str(s.get("Team","")).upper()
                    for k in ["LISTING","CATALOG","HVRI","NAGPUR","ROI"]):
                _team_from_file = str(_kt["team"]).strip()
                if "LISTING" in _team_from_file.upper():
                    s["Team"] = "Listing (KCD)"
                elif "CATALOG" in _team_from_file.upper():
                    s["Team"] = "Catalog (KCD)"

        # ── KCD team re-routing after client counts are resolved ─────────────
        # Listing/Catalog columns may not exist in structure file by name.
        # Re-route based on client ratios ONLY when Group didn't already set a specific team
        if "KCD" in str(s.get("Vertical","")).upper():
            _cur_team = str(s.get("Team","")).upper()
            _grp_set  = bool(s.get("Group","") and s.get("Group","") not in ("-",""))
            _is_default_team = not any(k in _cur_team
                                        for k in ["LISTING","CATALOG","HVRI","NAGPUR","ROI"])
            # Derive Catalog/Listing client counts from Group/Sub Group when not in target file
            _ca_total = float(s.get("Client Count", 0) or 0)
            if "LISTING" in _cur_team and float(s.get("Listing Clients", 0) or 0) == 0 and _ca_total > 0:
                s = dict(s); s["Listing Clients"] = _ca_total; s["Catalog Clients"] = 0
            elif "CATALOG" in _cur_team and float(s.get("Catalog Clients", 0) or 0) == 0 and _ca_total > 0:
                s = dict(s); s["Catalog Clients"] = _ca_total; s["Listing Clients"] = 0
            elif _ca_total > 0 and float(s.get("Catalog Clients", 0) or 0) == 0 and float(s.get("Listing Clients", 0) or 0) == 0:
                # Regular/ROI/HVRI/Nagpur KCD: all clients are catalog-type by default
                s = dict(s); s["Catalog Clients"] = _ca_total; s["Listing Clients"] = 0
            if _is_default_team and not _grp_set:
                _lc_rt  = float(s.get("Listing Clients", 0) or 0)
                _cat_rt = float(s.get("Catalog Clients", 0) or 0)
                _ca_rt  = float(s.get("Client Count", 1) or 1)
                _lcat_total = _lc_rt + _cat_rt
                if _ca_rt > 0 and _lc_rt / _ca_rt >= 0.55:
                    s = dict(s); s["Team"] = "Listing (KCD)"
                elif _ca_rt > 0 and _cat_rt / _ca_rt >= 0.55:
                    s = dict(s); s["Team"] = "Catalog (KCD)"
                elif _ca_rt > 0 and _lcat_total / _ca_rt >= 0.70:
                    # Mixed Listing+Catalog majority → Listing (more common)
                    s = dict(s); s["Team"] = "Listing (KCD)" if _lc_rt >= _cat_rt else "Catalog (KCD)"

        emp_sb = {**sb,
                  "csd_slab1_target": emp_targets["slab1"],
                  "csd_slab2_target": emp_targets["slab2"],
                  "kcd_slab1_target": emp_targets["slab1"],
                  "kcd_slab2_target": emp_targets["slab2"],
                  "sel_month": sel_month if sel_month else ""}

        _is_l2_tx = str(s.get("Designation","")).upper().strip() == "L2"
        (net_dv, txn_count, prods, rnl_prods, rnl_modes,
         rnl_count, total_ref, all_rnl_count,
         svc_tiers, insta_cnt_receipt, prod_score_receipt,
         gross_collection, gross_deal_val, deal_loss, net_deal_val,
         nr_upsell_count, weekly_dv, weekly_txn,
            fnt1_prod_count, fnt2_prod_count,
            pref_ss_count, btl_count, im_var_count,
            fnt1_pcdv, fnt2_pcdv,
            weekly_prod_counts, im_star_pro_count,
            wk1_prod_counts, excellent_txn_count,
            computed_client_c, prod_score_receipt_int) = \
            get_transactions(receipt_df, refund_df, renewal_df, emp_id,
                             client_a=float(s.get("Client Count", 0) or 0),
                             is_l2=_is_l2_tx,
                             emp_name=str(s.get("Employee Name", "")))

        # Build cfg_row and emp_row from structure map
        cfg_row = {
            "Vertical":           s.get("Vertical", ""),
            "Location":           s.get("Location", ""),
            "Vintage":            s.get("Vintage", ""),
            "Team":               s.get("Team", ""),
            "Client Count":       s.get("Client Count", 1),
            # Client-C: directly from FSF_TA (pre-computed Calculated Clients column)
            "Client-C":           float(s.get("Client-C", 0) or 0),
            "Joining Date":       s.get("Joining Date", None),
            "Listing Clients":    s.get("Listing Clients", 0),
            "Catalog Clients":    s.get("Catalog Clients", 0),
            "PCR Target":         s.get("PCR Target", 0),
            "Collection Target":  s.get("Collection Target", 0),
            "Effective Team Size": int(s.get("Effective Team Size", 1) or 1),
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
                             all_cmr_pct=all_cmr_map.get(emp_id, {}).get("cmr_pct", None),
                             all_cmr_sent=all_cmr_map.get(emp_id, {}).get("cmr_sent", 0),
                             cmr_plus1_pct=cmr_plus1_map.get(emp_id, {}).get("mdc1_cmr_pct", 0.0),
                             cmr_plus1_sent=cmr_plus1_map.get(emp_id, {}).get("mdc1_sent", 0),
                             nr_upsell_count=nr_upsell_count,
                             net_deal_val=net_deal_val,
                             collection_target=s.get("Collection Target", 0),
                             vintage_bucket=s.get("Vintage Bucket", ""),
                             designation=s.get("Designation", ""),
                             weekly_dv=weekly_dv,
                             wk1_prod_counts=wk1_prod_counts,
                             excellent_txn_count=excellent_txn_count)
        except Exception as _e:
            inc = {"CMR% (auto)": 0, "SS+ CMR% (auto)": 0,
                "CMR Slab1 Target": "", "CMR Slab2 Target": "",
                "CMR Sent": 0, "CMR Received": 0, "CMR Slab": "Error",
                "SS+ Sent": 0, "SS+ Received": 0,
                "MDC-1 CMR%": "", "PCR": 0, "PCDV": 0, "Slab Metric Used": "",
                "Productivity Score": 0, "Insta Txns (0.5×)": 0,
                "Receipt Txns": 0, "Renewal Txns": 0,
                "CMR+1 Sent": "", "CMR+1 Recd": "",
                "MDC1 CMR+1%": "", "CMR+1 Multiplier": "", "Inc. Payout Mult": "",
                "Inc. Per Txn (₹)": "", "Net Incentive (₹)": "",
                "SPS Booster": "", "Gross Inc w/ Boost (₹)": "",
                "KCD Base Incentive (₹)": 0, "KCD Incremental (₹)": 0,
                "KCD SS+ CMR%": "", "KCD SS+ Sent": "", "KCD SS+ Recd": "",
                "KCD SS+Ren Mult": "", "KCD SS+ Penalty Applied": "",
                "KCD Gross Incentive (₹)": 0,
                "Base Incentive (₹)": 0, "PoP Incentive (₹)": 0,
                "Spot Incentive (₹)": 0, "Total Incentive (₹)": 0,
                "Scheme": f"ERROR: {_e}",
            }


        results.append({
            # ── Fields from inc (calculation results) ─────────────────
            **inc,
            # ── Static fields -- always override anything inc may have set ──
            "Employee ID":        emp_id,
            "Employee Name":      emp_name,
            "Designation":        s.get("Designation", ""),
        "Client-A (aggregated)": max(int(float(s.get("Client Count", 0) or 0)), 50) if "KCD" in str(s.get("Vertical","")) else int(float(s.get("Client Count", 0) or 0)),
        "Client-C (aggregated)": (round(float(s.get("Client-C", 0) or 0), 1)
                                   if float(s.get("Client-C", 0) or 0) > 0
                                   else ""),
        "Catalog Client":        int(float(s.get("Catalog Clients", 0) or 0)),
        "Listing Client":        int(float(s.get("Listing Clients", 0) or 0)),
        "Collection Target (₹)": int(s.get("Collection Target", 0) or 0) if int(s.get("Collection Target", 0) or 0) > 0 else "",
        "Effective Team Size":  int(s.get("Effective Team Size", 0) or 0),
        "L1 Count":             int(s.get("L1 Count", 0) or 0),
            "Calc Month":         sel_month if sel_month else "All",
            "Vertical":           s.get("Vertical", ""),
            "Vintage":            s.get("Vintage", ""),
            "Joining Bucket":     s.get("Vintage", ""),  # FSF alias: 0-30D / 31-90D / 91-270D / 270D+
            "Team":               s.get("Team", ""),
            "Vintage Bucket":     s.get("Vintage Bucket", ""),
            "Scheme Type":        inc.get("Scheme Type", ""),
            "Location":           s.get("Location", ""),
            "L2":                 s.get("L2 Name", ""),
            "L3":                 s.get("L3 Name", ""),
            "L4":                 s.get("L4 Name", ""),
            "L5":                 s.get("L5 Name", ""),
            "Joining Date":       s.get("Joining Date", ""),
            # ── Financial data from receipt/refund (always correct) ───
            "Collection (₹)":     round(float(gross_collection or 0), 2),
            "Refund (₹)":         round(float(total_ref or 0), 2),
            "Net Collection (₹)": round(float(net_dv or 0), 2),
            "Deal Value (₹)":     round(float(gross_deal_val or 0), 2),
            "Deal Loss (₹)":      round(float(deal_loss or 0), 2),
            "Net Deal Value (₹)": round(float(net_deal_val or 0), 2),
            "Collection Target (₹)": int(s.get("Collection Target", 0)),
            "PCR Target (₹)":        int(s.get("PCR Target", 0)),
            "CMR Slab1 Target":   emp_targets["slab1"],
            "CMR Slab2 Target":   emp_targets["slab2"],
            "SPS Group":  ("SPS" if "SPS" in str(s.get("Team","")).upper()
                          else ("90+D" if "90+ DAYS" in str(s.get("Team","")).upper()
                                else "No")),
            "MDC1 Sent":  mdc1_cmr_map.get(emp_id, {}).get("mdc1_sent", 0),
            "MDC1 Recd":  mdc1_cmr_map.get(emp_id, {}).get("mdc1_recd", 0),
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
        "SPS Group", "Vintage Bucket",
            "Scheme Type", "Location", "L2",         "Collection (₹)", "Refund (₹)", "Net Collection (₹)",
        "Collection Target (₹)",
        "Deal Value (₹)", "Deal Loss (₹)", "Net Deal Value (₹)",
        "PCR", "PCDV", "Slab Metric Used",
        "CMR% (auto)", "CMR Slab1 Target", "CMR Slab2 Target",
        "SS+ CMR% (auto)", "SS+ Sent", "SS+ Received",
        "CMR Sent", "CMR Received", "CMR Slab",
        "MDC1 Sent", "MDC1 Recd",
        "MDC-1 CMR%", "CMR+1 Sent", "CMR+1 Recd", "MDC1 CMR+1%", "CMR+1 Multiplier", "Inc. Payout Mult",
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
            """Write df to sheet with full row-level Excel formulas for ALL derived columns."""
            df.to_excel(w, sheet_name=sheet_name, index=False, startrow=1)
            ws   = w.sheets[sheet_name]
            hf   = header_fmt or hdr
            cols = list(df.columns)

            # ── helpers ──────────────────────────────────────────────────────
            def xl(idx):
                s = ""; idx += 1
                while idx:
                    idx, r = divmod(idx - 1, 26)
                    s = chr(65 + r) + s
                return s

            def ci(name):
                return xl(cols.index(name)) if name in cols else None

            def _fmt(bg="#FFFFFF", bold=False, italic=False, font_color="#000000",
                     num_format=None, font_size=9):
                d = {"bg_color": bg, "bold": bold, "italic": italic,
                     "font_color": font_color, "font_size": font_size}
                if num_format: d["num_format"] = num_format
                return wb.add_format(d)

            # Format palette
            _money  = _fmt("#F0F7FF", num_format="#,##0")          # blue  — finance
            _pct1   = _fmt("#F7FFF0", num_format="0.0")            # green — %
            _green  = _fmt("#E2EFDA", num_format="#,##0", bold=True) # totals
            _orange = _fmt("#FFF0E0", num_format="#,##0")           # incentive components
            _grey   = _fmt("#F5F5F5", num_format="0.0")            # CMR / multipliers
            _yellow = _fmt("#FFF2CC", italic=True, font_color="#595959", font_size=8)  # note row

            # ── headers + freeze ──────────────────────────────────────────────
            for ci_i, col in enumerate(cols):
                ws.write(1, ci_i, col, hf)
                ws.set_column(ci_i, ci_i, max(14, len(str(col)) + 2))
            ws.write(0, 0, f"{sheet_name} — IndiaMart Incentive Calculator (May 2026)")
            ws.freeze_panes(2, 2)

            # ── formula rules: (output_col, formula_template, description_note, fmt)
            # {R} is replaced with the Excel row number; {key} with column letters
            formula_rules = []

            def rule(col_name, tmpl, note="", fmt=None):
                """Register a formula rule only if the output column exists in this sheet."""
                if col_name in cols:
                    formula_rules.append((col_name, tmpl, note, fmt or _money))

            # ── 1. Financial derivations ─────────────────────────────────────
            rule("Net Collection (₹)",  "={coll}{R}-{ref}{R}",           "=Collection − Refund", _money)
            rule("Net Deal Value (₹)",  "={dv}{R}-{dl}{R}",              "=Deal Value − Deal Loss", _money)

            # ── 2. Per-client metrics (PCR / PCDV) ───────────────────────────
            # PCR and PCDV: no Excel formula — Python-computed values are correct per vertical

            # ── 3. CMR family ────────────────────────────────────────────────
            rule("CMR% (auto)",
                 "=IF({rs}{R}>0,{rr}{R}/{rs}{R}*100,0)",
                 "=Renewals Recd / Sent × 100", _pct1)
            rule("SS+ CMR% (auto)",
                 "=IF({ss_s}{R}>0,{ss_r}{R}/{ss_s}{R}*100,0)",
                 "=SS+ Recd / Sent × 100", _pct1)
            rule("MDC-1 CMR%",
                 '=IF({ms}{R}>0,{mr}{R}/{ms}{R}*100,"")',
                 "=MDC1 Recd / MDC1 Sent × 100", _pct1)
            rule("MDC1 CMR+1%",
                 '=IF({c1s}{R}>0,{c1r}{R}/{c1s}{R}*100,"")',
                 "=CMR+1 Recd / CMR+1 Sent × 100", _pct1)
            rule("KCD CMR Ren%",
                 '=IF({kcmrs}{R}>0,{kcmrr}{R}/{kcmrs}{R}*100,"")',
                 "=KCD CMR Recd / Sent × 100", _pct1)
            rule("KCD SS+ CMR%",
                 '=IF({kss_s}{R}>0,{kss_r}{R}/{kss_s}{R}*100,"")',
                 "=KCD SS+ Recd / Sent × 100", _pct1)
            rule("CMR (Ren%)",      # BM/RM sheet name
                 "=IF({rs}{R}>0,{rr}{R}/{rs}{R},0)",
                 "=Renewals Received / Sent", _pct1)
            rule("CMR+1 Ren%",
                 '=IF({c1s}{R}>0,{c1r}{R}/{c1s}{R},"")',
                 "=CMR+1 Recd / CMR+1 Sent", _pct1)

            # ── 4. KCD targets & achievement ────────────────────────────────
            # KCD PCDV Target and PCDV%: no formula — Python computes correctly per team
            # (Collection Target only applies to Listing/Catalog; slab teams use HC/CA)
            # KCD HC: no formula — Python computes correctly per team/vintage
            # (formula would need to know HC multiplier per team which varies)

            # ── 5. CSD SPS incentive derivations ────────────────────────────
            rule("Inc. Per Txn (₹)",
                 "={ipm}{R}*{prod}{R}",
                 "=Inc. Payout Mult × Productivity Score", _orange)
            rule("Net Incentive (₹)",
                 "={ipt}{R}*{cmr1m}{R}",
                 "=Inc. Per Txn × CMR+1 Multiplier", _orange)
            rule("Gross Inc w/ Boost (₹)",
                 "=IF({boost}{R}>0,{nipt}{R}*{boost}{R},{nipt}{R})",
                 "=Net Incentive × SPS Booster", _orange)

            # ── 6. AOP for BM/RM ─────────────────────────────────────────────
            rule("AOP Achievement %",
                 "=IF({aop}{R}>0,{ndv}{R}/{aop}{R}*100,0)",
                 "=Net Deal Value / AOP Target × 100", _pct1)
            rule("AOP Multiplier",
                 '=IF({aopp}{R}=0,"",IF({aopp}{R}<95,"<95% — not eligible",'
                 'IF({aopp}{R}<100,"100%",IF({aopp}{R}<105,"110%",'
                 'IF({aopp}{R}<110,"120%","130%")))))',
                 "=<95%→0 | 95-100%→100% | 100-105%→110% | 105-110%→120% | 110%+→130%",
                 _grey)

            # ── 7. KCD weekly totals ─────────────────────────────────────────
            rule("KCD WK Total Txns",
                 "={wk1}{R}+{wk2}{R}+{wk3}{R}+{wk4}{R}",
                 "=WK-1+WK-2+WK-3+WK-4 Transactions", _pct1)

            # ── 8. KCD incentive totals ──────────────────────────────────────
            rule("KCD Total Incentive (₹)",
                 "={kbase}{R}+{kinc}{R}+{spot}{R}",
                 "=KCD Base + KCD Incremental + Spot Incentive", _green)
            rule("KCD Gross Incentive (₹)",
                 "={kbase}{R}+{kinc}{R}",
                 "=KCD Base Incentive + KCD Incremental", _green)

            # ── 9. Main totals (all sheets) ───────────────────────────────────
            rule("Gross Incentive (₹)",
                 '=IF(OR({jbkt}{R}="0-30D",{jbkt}{R}="31-90D"),MIN({base}{R}+{pop}{R},20000),{base}{R}+{pop}{R})',
                 "=MIN(Base+PoP,20000) for 0-90D; Base+PoP for 90+", _green)
            rule("Total Incentive (₹)",
                 "={gi}{R}+{spot}{R}",
                 "=Gross Incentive + Spot Incentive", _green)
            rule("Balance Incentive (₹)",
                 "=IF({gi}{R}>0,{gi}{R}-{pi}{R},0)",
                 "=Gross Incentive − Paid Incentive", _money)

            # ── 10. Days since joining ────────────────────────────────────────
            rule(                 '=IF({jd}{R}<>"",TODAY()-{jd}{R},"")',
                 "=TODAY() − Joining Date", _pct1)

            # ── 11. Receipt/Refund/Renewal enrichment formulas ───────────────
            # Day / Week / FNT — derived from date column
            rule("Day",   '=IF({edate}{R}<>"",DAY({edate}{R}),"")',       "=DAY(Entry Date)", _pct1)
            rule("Week",  '=IF({day_c}{R}="","",IF({day_c}{R}<=9,"WK-1",IF({day_c}{R}<=16,"WK-2",IF({day_c}{R}<=23,"WK-3","WK-4"))))',
                 '=IF(Day<=9,"WK-1",IF(<=16,"WK-2",IF(<=23,"WK-3","WK-4")))', _grey)
            rule("FNT",   '=IF({day_c}{R}="","",IF({day_c}{R}<=16,"FNT-1","FNT-2"))',
                 '=IF(Day<=16,"FNT-1","FNT-2")', _grey)
            rule("Total Sale",
                 '=IF(OR({uniq}{R}="",{uniq}{R}="TS"),0,1)',
                 '=IF(Unique="" or "TS", 0, 1)', _pct1)
            # Productivity: only apply formula if column doesn't already have valid 0/1 values
            _prod_col_valid = ("Productivity" in df.columns and
                               pd.to_numeric(df["Productivity"], errors="coerce").isin([0,0.5,1]).mean() > 0.8)
            if not _prod_col_valid:
                rule("Productivity",
                     "={tsale}{R}",
                     "=Total Sale (1=productive txn)", _pct1)
            rule("Collection",
                 '=IF(OR(ISNUMBER(SEARCH("NACH",{mode_c}{R})),ISNUMBER(SEARCH("ECS",{mode_c}{R}))),"No","Yes")',
                 '=IF(Mode contains NACH/ECS,"No","Yes")', _grey)

            # ── Column letter lookup (all possible columns across all sheets) ─
            _lk = {
                "coll":   ci("Collection (₹)"),
                "ref":    ci("Refund (₹)"),
                "nc":     ci("Net Collection (₹)"),
                "dv":     ci("Deal Value (₹)"),
                "dl":     ci("Deal Loss (₹)"),
                "ndv":    ci("Net Deal Value (₹)"),
                "ca":     ci("Client-A (aggregated)") or ci("Client-A"),
                "vt":     ci("Vertical"),
                "cc":     ci("Client-C (aggregated)") or ci("Client-C"),
                "rs":     ci("CMR Sent"),
                "rr":     ci("CMR Received"),
                "ss_s":   ci("SS+ Sent") or ci("SS+ Sent"),
                "ss_r":   ci("SS+ Received") or ci("SS+ Received"),
                "ms":     ci("MDC1 Sent"),
                "mr":     ci("MDC1 Recd"),
                "c1s":    ci("CMR+1 Sent"),
                "c1r":    ci("CMR+1 Recd"),
                "ct":     ci("KCD Collection Target (₹)"),
                "pt":     ci("KCD PCDV Target"),
                "pcdv":   ci("PCDV"),
                "kcmrs":  ci("KCD CMR Sent"),
                "kcmrr":  ci("KCD CMR Recd"),
                "kss_s":  ci("KCD SS+ Sent"),
                "kss_r":  ci("KCD SS+ Recd"),
                "aop":    ci("AOP Target (₹)"),
                "aopp":   ci("AOP Achievement %"),
                "jbkt":   ci("Joining Bucket"),
                "base":   ci("Base Incentive (₹)"),
                "pop":    ci("PoP Incentive (₹)"),
                "spot":   ci("Spot Incentive (₹)"),
                "kbase":  ci("KCD Base Incentive (₹)"),
                "kinc":   ci("KCD Incremental (₹)"),
                "gi":     ci("Gross Incentive (₹)"),
                "pi":     ci("Paid Incentive (₹)"),
                "ipm":    ci("Inc. Payout Mult"),
                "prod":   ci("Productivity Score"),
                "cmr1m":  ci("CMR+1 Multiplier"),
                "ipt":    ci("Inc. Per Txn (₹)"),
                "nipt":   ci("Net Incentive (₹)"),
                "boost":  ci("SPS Booster"),
                "hcm":    ci("KCD HC Multiplier"),
                "wk1":    ci("KCD WK-1 Txns"),
                "wk2":    ci("KCD WK-2 Txns"),
                "wk3":    ci("KCD WK-3 Txns"),
                "wk4":    ci("KCD WK-4 Txns"),
                "jd":     ci("Joining Date"),
                # Receipt/Refund columns
                "edate":  (ci("Entry Date") or ci("Clear Date") or
                           ci("Receipt Date") or ci("Date")),
                "day_c":  ci("Day"),
                "uniq":   ci("Unique"),
                "tsale":  ci("Total Sale"),
                "mode_c": ci("Mode"),
            }

            # ── Write note row (row 0) ────────────────────────────────────────
            for out_col, _, note, _ in formula_rules:
                if note:
                    ws.write(0, cols.index(out_col), note, _yellow)

            # ── Write row-level formulas for every data row ───────────────────
            for row_idx in range(len(df)):
                er = row_idx + 3  # note=row1, header=row2, data rows start at Excel row 3

                for out_col, tmpl, _, fmt in formula_rules:
                    try:
                        f = tmpl.format(R=er, **_lk)
                        if "None" in f:
                            continue  # required column not in this sheet
                        # Preserve computed fallback value so file opens correctly
                        raw = df.iloc[row_idx].get(out_col, 0) if hasattr(df.iloc[row_idx], 'get') else 0
                        try:
                            fallback = float(raw) if raw and str(raw) not in ('','nan') else 0
                        except (TypeError, ValueError):
                            fallback = 0
                        ws.write_formula(er - 1, cols.index(out_col), f, fmt, fallback)
                    except (KeyError, TypeError, ValueError):
                        continue

        # ── Sheet 1: FSF (Final Settlement File) -- all employees ─────────────
        fsf_cols = [c for c in [
            "Employee ID","Employee Name","Calc Month","Vertical","Vintage",
            "Team","Designation","Vintage Bucket",
            "Scheme Type","SPS Group","Location","L2","L3",
                        "Collection (₹)","Refund (₹)","Net Collection (₹)",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)",
            "PCR","PCDV","Slab Metric Used",
            "CMR Slab1 Target","CMR Slab2 Target",
            "CMR% (auto)","SS+ CMR% (auto)","SS+ Sent","SS+ Received",
            "CMR Sent","CMR Received","CMR Slab",
            "MDC1 Sent","MDC1 Recd",
            "MDC-1 CMR%","CMR+1 Sent","CMR+1 Recd","MDC1 CMR+1%","CMR+1 Multiplier","Inc. Payout Mult",
            "Productivity Score","Insta Txns (0.5×)","Receipt Txns","Renewal Txns",
            "Inc. Per Txn (₹)","Net Incentive (₹)","SPS Booster","Gross Inc w/ Boost (₹)",
            "KCD Collection Target (₹)","KCD Highest Collection (₹)","KCD PCDV Target","KCD PCDV%",
            "KCD WK-1 Txns","KCD WK-2 Txns","KCD WK-3 Txns","KCD WK-4 Txns","KCD WK Total Txns","KCD BTL",
            "KCD CMR Sent","KCD CMR Recd","KCD CMR Ren%",
            "KCD SS+ Sent","KCD SS+ Recd","KCD SS+ CMR%","KCD SS+Ren Mult","KCD SS+ Penalty Applied",
            "KCD Incentive Multiplier",
            "KCD Base Incentive (₹)","KCD Incremental (₹)",
            "KCD Total Incentive (₹)","KCD Gross Incentive (₹)",
            "KCD Paid Incentive (₹)","KCD Balance Incentive (₹)",
            "KCD Group","KCD Delhi Loc Incentive","KCD Rem",
            "Incentive Multiplier","Incentive","SS+Ren Multiplier",
            "Total Incentive (KCD)","Gross Incentive (KCD)",
            "Base Incentive (₹)","PoP Incentive (₹)","Spot Incentive (₹)",
            "Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        write_sheet(res[fsf_cols], "FSF", header_fmt=hdr)

        # ── Sheet 2: Exec-CSD -- CSD L1 employees only ────────────────────────────
        csd_res = res[res["Vertical"] == "CSD"].copy() if "Vertical" in res.columns else res.iloc[0:0]
        csd_cols = [c for c in [
            # Identity + hierarchy (FSF cols 1-20)
            "Employee ID","Employee Name","L2","L3","L4",
            "Client-A (aggregated)","Client-C (aggregated)",
            "Location","Joining Bucket","Joining Date",
            "Scheme Type","SPS Group",
            # PoP tier counts (FSF cols 21-23: all CSD employees)
            "MDC-Annual||TS-1","MDC-MYR||TS-2||Maxi-A||VE","TS-3||Maxi-2",
            # Financial block (FSF cols 24-31)
            "Collection (\u20b9)","Refund (\u20b9)","Net Collection (\u20b9)","PCR",
            "Deal Value (\u20b9)","Deal Loss (\u20b9)","Net Deal Value (\u20b9)","PCDV",
            # PCDV breakdown (FSF cols 33-35: 0-90D filled; SPS NA)
            "PCDV Amount","Incremental 3% Amount","Final PCDV Amount",
            # CMR targets + renewal stats (FSF cols 36-40)
            "CMR Slab1 Target","CMR Slab2 Target",
            "CMR Sent","CMR Received","CMR% (auto)","CMR Slab",
            # FSF col 42: Incentive = PoP; col 43: Productivity = receipt prod count
            "PoP Incentive (\u20b9)","Productivity Score","Base Incentive (\u20b9)",
            "Gross Incentive (₹)",
            "BA Multiplier",
            # SPS block (NA for 0-90D)
            "MDC-1 CMR%","CMR+1 Sent","CMR+1 Recd","MDC1 CMR+1%","CMR+1 Multiplier",
            "Inc. Payout Mult","Productivity Score","Base Incentive (₹)","Insta Txns (0.5\u00d7)","Receipt Txns",
            "Inc. Per Txn (\u20b9)","Net Incentive (\u20b9)","SPS Booster","Gross Inc w/ Boost (\u20b9)",
            # Spot bifurcation
            "FNT-1 Prod Count","FNT-1 Spot (\u20b9)",
            "FNT-2 Prod Count","FNT-2 Spot (\u20b9)",
            "IM Star Pro+ Spot (\u20b9)","Spot Incentive (\u20b9)",
            "Total Incentive (\u20b9)","Scheme",
        ] if c in res.columns]
        if not csd_res.empty:
            # Exec-CSD: L1 ONLY (L3/L4/L5/L6 managers excluded)
            csd_l1 = csd_res[csd_res["Designation"].astype(str).str.strip() == "L1"] if "Designation" in csd_res.columns else csd_res
            write_sheet(csd_l1[csd_cols], "Exec-CSD", header_fmt=grn)
            # L2 on separate Rel Mgr-CSD sheet
            csd_l2 = csd_res[csd_res["Designation"].astype(str) == "L2"] if "Designation" in csd_res.columns else csd_res.iloc[0:0]
            rm_cols = [c for c in [
                # Hierarchy & identity (matches sir's Rel Mgr-CSD first block)
                "Employee ID","Employee Name","Location","SPS Group","Vintage Bucket",
            "Scheme Type",
                "L3","Client-A (aggregated)","Client-C (aggregated)",
                "Effective Team Size","L1 Count","Joining Date",
                # Financial
                "Collection (₹)","Refund (₹)","Net Collection (₹)","PCR",
                "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCDV",
                # CMR (matches sir's CMR / CMR+1 / MDC-1 CMR sections)
                "CMR Slab1 Target","CMR Slab2 Target",
                "CMR Sent","CMR Received","CMR% (auto)",
                "MDC1 Sent","MDC1 Recd","MDC-1 CMR%","CMR+1 Sent","CMR+1 Recd","MDC1 CMR+1%","CMR+1 Multiplier",
                # Base incentive
                "Inc. Payout Mult","Productivity Score","Receipt Txns",
                "Inc. Per Txn (₹)","Net Incentive (₹)","SPS Booster","Gross Inc w/ Boost (₹)",
                "BA Multiplier","Base Incentive (₹)",
                # Spot bifurcation (matches sir's FNT-1 / FNT-2 / 28-30 sections)
                "FNT-1 Prod Count","FNT-1 Spot (₹)",
                "FNT-2 Prod Count","FNT-2 Spot (₹)",
                "IM Star Pro+ Spot (₹)",
                "Spot Incentive (₹)","Total Incentive (₹)","Scheme",
            ] if c in res.columns]
            if not csd_l2.empty:
                write_sheet(csd_l2[rm_cols], "Rel Mgr-CSD", header_fmt=grn)

        # ── Sheet 3: KCD-Exec -- KCD L1 employees only ────────────────────────────
        kcd_res = res[res["Vertical"] == "KCD"].copy() if "Vertical" in res.columns else res.iloc[0:0]
        kcd_cols = [c for c in [
            # Hierarchy & identity
            "Employee ID","Employee Name","Location","Team","Vintage",
            "Client-A (aggregated)","Client-C (aggregated)","Catalog Client","Listing Client",
            "Joining Date",            # Financial
            "Collection (₹)","Refund (₹)","Net Collection (₹)","KCD Collection Target (₹)",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCDV","PCR","Slab Metric Used",
            "KCD Highest Collection (₹)","KCD PCDV Target","KCD PCDV%",
            # Weekly DV
            "KCD WK-1 Txns","KCD WK-2 Txns","KCD WK-3 Txns","KCD WK-4 Txns","KCD WK Total Txns","KCD BTL",
            # CMR / SS+
            "KCD CMR Sent","KCD CMR Recd","KCD CMR Ren%",
            "KCD SS+ Sent","KCD SS+ Recd","KCD SS+ CMR%","KCD SS+Ren Mult","KCD SS+ Penalty Applied",
            "CMR Sent","CMR Received",
            "Productivity Score","Receipt Txns",
            "KCD Incentive Multiplier","KCD Base Incentive (₹)","KCD Incremental (₹)",
            "KCD Total Incentive (₹)","KCD Gross Incentive (₹)",
                "BA Multiplier",
            "KCD Group","KCD Delhi Loc Incentive","KCD Rem",
            "BTL Productivity Count","BA Multiplier",
            # Spot bifurcation (matches sir's FNT-1 / FNT-2 sections)
            "FNT-1 Spot (₹)","FNT-2 Spot (₹)",
            "WK-1 Prod Spot (₹)","Excellent Spot (₹)",
            "IM Insta Spot (₹)","MCATs Spot (₹)",
            "Spot Incentive (₹)","Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        if not kcd_res.empty:
            # L1 on KCD-Exec sheet
            kcd_l1 = kcd_res[kcd_res["Designation"].astype(str).str.strip() == "L1"] if "Designation" in kcd_res.columns else kcd_res
            write_sheet(kcd_l1[kcd_cols], "KCD-Exec", header_fmt=org)
            # L2 SAM on separate KCD-SAM sheet
            kcd_l2 = kcd_res[kcd_res["Designation"].astype(str) == "L2"] if "Designation" in kcd_res.columns else kcd_res.iloc[0:0]
            sam_cols = [c for c in [
                # Hierarchy & identity (matches sir's KCD-SAM first block)
                "Employee ID","Employee Name","Location","Team","Vintage",
                "Client-A (aggregated)","Client-C (aggregated)","Catalog Client","Listing Client",
                "L1 Count","Effective Team Size","Joining Date",
                # Financial
                "Collection (₹)","Refund (₹)","Net Collection (₹)","KCD Collection Target (₹)",
                "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)",
                "KCD Highest Collection (₹)","KCD PCDV Target","PCDV","PCR","KCD PCDV%",
                # Weekly
                "KCD WK-1 Txns","KCD WK-2 Txns","KCD WK-3 Txns","KCD WK-4 Txns","KCD WK Total Txns","KCD BTL",
                # CMR / SS+
                "KCD CMR Sent","KCD CMR Recd","KCD CMR Ren%",
                "KCD SS+ Sent","KCD SS+ Recd","KCD SS+ CMR%","KCD SS+Ren Mult","KCD SS+ Penalty Applied",
                "CMR Sent","CMR Received",
                "Productivity Score","Receipt Txns",
                # Base incentive
                "KCD Incentive Multiplier","KCD Base Incentive (₹)","KCD Incremental (₹)",
                "KCD Total Incentive (₹)","KCD Gross Incentive (₹)",
                "KCD Group","KCD Delhi Loc Incentive","KCD Rem",
                "BA Multiplier",
                # Spot bifurcation (matches sir's FNT-1 / FNT-2 / 28-30 sections)
                "FNT-1 Spot (₹)","FNT-2 Spot (₹)",
                "IM Insta Spot (₹)","MCATs Spot (₹)",
                "IM Star Pro+ Spot (₹)",
                "Spot Incentive (₹)","Total Incentive (₹)","Scheme",
            ] if c in res.columns]
            if not kcd_l2.empty:
                # Regular SAM (non-ILP)
                kcd_sam_regular = kcd_l2[~kcd_l2["Team"].astype(str).str.contains("ILP", na=False)] if "Team" in kcd_l2.columns else kcd_l2
                if not kcd_sam_regular.empty:
                    write_sheet(kcd_sam_regular[sam_cols], "KCD-SAM", header_fmt=org)

        # ── KCD-SAM ILP sheet (always created; empty rows if no ILP target uploaded) ─
        ilp_cols = [c for c in [
            "Employee ID","Employee Name","Location","Team","Designation","Vintage","Scheme Type",
            "Client-A (aggregated)","Client-C (aggregated)","Joining Date",
            "Collection (₹)","Refund (₹)","Net Collection (₹)",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCDV",
            "KCD Collection Target (₹)","KCD PCDV Target","KCD PCDV%",
            "KCD CMR Sent","KCD CMR Recd","KCD CMR Ren%",
            "KCD SS+ Sent","KCD SS+ Recd","KCD SS+ CMR%",
            "Base Incentive (₹)","Spot Incentive (₹)","Total Incentive (₹)","Scheme",
        ] if c in res.columns]
        # Pull SAM-ILP rows from res OR build from struct_map (so sheet exists even with 0 txns)
        ilp_res = pd.DataFrame()
        if not res.empty and "Team" in res.columns:
            ilp_res = res[res["Team"].astype(str).str.contains("ILP", na=False)]
        # If no ILP results (no receipt data), build skeleton from struct_map
        if ilp_res.empty:
            ilp_rows = []
            for eid, s in struct_map.items():
                if "ILP" in str(s.get("Team","")).upper() or "ILP" in str(s.get("Group","")).upper():
                    ilp_rows.append({
                        "Employee ID":          eid,
                        "Employee Name":        s.get("Employee Name",""),
                        "Location":             s.get("Location",""),
                        "Team":                 s.get("Team","KCD SAM ILP"),
                        "Designation":          s.get("Designation",""),
                        "Vintage":              s.get("Vintage",""),
                        "Scheme Type":          "KCD SAM ILP",
                        "Client-A (aggregated)":int(s.get("Client Count",0) or 0),
                        "Total Incentive (₹)":  0,
                        "Scheme":               "No target uploaded",
                    })
            if ilp_rows:
                ilp_res = pd.DataFrame(ilp_rows)
        if not ilp_res.empty:
            _ilp_out_cols = [c for c in ilp_cols if c in ilp_res.columns]
            write_sheet(ilp_res[_ilp_out_cols] if _ilp_out_cols else ilp_res,
                        "KCD-SAM ILP", header_fmt=org)

        # ── Sheets: BM-CSD, RM-CSD, BM-KCD, RM-KCD (L3/L4 AOP scheme) ─────────
        # Columns matching sir's BM/RM FSF layout
        # Need to compute AOP incentive from the structure dump data (aop_target from L3/L4 rows)
        bm_rm_cols_csd = [
            "Employee ID","Employee Name","Designation",
            "L4 ID","L4 Name","L5 ID","L5 Name",
            "Joining Date","Vertical",
            "Client-A","Client-C","L1 Count","L2 Count","HC",
            "Collection (₹)","Refund (₹)","Net Collection (₹)","PCR",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCDV",
            "AOP Target (₹)","AOP Achievement %","AOP Multiplier",
            "CMR%","CMR Multiplier",
            "Incentive (₹)","Gross Incentive (₹)","Paid Incentive (₹)","Balance Incentive (₹)",
            "CMR Sent","CMR Received","CMR (Ren%)",
            "CMR+1 Sent","CMR+1 Recd","CMR+1 Ren%",
            "Total Incentive (₹)","Scheme",
        ]
        bm_rm_cols_kcd = [
            "Employee ID","Employee Name","Designation",
            "L4 ID","L4 Name","L5 ID","L5 Name",
            "Joining Date","Vertical",
            "Client-A","Client-C","L1 Count","L2 Count","HC",
            "Collection (₹)","Refund (₹)","Net Collection (₹)","PCR",
            "Deal Value (₹)","Deal Loss (₹)","Net Deal Value (₹)","PCDV",
            "AOP Target (₹)","AOP Achievement %","AOP Multiplier",
            "SS+ CMR%","SS+ Multiplier","CMR%","CMR Multiplier",
            "Incentive (₹)","Gross Incentive (₹)","Paid Incentive (₹)","Balance Incentive (₹)",
            "Renewals Sent (Non SS+)","Renewals Received (Non SS+)","CMR (Ren%)",
            "CMR+1 Sent","CMR+1 Recd","CMR+1 Ren%",
            "Total Incentive (₹)","Scheme",
        ]

        # Build BM/RM rows from structure map (L3=BM, L4=RM)
        def build_bm_rm_rows(vertical_filter, level_filter):
            """Build BM (L3) or RM (L4) incentive rows by aggregating subordinates from res."""
            rows = []
            hier_col_res = "L3" if level_filter == "L3" else "L4"

            for eid, s in struct_map.items():
                v = str(s.get("Vertical","")).upper()
                d = str(s.get("Designation","")).upper().strip()
                if vertical_filter.upper() not in v: continue
                if d != level_filter: continue
                # Exclude Teleannual, Inside Sales, and other non-field verticals
                if any(excl in v for excl in ["TELEANNUAL","TELE ANNUAL","INSIDE SALES","TELESALES","INBOUND"]): continue

                emp_name_clean = str(s.get("Employee Name","")).strip()
                subs = res[res[hier_col_res].astype(str).str.strip() == emp_name_clean] if hier_col_res in res.columns else pd.DataFrame()

                def _sum(col):
                    if subs.empty or col not in subs.columns: return 0
                    return int(pd.to_numeric(subs[col], errors="coerce").fillna(0).sum())

                gross_coll = _sum("Collection (₹)");  total_ref = _sum("Refund (₹)")
                net_coll   = gross_coll - total_ref
                dv         = _sum("Deal Value (₹)");  dl = _sum("Deal Loss (₹)")
                net_dv_bm  = dv - dl

                # Client counts first (needed for aop_target fallback)
                client_a_sum = int(pd.to_numeric(subs["Client-A (aggregated)"], errors="coerce").fillna(0).sum()) if not subs.empty and "Client-A (aggregated)" in subs.columns else 0
                l1_cnt = len(subs[subs["Designation"].astype(str).str.strip()=="L1"]) if "Designation" in subs.columns else len(subs)
                l2_cnt = len(subs[subs["Designation"].astype(str).str.strip()=="L2"]) if "Designation" in subs.columns else 0
                hc     = l1_cnt
                client_a = client_a_sum if client_a_sum > 0 else int(s.get("Client Count", 0) or 0)
                client_c = float(s.get("Client-C", 0) or 0)

                def _safe_float(v):
                    try: return float(v) if v is not None else 0.0
                    except (TypeError, ValueError): return 0.0

                # AOP Target: annual deal value target for BM/RM
                # For CSD: sum of subordinates' monthly collection targets × 12 (annualized proxy)
                # For KCD: sum of monthly KCD targets × 12 (annualized proxy)
                # Note: True AOP = annual DV target assigned by management (upload separately)
                _monthly_target = (_sum("Collection Target (₹)") or
                                   _sum("KCD Collection Target (₹)") or
                                   _safe_float(s.get("Collection Target")) or
                                   _safe_float(s.get("PCR Target")) * client_a)
                # Use actual monthly sum if available, else 0 (no AOP data)
                # KCD monthly targets are per-month based on slab × client_a, not annual AOP
                # For mid-month May: AOP achievement will always be < 95% → ₹0 (correct)
                aop_target = _monthly_target

                pcr  = round(net_coll  / client_a, 1) if client_a > 0 else 0
                pcdv = round(net_dv_bm / client_a, 1) if client_a > 0 else 0

                # CMR from renewal aggregation (manager's own renewal data or subordinate aggregate)
                emp_cmr   = cmr_map.get(eid, {})
                cmr_pct_v = float(emp_cmr.get("cmr_pct", 0) or 0)
                ss_cmr_v  = float(emp_cmr.get("ss_cmr_pct", 0) or 0)
                rnl_sent  = int(emp_cmr.get("renewal_sent", 0) or 0)
                rnl_recd  = int(emp_cmr.get("renewal_received", 0) or 0)
                ss_sent   = int(emp_cmr.get("ss_sent", 0) or 0)
                ss_recd   = int(emp_cmr.get("ss_received", 0) or 0)
                mdc1_data = mdc1_cmr_map.get(eid, {})
                mdc1_pct  = float(mdc1_data.get("mdc1_cmr_pct", 0) or 0)
                mdc1_pct  = mdc1_pct * 100 if mdc1_pct <= 1 else mdc1_pct
                mdc1_sent = int(mdc1_data.get("mdc1_sent", 0) or 0)
                mdc1_recd = int(mdc1_data.get("mdc1_recd", 0) or 0)

                # If manager not in renewal file, aggregate from subordinates
                if cmr_pct_v == 0 and not subs.empty:
                    _ss = int(pd.to_numeric(subs.get("CMR Sent", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
                    _sr = int(pd.to_numeric(subs.get("CMR Received", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
                    cmr_pct_v = round(_sr/_ss*100,1) if _ss>0 else 0
                    rnl_sent=_ss; rnl_recd=_sr
                if ss_cmr_v == 0 and not subs.empty and "KCD SS+ Sent" in subs.columns:
                    _es=int(pd.to_numeric(subs["KCD SS+ Sent"],errors="coerce").fillna(0).sum())
                    _er=int(pd.to_numeric(subs["KCD SS+ Recd"],errors="coerce").fillna(0).sum()) if "KCD SS+ Recd" in subs.columns else 0
                    ss_cmr_v=round(_er/_es*100,1) if _es>0 else 0
                    ss_sent=_es; ss_recd=_er

                cmr_v = cmr_pct_v*100 if cmr_pct_v<=1 else cmr_pct_v
                ss_v  = ss_cmr_v*100  if ss_cmr_v<=1  else ss_cmr_v

                inc, scheme_note = calc_bm_rm_aop(net_deal_val=net_dv_bm, aop_target=aop_target,
                    cmr_pct=cmr_pct_v, ss_cmr_pct=ss_cmr_v, vertical=v, level=level_filter, S=S)

                aop_pct = (net_dv_bm/aop_target*100) if aop_target>0 else 0
                aop_mult_str = ("" if aop_pct<95 else "100%" if aop_pct<100 else "110%" if aop_pct<105 else "120%" if aop_pct<110 else "130%")
                if "CSD" in v:
                    cmr_mult_str = ("0%" if cmr_v<53 else "50%" if cmr_v<60 else "100%" if cmr_v<65 else "120%")
                else:
                    cmr_mult_str = ("0%" if cmr_v<72 else "75%" if cmr_v<75 else "100%" if cmr_v<80 else "120%")
                ss_mult_str = "100%" if ss_v>=72 else "50%"

                row = {
                    "Employee ID": eid, "Employee Name": emp_name_clean,
                    "Designation": s.get("Designation",""), "Joining Date": s.get("Joining Date",""),
                    "Vertical": s.get("Vertical",""),
                    "Client-A": client_a, "Client-C": round(client_c,1) if client_c>0 else client_a,
                    "L1 Count": l1_cnt, "L2 Count": l2_cnt, "HC": hc,
                    "Collection (₹)": gross_coll, "Refund (₹)": total_ref,
                    "Net Collection (₹)": net_coll, "PCR": pcr,
                    "Deal Value (₹)": dv, "Deal Loss (₹)": dl,
                    "Net Deal Value (₹)": net_dv_bm, "PCDV": pcdv,
                    "AOP Target (₹)": int(aop_target), "AOP Achievement %": round(aop_pct,1),
                    "AOP Multiplier": aop_mult_str,
                    "SS+ CMR%": round(ss_v,1), "SS+ Multiplier": ss_mult_str,
                    "CMR%": round(cmr_v,1), "CMR Multiplier": cmr_mult_str,
                    "Incentive (₹)": int(inc), "Gross Incentive (₹)": int(inc),
                    "Paid Incentive (₹)": 0, "Balance Incentive (₹)": int(inc),
                    "CMR Sent": rnl_sent, "CMR Received": rnl_recd,
                    "CMR (Ren%)": round(cmr_v/100,4),
                    "SS+ Sent": ss_sent, "SS+ Received": ss_recd,
                    "Renewals Sent (Non SS+)": mdc1_sent, "Renewals Received (Non SS+)": mdc1_recd,
                    "CMR+1 Sent": mdc1_sent, "CMR+1 Recd": mdc1_recd,
                    "CMR+1 Ren%": round(mdc1_pct/100,4) if mdc1_pct>0 else "",
                    "Total Incentive (₹)": int(inc), "Scheme": scheme_note,
                    "L4 ID": s.get("L2 Name",""), "L4 Name": s.get("L2 Name",""),
                    "L5 ID": s.get("L3 Name",""), "L5 Name": s.get("L3 Name",""),
                }
                rows.append(row)
            return pd.DataFrame(rows) if rows else pd.DataFrame()

        # Generate and write the 4 BM/RM sheets
        pur = wb.add_format({"bold": True, "bg_color": "#7030A0",
                              "font_color": "#FFFFFF", "border": 1, "font_size": 10})
        teal = wb.add_format({"bold": True, "bg_color": "#006471",
                               "font_color": "#FFFFFF", "border": 1, "font_size": 10})

        bm_csd = build_bm_rm_rows("CSD", "L3")
        if not bm_csd.empty:
            out_cols = [c for c in bm_rm_cols_csd if c in bm_csd.columns]
            write_sheet(bm_csd[out_cols], "BM-CSD", header_fmt=pur)

        rm_csd = build_bm_rm_rows("CSD", "L4")
        if not rm_csd.empty:
            out_cols = [c for c in bm_rm_cols_csd if c in rm_csd.columns]
            write_sheet(rm_csd[out_cols], "RM-CSD", header_fmt=pur)

        bm_kcd = build_bm_rm_rows("KCD", "L3")
        if not bm_kcd.empty:
            out_cols = [c for c in bm_rm_cols_kcd if c in bm_kcd.columns]
            write_sheet(bm_kcd[out_cols], "BM-KCD", header_fmt=teal)

        rm_kcd = build_bm_rm_rows("KCD", "L4")
        if not rm_kcd.empty:
            out_cols = [c for c in bm_rm_cols_kcd if c in rm_kcd.columns]
            write_sheet(rm_kcd[out_cols], "RM-KCD", header_fmt=teal)
        cmr_cols = [c for c in [
            "Employee ID","Employee Name","Vertical","Vintage","Team","Location",
            "CMR Slab1 Target","CMR Slab2 Target",
            "CMR Sent","CMR Received","CMR% (auto)","CMR Slab",
            "SS+ Sent","SS+ Received","SS+ CMR% (auto)",
            "MDC1 Sent","MDC1 Recd","MDC-1 CMR%",
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

        # ── Source data sheets — enriched to match sir's FSF extra columns ─────
        grey = wb.add_format({"bold": True, "bg_color": "#595959",
                               "font_color": "#FFFFFF", "border": 1, "font_size": 10})

        # ── Build a hierarchy lookup from struct_map (EID → L2/L3/L4/L5/L6) ──
        def _hier(emp_id_str):
            s = struct_map.get(str(emp_id_str).split('.')[0], {})
            return {
                "L2 ID":   s.get("L2 ID",""),   "L2 Name": s.get("L2 Name",""),
                "L3 ID":   s.get("L3 ID",""),   "L3 Name": s.get("L3 Name",""),
                "L4 ID":   s.get("L4 ID",""),   "L4 Name": s.get("L4 Name",""),
                "L5 ID":   s.get("L5 ID",""),   "L5 Name": s.get("L5 Name",""),
                "L6 ID":   s.get("L6 ID",""),   "L6 Name": s.get("L6 Name",""),
            }

        def _week_fnt(day):
            try:
                d = int(day)
                wk  = "WK-1" if d < 10 else "WK-2" if d < 17 else "WK-3" if d < 24 else "WK-4"
                fnt = "FNT-1" if d <= 16 else "FNT-2"
                return wk, fnt, d
            except Exception:
                return "", "", 0

        # ── Receipt Data ─────────────────────────────────────────────────────
        try:
            _exp_prod = int((receipt_df['Productivity']==1).sum()) if 'Productivity' in receipt_df.columns else -1
            st.sidebar.caption(f"📊 At export: {len(receipt_df)} rows | Prod=1: {_exp_prod}")
            rec_exp = receipt_df.copy()
            rec_exp = rec_exp.drop(columns=[c for c in
                ["Service_Tier","_is_upsell",
                 "_is_pure_renewal","_has_upsell_on_receipt"]
                if c in rec_exp.columns])
            # Drop unnamed/empty columns
            rec_exp = rec_exp.loc[:, ~rec_exp.columns.astype(str).str.lower().str.startswith("unnamed")]
            rec_exp = rec_exp.loc[:, rec_exp.columns.astype(str).str.strip() != ""]
            _already_enriched = all(c in rec_exp.columns
                                    for c in ["Total Sale","Productivity","AMR","Renewal Map"])

            _date_c  = find_col(rec_exp, ["Entry Date","Clear Date","Receipt Date","Date","O"])
            _empid_c = find_col(rec_exp, ["Sales Exec ID","Sales Ex. ID","EMP ID","L1 ID","P"])
            _unique_c= find_col(rec_exp, ["Unique","UNIQUE","E"])
            _amt_c   = find_col(rec_exp, ["WT AMT","WTAMT","WT_AMT","AK"])
            _mode_al = find_col(rec_exp, ["MODE","Mode","Payment Terms","AL"])
            _mode_c   = _mode_al  # alias
            _cmr_rem = find_col(rec_exp, ["Rnl Remarks","Rnl_Remarks","CMR-C+1-C+2","AH"])  # AMR source
            _rem_exp  = find_col(rec_exp, ["Rem"])   # Renewal/WIP/NACH-ECS
            _rem_c    = _rem_exp   # alias used in AMR/NR/Collection blocks below
            _base_ct = find_col(rec_exp, ["Base Client Type","CustType","Cust Type","X"])
            _vert_c  = find_col(rec_exp, ["Vertical","AB","vertical"])
            _rnl_col = find_col(rec_exp, ["Renewal Map","Renewal Base","Prod","BH"])
            _sale_map= find_col(rec_exp, ["Sale Mapping","Sale","BG"])
            _prod_col= find_col(rec_exp, ["WS/MDC Main","Prod","Product","C"])  # for AMR fallback

            # ── Day / Week / FNT (sir: col BC=DAY(O3), BD=Week, BE=FNT) ─────────
            # Sir's Week: >=24=WK-4, >=17=WK-3, >=10=WK-2, else WK-1
            if _date_c:
                try:
                    _dt_s = pd.to_datetime(rec_exp[_date_c], errors='coerce', dayfirst=False)
                    _num  = pd.to_numeric(rec_exp[_date_c], errors='coerce')
                    _is_s = _num.notna() & _dt_s.isna()
                    if _is_s.any():
                        _base_ts = pd.Timestamp('1899-12-30')
                        _dt_s = _dt_s.copy()
                        _dt_s[_is_s] = _num[_is_s].apply(
                            lambda x: _base_ts + pd.Timedelta(days=int(x)) if pd.notna(x) else pd.NaT)
                    _days = _dt_s.dt.day.fillna(0).astype(int)
                    rec_exp["Day"]  = _days.replace(0,"")
                    rec_exp["Week"] = _days.apply(
                        lambda d: "" if d==0 else "WK-4" if d>=24 else "WK-3" if d>=17 else "WK-2" if d>=10 else "WK-1")
                    rec_exp["FNT"]  = _days.apply(
                        lambda d: "" if d==0 else "FNT-1" if d<=16 else "FNT-2")
                except Exception: pass

            # Only recompute enrichment columns when file is raw (not already enriched)
            # ── IL Sale/CL (sir col BF) ────────────────────────────────────────
            _IL_PRODUCTS = {"CATEGORY LEADER","ILP","CATEGORY LEADER INDIA",
                            "INDUSTRY LEADER","BRAND BILLBOARD","IM IL","PREFERRED IL"}
            if _unique_c and (not _already_enriched or "IL Sale/CL" not in rec_exp.columns):
                rec_exp["IL Sale/CL"] = rec_exp[_unique_c].apply(
                    lambda v: "Yes" if str(v).strip().upper() in _IL_PRODUCTS else "No")

            # ── Sale Mapping / Renewal Map / Productivity — skip if already enriched
            if not _already_enriched:
                _UPSELL_PRODS = {"MDC-TS","MDC PLUS","MDC PRO","IVE","TRUSTSEAL","VERIFIED",
                                 "TS1","TS2","TS3","TS-1","TS-2","TS-3","PREMIUM"}
                if _unique_c:
                    rec_exp["Sale Mapping"] = rec_exp[_unique_c].apply(
                        lambda v: "Upsell" if any(k in str(v).upper() for k in _UPSELL_PRODS) else "")

            # ── Renewal Map (sir col BH) ────────────────────────────────────────
            # Sir: =IF(AH3="Retention","NA",IFERROR(VLOOKUP($C3,'For Renewal'!$A:$B,2,0),"NA"))
            # col C = Product/Prod name, AH = CMR-C+1-C+2 / Rem
            # Approximation: "Renewal" if product is a renewal type (MDC, WS, IVE etc.)
            _RENEWAL_PRODS = {"MDC","MDC-TS","WS","IVE","MYR","MAXI","TRUSTSEAL",
                              "TS-1","TS-2","TS-3","RENEWAL"}
            _prod_c = find_col(rec_exp, ["WS/MDC Main","Prod","Product","C"])
            if _prod_c and _cmr_rem:
                def _renewal_map(r):
                    rem = str(r.get(_cmr_rem,"")).strip()
                    if rem == "Retention": return "NA"
                    prod = str(r.get(_prod_c,"")).strip().upper()
                    return "Renewal" if any(k in prod for k in _RENEWAL_PRODS) else "NA"
                rec_exp["Renewal Map"] = rec_exp.apply(_renewal_map, axis=1)
            elif _prod_c:
                rec_exp["Renewal Map"] = rec_exp[_prod_c].apply(
                    lambda v: "Renewal" if any(k in str(v).upper() for k in _RENEWAL_PRODS) else "NA")

            # ── Total Sale (sir col AQ) ─────────────────────────────────────────
            # Sir: =IF(OR(E3="",E3="TS"),0,1)
            if _unique_c:
                rec_exp["Total Sale"] = rec_exp[_unique_c].apply(
                    lambda v: 0 if str(v).strip() in ("","nan","TS") else 1)
            else:
                rec_exp["Total Sale"] = 1

            # ── Productivity (sir col AR) ───────────────────────────────────────
            # Productivity: preserve if pre-enriched, else compute
            _prod_pre_set = ("Productivity" in rec_exp.columns and
                              pd.to_numeric(rec_exp["Productivity"], errors="coerce").isin([0,0.5,1]).mean() > 0.8)
            if not _prod_pre_set:
                if "Renewal Map" in rec_exp.columns and "Sale Mapping" in rec_exp.columns:
                    def _calc_prod(r):
                        if r.get("Total Sale",0) == 1: return 1
                        return 1 if (r.get("Renewal Map","") == "Renewal" and
                                     r.get("Sale Mapping","") == "") else ""
                    rec_exp["Productivity"] = rec_exp.apply(_calc_prod, axis=1)
                else:
                    rec_exp["Productivity"] = rec_exp["Total Sale"]  # fallback

            # ── AMR (sir col BR) ────────────────────────────────────────────────
            # Sir: =IF(OR(AH3="Others",AH3="Retention",AH3="CMR+3"),"No","Yes")
            _amr_excl = {"OTHERS","RETENTION","CMR+3"}
            if _cmr_rem:
                rec_exp["AMR"] = rec_exp[_cmr_rem].apply(
                    lambda v: "No" if str(v).strip().upper() in _amr_excl else "Yes")

            # ── NR Upsell/AMR (sir col BR) ──────────────────────────────────────
            # Sir: =IF($AB3="CSD",IF(OR($BR3="Yes",$AL3="Upsell-NR"),"Yes","No"),"No")
            if "AMR" in rec_exp.columns and _vert_c:
                _al_c = _mode_al
                rec_exp["NR Upsell/AMR"] = rec_exp.apply(
                    lambda r: "Yes" if (str(r.get(_vert_c,"")).upper()=="CSD" and
                              (r.get("AMR","No")=="Yes" or
                               str(r.get(_al_c,"")).strip().upper()=="UPSELL-NR"))
                              else "No", axis=1)

            # ── SAM ILP Slab (sir col BM) ───────────────────────────────────────
            # Sir: =IF(AK3>=1000000,"10L+",IF(AK3>=500000,"5L+",IF(AK3>=200000,"2L+",0)))
            if _amt_c:
                def _sf(v):
                    try: return float(v)
                    except: return 0.0
                rec_exp["SAM ILP Slab"] = rec_exp[_amt_c].apply(
                    lambda v: "10L+" if _sf(v)>=1000000 else "5L+" if _sf(v)>=500000 else "2L+" if _sf(v)>=200000 else 0)

            # ── Base to List Sale (sir col BP) ──────────────────────────────────
            # Sir: =IF(OR(X3="Leader",X3="Star"),"No","Yes")  col X = Base Client Type
            if _base_ct:
                rec_exp["Base to List Sale"] = rec_exp[_base_ct].apply(
                    lambda v: "No" if str(v).strip().upper() in ("LEADER","STAR") else "Yes")

            # ── Collection (sir col BI) ─────────────────────────────────────────
            # Sir: =IF(AL3<>"Nach/ECS","Yes","No")  — EXACT match "Nach/ECS"
            if _mode_al:
                rec_exp["Collection"] = rec_exp[_mode_al].apply(
                    lambda v: "No" if str(v).strip()=="Nach/ECS" else "Yes")

            # ── L2-L6 hierarchy ─────────────────────────────────────────────────
            if _empid_c:
                _hier_df = rec_exp[_empid_c].apply(lambda v: pd.Series(_hier(v)))
                for _hcol in _hier_df.columns:
                    if _hcol not in rec_exp.columns:
                        rec_exp[_hcol] = _hier_df[_hcol]

            # Day / Week / FNT from date column
            if _date_c:
                try:
                    _dt_series = pd.to_datetime(rec_exp[_date_c], errors='coerce', dayfirst=False)
                    # Handle Excel serial numbers (numeric date)
                    _num = pd.to_numeric(rec_exp[_date_c], errors='coerce')
                    _is_serial = _num.notna() & _dt_series.isna()
                    if _is_serial.any():
                        _base_ts = pd.Timestamp('1899-12-30')
                        _dt_series[_is_serial] = _num[_is_serial].apply(
                            lambda x: _base_ts + pd.Timedelta(days=int(x)) if pd.notna(x) else pd.NaT)
                    _days = _dt_series.dt.day.fillna(0).astype(int)
                    rec_exp["Day"]  = _days.replace(0, "")
                    rec_exp["Week"] = _days.apply(lambda d: "" if d==0 else "WK-1" if d<10 else "WK-2" if d<17 else "WK-3" if d<24 else "WK-4")
                    rec_exp["FNT"]  = _days.apply(lambda d: "" if d==0 else "FNT-1" if d<=16 else "FNT-2")
                except Exception:
                    pass

            # Total Sale: 1 if Unique column = "1" or "Y" or similar (not blank, not "TS")
            if _unique_c:
                rec_exp["Total Sale"] = rec_exp[_unique_c].apply(
                    lambda v: 0 if str(v).strip().upper() in ("","NAN","TS","0","NO","N","FALSE") else 1)
            else:
                rec_exp["Total Sale"] = 1  # default: every row is a sale

            # Productivity: preserve if pre-enriched, else compute from Total Sale
            _prod_pre2 = ("Productivity" in rec_exp.columns and
                           pd.to_numeric(rec_exp["Productivity"], errors="coerce").isin([0,0.5,1]).mean() > 0.8)
            if not _prod_pre2:
                rec_exp["Productivity"] = rec_exp["Total Sale"]

            # AMR: "Yes" if Remarks (AL col) is a renewal-type category
            # In sir's file: AL col values = "MDC","MDC-TS","WS","CMR+3","OTHERS","RETENTION" etc.
            # AMR-eligible = MDC, WS, MYR (renewal) products; NOT "OTHERS","RETENTION"
            if _rem_c:
                _amr_excl = {"OTHERS","RETENTION","CMR+3","UPSELL","WINBACK",""}
                rec_exp["AMR"] = rec_exp[_rem_c].apply(
                    lambda v: "No" if str(v).strip().upper() in _amr_excl else "Yes")
            elif _prod_col:
                # Fallback: derive from product name
                _amr_prods = {"MDC","MDC-TS","WS","IVE","MYR"}
                rec_exp["AMR"] = rec_exp[_prod_col].apply(
                    lambda v: "Yes" if any(k in str(v).upper() for k in _amr_prods) else "No")

            # NR Upsell/AMR: CSD employee AND (AMR=Yes OR product=Upsell-NR)
            if "AMR" in rec_exp.columns:
                rec_exp["NR Upsell/AMR"] = rec_exp.apply(
                    lambda r: "Yes" if (
                        ("CSD" in str(r.get(_vert_c,"") if _vert_c else "").upper()) and
                        (r.get("AMR","No")=="Yes" or
                         "UPSELL" in str(r.get(_rem_c,"") if _rem_c else "").upper())
                    ) else "No", axis=1)

            # SAM ILP Slab from WT AMT
            if _amt_c:
                def _sf(v, d=0):
                    try: return float(v)
                    except: return d
                rec_exp["SAM ILP Slab"] = rec_exp[_amt_c].apply(
                    lambda v: "10L+" if _sf(v)>=1000000 else
                              "5L+"  if _sf(v)>=500000  else
                              "2L+"  if _sf(v)>=200000  else "")

            # Base to List Sale: "No" if base client type is Leader/Star (premium)
            if _base_ct:
                rec_exp["Base to List Sale"] = rec_exp[_base_ct].apply(
                    lambda v: "No" if str(v).strip().upper() in
                              ("LEADER","STAR","PREFERRED STAR","PREFERRED LEADER") else "Yes")

            # Collection: "Yes" if not paid via NACH/ECS auto-debit
            if _mode_c:
                rec_exp["Collection"] = rec_exp[_mode_c].apply(
                    lambda v: "No" if ("NACH" in str(v).upper() or "ECS" in str(v).upper())
                              else "Yes")

            # L2-L6 hierarchy from struct_map
            if _empid_c:
                _hier_df = rec_exp[_empid_c].apply(lambda v: pd.Series(_hier(v)))
                for _hcol in _hier_df.columns:
                    if _hcol not in rec_exp.columns:
                        rec_exp[_hcol] = _hier_df[_hcol]

            if len(rec_exp) > 100_000: rec_exp = rec_exp.head(100_000)
            write_sheet(rec_exp, "Receipt Data", header_fmt=grey)
        except Exception as _e:
            st.warning(f"Receipt Data sheet error: {_e}")

        # ── Refund Data ──────────────────────────────────────────────────────
        try:
            ref_exp = refund_df.copy()
            ref_exp = ref_exp.loc[:, ~ref_exp.columns.astype(str).str.lower().str.startswith("unnamed")]
            ref_exp = ref_exp.loc[:, ref_exp.columns.astype(str).str.strip() != ""]
            _date_rf  = find_col(ref_exp, ["Clear Date","Date","Refund Date","I"])
            _empid_rf = find_col(ref_exp, ["Sales Ex. ID","Sales Exec ID","EMP ID","J"])

            if _date_rf:
                _days_rf = pd.to_datetime(ref_exp[_date_rf], errors='coerce').dt.day
                ref_exp["Day"]  = _days_rf
                ref_exp["Week"] = _days_rf.apply(lambda d: "WK-1" if d<10 else "WK-2" if d<17 else "WK-3" if d<24 else "WK-4")
                ref_exp["FNT"]  = _days_rf.apply(lambda d: "FNT-1" if d<=16 else "FNT-2")

            if _empid_rf:
                _hier_rf = ref_exp[_empid_rf].apply(lambda v: pd.Series(_hier(v)))
                for col in _hier_rf.columns:
                    if col not in ref_exp.columns:
                        ref_exp[col] = _hier_rf[col]

            if len(ref_exp) > 100_000: ref_exp = ref_exp.head(100_000)
            write_sheet(ref_exp, "Refund Data", header_fmt=grey)
        except Exception:
            pass

        # ── Renewal Data ─────────────────────────────────────────────────────
        try:
            # Use unfiltered raw renewal data so all months show in Renewal Data sheet
            _rnl_for_export = renewal_df_raw if (renewal_df_raw is not None and len(renewal_df_raw) > 0) else renewal_df
            if _rnl_for_export is not None and len(_rnl_for_export) > 0:
                rnl_exp = _rnl_for_export.copy()
                # Drop unnamed/blank-header columns
                rnl_exp = rnl_exp.loc[:, ~rnl_exp.columns.astype(str).str.lower().str.startswith("unnamed")]
                rnl_exp = rnl_exp.loc[:, rnl_exp.columns.astype(str).str.strip() != ""]

                _empid_rn   = find_col(rnl_exp, ["EMP ID","Emp ID","Employee ID","O"])
                # Status.1 = received/pending status in sir's file
                _recvd_rn   = find_col(rnl_exp, ["Received Date","Received","Received.1","AK"])
                _status_rn  = find_col(rnl_exp, ["Status.1","Status","Received","AH"])
                _remarks_rn = find_col(rnl_exp, ["Remarks (New)","Remarks(New)","Remarks_New","AS"])
                _vert_rn    = find_col(rnl_exp, ["Vertical Final","Vertical","S","W"])
                _month_rn   = find_col(rnl_exp, ["Month","month"])
                _remk_rn    = find_col(rnl_exp, ["Remarks","Remarks_Old","P"])
                _due_rn     = find_col(rnl_exp, ["Inv Due Date","InvDueDate","Due Date","N"])
                _loc_rn     = find_col(rnl_exp, ["Location","Q"])

                # Pending AMR: clients due in NEXT month (MDC-1 clients for current month)
                # = Inv Due Date is in next month relative to sel_month
                if _due_rn and sel_month:
                    _mo_map = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                               "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
                    _sel_mo = _mo_map.get(str(sel_month).strip()[:3], 5)
                    _next_mo = (_sel_mo % 12) + 1
                    _due_dates_rn = pd.to_datetime(rnl_exp[_due_rn], errors='coerce')
                    rnl_exp["Pending AMR"] = _due_dates_rn.apply(
                        lambda d: "Yes" if (pd.notna(d) and d.month == _next_mo) else "No")
                elif _status_rn:
                    rnl_exp["Pending AMR"] = rnl_exp[_status_rn].apply(
                        lambda v: "Yes" if "PENDING" in str(v).upper() else "No")

                # AMR Renewal (MDC-1): CSD employees with Inv Due Date = next month
                if "Pending AMR" in rnl_exp.columns and _vert_rn:
                    rnl_exp["AMR Renewal (MDC-1)"] = rnl_exp.apply(
                        lambda r: ("MDC-1" if (r.get("Pending AMR","No") == "Yes" and
                                               "CSD" in str(r.get(_vert_rn,"")).upper())
                                   else ""),
                        axis=1)

                # SS+ Client: from the Remarks (old) column
                if _remk_rn:
                    _ss_keywords = {"SS+","PREFERRED","PREFERRED STAR","PREFERRED LEADER",
                                    "STAR","LEADER","PL+"}
                    rnl_exp["SS+ Client"] = rnl_exp[_remk_rn].apply(
                        lambda v: "Yes" if any(k.upper() == str(v).strip().upper()
                                               for k in _ss_keywords) else "No")

                # L2-L6 hierarchy from struct_map
                if _empid_rn:
                    _hier_rn = rnl_exp[_empid_rn].apply(lambda v: pd.Series(_hier(v)))
                    for col in _hier_rn.columns:
                        if col not in rnl_exp.columns:
                            rnl_exp[col] = _hier_rn[col]

                if len(rnl_exp) > 100_000: rnl_exp = rnl_exp.head(100_000)
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
