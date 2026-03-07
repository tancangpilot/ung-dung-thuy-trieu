import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import math

# ==========================================
# CẤU HÌNH THÔNG SỐ CƠ BẢN
# ==========================================
FILE_EXCEL = '06 tram HL6-HL21-HL27-BB-TCHP-VL nam 2026.xlsx'
NAM_DU_LIEU = 2026

# Độ sâu luồng tại 6 điểm cạn
CHANNEL_DEPTHS = {
    'HL6': 8.8, 
    'HL21': 8.5, 
    'HL27': 8.5,
    'VL': 8.0,
    'TCHP': 8.0,
    'BB': 6.7
}

# Cấu trúc Tuyến Luồng phân chia INBOUND và OUTBOUND
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
    month_keys = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
                   
    for sheet in list(CHANNEL_DEPTHS.keys()):
        try:
            df_raw = pd.read_excel(FILE_EXCEL, sheet_name=sheet, header=None)
        except Exception as e:
            continue

        parsed_data = []
        current_month = 0
        current_day = 0
        
        for index, row in df_raw.iterrows():
            val0 = str(row[0]).strip().lower()
            val1 = str(row[1]).strip().upper().replace(" ", "")
            
            is_month = False
            for m_key, m_val in month_keys.items():
                if m_key in val0:
                    current_month = m_val
                    current_day = 0
                    is_month = True
                    break
            
            if is_month:
                continue
                
            if current_month > 0:
                if val1 == 'CN':
                    current_day += 1
                else:
                    try:
                        current_day = int(float(val1))
                    except ValueError:
                        continue 
                    
                hours_data = row[2:26].values
                if len(hours_data) == 24:
                    hours_float = pd.to_numeric(hours_data, errors='coerce')
                    if pd.Series(hours_float).notna().sum() > 12:
                        row_dict = {'Thang': current_month, 'Ngay': current_day}
                        for h in range(24):
                            row_dict[h] = hours_float[h]
                        parsed_data.append(row_dict)
                        
        df_clean = pd.DataFrame(parsed_data)
        if not df_clean.empty:
            df_clean = df_clean.drop_duplicates(subset=['Thang', 'Ngay'], keep='first')
            df_clean = df_clean.set_index(['Thang', 'Ngay'])
            dict_data[sheet] = df_clean
            
    return dict_data if len(dict_data) > 0 else None

def tinh_ukc(draft, eta_time):
    time_only = eta_time.time()
    day_start = datetime.strptime('05:01', '%H:%M').time()
    day_end = datetime.strptime('17:59', '%H:%M').time()
    ukc_percent = 0.07 if day_start <= time_only <= day_end else 0.10
    return draft + (draft * ukc_percent), ukc_percent

def noi_suy_thuy_trieu(df_tide, eta_time):
    thang = eta_time.month
    ngay = eta_time.day
    gio = eta_time.hour
    phut = eta_time.minute
    
    try:
        if (thang, ngay) not in df_tide.index:
            return None
            
        muc_hien_tai = df_tide.loc[(thang, ngay), gio]
        if isinstance(muc_hien_tai, pd.Series):
            muc_hien_tai = muc_hien_tai.iloc[0]
            
        if gio == 23:
            eta_sau = eta_time + timedelta(hours=1)
            thang_sau, ngay_sau, gio_sau = eta_sau.month, eta_sau.day, 0
        else:
            thang_sau, ngay_sau, gio_sau = thang, ngay, gio + 1
            
        if (thang_sau, ngay_sau) in df_tide.index:
            muc_sau = df_tide.loc[(thang_sau, ngay_sau), gio_sau]
            if isinstance(muc_sau, pd.Series):
                muc_sau = muc_sau.iloc[0]
        else:
            muc_sau = muc_hien_tai
            
        return round(muc_hien_tai + ((muc_sau - muc_hien_tai) * (phut / 60)), 2)
    except Exception as e:
        return None

@st.cache_data
def tao_bang_mon_nuoc_toi_da(data_dict, thang_chon):
    danh_sach_dong = []
    try:
        loaded_sheets = list(data_dict.keys())
        if not loaded_sheets:
            return pd.DataFrame()
            
        common_days = set()
        if thang_chon in data_dict[loaded_sheets[0]].index.get_level_values(0):
            common_days = set(data_dict[loaded_sheets[0]].loc[thang_chon].index.tolist())
            
        for sheet in loaded_sheets[1:]:
            if thang_chon in data_dict[sheet].index.get_level_values(0):
                common_days = common_days.intersection(set(data_dict[sheet].loc[thang_chon].index.tolist()))
            else:
                common_days = set()
                
        ngay_hop_le = list(common_days)
        ngay_hop_le.sort()
    except:
        return pd.DataFrame()
        
    for ngay in ngay_hop_le:
        try:
            date_obj = datetime(NAM_DU_LIEU, thang_chon, int(ngay))
            thu_ngay_str = f"{date_obj.strftime('%a')}\n{ngay}"
        except:
            thu_ngay_str = str(ngay)

        for point in list(CHANNEL_DEPTHS.keys()):
            if point not in data_dict:
                continue
                
            dong = {'Ngày': thu_ngay_str, 'Điểm': point}
            for gio in range(24):
                muc_nuoc = data_dict[point].loc[(thang_chon, ngay), gio]
                if isinstance(muc_nuoc, pd.Series):
                    muc_nuoc = muc_nuoc.iloc[0]
                    
                do_sau_thuc_te = CHANNEL_DEPTHS[point] + muc_nuoc
                ukc_pct = 0.07 if 6 <= gio <= 17 else 0.10
                
                mon_toi_da = do_sau_thuc_te / (1 + ukc_pct)
                mon_toi_da_lam_tron = math.ceil(mon_toi_da * 10) / 10
                dong[f'{gio}h'] = f"{mon_toi_da_lam_tron:.1f}"
                
            danh_sach_dong.append(dong)
            
    df_tong_hop = pd.DataFrame(danh_sach_dong)
    if not df_tong_hop.empty:
        df_tong_hop = df_tong_hop.set_index(['Ngày', 'Điểm'])
    return df_tong_hop

# ==========================================
# GIAO DIỆN WEB (UI)
# ==========================================
st.set_page_config(page_title="Thủy Triều & Mớn Nước", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; padding-left: 1rem; padding-right: 1rem; }
    .stButton>button { min-height: 55px; font-size: 18px !important; font-weight: bold; border-radius: 8px; }
    .result-card { border: 1px solid #ddd; border-radius: 10px; padding: 15px; margin-bottom: 15px; background-color: #f9f9f9; }
    .footer {
        text-align: justify;
        color: #888;
        font-size: 0.85em;
        line-height: 1.5;
        margin-top: 60px;
        padding-top: 20px;
        border-top: 1px solid #eaeaea;
    }
</style>
""", unsafe_allow_html=True)

st.title("🚢 Kiểm Tra Mớn Nước Tàu - Hệ thống Tuyến Luồng")

data_dict = load_tide_data()

if data_dict is None:
    st.error(f"⚠️ Không thể xử lý file Excel '{FILE_EXCEL}'. Vui lòng đảm bảo file đang nằm cùng thư mục với app.py.")
    st.stop()

tab1, tab2 = st.tabs(["🚀 ĐÁNH GIÁ POB", "📅 BẢNG MỚN TỐI ĐA"])

with tab1:
    st.markdown("### 📋 Thông tin chuyến tàu")
    col1, col2 = st.columns(2)
    with col1:
        mon_nuoc = st.number_input("Mớn nước (m)", min_value=1.0, value=10.5, step=0.1)
        ngay_pob = st.date_input("Ngày POB", value=datetime.today(), format="DD/MM/YYYY")
        gio_pob = st.time_input("Giờ POB", value=datetime.strptime('08:30', '%H:%M').time(), step=timedelta(minutes=30))
    with col2:
        huong_di = st.selectbox("Hướng di chuyển", ["ĐI VÀO (INBOUND)", "ĐI RA (OUTBOUND)"])
        danh_sach_tuyen = list(ROUTES[huong_di].keys())
        tuyen_luong = st.selectbox("Tuyến luồng (Route)", options=danh_sach_tuyen)

    st.write("")
    if st.button("🚀 KIỂM TRA ĐIỀU KIỆN AN TOÀN", use_container_width=True):
        pob_time = datetime.combine(ngay_pob, gio_pob)
        st.markdown("---")
        
        st.markdown(f"### 📊 KẾT QUẢ: {tuyen_luong}")
        
        diem_can_tuyen = ROUTES[huong_di][tuyen_luong]
        cols_ket_qua = st.columns(len(diem_can_tuyen))
        
        for idx, (point, travel_hours) in enumerate(diem_can_tuyen.items()):
            eta = pob_time + timedelta(hours=travel_hours)
            req_depth, ukc_pct = tinh_ukc(mon_nuoc, eta)
            
            with cols_ket_qua[idx]:
                if point not in data_dict:
                    st.warning(f"### 📍 ĐIỂM {point}\n\n⚠️ **THIẾU SỐ LIỆU**")
                    st.caption("Chưa có sheet dữ liệu cho điểm này.")
                    continue

                tide_height = noi_suy_thuy_trieu(data_dict[point], eta)
                
                if tide_height is None:
                    st.warning(f"### 📍 ĐIỂM {point}\n\n⚠️ **THIẾU SỐ LIỆU**")
                    st.caption(f"Không có dữ liệu thủy triều ngày {eta.strftime('%d/%b/%Y')}")
                else:
                    actual_depth = CHANNEL_DEPTHS[point] + tide_height
                    if actual_depth >= req_depth:
                        st.success(f"### 📍 ĐIỂM {point}\n\n✅ **LỌT (AN TOÀN)**")
                    else:
                        st.error(f"### 📍 ĐIỂM {point}\n\n❌ **CẠN (NGUY HIỂM)**")
                    
                    st.write(f"🕒 **ETA:** {eta.strftime('%H:%M %d/%b/%Y')}")
                    st.write(f"📏 **Yêu cầu (UKC {int(ukc_pct*100)}%):** {req_depth:.2f} m")
                    st.write(f"🌊 **Thực tế:** {actual_depth:.2f} m")
                    st.caption(f"(Luồng {CHANNEL_DEPTHS[point]}m + Triều {tide_height}m)")

with tab2:
    st.markdown("### 🌊 Tra cứu bảng Mớn tối đa 6 Điểm")
    
    st.markdown("""
    <div style="font-size: 0.95em; color: #555; margin-bottom: 15px; padding: 10px; background-color: #f0f2f6; border-radius: 5px;">
        UKC: Ban ngày (06h-17h) 7%, Ban đêm 10%. &nbsp;|&nbsp; 🔴 <b>Chủ Nhật (Sun)</b> <br>
        🔵 Đèn Đỏ (HL6)=<strong style="color: #ff0000;">-8.8m</strong>; 
        🔵 Cout de L’est (HL21)=<strong style="color: #ff0000;">-8.5m</strong>; 
        🔵 Dần Xây (HL27)=<strong style="color: #ff0000;">-8.5m</strong>; <br>
        🟠 Bờ Băng (BB)=<strong style="color: #ff0000;">-6.7m</strong>; 
        🟠 Vàm Láng (VL)=<strong style="color: #ff0000;">-8.0m</strong>; 
        🟠 Hạ Lưu TCHP(TCHP)=<strong style="color: #ff0000;">-8.0m</strong>.
    </div>
    """, unsafe_allow_html=True)
    
    col_thang, col_tuyen = st.columns([1, 2])
    with col_thang:
        thang_chon = st.selectbox("📅 Chọn Tháng hiển thị:", list(range(1, 13)), index=datetime.today().month - 1)
    with col_tuyen:
        danh_sach_loc_tuyen = [
            "1. Hiển thị tất cả 6 điểm cạn",
            "2. P0VT – LÒNG TÀU – CÁT LÁI",
            "3. P0SR – SOÀI RẠP – TC HIỆP PHƯỚC",
            "4. CÁT LÁI – SOÀI RẠP – P0SR"
        ]
        chon_tuyen_tab2 = st.selectbox("🔍 Lọc bảng theo Tuyến:", options=danh_sach_loc_tuyen)

    bang_tong_hop_csv = tao_bang_mon_nuoc_toi_da(data_dict, thang_chon)
    
    if not bang_tong_hop_csv.empty:
        if chon_tuyen_tab2 == "2. P0VT – LÒNG TÀU – CÁT LÁI":
            diem_can_hien_thi = ['HL27', 'HL21', 'HL6']
            df_loc = bang_tong_hop_csv[bang_tong_hop_csv.index.get_level_values('Điểm').isin(diem_can_hien_thi)]
        elif chon_tuyen_tab2 == "3. P0SR – SOÀI RẠP – TC HIỆP PHƯỚC":
            diem_can_hien_thi = ['VL', 'TCHP']
            df_loc = bang_tong_hop_csv[bang_tong_hop_csv.index.get_level_values('Điểm').isin(diem_can_hien_thi)]
        elif chon_tuyen_tab2 == "4. CÁT LÁI – SOÀI RẠP – P0SR":
            diem_can_hien_thi = ['BB', 'VL']
            df_loc = bang_tong_hop_csv[bang_tong_hop_csv.index.get_level_values('Điểm').isin(diem_can_hien_thi)]
        else:
            df_loc = bang_tong_hop_csv.copy()

        # THỦ THUẬT NÂNG CẤP TỐI THƯỢNG: Global Counter không bao giờ reset
        # Đảm bảo 100% Unique Index cho toàn bộ bảng.
        real_dates = df_loc.index.get_level_values(0).tolist()
        real_points = df_loc.index.get_level_values(1).tolist()
        
        new_level_0 = []
        new_level_1 = []
        last_d = None
        hidden_char = '\u200b'
        global_counter = 1  # Không bao giờ reset biến này!
        
        for d, p in zip(real_dates, real_points):
            # Xử lý Cột Ngày
            if d != last_d:
                disp_d = f"🔴 {d}" if "Sun" in d else d
                new_level_0.append(disp_d)
                last_d = d
            else:
                new_level_0.append(hidden_char * global_counter)
                global_counter += 1
                
            # Xử lý Cột Điểm
            if p in ['HL6', 'HL21', 'HL27']:
                new_level_1.append(f"🔵 {p}")
            elif p in ['VL', 'BB', 'TCHP']:
                new_level_1.append(f"🟠 {p}")
            else:
                new_level_1.append(p)
                
        df_display = df_loc.copy()
        df_display.index = pd.MultiIndex.from_arrays([new_level_0, new_level_1], names=['Ngày', 'Điểm'])

        def apply_styles(df):
            styles = pd.DataFrame('', index=df.index, columns=df.columns)
            for i in range(len(df)):
                if "Sun" in real_dates[i]:
                    styles.iloc[i, :] = 'background-color: rgba(255, 77, 77, 0.15); color: #ff4d4d; font-weight: bold;'
            return styles

        bang_co_mau = df_display.style.apply(apply_styles, axis=None)

        st.dataframe(bang_co_mau, use_container_width=True, height=600)
        
        csv = df_loc.to_csv(encoding='utf-8-sig')
        st.download_button(
            label=f"📥 Tải Bảng Tháng {thang_chon} (CSV)",
            data=csv,
            file_name=f'Mon_Nuoc_Toi_Da_Thang_{thang_chon}.csv',
            mime='text/csv',
            use_container_width=True
        )
    else:
        st.warning(f"Dữ liệu Tháng {thang_chon} bị thiếu. Vui lòng kiểm tra lại file Excel.")

# ==========================================
# DISCLAIMER PHÁP LÝ CHUẨN QUỐC TẾ
# ==========================================
st.markdown("""
<div class="footer">
    <strong style="color: #555; font-size: 1.1em;">DISCLAIMER OF LIABILITY</strong><br>
    This application and its underlying algorithms were independently developed by <strong>NP44</strong>. All data, calculations, and information provided herein are for informational and reference purposes only and are strictly non-commercial. The creator (NP44) makes no warranties, expressed or implied, regarding the accuracy, adequacy, validity, reliability, or completeness of any information provided. Under no circumstance shall the creator incur any liability for any loss, damage, or legal consequence arising directly or indirectly from the reliance on or external application of this tool's outputs. Users bear full and sole responsibility for any maritime, navigational, or operational decisions made.
</div>
""", unsafe_allow_html=True)
