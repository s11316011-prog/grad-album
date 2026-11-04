            else:
                paths.append(full_path)

    walk("")
    return sorted(set(paths))


# ---------- 頁面外觀 ----------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Noto Sans TC', sans-serif;
        background: #f3f8fd;
    }
    .block-container {max-width: 1120px; padding-top: 1.8rem;}
    .hero {text-align:center; color:#173b61; padding: 4px 0 18px;}
    .hero h1 {font-size: 2rem; font-weight: 800; margin: 8px 0;}
    .hero p {color:#5a7590; font-size:1.05rem;}
    div.stButton > button {border-radius:10px; font-weight:650; min-height:42px;}
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    st.image("fsvs_logo.png", width=88)
except Exception:
    pass

st.markdown(
    """
    <div class="hero">
      <h1>國立鳳山高級商工職業學校</h1>
      <p>116級 國三一｜畢業紀念冊照片與拍攝資訊平台</p>
    </div>
    """,
    unsafe_allow_html=True,
)

role = active_role()

# ---------- 登入 ----------
if not role:
    student_tab, staff_tab = st.tabs(["學生登入", "製作組／班級幹部登入"])

    with student_tab:
        st.subheader("📷 學生照片專區")
        student_password = st.text_input(
            "輸入個人專屬密碼", type="password", key="student_password"
        )
        if st.button("登入學生專區", use_container_width=True):
            if login_throttle_ok():
                try:
                    student = verify_student_password(student_password)
                except Exception:
                    st.error("密碼驗證服務暫時無法使用，請稍後再試。")
                    student = None
                if student:
                    set_login(
                        "student",
                        {
                            "id": student["id"],
                            "seat_no": str(student["seat_no"]),
                            "name": student["name"],
                        },
                    )
                    st.rerun()
                else:
                    st.error("密碼錯誤，請確認後再試。")

    with staff_tab:
        st.subheader("🔐 工作人員登入")
        staff_role = st.radio(
            "登入身分", ["畢冊製作組", "班級幹部"], horizontal=True
        )
        staff_password = st.text_input(
            "工作人員密碼", type="password", key="staff_password"
        )
        if st.button("登入工作人員專區", use_container_width=True):
            if login_throttle_ok():
                expected = (
                    ADMIN_PASSWORD if staff_role == "畢冊製作組" else CADRE_PASSWORD
                )
                if not expected:
                    st.error("尚未設定這個身分的密碼，請先設定 Streamlit Secrets。")
                elif hmac.compare_digest(staff_password, expected):
                    set_login("admin" if staff_role == "畢冊製作組" else "cadre")
                    st.rerun()
                else:
                    st.error("工作人員密碼錯誤。")
    st.stop()


# ---------- 已登入狀態 ----------
identity = st.session_state.get("identity")
if role == "student":
    st.success(f"已登入：{identity['seat_no']} 號｜{identity['name']} 同學")
elif role == "admin":
    st.success("已登入：畢冊製作組管理員")
else:
    st.success("已登入：班級幹部（拍攝小組資料管理）")

if st.button("登出"):
    logout()


# ---------- 學生功能 ----------
if role == "student":
    upload_tab, photos_tab, groups_tab = st.tabs(
        ["📤 上傳照片", "🖼️ 我的照片", "📍 拍攝小組資訊"]
    )

    with upload_tab:
        st.subheader("上傳個人照片")
        uploads = st.file_uploader(
            "可一次選取多張 JPG、PNG、WEBP；單張上限 10 MB",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
        )
        if st.button("確認上傳"):
            if not uploads:
                st.warning("請先選擇照片。")
            else:
                success_count = 0
                for uploaded in uploads:
                    raw, image_format, error = validate_image(uploaded)
                    if error:
                        st.error(f"{uploaded.name}：{error}")
                        continue
                    path = (
                        f"{identity['seat_no']}/"
                        f"{uuid.uuid4().hex}.{extension_for(image_format)}"
                    )
                    try:
                        upload_image(path, raw, image_format)
                        success_count += 1
                    except Exception:
                        st.error(f"{uploaded.name} 上傳失敗，請稍後再試。")
                if success_count:
                    st.success(f"成功上傳 {success_count} 張照片。")

    with photos_tab:
        st.subheader("我的照片")
        try:
            storage = supabase_admin.storage.from_(PHOTO_BUCKET)
            my_paths = []
            # 舊版根目錄命名格式：座號_檔名
            for item in storage.list(path="", options={"limit": 500}):
                name = item.get("name", "")
                if (
                    name.startswith(f"{identity['seat_no']}_")
                    and item.get("id") is not None
                ):
                    my_paths.append(name)
            # 新版個人資料夾：座號/檔名
            for item in storage.list(
                path=identity["seat_no"], options={"limit": 500}
            ):
                name = item.get("name", "")
                if name and item.get("id") is not None:
                    my_paths.append(f"{identity['seat_no']}/{name}")
            my_paths = sorted(set(my_paths))
            if not my_paths:
                st.info("目前還沒有上傳照片。")
            else:
                columns = st.columns(3)
                for index, path in enumerate(my_paths):
                    with columns[index % 3]:
                        st.image(signed_url(path), use_container_width=True)
        except Exception:
            st.error("照片讀取失敗，請稍後再試。")

    with groups_tab:
        st.subheader("小組拍攝資訊")
        try:
            groups = get_groups()
            if not groups:
                st.info("目前尚未公布拍攝小組資訊。")
            for group in groups:
                with st.container(border=True):
                    show_group(group)
        except Exception:
            st.error("拍攝資訊尚未建立，請聯絡畢冊製作組。")


# ---------- 製作組／幹部功能 ----------
else:
    if role == "admin":
        group_tab, photo_tab = st.tabs(["📍 拍攝小組管理", "🗂️ 全班照片管理"])
    else:
