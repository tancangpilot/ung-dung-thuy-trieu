import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import math

# ==========================================
# CẤU HÌNH THÔNG SỐ CƠ BẢN
# ==========================================
FILE_EXCEL = '06 tram HL6-HL21-HL27-BB-TCHP-VL nam 2026.xlsx'
NAM_DU_LIEU = 2026

CHANNEL_DEPTHS = {
    'HL6': 8.8, 'HL21': 8.5, 'HL27': 8.5,
    'VL': 8.0, 'TCHP': 8.0, 'BB': 6.7
}

ROUTES = {
    "ĐI VÀO (INBOUND)": {
        "INbound 01 P0VT – LÒNG TÀU – CÁT LÁI": {'HL27': 2.0, 'HL21': 2.5, 'HL6': 4.0},
        "INbound 02 P0SR – SOÀI RẠP – TC HIỆP PHƯỚC": {'VL': 1.5, 'TCHP': 3.0}
    },
    "ĐI RA (OUTBOUND)": {
        "OUTbound 01 CÁT LÁI – LÒNG TÀU – P0VT": {'HL6': 0.5, 'HL21': 2.0, 'HL27': 2.5},
        "OUTbound 02 CÁT LÁI – SOÀI RẠP – P0SR": {'BB': 1.0, 'VL': 2.0},
        "OUTbound 03 TC HIỆP PHƯỚC – SOÀI RẠP – P0SR": {'TCHP': 0.5, 'VL': 1.5}
    }
}

# ==========================================
# HÀM XỬ LÝ DỮ LIỆU CẢ NĂM
# ==========================================
@st.cache_data
def load_tide_data():
    dict_data = {}
    month_keys = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                  'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
    try:
        for sheet in list(CHANNEL_DEPTHS.keys()):
            df_raw = pd.read_excel(FILE_EXCEL, sheet_name=sheet, header=None)
            parsed_data = []
            current_month = 0
            current_day = 0
            for index, row in df_raw.iterrows():
                val0 = str(row[0]).strip().lower()
                val1 = str(row[1]).strip().upper().replace(" ", "")
                is_month = False
                for m_key, m_val in month_keys.items():
                    if m_key in val0:
                        current_month, current_day, is_month = m_val, 0, True
                        break
                if is_month: continue
                if current_month > 0:
                    if val1 == 'CN': current_day += 1
                    else:
                        try: current_day = int(float(val1))
                        except: continue
                    hours_data = row[2:26].values
                    if len(hours_data) == 24:
                        hours_f = pd.to_numeric(hours_data, errors='coerce')
                        if pd.Series(hours_f).notna().sum() > 12:
                            row_dict = {'Thang': current_month, 'Ngay': current_day}
                            for h in range(24): row_dict[h] = hours_f[h]
                            parsed_data.append(row_dict)
            df_clean = pd.DataFrame(parsed_data)
            if not df_clean.empty:
                dict_data[sheet] = df_clean.drop_duplicates(subset=['Thang', 'Ngay']).set_index(['Thang', 'Ngay'])
    except: return None
    return dict_data if len(dict_data) > 0 else None

def tinh_ukc(draft, eta_time):
    t = eta_time.time()
    pct = 0.07 if datetime.strptime('05:01','%H:%M').time() <= t <= datetime.strptime('17:59','%H:%M').time() else 0.10
    return draft * (1 + pct), pct

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
        return round(v1 + ((v2 - v1) * (mi / 60)), 2)
    except: return None

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
                    mon = math.ceil(((CHANNEL_DEPTHS[point] + muc) / (1 + ukc)) * 10) / 10
                    dong[f'{gio}h'] = f"{mon:.1f}"
                danh_sach_dong.append(dong)
    except: return pd.DataFrame()
    return pd.DataFrame(danh_sach_dong)

# ==========================================
# GIAO DIỆN WEB (UI)
# ==========================================
st.set_page_config(page_title="Thủy Triều & Mớn Nước", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    .stButton>button { min-height: 55px; font-weight: bold; border-radius: 8px; }
    .footer { text-align: justify; color: #888; font-size: 0.85em; margin-top: 60px; border-top: 1px solid #eaeaea; padding-top: 20px; }
</style>
""", unsafe_allow_html=True)

st.title("🚢 Kiểm Tra Mớn Nước Tàu - Hệ thống Tuyến Luồng")

data_dict = load_tide_data()
if data_dict is None:
    st.error(f"⚠️ Thiếu file {FILE_EXCEL}!"); st.stop()

tab1, tab2 = st.tabs(["🚀 ĐÁNH GIÁ POB", "📅 BẢNG MỚN TỐI ĐA"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        mon_nuoc = st.number_input("Mớn nước (m)", 1.0, 20.0, 10.5, 0.1)
        ngay_pob = st.date_input("Ngày POB", datetime.today(), format="DD/MM/YYYY")
        gio_pob = st.time_input("Giờ POB", datetime.strptime('08:30', '%H:%M').time())
    with col2:
        huong_di = st.selectbox("Hướng di chuyển", ["ĐI VÀO (INBOUND)", "ĐI RA (OUTBOUND)"])
        tuyen_luong = st.selectbox("Tuyến luồng (Route)", list(ROUTES[huong_di].keys()))

    if st.button("🚀 KIỂM TRA ĐIỀU KIỆN AN TOÀN", use_container_width=True):
        pob_t = datetime.combine(ngay_pob, gio_pob)
        st.markdown(f"### 📊 KẾT QUẢ: {tuyen_luong}")
        pts = ROUTES[huong_di][tuyen_luong]
        cols = st.columns(len(pts))
        for i, (p, h) in enumerate(pts.items()):
            eta = pob_t + timedelta(hours=h)
            req, ukc_pct = tinh_ukc(mon_nuoc, eta)
            with cols[i]:
                t_h = noi_suy_thuy_trieu(data_dict[p], eta)
                if t_h is not None:
                    act = CHANNEL_DEPTHS[p] + t_h
                    if act >= req: st.success(f"📍 {p}: ✅ LỌT")
                    else: st.error(f"📍 {p}: ❌ CẠN")
                    st.write(f"🕒 ETA: {eta.strftime('%H:%M %d/%b/%Y')}")
                    st.write(f"📏 Yêu cầu: {req:.2f}m | 🌊 Thực tế: {act:.2f}m")
                    st.caption(f"(Luồng {CHANNEL_DEPTHS[p]}m + Triều {t_h}m)")

with tab2:
    st.markdown("""
    <div style="font-size: 0.95em; color: #555; margin-bottom: 10px; padding: 10px; background-color: #f0f2f6; border-radius: 5px;">
        UKC: Ban ngày (06h-17h) 7%, Ban đêm 10%. &nbsp;|&nbsp;
        Đèn Đỏ (HL6)=<strong style="color: #ff0000;">-8.8m</strong>; Cout de L’est (HL21)=<strong style="color: #ff0000;">-8.5m</strong>; Dần Xây (HL27)=<strong style="color: #ff0000;">-8.5m</strong>; 
        Bờ Băng (BB)=<strong style="color: #ff0000;">-6.7m</strong>; Vàm Láng (VL)=<strong style="color: #ff0000;">-8.0m</strong>; Hạ Lưu TCHP(TCHP)=<strong style="color: #ff0000;">-8.0m</strong>.
    </div>
    """, unsafe_allow_html=True)
    
    bay_gio = datetime.now()
    
    # SẮP XẾP LẠI: Nút hiện ngày cũ nằm cạnh ô chọn Tháng
    col_th, col_ck, col_tu = st.columns([1, 1, 2])
    with col_th:
        thang_ch = st.selectbox("📅 Tháng", list(range(1, 13)), bay_gio.month - 1)
    with col_ck:
        st.write("") # Tạo khoảng cách để checkbox thẳng hàng với selectbox
        show_old = st.checkbox("Hiện ngày đã qua", value=False)
    with col_tu:
        tu_sel = st.selectbox("🔍 Lọc bảng theo Tuyến:", ["1. Hiển thị tất cả 6 điểm cạn", "2. P0VT – LÒNG TÀU – CÁT LÁI", "3. P0SR – SOÀI RẠP – TC HIỆP PHƯỚC", "4. CÁT LÁI – SOÀI RẠP – P0SR"])

    bang_raw = tao_bang_mon_nuoc_toi_da(data_dict, thang_ch)
    
    if not bang_raw.empty:
        df_f = bang_raw.copy()
        
        # 1. Lọc ngày hiện tại (Chỉ áp dụng khi xem tháng hiện tại và KHÔNG tích checkbox)
        if thang_ch == bay_gio.month and not show_old:
            df_f = df_f[df_f['Ngay_Goc'] >= bay_gio.day]

        # 2. Lọc theo Tuyến luồng (Thực hiện sau khi lọc ngày)
        if tu_sel == "2. P0VT – LÒNG TÀU – CÁT LÁI":
            df_f = df_f[df_f['Điểm'].isin(['HL27','HL21','HL6'])]
        elif tu_sel == "3. P0SR – SOÀI RẠP – TC HIỆP PHƯỚC":
            df_f = df_f[df_f['Điểm'].isin(['VL','TCHP'])]
        elif tu_sel == "4. CÁT LÁI – SOÀI RẠP – P0SR":
            df_f = df_f[df_f['Điểm'].isin(['BB','VL'])]

        # Xử lý gộp ô (Merge cells visual)
        ngay_list = df_f['Ngày'].tolist()
        new_ngay = []
        last_d, h_char, global_cnt = None, '\u200b', 1
        for d in ngay_list:
            if d != last_d: 
                new_ngay.append(d)
                last_d = d
            else: 
                new_ngay.append(h_char * global_cnt)
                global_cnt += 1
        
        df_f['Ngày'] = new_ngay
        df_disp = df_f.drop(columns=['Ngay_Goc']).set_index(['Ngày', 'Điểm'])

        def apply_st(df):
            stys = pd.DataFrame('', index=df.index, columns=df.columns)
            for i in range(len(df)):
                if "Sun" in ngay_list[i]:
                    stys.iloc[i, :] = 'background-color: #ffcccc; color: #b30000; font-weight: bold;'
            return stys

        def style_idx(val):
            if val in ['HL6','HL21','HL27']: return 'color: #33ccff; font-weight: bold;'
            if val in ['VL','BB','TCHP']: return 'color: #ff9933; font-weight: bold;'
            return 'font-weight: bold;'
            
        styled_df = df_disp.style.apply(apply_st, axis=None).map_index(style_idx, axis=0)
        st.dataframe(styled_df, use_container_width=True, height=600)
        
        csv = df_f.drop(columns=['Ngay_Goc']).to_csv(index=False, encoding='utf-8-sig')
        st.download_button("📥 Tải Bảng Dữ Liệu Hiện Tại (CSV)", csv, f"Tide_{thang_ch}.csv", "text/csv", use_container_width=True)
    else:
        st.warning(f"Dữ liệu Tháng {thang_ch} bị thiếu.")

# ==========================================
# DISCLAIMER PHÁP LÝ CHUẨN QUỐC TẾ
# ==========================================
st.markdown("""
<div class="footer">
    <strong style="color: #555; font-size: 1.1em;">DISCLAIMER OF LIABILITY</strong><br>
    This application and its underlying algorithms were independently developed by <strong>NP44</strong>. All data, calculations, and information provided herein are for informational and reference purposes only and are strictly non-commercial. The creator (NP44) makes no warranties, expressed or implied, regarding the accuracy, adequacy, validity, reliability, or completeness of any information provided. Under no circumstance shall the creator incur any liability for any loss, damage, or legal consequence arising directly or indirectly from the reliance on or external application of this tool's outputs. Users bear full and sole responsibility for any maritime, navigational, or operational decisions made.
</div>
""", unsafe_allow_html=True)
