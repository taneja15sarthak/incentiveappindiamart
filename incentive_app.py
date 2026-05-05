"""
Tele Annual (TA) Incentive Calculator - Apr 2026
All levels: L1 Exec, L2 Rel'n Mgr, L3 BM, L4 CH + Nursery
For Tele Annual CSD and Tele Annual KCD - SEPARATE from regular CSD/KCD
"""
import streamlit as st
import pandas as pd
import io
from datetime import date

st.set_page_config(page_title="TA Incentive Calculator", layout="wide", page_icon="📊")

CALC_DATE  = date(2026, 4, 30)
EXCEL_EPOCH= date(1899, 12, 30)

IM_STAR_LEADER_KW = {"IM STAR","IM LEADER","CITY STAR","CITY LEADER","PREFERRED STAR",
    "PREFERRED LEADER","IM STAR PRO","IM LEADER PRO","PREFERRED STAR PRO",
    "PREFERRED LEADER PRO","IM STAR-ADDON","IM STAR PRO-ADDON",
    "PREFERRED STAR PRO-ADDON","PREFERRED LEADER-ADDON"}
IM_STAR_PRO_KW = {"IM STAR PRO","IM LEADER PRO","PREFERRED STAR PRO",
    "PREFERRED LEADER PRO","PREFERRED STAR PRO-ADDON","PREFERRED LEADER-ADDON"}
SS_PLUS_KW = {"IM STAR","IM LEADER","CITY STAR","CITY LEADER","PREFERRED STAR",
    "PREFERRED LEADER","IM STAR PRO","IM LEADER PRO","PREFERRED STAR PRO","PREFERRED LEADER PRO"}

# ──────────────────────────────────────────────────────────
# SLAB CONFIG (defaults + loader)
# ──────────────────────────────────────────────────────────
def build_ta_slab_config():
    csd_milestones = pd.DataFrame([
        {"Min_Ach_Pct":140,"Grid":8000},
        {"Min_Ach_Pct":120,"Grid":6000},
        {"Min_Ach_Pct":100,"Grid":4000},
    ])
    csd_targets = pd.DataFrame([
        {"Vintage":"0-90","Target_PCDV":1300},
        
        {"Vintage":"90-270","Target_PCDV":1800},
        {"Vintage":"270+","Target_PCDV":2000},
    ])
    csd_cmr_mult = pd.DataFrame([
        {"Min_CMR_Ach_Pct":120,"Multiplier":1.2},
        {"Min_CMR_Ach_Pct":100,"Multiplier":1.0},
        {"Min_CMR_Ach_Pct":0,"Multiplier":0.0},
    ])
    csd_params = pd.DataFrame([
        {"Parameter":"Incr_Rate_Pct","Value":3.0},
        {"Parameter":"CMR_Target_Pct","Value":40.0},
    ])
    csd_spot_2_6  = pd.DataFrame([{"Txn":3,"Inc":2250},{"Txn":2,"Inc":1500},{"Txn":1,"Inc":500}])
    csd_spot_7_12 = pd.DataFrame([{"Txn":3,"Inc":2250},{"Txn":2,"Inc":1500},{"Txn":1,"Inc":500}])
    csd_spot_20_30= pd.DataFrame([{"Txn":6,"Inc":4250},{"Txn":5,"Inc":3500},{"Txn":4,"Inc":1375},{"Txn":3,"Inc":1000}])

    kcd_milestones= csd_milestones.copy()
    kcd_targets   = csd_targets.copy()
    kcd_spot_1_12 = pd.DataFrame([
        {"PCDV":9000,"Inc":8000},{"PCDV":7000,"Inc":5500},
        {"PCDV":6000,"Inc":4500},{"PCDV":5500,"Inc":4000},{"PCDV":4500,"Inc":3000},
    ])
    kcd_spot_20_30= kcd_spot_1_12.copy()
    kcd_25cr_1_12 = pd.DataFrame([
        {"PCDV":12000,"Inc":10000},{"PCDV":10000,"Inc":8000},
        {"PCDV":8000,"Inc":6000},{"PCDV":6000,"Inc":4000},
    ])
    kcd_25cr_20_30= kcd_25cr_1_12.copy()
    kcd_rm_1_12   = kcd_spot_1_12.copy()
    kcd_rm_20_30  = kcd_spot_20_30.copy()
    kcd_ss_mult   = pd.DataFrame([{"Min_SS_CMR_Pct":50,"Multiplier":1.25},{"Min_SS_CMR_Pct":0,"Multiplier":0.5}])
    kcd_params    = pd.DataFrame([{"Parameter":"Min_SS_Sent","Value":3}])

    nursery_params= pd.DataFrame([
        {"Parameter":"Inc_Per_Txn","Value":1000},
        {"Parameter":"Min_Prod","Value":3},
        {"Parameter":"Sent_Table_Max","Value":4},
    ])
    nursery_grid  = pd.DataFrame([
        {"Min_CMR_Pct":80,"Mult":1.0},{"Min_CMR_Pct":60,"Mult":0.6},
        {"Min_CMR_Pct":50,"Mult":0.35},{"Min_CMR_Pct":0,"Mult":0.0},
    ])
    nursery_table = pd.DataFrame([
        {"Sent":4,"Min_Recd":3,"Mult":1.0},{"Sent":3,"Min_Recd":2,"Mult":1.0},
        {"Sent":2,"Min_Recd":1,"Mult":1.0},{"Sent":1,"Min_Recd":0,"Mult":1.0},
        {"Sent":0,"Min_Recd":0,"Mult":0.0},
    ])
    bm_csd = pd.DataFrame([{"Min_Ach_Pct":100,"Inc":20000},{"Min_Ach_Pct":95,"Inc":15000},{"Min_Ach_Pct":85,"Inc":10000}])
    bm_kcd = pd.DataFrame([{"Min_Ach_Pct":100,"Inc":20000},{"Min_Ach_Pct":90,"Inc":15000},{"Min_Ach_Pct":80,"Inc":10000}])
    ch_csd = pd.DataFrame([{"Min_Ach_Pct":100,"Inc":25000},{"Min_Ach_Pct":90,"Inc":20000}])
    ch_kcd = pd.DataFrame([{"Min_Ach_Pct":100,"Inc":25000},{"Min_Ach_Pct":90,"Inc":20000}])
    bt_bm_csd = pd.DataFrame([{"Deal_Size":"3L+","Min_Lakh":300,"Per_Deal":15000},{"Deal_Size":"2L+","Min_Lakh":200,"Per_Deal":10000},{"Deal_Size":"1L+","Min_Lakh":100,"Per_Deal":5000}])
    bt_ch_csd = pd.DataFrame([{"Deal_Size":"3L+","Min_Lakh":300,"Per_Deal":25000},{"Deal_Size":"2L+","Min_Lakh":200,"Per_Deal":15000},{"Deal_Size":"1L+","Min_Lakh":100,"Per_Deal":7500}])
    bt_bm_kcd = pd.DataFrame([{"Deal_Size":"10L+","Min_Lakh":1000,"Per_Deal":30000},{"Deal_Size":"8L+","Min_Lakh":800,"Per_Deal":20000},{"Deal_Size":"5L+","Min_Lakh":500,"Per_Deal":10000},{"Deal_Size":"3L+","Min_Lakh":300,"Per_Deal":5000}])
    bt_ch_kcd = pd.DataFrame([{"Deal_Size":"10L+","Min_Lakh":1000,"Per_Deal":50000},{"Deal_Size":"8L+","Min_Lakh":800,"Per_Deal":30000},{"Deal_Size":"5L+","Min_Lakh":500,"Per_Deal":15000},{"Deal_Size":"3L+","Min_Lakh":300,"Per_Deal":7500}])
    bm_csd_target = pd.DataFrame([{"Parameter":"Collection_Target","Value":0}])

    return {
        "CSD_Milestones":csd_milestones, "CSD_Targets":csd_targets,
        "CSD_CMR_Mult":csd_cmr_mult, "CSD_Params":csd_params,
        "CSD_Spot_2_6":csd_spot_2_6, "CSD_Spot_7_12":csd_spot_7_12, "CSD_Spot_20_30":csd_spot_20_30,
        "KCD_Milestones":kcd_milestones, "KCD_Targets":kcd_targets,
        "KCD_Spot_1_12":kcd_spot_1_12, "KCD_Spot_20_30":kcd_spot_20_30,
        "KCD_25Cr_Spot_1_12":kcd_25cr_1_12, "KCD_25Cr_Spot_20_30":kcd_25cr_20_30,
        "KCD_RM_Spot_1_12":kcd_rm_1_12, "KCD_RM_Spot_20_30":kcd_rm_20_30,
        "KCD_SS_Mult":kcd_ss_mult, "KCD_Params":kcd_params,
        "Nursery_Params":nursery_params, "Nursery_CMR_Grid":nursery_grid,
        "Nursery_CMR_Table":nursery_table,
        "BM_CSD_Slabs":bm_csd, "BM_KCD_Slabs":bm_kcd,
        "CH_CSD_Slabs":ch_csd, "CH_KCD_Slabs":ch_kcd,
        "BT_BM_CSD":bt_bm_csd, "BT_CH_CSD":bt_ch_csd,
        "BT_BM_KCD":bt_bm_kcd, "BT_CH_KCD":bt_ch_kcd,
        "BM_CSD_Target":bm_csd_target,
    }


def load_ta_slab_config(f):
    defs = build_ta_slab_config()
    if f is None: return defs
    xl = pd.ExcelFile(f)
    cfg = {}
    for k, dd in defs.items():
        if k in xl.sheet_names:
            df = pd.read_excel(f, sheet_name=k, header=1).dropna(how="all")
            cfg[k] = df
        else:
            cfg[k] = dd
    return cfg


def parse_slabs(cfg):
    def rows(k):   return cfg[k].to_dict("records")
    def param(k,p,d):
        df = cfg.get(k, pd.DataFrame())
        if len(df)==0: return d
        r = df[df.iloc[:,0].astype(str)==p]
        return float(r.iloc[0,1]) if len(r)>0 else d

    return {
        "csd_milestones":sorted(rows("CSD_Milestones"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "csd_targets":   {r["Vintage"]:float(r["Target_PCDV"]) for r in rows("CSD_Targets")},
        "csd_cmr_mult":  sorted(rows("CSD_CMR_Mult"),key=lambda r:-r.get("Min_CMR_Ach_Pct",0)),
        "csd_incr_rate": param("CSD_Params","Incr_Rate_Pct",3.0)/100,
        "csd_cmr_tgt":   param("CSD_Params","CMR_Target_Pct",40.0),
        "csd_spot_2_6":  sorted(rows("CSD_Spot_2_6"),  key=lambda r:-r.get("Txn",0)),
        "csd_spot_7_12": sorted(rows("CSD_Spot_7_12"), key=lambda r:-r.get("Txn",0)),
        "csd_spot_20_30":sorted(rows("CSD_Spot_20_30"),key=lambda r:-r.get("Txn",0)),
        "kcd_milestones":sorted(rows("KCD_Milestones"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "kcd_targets":   {r["Vintage"]:float(r["Target_PCDV"]) for r in rows("KCD_Targets")},
        "kcd_spot_1_12": sorted(rows("KCD_Spot_1_12"), key=lambda r:-r.get("PCDV",0)),
        "kcd_spot_20_30":sorted(rows("KCD_Spot_20_30"),key=lambda r:-r.get("PCDV",0)),
        "kcd_25cr_1_12": sorted(rows("KCD_25Cr_Spot_1_12"),key=lambda r:-r.get("PCDV",0)),
        "kcd_25cr_20_30":sorted(rows("KCD_25Cr_Spot_20_30"),key=lambda r:-r.get("PCDV",0)),
        "kcd_rm_1_12":   sorted(rows("KCD_RM_Spot_1_12"), key=lambda r:-r.get("PCDV",0)),
        "kcd_rm_20_30":  sorted(rows("KCD_RM_Spot_20_30"),key=lambda r:-r.get("PCDV",0)),
        "kcd_ss_mult":   sorted(rows("KCD_SS_Mult"),key=lambda r:-r.get("Min_SS_CMR_Pct",0)),
        "kcd_min_ss_sent":int(param("KCD_Params","Min_SS_Sent",3)),
        "nursery_inc_per_txn":int(param("Nursery_Params","Inc_Per_Txn",1000)),
        "nursery_min_prod":   int(param("Nursery_Params","Min_Prod",3)),
        "nursery_sent_max":   int(param("Nursery_Params","Sent_Table_Max",4)),
        "nursery_grid": sorted(rows("Nursery_CMR_Grid"), key=lambda r:-r.get("Min_CMR_Pct",0)),
        "nursery_table":{r["Sent"]:(r["Min_Recd"],r["Mult"]) for r in rows("Nursery_CMR_Table")},
        "bm_csd": sorted(rows("BM_CSD_Slabs"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "bm_kcd": sorted(rows("BM_KCD_Slabs"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "ch_csd": sorted(rows("CH_CSD_Slabs"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "ch_kcd": sorted(rows("CH_KCD_Slabs"),key=lambda r:-r.get("Min_Ach_Pct",0)),
        "bt_bm_csd":sorted(rows("BT_BM_CSD"),key=lambda r:-r.get("Min_Lakh",0)),
        "bt_ch_csd":sorted(rows("BT_CH_CSD"),key=lambda r:-r.get("Min_Lakh",0)),
        "bt_bm_kcd":sorted(rows("BT_BM_KCD"),key=lambda r:-r.get("Min_Lakh",0)),
        "bt_ch_kcd":sorted(rows("BT_CH_KCD"),key=lambda r:-r.get("Min_Lakh",0)),
    }


@st.cache_data(show_spinner=False)
def make_slab_excel():
    cfg = build_ta_slab_config()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        hf = w.book.add_format({"bold":True,"bg_color":"#1F4E79","font_color":"#FFFFFF","border":1})
        nf = w.book.add_format({"italic":True,"font_color":"#595959"})
        for sh, df in cfg.items():
            df.to_excel(w, sheet_name=sh, index=False, startrow=1)
            ws = w.sheets[sh]
            ws.set_column(0, len(df.columns)-1, 22)
            for ci,col in enumerate(df.columns): ws.write(1,ci,col,hf)
            ws.write(0,0,f"TA Slab Config | {sh} | Edit values below, do NOT rename columns.",nf)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────
# UTILITY
# ──────────────────────────────────────────────────────────
def find_col(df, candidates):
    def n(s): return " ".join(str(s).lower().split())
    nm = {n(c):c for c in df.columns}
    for c in candidates:
        if n(c) in nm: return nm[n(c)]
    return None

@st.cache_data(show_spinner=False)
def load_excel(bts:bytes, fname:str)->pd.DataFrame:
    ext = fname.lower().rsplit(".",1)[-1] if "." in fname else "xlsx"
    buf = io.BytesIO(bts)
    try:
        return pd.read_excel(buf, engine="pyxlsb" if ext=="xlsb" else "openpyxl")
    except Exception as e:
        st.error(f"Cannot read '{fname}': {e}"); return pd.DataFrame()

def _rf(f):
    if f is None: return pd.DataFrame()
    return load_excel(f.getvalue(), f.name)

def _sf(v, d=0.0):
    try:
        fv=float(v); return fv if fv==fv else d
    except: return d

def _to_date(v):
    import datetime as dt
    if v is None: return None
    if isinstance(v,dt.date) and not isinstance(v,dt.datetime): return v
    if isinstance(v,dt.datetime): return v.date()
    if isinstance(v,pd.Timestamp): return v.date()
    try:
        fv=float(v)
        if 30000<fv<60000: return EXCEL_EPOCH+dt.timedelta(days=int(fv))
    except: pass
    try: return pd.to_datetime(str(v)).date()
    except: return None


# ──────────────────────────────────────────────────────────
# STRUCTURE LOADER  (OPTIMISED: iterrows → to_dict)
# ──────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_ta_structure(fbytes: bytes, fname: str):
    """Cached, fast version — accepts raw bytes so st.cache_data can hash it."""
    import io as _io
    try:
        buf = _io.BytesIO(fbytes)
        xl  = pd.ExcelFile(buf)
        norms = [s.strip().upper() for s in xl.sheet_names]
        sh = next((xl.sheet_names[i] for i,s in enumerate(norms)
                   if s in ("FSF_TA","TA","STRUCT","STRUCTURE"," FSF_TA")), None)
        if sh is None:
            st.warning("⚠️ Could not find FSF_TA/TA sheet in the structure file.")
            return {}
        buf.seek(0)
        df = pd.read_excel(buf, sheet_name=sh)
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        st.error(f"Structure file error: {e}"); return {}

    def gc(candidates): return find_col(df, candidates)
    ec  = gc(["Employee ID","Emp ID","EmpID"])
    nc  = gc(["Employee Name"])
    dc  = gc(["Designation"])
    vc  = gc(["IIL Vertical Name","Vertical","IIL Vertical"])
    jc  = gc(["Joining Date","DOJ"])
    fgc = gc(["Final Group","FinalGroup","Vintage"])
    cac = gc(["Client-A","Client A"])
    ccc = gc(["Client-C","Client C"])
    agc = gc(["Aeging","Ageing","Aging"])
    hcc = gc(["HC"])
    grc = gc(["Group"])
    rmc = gc(["Remarks"])
    l2i = gc(["L2 ID","L2ID"]); l2n = gc(["L2 Name","L2Name"])
    l3i = gc(["L3 ID","L3ID"]); l3n = gc(["L3 Name","L3Name"])
    l4i = gc(["L4 ID","L4ID"]); l4n = gc(["L4 Name","L4Name"])
    l5i = gc(["L5 ID","L5ID"]); l5n = gc(["L5 Name","L5Name"])
    l6i = gc(["L6 ID","L6  ID","L6ID"]); l6n = gc(["L6 Name","L6Name"])
    mdc_c  = gc(["MDC"]); star_c = gc(["Star"]); ldr_c  = gc(["Leader"])
    wsm_c  = gc(["WS-M"]); wsa_c  = gc(["WS-A"]); ive_c  = gc(["IVE"])
    mdc1_c = gc(["MDC.1"]); star1_c= gc(["Star.1"]); ldr1_c = gc(["Leader.1"])
    wsm1_c = gc(["WS-M.1"]); wsa1_c = gc(["WS-A.1"]); ive1_c = gc(["IVE.1"])
    email_c= gc(["Email Id"]); loc_c  = gc(["Location","New Location/ROI Location"])

    if not ec: return {}

    # ── FAST: to_dict is ~10x faster than iterrows ──────────
    result = {}
    import datetime as _dt
    for row in df.to_dict("records"):
        eid = str(row.get(ec,"")).strip().split(".")[0]
        if not eid or eid.lower() in ("nan","none",""): continue

        vraw = str(row.get(vc,"")).strip().upper() if vc else ""
        if "TELE" not in vraw: continue
        if "CSD" in vraw:   vert = "CSD"
        elif "KCD" in vraw: vert = "KCD"
        else: continue

        desig = str(row.get(dc,"")).strip().upper() if dc else "L1"
        vint  = "90-270"  # placeholder; overridden by ageing in calc loop

        ageing = 0
        if agc and str(row.get(agc,"")).strip() not in ("nan","None",""):
            try: ageing = int(float(row[agc]))
            except: pass
        if ageing == 0:
            jd = _to_date(row.get(jc)) if jc else None
            if jd:
                try:
                    jd_date = jd.date() if isinstance(jd, _dt.datetime) else jd
                    ageing = (CALC_DATE - jd_date).days
                except: ageing = 0

        def sv(c): return str(row.get(c,"")).strip() if c else ""
        def nv(c): return _sf(row.get(c,0)) if c else 0.0
        def id_sv(c): return str(row.get(c,"")).strip().split(".")[0] if c else ""

        result[eid] = {
            "Name":     sv(nc),   "Designation": desig,
            "Vertical": vert,     "Vintage":     vint,
            "Ageing":   ageing,   "Joining Date":_to_date(row.get(jc)) if jc else None,
            "Client-A": nv(cac),  "Client-C":    nv(ccc),
            "HC":       nv(hcc),  "Group":       sv(grc),
            "Remarks":  sv(rmc),  "Email Id":    sv(email_c),
            "Location": sv(loc_c),
            "MDC":  nv(mdc_c),"Star": nv(star_c),"Leader":nv(ldr_c),
            "WS-M": nv(wsm_c),"WS-A": nv(wsa_c), "IVE":  nv(ive_c),
            "MDC.1":nv(mdc1_c),"Star.1":nv(star1_c),"Leader.1":nv(ldr1_c),
            "WS-M.1":nv(wsm1_c),"WS-A.1":nv(wsa1_c),"IVE.1":nv(ive1_c),
            "L2 ID":id_sv(l2i),"L2 Name":sv(l2n),
            "L3 ID":id_sv(l3i),"L3 Name":sv(l3n),
            "L4 ID":id_sv(l4i),"L4 Name":sv(l4n),
            "L5 ID":id_sv(l5i),"L5 Name":sv(l5n),
            "L6 ID":id_sv(l6i),"L6 Name":sv(l6n),
        }

    # Aggregate Client-A and HC for management levels from L1 data
    if ec and cac:
        try:
            df["_eid"] = df[ec].astype(str).str.split(".").str[0].str.strip()
            df[cac] = pd.to_numeric(df[cac], errors="coerce").fillna(0)
            l1_df = df[df[dc].astype(str).str.strip().str.upper()=="L1"] if dc else df
            def _agg_for(id_col, src_df=None):
                if not id_col: return {}
                src = src_df if src_df is not None else l1_df
                return src.groupby(src[id_col].astype(str).str.split(".").str[0].str.strip()).agg(
                    ca_sum=(cac,"sum"), l1_cnt=("_eid","count")).to_dict("index")
            l2_df = df[df[dc].astype(str).str.strip().str.upper()=="L2"] if dc else df
            agg_l2_cnt = _agg_for(l3i, l2_df) if l3i else {}
            agg_l2 = _agg_for(l2i); agg_l3 = _agg_for(l3i)
            agg_l4 = _agg_for(l4i); agg_l5 = _agg_for(l5i)
            for eid, emp in result.items():
                d = emp["Designation"]; a = None
                if d=="L2":   a = agg_l2.get(eid)
                elif d=="L3":
                    a = agg_l3.get(eid)
                    l2c = agg_l2_cnt.get(eid)
                    if l2c: result[eid]["L2_Count"] = int(l2c["l1_cnt"])
                elif d=="L4": a = agg_l4.get(eid)
                elif d=="L5": a = agg_l5.get(eid)
                if a:
                    result[eid]["Client-A_Agg"] = float(a["ca_sum"])
                    result[eid]["HC"]            = int(a["l1_cnt"])
                    result[eid]["L1_Count"]      = int(a["l1_cnt"])
        except Exception: pass
    return result


def get_months(rec_df, rnl_df):
    months = set()
    dc = find_col(rec_df, ["Entry Date","Clear Date","Receipt Date"])
    if dc:
        for d in pd.to_datetime(rec_df[dc], errors="coerce").dropna():
            months.add(d.strftime("%b-%y"))
    if rnl_df is not None:
        mc = find_col(rnl_df, ["Month","MONTH"])
        if mc:
            for m in rnl_df[mc].dropna().unique():
                try:
                    p = pd.to_datetime(str(m), format="%b'%y", errors="coerce")
                    if pd.notna(p): months.add(p.strftime("%b-%y"))
                except: pass
    return sorted(months, key=lambda x: pd.to_datetime(x, format="%b-%y"))


def get_prev_month_str(sel, available_months):
    """Return previous month string for CMR+1, or None if unavailable."""
    try:
        import pandas as _pd2
        prev = (_pd2.to_datetime(sel, format="%b-%y") - _pd2.DateOffset(months=1)).strftime("%b-%y")
        return prev if prev in available_months else None
    except: return None

def filter_month(rec, ref, rnl, sel):
    tgt = pd.to_datetime(sel, format="%b-%y")
    tm, ty = tgt.month, tgt.year

    def _dt(s):
        p = pd.to_datetime(s, errors="coerce")
        nums = pd.to_numeric(s, errors="coerce")
        ec = (p.dt.year==1970).sum() if p.notna().any() else 0
        if ec > p.notna().sum()*0.5:
            base = pd.Timestamp("1899-12-30")
            p = nums.apply(lambda x: base+pd.Timedelta(days=int(x)) if pd.notna(x) and x>0 else pd.NaT)
        return p

    dc = find_col(rec, ["Entry Date","Clear Date","Receipt Date"])
    r  = rec.copy()
    if dc:
        dt = _dt(r[dc]); r = r[(dt.dt.month==tm)&(dt.dt.year==ty)]

    rf = ref.copy()
    rdc = find_col(rf, ["Clear Date","Month"])
    if rdc:
        dt2 = _dt(rf[rdc]); rf = rf[(dt2.dt.month==tm)&(dt2.dt.year==ty)]

    rn = rnl.copy() if rnl is not None else None
    if rn is not None:
        mc = find_col(rn, ["Month","MONTH"])
        if mc:
            def _m(v):
                try:
                    p = pd.to_datetime(str(v).strip(), format="%b'%y", errors="coerce")
                    return pd.notna(p) and p.month==tm and p.year==ty
                except: return False
            rn = rn[rn[mc].apply(_m)]
    return r, rf, rn


# ──────────────────────────────────────────────────────────
# CMR  (OPTIMISED: accept pre-grouped data)
# ──────────────────────────────────────────────────────────
def _cmr_from_group(grp, sc, pc):
    """Compute CMR stats from an already-filtered DataFrame slice."""
    zero = {"sent":0,"recd":0,"pct":0.0,"ss_sent":0,"ss_recd":0,"ss_pct":0.0}
    if grp is None or len(grp) == 0: return zero
    rm = grp[sc].astype(str).str.upper().str.contains("RECEIVED", na=False) if sc else pd.Series(False, index=grp.index)
    sent, recd = len(grp), int(rm.sum())
    pct = round(recd/sent*100, 2) if sent > 0 else 0.0
    if pc:
        ss = grp[pc].astype(str).str.upper().apply(lambda x: any(k in x for k in SS_PLUS_KW))
    else:
        ss = pd.Series(False, index=grp.index)
    ss_s = int(ss.sum()); ss_r = int((ss & rm).sum())
    return {"sent":sent,"recd":recd,"pct":pct,
            "ss_sent":ss_s,"ss_recd":ss_r,
            "ss_pct":round(ss_r/ss_s*100,2) if ss_s>0 else 0.0}

def calc_cmr(rnl, eid_str, _rnl_by_eid=None, _rnl_sc=None, _rnl_pc=None):
    """Falls back to full-scan if pre-grouped dict not supplied (backward compat)."""
    zero = {"sent":0,"recd":0,"pct":0.0,"ss_sent":0,"ss_recd":0,"ss_pct":0.0}
    if rnl is None or len(rnl)==0: return zero
    if _rnl_by_eid is not None:
        grp = _rnl_by_eid.get(str(eid_str).strip(), pd.DataFrame())
        return _cmr_from_group(grp, _rnl_sc, _rnl_pc)
    # Legacy path (slow) — kept for compatibility
    ec = find_col(rnl, ["EMP ID","Emp ID","EmpID","Employee ID"])
    sc = find_col(rnl, ["Status","STATUS"])
    pc = find_col(rnl, ["WS/MDC Main","Product","Service"])
    if not ec: return zero
    grp = rnl[rnl[ec].astype(str).str.split(".").str[0].str.strip()==str(eid_str)]
    return _cmr_from_group(grp, sc, pc)

def calc_cmr_by_name(rnl, l2_col, name, _rnl_by_name=None, _rnl_sc=None, _rnl_pc=None):
    """Falls back to full-scan if pre-grouped dict not supplied (backward compat)."""
    zero = {"sent":0,"recd":0,"pct":0.0,"ss_sent":0,"ss_recd":0,"ss_pct":0.0}
    if rnl is None or not l2_col or not name: return zero
    if _rnl_by_name is not None:
        grp = _rnl_by_name.get(str(name).strip(), pd.DataFrame())
        return _cmr_from_group(grp, _rnl_sc, _rnl_pc)
    # Legacy path (slow)
    if l2_col not in rnl.columns: return zero
    grp = rnl[rnl[l2_col].astype(str).str.strip()==name.strip()]
    sc = find_col(rnl, ["Status","STATUS"])
    pc = find_col(rnl, ["WS/MDC Main","Product","Service"])
    return _cmr_from_group(grp, sc, pc)


# ──────────────────────────────────────────────────────────
# RECEIPT EXTRACTION  (OPTIMISED: pre-grouped data)
# ──────────────────────────────────────────────────────────
def clean_receipt(df):
    """Keep only CLEARED rows with no B/C flag."""
    df = df.copy()
    bc = find_col(df,["B/C"])
    if bc: df = df[df[bc].isna()|(df[bc].astype(str).str.strip()=="")]
    sc = find_col(df,["Status","PAYMENT STATUS","Payment Status"])
    if sc:
        cl = df[df[sc].astype(str).str.upper().str.strip()=="CLEARED"]
        if len(cl)>0: df=cl
    return df


def _build_rec_index(rec):
    """Pre-compute all column names and grouped sub-DataFrames for receipt.
    Called ONCE before the employee loop — O(N) not O(N*M).
    Returns (col_cache dict, grouped dicts).
    """
    cols = {
        "ec":  find_col(rec, ["Sales Exec ID","EMP ID","Emp ID"]),
        "dvc": find_col(rec, ["Deal Val (WT)","Deal Value","Deal Val"]),
        "wtc": find_col(rec, ["WT AMT","WT_AMT"]),
        "dtc": find_col(rec, ["Entry Date","Clear Date","Receipt Date"]),
        "upc": find_col(rec, ["Unique","Upsell","UNIQUE"]),
        "mgc": find_col(rec, ["Manager Id","Old Sales HOD-3 ID"]),
        "hodc":find_col(rec, ["HOD Id","Old Sales Hod ID"]),
    }
    grp_l1 = {}; grp_mgr = {}; grp_hod = {}
    if cols["ec"]:
        rec = rec.copy()
        rec["_eid"]  = rec[cols["ec"]].astype(str).str.split(".").str[0].str.strip()
        grp_l1 = dict(tuple(rec.groupby("_eid", sort=False)))
    if cols["mgc"]:
        rec["_mgr"]  = rec[cols["mgc"]].astype(str).str.split(".").str[0].str.strip()
        grp_mgr = dict(tuple(rec.groupby("_mgr", sort=False)))
    if cols["hodc"]:
        rec["_hod"]  = rec[cols["hodc"]].astype(str).str.split(".").str[0].str.strip()
        grp_hod = dict(tuple(rec.groupby("_hod", sort=False)))
    return cols, grp_l1, grp_mgr, grp_hod


def _build_ref_index(ref):
    """Pre-compute refund column + grouped dict."""
    rfc = find_col(ref,["Sales Ex. ID","Sales Exec ID","EMP ID"])
    wac = find_col(ref,["WT Amount","WT_Amount","WT AMT"])
    grp_ref = {}
    if rfc and len(ref):
        ref = ref.copy()
        ref["_eid"] = ref[rfc].astype(str).str.split(".").str[0].str.strip()
        grp_ref = dict(tuple(ref.groupby("_eid", sort=False)))
    return rfc, wac, grp_ref


def get_emp_data(rec, ref, eid_str, desig="L1", emp_name="", client_a=1, is_l2=False,
                 _rec_cols=None, _grp_l1=None, _grp_mgr=None, _grp_hod=None,
                 _ref_wac=None, _grp_ref=None):
    """
    Designation-aware receipt matching.
    Fast path: supply pre-built index dicts (_rec_cols, _grp_*).
    Slow path (legacy): falls back to full DataFrame scans.
    """
    # ── resolve column cache ──────────────────────────────
    if _rec_cols is not None:
        ec  = _rec_cols["ec"];  dvc = _rec_cols["dvc"]
        wtc = _rec_cols["wtc"]; dtc = _rec_cols["dtc"]
        upc = _rec_cols["upc"]; mgc = _rec_cols["mgc"]
        hodc= _rec_cols["hodc"]
    else:
        ec  = find_col(rec,["Sales Exec ID","EMP ID","Emp ID"])
        dvc = find_col(rec,["Deal Val (WT)","Deal Value","Deal Val"])
        wtc = find_col(rec,["WT AMT","WT_AMT"])
        dtc = find_col(rec,["Entry Date","Clear Date","Receipt Date"])
        upc = find_col(rec,["Unique","Upsell","UNIQUE"])
        mgc = find_col(rec,["Manager Id","Old Sales HOD-3 ID"])
        hodc= find_col(rec,["HOD Id","Old Sales Hod ID"])

    if not ec: return {}

    # ── fast group lookup ─────────────────────────────────
    eid_str = str(eid_str).strip()
    if _grp_l1 is not None:
        if desig == "L2" or is_l2:
            r = _grp_mgr.get(eid_str, pd.DataFrame()) if _grp_mgr else pd.DataFrame()
        elif desig in ("L3","L4","L5","L6"):
            r = _grp_hod.get(eid_str, pd.DataFrame()) if _grp_hod else pd.DataFrame()
        else:
            r = _grp_l1.get(eid_str, pd.DataFrame())
    else:
        # Legacy slow path
        if desig == "L2" or is_l2:
            hc = mgc
        elif desig in ("L3","L4","L5","L6"):
            hc = hodc
        else:
            hc = None
        if hc:
            mask = rec[hc].astype(str).str.split(".").str[0].str.strip()==eid_str
        else:
            mask = rec[ec].astype(str).str.split(".").str[0].str.strip()==eid_str
        r = rec[mask]

    gross = _sf(r[wtc].fillna(0).sum()) if (wtc and len(r)>0) else 0.0
    dval  = _sf(r[dvc].fillna(0).sum()) if (dvc and len(r)>0) else 0.0

    # ── refund ────────────────────────────────────────────
    refund = 0.0
    if _grp_ref is not None:
        rr = _grp_ref.get(eid_str, pd.DataFrame())
        if _ref_wac and len(rr)>0:
            refund = _sf(rr[_ref_wac].fillna(0).sum())
    else:
        rfc = find_col(ref,["Sales Ex. ID","Sales Exec ID","EMP ID"])
        if rfc:
            wac = find_col(ref,["WT Amount","WT_Amount","WT AMT"])
            rr = ref[ref[rfc].astype(str).str.split(".").str[0].str.strip()==eid_str]
            if wac: refund = _sf(rr[wac].fillna(0).sum())

    net_coll = gross - refund
    client_a_eff = max(float(client_a),1)

    # ── period-based deal value & spot txn counts ─────────
    fnt_dv   = {"1_12":0.0,"20_30":0.0}
    spot_txn = {"2_6":0,"7_12":0,"20_30":0}
    if dtc and len(r)>0:
        try:
            dates = pd.to_datetime(r[dtc], errors="coerce")
            nums  = pd.to_numeric(r[dtc], errors="coerce")
            if (dates.dt.year==1970).sum() > dates.notna().sum()*0.4:
                base=pd.Timestamp("1899-12-30")
                dates=nums.apply(lambda x:base+pd.Timedelta(days=int(x)) if pd.notna(x) and x>0 else pd.NaT)
            days = dates.dt.day
            if dvc:
                dv_s = pd.to_numeric(r[dvc],errors="coerce").fillna(0)
                fnt_dv["1_12"]  = float(dv_s[days<=12].sum())
                fnt_dv["20_30"] = float(dv_s[days>=20].sum())
            spot_txn["2_6"]   = int(days.between(2,6).sum())
            spot_txn["7_12"]  = int(days.between(7,12).sum())
            spot_txn["20_30"] = int((days>=20).sum())
        except: pass

    # ── IM Star / Leader counts ───────────────────────────
    im_count = 0; im_pro_count = 0
    if upc and len(r)>0:
        uv = r[upc].fillna("").astype(str).str.upper()
        im_count = int(uv.apply(lambda x: any(k in x for k in IM_STAR_LEADER_KW)).sum())
        if dtc:
            try:
                dts = pd.to_datetime(r[dtc],errors="coerce")
                d28 = dts.dt.day >= 28
                im_pro_count = int((d28 & uv.apply(
                    lambda x: any(k in x for k in IM_STAR_PRO_KW))).sum())
            except: im_pro_count=0

    pcdv_1_12  = fnt_dv["1_12"]  / client_a_eff
    pcdv_20_30 = fnt_dv["20_30"] / client_a_eff
    pcdv_total = dval / client_a_eff

    return {
        "gross":gross,"refund":refund,"net_coll":net_coll,
        "deal_val":dval,"pcdv":pcdv_total,
        "fnt_dv":fnt_dv,"pcdv_1_12":pcdv_1_12,"pcdv_20_30":pcdv_20_30,
        "spot_txn":spot_txn,"im_count":im_count,"im_pro_count":im_pro_count,
        "txns":len(r),
    }

# INCENTIVE CALCULATORS
# ──────────────────────────────────────────────────────────
def _milestone(pcdv, tgt, slabs):
    if tgt<=0: return 0
    ach = pcdv/tgt*100
    for r in slabs:
        if ach >= r.get("Min_Ach_Pct",r.get("Min_Achievement_Pct",0)):
            return r.get("Grid",r.get("Grid_Incentive",0))
    return 0

def _txn_spot(txn, slabs):
    for r in slabs:
        if txn >= r.get("Txn",r.get("Txn_Count",0)): return r.get("Inc",r.get("Incentive",0))
    return 0

def _pcdv_spot(pcdv, slabs):
    for r in slabs:
        if pcdv >= r.get("PCDV",r.get("PCDV_Threshold",0)): return r.get("Inc",r.get("Incentive",0))
    return 0

def _cmr_mult(cmr_pct, cmr_tgt, slabs):
    if cmr_tgt<=0: return 1.0
    ach = cmr_pct/cmr_tgt*100
    for r in slabs:
        if ach >= r.get("Min_CMR_Ach_Pct",0): return r.get("Multiplier",0)
    return 0.0

def _ss_mult(ss_pct, ss_sent, min_sent, slabs):
    if ss_sent < min_sent: return 1.0
    for r in slabs:
        if ss_pct >= r.get("Min_SS_CMR_Pct",0): return r.get("Multiplier",0.5)
    return 0.5

def _nursery_mult(sent, recd, cmr_pct, sent_max, cmr_grid, cmr_table):
    if sent <= sent_max:
        tbl = cmr_table.get(sent, cmr_table.get(0,(0,0.0)))
        return tbl[1] if recd >= tbl[0] else 0.0
    for r in cmr_grid:
        if cmr_pct >= r.get("Min_CMR_Pct",0): return r.get("Mult",0.0)
    return 0.0

def _bm_milestone(ach_pct, slabs):
    for r in slabs:
        if ach_pct >= r.get("Min_Ach_Pct",0): return r.get("Inc",0)
    return 0

def _big_ticket(deal_sizes_lakh, slabs):
    """deal_sizes_lakh: list of deal sizes in lakhs. Count how many fall in each bucket."""
    total = 0
    for dv in deal_sizes_lakh:
        for r in slabs:
            if dv >= r.get("Min_Lakh",0):
                total += r.get("Per_Deal",0)
                break
    return total


# ──────────────────────────────────────────────────────────
# MAIN CALCULATOR per employee
# ──────────────────────────────────────────────────────────
def calc_employee(emp, data, cmr, S, is_25cr=False):
    """Returns dict of all incentive columns for one employee."""
    vert   = emp["Vertical"]   # "CSD" or "KCD"
    desig  = emp["Designation"]
    vint   = emp["Vintage"]
    client_a = max(float(emp.get("Client-A_Agg", emp.get("Client-A",1))),1)
    hc     = max(float(emp.get("HC",1) or 1),1)

    pcdv_total  = data.get("pcdv",0)
    pcdv_1_12   = data.get("pcdv_1_12",0)
    pcdv_20_30  = data.get("pcdv_20_30",0)
    deal_val    = data.get("deal_val",0)
    fnt_dv      = data.get("fnt_dv",{})
    spot_txn    = data.get("spot_txn",{"2_6":0,"7_12":0,"20_30":0})
    im_count    = data.get("im_count",0)
    im_pro_count= data.get("im_pro_count",0)

    cmr_pct = cmr.get("pct",0); cmr_sent = cmr.get("sent",0); cmr_recd = cmr.get("recd",0)
    ss_pct  = cmr.get("ss_pct",0); ss_sent = cmr.get("ss_sent",0); ss_recd = cmr.get("ss_recd",0)

    out = {
        "gross_coll":data.get("gross",0), "refund":data.get("refund",0),
        "net_coll":data.get("net_coll",0), "deal_val":deal_val, "pcdv":pcdv_total,
        "cmr_sent":cmr_sent,"cmr_recd":cmr_recd,"cmr_pct":round(cmr_pct,1),
        "ss_sent":ss_sent,"ss_recd":ss_recd,"ss_pct":round(ss_pct,1),
        # Spot period deal values (KCD)
        "spot1_dv":fnt_dv.get("1_12",0), "spot2_dv":fnt_dv.get("20_30",0),
        "spot1_pcdv":pcdv_1_12,"spot2_pcdv":pcdv_20_30,
        # Spot period txns (CSD)
        "sp2_6_txn":spot_txn.get("2_6",0), "sp7_12_txn":spot_txn.get("7_12",0),
        "sp20_30_txn":spot_txn.get("20_30",0),
        "im_star_count":im_count, "im_star_pro_count":im_pro_count,
    }

    # ── NURSERY (L1, ageing ≤ 90 days) ────────────────────
    productivity = data.get("txns",0)  # total txns as proxy for productivity
    is_nursery = desig in ("L1","") and emp.get("FY_Ageing", emp.get("Ageing",999)) <= 90

    if is_nursery:
        min_prod = S["nursery_min_prod"]
        eligible = productivity >= min_prod
        inc = int(productivity * S["nursery_inc_per_txn"]) if eligible else 0
        mult = _nursery_mult(cmr_sent, cmr_recd, cmr_pct,
                             S["nursery_sent_max"], S["nursery_grid"], S["nursery_table"])
        gross_inc = round(inc * mult, 0)
        out.update({
            "scheme":"Nursery", "productivity":productivity,
            "eligible":"Yes" if eligible else "No",
            "renewal_mult":mult, "base_inc":inc, "gross_inc":gross_inc,
            "total_inc":int(gross_inc),
            "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":0,
        })
        return out

    # ── TELE ANNUAL CSD ────────────────────────────────────
    if vert == "CSD":
        if desig == "L1":
            tgt_pcdv = S["csd_targets"].get(vint, 1800)
            grid = _milestone(pcdv_total, tgt_pcdv, S["csd_milestones"])
            incr = round(max(0,pcdv_total-tgt_pcdv)*client_a*S["csd_incr_rate"]/1000)*1000 if grid>0 else 0
            base_incentive = grid + incr
            cmr_tgt = emp.get("CMR_Target_Pct", S["csd_cmr_tgt"])
            mult_val = _cmr_mult(cmr_pct, cmr_tgt, S["csd_cmr_mult"])
            gross_inc = round(base_incentive * mult_val, 0)
            # Spot
            sp2_6   = _txn_spot(spot_txn.get("2_6",0),  S["csd_spot_2_6"])
            sp7_12  = _txn_spot(spot_txn.get("7_12",0), S["csd_spot_7_12"])
            sp20_30 = _txn_spot(spot_txn.get("20_30",0),S["csd_spot_20_30"])
            total = int(gross_inc) + sp2_6 + sp7_12 + sp20_30
            out.update({
                "scheme":f"TA CSD Exec {vint}", "target_pcdv":tgt_pcdv,
                "incr_amt":int(incr), "incentive_grid":grid,
                "base_inc":int(base_incentive), "cmr_mult":mult_val,
                "gross_inc":int(gross_inc),
                "sp2_6_gross":sp2_6,"sp7_12_gross":sp7_12,"sp20_30_gross":sp20_30,
                "total_inc":total, "paid_inc":0, "bal_inc":total,
            })

        elif desig == "L2":
            # Rel'n Mgr CSD: team aggregate / HC
            tgt_pcdv = S["csd_targets"].get(vint, 1800)
            grid = _milestone(pcdv_total, tgt_pcdv, S["csd_milestones"])
            incr = round(max(0,pcdv_total-tgt_pcdv)*client_a*S["csd_incr_rate"]/1000)*1000 if grid>0 else 0
            base_incentive = grid + incr
            mult_val = _cmr_mult(cmr_pct, emp.get("CMR_Target_Pct", S["csd_cmr_tgt"]), S["csd_cmr_mult"])
            gross_inc = round(base_incentive * mult_val, 0)
            # Team productivity per L1 for spot
            sp2_6_prod  = spot_txn.get("2_6",0)  / hc
            sp7_12_prod = spot_txn.get("7_12",0) / hc
            sp20_30_prod= spot_txn.get("20_30",0)/ hc
            sp2_6   = _txn_spot(spot_txn.get("2_6",0),  S["csd_spot_2_6"])
            sp7_12  = _txn_spot(spot_txn.get("7_12",0), S["csd_spot_7_12"])
            sp20_30 = _txn_spot(spot_txn.get("20_30",0),S["csd_spot_20_30"])
            total = int(gross_inc) + sp2_6 + sp7_12 + sp20_30
            out.update({
                "scheme":f"TA CSD RM {vint}", "target_pcdv":tgt_pcdv,
                "incr_amt":int(incr),"incentive_grid":grid,
                "base_inc":int(base_incentive),"cmr_mult":mult_val,
                "gross_inc":int(gross_inc),
                "sp2_6_prod":round(sp2_6_prod,2),"sp7_12_prod":round(sp7_12_prod,2),
                "sp20_30_prod":round(sp20_30_prod,2),
                "sp2_6_gross":sp2_6,"sp7_12_gross":sp7_12,"sp20_30_gross":sp20_30,
                "total_inc":total,"paid_inc":0,"bal_inc":total,
            })

        elif desig == "L3":  # BM-CSD
            net_coll = data.get("net_coll",0)
            coll_target = emp.get("Coll_Target",0)
            ach_pct = (net_coll/coll_target*100) if coll_target>0 else 0
            incentive = _bm_milestone(ach_pct, S["bm_csd"])
            eligible  = ach_pct >= S["bm_csd"][-1]["Min_Ach_Pct"] if S["bm_csd"] else False
            total = int(incentive)
            out.update({
                "scheme":"BM CSD", "net_coll":net_coll,
                "coll_target":coll_target,"ach_pct":round(ach_pct,2),
                "payout_eligible":"Yes" if eligible else "No",
                "base_inc":incentive,"total_inc":total,
                "paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":0,
            })

        else:  # L4+ CH-CSD
            net_coll = data.get("net_coll",0)
            coll_target = emp.get("Coll_Target",0)
            ach_pct = (net_coll/coll_target*100) if coll_target>0 else 0
            incentive = _bm_milestone(ach_pct, S["ch_csd"])
            total = int(incentive)
            out.update({
                "scheme":"CH CSD","net_coll":net_coll,
                "coll_target":coll_target,"ach_pct":round(ach_pct,2),
                "base_inc":incentive,"total_inc":total,"paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":0,
            })

    # ── TELE ANNUAL KCD ────────────────────────────────────
    elif vert == "KCD":
        spot1_slabs = S["kcd_25cr_1_12"]  if is_25cr else S["kcd_spot_1_12"]
        spot2_slabs = S["kcd_25cr_20_30"] if is_25cr else S["kcd_spot_20_30"]
        rm1_slabs   = S["kcd_rm_1_12"]
        rm2_slabs   = S["kcd_rm_20_30"]
        ss_m = _ss_mult(ss_pct, ss_sent, S["kcd_min_ss_sent"], S["kcd_ss_mult"])

        if desig == "L1":
            tgt_pcdv = S["kcd_targets"].get(vint,1800)
            grid   = _milestone(pcdv_total, tgt_pcdv, S["kcd_milestones"])
            incr   = round(max(0,pcdv_total-tgt_pcdv)*client_a*S.get("csd_incr_rate",0.03)/1000)*1000 if grid>0 else 0
            gross_inc = round((grid+incr)*ss_m,0)

            sp1_inc = _pcdv_spot(pcdv_1_12,  spot1_slabs)
            sp2_inc = _pcdv_spot(pcdv_20_30, spot2_slabs)
            sp1_gross = round(sp1_inc * ss_m + im_count*1000,0)   # spot 1-12
            sp2_gross = round(sp2_inc * ss_m + im_pro_count*1000,0) # spot 20-30 (+28-30 IM star pro)
            total = int(gross_inc) + int(sp1_gross) + int(sp2_gross)
            out.update({
                "scheme":f"TA KCD Exec {vint}","target_pcdv":tgt_pcdv,
                "incentive_grid":grid,"incr_amt":int(incr),
                "base_inc":int(grid+incr),"ss_mult":ss_m,"gross_inc":int(gross_inc),
                "spot1_inc":sp1_inc,"spot1_gross":int(sp1_gross),
                "spot2_inc":sp2_inc,"spot2_gross":int(sp2_gross),
                "total_inc":total,"paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":int(sp2_gross),
            })

        elif desig == "L2":
            tgt_pcdv = S["kcd_targets"].get(vint,1800)
            grid     = _milestone(pcdv_total,tgt_pcdv,S["kcd_milestones"])
            gross_inc= round(grid*ss_m,0)
            payout_elig = gross_inc > 0
            booster = 0  # configurable in future
            final_inc = int(gross_inc + booster)
            sp1_inc = _pcdv_spot(pcdv_1_12,  rm1_slabs)
            sp2_inc = _pcdv_spot(pcdv_20_30, rm2_slabs)
            sp1_gross = round(sp1_inc*ss_m + im_count*0.5*1000,0)   # team im count / team
            sp2_gross = round(sp2_inc*ss_m + im_pro_count*1000,0)
            im_ss_spot= im_pro_count * 1000  # 28-30 spot
            total = final_inc + int(sp1_gross) + int(sp2_gross) + im_ss_spot
            out.update({
                "scheme":f"TA KCD RM {vint}","target_pcdv":tgt_pcdv,
                "incentive_grid":grid,"payout_eligible":"Yes" if payout_elig else "No",
                "ss_mult":ss_m,"base_inc":int(gross_inc),"booster":booster,
                "final_inc":final_inc,
                "spot1_inc":sp1_inc,"spot1_gross":int(sp1_gross),
                "spot2_inc":sp2_inc,"spot2_gross":int(sp2_gross),
                "im_ss_spot":im_ss_spot,
                "total_inc":total,"paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":int(sp2_gross),
            })

        elif desig == "L3":  # BM-KCD
            net_coll = data.get("net_coll",0)
            coll_target = emp.get("Coll_Target",0)
            ach_pct = (net_coll/coll_target*100) if coll_target>0 else 0
            incentive = _bm_milestone(ach_pct, S["bm_kcd"])
            total = int(incentive)
            out.update({
                "scheme":"BM KCD","net_coll":net_coll,
                "coll_target":coll_target,"ach_pct":round(ach_pct,2),
                "base_inc":incentive,"total_inc":total,
                "paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":0,
            })

        else:  # CH-KCD
            net_coll = data.get("net_coll",0)
            coll_target = emp.get("Coll_Target",0)
            ach_pct = (net_coll/coll_target*100) if coll_target>0 else 0
            incentive = _bm_milestone(ach_pct, S["ch_kcd"])
            total = int(incentive)
            out.update({
                "scheme":"CH KCD","net_coll":net_coll,
                "ach_pct":round(ach_pct,2),"base_inc":incentive,
                "total_inc":total,"paid_inc":0,"bal_inc":total,
                "sp2_6_gross":0,"sp7_12_gross":0,"sp20_30_gross":0,
            })

    return out


def calc_big_ticket(rec, eid_str, desig, vert, slabs, is_l2=False,
                    _rec_cols=None, _grp_l1=None, _grp_mgr=None):
    """Big ticket incentive. Fast path: supply pre-built index dicts."""
    empty = {"3L+":0,"2L+":0,"1L+":0,"10L+":0,"8L+":0,"5L+":0}

    if _rec_cols is not None:
        ec  = _rec_cols["ec"]
        mgc = _rec_cols["mgc"]
        upc = _rec_cols["upc"]
    else:
        ec  = find_col(rec,["Sales Exec ID","EMP ID"])
        mgc = find_col(rec,["Old Sales HOD-3 ID","Manager Id"])
        upc = find_col(rec,["Unique","Upsell"])

    if not ec: return 0, empty
    eid_str = str(eid_str).strip()

    if _grp_l1 is not None:
        r = (_grp_mgr.get(eid_str, pd.DataFrame()) if is_l2 and _grp_mgr
             else _grp_l1.get(eid_str, pd.DataFrame())).copy()
    else:
        if is_l2 and mgc:
            mask = rec[mgc].astype(str).str.split(".").str[0].str.strip()==eid_str
        else:
            mask = rec[ec].astype(str).str.split(".").str[0].str.strip()==eid_str
        r = rec[mask].copy()

    if len(r) == 0: return 0, empty

    if upc and upc in r.columns:
        im_mask = r[upc].fillna("").astype(str).str.upper().apply(
            lambda x: any(k in x for k in IM_STAR_LEADER_KW))
        r = r[im_mask]
    if len(r) == 0: return 0, empty

    dvc = find_col(r, ["Deal Val (WT)","Deal Value","Deal Val","WT AMT","WT_AMT"])
    if not dvc: return 0, empty

    try:
        deal_vals_lakh = pd.to_numeric(r[dvc], errors="coerce").fillna(0) / 100000
    except (KeyError, TypeError):
        return 0, empty

    counts = dict(empty); total_bt = 0
    for dv in deal_vals_lakh:
        for s in slabs:
            if dv >= s.get("Min_Lakh",0):
                size_key = s.get("Deal_Size","")
                counts[size_key] = counts.get(size_key,0) + 1
                total_bt += s.get("Per_Deal",0)
                break
    return total_bt, counts


# ──────────────────────────────────────────────────────────
# MILESTONE TARGET FILE LOADER  (OPTIMISED: iterrows → to_dict)
# ──────────────────────────────────────────────────────────
def load_ta_targets(f):
    empty = {"l1_cmr":{}, "l2_cmr":{}, "l3_coll":{}, "l4_coll":{}}
    if f is None: return empty
    try:
        xl = pd.ExcelFile(f)
        norms = {s.strip().upper(): s for s in xl.sheet_names}

        def _load_eid_tgt(sh_key_list, id_candidates, tgt_candidates, pct_col=True):
            result = {}
            sh = next((norms.get(k) for k in sh_key_list if norms.get(k)), None)
            if not sh: return result
            df = pd.read_excel(f, sheet_name=sh)
            df.columns = [str(c).strip() for c in df.columns]
            iil_c = find_col(df, id_candidates)
            tgt_c = find_col(df, tgt_candidates)
            if not iil_c or not tgt_c: return result
            for row in df.to_dict("records"):
                eid = str(row.get(iil_c,"")).strip().split(".")[0]
                if not eid or eid.lower() in ("nan","none",""): continue
                val = _sf(row.get(tgt_c,0))
                result[eid] = round(val*100 if (pct_col and val<=1.0) else val, 4)
            return result

        def _load_name_tgt(sh_key_list, name_candidates, tgt_candidates):
            result = {}
            sh = next((norms.get(k) for k in sh_key_list if norms.get(k)), None)
            if not sh: return result
            df = pd.read_excel(f, sheet_name=sh)
            df.columns = [str(c).strip() for c in df.columns]
            name_c = find_col(df, name_candidates)
            tgt_c  = find_col(df, tgt_candidates)
            if not name_c or not tgt_c: return result
            for row in df.to_dict("records"):
                nm = str(row.get(name_c,"")).strip()
                if not nm or nm.lower() in ("nan","none",""): continue
                val = _sf(row.get(tgt_c,0))
                rs = val * 1e7 if val < 10000 else val
                result[nm.lower()] = rs
            return result

        l1_cmr = _load_eid_tgt(
            ["L1 RENEWAL","L1RENEWAL","L1"],
            ["IIL","Employee ID","Emp ID","EmpID"],
            ["TGT CMR 100%","CMR Target","Target CMR","TGT CMR","CMR%","Target"],
        )
        l2_cmr = _load_eid_tgt(
            ["L2 TARGET","L2TARGET","L2"],
            ["IIL","Employee ID","Emp ID"],
            ["% TGT","TGT","Target","CMR Target","CMR%"],
        )
        l3_coll = _load_name_tgt(
            ["L3"],
            ["Employee Name","Name","L3 Name","L3Name"],
            ["Target","Collection Target","Coll Target"],
        )
        l4_coll = _load_name_tgt(
            ["L4"],
            ["L4 Name","Name","Employee Name"],
            ["Target","Collection Target","Coll Target"],
        )
        return {"l1_cmr":l1_cmr,"l2_cmr":l2_cmr,"l3_coll":l3_coll,"l4_coll":l4_coll}
    except Exception as e:
        st.warning(f"⚠️ Could not load target file: {e}")
        return empty

# ──────────────────────────────────────────────────────────
# OUTPUT SHEET BUILDER
# ──────────────────────────────────────────────────────────
def write_sheet(w, df, sheet_name, header_fmt, note="", merged_headers=None):
    """Write a DataFrame to sheet with optional merged header row."""
    start = 2 if merged_headers else 1
    df.to_excel(w, sheet_name=sheet_name, index=False, startrow=start)
    ws = w.sheets[sheet_name]
    for ci, col in enumerate(df.columns):
        ws.write(start, ci, col, header_fmt)
        ws.set_column(ci, ci, max(14, len(str(col))+2))
    if merged_headers:
        for (merge_start, merge_end, label) in merged_headers:
            ws.merge_range(0, merge_start, 0, merge_end, label, header_fmt)
    if note:
        ws.write(0 if not merged_headers else 1, 0, note, None)
    ws.freeze_panes(start+1, 0)


def build_excel_output(results_dict, sel_month):
    """Build final Excel with all sheets matching sirs file structure."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        wb  = w.book
        hdr = wb.add_format({"bold":True,"bg_color":"#1F4E79","font_color":"#FFFFFF","border":1,"font_size":9})
        grn = wb.add_format({"bold":True,"bg_color":"#375623","font_color":"#FFFFFF","border":1,"font_size":9})
        org = wb.add_format({"bold":True,"bg_color":"#843C0C","font_color":"#FFFFFF","border":1,"font_size":9})
        pur = wb.add_format({"bold":True,"bg_color":"#7030A0","font_color":"#FFFFFF","border":1,"font_size":9})
        gry = wb.add_format({"bold":True,"bg_color":"#595959","font_color":"#FFFFFF","border":1,"font_size":9})

        hierarchy_l1  = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name","L4 ID","L4 Name","L5 ID","L5 Name","L6 ID","L6 Name"]
        hierarchy_bm  = ["Employee ID","Employee Name","L3 ID","L3 Name","L4 ID","L4 Name","L5 ID","L5 Name","L6 ID","L6 Name","HC","L2"]
        hierarchy_ch  = ["Employee ID","Employee Name","L5 ID","L5 Name","L6 ID","L6 Name"]

        def _dfcols(rows, cols):
            d = pd.DataFrame(rows)
            out = {}
            for c in cols:
                out[c] = d[c].values if c in d.columns else [""]*len(d)
            return pd.DataFrame(out)

        def _getv(r, *keys):
            for k in keys:
                if k in r and r[k] not in (None,""): return r[k]
            return ""

        # ── Nursery ────────────────────────────────────────
        nursery_rows = results_dict.get("nursery",[])
        if nursery_rows:
            cols_n = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                      "L4 ID","L4 Name","L5 ID","L5 Name","L6  ID","L6 Name",
                      "Location","Client-A","Client-C",
                      "MDC","Star","Leader","WS-M","WS-A","IVE",
                      "MDC.1","Star.1","Leader.1","WS-M.1","WS-A.1","IVE.1",
                      "Email Id","Joining Date",
                      "IIL Vertical Name",
                      "CSD to KCD\nMovement/New Joining\n<=90D",
                      "60D/90D","Productvity","Eligible",
                      "Sent","Recd","Ren %",
                      "Renewal\nMultiplier","Incentive","Gross Incentive",
                      "Paid\nIncentive","Balance\nIncentive"]
            rows_n = []
            for r in nursery_rows:
                rows_n.append({
                    "Employee ID":r.get("eid",""),"Employee Name":r.get("name",""),
                    "L2 ID":r.get("L2 ID",""),"L2 Name":r.get("L2 Name",""),
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Location":r.get("Location",""),"Client-A":r.get("Client-A",0),
                    "Client-C":r.get("Client-C",0),
                    "MDC":r.get("MDC",0),"Star":r.get("Star",0),"Leader":r.get("Leader",0),
                    "WS-M":r.get("WS-M",0),"WS-A":r.get("WS-A",0),"IVE":r.get("IVE",0),
                    "MDC.1":r.get("MDC.1",0),"Star.1":r.get("Star.1",0),"Leader.1":r.get("Leader.1",0),
                    "WS-M.1":r.get("WS-M.1",0),"WS-A.1":r.get("WS-A.1",0),"IVE.1":r.get("IVE.1",0),
                    "Email Id":r.get("Email Id",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual "+r.get("Vertical","CSD"),
                    "CSD to KCD\nMovement/New Joining\n<=90D":"L1",
                    "60D/90D":r.get("vintage_label","60-90"),
                    "Productvity":r.get("productivity",0),
                    "Eligible":r.get("eligible","No"),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Renewal\nMultiplier":r.get("renewal_mult",0),
                    "Incentive":r.get("base_inc",0),
                    "Gross Incentive":r.get("gross_inc",0),
                    "Paid\nIncentive":0,"Balance\nIncentive":r.get("gross_inc",0),
                })
            df_n = pd.DataFrame(rows_n).reindex(columns=cols_n, fill_value="")

            df_n.to_excel(w, sheet_name="Nursery Scheme", index=False, startrow=1)
            ws = w.sheets["Nursery Scheme"]
            for ci,col in enumerate(cols_n): ws.write(1,ci,col,pur)
            ws.set_column(0,len(cols_n)-1,16)
            ws.freeze_panes(2,0)

        # ── Exec-CSD ───────────────────────────────────────
        csd_l1 = results_dict.get("exec_csd",[])
        if csd_l1:
            cols_e = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                      "L4 ID","L4 Name","L5 ID","L5 Name","L6 ID","L6 Name",
                      "Joining Date/Movement Date","IIL Vertical Name",
                      "Aeging","Vintage","Client-A","Client-C",
                      "Deal Value","PCDV","Target","Incremental\nPCDV\nAmt.",
                      "Sent","Recd","Ren %","Multiplier","Renewal\nTarget",
                      "Sent.1","Recd.1","Ren %.1",
                      "Incentive Grid","Incentive","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive",
                      "Transaction","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive",  # Spot 2-6
                      "Transaction","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive",  # Spot 7-12
                      "Transaction","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive",  # Spot 20-30
                      ]
            # Use unique column names for the repeated spot cols
            cols_out = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                        "L4 ID","L4 Name","L5 ID","L5 Name","L6  ID","L6 Name",
                        "Joining Date/Movement Date","IIL Vertical Name","Aeging","Vintage",
                        "Client-A","Client-C","Deal Value","PCDV","Target","Incremental\nPCDV\nAmt.",
                        "Sent","Recd","Ren %","Multiplier","Renewal\nTarget",
                        "Sent.1","Recd.1","Ren %.1",
                        "Incentive Grid","Incentive","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive",
                        "Transaction","Gross\nIncentive.1","Paid\nIncentive.1","Balance\nIncentive.1",
                        "Transaction.1","Gross\nIncentive.2","Paid\nIncentive.2","Balance\nIncentive.2",
                        "Transaction.2","Gross\nIncentive.3","Paid\nIncentive.3","Balance\nIncentive.3"]
            rows_e = []
            for r in csd_l1:
                rows_e.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L2 ID":r.get("L2 ID",""),"L2 Name":r.get("L2 Name",""),
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Joining Date/Movement Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual CSD",
                    "Aeging":r.get("Ageing",0),"Vintage":r.get("Vintage",""),
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Deal Value":round(r.get("deal_val",0),2),"PCDV":round(r.get("pcdv",0),2),
                    "Target":r.get("target_pcdv",0),"Incremental\nPCDV\nAmt.":r.get("incr_amt",0),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Multiplier":r.get("cmr_mult",0),"Renewal\nTarget":(__import__("math").ceil(r.get("cmr_sent",0) * r.get("cmr_target_pct",r.get("csd_cmr_tgt",40))/100) / max(r.get("cmr_sent",0),1) if r.get("cmr_sent",0)>0 else r.get("cmr_target_pct",r.get("csd_cmr_tgt",40))/100),
                    "Sent.1":r.get("cmr1_sent",0),"Recd.1":r.get("cmr1_recd",0),"Ren %.1":round(r.get("cmr1_pct",0)/100,4),
                    "Incentive Grid":r.get("incentive_grid",0),"Incentive":r.get("base_inc",0),
                    "Gross\nIncentive":r.get("gross_inc",0),"Paid\nIncentive":0,
                    "Balance\nIncentive":r.get("gross_inc",0),
                    "Transaction":r.get("sp2_6_txn",0),"Gross\nIncentive.1":r.get("sp2_6_gross",0),"Paid\nIncentive.1":0,"Balance\nIncentive.1":r.get("sp2_6_gross",0),
                    "Transaction.1":r.get("sp7_12_txn",0),"Gross\nIncentive.2":r.get("sp7_12_gross",0),"Paid\nIncentive.2":0,"Balance\nIncentive.2":r.get("sp7_12_gross",0),
                    "Transaction.2":r.get("sp20_30_txn",0),"Gross\nIncentive.3":r.get("sp20_30_gross",0),"Paid\nIncentive.3":0,"Balance\nIncentive.3":r.get("sp20_30_gross",0),
                })
            df_e = pd.DataFrame(rows_e).reindex(columns=cols_out, fill_value="")
            df_e.to_excel(w, sheet_name="Exec-CSD", index=False, startrow=2)
            ws = w.sheets["Exec-CSD"]
            # Row 0: merged group headers
            ws.merge_range(0,35,0,38,"Spot 2nd to 6th",hdr)
            ws.merge_range(0,39,0,42,"Spot 7th to 12th",hdr)
            ws.merge_range(0,43,0,46,"Spot 20th to 30th",hdr)
            for ci,col in enumerate(cols_out): ws.write(1,ci,col,grn)
            ws.set_column(0,len(cols_out)-1,14); ws.freeze_panes(3,0)

        # ── Rel'n Mgr-CSD ──────────────────────────────────
        csd_l2 = results_dict.get("rm_csd",[])
        if csd_l2:
            cols_rm = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                       "L4 ID","L4 Name","L5 ID","L5 Name","L6  ID","L6 Name",
                       "Joining Date","IIL Vertical Name","Group","<90\nVintage\nExec","HC",
                       "Client-A","Client-C","Deal Value","PCDV",
                       "Sent","Recd","Ren %","Renewal\nTarget",
                       "Sent.1","Recd.1","Ren %.1",
                       "Incremental\nPCDV\nAmt.","Incentive\nGrid","Incentive","Gross Incentive","Paid\nIncentive","Balance\nIncentive",
                       "Transaction","Productvity","Gross\nIncentive.1","Paid\nIncentive.1","Balance\nIncentive.1",
                       "Transaction.1","Productvity.1","Gross\nIncentive.2","Paid\nIncentive.2","Balance\nIncentive.2",
                       "Transaction.2","Productvity.2","Gross\nIncentive.3","Paid\nIncentive.3","Balance\nIncentive.3"]
            rows_rm = []
            for r in csd_l2:
                rows_rm.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L2 ID":r.get("L2 ID",""),"L2 Name":r.get("L2 Name",""),
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual CSD","Group":"",
                    "<90\nVintage\nExec":r.get("Vintage",""),"HC":r.get("HC",0),
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Deal Value":round(r.get("deal_val",0),2),"PCDV":round(r.get("pcdv",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Renewal\nTarget":(__import__("math").ceil(r.get("cmr_sent",0) * r.get("cmr_target_pct",r.get("csd_cmr_tgt",40))/100) / max(r.get("cmr_sent",0),1) if r.get("cmr_sent",0)>0 else r.get("cmr_target_pct",r.get("csd_cmr_tgt",40))/100),
                    "Sent.1":r.get("cmr1_sent",0),"Recd.1":r.get("cmr1_recd",0),"Ren %.1":round(r.get("cmr1_pct",0)/100,4),
                    "Incremental\nPCDV\nAmt.":r.get("incr_amt",0),"Incentive\nGrid":r.get("incentive_grid",0),
                    "Incentive":r.get("base_inc",0),"Gross Incentive":r.get("gross_inc",0),
                    "Paid\nIncentive":0,"Balance\nIncentive":r.get("gross_inc",0),
                    "Transaction":r.get("sp2_6_txn",0),"Productvity":r.get("sp2_6_prod",0),
                    "Gross\nIncentive.1":r.get("sp2_6_gross",0),"Paid\nIncentive.1":0,"Balance\nIncentive.1":r.get("sp2_6_gross",0),
                    "Transaction.1":r.get("sp7_12_txn",0),"Productvity.1":r.get("sp7_12_prod",0),
                    "Gross\nIncentive.2":r.get("sp7_12_gross",0),"Paid\nIncentive.2":0,"Balance\nIncentive.2":r.get("sp7_12_gross",0),
                    "Transaction.2":r.get("sp20_30_txn",0),"Productvity.2":r.get("sp20_30_prod",0),
                    "Gross\nIncentive.3":r.get("sp20_30_gross",0),"Paid\nIncentive.3":0,"Balance\nIncentive.3":r.get("sp20_30_gross",0),
                })
            df_rm = pd.DataFrame(rows_rm).reindex(columns=cols_rm, fill_value="")
            df_rm.to_excel(w, sheet_name="Rel'n Mgr-CSD", index=False, startrow=2)
            ws = w.sheets["Rel'n Mgr-CSD"]
            ws.merge_range(0,34,0,38,"Spot 2nd to 6th",hdr)
            ws.merge_range(0,39,0,43,"Spot 7th to 12th",hdr)
            ws.merge_range(0,44,0,48,"Spot 20th to 30th",hdr)
            for ci,col in enumerate(cols_rm): ws.write(1,ci,col,grn)
            ws.set_column(0,len(cols_rm)-1,14); ws.freeze_panes(3,0)

        # ── BM-CSD ─────────────────────────────────────────
        bm_csd_rows = results_dict.get("bm_csd",[])
        if bm_csd_rows:
            cols_bm = ["Employee ID","Employee Name","L3 ID","L3 Name","L4 ID","L4 Name",
                       "L5 ID","L5 Name","L6  ID","L6 Name","HC","L2",
                       "Joining Date","IIL Vertical Name","Location",
                       "Client-A","Client-C","Deal Value","PCDV","Collection","Refund","Net Collection",
                       "Target","Ach\n%","CMR\nSent","CMR\nReceived","Ren %",
                       "Payout\nEligibile","Incentive","Total Incentive","Gross Incentive",
                       "Paid\nIncentive","Balance\nIncentive"]
            rows_bm = []
            for r in bm_csd_rows:
                rows_bm.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "HC":r.get("HC",0),"L2":r.get("L2_Count",0),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual CSD","Location":r.get("Location",""),
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Deal Value":round(r.get("deal_val",0),2),"PCDV":round(r.get("pcdv",0),2),
                    "Collection":round(r.get("gross_coll",0),2),"Refund":round(r.get("refund",0),2),
                    "Net Collection":round(r.get("net_coll",0),2),
                    "Target":r.get("coll_target",0),"Ach\n%":round(r.get("ach_pct",0)/100,4),
                    "CMR\nSent":r.get("cmr_sent",0),"CMR\nReceived":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Payout\nEligibile":r.get("payout_eligible","No"),
                    "Incentive":r.get("base_inc",0),"Total Incentive":r.get("total_inc",0),
                    "Gross Incentive":r.get("total_inc",0),
                    "Paid\nIncentive":0,"Balance\nIncentive":r.get("total_inc",0),
                })
            df_bm = pd.DataFrame(rows_bm).reindex(columns=cols_bm, fill_value="")
            df_bm.to_excel(w, sheet_name="BM-CSD", index=False, startrow=1)
            ws = w.sheets["BM-CSD"]
            for ci,col in enumerate(cols_bm): ws.write(1,ci,col,grn)
            ws.set_column(0,len(cols_bm)-1,14); ws.freeze_panes(2,0)

        # ── BM-CSD Big Ticket ──────────────────────────────
        bt_bm_csd_rows = results_dict.get("bt_bm_csd",[])
        if bt_bm_csd_rows:
            cols_bt = ["Employee ID","Employee Name","L4 ID","L4 Name","L5 ID","L5 Name",
                       "L6  ID","L6 Name","Location","Joining Date","IIL Vertical Name",
                       "Net Collection","AOP","%",
                       "Sent","Recd","Ren %",
                       "3L+","2L+","1L+","Total","Eligible",
                       "Gross\nIncentive","Paid\nIncentive","Balance\nIncentive"]
            rows_bt = []
            for r in bt_bm_csd_rows:
                cnt = r.get("bt_counts",{})
                total_deals = sum(cnt.get(k,0) for k in ["3L+","2L+","1L+"])
                rows_bt.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Location":r.get("Location",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual CSD",
                    "Net Collection":round(r.get("net_coll",0),2),
                    "AOP":r.get("aop",0),"%":round(r.get("aop_pct",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "3L+":cnt.get("3L+",0),"2L+":cnt.get("2L+",0),"1L+":cnt.get("1L+",0),
                    "Total":total_deals,"Eligible":r.get("bt_eligible","NO"),
                    "Gross\nIncentive":r.get("bt_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("bt_inc",0),
                })
            df_bt = pd.DataFrame(rows_bt).reindex(columns=cols_bt, fill_value="")
            df_bt.to_excel(w, sheet_name="BM-CSD Big Ticket", index=False, startrow=1)
            ws = w.sheets["BM-CSD Big Ticket"]
            for ci,col in enumerate(cols_bt): ws.write(1,ci,col,grn)
            ws.set_column(0,len(cols_bt)-1,14); ws.freeze_panes(2,0)

        # ── CH-CSD Big Ticket ──────────────────────────────
        bt_ch_csd_rows = results_dict.get("bt_ch_csd",[])
        if bt_ch_csd_rows:
            cols_btch = ["Employee ID","Employee Name","L5 ID","L5 Name","L6  ID","L6 Name",
                         "Location","Joining Date","IIL Vertical Name",
                         "Client-A","Client-C","Target\nOf 1L+ Deal",
                         "Net Collection","AOP","AOP%",
                         "Sent","Recd","Ren %",
                         "3L+","2L+","1L+","Total","Eligible",
                         "Gross\nIncentive","Paid\nIncentive","Balance\nIncentive"]
            rows_btch = []
            for r in bt_ch_csd_rows:
                cnt = r.get("bt_counts",{})
                total_deals = sum(cnt.get(k,0) for k in ["3L+","2L+","1L+"])
                rows_btch.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Location":r.get("Location",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual CSD",
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Target\nOf 1L+ Deal":r.get("deal_target",0),
                    "Net Collection":round(r.get("net_coll",0),2),
                    "AOP":r.get("aop",0),"AOP%":round(r.get("aop_pct",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "3L+":cnt.get("3L+",0),"2L+":cnt.get("2L+",0),"1L+":cnt.get("1L+",0),
                    "Total":total_deals,"Eligible":r.get("bt_eligible","No"),
                    "Gross\nIncentive":r.get("bt_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("bt_inc",0),
                })
            df_btch = pd.DataFrame(rows_btch).reindex(columns=cols_btch, fill_value="")
            df_btch.to_excel(w, sheet_name="CH-CSD Big Ticket", index=False, startrow=1)
            ws = w.sheets["CH-CSD Big Ticket"]
            for ci,col in enumerate(cols_btch): ws.write(1,ci,col,grn)
            ws.set_column(0,len(cols_btch)-1,14); ws.freeze_panes(2,0)

        # ── Exec-KCD ───────────────────────────────────────
        kcd_l1 = results_dict.get("exec_kcd",[])
        if kcd_l1:
            cols_kl1 = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                        "L4 ID","L4 Name","L5 ID","L5 Name","L6  ID","L6 Name",
                        "Joining Date/Movement Date","IIL Vertical Name","Group","Aeging","Vintage",
                        "Target","Client-A","Client-C","Deal Value","PCDV",
                        "Sent","Recd","Ren %","Sent.1","Recd.1","Ren %.1",
                        "SS+\nMultiplier","Target\nPCDV%","Incentive","Mulitipler\nPayout","Final\nIncentive",
                        "Gross Incentive","Paid\nIncentive","Balance\nIncentive",
                        "Deal Value.1","PCDV.1","Incentive.1","IM Star/Leader\nNew Sale","Gross Incentive.1","Paid\nIncentive.1","Balance\nIncentive.1",
                        "Deal Value.2","PCDV.2","Incentive.2","IM Star/Leader\nNew Sale.1","Gross Incentive.2","Paid\nIncentive.2","Balance\nIncentive.2"]
            rows_kl1=[]
            for r in kcd_l1:
                tgt = r.get("target_pcdv",0)
                pcdv = r.get("pcdv",0)
                tgt_pct = round(pcdv/tgt*100,2) if tgt>0 else 0
                rows_kl1.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L2 ID":r.get("L2 ID",""),"L2 Name":r.get("L2 Name",""),
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Joining Date/Movement Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual KCD","Group":r.get("Group",""),
                    "Aeging":r.get("Ageing",0),"Vintage":r.get("Vintage",""),
                    "Target":tgt,"Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Deal Value":round(r.get("deal_val",0),2),"PCDV":round(pcdv,2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Sent.1":r.get("ss_sent",0),"Recd.1":r.get("ss_recd",0),
                    "Ren %.1":round(r.get("ss_pct",0)/100,4),
                    "SS+\nMultiplier":r.get("ss_mult",1),"Target\nPCDV%":tgt_pct,
                    "Incentive":r.get("incentive_grid",0),
                    "Mulitipler\nPayout":round(r.get("incentive_grid",0)*r.get("ss_mult",1),0),
                    "Final\nIncentive":r.get("gross_inc",0),
                    "Gross Incentive":r.get("gross_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("gross_inc",0),
                    "Deal Value.1":round(r.get("fnt_dv",{}).get("1_12",0),2),
                    "PCDV.1":round(r.get("pcdv_1_12",0),2),
                    "Incentive.1":r.get("spot1_inc",0),"IM Star/Leader\nNew Sale":r.get("im_count",0),
                    "Gross Incentive.1":r.get("spot1_gross",0),"Paid\nIncentive.1":0,"Balance\nIncentive.1":r.get("spot1_gross",0),
                    "Deal Value.2":round(r.get("fnt_dv",{}).get("20_30",0),2),
                    "PCDV.2":round(r.get("pcdv_20_30",0),2),
                    "Incentive.2":r.get("spot2_inc",0),"IM Star/Leader\nNew Sale.1":r.get("im_pro_count",0),
                    "Gross Incentive.2":r.get("spot2_gross",0),"Paid\nIncentive.2":0,"Balance\nIncentive.2":r.get("spot2_gross",0),
                })
            df_kl1 = pd.DataFrame(rows_kl1).reindex(columns=cols_kl1, fill_value="")
            df_kl1.to_excel(w, sheet_name="Exec-KCD", index=False, startrow=2)
            ws = w.sheets["Exec-KCD"]
            ws.merge_range(0,36,0,42,"Spot 1st to 12th",org)
            ws.merge_range(0,43,0,49,"Spot 20th to 30th",org)
            for ci,col in enumerate(cols_kl1): ws.write(1,ci,col,org)
            ws.set_column(0,len(cols_kl1)-1,14); ws.freeze_panes(3,0)

        # ── Reln Mgr-KCD ───────────────────────────────────
        kcd_l2 = results_dict.get("rm_kcd",[])
        if kcd_l2:
            cols_kl2 = ["Employee ID","Employee Name","L2 ID","L2 Name","L3 ID","L3 Name",
                        "L4 ID","L4 Name","L5 ID","L5 Name","L6  ID","L6 Name",
                        "Joining Date","IIL Vertical Name","Group","Aeging","HC",
                        "Client-A","Client-C","Deal Value","PCDV",
                        "Sent","Recd","Ren %","Sent.1","Recd.1","Ren %.1",
                        "SS+\nMultiplier","Payout\nEligibile","Incentive","Booster\nPayout","Final Incentive",
                        "Gross\nIncentive ","Paid\nIncentive","Balance\nIncentive",
                        "Deal Value","PCDV","Incentive.1","IM Star/Leader\nNew Sale","Gross Incentive","Paid\nIncentive.1","Balance\nIncentive.1",
                        "Deal Value.1","PCDV.1","Incentive.2","IM Star/Leader\nNew Sale.1","Gross Incentive.1","Paid\nIncentive.2","Balance\nIncentive.2",
                        "IM Star Pro/Leader Pro+\nNew Sale","Gross Incentive.2","Paid\nIncentive.3","Balance\nIncentive.3"]
            rows_kl2=[]
            for r in kcd_l2:
                tgt = r.get("target_pcdv",0)
                rows_kl2.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L2 ID":r.get("L2 ID",""),"L2 Name":r.get("L2 Name",""),
                    "L3 ID":r.get("L3 ID",""),"L3 Name":r.get("L3 Name",""),
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual KCD","Group":r.get("Group",""),
                    "Aeging":r.get("Ageing",0),"HC":r.get("HC",0),
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Deal Value":round(r.get("deal_val",0),2),"PCDV":round(r.get("pcdv",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Sent.1":r.get("ss_sent",0),"Recd.1":r.get("ss_recd",0),
                    "Ren %.1":round(r.get("ss_pct",0)/100,4),
                    "SS+\nMultiplier":r.get("ss_mult",1),
                    "Payout\nEligibile":r.get("payout_eligible","No"),
                    "Incentive":r.get("incentive_grid",0),
                    "Booster\nPayout":r.get("booster",0),"Final Incentive":r.get("final_inc",0),
                    "Gross\nIncentive ":r.get("final_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("final_inc",0),
                    "Deal Value":round(r.get("fnt_dv",{}).get("1_12",0),2),
                    "PCDV":round(r.get("pcdv_1_12",0),2),
                    "Incentive.1":r.get("spot1_inc",0),"IM Star/Leader\nNew Sale":r.get("im_count",0),
                    "Gross Incentive":r.get("spot1_gross",0),"Paid\nIncentive.1":0,"Balance\nIncentive.1":r.get("spot1_gross",0),
                    "Deal Value.1":round(r.get("fnt_dv",{}).get("20_30",0),2),
                    "PCDV.1":round(r.get("pcdv_20_30",0),2),
                    "Incentive.2":r.get("spot2_inc",0),"IM Star/Leader\nNew Sale.1":r.get("im_count",0),
                    "Gross Incentive.1":r.get("spot2_gross",0),"Paid\nIncentive.2":0,"Balance\nIncentive.2":r.get("spot2_gross",0),
                    "IM Star Pro/Leader Pro+\nNew Sale":r.get("im_pro_count",0),
                    "Gross Incentive.2":r.get("im_ss_spot",0),"Paid\nIncentive.3":0,"Balance\nIncentive.3":r.get("im_ss_spot",0),
                })
            df_kl2 = pd.DataFrame(rows_kl2).reindex(columns=cols_kl2, fill_value="")
            df_kl2.to_excel(w, sheet_name="Reln Mgr-KCD", index=False, startrow=2)
            ws = w.sheets["Reln Mgr-KCD"]
            ws.merge_range(0,35,0,41,"Spot 1st to 12th",org)
            ws.merge_range(0,42,0,48,"Spot 20th to 30th",org)
            ws.merge_range(0,49,0,52,"28th to 30th",org)
            for ci,col in enumerate(cols_kl2): ws.write(1,ci,col,org)
            ws.set_column(0,len(cols_kl2)-1,14); ws.freeze_panes(3,0)

        # ── BM-KCD ─────────────────────────────────────────
        bm_kcd_rows = results_dict.get("bm_kcd",[])
        if bm_kcd_rows:
            cols_bk = ["Employee ID","Employee Name","L4 ID","L4 Name","L5 ID","L5 Name",
                       "L6  ID","L6 Name","Joining Date","IIL Vertical Name","Group",
                       "Aeging","HC","Client-A","Client-C",
                       "Collection","Refund","Net Collection","Deal Value","Target","Ach\n%",
                       "Incentive","Sent","Recd","Ren %","Sent.1","Recd.1","Ren %.1",
                       "Total\nIncentive","Gross\nIncentive","Paid\nIncentive","Balance\nIncentive"]
            rows_bk=[]
            for r in bm_kcd_rows:
                rows_bk.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual KCD","Group":r.get("Group",""),
                    "Aeging":r.get("Ageing",0),"HC":r.get("HC",0),
                    "Client-A":r.get("Client-A",0),"Client-C":r.get("Client-C",0),
                    "Collection":round(r.get("gross_coll",0),2),"Refund":round(r.get("refund",0),2),
                    "Net Collection":round(r.get("net_coll",0),2),
                    "Deal Value":round(r.get("deal_val",0),2),
                    "Target":r.get("coll_target",0),"Ach\n%":round(r.get("ach_pct",0)/100,4),
                    "Incentive":r.get("base_inc",0),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Sent.1":r.get("ss_sent",0),"Recd.1":r.get("ss_recd",0),
                    "Ren %.1":round(r.get("ss_pct",0)/100,4),
                    "Total\nIncentive":r.get("total_inc",0),
                    "Gross\nIncentive":r.get("total_inc",0),
                    "Paid\nIncentive":0,"Balance\nIncentive":r.get("total_inc",0),
                })
            df_bk = pd.DataFrame(rows_bk).reindex(columns=cols_bk, fill_value="")
            df_bk.to_excel(w, sheet_name="BM-KCD", index=False, startrow=1)
            ws = w.sheets["BM-KCD"]
            for ci,col in enumerate(cols_bk): ws.write(1,ci,col,org)
            ws.set_column(0,len(cols_bk)-1,14); ws.freeze_panes(2,0)

        # ── BM-KCD Big Ticket ──────────────────────────────
        bt_bm_kcd_rows = results_dict.get("bt_bm_kcd",[])
        if bt_bm_kcd_rows:
            cols_btbk=["Employee ID","Employee Name","L4 ID","L4 Name","L5 ID","L5 Name",
                       "L6  ID","L6 Name","Location","Joining Date","IIL Vertical Name",
                       "Net Collection","AOP","%","Sent","Recd","Ren %",
                       "Total","10L+","8L+","5L+","3L+","Eligible",
                       "Gross\nIncentive","Paid\nIncentive","Balance\nIncentive"]
            rows_btbk=[]
            for r in bt_bm_kcd_rows:
                cnt=r.get("bt_counts",{})
                rows_btbk.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L4 ID":r.get("L4 ID",""),"L4 Name":r.get("L4 Name",""),
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Location":r.get("Location",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual KCD",
                    "Net Collection":round(r.get("net_coll",0),2),
                    "AOP":r.get("aop",0),"%":round(r.get("aop_pct",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Total":sum(cnt.get(k,0) for k in ["10L+","8L+","5L+","3L+"]),
                    "10L+":cnt.get("10L+",0),"8L+":cnt.get("8L+",0),
                    "5L+":cnt.get("5L+",0),"3L+":cnt.get("3L+",0),
                    "Eligible":r.get("bt_eligible","NO"),
                    "Gross\nIncentive":r.get("bt_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("bt_inc",0),
                })
            df_btbk=pd.DataFrame(rows_btbk).reindex(columns=cols_btbk, fill_value="")
            df_btbk.to_excel(w,sheet_name="BM-KCD Big Ticket",index=False,startrow=1)
            ws=w.sheets["BM-KCD Big Ticket"]
            for ci,col in enumerate(cols_btbk): ws.write(1,ci,col,org)
            ws.set_column(0,len(cols_btbk)-1,14); ws.freeze_panes(2,0)

        # ── CH-KCD Big Ticket ──────────────────────────────
        bt_ch_kcd_rows = results_dict.get("bt_ch_kcd",[])
        if bt_ch_kcd_rows:
            cols_btck=["Employee ID","Employee Name","L5 ID","L5 Name","L6  ID","L6 Name",
                       "Location","Joining Date","IIL Vertical Name",
                       "Net Collection","AOP","%","Sent","Recd","Ren %",
                       "Total Deal","10L+","8L+","5L+","3L+","Eligible",
                       "Gross\nIncentive","Paid\nIncentive","Balance\nIncentive"]
            rows_btck=[]
            for r in bt_ch_kcd_rows:
                cnt=r.get("bt_counts",{})
                rows_btck.append({
                    "Employee ID":r["eid"],"Employee Name":r["name"],
                    "L5 ID":r.get("L5 ID",""),"L5 Name":r.get("L5 Name",""),
                    "L6  ID":r.get("L6 ID",""),"L6 Name":r.get("L6 Name",""),
                    "Location":r.get("Location",""),
                    "Joining Date":str(r.get("Joining Date",""))[:10],
                    "IIL Vertical Name":"Tele Annual KCD",
                    "Net Collection":round(r.get("net_coll",0),2),
                    "AOP":r.get("aop",0),"%":round(r.get("aop_pct",0),2),
                    "Sent":r.get("cmr_sent",0),"Recd":r.get("cmr_recd",0),
                    "Ren %":round(r.get("cmr_pct",0)/100,4),
                    "Total Deal":sum(cnt.get(k,0) for k in ["10L+","8L+","5L+","3L+"]),
                    "10L+":cnt.get("10L+",0),"8L+":cnt.get("8L+",0),
                    "5L+":cnt.get("5L+",0),"3L+":cnt.get("3L+",0),
                    "Eligible":r.get("bt_eligible","No"),
                    "Gross\nIncentive":r.get("bt_inc",0),"Paid\nIncentive":0,"Balance\nIncentive":r.get("bt_inc",0),
                })
            df_btck=pd.DataFrame(rows_btck).reindex(columns=cols_btck, fill_value="")
            df_btck.to_excel(w,sheet_name="CH-KCD Big Ticket",index=False,startrow=1)
            ws=w.sheets["CH-KCD Big Ticket"]
            for ci,col in enumerate(cols_btck): ws.write(1,ci,col,org)
            ws.set_column(0,len(cols_btck)-1,14); ws.freeze_panes(2,0)

        # ── Summary ────────────────────────────────────────
        all_rows = []
        for key, lst in results_dict.items():
            if not isinstance(lst, list): continue
            for r in lst:
                if "eid" not in r: continue
                all_rows.append({
                    "Employee ID":r["eid"],"Employee Name":r.get("name",""),
                    "Vertical":r.get("Vertical",""),"Designation":r.get("Designation",""),
                    "Vintage":r.get("Vintage",""),"Scheme":r.get("scheme",""),
                    "Net Collection":r.get("net_coll",0),"Deal Value":r.get("deal_val",0),
                    "PCDV":round(r.get("pcdv",0),1),
                    "CMR%":r.get("cmr_pct",0),"SS+CMR%":r.get("ss_pct",0),
                    "Base Incentive":r.get("base_inc",r.get("gross_inc",0)),
                    "Spot 2-6":r.get("sp2_6_gross",0),
                    "Spot 7-12":r.get("sp7_12_gross",0),
                    "Spot 20-30":r.get("sp20_30_gross",0),
                    "BT Incentive":r.get("bt_inc",0),
                    "Total Incentive":r.get("total_inc",0),
                })
        if all_rows:
            df_sum = pd.DataFrame(all_rows)
            df_sum.to_excel(w, sheet_name="Summary", index=False, startrow=1)
            ws = w.sheets["Summary"]
            for ci,col in enumerate(df_sum.columns): ws.write(1,ci,col,hdr)
            ws.set_column(0,len(df_sum.columns)-1,16); ws.freeze_panes(2,0)

    return buf.getvalue()
# ──────────────────────────────────────────────────────────
# STREAMLIT UI
# ──────────────────────────────────────────────────────────
st.title("📊 Tele Annual Incentive Calculator")
st.caption("TA CSD & KCD | All Levels: L1 Exec · L2 Rel'n Mgr · L3 BM · L4 CH · Nursery | Separate from regular CSD/KCD")

with st.sidebar:
    st.header("📂 Upload Files")
    receipt_f   = st.file_uploader("1. Receipt file",           type=["xlsx","xlsb"])
    refund_f    = st.file_uploader("2. Refund file",            type=["xlsx","xlsb"])
    renewal_f   = st.file_uploader("3. Renewal file",           type=["xlsx","xlsb"])
    struct_f    = st.file_uploader("4. Employee Structure (FSF_TA sheet)", type=["xlsx","xlsb"])
    slab_f      = st.file_uploader("5. TA Slab Config (optional)", type=["xlsx"])
    target_f    = st.file_uploader("6. Milestone Target file (optional)", type=["xlsx","xlsb"],
                                    help="Sheets: L4, L3, L1 Renewal, L2 Target — provides per-employee CMR targets and collection targets")
    st.divider()
    st.header("⚙️ Settings")
    st.caption("Slab targets are configurable via the Slab Config file.")
    calc_btn = st.button("▶ Calculate", type="primary", use_container_width=True)

# Slab config download
st.subheader("Step 0 – Download TA Slab Config")
st.download_button("⬇️ Download TA Slab Config Template",
                   data=make_slab_excel(),
                   file_name="TA_Slab_Config_Apr2026.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Load slab config
cfg_raw = load_ta_slab_config(slab_f)
S = parse_slabs(cfg_raw)
if slab_f:
    st.success(f"✅ TA Slab Config loaded from: {slab_f.name}")

# Load milestone targets
ta_targets = load_ta_targets(target_f if "target_f" in dir() else None)
if "target_f" in dir() and target_f:
    n1 = len(ta_targets["l1_cmr"]); n2 = len(ta_targets["l2_cmr"])
    n3 = len(ta_targets["l3_coll"]); n4 = len(ta_targets["l4_coll"])
    st.success(f"✅ Target file loaded — L1: {n1} CMR targets | L2: {n2} CMR targets | "
               f"L3: {n3} collection targets | L4: {n4} collection targets")
else:
    st.info("📋 No target file uploaded — CMR targets use slab config default (40%), "
            "collection targets will show 0 (BM/CH achievement will be 0%).", icon="ℹ️")
if not slab_f:
    st.info("📋 Using built-in default slabs. Download and upload a slab config to customise.", icon="ℹ️")

st.subheader("Step 1 – Upload Employee Structure")
if not struct_f:
    st.info("Upload the Employee Structure file with a FSF_TA sheet.", icon="📂")
    st.stop()

struct_map = load_ta_structure(struct_f)
if not struct_map:
    st.error("Could not load TA structure. Check the FSF_TA sheet in the file.")
    st.stop()

csd_count = sum(1 for v in struct_map.values() if v["Vertical"]=="CSD")
kcd_count = sum(1 for v in struct_map.values() if v["Vertical"]=="KCD")
st.success(f"✅ Loaded {len(struct_map)} TA employees — CSD: {csd_count}, KCD: {kcd_count}")

with st.expander("Employee Structure Preview"):
    preview = pd.DataFrame([
        {"Emp ID":k,"Name":v["Name"],"Vertical":v["Vertical"],"Designation":v["Designation"],
         "Vintage":v["Vintage"],"Ageing":v["Ageing"],"Client-A":v.get("Client-A",0)}
        for k,v in struct_map.items()
    ])
    st.dataframe(preview, use_container_width=True, hide_index=True)

if not (receipt_f and refund_f and renewal_f):
    st.info("Upload Receipt, Refund, and Renewal files to proceed.", icon="📂")
    st.stop()

# Load files
rec_raw = clean_receipt(_rf(receipt_f))
ref_raw = _rf(refund_f)
rnl_raw = _rf(renewal_f)

# Normalise EMP ID in renewal
ec_rnl = find_col(rnl_raw, ["EMP ID","Emp ID","EmpID","Employee ID"])
if ec_rnl:
    rnl_raw[ec_rnl] = rnl_raw[ec_rnl].apply(
        lambda x: str(int(float(x))) if str(x).replace(".","").isdigit() else str(x))

months = get_months(rec_raw, rnl_raw)
if not months:
    st.warning("No months detected from files. Check Entry Date / Month columns.", icon="⚠️")
    st.stop()

sel_month = st.sidebar.selectbox("Month to calculate", options=months,
                                  index=len(months)-1, key="ta_month")

rec, ref, rnl = filter_month(rec_raw, ref_raw, rnl_raw, sel_month)

# ── OPTIMISED: pass bytes to cached load_ta_structure ─────
struct_map = load_ta_structure(struct_f.getvalue(), struct_f.name)
if not struct_map:
    st.error("Could not load TA structure. Check the FSF_TA sheet in the file.")
    st.stop()

csd_count = sum(1 for v in struct_map.values() if v["Vertical"]=="CSD")
kcd_count = sum(1 for v in struct_map.values() if v["Vertical"]=="KCD")
st.success(f"✅ Loaded {len(struct_map)} TA employees — CSD: {csd_count}, KCD: {kcd_count}")

with st.expander("Employee Structure Preview"):
    preview = pd.DataFrame([
        {"Emp ID":k,"Name":v["Name"],"Vertical":v["Vertical"],"Designation":v["Designation"],
         "Vintage":v["Vintage"],"Ageing":v["Ageing"],"Client-A":v.get("Client-A",0)}
        for k,v in struct_map.items()
    ])
    st.dataframe(preview, use_container_width=True, hide_index=True)

if not (receipt_f and refund_f and renewal_f):
    st.info("Upload Receipt, Refund, and Renewal files to proceed.", icon="📂")
    st.stop()

# Load files
rec_raw = clean_receipt(_rf(receipt_f))
ref_raw = _rf(refund_f)
rnl_raw = _rf(renewal_f)

# Normalise EMP ID in renewal
ec_rnl = find_col(rnl_raw, ["EMP ID","Emp ID","EmpID","Employee ID"])
if ec_rnl:
    rnl_raw[ec_rnl] = rnl_raw[ec_rnl].apply(
        lambda x: str(int(float(x))) if str(x).replace(".","").isdigit() else str(x))

months = get_months(rec_raw, rnl_raw)
if not months:
    st.warning("No months detected from files. Check Entry Date / Month columns.", icon="⚠️")
    st.stop()

sel_month = st.sidebar.selectbox("Month to calculate", options=months,
                                  index=len(months)-1, key="ta_month")

rec, ref, rnl = filter_month(rec_raw, ref_raw, rnl_raw, sel_month)
st.info(f"📅 {sel_month} | Receipt: {len(rec)} rows | Refund: {len(ref)} rows | Renewal: {len(rnl) if rnl is not None else 0} rows")

st.subheader("Step 2 – Calculate")

# Detect L2 name column in renewal (for L2+ CMR lookup)
l2_rnl_col = find_col(rnl, ["L2","L2 Name","L2Name","RM Name"]) if rnl is not None else None


if calc_btn:
    results = {
        "nursery":[],"exec_csd":[],"rm_csd":[],
        "bm_csd":[],"bt_bm_csd":[],"bt_ch_csd":[],
        "exec_kcd":[],"rm_kcd":[],
        "bm_kcd":[],"bt_bm_kcd":[],"bt_ch_kcd":[],
    }

    # ═══════════════════════════════════════════════════════
    # PRE-COMPUTATION  — run ONCE before the employee loop
    # ═══════════════════════════════════════════════════════

    # 1. Previous-month renewal data computed ONCE (was inside the loop!)
    _prev_sel = get_prev_month_str(sel_month, months)
    _rnl_prev = pd.DataFrame()
    if _prev_sel:
        _, _, _rnl_prev = filter_month(rec_raw, ref_raw, rnl_raw, _prev_sel)
        if _rnl_prev is None: _rnl_prev = pd.DataFrame()

    # 2. Receipt column cache + grouped dicts (O(N) once vs O(N*M) per employee)
    _rec_cols, _grp_l1, _grp_mgr, _grp_hod = _build_rec_index(rec)

    # 3. Refund grouped dict
    _ref_rfc, _ref_wac, _grp_ref = _build_ref_index(ref)

    # 4. Renewal grouped by EID and by L2 name (for current month)
    _rnl_ec = find_col(rnl, ["EMP ID","Emp ID","EmpID","Employee ID"]) if rnl is not None else None
    _rnl_sc = find_col(rnl, ["Status","STATUS"]) if rnl is not None else None
    _rnl_pc = find_col(rnl, ["WS/MDC Main","Product","Service"]) if rnl is not None else None
    _rnl_by_eid  = {}; _rnl_by_name = {}
    if rnl is not None and _rnl_ec and len(rnl):
        rnl_c = rnl.copy()
        rnl_c["_eid"] = rnl_c[_rnl_ec].astype(str).str.split(".").str[0].str.strip()
        _rnl_by_eid = dict(tuple(rnl_c.groupby("_eid", sort=False)))
        if l2_rnl_col and l2_rnl_col in rnl_c.columns:
            rnl_c["_l2n"] = rnl_c[l2_rnl_col].astype(str).str.strip()
            _rnl_by_name = dict(tuple(rnl_c.groupby("_l2n", sort=False)))

    # 5. Previous month renewal grouped dicts
    _prev_by_eid  = {}; _prev_by_name = {}
    _prev_sc = None;    _prev_pc = None
    if len(_rnl_prev):
        _prev_ec2 = find_col(_rnl_prev, ["EMP ID","Emp ID","EmpID","Employee ID"])
        _prev_sc  = find_col(_rnl_prev, ["Status","STATUS"])
        _prev_pc  = find_col(_rnl_prev, ["WS/MDC Main","Product","Service"])
        if _prev_ec2:
            prnl = _rnl_prev.copy()
            prnl["_eid"] = prnl[_prev_ec2].astype(str).str.split(".").str[0].str.strip()
            _prev_by_eid = dict(tuple(prnl.groupby("_eid", sort=False)))
            if l2_rnl_col and l2_rnl_col in prnl.columns:
                prnl["_l2n"] = prnl[l2_rnl_col].astype(str).str.strip()
                _prev_by_name = dict(tuple(prnl.groupby("_l2n", sort=False)))

    # ═══════════════════════════════════════════════════════
    # EMPLOYEE LOOP  — now uses pre-built indexes
    # ═══════════════════════════════════════════════════════
    prog = st.progress(0, "Calculating…")
    eids = list(struct_map.keys())

    for i, eid in enumerate(eids):
        emp    = struct_map[eid]
        vert   = emp["Vertical"]
        desig  = emp["Designation"]
        ageing = emp["Ageing"]
        name   = emp["Name"]
        ca     = max(float(emp.get("Client-A_Agg", emp.get("Client-A",1)) or 1), 1)
        is_l2  = desig in ("L2","L3","L4","L5")
        is_25cr= "25" in str(emp.get("Group",""))

        # CMR (current month) — fast lookup via pre-grouped dict
        if is_l2 and l2_rnl_col and name:
            cmr = calc_cmr_by_name(rnl, l2_rnl_col, name,
                                   _rnl_by_name=_rnl_by_name,
                                   _rnl_sc=_rnl_sc, _rnl_pc=_rnl_pc)
            if cmr["sent"] == 0:
                cmr = calc_cmr(rnl, eid, _rnl_by_eid=_rnl_by_eid,
                               _rnl_sc=_rnl_sc, _rnl_pc=_rnl_pc)
        else:
            cmr = calc_cmr(rnl, eid, _rnl_by_eid=_rnl_by_eid,
                           _rnl_sc=_rnl_sc, _rnl_pc=_rnl_pc)

        # CMR+1 — previous month renewal (pre-computed ONCE outside the loop)
        if _prev_sel:
            if is_l2 and l2_rnl_col and name:
                cmr_prev = calc_cmr_by_name(_rnl_prev, l2_rnl_col, name,
                                            _rnl_by_name=_prev_by_name,
                                            _rnl_sc=_prev_sc, _rnl_pc=_prev_pc)
                if cmr_prev["sent"] == 0:
                    cmr_prev = calc_cmr(_rnl_prev, eid, _rnl_by_eid=_prev_by_eid,
                                        _rnl_sc=_prev_sc, _rnl_pc=_prev_pc)
            else:
                cmr_prev = calc_cmr(_rnl_prev, eid, _rnl_by_eid=_prev_by_eid,
                                    _rnl_sc=_prev_sc, _rnl_pc=_prev_pc)
        else:
            cmr_prev = {"sent":0,"recd":0,"pct":0.0,"ss_sent":0,"ss_recd":0,"ss_pct":0.0}

        # Per-employee targets from target file
        if desig == "L1":
            per_emp_cmr_tgt = ta_targets["l1_cmr"].get(eid, S["csd_cmr_tgt"])
        elif desig == "L2":
            per_emp_cmr_tgt = ta_targets["l2_cmr"].get(eid, S["csd_cmr_tgt"])
        else:
            per_emp_cmr_tgt = S["csd_cmr_tgt"]

        emp_own_name = emp.get("Name","").lower()
        if desig == "L3":
            per_emp_coll_tgt = ta_targets["l3_coll"].get(emp_own_name, 0)
        elif desig == "L4":
            per_emp_coll_tgt = ta_targets["l4_coll"].get(emp_own_name, 0)
        else:
            per_emp_coll_tgt = 0

        emp = dict(emp)
        emp["CMR_Target_Pct"] = per_emp_cmr_tgt
        if per_emp_coll_tgt > 0:
            emp["Coll_Target"] = per_emp_coll_tgt

        _age = emp.get("Ageing", 0)
        if _age <= 90:    emp["Vintage"] = "0-90"
        elif _age <= 270: emp["Vintage"] = "90-270"
        else:             emp["Vintage"] = "270+"

        cc = max(float(emp.get("Client-C", ca) or ca), 1)

        # Receipt data — fast lookup via pre-grouped dicts
        data = get_emp_data(rec, ref, eid, desig=desig, emp_name=name, client_a=cc,
                            _rec_cols=_rec_cols, _grp_l1=_grp_l1,
                            _grp_mgr=_grp_mgr, _grp_hod=_grp_hod,
                            _ref_wac=_ref_wac, _grp_ref=_grp_ref)

        inc = calc_employee(emp, data, cmr, S, is_25cr=is_25cr)

        row = {
            "eid":eid, "name":name, "scheme":inc.get("scheme",""),
            "Vertical":vert,"Designation":desig,"Vintage":emp["Vintage"],
            "cmr_target_pct": per_emp_cmr_tgt,
            "Ageing":ageing,"Joining Date":emp.get("Joining Date",""),
            "cmr1_sent":cmr_prev["sent"],"cmr1_recd":cmr_prev["recd"],"cmr1_pct":cmr_prev["pct"],
            "Client-A":emp.get("Client-A",0),"Client-C":emp.get("Client-C",0),
            "Client-A_Agg":emp.get("Client-A_Agg",emp.get("Client-A",0)),
            "HC":emp.get("HC",0),"Group":emp.get("Group",""),
            "Location":emp.get("Location","Tele Annual"),
            **{k:v for k,v in emp.items() if "ID" in k or "Name" in k},
            **inc,
            "fnt_dv":data.get("fnt_dv",{}),
            "pcdv_1_12":data.get("pcdv_1_12",0),"pcdv_20_30":data.get("pcdv_20_30",0),
            "im_count":data.get("im_count",0),"im_pro_count":data.get("im_pro_count",0),
            "gross_coll":data.get("gross",0),"refund":data.get("refund",0),
            "deal_val":data.get("deal_val",0),"net_coll":data.get("net_coll",0),
            "pcdv":data.get("pcdv",0),
        }

        # Big Ticket — fast lookup via pre-grouped dicts
        row["bt_inc"] = 0; row["bt_counts"] = {}
        row["aop"] = 0; row["aop_pct"] = 0; row["bt_eligible"] = "NO"
        row["csd_cmr_tgt"] = S["csd_cmr_tgt"]

        if vert == "CSD":
            fy_age = emp.get("FY_Ageing", ageing)
            is_nursery = desig == "L1" and fy_age <= 90
            if is_nursery:
                vl = "60-90" if fy_age > 60 else "60D"
                row["vintage_label"] = vl; emp["vintage_label"] = vl
                results["nursery"].append(row)
            elif desig == "L1":
                results["exec_csd"].append(row)
            elif desig == "L2":
                results["rm_csd"].append(row)
            elif desig == "L3":
                bt_inc, bt_counts = calc_big_ticket(rec, eid, desig, vert,
                    S["bt_bm_csd"], is_l2=False,
                    _rec_cols=_rec_cols, _grp_l1=_grp_l1, _grp_mgr=_grp_mgr)
                row.update({"bt_inc":bt_inc,"bt_counts":bt_counts,
                             "bt_eligible":"Yes" if bt_inc>0 else "No"})
                results["bm_csd"].append(row); results["bt_bm_csd"].append(row)
            else:
                bt_inc, bt_counts = calc_big_ticket(rec, eid, desig, vert,
                    S["bt_ch_csd"], is_l2=True,
                    _rec_cols=_rec_cols, _grp_l1=_grp_l1, _grp_mgr=_grp_mgr)
                row.update({"bt_inc":bt_inc,"bt_counts":bt_counts,
                             "bt_eligible":"Yes" if bt_inc>0 else "No","deal_target":0})
                results["bt_ch_csd"].append(row)

        elif vert == "KCD":
            fy_age = emp.get("FY_Ageing", ageing)
            is_nursery = desig == "L1" and fy_age <= 90
            if is_nursery:
                vl = "60-90" if fy_age > 60 else "60D"
                row["vintage_label"] = vl; emp["vintage_label"] = vl
                results["nursery"].append(row)
            elif desig == "L1":
                results["exec_kcd"].append(row)
            elif desig == "L2":
                results["rm_kcd"].append(row)
            elif desig == "L3":
                bt_inc, bt_counts = calc_big_ticket(rec, eid, desig, vert,
                    S["bt_bm_kcd"], is_l2=False,
                    _rec_cols=_rec_cols, _grp_l1=_grp_l1, _grp_mgr=_grp_mgr)
                row.update({"bt_inc":bt_inc,"bt_counts":bt_counts,
                             "bt_eligible":"Yes" if bt_inc>0 else "NO"})
                results["bm_kcd"].append(row); results["bt_bm_kcd"].append(row)
            else:
                bt_inc, bt_counts = calc_big_ticket(rec, eid, desig, vert,
                    S["bt_ch_kcd"], is_l2=True,
                    _rec_cols=_rec_cols, _grp_l1=_grp_l1, _grp_mgr=_grp_mgr)
                row.update({"bt_inc":bt_inc,"bt_counts":bt_counts,
                             "bt_eligible":"Yes" if bt_inc>0 else "No"})
                results["bt_ch_kcd"].append(row)

        prog.progress((i+1)/len(eids), f"Processing {i+1}/{len(eids)}…")

    prog.empty()

    # Summary metrics
    all_rows_flat = []
    for lst in results.values():
        if isinstance(lst, list): all_rows_flat.extend(lst)

    if all_rows_flat:
        total_emp = len(all_rows_flat)
        total_payout = sum(r.get("total_inc",0) for r in all_rows_flat)
        total_bt     = sum(r.get("bt_inc",0)    for r in all_rows_flat)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Employees", total_emp)
        m2.metric("Total Incentive", f"₹{total_payout:,.0f}")
        m3.metric("Total Big Ticket", f"₹{total_bt:,.0f}")
        m4.metric("Avg Incentive", f"₹{total_payout/max(total_emp,1):,.0f}")

    if all_rows_flat:
        st.markdown("#### Employee-wise Preview")
        preview_df = pd.DataFrame([{
            "Emp ID":r.get("eid",""), "Name":r.get("name",""),
            "Vert":r.get("Vertical",""), "Level":r.get("Designation",""),
            "Vintage":r.get("Vintage",""), "Scheme":r.get("scheme",""),
            "PCDV":round(r.get("pcdv",0),0),"CMR%":r.get("cmr_pct",0),
            "Base Inc":r.get("base_inc",r.get("gross_inc",0)),
            "Spot":r.get("sp2_6_gross",0)+r.get("sp7_12_gross",0)+r.get("sp20_30_gross",0),
            "BT Inc":r.get("bt_inc",0),"Total":r.get("total_inc",0),
        } for r in all_rows_flat])
        st.dataframe(preview_df, use_container_width=True, hide_index=True)

    out_bytes = build_excel_output(results, sel_month)
    st.download_button(
        "⬇️ Download Full TA Incentive Report (Excel)",
        data=out_bytes,
        file_name=f"TA_Incentives_{sel_month.replace('-','_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    with st.expander(f"Zero Incentive Employees ({sum(1 for r in all_rows_flat if r.get('total_inc',0)==0)})"):
        zero = [r for r in all_rows_flat if r.get("total_inc",0)==0]
        if zero:
            st.dataframe(pd.DataFrame([{
                "Emp ID":r["eid"],"Name":r.get("name",""),"Level":r.get("Designation",""),
                "PCDV":round(r.get("pcdv",0),0),"CMR%":r.get("cmr_pct",0),"Scheme":r.get("scheme","")
            } for r in zero]), use_container_width=True, hide_index=True)
        else:
            st.success("All employees earned an incentive! 🎉")
