import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import math

# ==========================================
# CẤU HÌNH THÔNG SỐ CƠ BẢN
# ==========================================
FILE_EXCEL = '03 tram HL6-HL21-HL27 nam 2026.xlsx'

CHANNEL_DEPTHS = {'HL6': 8.8, 'HL21': 8.5, 'HL27': 8.5}
TRAVEL_TIMES = {
    'OUTBOUND': {'HL6': 0.5, 'HL21': 2.0, 'HL27': 2.5},
    'INBOUND': {'HL27': 2.0, 'HL21': 2.5, 'HL6': 4.0}
}

# ==========================================
# HÀM XỬ LÝ DỮ LIỆU CẢ NĂM (SIÊU BỀN BỈ)
# ==========================================
@st.cache_data
def load_tide_data():
    dict_data = {}
    # Sử dụng 3 chữ cái đầu để bắt lỗi sai chính tả trong Excel (ví dụ Febuary, Jan...)
    month_keys = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
                   
    for sheet in ['HL6', 'HL21', 'HL27']:
        try:
            df_raw = pd.read_excel(FILE_EXCEL, sheet_name=sheet, header=None)
        except Exception as e:
            return None

        parsed_data = []
        current_month = 0
        current_day = 0
        
        for index, row in df_raw.iterrows():
            val0 = str(row[0]).strip().lower()
            val1 = str(row[1]).strip().upper().replace(" ", "") # Bắt cả lỗi gõ cách chữ C N
            
            # Nhận diện tháng cực kỳ linh hoạt
            is_month = False
            for m_key, m_val in month_keys.items():
                if m_key in val0:
                    current_month = m_val
                    current_day = 0
                    is_month = True
                    break
            
            if is_month:
                continue
                
            # Xử lý Ngày
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
            # Chốt chặn lọc các dòng rác trùng ngày
            df_clean = df_clean.drop_duplicates(subset=['Thang', 'Ngay'], keep='first')
            df_clean = df_clean.set_index(['Thang', 'Ngay'])
            dict_data[sheet] = df_clean
        else:
            return None
            
    return dict_data

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
        # Nếu thiếu dữ liệu ngày này trong bảng, trả về None để báo lỗi
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
        # Chốt chặn chống KeyError: Chỉ lấy những ngày tồn tại ở CẢ 3 SHEET
        idx_hl6 = data_dict['HL6'].loc[thang_chon].index.tolist() if thang_chon in data_dict['HL6'].index.get_level_values(0) else []
        idx_hl21 = data_dict['HL21'].loc[thang_chon].index.tolist() if thang_chon in data_dict['HL21'].index.get_level_values(0) else []
        idx_hl27 = data_dict['HL27'].loc[thang_chon].index.tolist() if thang_chon in data_dict['HL27'].index.get_level_values(0) else []
        
        if not idx_hl6 or not idx_hl21 or not idx_hl27:
            return pd.DataFrame()
            
        ngay_hop_le = list(set(idx_hl6) & set(idx_hl21) & set(idx_hl27))
        ngay_hop_le.sort()
    except:
        return pd.DataFrame()
        
    for ngay in ngay_hop_le:
        for point in ['HL6', 'HL21', 'HL27']:
            dong = {'Ngày': ngay, 'Điểm': point}
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

def to_mau_ngay_le(row):
    ngay = row.name[0]
    if ngay % 2 != 0:
        return ['background-color: rgba(255, 215, 0, 0.15)'] * len(row)
    return [''] * len(row)

# ==========================================
# GIAO DIỆN WEB (UI) - TỐI ƯU MOBILE/TABLET
# ==========================================
st.set_page_config(page_title="Thủy Triều & Mớn Nước", layout="wide", initial_sidebar_state="collapsed")

# --- CSS Tùy chỉnh cho Giao diện Chạm (Touch-friendly) ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; padding-left: 1rem; padding-right: 1rem; }
    .stButton>button { min-height: 55px; font-size: 18px !important; font-weight: bold; border-radius: 8px; }
    .result-card { border: 1px solid #ddd; border-radius: 10px; padding: 15px; margin-bottom: 15px; background-color: #f9f9f9; }
</style>
""", unsafe_allow_html=True)

st.title("🚢 Kiểm Tra Mớn Nước Tàu")

data_dict = load_tide_data()

if data_dict is None:
    st.error(f"⚠️ Không thể xử lý file Excel '{FILE_EXCEL}'. Vui lòng kiểm tra lại tên file hoặc cấu trúc file.")
    st.stop()

tab1, tab2 = st.tabs(["🚀 ĐÁNH GIÁ POB", "📅 BẢNG MỚN TỐI ĐA"])

with tab1:
    st.markdown("### 📋 Thông tin chuyến tàu")
    col1, col2 = st.columns(2)
    with col1:
        mon_nuoc = st.number_input("Mớn nước (m)", min_value=1.0, value=10.5, step=0.1)
        ngay_pob = st.date_input("Ngày POB", value=datetime.today())
    with col2:
        huong_di = st.selectbox("Hướng di chuyển", options=["OUTBOUND", "INBOUND"])
        gio_pob = st.time_input("Giờ POB", value=datetime.strptime('08:15', '%H:%M').time())

    st.write("")
    if st.button("🚀 KIỂM TRA ĐIỀU KIỆN AN TOÀN", use_container_width=True):
        pob_time = datetime.combine(ngay_pob, gio_pob)
        st.markdown("---")
        st.markdown(f"### 📊 KẾT QUẢ: Hướng {huong_di}")
        
        thu_tu_diem = ['HL6', 'HL21', 'HL27'] if huong_di == 'OUTBOUND' else ['HL27', 'HL21', 'HL6']
        cols_ket_qua = st.columns(3)
        
        for idx, point in enumerate(thu_tu_diem):
            travel_hours = TRAVEL_TIMES[huong_di][point]
            eta = pob_time + timedelta(hours=travel_hours)
            req_depth, ukc_pct = tinh_ukc(mon_nuoc, eta)
            
            tide_height = noi_suy_thuy_trieu(data_dict[point], eta)
            
            with cols_ket_qua[idx]:
                if tide_height is None:
                    st.warning(f"### 📍 ĐIỂM {point}\n\n⚠️ **THIẾU SỐ LIỆU**")
                    st.caption(f"Không có dữ liệu thủy triều ngày {eta.strftime('%d/%m/%Y')}")
                else:
                    actual_depth = CHANNEL_DEPTHS[point] + tide_height
                    if actual_depth >= req_depth:
                        st.success(f"### 📍 ĐIỂM {point}\n\n✅ **LỌT (AN TOÀN)**")
                    else:
                        st.error(f"### 📍 ĐIỂM {point}\n\n❌ **CẠN (NGUY HIỂM)**")
                    
                    st.write(f"🕒 **ETA:** {eta.strftime('%H:%M %d/%m')}")
                    st.write(f"📏 **Yêu cầu (UKC {int(ukc_pct*100)}%):** {req_depth:.2f} m")
                    st.write(f"🌊 **Thực tế:** {actual_depth:.2f} m")
                    st.caption(f"(Luồng {CHANNEL_DEPTHS[point]}m + Triều {tide_height}m)")
with tab2:
    st.markdown("### 🌊 Tra cứu bảng Mớn tối đa")
    st.caption("UKC: Ban ngày (06h-17h) 7%, Ban đêm 10%. (Cuộn ngang để xem hết giờ).")
    
    col_thang, _ = st.columns([1, 3])
    with col_thang:
        thang_chon = st.selectbox("📅 Chọn Tháng hiển thị:", list(range(1, 13)), index=datetime.today().month - 1)
    
    bang_tong_hop = tao_bang_mon_nuoc_toi_da(data_dict, thang_chon)
    
    if not bang_tong_hop.empty:
        bang_co_mau = bang_tong_hop.style.apply(to_mau_ngay_le, axis=1)
        st.dataframe(bang_co_mau, use_container_width=True, height=500)
        
        csv = bang_tong_hop.to_csv(encoding='utf-8-sig')
        st.download_button(
            label=f"📥 Tải Bảng Tháng {thang_chon} (CSV)",
            data=csv,
            file_name=f'Mon_Nuoc_Toi_Da_Thang_{thang_chon}.csv',
            mime='text/csv',
            use_container_width=True
        )
    else:
        st.warning(f"Dữ liệu Tháng {thang_chon} bị thiếu ở một hoặc nhiều trạm. Vui lòng kiểm tra lại file Excel.")