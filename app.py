import streamlit as st
import uuid
from supabase import create_client, Client

# ==========================================
# 1. 網頁基本設定
# ==========================================

st.set_page_config(
    page_title="國立鳳山高級商工職業學校 - 畢業紀念冊個人照收集系統",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. Supabase 金鑰設定
# ==========================================

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"]


# 一般 Supabase Client
@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


supabase: Client = get_supabase_client()


# 管理端 Supabase Client（僅限伺服器端）
@st.cache_resource
def get_supabase_admin_client():
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


supabase_admin: Client = get_supabase_admin_client()


# ==========================================
# 3. 學生密碼驗證
# ==========================================

def verify_student_password(input_password):

    if not input_password:
        return None

    try:
        response = supabase_admin.rpc(
            "verify_student_password",
            {"input_password": input_password}
        ).execute()

        students = response.data or []

        if len(students) == 1:
            return students[0]

        return None

    except Exception:
        st.error("密碼驗證服務暫時無法使用，請稍後再試。")
        return None


# ==========================================
# 4. 網頁 CSS 設計
# ==========================================

st.markdown("""
    <style>

    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Noto Sans TC', sans-serif;
        background-color: #F8F9FA;
    }

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

    .logo-container {
        display: flex;
        justify-content: center;
        margin-bottom: 15px;
    }

    .logo-img {
        width: 90px;
        height: auto;
    }

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

    div.stButton > button:hover {
        background: linear-gradient(135deg, #1A3E70 0%, #245699 100%);
        box-shadow: 0 6px 12px rgba(15, 37, 71, 0.25);
        transform: translateY(-1px);
        color: #D4AF37 !important;
    }

    div.stButton > button:active {
        transform: translateY(1px);
        box-shadow: 0 2px 4px rgba(15, 37, 71, 0.15);
    }

    .css-1r6slb0, [data-testid="stVerticalBlock"] > div {
        background-color: #FFFFFF;
        padding: 5px;
        border-radius: 10px;
    }

    input:focus {
        border-color: #0F2547 !important;
        box-shadow: 0 0 0 1px #0F2547 !important;
    }

    </style>
""", unsafe_allow_html=True)


# ==========================================
# 5. 網頁標題與校徽
# ==========================================

st.image("fsvs_logo.png", width=90)

st.markdown("""
    <div style="text-align: center;">
        <div class="main-title" style="margin-top: 10px;">
            國立鳳山高級商工職業學校
        </div>
        <div class="sub-title">
            116級 國三一 畢業紀念冊個人寫真照片收集系統
        </div>
    </div>
""", unsafe_allow_html=True)


# ==========================================
# 6. 建立分頁
# ==========================================

tab1, tab2 = st.tabs([
    "📷 我要上傳照片",
    "🔍 確認我的上傳狀態"
])


# ==========================================
# 7. 照片上傳功能
# ==========================================

with tab1:

    st.markdown(
        "<h4 style='color: #0F2547; font-weight: 600; margin-bottom: 15px;'>照片檔案上傳</h4>",
        unsafe_allow_html=True
    )

    upload_password = st.text_input(
        "請輸入您的專屬密碼：",
        type="password",
        key="pwd_upload",
        help="請輸入系統發放的個人密碼"
    )

    uploaded_files = st.file_uploader(
        "請選擇要上傳的照片（可多選，支援 JPG、PNG、WEBP）：",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True
    )

    if st.button("確認送出上傳", key="btn_upload"):

        if not upload_password:
            st.error("請先輸入您的專屬密碼！")

        elif not uploaded_files:
            st.error("請至少選擇一張照片！")

        elif any(
            file.size > 10 * 1024 * 1024
            for file in uploaded_files
        ):
            st.error("單張照片不可超過 10 MB，請重新選擇照片！")

        else:

            with st.spinner("系統正在處理上傳照片，請稍候..."):

                student = verify_student_password(upload_password)

                if not student:

                    st.error("密碼驗證失敗，拒絕上傳。")

                else:

                    seat_no = student["seat_no"]
                    name = student["name"]
                    success_count = 0

                    allowed_types = {
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg",
                        "png": "image/png",
                        "webp": "image/webp"
                    }

                    for file in uploaded_files:

                        file_ext = file.name.rsplit(".", 1)[-1].lower()

                        if file_ext not in allowed_types:
                            st.error(
                                f"{file.name}：不支援的照片格式。"
                            )
                            continue

                        if file.type != allowed_types[file_ext]:
                            st.error(
                                f"{file.name}：檔案格式與類型不符。"
                            )
                            continue

                        # 使用已驗證的座號建立專屬資料夾
                        new_filename = (
                            f"{seat_no}/{uuid.uuid4().hex}.{file_ext}"
                        )

                        try:

                            supabase_admin.storage.from_("photos").upload(
                                path=new_filename,
                                file=file.getvalue(),
                                file_options={
                                    "content-type": file.type,
                                    "upsert": "false"
                                }
                            )

                            success_count += 1

                        except Exception:
                            st.error(
                                f"{file.name} 上傳失敗，請稍後再試。"
                            )

                    if success_count > 0:

                        st.success(
                            f"🎉 上傳成功｜座號：{seat_no} 號 — "
                            f"{name} 同學，已成功匯入 "
                            f"{success_count} 張相片！"
                        )

                    else:

                        st.warning(
                            "沒有任何照片成功上傳，"
                            "請檢查檔案格式或稍後再試。"
                        )


# ==========================================
# 8. 個人照片查詢功能
# ==========================================

with tab2:

    st.markdown(
        "<h4 style='color: #0F2547; font-weight: 600; margin-bottom: 15px;'>個人相片查詢台</h4>",
        unsafe_allow_html=True
    )

    # 初始化登入狀態
    if "verified_student" not in st.session_state:
        st.session_state["verified_student"] = None

    # 尚未登入
    if not st.session_state["verified_student"]:

        st.info(
            "為了保護學生個人隱私，"
            "請輸入您的專屬密碼以查看照片。"
        )

        query_password = st.text_input(
            "請輸入您的專屬密碼解鎖：",
            type="password",
            key="pwd_query"
        )

        if st.button("解鎖我的照片", key="btn_query"):

            if not query_password:

                st.error("請輸入解鎖密碼！")

            else:

                with st.spinner("正在安全驗證中..."):

                    student = verify_student_password(query_password)

                    if student:

                        st.session_state["verified_student"] = {
                            "id": student["id"],
                            "seat_no": student["seat_no"],
                            "name": student["name"]
                        }

                        st.rerun()

                    else:

                        st.error("密碼驗證錯誤，無法讀取資料。")

    # 已登入
    if st.session_state["verified_student"]:

        student = st.session_state["verified_student"]

        seat_no = student["seat_no"]
        name = student["name"]

        st.success(
            f"🔓 驗證通過｜座號：{seat_no} 號 — "
            f"{name} 同學，以下為您已上傳的照片："
        )

        # 登出
        if st.button("登出", key="btn_logout"):

            st.session_state["verified_student"] = None
            st.session_state["pwd_query"] = ""

            st.rerun()

        # 使用管理端連線讀取 Private bucket
        storage = supabase_admin.storage.from_("photos")

        my_photos_urls = []

        try:

            # ① 讀取舊照片：仍放在 bucket 最外層
            old_files = storage.list(
                path="",
                options={"limit": 500}
            )

            for photo in old_files:

                filename = photo.get("name", "")

                if filename.startswith(f"{seat_no}_"):

                    signed = storage.create_signed_url(
                        filename,
                        3600
                    )

                    photo_url = (
                        signed.get("signedURL")
                        or signed.get("signedUrl")
                    )

                    if photo_url:
                        my_photos_urls.append(photo_url)

            # ② 讀取新照片：只讀取目前學生自己的資料夾
            new_files = storage.list(
                path=str(seat_no),
                options={"limit": 500}
            )

            for photo in new_files:

                filename = photo.get("name", "")

                if not filename:
                    continue

                photo_path = f"{seat_no}/{filename}"

                signed = storage.create_signed_url(
                    photo_path,
                    3600
                )

                photo_url = (
                    signed.get("signedURL")
                    or signed.get("signedUrl")
                )

                if photo_url:
                    my_photos_urls.append(photo_url)

            # 沒有照片
            if not my_photos_urls:

                st.warning(
                    "您目前在此系統中尚未有任何照片紀錄。"
                )

            else:

                # 照片格子
                cols = st.columns(3)

                for idx, url in enumerate(my_photos_urls):

                    with cols[idx % 3]:

                        st.image(
                            url,
                            use_container_width=True
                        )

        except Exception:

            st.error("照片讀取失敗，請稍後再試。")
