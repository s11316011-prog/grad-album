import streamlit as st

# --- 這裡通常是您前面的其它 UI 元件，例如標題或欄位輸入 ---
# st.title("🎓 畢業紀念冊照片上傳系統")

# 使用邊框容器（Border Container）打造卡片式現代化 UI
with st.container(border=True):
    st.markdown("### 🔑 安全驗證與檔案上傳")
    st.info("💡 提示：請先輸入您的個人專屬密碼，並選擇欲上傳的照片。")
    
    # 建立左右兩欄，使排版更精簡美觀
    col1, col2 = st.columns(2)
    with col1:
        upload_password = st.text_input("輸入專屬密碼", type="password", placeholder="請輸入密碼...")
    with col2:
        uploaded_files = st.file_uploader("選擇照片 (可多選)", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

    st.markdown("---") # 分隔線

    # 調大按鈕視覺寬度並加上引導 Icon
    if st.button("🚀 確認送出並開始上傳", use_container_width=True):
        
        # 1. 前端欄位防呆檢查
        if not upload_password:
            st.error("❌ 請先輸入您的專屬密碼！")
            
        elif not uploaded_files:
            st.warning("⚠️ 請至少選擇一張照片！")
            
        else:
            # 2. 通過欄位檢查，啟動讀取動畫與資料庫查詢
            with st.spinner("⏳ 正在驗證身份並準備上傳，請稍候..."):
                try:
                    # 執行 Supabase 資料庫查詢
                    response = supabase.table("grad_album").select("*").eq("password", upload_password).execute()
                    
                    # 3. 檢查資料庫是否有找到對應密碼的資料
                    if not response.data:
                        st.error("❌ 密碼錯誤，拒絕上傳。請確認後再試一次！")
                    else:
                        # 4. 成功獲取資料，自動取出 List 中的首筆項目
                        student = response.data[0]
                        seat_no = student.get('seat_no', '未知')
                        name = student.get('name', '未知')
                        
                        # 顯示歡迎提示卡片
                        st.success(f"✅ 身份驗證成功！歡迎您，【座號 {seat_no}】{name} 同學。")
                        
                        # ---- 🚀 這裡接您原本處理「照片上傳到儲存空間」的後續代碼 ----
                        # 例如：for file in uploaded_files: ...
                        
                except Exception as e:
                    # 補捉所有資料庫或執行期的異常錯誤，防範程式崩潰
                    st.error(f"⚠️ 系統發生未知錯誤，請聯絡管理員。錯誤訊息: {e}")
