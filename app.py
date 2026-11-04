import streamlit as st
import uuid
import hmac
from datetime import datetime, timezone
from supabase import create_client, Client

st.set_page_config(
    page_title="116級國三一畢業紀念冊",
    page_icon="📷",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Secrets are stored only in Streamlit Cloud/local .streamlit/secrets.toml.
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"]
ADMIN_USERNAME = st.secrets["ADMIN_USERNAME"]
ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
BUCKET = "photos"
MAX_FILE_SIZE = 10 * 1024 * 1024

@st.cache_resource
def get_clients():
    public_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    admin_client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    return public_client, admin_client

supabase, admin = get_clients()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"] {font-family:'Noto Sans TC',sans-serif;background:#f3f8fd;}
.block-container {max-width:1120px;padding-top:1.5rem;}
.hero {text-align:center;color:#173b61;padding:8px 0 20px;}
.hero h1 {font-size:2rem;font-weight:800;}
.hero p {color:#58738e;}
</style>
""", unsafe_allow_html=True)

try:
    st.image("fsvs_logo.png", width=88)
except Exception:
    pass
st.markdown(
    '<div class="hero"><h1>國立鳳山高級商工職業學校</h1>'
    '<p>116級 國三一｜畢業紀念冊照片與拍攝資訊平台</p></div>',
    unsafe_allow_html=True,
)

def verify_student(seat_no: str, password: str):
    result = admin.rpc(
        "verify_student_login",
        {"input_seat_no": seat_no.strip(), "input_password": password},
    ).execute()
    return result.data[0] if result.data else None

def set_session(role, identity=None):
    st.session_state["role"] = role
    st.session_state["identity"] = identity
    st.session_state["login_time"] = datetime.now(timezone.utc).timestamp()

def logout():
    for key in ("role", "identity", "login_time"):
        st.session_state.pop(key, None)
    st.rerun()

def current_role():
    role = st.session_state.get("role")
    logged_at = st.session_state.get("login_time", 0)
    if not role or datetime.now(timezone.utc).timestamp() - logged_at > 1800:
        if role:
            logout()
        return None
    return role

def image_info(uploaded):
    data = uploaded.getvalue()
    if not data or len(data) > MAX_FILE_SIZE:
        return None, None, "檔案為空或超過 10 MB"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg", None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png", None
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return data, "image/webp", None
    return None, None, "檔案內容不是有效的 JPG、PNG 或 WEBP 圖片"

def upload_photo(path, data, mime):
    admin.storage.from_(BUCKET).upload(
        path=path, file=data,
        file_options={"content-type": mime, "upsert": "false"},
    )

def make_url(path):
    result = admin.storage.from_(BUCKET).create_signed_url(path, 900)
    return result.get("signedURL") or result.get("signedUrl")

def list_student_photos(seat_no):
    storage = admin.storage.from_(BUCKET)
    found = []
    # New format: one private folder per seat number.
    try:
        for item in storage.list(path=seat_no, options={"limit": 500}):
            name = item.get("name", "")
            if name and item.get("id") is not None:
                found.append(f"{seat_no}/{name}")
    except Exception:
        pass
    # Backward compatibility for old files named seatno_filename in bucket root.
    try:
        for item in storage.list(path="", options={"limit": 500}):
            name = item.get("name", "")
            if name.startswith(f"{seat_no}_") and item.get("id") is not None:
                found.append(name)
    except Exception:
        pass
    return sorted(set(found))

def list_all_photos():
    storage = admin.storage.from_(BUCKET)
    paths = []
    for item in storage.list(path="", options={"limit": 500}):
        name = item.get("name", "")
        if not name:
            continue
        if item.get("id") is not None:
            paths.append(name)
        else:
            # Folder entry; enumerate its immediate files.
            try:
                for child in storage.list(path=name, options={"limit": 500}):
                    child_name = child.get("name", "")
                    if child_name and child.get("id") is not None:
                        paths.append(f"{name}/{child_name}")
            except Exception:
                continue
    return sorted(set(paths))

def get_groups():
    return admin.table("shooting_groups").select("*").order("created_at").execute().data

def show_group(group):
    st.markdown(f"### {group.get('group_name') or '未命名小組'}")
    c1, c2 = st.columns(2)
    c1.write(f"**拍攝地點：** {group.get('location') or '未設定'}")
    c2.write(f"**集合時間：** {group.get('meeting_time') or '未設定'}")
    st.write(f"**組員名單：** {group.get('members') or '未設定'}")
    st.write(f"**注意事項：** {group.get('notes') or '無'}")
    if group.get("photo_path"):
        try:
            st.image(make_url(group["photo_path"]), width=420)
        except Exception:
            st.caption("地點照片目前無法讀取")

role = current_role()

if role is None:
    student_tab, admin_tab = st.tabs(["學生登入", "畢冊製作組登入"])
    with student_tab:
        st.subheader("學生個人專區")
        seat = st.text_input("帳號（請輸入座號）", key="student_seat")
        password = st.text_input("個人專屬密碼", type="password", key="student_pwd")
        if st.button("登入學生專區", type="primary", use_container_width=True):
            if not seat.strip() or not password:
                st.warning("請輸入座號及個人密碼。")
            else:
                try:
                    student = verify_student(seat, password)
                    if student:
                        set_session("student", {
                            "id": student["id"],
                            "seat_no": str(student["seat_no"]),
                            "name": student["name"],
                        })
                        st.rerun()
                    else:
                        st.error("座號或密碼錯誤。")
                except Exception:
                    st.error("登入驗證暫時無法使用，請稍後再試。")
    with admin_tab:
        st.subheader("畢冊製作組管理專區")
        username = st.text_input("管理帳號", key="admin_user")
        password = st.text_input("管理密碼", type="password", key="admin_pwd")
        if st.button("登入管理專區", type="primary", use_container_width=True):
            if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
                set_session("admin", {"username": ADMIN_USERNAME})
                st.rerun()
            else:
                st.error("管理帳號或密碼錯誤。")
    st.stop()

identity = st.session_state.get("identity") or {}
st.caption("登入有效時間：30 分鐘")
if role == "student":
    st.success(f"學生登入成功：{identity['seat_no']} 號｜{identity['name']}")
else:
    st.success("畢冊製作組管理員登入成功")
if st.button("登出"):
    logout()

if role == "student":
    up_tab, mine_tab, info_tab = st.tabs(["📤 上傳照片", "🖼️ 我的照片", "📍 拍攝小組資訊"])
    with up_tab:
        st.subheader("上傳個人照片")
        files = st.file_uploader(
            "可多選 JPG、PNG、WEBP，每張上限 10 MB",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
        )
        if st.button("確認上傳", type="primary"):
            if not files:
                st.warning("請先選擇照片。")
            else:
                count = 0
                for file in files:
                    data, mime, error = image_info(file)
                    if error:
                        st.error(f"{file.name}：{error}")
                        continue
                    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
                    path = f"{identity['seat_no']}/{uuid.uuid4().hex}.{ext}"
                    try:
                        upload_photo(path, data, mime)
                        count += 1
                    except Exception:
                        st.error(f"{file.name} 上傳失敗，請稍後再試。")
                if count:
                    st.success(f"成功上傳 {count} 張照片。")
    with mine_tab:
        st.subheader("我的照片")
        try:
            paths = list_student_photos(identity["seat_no"])
            if not paths:
                st.info("目前還沒有上傳照片。")
            else:
                cols = st.columns(3)
                for i, path in enumerate(paths):
                    with cols[i % 3]:
                        st.image(make_url(path), use_container_width=True)
        except Exception:
            st.error("照片讀取失敗，請稍後再試。")
    with info_tab:
        st.subheader("拍攝小組資訊")
        try:
            groups = get_groups()
            if not groups:
                st.info("目前尚未公布拍攝小組資訊。")
            for group in groups:
                with st.container(border=True):
                    show_group(group)
        except Exception:
            st.error("拍攝資訊讀取失敗，請聯絡畢冊製作組。")

elif role == "admin":
    group_tab, photo_tab = st.tabs(["📍 拍攝小組管理", "🗂️ 全班照片管理"])
    with group_tab:
        st.subheader("新增拍攝小組")
        with st.form("new_group_form", clear_on_submit=True):
            group_name = st.text_input("組別名稱")
            location = st.text_input("拍攝地點")
            meeting_time = st.text_input("集合時間")
            members = st.text_area("組員名單")
            notes = st.text_area("拍攝注意事項")
            location_photo = st.file_uploader("地點照片（JPG、PNG、WEBP）", type=["jpg", "jpeg", "png", "webp"], key="new_group_photo")
            submitted = st.form_submit_button("新增小組")
        if submitted:
            if not group_name.strip():
                st.warning("請填寫組別名稱。")
            else:
                photo_path = None
                if location_photo:
                    data, mime, error = image_info(location_photo)
                    if error:
                        st.error(error)
                        st.stop()
                    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
                    photo_path = f"shoot_groups/{uuid.uuid4().hex}.{ext}"
                    upload_photo(photo_path, data, mime)
                admin.table("shooting_groups").insert({
                    "group_name": group_name.strip(),
                    "location": location.strip(),
                    "meeting_time": meeting_time.strip(),
                    "members": members.strip(),
                    "notes": notes.strip(),
                    "photo_path": photo_path,
                }).execute()
                st.success("小組資料已新增。")
                st.rerun()
        st.divider()
        st.subheader("修改／刪除拍攝小組")
        try:
            groups = get_groups()
            for group in groups:
                gid = group["id"]
                with st.expander(f"{group.get('group_name')}｜編輯"):
                    with st.form(f"edit_group_{gid}"):
                        gn = st.text_input("組別名稱", value=group.get("group_name") or "", key=f"gn{gid}")
                        loc = st.text_input("拍攝地點", value=group.get("location") or "", key=f"loc{gid}")
                        mt = st.text_input("集合時間", value=group.get("meeting_time") or "", key=f"mt{gid}")
                        mem = st.text_area("組員名單", value=group.get("members") or "", key=f"mem{gid}")
                        nt = st.text_area("注意事項", value=group.get("notes") or "", key=f"nt{gid}")
                        new_photo = st.file_uploader("更換地點照片", type=["jpg", "jpeg", "png", "webp"], key=f"gp{gid}")
                        save = st.form_submit_button("儲存修改")
                    if save:
                        update = {
                            "group_name": gn.strip(), "location": loc.strip(),
                            "meeting_time": mt.strip(), "members": mem.strip(),
                            "notes": nt.strip(),
                        }
                        if new_photo:
                            data, mime, error = image_info(new_photo)
                            if error:
                                st.error(error)
                                st.stop()
                            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
                            new_path = f"shoot_groups/{uuid.uuid4().hex}.{ext}"
                            upload_photo(new_path, data, mime)
                            update["photo_path"] = new_path
                        admin.table("shooting_groups").update(update).eq("id", gid).execute()
                        st.success("修改完成。")
                        st.rerun()
                    if st.button("刪除此小組", key=f"del_group_{gid}"):
                        admin.table("shooting_groups").delete().eq("id", gid).execute()
                        st.success("小組已刪除。")
                        st.rerun()
        except Exception:
            st.error("無法讀取小組資料，請確認已執行建表 SQL。")
    with photo_tab:
        st.subheader("全班照片管理")
        st.warning("刪除照片無法復原，請確認選取內容。")
        try:
            paths = list_all_photos()
            st.write(f"目前找到 {len(paths)} 張照片")
            if not paths:
                st.info("目前沒有照片。")
            for path in paths:
                c1, c2, c3 = st.columns([5, 2, 1])
                c1.code(path)
                try:
                    c2.image(make_url(path), width=110)
                except Exception:
                    c2.caption("預覽失敗")
                raw = admin.storage.from_(BUCKET).download(path)
                c1.download_button("下載", raw, file_name=path.split("/")[-1], key=f"dl_{path}")
                if c3.button("刪除", key=f"rm_{path}"):
                    admin.storage.from_(BUCKET).remove([path])
                    st.success("照片已刪除。")
                    st.rerun()
        except Exception:
            st.error("照片清單讀取失敗，請確認 Storage bucket 名稱及權限。")
