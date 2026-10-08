import streamlit as st
from supabase import create_client, Client

# 🔑 請確認以下這兩行，有沒有精準填入您在 Supabase 複製的通行證：
SUPABASE_URL = "https://yxbjluynjjxyjkrmihyz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl4YmpsdXluamp4eWprcm1paHl6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTg1NzAsImV4cCI6MjEwNzAzNDU3MH0.QtslxkyN1z5gMTAgYX5HHn6kQlqNU1sXtghTSFA8vjE"

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
                response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                if not response.data:
                    st.error("❌ 密碼錯誤，拒絕上傳。")
                else:
                    student = response.data[0]  # 修改防呆邏輯
                    seat_no = student['seat_no']
                    name = student['name']
                    success_count = 0
                    for file in uploaded_files:
                        new_filename = f"{seat_no}_{name}_{file.name}"
                        try:
                            supabase.storage.from_("photos").upload(path=new_filename, file=file.read(), file_options={"content-type": file.type})
                            success_count += 1
                        except Exception as e:
                            st.error(f"❌ {file.name} 上傳失敗: {str(e)}")
                    if success_count > 0:
                        st.success(f"🎉 恭喜 {name} 同學！成功上傳 {success_count} 張照片！")

# --- 查詢功能 ---
with tab2:
    st.header("個人相片查詢台")
    st.info("💡 為了保護隱私，預設畫面為空白。請在下方輸入您的密碼解鎖照片。")
    query_password = st.text_input("請輸入您的專屬密碼解鎖：", type="password", key="pwd_query")
    
    if st.button("🔓 解鎖我的照片"):
        if not query_password:
            st.error("❌ 請輸入密碼！")
        else:
            with st.spinner("正在查詢..."):
                response = supabase.table("grad_album").select("*").eq("password", query_password).execute()
                if not response.data:
                    st.error("❌ 密碼錯誤。")
                else:
                    student = response.data[0]  # 修改防呆邏輯
                    seat_no = student['seat_no']
                    st.success(f"👋 歡迎回來，{student['name']} 你已上傳的照片：")
                    storage_files = supabase.storage.from_("photos").list(path="")
                    my_photos_urls = [supabase.storage.from_("photos").get_public_url(f['name']) for f in storage_files if f['name'].startswith(f"{seat_no}_")]
                    
                    if not my_photos_urls:
                        st.warning("你目前還沒有上傳過任何照片喔！")
                    else:
                        cols = st.columns(3)
                        for idx, url in enumerate(my_photos_urls):
                            with cols[idx % 3]:
                                st.image(url, use_column_width=True)
