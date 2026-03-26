import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time, timezone
import math
import numpy as np

# Bắt lỗi nếu chưa cài thư viện AI
try:
    import google.generativeai as genai
    HAS_AI = True
except ImportError:
    HAS_AI = False

# ==========================================
# CẤU HÌNH THÔNG SỐ CƠ BẢN & MÚI GIỜ
# ==========================================
FILE_EXCEL = '06 tram HL6-HL21-HL27-BB-TCHP-VL-HLWVT 2026.xlsx'
NAM_DU_LIEU = 2026

# Lấy Key từ Két sắt bảo mật (Secrets) của Streamlit
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = ""

LAG_HIEPPHUOC_HOURS = 2.0 

CHANNEL_DEPTHS = {
    'HL6': 8.8, 'HL21': 8.5, 'HL27': 8.5,
    'VL': 8.0, 'TCHP': 8.0, 'BB': 6.7
}

ROUTES = {
    "ĐI VÀO (INBOUND)": {
        "P0 Vũng Tàu - Lòng Tàu - Cát Lái": {'HL27': 2.0, 'HL21': 2.5, 'HL6': 4.0},
        "P0 SR (H25) - Soài Rạp - TC Hiệp Phước": {'VL': 1.5, 'TCHP': 3.0}
    },
    "ĐI RA (OUTBOUND)": {
        "Cát Lái - Lòng Tàu - P0 Vũng Tàu": {'HL6': 0.5, 'HL21': 2.0, 'HL27': 2.5},
        "Cát Lái - Soài Rạp (Bờ Băng) - P0 SR (H25)": {'BB': 1.0, 'VL': 2.5},
        "TC Hiệp Phước - Soài Rạp (Vàm Láng) - P0 SR (H25)": {'TCHP': 0.5, 'VL': 1.5}
    }
}

# ==========================================
# HÀM XỬ LÝ TOÁN HỌC & THỜI GIAN
# ==========================================
def get_vn_time():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=7)

def lam_tron_hang_hai(val):
    if val is None: return None
    v_int = int(round(val * 100, 2))
    hang_phan_tram = v_int % 10
    if hang_phan_tram >= 4: return (v_int // 10 + 1) / 10.0
    else: return (v_int // 10) / 10.0

@st.cache_data
def load_tide_data():
    dict_data = {}
    month_keys = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                  'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
    try:
        for sheet in list(CHANNEL_DEPTHS.keys()):
            df_raw = pd.read_excel(FILE_EXCEL, sheet_name=sheet, header=None)
            parsed_data = []
            current_month, current_day = 0, 0
            for index, row in df_raw.iterrows():
                val0, val1 = str(row[0]).strip().lower(), str(row[1]).strip().upper().replace(" ", "")
                is_month = False
                for m_key, m_val in month_keys.items():
                    if m_key in val0: current_month, current_day, is_month = m_val, 0, True; break
                if is_month: continue
                if current_month > 0:
                    if val1 == 'CN': current_day += 1
                    else:
                        try: current_day = int(float(val1))
                        except: continue
                    hours_data = pd.to_numeric(row[2:26].values, errors='coerce')
                    if pd.Series(hours_data).notna().sum() > 12:
                        row_dict = {'Thang': current_month, 'Ngay': current_day}
                        for h in range(24): row_dict[h] = hours_data[h]
                        parsed_data.append(row_dict)
            df_clean = pd.DataFrame(parsed_data)
            if not df_clean.empty:
                dict_data[sheet] = df_clean.drop_duplicates(subset=['Thang', 'Ngay']).set_index(['Thang', 'Ngay'])
    except: return None
    return dict_data if len(dict_data) > 0 else None

def tinh_ukc(draft, eta_time):
    t = eta_time.time()
    pct = 0.07 if datetime.strptime('05:01','%H:%M').time() <= t <= datetime.strptime('17:59','%H:%M').time() else 0.10
    return lam_tron_hang_hai(draft * (1 + pct)), pct

def noi_suy_thuy_trieu(df_tide, eta_time):
    try:
        th, ng, gi, mi = eta_time.month, eta_time.day, eta_time.hour, eta_time.minute
        if (th, ng) not in df_tide.index: return None
        v1 = df_tide.loc[(th, ng), gi]
        if isinstance(v1, pd.Series): v1 = v1.iloc[0]
        if gi == 23:
            eta2 = eta_time + timedelta(hours=1)
            th2, ng2, gi2 = eta2.month, eta2.day, 0
        else: th2, ng2, gi2 = th, ng, gi + 1
        v2 = df_tide.loc[(th2, ng2), gi2] if (th2, ng2) in df_tide.index else v1
        if isinstance(v2, pd.Series): v2 = v2.iloc[0]
        return lam_tron_hang_hai(v1 + ((v2 - v1) * (mi / 60)))
    except: return None

# ==========================================
# LÕI THUẬT TOÁN WINDOW (BẢN GỐC 100% CỦA BẠN)
# ==========================================
@st.cache_data
def process_slack_windows_original():
    try:
        xl = pd.ExcelFile(FILE_EXCEL)
        
        # 1. Đọc F28 Cát Lái
        df_f28 = pd.DataFrame()
        if 'CL' in xl.sheet_names:
            df_cl = xl.parse('CL')
            df_cl.columns = df_cl.columns.astype(str).str.strip().str.upper()
            df_cl = df_cl.dropna(subset=['TIME']).copy()
            df_cl['DATE'] = df_cl['DATE'].ffill()
            dts_f28 = []
            for _, r in df_cl.iterrows():
                try:
                    d = pd.to_datetime(r['DATE'])
                    t = str(r['TIME']).strip()
                    h, m = map(int, t.split(':')[:2])
                    dts_f28.append(d + pd.Timedelta(hours=h, minutes=m))
                except: continue
            df_f28 = pd.DataFrame({'F28_DT': dts_f28}).dropna().sort_values('F28_DT')

        # 2. Đọc F28 Cái Mép
        df_f28cm = pd.DataFrame()
        if 'CM' in xl.sheet_names:
            df_cm = xl.parse('CM')
            df_cm.columns = df_cm.columns.astype(str).str.strip().str.upper()
            df_cm = df_cm.dropna(subset=['TIME']).copy()
            df_cm['DATE'] = df_cm['DATE'].ffill()
            dts_f28cm = []
            for _, r in df_cm.iterrows():
                try:
                    d = pd.to_datetime(r['DATE'])
                    t = str(r['TIME']).strip()
                    h, m = map(int, t.split(':')[:2])
                    dts_f28cm.append(d + pd.Timedelta(hours=h, minutes=m))
                except: continue
            df_f28cm = pd.DataFrame({'F28_DT': dts_f28cm}).dropna().sort_values('F28_DT')

        # 3. Đọc dữ liệu triều Vũng Tàu (HLW-VT)
        sheet_n = 'HLW-VT' if 'HLW-VT' in xl.sheet_names else 'HW_LW_VT'
        df = xl.parse(sheet_n)
        df.columns = df.columns.str.strip()
        
        col_time_orig = 'HL Water'
        col_level = 'Level(m)'
        
        # Đề phòng tên cột trong file bị lệch
        if col_time_orig not in df.columns:
            df.columns = ['Date', 'HL Water', 'Level(m)'] + list(df.columns[3:])

        df = df.dropna(subset=[col_time_orig, col_level]).copy()
        df[col_level] = pd.to_numeric(df[col_level], errors='coerce')
        df['Parsed_Date'] = pd.to_datetime(df['Date'], errors='coerce').bfill(limit=1).ffill()

        base_dts = []
        for _, row in df.iterrows():
            try:
                t = str(row[col_time_orig]).strip()
                h, m = map(int, t.split(':')[:2])
                base_dts.append(row['Parsed_Date'] + pd.Timedelta(hours=h, minutes=m))
            except: base_dts.append(pd.NaT)

        df['Event_Datetime'] = base_dts
        df_clean = df.dropna(subset=['Event_Datetime', col_level]).sort_values('Event_Datetime').reset_index(drop=True)

        # 4. LỌC BÓNG MA V2 (Giữ nguyên gốc)
        df_clean['Amplitude'] = abs(df_clean[col_level] - df_clean[col_level].shift(1))
        df_clean['Ký hiệu'] = np.where(df_clean[col_level] > df_clean[col_level].shift(1), 'HW', 'LW')

        valid_indices = []
        for idx, row in df_clean.iterrows():
            if pd.notna(row['Amplitude']) and row['Amplitude'] == 0.0:
                continue
            valid_indices.append(idx)
            
        df_calc = df_clean.loc[valid_indices].copy().reset_index(drop=True)

        # 5. TÍNH SLACK
        final_cl_dts, final_cm_dts, arrs = [], [], []
        res_cl, res_cm = [], []

        for idx, row in df_calc.iterrows():
            hw_lw, level, base_dt = row['Ký hiệu'], row[col_level], row['Event_Datetime']
            
            if hw_lw == 'HW':
                arr = '↙'
                delta_cm = 65 
                if level >= 4.0: delta_cl = 235 
                elif level >= 3.0: delta_cl = 205 
                elif level >= 2.0: delta_cl = 195 
                else: delta_cl = 185 
            else:
                arr = '↗'
                delta_cm = 50 
                if level >= 1.5: delta_cl = 220 
                elif level >= 1.0: delta_cl = 225 
                elif level >= 0.5: delta_cl = 230 
                else: delta_cl = 235 

            arrs.append(arr)

            # Cát Lái
            cl_dt = base_dt + pd.Timedelta(minutes=delta_cl)
            final_cl_dt = cl_dt
            if not df_f28.empty:
                t_diffs = (df_f28['F28_DT'] - cl_dt).abs()
                if t_diffs.min() <= pd.Timedelta(hours=3):
                    best_f28 = df_f28.loc[t_diffs.idxmin(), 'F28_DT']
                    d_mins = int((cl_dt - best_f28).total_seconds() / 60)
                    early, d_abs = (cl_dt if d_mins < 0 else best_f28), abs(d_mins)
                    if d_abs <= 15: final_cl_dt = early
                    else: final_cl_dt = early + pd.Timedelta(minutes=int(d_abs * 0.35))
                    final_cl_dt = final_cl_dt.replace(minute=(final_cl_dt.minute // 5) * 5)
            final_s = final_cl_dt.strftime('%H:%M') + (' (+1)' if final_cl_dt.date() > base_dt.date() else '')
            final_cl_dts.append(final_cl_dt)
            res_cl.append(final_s)

            # Cái Mép
            cm_dt = base_dt + pd.Timedelta(minutes=delta_cm)
            final_cm_dt = cm_dt
            if not df_f28cm.empty:
                t_diffs_cm = (df_f28cm['F28_DT'] - cm_dt).abs()
                if t_diffs_cm.min() <= pd.Timedelta(hours=3):
                    best_f28cm = df_f28cm.loc[t_diffs_cm.idxmin(), 'F28_DT']
                    d_mins_cm = int((cm_dt - best_f28cm).total_seconds() / 60)
                    early_cm, d_abs_cm = (cm_dt if d_mins_cm < 0 else best_f28cm), abs(d_mins_cm)
                    if d_abs_cm <= 15: final_cm_dt = early_cm
                    else: final_cm_dt = early_cm + pd.Timedelta(minutes=int(d_abs_cm * 0.35))
                    final_cm_dt = final_cm_dt.replace(minute=(final_cm_dt.minute // 5) * 5)
            final_cm_s = final_cm_dt.strftime('%H:%M') + (' (+1)' if final_cm_dt.date() > base_dt.date() else '')
            final_cm_dts.append(final_cm_dt)
            res_cm.append(final_cm_s)

        df_calc['SlackCL_DT'] = final_cl_dts
        df_calc['SlackCM_DT'] = final_cm_dts
        df_calc['Dir'] = arrs
        df_calc['Slack CL'] = res_cl
        df_calc['Slack CM'] = res_cm

        # 6. HÀM TÍNH TOÁN TARGET VÀ CỬA SỔ
        def floor_to_15min(dt_obj):
            if pd.isna(dt_obj) or dt_obj is None: return None
            return dt_obj.replace(minute=(dt_obj.minute // 15) * 15, second=0, microsecond=0)

        def calc_window_dt(t_slack, boundary_slack, dt_mins, amp, target_knot, is_before):
            if pd.isna(t_slack) or pd.isna(dt_mins) or pd.isna(amp) or dt_mins <= 0 or amp <= 0: 
                return None
            th_mins = dt_mins / 6.0 
            speeds = [0, (1/12 * amp) / 0.2, (2/12 * amp) / 0.2, (3/12 * amp) / 0.2] 
            if target_knot > speeds[-1]: return floor_to_15min(boundary_slack)
            else:
                for k in range(1, 4):
                    if speeds[k-1] <= target_knot <= speeds[k]:
                        frac = 0 if speeds[k] == speeds[k-1] else (target_knot - speeds[k-1]) / (speeds[k] - speeds[k-1])
                        delta_mins = (k - 1 + frac) * th_mins
                        res_time = t_slack - pd.Timedelta(minutes=delta_mins) if is_before else t_slack + pd.Timedelta(minutes=delta_mins)
                        return floor_to_15min(res_time)
            return None

        TARGET_BEGIN_CL, TARGET_END_CL = 2.1, 1.5
        TARGET_BEGIN_CM1, TARGET_END_CM1 = 1.5, 1.0
        TARGET_BEGIN_CM2, TARGET_END_CM2 = 2.3, 1.6

        raw_b_cl, raw_e_cl = [], []
        raw_b_cm1, raw_e_cm1 = [], []
        raw_b_cm2, raw_e_cm2 = [], []

        for i in range(len(df_calc)):
            # CL
            if i > 0:
                boundary_prev = df_calc['SlackCL_DT'][i-1]
                dur_bef = (df_calc['SlackCL_DT'][i] - boundary_prev).total_seconds() / 60
                amp_bef = abs(df_calc[col_level][i] - df_calc[col_level][i-1])
                raw_b_cl.append(calc_window_dt(df_calc['SlackCL_DT'][i], boundary_prev, dur_bef, amp_bef, TARGET_BEGIN_CL, True))
            else: raw_b_cl.append(None)
            
            if i < len(df_calc) - 1:
                boundary_next = df_calc['SlackCL_DT'][i+1]
                dur_aft = (boundary_next - df_calc['SlackCL_DT'][i]).total_seconds() / 60
                amp_aft = abs(df_calc[col_level][i+1] - df_calc[col_level][i])
                raw_e_cl.append(calc_window_dt(df_calc['SlackCL_DT'][i], boundary_next, dur_aft, amp_aft, TARGET_END_CL, False))
            else: raw_e_cl.append(None)

            # CM
            if i > 0:
                boundary_prev = df_calc['SlackCM_DT'][i-1]
                dur_bef = (df_calc['SlackCM_DT'][i] - boundary_prev).total_seconds() / 60
                amp_bef = abs(df_calc[col_level][i] - df_calc[col_level][i-1])
                raw_b_cm1.append(calc_window_dt(df_calc['SlackCM_DT'][i], boundary_prev, dur_bef, amp_bef, TARGET_BEGIN_CM1, True))
                raw_b_cm2.append(calc_window_dt(df_calc['SlackCM_DT'][i], boundary_prev, dur_bef, amp_bef, TARGET_BEGIN_CM2, True))
            else: 
                raw_b_cm1.append(None); raw_b_cm2.append(None)
            
            if i < len(df_calc) - 1:
                boundary_next = df_calc['SlackCM_DT'][i+1]
                dur_aft = (boundary_next - df_calc['SlackCM_DT'][i]).total_seconds() / 60
                amp_aft = abs(df_calc[col_level][i+1] - df_calc[col_level][i])
                raw_e_cm1.append(calc_window_dt(df_calc['SlackCM_DT'][i], boundary_next, dur_aft, amp_aft, TARGET_END_CM1, False))
                raw_e_cm2.append(calc_window_dt(df_calc['SlackCM_DT'][i], boundary_next, dur_aft, amp_aft, TARGET_END_CM2, False))
            else: 
                raw_e_cm1.append(None); raw_e_cm2.append(None)

        # 7. RELAY RACE
        b_cl, e_cl = [], []
        b_cm1, e_cm1 = [], []
        b_cm2, e_cm2 = [], []

        for i in range(len(df_calc)):
            # CL
            b_cl_val = raw_b_cl[i]
            if i > 0 and b_cl_val is not None and raw_e_cl[i-1] is not None:
                if b_cl_val < raw_e_cl[i-1]: b_cl_val = raw_e_cl[i-1]
            b_cl.append(b_cl_val)
            e_cl.append(raw_e_cl[i])

            # CM1
            b_cm1_val = raw_b_cm1[i]
            if i > 0 and b_cm1_val is not None and raw_e_cm1[i-1] is not None:
                if b_cm1_val < raw_e_cm1[i-1]: b_cm1_val = raw_e_cm1[i-1]
            b_cm1.append(b_cm1_val)
            e_cm1.append(raw_e_cm1[i])

            # CM2
            b_cm2_val = raw_b_cm2[i]
            if i > 0 and b_cm2_val is not None and raw_e_cm2[i-1] is not None:
                if b_cm2_val < raw_e_cm2[i-1]: b_cm2_val = raw_e_cm2[i-1]
            b_cm2.append(b_cm2_val)
            e_cm2.append(raw_e_cm2[i])

        df_calc['B_CL'] = b_cl
        df_calc['E_CL'] = e_cl
        df_calc['B_CM1'] = b_cm1
        df_calc['E_CM1'] = e_cm1
        df_calc['B_CM2'] = b_cm2
        df_calc['E_CM2'] = e_cm2

        return df_calc

    except Exception as e:
        return pd.DataFrame()

def format_win_str(dt_val, ref_dt):
    if pd.isna(dt_val) or dt_val is None: return "-"
    s = dt_val.strftime('%H:%M')
    if dt_val.date() > ref_dt.date(): s += ' (+1)'
    elif dt_val.date() < ref_dt.date(): s += ' (-1)'
    return s

@st.cache_data
def tao_bang_mon_nuoc_toi_da(data_dict, thang_chon):
    danh_sach_dong = []
    try:
        pts = list(CHANNEL_DEPTHS.keys())
        ngay_hop_le = sorted(list(set(data_dict[pts[0]].loc[thang_chon].index.tolist())))
        for ngay in ngay_hop_le:
            try:
                date_obj = datetime(NAM_DU_LIEU, thang_chon, int(ngay))
                thu_ngay_str = f"{date_obj.strftime('%a')}\n{ngay}"
            except: thu_ngay_str = str(ngay)
            for point in pts:
                if point not in data_dict: continue
                dong = {'Ngày': thu_ngay_str, 'Điểm': point, 'Ngay_Goc': int(ngay)}
                for gio in range(24):
                    muc = data_dict[point].loc[(thang_chon, ngay), gio]
                    if isinstance(muc, pd.Series): muc = muc.iloc[0]
                    ukc = 0.07 if 6 <= gio <= 17 else 0.10
                    mon = lam_tron_hang_hai((CHANNEL_DEPTHS[point] + muc) / (1 + ukc))
                    dong[f'{gio}h'] = f"{mon:.1f}"
                danh_sach_dong.append(dong)
    except: return pd.DataFrame()
    return pd.DataFrame(danh_sach_dong)

# ==========================================
# KHỞI TẠO AI CHATBOT (BƠM DỮ LIỆU WINDOW MỚI)
# ==========================================
@st.cache_resource
def get_ai_bot(_df_calc, api_key):
    genai.configure(api_key=api_key)
    
    if not _df_calc.empty:
        ai_data = []
        for i, r in _df_calc.iterrows():
            d_str = r['Event_Datetime'].strftime('%d/%m %H:%M')
            lvl = r.get('Level(m)', 0)
            
            win_cl = f"{r['B_CL'].strftime('%H:%M')}-{r['E_CL'].strftime('%H:%M')}" if pd.notna(r['B_CL']) and pd.notna(r['E_CL']) else "-"
            win_cm = f"{r['B_CM1'].strftime('%H:%M')}-{r['E_CM1'].strftime('%H:%M')}" if pd.notna(r['B_CM1']) and pd.notna(r['E_CM1']) else "-"
            ai_data.append(f"{d_str}|{r['Ký hiệu']} {lvl}m -> CL:{win_cl} | CM(Lớn):{win_cm}")
        almanac_str = "\n".join(ai_data)
    else:
        almanac_str = "Không có dữ liệu."

    system_instruction = f"""
    Bạn là Trợ lý AI Hoa Tiêu Hàng Hải (Tân Cảng Pilot). 
    
    ĐỊNH NGHĨA TUYẾN LUỒNG:
    1. ĐI VÀO: "P0 Vũng Tàu - Cát Lái" (Qua HL6 sau 4h). "P0 SR - TC Hiệp Phước" (Qua TCHP sau 3h). CÁI MÉP (Tàu cập thẳng Cái Mép).
    2. ĐI RA: "Cát Lái - Vũng Tàu" (Qua HL6 sau 0.5h). "Cát Lái - Soài Rạp H25" (Qua Bờ Băng, Vàm Láng).
    
    CẤU TRÚC BÁO CÁO NHƯ BỘ ĐÀM VHF:
    - Tuyến: [Tên tuyến].
    - Đánh giá mớn: Mớn + UKC. [Lọt / Cạn].
    - Chốt giờ POB: Dựa vào DỮ LIỆU WINDOW bên dưới, chọn giờ POB sao cho giờ tàu đến Cát Lái/Cái Mép phải nằm LỌT GIỮA khung Window quy định.
    
    DỮ LIỆU WINDOW CÁT LÁI & CÁI MÉP 2026 (Ngày giờ | HW/LW Đỉnh triều -> Khung giờ dòng chảy êm):
    {almanac_str}
    """
    
    try:
        valid_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        clean_models = [m for m in valid_models if 'image' not in m.lower() and 'vision' not in m.lower() and 'preview' not in m.lower()]
        
        chosen_model = None
        for m in clean_models:
            if 'gemini-1.5-flash' in m.lower() and '8b' not in m.lower():
                chosen_model = m.replace('models/', '')
                break
        if not chosen_model:
            for m in clean_models:
                if 'flash' in m.lower():
                    chosen_model = m.replace('models/', '')
                    break
        if not chosen_model:
            chosen_model = clean_models[0].replace('models/', '') if clean_models else 'gemini-1.5-flash'
    except Exception as e: chosen_model = 'gemini-1.5-flash'
        
    model = genai.GenerativeModel(chosen_model)
    return model, chosen_model, system_instruction

# ==========================================
# GIAO DIỆN WEB (UI)
# ==========================================
st.set_page_config(page_title="Tan Cang Pilot Tide Calculation", layout="wide", initial_sidebar_state="collapsed")

df_slack = process_slack_windows_original()
data_dict = load_tide_data()

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    .stButton>button { min-height: 55px; font-weight: bold; border-radius: 8px; margin-top: 15px; }
    .safe-window { background-color: rgba(46, 160, 67, 0.15); border-left: 5px solid #2ea043; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    .warn-window { background-color: rgba(212, 167, 44, 0.15); border-left: 5px solid #d4a72c; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    .unsafe-window { background-color: rgba(207, 34, 46, 0.15); border-left: 5px solid #cf222e; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    
    div.row-widget.stRadio > div{ flex-direction:row; }
    [data-testid="stNumberInput"], [data-testid="stDateInput"], [data-testid="stTimeInput"], 
    [data-testid="stSelectbox"], [data-testid="stMultiSelect"] { display: flex; flex-direction: row; align-items: center; }
    [data-testid="stNumberInput"] > label, [data-testid="stDateInput"] > label, 
    [data-testid="stTimeInput"] > label, [data-testid="stSelectbox"] > label, 
    [data-testid="stMultiSelect"] > label { width: 100px !important; min-width: 100px !important; margin-bottom: 0px !important; margin-right: 15px; display: flex; align-items: center; }
    [data-testid="stNumberInput"] > div, [data-testid="stDateInput"] > div, 
    [data-testid="stTimeInput"] > div, [data-testid="stSelectbox"] > div, [data-testid="stMultiSelect"] > div { flex: 1; }
    [data-testid="stCheckbox"] { display: flex; align-items: center; padding-top: 8px; }
    .stChatMessage { border-radius: 10px; padding: 10px; }

    /* ======== HIỆU ỨNG 3D NÚT BẤM CHO CÁC TAB ======== */
    button[data-baseweb="tab"] {
        background-color: rgba(128,128,128,0.05); 
        border: 1px solid rgba(128,128,128,0.2);
        border-bottom: 4px solid rgba(128,128,128,0.3);
        border-radius: 10px 10px 0 0;
        margin-right: 5px;
        transition: all 0.15s ease-in-out;
    }
    button[data-baseweb="tab"]:hover { transform: translateY(-2px); border-bottom: 6px solid rgba(128,128,128,0.4); }
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: transparent; border-bottom: 0px solid transparent; 
        transform: translateY(4px); box-shadow: inset 0 3px 6px rgba(0,0,0,0.1); 
        border-top: 3px solid #0099ff; 
    }
    @media (prefers-color-scheme: dark) { button[data-baseweb="tab"][aria-selected="true"] { box-shadow: inset 0 3px 6px rgba(0,0,0,0.5); } }
</style>
""", unsafe_allow_html=True)

st.title("🚢 TAN CANG PILOT V3.1")

st.markdown("""
<div style="font-size: 0.65em; margin-bottom: 20px; padding: 10px; background-color: rgba(128,128,128,0.1); border-radius: 5px; opacity: 0.9;">
    UKC: Ngày 7%, Đêm 10%. &nbsp;|&nbsp; 
    HL6=<strong style="color: #ff4b4b;">-8.8m</strong>; HL21/HL27=<strong style="color: #ff4b4b;">-8.5m</strong>; BB=<strong style="color: #ff4b4b;">-6.7m</strong>; VL/TCHP=<strong style="color: #ff4b4b;">-8.0m</strong>.
</div>
""", unsafe_allow_html=True)

if data_dict is None or df_slack.empty:
    st.error(f"⚠️ Thiếu file hoặc dữ liệu {FILE_EXCEL} không hợp lệ!"); st.stop()

tab_pob_draft, tab_ai, tab_draft_pob, tab_max_draft, tab_window = st.tabs([
    "🚀 POB and Draft", 
    "🤖 Trợ lý AI", 
    "⏱️ Draft for POB", 
    "📅 Max Draft Table",
    "🌊 Slack Water Window"
])

# ----------------- TAB 1: POB AND DRAFT -----------------
with tab_pob_draft:
    col1, col2 = st.columns(2)
    bay_gio = get_vn_time()
    gio_mac_dinh = time(bay_gio.hour, 0)
    
    with col1:
        mon_nuoc = st.number_input("Mớn nước (m)", 1.0, 20.0, 10.5, 0.1, key="t1_mon")
        ngay_pob = st.date_input("Ngày POB", bay_gio.date(), format="DD/MM/YYYY", key="t1_ngay")
        gio_pob = st.time_input("Giờ POB", gio_mac_dinh, key="t1_gio")
    with col2:
        huong_di = st.radio("Hướng di chuyển", ["ĐI VÀO (INBOUND)", "ĐI RA (OUTBOUND)"], horizontal=True, key="t1_huong")
        tuyen_luong = st.radio("Tuyến luồng (Route)", list(ROUTES[huong_di].keys()), key="t1_tuyen")

    if st.button("🚀 KIỂM TRA ĐIỀU KIỆN AN TOÀN", use_container_width=True, key="btn_t1"):
        pob_t = datetime.combine(ngay_pob, gio_pob)
        st.markdown(f"### 📊 KẾT QUẢ: {tuyen_luong}")
        pts = ROUTES[huong_di][tuyen_luong]
        cols = st.columns(len(pts))
        for i, (p, h) in enumerate(pts.items()):
            eta = pob_t + timedelta(hours=h)
            req, _ = tinh_ukc(mon_nuoc, eta) 
            with cols[i]:
                t_h = noi_suy_thuy_trieu(data_dict[p], eta) 
                if t_h is not None:
                    act = lam_tron_hang_hai(CHANNEL_DEPTHS[p] + t_h)
                    if act >= req: st.success(f"📍 {p}: ✅ LỌT")
                    else: st.error(f"📍 {p}: ❌ CẠN")
                    st.write(f"🕒 ETA: {eta.strftime('%H:%M %d/%b')}")
                    st.write(f"📏 Yêu cầu: {req:.1f}m | 🌊 TT: {act:.1f}m")
                    st.caption(f"(Luồng {CHANNEL_DEPTHS[p]}m + Triều {t_h:.1f}m)")

# ----------------- TAB 2: TRỢ LÝ AI -----------------
with tab_ai:
    if not HAS_AI or not API_KEY:
        st.error("⚠️ Lỗi: Chưa cấu hình đúng thư viện AI hoặc mất kết nối tới API Key (Két sắt Secrets).")
    else:
        st.markdown("### 🤖 Trợ lý AI Tân Cảng Pilot")
        
        if "chat_session" not in st.session_state:
            with st.spinner("Đang khởi động AI & Tích hợp thuật toán Slack Water..."):
                try:
                    ai_model, model_name, sys_instruct = get_ai_bot(df_slack, API_KEY)
                    st.session_state.chat_session = ai_model.start_chat(history=[
                        {"role": "user", "parts": [sys_instruct]},
                        {"role": "model", "parts": ["Đã rõ thưa Thuyền trưởng. Báo cáo chốt lọt/cạn và giờ Window chuẩn xác. Xin lệnh!"]}
                    ])
                except Exception as e:
                    st.error(f"Lỗi khởi tạo AI: {e}")

        if "chat_session" in st.session_state:
            for message in st.session_state.chat_session.history[2:]:
                role = "user" if message.role == "user" else "assistant"
                with st.chat_message(role):
                    st.markdown(message.parts[0].text)

            if user_prompt := st.chat_input("Nhập yêu cầu điều động (VD: Mớn 10.7m, đi Cát Lái ngày 25/03, giờ nào an toàn?)..."):
                with st.chat_message("user"):
                    st.markdown(user_prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("Đang chéo bảng triều và cắt Window..."):
                        try:
                            response = st.session_state.chat_session.send_message(user_prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"⚠️ Đã có lỗi xảy ra: {e}")

# ----------------- TAB 3: DRAFT FOR POB (SỬ DỤNG LÕI WINDOW CHUẨN) -----------------
with tab_draft_pob:
    col3_1, col3_2 = st.columns(2)
    bay_gio_t3 = get_vn_time()
    
    with col3_1:
        mon_nuoc_t3 = st.number_input("Mớn nước (m)", 1.0, 20.0, 10.5, 0.1, key="t3_mon")
        ngay_pob_t3 = st.date_input("Ngày POB", bay_gio_t3.date(), format="DD/MM/YYYY", key="t3_ngay")
    with col3_2:
        huong_di_t3 = st.radio("Hướng di chuyển", ["ĐI VÀO (INBOUND)", "ĐI RA (OUTBOUND)"], horizontal=True, key="t3_huong")
        tuyen_luong_t3 = st.radio("Tuyến luồng (Route)", list(ROUTES[huong_di_t3].keys()), key="t3_tuyen")

    if st.button("⏱️ QUÉT TÌM GIỜ CHẠY TÀU", use_container_width=True, key="btn_t3"):
        st.markdown("---")
        pts = ROUTES[huong_di_t3][tuyen_luong_t3]
        current_time_vn = get_vn_time()
        rounded_now = current_time_vn.replace(minute=(0 if current_time_vn.minute < 30 else 30), second=0, microsecond=0)

        ket_qua = []
        khung_gio_hoan_hao = []
        dang_trong_khung = False
        gio_bat_dau = None
        
        di_cat_lai = "Cát Lái" in tuyen_luong_t3
        travel_to_cl = pts.get('HL6', 0) if di_cat_lai else 0

        for h in range(24):
            for m in [0, 30]:
                thoi_gian_xet = time(h, m)
                pob_t = datetime.combine(ngay_pob_t3, thoi_gian_xet)
                
                if pob_t < rounded_now: continue
                
                is_safe = True
                ly_do = ""
                
                # Quét lọt mớn
                for p, travel_h in pts.items():
                    if p not in data_dict:
                        is_safe, ly_do = False, f"Thiếu dữ liệu {p}"; break
                        
                    eta = pob_t + timedelta(hours=travel_h)
                    req, _ = tinh_ukc(mon_nuoc_t3, eta)
                    tide_h = noi_suy_thuy_trieu(data_dict[p], eta)

                    if tide_h is None:
                        is_safe, ly_do = False, f"Hết dữ liệu Triều"; break

                    act = lam_tron_hang_hai(CHANNEL_DEPTHS[p] + tide_h)
                    clearance = round(act - req, 1)

                    if clearance < 0:
                        is_safe, ly_do = False, f"Cạn tại {p} (Thiếu {-clearance:.1f}m)"
                        break
                            
                # Đối chiếu Window
                is_in_window = False
                window_note = "N/A"
                
                if di_cat_lai and not df_slack.empty:
                    eta_cl = pob_t + timedelta(hours=travel_to_cl)
                    for _, r in df_slack.iterrows():
                        if pd.notna(r['B_CL']) and pd.notna(r['E_CL']):
                            if r['B_CL'] <= eta_cl <= r['E_CL']:
                                is_in_window = True
                                window_note = f"{r['Dir']} Dòng êm ({r['B_CL'].strftime('%H:%M')}-{r['E_CL'].strftime('%H:%M')} tại CL)"
                                break
                    if not is_in_window: window_note = "Ngoài Window (Dòng xiết)"
                elif not di_cat_lai:
                    is_in_window = True
                    window_note = "Lọt mớn an toàn"

                if is_safe:
                    if is_in_window:
                        ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "✅ LỌT & WINDOW", "Ghi chú": window_note})
                        if not dang_trong_khung: gio_bat_dau, dang_trong_khung = thoi_gian_xet.strftime('%H:%M'), True
                    else:
                        ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "⚠️ LỌT (DÒNG XIẾT)", "Ghi chú": window_note})
                        if dang_trong_khung:
                            gio_ket_thuc = (pob_t - timedelta(minutes=30)).strftime('%H:%M')
                            khung_gio_hoan_hao.append(f"{gio_bat_dau} đến {gio_ket_thuc}")
                            dang_trong_khung = False
                else:
                    ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "❌ CẠN", "Ghi chú": ly_do})
                    if dang_trong_khung:
                        gio_ket_thuc = (pob_t - timedelta(minutes=30)).strftime('%H:%M')
                        khung_gio_hoan_hao.append(f"{gio_bat_dau} đến {gio_ket_thuc}")
                        dang_trong_khung = False
        
        if dang_trong_khung: khung_gio_hoan_hao.append(f"{gio_bat_dau} đến 23:30")

        if len(khung_gio_hoan_hao) > 0:
            st.markdown(f"<div class='safe-window'><strong>🎯 KẾT LUẬN (CỬA SỔ VÀNG):</strong> Tàu có thể POB lọt mớn & đúng dòng êm trong khoảng:<br><h3>" + " <br> ".join([f"🕒 {k}" for k in khung_gio_hoan_hao]) + "</h3></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='unsafe-window'><strong>⚠️ KẾT LUẬN:</strong> Không có giờ POB nào lọt mớn hoặc rơi vào Window!</div>", unsafe_allow_html=True)

        st.markdown("#### 📋 Bảng chi tiết")
        df_kq = pd.DataFrame(ket_qua)
        if not df_kq.empty:
            def color_status(val):
                if "✅" in val: return 'color: #009900; font-weight: bold;'
                elif "⚠️" in val: return 'color: #b8860b; font-weight: bold;'
                elif "❌" in val: return 'color: #cc0000; font-weight: bold;'
                return ''
            styled_kq = df_kq.style.map(color_status, subset=['Trạng thái'])
            st.dataframe(styled_kq, use_container_width=True, height=400)

# ----------------- TAB 4: MAX DRAFT TABLE -----------------
with tab_max_draft:
    bay_gio_t2 = get_vn_time()
    col_th, col_ck, col_tu = st.columns([1, 1, 2])
    with col_th: 
        thang_ch = st.selectbox("Tháng", list(range(1, 13)), index=int(bay_gio_t2.month - 1))
    with col_ck: 
        show_old = st.checkbox("Hiện ngày đã qua", value=False)
    with col_tu: 
        diem_options = ['HL6', 'HL21', 'HL27', 'Vàm Láng', 'TC Hiệp Phước', 'Bờ Băng']
        tu_sel = st.multiselect("Điểm cạn", diem_options, default=['HL6', 'HL27'])

    bang_raw = tao_bang_mon_nuoc_toi_da(data_dict, thang_ch)
    if not bang_raw.empty:
        df_f = bang_raw.copy()
        if thang_ch == bay_gio_t2.month and not show_old: df_f = df_f[df_f['Ngay_Goc'] >= bay_gio_t2.day]
        rev_map = {'HL6': 'HL6', 'HL21': 'HL21', 'HL27': 'HL27', 'VL': 'Vàm Láng', 'TCHP': 'TC Hiệp Phước', 'BB': 'Bờ Băng'}
        df_f['Điểm'] = df_f['Điểm'].map(rev_map)
        
        if tu_sel: df_f = df_f[df_f['Điểm'].isin(tu_sel)]
        else: df_f = df_f[df_f['Điểm'].isin([])]

        ngay_list = df_f['Ngày'].tolist()
        new_ngay = []
        last_d, h_char, global_cnt = None, '\u200b', 1
        for d in ngay_list:
            if d != last_d: new_ngay.append(d); last_d = d
            else: new_ngay.append(h_char * global_cnt); global_cnt += 1
        df_f['Ngày'] = new_ngay
        
        if not df_f.empty:
            df_disp = df_f.drop(columns=['Ngay_Goc']).set_index(['Ngày', 'Điểm'])
            def apply_st(df):
                stys = pd.DataFrame('', index=df.index, columns=df.columns)
                for i in range(len(df)):
                    if "Sun" in ngay_list[i]: stys.iloc[i, :] = 'background-color: rgba(255, 75, 75, 0.15); color: #ff4b4b; font-weight: bold;'
                return stys
            def style_idx(val):
                if val in ['HL6','HL21','HL27']: return 'color: #33ccff; font-weight: bold;'
                if val in ['Vàm Láng','Bờ Băng','TC Hiệp Phước']: return 'color: #ff9933; font-weight: bold;'
                return 'font-weight: bold;'
            styled_df = df_disp.style.apply(apply_st, axis=None).map_index(style_idx, axis=0)
            st.dataframe(styled_df, use_container_width=True, height=600)
        else:
            st.info("Vui lòng chọn ít nhất một điểm để hiển thị dữ liệu.")

# ----------------- TAB 5: SLACK WATER WINDOW (TÍNH TỪ LÕI GỐC) -----------------
with tab_window:
    st.markdown("""
    <style>
        .tag-hw { background-color: #e3f2fd; color: #007bff; padding: 4px 10px; border-radius: 12px; font-weight: bold; border: 1px solid #007bff; display: inline-block; text-align: center; }
        .tag-lw { background-color: #fce4e4; color: #dc3545; padding: 4px 10px; border-radius: 12px; font-weight: bold; border: 1px solid #dc3545; display: inline-block; text-align: center; }
        .tag-dir-in { background-color: #e8f8f5; color: #117a65; font-size: 1.2em; font-weight: bold; border-radius: 50%; padding: 0 5px; }
        .tag-dir-out { background-color: #fef9e7; color: #d35400; font-size: 1.2em; font-weight: bold; border-radius: 50%; padding: 0 5px; }
    </style>
    """, unsafe_allow_html=True)
    
    col_win_1, col_win_2 = st.columns([2, 8])
    with col_win_1:
        st.markdown("<p style='margin-top: 10px; font-weight: bold; font-size: 16px;'>🔄 Chế độ hiển thị:</p>", unsafe_allow_html=True)
    with col_win_2:
        view = st.radio("Chế độ hiển thị", ("Week", "Month"), horizontal=True, label_visibility="collapsed")
        
    if view == "Week":
        sel_d = st.date_input("🗓️ Chọn ngày mốc:", bay_gio.date())
        start = pd.Timestamp(sel_d) - pd.Timedelta(days=1)
        end = start + pd.Timedelta(days=6)
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1: s_month = st.selectbox("📅 Tháng:", list(range(1, 13)), index=bay_gio.month-1)
        with col_m2: s_year = st.selectbox("📅 Năm:", [2025, 2026, 2027], index=1)
        start = pd.Timestamp(year=s_year, month=s_month, day=1)
        end = start + pd.offsets.MonthEnd()

    if df_slack.empty:
        st.warning("Không có dữ liệu Window. Vui lòng kiểm tra lại file Excel (Sheet HLW-VT).")
    else:
        df_show = df_slack[(df_slack['Event_Datetime'] >= start) & (df_slack['Event_Datetime'] <= end)].copy()
        
        df_show['Date'] = df_show['Event_Datetime'].dt.strftime('%d/%m/%Y')
        df_show.loc[df_show['Date'] == df_show['Date'].shift(), 'Date'] = ""
        df_show['Vũng Tàu'] = df_show['Event_Datetime'].dt.strftime('%H:%M') + "<br><b>" + df_show['Level(m)'].astype(str) + "m</b>"
        
        df_show['Type'] = df_show['Ký hiệu'].apply(lambda x: f"<div class='tag-hw'>{x}</div>" if x == 'HW' else f"<div class='tag-lw'>{x}</div>")
        df_show['Dir Tag'] = df_show['Dir'].apply(lambda x: f"<span class='tag-dir-in'>{x}</span>" if x == '↙' else f"<span class='tag-dir-out'>{x}</span>")
        
        df_show['Slack CL'] = df_show['Slack CL'].apply(lambda x: f"<b>{x}</b>")
        df_show['Slack CM'] = df_show['Slack CM'].apply(lambda x: f"<b>{x}</b>")
        
        df_show['Win Cát Lái'] = df_show.apply(lambda r: f"{format_win_str(r['B_CL'], r['Event_Datetime'])} - {format_win_str(r['E_CL'], r['Event_Datetime'])}", axis=1)
        df_show['Win CM(Lớn)'] = df_show.apply(lambda r: f"{format_win_str(r['B_CM1'], r['Event_Datetime'])} - {format_win_str(r['E_CM1'], r['Event_Datetime'])}", axis=1)
        df_show['Win CM(Nhỏ)'] = df_show.apply(lambda r: f"{format_win_str(r['B_CM2'], r['Event_Datetime'])} - {format_win_str(r['E_CM2'], r['Event_Datetime'])}", axis=1)

        tab_view_cl, tab_view_cm = st.tabs(["⚓ TRẠM CÁT LÁI", "🚢 TRẠM CÁI MÉP"])
        
        with tab_view_cl:
            disp_cl = df_show[['Date', 'Type', 'Vũng Tàu', 'Dir Tag', 'Slack CL', 'Win Cát Lái']]
            st.write(disp_cl.to_html(escape=False, index=False, classes="tide-table"), unsafe_allow_html=True)
            
        with tab_view_cm:
            disp_cm = df_show[['Date', 'Type', 'Vũng Tàu', 'Dir Tag', 'Slack CM', 'Win CM(Lớn)', 'Win CM(Nhỏ)']]
            st.write(disp_cm.to_html(escape=False, index=False, classes="tide-table"), unsafe_allow_html=True)

# ==========================================
# DISCLAIMER PHÁP LÝ CHUẨN QUỐC TẾ
# ==========================================
st.markdown("""
<div class="footer">
    <strong style="color: #555; font-size: 1.1em;">DISCLAIMER OF LIABILITY</strong><br>
    This application and its underlying algorithms were independently developed by <strong>NP44</strong>. All data, calculations, and information provided herein are for informational and reference purposes only and are strictly non-commercial. The creator (NP44) makes no warranties, expressed or implied, regarding the accuracy, adequacy, validity, reliability, or completeness of any information provided. Under no circumstance shall the creator incur any liability for any loss, damage, or legal consequence arising directly or indirectly from the reliance on or external application of this tool's outputs. Users bear full and sole responsibility for any maritime, navigational, or operational decisions made.
</div>
""", unsafe_allow_html=True)
