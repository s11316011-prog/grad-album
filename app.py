import streamlit as st
from supabase import create_client, Client
import time

# 🔑 您的 Supabase 通行證
SUPABASE_URL = "https://yxbjluynjjxyjkrmihyz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl4YmpsdXluamp4eWprcm1paHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTg1NzAsImV4cCI6MjEwNzAzNDU3MH0.QtslxkyN1z5gMTAgYX5HHn6kQlqNU1sXtghTSFA8vjE"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

# --- 網頁基本設定 ---
st.set_page_config(page_title="國三一個人照收集處", layout="centered")

# --- 標題與標籤頁 ---
st.title("國三一 一個人照收集處")
st.write("116級個人照片上傳與查詢系統")

tab1, tab2 = st.tabs(["我要上傳照片", "確認我的上傳狀態"])

# --- 上傳功能 ---
with tab1:
    st.subheader("上傳個人寫真")
    upload_password = st.text_input("請輸入您的專屬密碼：", type="password", key="pwd_upload")
    uploaded_files = st.file_uploader("請選擇要上傳的照片（可多選）：", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    
    if st.button("確認送出上傳"):
        if not upload_password:
            st.error("請先輸入您的專屬密碼！")
        elif not uploaded_files:
            st.error("請至少選擇一張照片！")
        else:
            with st.spinner("照片上傳中..."):
                try:
                    response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                    raw_data = response.data
                    
                    if not raw_data:
                        st.error("密碼錯誤，拒絕上傳。")
                    else:
                        student = raw_data[0]
                        seat_no = student['seat_no']
                        name = student['name']
                        success_count = 0
                        
                        for idx, file in enumerate(uploaded_files):
                            file_ext = file.name.split(".")[-1]
                            # 自動智慧改名：座號_序號_時間.副檔名，徹底解決中文檔名 InvalidKey 錯誤
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
                            st.success(f"恭喜 {name} 同學！成功上傳 {success_count} 張照片！")
                except Exception as db_err:
                    st.error(f"系統連線異常: {str(db_err)}")

# --- 查詢功能 ---
with tab2:
    st.subheader("個人相片查詢台")
    st.info("為了保護隱私，預設畫面為空白。請在下方輸入您的密碼解鎖照片。")
    query_password = st.text_input("請輸入您的專屬密碼解鎖：", type="password", key="pwd_query")
    
    if st.button("解鎖我的照片"):
        if not query_password:
            st.error("請輸入密碼！")
        else:
            with st.spinner("正在查詢..."):
                try:
                    response = supabase.table("grad_album").select("*").eq("password", query_password).execute()
                    raw_data = response.data
                    
                    if not raw_data:
                        st.error("密碼錯誤。")
                    else:
                        student = raw_data[0]
                        seat_no = student['seat_no']
                        st.success(f"歡迎回來，{student['name']} 你已上傳的照片：")
                        
                        storage_files = supabase.storage.from_("photos").list(path="")
                        my_photos_urls = [
                            supabase.storage.from_("photos").get_public_url(f['name']) 
                            for f in storage_files 
                            if f['name'].startswith(f"{seat_no}_")
                        ]
                        
                        if not my_photos_urls:
                            st.warning("你目前還沒有上傳過任何照片喔！")
                        else:
                            cols = st.columns(3)
                            for idx, url in enumerate(my_photos_urls):
                                with cols[idx % 3]:
                                    st.image(url, use_column_width=True)
                except Exception as db_err:
                    st.error(f"系統連線異常: {str(db_err)}")
