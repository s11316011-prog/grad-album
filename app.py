import streamlit as st
from supabase import create_client, Client
import time

# 🔑 請確認以下這兩行，有沒有精準填入您在 Supabase 複製的通行證：
SUPABASE_URL = "https://supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl4YmpsdXluamp4eWprcm1paHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTg1NzAsImV4cCI6MjEwNzAuthNDU3MH0.QtslxkyN1z5gMTAgYX5HHn6kQlqNU1sXtghTSFA8vjE"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

# --- 網頁基礎設定 ---
st.set_page_config(page_title="畢業紀念冊照片收集網頁", page_icon="🎓", layout="centered")

# --- 🎯 學校風格高級 CSS 注入 ---
# 💡 提示：你可以把下面的 #1E3A8A (深藍) 和 #D97706 (金色) 改成你們學校的代表色！
st.markdown("""
    <style>
    /* 全局背景與字體優化 */
    .stApp {
        background-color: #F8FAFC;
    }
    
    /* 學校風主題大標題 */
    .school-title {
        font-size: 2.2rem !important;
        font-weight: 800 !important;
        color: #1E3A8A; /* 學校主色：學院深藍 */
        text-align: center;
        margin-bottom: 5px;
        letter-spacing: 1px;
    }
    .school-subtitle {
        font-size: 1.1rem !important;
        color: #64748B;
        text-align: center;
        margin-bottom: 25px;
    }
    
    /* 質感卡片容器 */
    .custom-card {
        background: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        border-left: 5px solid #D97706; /* 學校點綴色：榮譽金色 */
        margin-bottom: 20px;
    }
    
    /* 大按鈕美化 */
    div.stButton > button {
        background-color: #1E3A8A !important;
        color: white !important;
        border-radius: 8px !important;
        padding: 10px 24px !important;
        font-weight: 600 !important;
        border: none !important;
        width: 100% !important;
        box-shadow: 0 4px 6px rgba(30, 58, 138, 0.15) !important;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        background-color: #1D4ED8 !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 10px rgba(30, 58, 138, 0.2) !important;
    }
    
    /* 照片網格美化 */
    .photo-frame {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        border: 1px solid #E2E8F0;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 頂部橫幅 (可放校徽或校園意象) ---
st.markdown('<div class="school-title">🎓 國立華麗高級中學</div>', unsafe_allow_html=True) # 👈 可以改成你們學校的名字
st.markdown('<div class="school-subtitle">115 級畢業紀念冊 ・ 照片個人收集中心</div>', unsafe_allow_html=True)

# 貼心提示小卡
st.markdown("""
<div class="custom-card">
    📌 <b>畢業生注意事項：</b><br>
    請輸入發送到您學校信箱（或由班代發放）的 <b>專屬 4 位數密碼</b>。
    系統已全面升級，支援手機直接截圖上傳、多圖同時投遞，檔名會由系統自動智慧處理。
</div>
""", unsafe_allow_html=True)

# 橫向標籤頁
tab1, tab2 = st.tabs(["📥 投遞我的照片 (上傳)", "🔍 查看我的足跡 (查詢)"])

# --- 📥 上傳功能 ---
with tab1:
    st.markdown("<br>", unsafe_allow_html=True)
    upload_password = st.text_input("🔑 請輸入您的專屬密碼：", type="password", key="pwd_upload", help="請輸入 4 位數密碼以利系統核對座號")
    uploaded_files = st.file_uploader("📸 挑選完美的照片（可多選）：", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("🚀 確認送出照片，製作畢業紀念冊"):
        if not upload_password:
            st.error("❌ 請先輸入您的專屬密碼！")
        elif not uploaded_files:
            st.error("❌ 請至少選擇一張照片！")
        else:
            with st.spinner("✨ 正在為您封裝照片並連線校園儲存中心..."):
                response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                if not response.data:
                    st.error("❌ 密碼驗證失敗！請確認密碼是否正確，或聯繫畢聯會管理員。")
                else:
                    student = response.data[0]
                    seat_no = student['seat_no']
                    name = student['name']
                    success_count = 0
                    
                    for idx, file in enumerate(uploaded_files):
                        file_ext = file.name.split(".")[-1]
                        # 智慧改名：座號_序號_時間戳記.副檔名
                        new_filename = f"{seat_no}_{idx}_{int(time.time())}.{file_ext}"
                        
                        try:
                            supabase.storage.from_("photos").upload(
                                path=new_filename, 
                                file=file.read(), 
                                file_options={"content-type": file.type}
                            )
                            success_count += 1
                        except Exception as e:
                            st.error(f"❌ {file.name} 傳輸中斷: {str(e)}")
                            
                    if success_count > 0:
                        st.balloons() # 噴出慶祝氣球 🎈
                        st.success(f"🎉 成功！親愛的 {name} 同學，您已順利完成 {success_count} 張照片的投遞！")

# --- 🔍 查詢功能 ---
with tab2:
    st.markdown("<br>", unsafe_allow_html=True)
    st.info("💡 為了保護個人隱私，預設畫面為空白。請在下方輸入您的密碼解鎖已上傳的照片。")
    query_password = st.text_input("🔑 請輸入您的專屬密碼解鎖：", type="password", key="pwd_query")
    
    if st.button("🔓 點擊解鎖我的相簿"):
        if not query_password:
            st.error("❌ 請輸入密碼！")
        else:
            with st.spinner("🔍 正在從畢業相冊資料庫中檢索您的照片..."):
                response = supabase.table("grad_album").select("*").eq("password", query_password).execute()
                if not response.data:
                    st.error("❌ 密碼錯誤，無法解鎖。")
                else:
                    student = response.data[0]
                    seat_no = student['seat_no']
                    st.success(f"👋 歡迎回來，{student['name']} 同學！以下為您已上傳的珍貴回憶：")
                    
                    storage_files = supabase.storage.from_("photos").list(path="")
                    my_photos_urls = [
                        supabase.storage.from_("photos").get_public_url(f['name']) 
                        for f in storage_files 
                        if f['name'].startswith(f"{seat_no}_")
                    ]
                    
                    if not my_photos_urls:
                        st.warning(" 偵測到您目前還沒有上傳過任何照片喔！趕快到隔壁分頁上傳吧！")
                    else:
                        cols = st.columns(3)
                        for idx, url in enumerate(my_photos_urls):
                            with cols[idx % 3]:
                                # 使用帶有陰影邊框的 HTML 容器包裝圖片
                                st.markdown(f'<div class="photo-frame">', unsafe_allow_html=True)
                                st.image(url, use_column_width=True)
                                st.markdown('</div>', unsafe_allow_html=True)

