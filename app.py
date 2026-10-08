import streamlit as st
from supabase import create_client, Client
import time

# 🔑 從 Streamlit Secrets 安全讀取金鑰
SUPABASE_URL = "https://yxbjluynjjxyjkrmihyz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl4YmpsdXluamp4eWprcm1paHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTg1NzAsImV4cCI6MjEwNzAzNDU3MH0.QtslxkyN1z5gMTAgYX5HHn6kQlqNU1sXtghTSFA8vjE"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

# --- 網頁基本設定 ---
st.set_page_config(
    page_title="國立鳳山高級商工職業學校 - 畢業紀念冊個人照收集系統", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- 🎨 鳳山商工校園風自訂 CSS 樣式 ---
st.markdown("""
    <style>
    /* 引入 Google 字體 */
    @import url('https://googleapis.com');
    
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Noto Sans TC', sans-serif;
        background-color: #F8F9FA;
    }
    
    /* 頁面大標題樣式 */
    .main-title {
        color: #0F2547;
        font-size: 2.2rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 5px;
        letter-spacing: 1px;
    }
    .sub-title {
        color: #555555;
        font-size: 1.1rem;
        text-align: center;
        margin-bottom: 25px;
    }
    
    /* 校徽置中容器 */
    .logo-container {
        display: flex;
        justify-content: center;
        margin-bottom: 15px;
    }
    .logo-img {
        width: 90px;
        height: auto;
    }
    
    /* 調整 Tabs 標籤頁樣式 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        justify-content: center;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #FFFFFF;
        border: 1px solid #E0E0E0;
        border-radius: 8px 8px 0px 0px;
        padding: 10px 30px;
        color: #666666;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0F2547 !important;
        color: #FFFFFF !important;
        border-color: #0F2547 !important;
        font-weight: 700;
    }
    
    /* 🔍 核心重點：所有按鈕元件設計 */
    div.stButton > button {
        width: 100%;
        background: linear-gradient(135deg, #0F2547 0%, #1A3E70 100%);
        color: #FFFFFF !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        padding: 12px 24px !important;
        border-radius: 8px !important;
        border: none !important;
        box-shadow: 0 4px 6px rgba(15, 37, 71, 0.15);
        transition: all 0.25s ease-in-out !important;
    }
    /* 按鈕滑鼠懸停效果 */
    div.stButton > button:hover {
        background: linear-gradient(135deg, #1A3E70 0%, #245699 100%);
        box-shadow: 0 6px 12px rgba(15, 37, 71, 0.25);
        transform: translateY(-1px);
        color: #D4AF37 !important; /* 懸停時字體微調為金色 */
    }
    /* 按鈕點擊效果 */
    div.stButton > button:active {
        transform: translateY(1px);
        box-shadow: 0 2px 4px rgba(15, 37, 71, 0.15);
    }
    
    /* 區塊卡片化設計 */
    .css-1r6slb0, [data-testid="stVerticalBlock"] > div {
        background-color: #FFFFFF;
        padding: 5px;
        border-radius: 10px;
    }
    
    /* 輸入框外框聚焦顏色 */
    input:focus {
        border-color: #0F2547 !important;
        box-shadow: 0 0 0 1px #0F2547 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 🏛️ 鳳山商工校徽與極正式標題 ---
st.markdown("""
    <div class="logo-container">
     st.image("https://wikimedia.org", width=90)
    </div>
    <div class="main-title">國立鳳山高級商工職業學校</div>
    <div class="sub-title">116級 國三一 畢業紀念冊個人寫真照片收集系統</div>
""", unsafe_allow_html=True)






# 建立分頁
tab1, tab2 = st.tabs(["📷 我要上傳照片", "🔍 確認我的上傳狀態"])

# --- 上傳功能 ---
with tab1:
    st.markdown("<h4 style='color: #0F2547; font-weight: 600; margin-bottom: 15px;'>照片檔案上傳</h4>", unsafe_allow_html=True)
    
    upload_password = st.text_input("請輸入您的專屬密碼：", type="password", key="pwd_upload", help="請輸入系統發放的個人密碼")
    uploaded_files = st.file_uploader("請選擇要上傳的照片（可多選，支援 JPG、PNG、WEBP）：", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)

    if st.button("確認送出上傳", key="btn_upload"):
        if not upload_password:
            st.error("請先輸入您的專屬密碼！")
        elif not uploaded_files:
            st.error("請至少選擇一張照片！")
        else:
            with st.spinner("系統正在處理上傳照片，請稍候..."):
                try:
                    response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                    raw_data = response.data
                    if not raw_data:
                        st.error("密碼驗證失敗，拒絕上傳。")
                    else:
                        student = raw_data[0] # 確保精準讀取學生資料
                        seat_no = student["seat_no"]
                        name = student["name"]
                        
                        success_count = 0
                        for idx, file in enumerate(uploaded_files):
                            file_ext = file.name.split(".")[-1]
                            # 自動變更檔名：座號_序號_時間戳記.副檔名
                            new_filename = f"{seat_no}_{idx}_{int(time.time())}.{file_ext}"
                            try:
                                supabase.storage.from_("photos").upload(
                                    path=new_filename,
                                    file=file.read(),
                                    file_options={"content-type": file.type}
                                )
                                success_count += 1
                            except Exception as e:
                                st.error(f"{file.name} 上傳失敗: {str(e)}")
                                
                        if success_count > 0:
                            # ✨【完美排版】與 tab2 風格一致，只留座號、姓名與成功張數，且沒有任何不舒服的右上角彈出通知
                            st.success(f"🎉 上傳成功｜座號：{seat_no} 號 — {name} 同學，已成功匯入 {success_count} 張相片！")
                except Exception as db_err:
                    st.error(f"系統連線異常，請洽系統管理員: {str(db_err)}")


# --- 查詢功能 ---
# --- 查詢功能 ---
# --- 查詢功能 ---
with tab2:
    st.markdown("<h4 style='color: #0F2547; font-weight: 600; margin-bottom: 15px;'>個人相片查詢台</h4>", unsafe_allow_html=True)
    st.info("為了保護學生個人隱私，預設畫面為空白。請在下方輸入您的專屬密碼以解鎖照片。")
    
    query_password = st.text_input("請輸入您的專屬密碼解鎖：", type="password", key="pwd_query")
    
    if "is_unlocked" not in st.session_state:
        st.session_state["is_unlocked"] = False
        
    if st.button("解鎖我的照片", key="btn_query") or st.session_state["is_unlocked"]:
        if not query_password:
            st.error("請輸入解鎖密碼！")
        else:
            with st.spinner("正在安全驗證並讀取照片中..."):
                try:
                    response = supabase.table("grad_album").select("*").eq("password", query_password).execute()
                    raw_data = response.data
                    if not raw_data:
                        st.error("密碼驗證錯誤，無法讀取資料。")
                        st.session_state["is_unlocked"] = False
                    else:
                        st.session_state["is_unlocked"] = True
                        student = raw_data[0]  # 確保讀取陣列第一筆
                        seat_no = student["seat_no"]
                        name = student["name"]
                        
                        # ✨ 【完美排版】刪除多餘大字，將通知與提示框完美合併，只留座號與姓名
                        st.success(f"🔓 驗證通過｜座號：{seat_no} 號 — {name} 同學，以下為您已上傳的照片：")
                        
                        # 從雲端儲存空間撈取該學生照片
                        storage_files = supabase.storage.from_("photos").list(path="", options={"limit": 500})
                        
                        my_photos_urls = [
                            supabase.storage.from_("photos").get_public_url(f["name"])
                            for f in storage_files if f["name"].startswith(f"{seat_no}_")
                        ]
                        
                        if not my_photos_urls:
                            st.warning("您目前在此系統中尚未有任何照片紀錄。")
                        else:
                            # 📷 照片格子
                            cols = st.columns(3)
                            for idx, url in enumerate(my_photos_urls):
                                with cols[idx % 3]:
                                    st.image(url, use_container_width=True)
                except Exception as db_err:
                    st.error(f"系統連線異常，請稍後再試: {str(db_err)}")
