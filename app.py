import streamlit as st
from supabase import create_client, Client

# 🔑 您的 API 連線憑證已為您精準填入
SUPABASE_URL = "https://supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl4Ymx1anloeWp4eWprcm1paHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTg1NzAsImV4cCI6MjEwNzAzNDU3MH0.QtslxkyN1z5gMTAgYX5HHn6kQlqNU1sXtghTSFA8vjE"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

st.set_page_config(page_title="畢業紀念冊照片收集網頁", page_icon="🎓", layout="centered")
st.title("🎓 畢業紀念冊・照片收集中心")
st.write("你好！請輸入在學校信箱中的 **專屬 4 位數密碼** 來上傳或查詢照片。")

tab1, tab2 = st.tabs(["📥 我要上傳照片", "🔍 確認我的上傳狀態"])

# --- 上傳功能 ---
with tab1:
    st.header("上傳個人寫真")
    upload_password = st.text_input("請輸入您的專屬密碼：", type="password", key="pwd_upload")
    uploaded_files = st.file_uploader("請選擇要上傳的照片（可多選）：", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("🚀 確認送出上傳"):
        if not upload_password:
            st.error("❌ 請先輸入您的專屬密碼！")
            
        elif not uploaded_files:
            st.error("❌ 請至少選擇一張照片！")
            
        else:
            with st.spinner("照片上傳中..."):
                try:
                    # 1. 執行查詢
                    response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                    
                    # 2. 檢查是否有找到對應密碼的資料
                    if not response.data:
                        st.error("❌ 密碼錯誤，拒絕上傳。")
                    else:
                        # 這裡 data 回傳的是一個 List（列表），取第一個項目 [0]
                        student = response.data[0]
                        seat_no = student['seat_no']
                        name = student['name']
                        
                        # ---- 這裡接你原本處理「照片上傳」的後續代碼 ----
                        # (請確保這裡後續的代碼也是維持正確縮排)
                        
                except Exception as e:
                    st.error(f"⚠️ 發生未知錯誤: {e}")
