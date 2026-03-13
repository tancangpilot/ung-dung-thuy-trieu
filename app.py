import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time, timezone
import math

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
        "Cát Lái - Soài Rạp (Bờ Băng) - P0 SR (H25)": {'BB': 1.0, 'VL': 2.0},
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

def calc_safe_th(amp):
    if amp <= 0: return 3.0
    r1 = amp / 12.0
    r2 = 2.0 * amp / 12.0
    r3 = 3.0 * amp / 12.0
    limit = 0.4
    if r1 > limit: return limit / r1
    elif r2 > limit: return 1.0 + (limit - r1) / (r2 - r1)
    elif r3 > limit: return 2.0 + (limit - r2) / (r3 - r2)
    else: return 3.0 

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

@st.cache_data
def load_extremes_data():
    try:
        sheet_n = 'HLW-VT' if 'HLW-VT' in pd.ExcelFile(FILE_EXCEL).sheet_names else 'HW_LW_VT'
        df = pd.read_excel(FILE_EXCEL, sheet_name=sheet_n, header=None)
        def parse_date(x):
            x_str = str(x).strip()
            if x_str.startswith(f'{NAM_DU_LIEU}-'):
                try: return datetime.strptime(x_str[:10], '%Y-%m-%d').date()
                except: return None
            return None
        df['RealDate'] = df[0].apply(parse_date)
        is_blank = df[1].isna() | (df[1].astype(str).str.strip() == '')
        df['Block'] = is_blank.cumsum()
        df['RealDate'] = df.groupby('Block')['RealDate'].transform(lambda x: x.bfill().ffill())
        df_valid = df[~is_blank].dropna(subset=['RealDate', 1, 2])
        extremes = []
        for _, row in df_valid.iterrows():
            try:
                d_obj = row['RealDate']
                gio_val = row[1]
                muc_nuoc = float(row[2])
                if isinstance(gio_val, time): h, m = gio_val.hour, gio_val.minute
                else: h, m = map(int, str(gio_val).strip().split(':'))
                dt = datetime.combine(d_obj, time(h, m))
                extremes.append({'dt': dt, 'level': muc_nuoc})
            except: continue
        extremes = sorted(extremes, key=lambda x: x['dt'])
        for i in range(len(extremes)):
            if i == 0: extremes[i]['type'] = 'HW' if extremes[i]['level'] > extremes[i+1]['level'] else 'LW'
            elif i == len(extremes) - 1: extremes[i]['type'] = 'HW' if extremes[i]['level'] > extremes[i-1]['level'] else 'LW'
            else: extremes[i]['type'] = 'HW' if extremes[i]['level'] > extremes[i-1]['level'] else 'LW'
        return extremes
    except Exception as e:
        return None

# ==========================================
# KHỞI TẠO AI CHATBOT (CHUẨN ĐỊA LÝ & YÊU CẦU NGẮN GỌN)
# ==========================================
@st.cache_resource
def get_ai_bot(_extremes_list, api_key):
    genai.configure(api_key=api_key)
    
    almanac_str = "\n".join([f"- {e['dt'].strftime('%d/%m/%Y %H:%M')} | {e['type']} | {e['level']:.1f}m" for e in _extremes_list]) if _extremes_list else "Không có dữ liệu triều."

    system_instruction = f"""
    Bạn là Trợ lý AI Hoa Tiêu Hàng Hải (Tân Cảng Pilot). Bạn là người ra quyết định chuyên nghiệp.
    
    ĐỊNH NGHĨA TUYẾN LUỒNG & CHOKEPOINT (TUYỆT ĐỐI TUÂN THỦ KHÔNG ĐƯỢC NHẦM LẪN):
    1. ĐI VÀO (INBOUND):
       - "P0 Vũng Tàu - Lòng Tàu - Cát Lái": Qua Dần Xây/HL27 (sau 2h), L'est/HL21 (sau 2.5h), Đèn Đỏ/HL6 (sau 4h). Tuyệt đối KHÔNG liên quan đến Hiệp Phước.
       - "P0 SR (H25) - Soài Rạp - TC Hiệp Phước": Qua Vàm Láng/VL (sau 1.5h), TC Hiệp Phước/TCHP (sau 3h).
    2. ĐI RA (OUTBOUND):
       - "Cát Lái - Lòng Tàu - P0 Vũng Tàu": Qua HL6 (sau 0.5h), HL21 (sau 2h), HL27 (sau 2.5h).
       - "Cát Lái - Soài Rạp (Bờ Băng) - P0 SR (H25)": Qua Bờ Băng/BB (sau 1h), Vàm Láng/VL (sau 2h).
       - "TC Hiệp Phước - Soài Rạp (Vàm Láng) - P0 SR (H25)": Qua TCHP (sau 0.5h), Vàm Láng/VL (sau 1.5h).

    THÔNG SỐ BẮT BUỘC:
    1. Độ sâu chuẩn: HL6 (-8.8m), HL21 (-8.5m), HL27 (-8.5m), BB (-6.7m), VL (-8.0m), TCHP (-8.0m).
    2. UKC (Khoảng sáng gầm tàu): Ngày 7%, Đêm 10%. Độ sâu yêu cầu = Mớn * (1 + UKC).
    
    CẤU TRÚC BÁO CÁO (BẮT BUỘC ĐÚNG 3 GẠCH ĐẦU DÒNG, DỨT KHOÁT NHƯ BỘ ĐÀM VHF):
    - Tuyến luồng: [Đọc đúng Tên tuyến và các điểm cạn theo định nghĩa trên].
    - Đánh giá mớn: Mớn [X]m + UKC cần độ sâu [Y]m. Đánh giá [Lọt / Cạn].
    - Chốt giờ POB: [Khung giờ an toàn đề xuất từ ... đến ...].
    
    Tuyệt đối không giải thích thuật toán, không nói luyên thuyên. 
    
    DỮ LIỆU THỦY TRIỀU VŨNG TÀU 2026:
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
            
    except Exception as e:
        chosen_model = 'gemini-1.5-flash'
        
    model = genai.GenerativeModel(chosen_model)
    return model, chosen_model, system_instruction

# ==========================================
# GIAO DIỆN WEB (UI) - KÈM HIỆU ỨNG 3D
# ==========================================
st.set_page_config(page_title="Tan Cang Pilot Tide Calculation", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    .stButton>button { min-height: 55px; font-weight: bold; border-radius: 8px; margin-top: 15px; }
    .footer { text-align: justify; color: gray; font-size: 0.85em; margin-top: 60px; border-top: 1px solid rgba(128,128,128,0.2); padding-top: 20px; }
    
    .safe-window { background-color: rgba(46, 160, 67, 0.15); border-left: 5px solid #2ea043; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    .warn-window { background-color: rgba(212, 167, 44, 0.15); border-left: 5px solid #d4a72c; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    .unsafe-window { background-color: rgba(207, 34, 46, 0.15); border-left: 5px solid #cf222e; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
    
    .tide-box { background-color: rgba(128, 128, 128, 0.05); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(128, 128, 128, 0.2); }
    .tide-table { width: 100%; text-align: center; font-size: 0.9em; border-collapse: collapse; margin-top: 10px; }
    .tide-table th { font-weight: bold; border-bottom: 1px solid rgba(128, 128, 128, 0.3); padding-bottom: 5px; opacity: 0.8; }
    .tide-table td { padding: 4px 0; border-bottom: 1px dashed rgba(128, 128, 128, 0.1); }
    
    .hw-row { background-color: rgba(0, 153, 255, 0.15); font-weight: bold; color: #0099ff; }
    .lw-row { background-color: rgba(255, 75, 75, 0.15); font-weight: bold; color: #ff4b4b; }
    
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

    /* ======== HIỆU ỨNG 3D CHO TABS ======== */
    button[data-baseweb="tab"] {
        background-color: rgba(128,128,128,0.05); 
        border: 1px solid rgba(128,128,128,0.2);
        border-bottom: 4px solid rgba(128,128,128,0.3); /* Cạnh dưới đổ bóng 3D */
        border-radius: 10px 10px 0 0;
        margin-right: 5px;
        transition: all 0.15s ease-in-out;
    }
    button[data-baseweb="tab"]:hover {
        transform: translateY(-2px); /* Nhô lên khi lướt qua */
        border-bottom: 6px solid rgba(128,128,128,0.4);
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: transparent;
        border-bottom: 0px solid transparent; /* Mất cạnh dưới tạo cảm giác lún */
        transform: translateY(4px); /* Ép nút lún xuống */
        box-shadow: inset 0 3px 6px rgba(0,0,0,0.1); /* Đổ bóng chìm trong nút */
        border-top: 3px solid #ff4b4b; /* Viền đỏ nổi bật khi được chọn */
    }
    @media (prefers-color-scheme: dark) {
        button[data-baseweb="tab"][aria-selected="true"] {
            box-shadow: inset 0 3px 6px rgba(0,0,0,0.5);
        }
    }
</style>
""", unsafe_allow_html=True)

st.title("🚢 TAN CANG PILOT TIDE CALCULATION")

st.markdown("""
<div style="font-size: 0.65em; margin-bottom: 20px; padding: 10px; background-color: rgba(128,128,128,0.1); border-radius: 5px; opacity: 0.9;">
    UKC: Ban ngày (06h-17h) 7%, Ban đêm 10%. &nbsp;|&nbsp; 
    Đèn Đỏ (HL6)=<strong style="color: #ff4b4b;">-8.8m</strong>; L'est (HL21)=<strong style="color: #ff4b4b;">-8.5m</strong>; Dần Xây (HL27)=<strong style="color: #ff4b4b;">-8.5m</strong>; 
    Bờ Băng (BB)=<strong style="color: #ff4b4b;">-6.7m</strong>; Vàm Láng (VL)=<strong style="color: #ff4b4b;">-8.0m</strong>; TCHP=<strong style="color: #ff4b4b;">-8.0m</strong>.
</div>
""", unsafe_allow_html=True)

data_dict = load_tide_data()
extremes_data = load_extremes_data()

if data_dict is None:
    st.error(f"⚠️ Thiếu file {FILE_EXCEL}!"); st.stop()

# ĐÃ ĐỔI LẠI THỨ TỰ TABS THEO ĐÚNG YÊU CẦU MỚI
tab_pob_draft, tab_ai, tab_draft_pob, tab_max_draft = st.tabs([
    "🚀 POB and Draft", 
    "🤖 Trợ lý AI", 
    "⏱️ Draft for POB", 
    "📅 Max Draft Table"
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
        
        st.markdown("""
        <div style="background-color: rgba(0, 153, 255, 0.1); padding: 15px; border-radius: 8px; border-left: 4px solid #0099ff; margin-bottom: 20px;">
            <strong>💡 MẪU CÂU HỎI NHANH:</strong><br>
            <i>Hãy gõ câu hỏi theo ý bạn, AI sẽ tính toán ngay lập tức:</i>
            <ul style="margin-top: 5px; margin-bottom: 0px;">
                <li>"Tàu ETA 07:00 ngày 25/03, mớn 10.7m, đi Cát Lái. Giờ nào an toàn?"</li>
                <li>"Mớn 9.8m ngày 13/3 mấy giờ đi từ Cát Lái ra H25 được?"</li>
                <li>"Tìm giờ POB tốt nhất cho tàu mớn 11m Inbound Cát Lái ngày 2/5."</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        if "chat_session" not in st.session_state:
            with st.spinner("Đang khởi động hệ thống AI & Nạp dữ liệu thủy triều..."):
                try:
                    ai_model, model_name, sys_instruct = get_ai_bot(extremes_data, API_KEY)
                    
                    st.session_state.chat_session = ai_model.start_chat(history=[
                        {"role": "user", "parts": [sys_instruct]},
                        {"role": "model", "parts": ["Đã rõ thưa Thuyền trưởng. Tôi đã nạp bản đồ luồng tuyến chuẩn xác và sẽ báo cáo kết quả theo đúng 3 ý yêu cầu, không phân tích rườm rà. Xin chờ lệnh!"]}
                    ])
                except Exception as e:
                    st.error(f"Lỗi khởi tạo AI: {e}")

        if "chat_session" in st.session_state:
            for message in st.session_state.chat_session.history[2:]:
                role = "user" if message.role == "user" else "assistant"
                with st.chat_message(role):
                    st.markdown(message.parts[0].text)

            if user_prompt := st.chat_input("Nhập yêu cầu điều động tàu tại đây..."):
                with st.chat_message("user"):
                    st.markdown(user_prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("Đang tra cứu thủy triều và tính toán..."):
                        try:
                            response = st.session_state.chat_session.send_message(user_prompt)
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"⚠️ Đã có lỗi xảy ra: {e}")

# ----------------- TAB 3: DRAFT FOR POB -----------------
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

        local_windows = []
        if extremes_data and len(extremes_data) >= 3:
            if huong_di_t3 == "ĐI VÀO (INBOUND)":
                for i in range(1, len(extremes_data) - 1):
                    prev_ex, curr_ex, next_ex = extremes_data[i-1], extremes_data[i], extremes_data[i+1]
                    
                    amp_before = abs(curr_ex['level'] - prev_ex['level'])
                    amp_after = abs(next_ex['level'] - curr_ex['level'])
                    th_before = (curr_ex['dt'] - prev_ex['dt']).total_seconds() / 60 / 6
                    th_after = (next_ex['dt'] - curr_ex['dt']).total_seconds() / 60 / 6
                    
                    if amp_before <= 1.0: start_dt = prev_ex['dt']
                    else: start_dt = curr_ex['dt'] - timedelta(minutes=2.5 * th_before)
                    
                    if amp_after <= 1.0: end_dt = next_ex['dt']
                    elif amp_after <= 1.5: end_dt = curr_ex['dt'] + timedelta(minutes=0.5 * th_after)
                    else: end_dt = curr_ex['dt']
                    
                    local_windows.append({
                        'type': curr_ex['type'],
                        'arrow': '↙' if curr_ex['type'] == 'HW' else '↗',
                        'desc': 'HW' if curr_ex['type'] == 'HW' else 'LW',
                        'dt': curr_ex['dt'],
                        'start': start_dt,
                        'end': end_dt
                    })
            else:
                local_extremes = []
                for ex in extremes_data:
                    lag = timedelta(hours=LAG_HIEPPHUOC_HOURS)
                    if "Cát Lái" in tuyen_luong_t3:
                        if ex['type'] == 'HW':
                            lag = timedelta(hours=3, minutes=5)
                        else:
                            lvl = ex['level']
                            if lvl >= 1.5: lag = timedelta(hours=3, minutes=30)
                            elif 1.0 <= lvl < 1.5: lag = timedelta(hours=3, minutes=35)
                            elif 0.5 <= lvl < 1.0: lag = timedelta(hours=3, minutes=40)
                            else: lag = timedelta(hours=3, minutes=45)
                    local_ex = ex.copy()
                    local_ex['dt'] = ex['dt'] + lag
                    local_ex['desc'] = 'Tdown' if ex['type'] == 'HW' else 'Tup'
                    local_ex['arrow'] = '↙' if ex['type'] == 'HW' else '↗'
                    local_extremes.append(local_ex)
                
                for i in range(1, len(local_extremes) - 1):
                    prev_ex, curr_ex, next_ex = local_extremes[i-1], local_extremes[i], local_extremes[i+1]
                    
                    amp_before = abs(curr_ex['level'] - prev_ex['level'])
                    amp_after = abs(next_ex['level'] - curr_ex['level'])
                    th_before = (curr_ex['dt'] - prev_ex['dt']).total_seconds() / 60 / 6
                    th_after = (next_ex['dt'] - curr_ex['dt']).total_seconds() / 60 / 6
                    
                    safe_prev_th = calc_safe_th(amp_before)
                    safe_next_th = calc_safe_th(amp_after)
                    
                    start_dt = curr_ex['dt'] - timedelta(minutes=safe_prev_th * th_before)
                    end_dt = curr_ex['dt'] + timedelta(minutes=safe_next_th * th_after)
                    
                    local_windows.append({
                        'type': curr_ex['type'],
                        'arrow': curr_ex['arrow'],
                        'desc': curr_ex['desc'],
                        'dt': curr_ex['dt'],
                        'start': start_dt,
                        'end': end_dt
                    })

        ket_qua = []
        khung_gio_hoan_hao = []
        dang_trong_khung = False
        gio_bat_dau = None
        
        for h in range(24):
            for m in [0, 30]:
                thoi_gian_xet = time(h, m)
                pob_t = datetime.combine(ngay_pob_t3, thoi_gian_xet)
                
                if pob_t < rounded_now:
                    continue
                
                is_safe = True
                ly_do = ""
                min_clearance = 999
                
                for p, travel_h in pts.items():
                    if p not in data_dict:
                        is_safe, ly_do = False, f"Thiếu dữ liệu trạm {p}"; break
                        
                    eta = pob_t + timedelta(hours=travel_h)
                    req, _ = tinh_ukc(mon_nuoc_t3, eta)
                    tide_h = noi_suy_thuy_trieu(data_dict[p], eta)

                    if tide_h is None:
                        is_safe, ly_do = False, f"Vượt quá ngày DL Triều"; break

                    act = lam_tron_hang_hai(CHANNEL_DEPTHS[p] + tide_h)
                    clearance = round(act - req, 1)

                    if clearance < 0:
                        is_safe = False
                        if clearance < min_clearance:
                            min_clearance, ly_do = clearance, f"Cạn tại {p} (Thiếu {-clearance:.1f}m)"
                            
                is_in_window = False
                window_note = "N/A"
                if local_windows:
                    for w in local_windows:
                        if w['start'] <= pob_t <= w['end']:
                            is_in_window = True
                            window_note = f"{w['arrow']} Dòng chùng sát {w['desc']} ({w['dt'].strftime('%H:%M')})"
                            break
                    if not is_in_window:
                        window_note = "Ngoài Window (Dòng xiết)"

                if is_safe:
                    if local_windows:
                        if is_in_window:
                            ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "✅ LỌT & WINDOW", "Ghi chú": window_note})
                            if not dang_trong_khung: gio_bat_dau, dang_trong_khung = thoi_gian_xet.strftime('%H:%M'), True
                        else:
                            ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "⚠️ LỌT (NƯỚC XIẾT)", "Ghi chú": window_note})
                            if dang_trong_khung:
                                gio_ket_thuc = (pob_t - timedelta(minutes=30)).strftime('%H:%M')
                                khung_gio_hoan_hao.append(f"{gio_bat_dau} đến {gio_ket_thuc}")
                                dang_trong_khung = False
                    else:
                        ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "✅ AN TOÀN", "Ghi chú": "Lọt (Chưa bật Window)"})
                        if not dang_trong_khung: gio_bat_dau, dang_trong_khung = thoi_gian_xet.strftime('%H:%M'), True
                else:
                    ket_qua.append({"Giờ POB": thoi_gian_xet.strftime('%H:%M'), "Trạng thái": "❌ CẠN", "Ghi chú": ly_do})
                    if dang_trong_khung:
                        gio_ket_thuc = (pob_t - timedelta(minutes=30)).strftime('%H:%M')
                        khung_gio_hoan_hao.append(f"{gio_bat_dau} đến {gio_ket_thuc}")
                        dang_trong_khung = False
        
        if dang_trong_khung: khung_gio_hoan_hao.append(f"{gio_bat_dau} đến 23:30")

        if len(khung_gio_hoan_hao) > 0:
            st.markdown(f"<div class='safe-window'><strong>🎯 KẾT LUẬN (CỬA SỔ VÀNG):</strong> Tàu có thể POB vừa đủ UKC vừa dòng chảy êm trong khoảng:<br><h3>" + " <br> ".join([f"🕒 {k}" for k in khung_gio_hoan_hao]) + "</h3></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='unsafe-window'><strong>⚠️ KẾT LUẬN:</strong> Không có bất kỳ khung giờ nào hợp lệ đáp ứng đủ mớn nước HOẶC window time!</div>", unsafe_allow_html=True)

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
        else:
            st.info("Không có mốc thời gian nào để hiển thị (đã qua hết giờ trong ngày).")

    if extremes_data:
        st.markdown("---")
        col_y, col_t, col_tm = st.columns(3)
        dates_to_show = [ngay_pob_t3 - timedelta(days=1), ngay_pob_t3, ngay_pob_t3 + timedelta(days=1)]
        headers = ["Yesterday", "Today", "Tomorrow"]
        cols_ui = [col_y, col_t, col_tm]

        for i, d in enumerate(dates_to_show):
            with cols_ui[i]:
                day_ex = [e for e in extremes_data if e['dt'].date() == d]
                st.markdown(f"<div class='tide-box'><strong>{headers[i]} ({d.strftime('%d/%m')})</strong><br>", unsafe_allow_html=True)
                if day_ex:
                    html_table = "<table class='tide-table'><tr><th>Phân loại</th><th>Vũng Tàu</th><th>Độ cao</th><th>Cát Lái</th><th>Mũi tên</th></tr>"
                    for e in day_ex:
                        if e['type'] == 'HW':
                            lag = timedelta(hours=3, minutes=5)
                            arrow = "↙"
                            row_class = "hw-row"
                        else:
                            lvl = e['level']
                            if lvl >= 1.5: lag = timedelta(hours=3, minutes=30)
                            elif 1.0 <= lvl < 1.5: lag = timedelta(hours=3, minutes=35)
                            elif 0.5 <= lvl < 1.0: lag = timedelta(hours=3, minutes=40)
                            else: lag = timedelta(hours=3, minutes=45)
                            arrow = "↗"
                            row_class = "lw-row"
                            
                        if "Hiệp Phước" in tuyen_luong_t3:
                            lag = timedelta(hours=LAG_HIEPPHUOC_HOURS)
                            
                        vt_time = e['dt'].strftime('%H:%M')
                        cl_time = (e['dt'] + lag).strftime('%H:%M')
                        
                        html_table += f"<tr class='{row_class}'><td><b>{e['type']}</b></td><td>{vt_time}</td><td>{e['level']:.1f}m</td><td>{cl_time}</td><td>{arrow}</td></tr>"
                    html_table += "</table>"
                    st.markdown(html_table, unsafe_allow_html=True)
                else:
                    st.write("Không có dữ liệu")
                st.markdown("</div>", unsafe_allow_html=True)

# ----------------- TAB 4: MAX DRAFT TABLE -----------------
with tab_max_draft:
    bay_gio_t2 = get_vn_time()
    col_th, col_ck, col_tu = st.columns([1, 1, 2])
    with col_th: 
        thang_ch = st.selectbox("Tháng", list(range(1, 13)), bay_gio_t2.month - 1)
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
        
        if tu_sel:
            df_f = df_f[df_f['Điểm'].isin(tu_sel)]
        else:
            df_f = df_f[df_f['Điểm'].isin([])]

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
            st.download_button("📥 Tải Bảng (CSV)", df_f.drop(columns=['Ngay_Goc']).to_csv(index=False, encoding='utf-8-sig'), f"Tide_{thang_ch}.csv", "text/csv")
        else:
            st.info("Vui lòng chọn ít nhất một điểm để hiển thị dữ liệu.")

# ==========================================
# DISCLAIMER PHÁP LÝ CHUẨN QUỐC TẾ
# ==========================================
st.markdown("""
<div class="footer">
    <strong style="color: #555; font-size: 1.1em;">DISCLAIMER OF LIABILITY</strong><br>
    This application and its underlying algorithms were independently developed by <strong>NP44</strong>. All data, calculations, and information provided herein are for informational and reference purposes only and are strictly non-commercial. The creator (NP44) makes no warranties, expressed or implied, regarding the accuracy, adequacy, validity, reliability, or completeness of any information provided. Under no circumstance shall the creator incur any liability for any loss, damage, or legal consequence arising directly or indirectly from the reliance on or external application of this tool's outputs. Users bear full and sole responsibility for any maritime, navigational, or operational decisions made.
</div>
""", unsafe_allow_html=True)
