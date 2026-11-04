import streamlit as st
import uuid
import hmac
import base64
import hashlib
import secrets
from importlib.metadata import version
from datetime import datetime, timezone
from supabase import create_client, Client

st.set_page_config(
    page_title="116級國三一畢業紀念冊",
    page_icon="📷",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Secrets are stored only in Streamlit Cloud/local .streamlit/secrets.toml.
SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
SUPABASE_SECRET_KEY = st.secrets["SUPABASE_SECRET_KEY"]
# 舊管理員 Secrets 僅用於第一次啟動時遷移至 Supabase，完成後可從 ST Secrets 移除。
BOOTSTRAP_ADMIN_ACCOUNTS = []
for admin_no in range(1, 6):
    username_key = f"ADMIN_USERNAME_{admin_no}"
    password_key = f"ADMIN_PASSWORD_{admin_no}"
    if admin_no == 1:
        username = st.secrets.get(username_key, st.secrets.get("ADMIN_USERNAME", ""))
        password = st.secrets.get(password_key, st.secrets.get("ADMIN_PASSWORD", ""))
    else:
        username = st.secrets.get(username_key, "")
        password = st.secrets.get(password_key, "")
    if username and password:
        BOOTSTRAP_ADMIN_ACCOUNTS.append({"username": str(username).strip(), "password": str(password)})
BUCKET = "photos"
MAX_FILE_SIZE = 10 * 1024 * 1024

@st.cache_resource
def get_clients(project_url: str, publishable_key: str, secret_key: str):
    # Include configuration in the cache key so Streamlit cannot reuse a
    # client constructed earlier with a stale or malformed REST endpoint.
    public_client = create_client(project_url, publishable_key)
    admin_client = create_client(project_url, secret_key)
    return public_client, admin_client

supabase, admin = get_clients(SUPABASE_URL, SUPABASE_KEY, SUPABASE_SECRET_KEY)

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

PASSWORD_ITERATIONS = 600_000

def hash_staff_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt_text}${digest_text}"

def verify_staff_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def verify_staff_account(username: str, password: str, expected_role: str):
    rows = (
        admin.table("staff_accounts")
        .select("username, role, password_hash, is_active")
        .eq("username", username.strip())
        .eq("role", expected_role)
        .limit(1)
        .execute().data
    )
    if not rows or not rows[0].get("is_active"):
        return None
    row = rows[0]
    if verify_staff_password(password, row["password_hash"]):
        return {"username": row["username"], "role": row["role"]}
    return None

def bootstrap_staff_accounts():
    existing = admin.table("staff_accounts").select("id").limit(1).execute().data
    if existing:
        return
    for account in BOOTSTRAP_ADMIN_ACCOUNTS:
        admin.table("staff_accounts").insert({
            "username": account["username"],
            "role": "admin",
            "password_hash": hash_staff_password(account["password"]),
            "is_active": True,
        }).execute()

try:
    bootstrap_staff_accounts()
except Exception:
    st.error("管理員帳號資料庫初始化失敗，請確認 Supabase staff_accounts 資料表及 Data API 權限。")
    st.stop()

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
    student_tab, teacher_tab, admin_tab = st.tabs(["學生登入", "教師登入", "畢冊製作組登入"])
    with student_tab:
        st.subheader("學生個人專區")
        seat = st.text_input("帳號（請輸入座號）", key="student_seat")
        password = st.text_input("個人專屬密碼", type="password", key="student_pwd")
        if st.button("登入", type="primary", use_container_width=True):
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
                except Exception as e:
                    st.error("登入驗證發生系統錯誤，正在區分資料庫 API 與登入 RPC 問題。")
                    st.code(f"登入 RPC：{type(e).__name__}: {e}")
                    try:
                        admin.table("grad_album").select("id").limit(1).execute()
                        st.success("診斷結果：一般資料表 API 可正常連線；問題集中在登入 RPC 請求。")
                    except Exception as api_error:
                        st.error("診斷結果：一般資料表 API 也無法連線。")
                        st.code(f"資料表 API：{type(api_error).__name__}: {api_error}")
                    st.caption("此診斷只讀取一筆資料的 id，不會顯示或修改學生個資、密碼或照片。")
                    st.markdown("**連線設定診斷（不含任何金鑰）**")
                    st.code(
                        f"SUPABASE_URL = {SUPABASE_URL!r}\\n"
                        f"REST endpoint = {getattr(admin, 'rest_url', 'SDK 未提供 rest_url 屬性')!r}\\n"
                        f"supabase package = {version('supabase')}\\n"
                        f"postgrest package = {version('postgrest')}"
                    )
    with teacher_tab:
        st.subheader("教師登入")
        teacher_username = st.text_input("教師帳號", key="teacher_user")
        teacher_password = st.text_input("教師密碼", type="password", key="teacher_pwd")
        if st.button("教師登入", type="primary", use_container_width=True):
            try:
                matched = verify_staff_account(teacher_username, teacher_password, "teacher")
                if matched:
                    set_session("teacher", {"username": matched["username"]})
                    st.rerun()
                else:
                    st.error("教師帳號或密碼錯誤，或帳號已停用。")
            except Exception:
                st.error("教師登入驗證暫時無法使用，請稍後再試。")
    with admin_tab:
        st.subheader("畢冊製作組管理專區")
        username = st.text_input("管理帳號", key="admin_user")
        password = st.text_input("管理密碼", type="password", key="admin_pwd")
        if st.button("登入管理專區", type="primary", use_container_width=True):
            try:
                matched = verify_staff_account(username, password, "admin")
                if matched:
                    set_session("admin", {"username": matched["username"]})
                    st.rerun()
                else:
                    st.error("管理帳號或密碼錯誤，或帳號已停用。")
            except Exception:
                st.error("管理員登入驗證暫時無法使用，請稍後再試。")
    st.stop()

identity = st.session_state.get("identity") or {}
st.caption("登入有效時間：30 分鐘")
if role == "student":
    st.success(f"學生登入成功：{identity['seat_no']} 號｜{identity['name']}")
elif role == "teacher":
    st.success("教師登入成功｜僅可查詢全班照片及小組分組名單")
elif role == "admin":
    st.success("畢冊製作組管理員登入成功")
if st.button("登出"):
    logout()

if role == "student":
    upload_tab, mine_tab, class_tab, group_tab, personal_tab = st.tabs([
        "📤 個人生活照繳交",
        "🖼️ 我的照片",
        "📸 班級團體照",
        "👥 小組拍攝資訊",
        "📝 個人生活照須知",
    ])
    with upload_tab:
        st.subheader("上傳個人生活照")
        st.info("每位同學都必須繳交個人生活照，請先閱讀「個人生活照須知」再上傳。")
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
    with class_tab:
        st.subheader("班級團體照拍攝公告")
        st.markdown("**拍攝日期：** 11 月 6 日（星期五）")
        st.markdown("**集合時間：** 上午 08:20")
        st.markdown("**集合地點：** 健康中心旁的小石桌")
        st.markdown("**服裝要求：** 請穿著制服")
        st.markdown("**預計拍攝：** 3 張")
        st.markdown("**指定動作：**")
        st.markdown("1. YA 手勢\n2. 小愛心\n3. 戳臉")
        st.warning("請依照集合時間準時到場；如有異動，請留意畢冊製作組後續公告。")
    with group_tab:
        st.subheader("小組拍攝資訊")
        st.caption("各組拍攝地點、集合時間、注意事項、地點照片及組員名單，以畢冊製作組公布的資料為準。")
        try:
            groups = get_groups()
            if not groups:
                st.info("目前尚未公布小組拍攝資訊。")
            for group in groups:
                with st.container(border=True):
                    show_group(group)
        except Exception:
            st.error("拍攝資訊讀取失敗，請聯絡畢冊製作組。")
        st.divider()
        st.subheader("小組登記")
        st.write(f"座號：**{identity['seat_no']}**　姓名：**{identity['name']}**")
        try:
            signup_rows = (
                admin.table("group_signups")
                .select("id, assigned_group, created_at")
                .eq("student_id", identity["id"])
                .limit(1).execute().data
            )
            if signup_rows:
                signup = signup_rows[0]
                group_label = f"第 {signup['assigned_group']} 組" if signup.get("assigned_group") else "尚未分組"
                st.success(f"已完成登記！你的登記編號為 {signup['id']:03d}，目前：{group_label}")
            else:
                if st.button("我要登記小組", type="primary", key="student_group_signup"):
                    admin.table("group_signups").insert({
                        "student_id": identity["id"],
                        "seat_no": str(identity["seat_no"]),
                        "student_name": identity["name"],
                    }).execute()
                    st.success("登記成功！系統已依登記順序產生編號，請留意後續分組公告。")
                    st.rerun()
        except Exception:
            st.error("小組登記功能尚未啟用，請畢冊製作組確認已執行 group_signups.sql。")
    with personal_tab:
        st.subheader("個人生活照繳交規範")
        st.warning("每位同學都必須繳交，截止日期為 11 月 13 日。")
        st.markdown(
            "1. 每位同學都必須繳交個人生活照。\n"
            "2. 不可用任何方式遮蓋五官。\n"
            "3. 請採用七分身拍攝方式。\n"
            "4. 修圖請使用電腦進行，避免手機修圖造成圖片呈現不佳。\n"
            "5. 請於 11 月 13 日前至指定網址繳交。"
        )
        st.info("七分身拍攝範例及指定繳交網址尚待提供，公布後會再補上。")
        st.caption("如有任何問題，請直接提出，或私下向相關負責人反映。")

elif role == "teacher":
    photo_tab, roster_tab = st.tabs(["🖼️ 全班照片查詢", "👥 小組分組名單"])
    with photo_tab:
        st.subheader("全班學生照片")
        st.caption("教師僅能查看照片，沒有下載、刪除或修改權限。")
        try:
            student_paths = [
                path for path in list_all_photos()
                if not path.startswith("shoot_groups/")
            ]
            if not student_paths:
                st.info("目前尚無學生上傳的照片。")
            else:
                st.write(f"目前共有 {len(student_paths)} 張學生照片")
                for path in student_paths:
                    seat_label = path.split("/", 1)[0] if "/" in path else path.split("_", 1)[0]
                    with st.container(border=True):
                        st.caption(f"座號：{seat_label}")
                        try:
                            st.image(make_url(path), use_container_width=True)
                        except Exception:
                            st.warning("這張照片目前無法預覽。")
        except Exception:
            st.error("照片查詢失敗，請稍後再試。")
    with roster_tab:
        st.subheader("小組分組名單")
        st.caption("此頁僅供查詢，教師無法調整學生組別或修改拍攝資訊。")
        try:
            signups = (
                admin.table("group_signups")
                .select("id, seat_no, student_name, assigned_group")
                .order("id")
                .execute().data
            )
            if not signups:
                st.info("目前尚無學生完成小組登記。")
            else:
                assigned = {}
                unassigned = []
                for row in signups:
                    group_no = row.get("assigned_group")
                    if group_no:
                        assigned.setdefault(group_no, []).append(row)
                    else:
                        unassigned.append(row)
                for group_no in sorted(assigned):
                    st.markdown(f"### 第 {group_no} 組")
                    for row in assigned[group_no]:
                        st.write(f"{row.get('seat_no')} 號｜{row.get('student_name')}")
                if unassigned:
                    st.markdown("### 尚未分組")
                    for row in unassigned:
                        st.write(f"{row.get('seat_no')} 號｜{row.get('student_name')}")
            st.divider()
            st.subheader("小組拍攝資訊")
            groups = get_groups()
            if not groups:
                st.info("目前尚未公布小組拍攝資訊。")
            for group in groups:
                with st.container(border=True):
                    show_group(group)
        except Exception:
            st.error("小組名單讀取失敗，請稍後再試。")

elif role == "admin":
    signup_tab, group_tab, photo_tab, staff_tab = st.tabs(["🧾 小組登記與分組", "📍 拍攝小組管理", "🗂️ 全班照片管理", "🔐 帳號管理"])
    with signup_tab:
        st.subheader("學生小組登記名單")
        st.caption("依系統登記先後排序；管理員可依實際分組狀況調整，不限制每組人數。")
        try:
            signups = admin.table("group_signups").select("*").order("id").execute().data
            if not signups:
                st.info("目前尚無學生登記。")
            else:
                st.write(f"目前共 {len(signups)} 位學生完成登記")
                for signup in signups:
                    sid = signup["id"]
                    current_group = signup.get("assigned_group") or 0
                    label = f"#{sid:03d}｜{signup.get('seat_no')} 號｜{signup.get('student_name')}"
                    with st.container(border=True):
                        left, right = st.columns([3, 2])
                        left.write(label)
                        options = [0] + list(range(1, len(signups) + 2))
                        selected = right.selectbox(
                            "分配組別（0 代表尚未分組）",
                            options,
                            index=options.index(current_group) if current_group in options else 0,
                            format_func=lambda x: "尚未分組" if x == 0 else f"第 {x} 組",
                            key=f"assign_group_{sid}",
                        )
                        if right.button("儲存組別", key=f"save_group_{sid}"):
                            admin.table("group_signups").update({
                                "assigned_group": selected if selected else None
                            }).eq("id", sid).execute()
                            st.success(f"{signup.get('seat_no')} 號已更新分組。")
                            st.rerun()
        except Exception:
            st.error("無法讀取登記名單，請確認已執行 group_signups.sql。")
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

    with staff_tab:
        st.subheader("教師及管理員帳號管理")
        st.caption("帳號資料存放於 Supabase；密碼只保存 PBKDF2 雜湊值，不保存明文。")
        with st.form("create_staff_account", clear_on_submit=True):
            new_username = st.text_input("新帳號")
            new_role_label = st.selectbox("身分", ["教師", "畢冊製作組管理員"])
            new_password = st.text_input("設定密碼（至少 12 個字元）", type="password")
            confirm_password = st.text_input("再次輸入密碼", type="password")
            create_staff = st.form_submit_button("新增帳號")
        if create_staff:
            if not new_username.strip():
                st.warning("請輸入帳號。")
            elif len(new_password) < 12:
                st.warning("密碼至少需要 12 個字元。")
            elif new_password != confirm_password:
                st.warning("兩次輸入的密碼不一致。")
            else:
                try:
                    duplicate = (
                        admin.table("staff_accounts")
                        .select("id")
                        .ilike("username", new_username.strip())
                        .limit(1).execute().data
                    )
                    if duplicate:
                        st.error("這個帳號已經存在，請換一個帳號。")
                    else:
                        admin.table("staff_accounts").insert({
                            "username": new_username.strip(),
                            "role": "teacher" if new_role_label == "教師" else "admin",
                            "password_hash": hash_staff_password(new_password),
                            "is_active": True,
                        }).execute()
                        st.success("帳號已安全寫入 Supabase。")
                        st.rerun()
                except Exception:
                    st.error("新增帳號失敗，請稍後再試。")
        st.divider()
        st.subheader("現有帳號")
        try:
            staff_rows = (
                admin.table("staff_accounts")
                .select("id, username, role, is_active, created_at")
                .order("role")
                .order("username")
                .execute().data
            )
            if not staff_rows:
                st.info("目前沒有管理員或教師帳號。")
            for staff in staff_rows:
                staff_id = staff["id"]
                role_label = "教師" if staff["role"] == "teacher" else "管理員"
                with st.expander(f"{role_label}｜{staff['username']}｜{'啟用中' if staff['is_active'] else '已停用'}"):
                    with st.form(f"edit_staff_{staff_id}"):
                        active_value = st.checkbox("啟用此帳號", value=staff["is_active"])
                        reset_password = st.text_input("更換密碼（留空代表不更換）", type="password")
                        save_staff = st.form_submit_button("儲存帳號設定")
                    if save_staff:
                        try:
                            if staff["role"] == "admin" and staff["is_active"] and not active_value:
                                active_admins = sum(1 for item in staff_rows if item["role"] == "admin" and item["is_active"])
                                if active_admins <= 1:
                                    st.error("至少必須保留一位啟用中的管理員。")
                                    st.stop()
                            updates = {"is_active": active_value, "updated_at": datetime.now(timezone.utc).isoformat()}
                            if reset_password:
                                if len(reset_password) < 12:
                                    st.error("新密碼至少需要 12 個字元。")
                                    st.stop()
                                updates["password_hash"] = hash_staff_password(reset_password)
                            admin.table("staff_accounts").update(updates).eq("id", staff_id).execute()
                            st.success("帳號設定已更新。")
                            st.rerun()
                        except Exception:
                            st.error("帳號更新失敗，請稍後再試。")
        except Exception:
            st.error("無法讀取帳號清單，請稍後再試。")

