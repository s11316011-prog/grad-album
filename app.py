import streamlit as st
import uuid
import hmac
import base64
import hashlib
import json
import re
import secrets
from importlib.metadata import version
from datetime import datetime, timezone, timedelta
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
:root { color-scheme: light !important; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stMainBlockContainer"], [data-testid="stHeader"] {
  color-scheme: light !important;
  background: #f3f8fd !important;
  color: #173b61 !important;
  font-family: 'Noto Sans TC', sans-serif !important;
}
.block-container {max-width:1120px;padding-top:1.5rem;}
/* Keep the school emblem clear of Streamlit's fixed top header. */
[data-testid="stHeader"] {
  position: relative !important;
  z-index: 0 !important;
  background: transparent !important;
}
[data-testid="stMainBlockContainer"] {
  position: relative !important;
  z-index: 1 !important;
  padding-top: 3.5rem !important;
}
[data-testid="stImage"] {
  position: relative !important;
  z-index: 2 !important;
  margin-top: 0.5rem !important;
}
/* Force readable text on every Streamlit content surface, even if the device uses dark mode. */
[data-testid="stAppViewContainer"] :is(p, label, h1, h2, h3, h4, h5, h6, li, summary, .stMarkdown, [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"]) {
  color: #173b61 !important;
}
[data-testid="stWidgetLabel"] *, [data-testid="stMarkdownContainer"] *,
[data-testid="stCaptionContainer"] *, [data-testid="stText"], .stRadio label,
.stCheckbox label, .stSelectbox label, .stTextInput label, .stTextArea label,
.stFileUploader label { color: #173b61 !important; }
/* Inputs */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
  background: #ffffff !important; color: #173b61 !important;
  -webkit-text-fill-color: #173b61 !important; border-color: #b8cde0 !important;
}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {
  color: #6b8197 !important; -webkit-text-fill-color: #6b8197 !important;
}
/* Tabs, buttons, cards, expanders and notices */
[data-testid="stTabs"] button, [data-testid="stBaseButton"],
.stButton button, [data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stAlert"], [data-testid="stNotification"] {
  color: #173b61 !important;
}
.stButton button, [data-testid="stBaseButton"] {
  background: #e3effa !important; border: 1px solid #9bbbd8 !important;
}
.stButton button p, [data-testid="stBaseButton"] p { color: #173b61 !important; }
[data-testid="stTabs"] button p { color: #173b61 !important; }
[data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] {
  background: #ffffff !important; border-color: #c7d9e9 !important;
}
[data-testid="stFileUploader"], [data-testid="stFileUploader"] section,
[data-testid="stDataFrame"], [data-testid="stTable"] {
  background: #ffffff !important; color: #173b61 !important;
}
.hero {text-align:center;color:#173b61;padding:8px 0 20px;}
.hero h1 {font-size:2rem;font-weight:800;color:#173b61 !important;}
.hero p {color:#58738e !important;}
</style>
""", unsafe_allow_html=True)

try:
    from PIL import Image
    from io import BytesIO

    logo = Image.open("fsvs_logo.png").convert("RGBA")
    pixels = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            red, green, blue, alpha = pixels[x, y]
            # Make the near-white outer background transparent.
            if min(red, green, blue) >= 246:
                pixels[x, y] = (red, green, blue, 0)
            elif min(red, green, blue) >= 232 and max(red, green, blue) >= 240:
                opacity = int(255 * (246 - min(red, green, blue)) / 14)
                pixels[x, y] = (red, green, blue, min(alpha, max(0, opacity)))
    logo_bytes = BytesIO()
    logo.save(logo_bytes, format="PNG")
    st.image(logo_bytes.getvalue(), width=88)
except Exception:
    st.image("fsvs_logo.png", width=88)
st.markdown(
    '<div class="hero"><h1>國立鳳山高級商工職業學校</h1>'
    '<p>116級 國三一｜畢業紀念冊照片與拍攝資訊平台</p></div>',
    unsafe_allow_html=True,
)

# Compact live Taiwan date/time, shared by the landing page and all signed-in views.
st.components.v1.html(
    """
    <div id="taiwan-clock" style="
        width:100%; display:flex; justify-content:flex-end; align-items:center;
        gap:6px; color:#718096; font-family:'Noto Sans TC',sans-serif;
        font-size:12px; line-height:20px; white-space:nowrap;
    ">
      <span aria-hidden="true">▦</span>
      <span id="taiwan-date">載入日期…</span>
      <span aria-hidden="true">◷</span>
      <span id="taiwan-time">--:--:--</span>
    </div>
    <script>
      (function () {
        const dateNode = document.getElementById("taiwan-date");
        const timeNode = document.getElementById("taiwan-time");
        const formatter = new Intl.DateTimeFormat("zh-TW", {
          timeZone: "Asia/Taipei", year: "numeric", month: "2-digit",
          day: "2-digit", weekday: "short", hour: "2-digit",
          minute: "2-digit", second: "2-digit", hourCycle: "h23"
        });
        function updateTaiwanClock() {
          const parts = Object.fromEntries(
            formatter.formatToParts(new Date()).map(part => [part.type, part.value])
          );
          dateNode.textContent =
            parts.year + "/" + parts.month + "/" + parts.day + "（" + parts.weekday + "）";
          timeNode.textContent =
            parts.hour + ":" + parts.minute + ":" + parts.second;
        }
        updateTaiwanClock();
        window.setInterval(updateTaiwanClock, 1000);
      })();
    </script>
    """,
    height=26,
    scrolling=False,
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

def verify_staff_account(username: str, password: str, expected_role):
    rows = (
        admin.table("staff_accounts")
        .select("username, display_name, role, password_hash, is_active")
        .eq("username", username.strip())
        .in_("role", expected_role if isinstance(expected_role, (list, tuple)) else [expected_role])
        .limit(1)
        .execute().data
    )
    if not rows or not rows[0].get("is_active"):
        return None
    row = rows[0]
    if verify_staff_password(password, row["password_hash"]):
        return {"username": row["username"], "display_name": row.get("display_name") or row["username"], "role": row["role"]}
    return None

def change_staff_password(username: str, old_password: str, new_password: str):
    rows = (
        admin.table("staff_accounts")
        .select("id, password_hash, is_active")
        .eq("username", username.strip())
        .limit(1)
        .execute().data
    )
    if not rows or not rows[0].get("is_active"):
        return False
    row = rows[0]
    if not verify_staff_password(old_password, row["password_hash"]):
        return False
    admin.table("staff_accounts").update({
        "password_hash": hash_staff_password(new_password)
    }).eq("id", row["id"]).execute()
    return True

def bootstrap_staff_accounts():
    existing = admin.table("staff_accounts").select("id").limit(1).execute().data
    if existing:
        return
    for account in BOOTSTRAP_ADMIN_ACCOUNTS:
        admin.table("staff_accounts").insert({
            "username": account["username"],
            "display_name": account["username"],
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

def upload_announcement_images(notice_id, uploaded_files):
    """Upload announcement images to the private photos bucket and return storage paths."""
    paths = []
    storage = admin.storage.from_(BUCKET)
    allowed_types = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "webp": "image/webp",
    }
    for uploaded in uploaded_files or []:
        extension = uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
        if extension not in allowed_types:
            raise ValueError(f"{uploaded.name}：僅支援 JPG、JPEG、PNG、WEBP。")
        file_bytes = uploaded.getvalue()
        if not file_bytes or len(file_bytes) > MAX_FILE_SIZE:
            raise ValueError(f"{uploaded.name}：圖片不可為空，且單張不得超過 10 MB。")
        path = f"announcements/{notice_id}/{uuid.uuid4().hex}.{extension}"
        storage.upload(path, file_bytes, file_options={"content-type": allowed_types[extension], "upsert": "false"})
        paths.append(path)
    return paths

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
    linked_group = group.get("group_number")
    if linked_group is not None:
        member_rows = (
            admin.table("group_signups")
            .select("student_id, seat_no, student_name")
            .eq("assigned_group", linked_group)
            .order("seat_no").execute().data
        )
        leader_rows = (
            admin.table("group_leaders")
            .select("leader_student_id")
            .eq("group_number", linked_group)
            .limit(1).execute().data
        )
        leader_student_id = leader_rows[0]["leader_student_id"] if leader_rows else None
        if member_rows:
            member_text = "、".join(
                f"{row.get('seat_no')} 號｜{'組長｜' if row.get('student_id') == leader_student_id else ''}{row.get('student_name')}"
                for row in member_rows
            )
        else:
            member_text = "目前尚無組員"
        st.write(f"**實際組員名單（第 {linked_group} 組）：** {member_text}")
    else:
        st.write(f"**組員名單：** {group.get('members') or '尚未連結學生分組'}")
    st.write(f"**注意事項：** {group.get('notes') or '無'}")
    if group.get("photo_path"):
        try:
            st.image(make_url(group["photo_path"]), width=420)
        except Exception:
            st.caption("地點照片目前無法讀取")

role = current_role()

if role is None:
    # 登入前公開資訊：只讀顯示，不提供任何資料修改或照片上傳操作。
    landing_settings = {
        "show_student_announcements": True,
        "show_personal_photo_rules": True,
        "show_class_group_roster": True,
    }
    landing_content = {
        "tab_announcements": "📢 最新公告",
        "announcements_caption": "查看畢冊製作組發布的重要通知、拍攝異動及活動提醒。",
        "announcements_empty": "目前沒有已發布的公告。",
        "announcements_error": "公告讀取失敗，請稍後再試。",
        "announcement_pinned": "📌 置頂",
        "announcement_default_category": "一般通知",
        "announcement_published_at": "發布時間：{published_at}",
        "personal_rules_title": "個人生活照繳交規範",
        "personal_rules_deadline": "每位同學都必須繳交，截止日期為 11 月 13 日。",
        "personal_rules_list": "1. 每位同學都必須繳交個人生活照。\n2. 不可用任何方式遮蓋五官。\n3. 請採用七分身拍攝方式。\n4. 修圖請使用電腦進行，避免手機修圖造成圖片呈現不佳。\n5. 請於 11 月 13 日前至指定網址繳交。",
        "personal_rules_extra": "七分身拍攝範例及指定繳交網址尚待提供，公布後會再補上。",
        "personal_rules_contact": "如有任何問題，請直接提出，或私下向相關負責人反映。",
        "roster_title": "👥 全班分組一覽",
        "roster_caption": "所有同學都可以查看目前各組名單；組長會特別標示。",
        "roster_empty": "目前尚未有學生完成分組。",
        "roster_load_error": "目前無法載入全班分組名單，請稍後重新整理。",
        "roster_unassigned_label": "尚未分組（{count} 位）",
        "roster_group_title": "**第 {group_no} 組**",
        "roster_leader_prefix": "組長｜",
        "roster_member_format": "{seat_no} 號｜{leader_prefix}{name}",
        "roster_unassigned_member_format": "{seat_no} 號｜{name}",
    }
    landing_custom_blocks = []
    try:
        landing_rows = admin.table("site_settings").select("setting_key, setting_value").execute().data
        for row in landing_rows:
            key, value = row.get("setting_key"), row.get("setting_value")
            if key in landing_settings and isinstance(value, bool):
                landing_settings[key] = value
            elif key == "student_page_content" and isinstance(value, dict):
                for content_key in landing_content:
                    if isinstance(value.get(content_key), str):
                        landing_content[content_key] = value[content_key]
            elif key == "student_custom_blocks" and isinstance(value, list):
                landing_custom_blocks = [
                    item for item in value
                    if isinstance(item, dict) and item.get("enabled", True)
                    and str(item.get("title", "")).strip()
                    and isinstance(item.get("content", ""), str)
                ]
    except Exception:
        pass

    def clear_login_inputs(*keys):
        for field_key in keys:
            st.session_state[field_key] = ""

    def toggle_login_panel():
        st.session_state["show_login_panel"] = not st.session_state.get("show_login_panel", False)

    if not st.session_state.get("show_login_panel", False):
        if st.button(":material/door_open: 登入", key="open_login_panel", type="primary", use_container_width=True):
            st.session_state["show_login_panel"] = True
            st.rerun()
    else:
        st.button(":material/keyboard_arrow_up: 收合", key="close_login_panel", use_container_width=True, on_click=toggle_login_panel)
        login_identity = st.radio(
            "請選擇登入身分",
            [":material/person: 學生", ":material/shield_person: 管理員"],
            horizontal=True,
            key="login_identity_selector",
            label_visibility="collapsed",
        )
        st.markdown("---")
        if login_identity == ":material/person: 學生":
            with st.container(border=True):
                st.markdown("## :material/person: 學生登入")
                st.caption("使用個人座號與專屬密碼登入")
                show_student_password = st.checkbox("顯示密碼", key="show_student_login_password")
                with st.form("student_login_form"):
                    seat = st.text_input("學生座號", key="student_seat", placeholder="例如：12")
                    student_password = st.text_input(
                        "個人專屬密碼",
                        type="default" if show_student_password else "password",
                        key="student_pwd",
                        placeholder="請輸入你的密碼",
                    )
                    student_submitted = st.form_submit_button("🎓 登入學生專區", type="primary", use_container_width=True)
                st.button(
                    "清除欄位，重新輸入",
                    key="clear_student_login",
                    use_container_width=True,
                    on_click=clear_login_inputs,
                    args=("student_seat", "student_pwd"),
                )
                if student_submitted:
                    if not seat.strip() or not student_password:
                        st.warning("還差一點！請先填寫座號和個人密碼。")
                    else:
                        try:
                            with st.spinner("正在安全驗證學生身分…"):
                                student = verify_student(seat.strip(), student_password)
                            if student:
                                set_session("student", {
                                    "id": student["id"],
                                    "seat_no": str(student["seat_no"]),
                                    "name": student["name"],
                                })
                                st.rerun()
                            else:
                                st.error("登入沒有成功，請確認座號與密碼是否正確，再試一次。")
                        except Exception as e:
                            st.error("目前無法完成學生登入，請稍後再試。")
                            with st.expander("查看系統診斷資訊"):
                                st.code(f"登入 RPC：{type(e).__name__}: {e}")
                                try:
                                    admin.table("grad_album").select("id").limit(1).execute()
                                    st.success("資料表 API 可正常連線；問題可能集中在登入驗證 RPC。")
                                except Exception as api_error:
                                    st.error("資料表 API 目前也無法連線。")
                                    st.code(f"資料表 API：{type(api_error).__name__}: {api_error}")
                                st.caption("診斷只讀取一筆資料的 id，不會顯示或修改學生個資、密碼或照片。")
                                st.code(
                                    f"SUPABASE_URL = {SUPABASE_URL!r}\\n"
                                    f"REST endpoint = {getattr(admin, 'rest_url', 'SDK 未提供 rest_url 屬性')!r}\\n"
                                    f"supabase package = {version('supabase')}\\n"
                                    f"postgrest package = {version('postgrest')}"
                                )
                with st.expander("🔐 更改學生密碼"):
                    st.caption("請輸入座號及目前密碼驗證身分；新密碼至少 8 個字元。")
                    change_seat = st.text_input("學生座號", key="student_change_seat")
                    old_student_pwd = st.text_input("目前密碼", type="password", key="student_old_pwd")
                    new_student_pwd = st.text_input("新密碼（至少 8 個字元）", type="password", key="student_new_pwd")
                    confirm_student_pwd = st.text_input("再次輸入新密碼", type="password", key="student_confirm_pwd")
                    if st.button("確認更改學生密碼", key="student_change_pwd_button", use_container_width=True):
                        if not all([change_seat.strip(), old_student_pwd, new_student_pwd, confirm_student_pwd]):
                            st.warning("請完整填寫所有欄位。")
                        elif len(new_student_pwd) < 8 or len(new_student_pwd) > 128:
                            st.warning("新密碼長度需為 8～128 個字元。")
                        elif new_student_pwd != confirm_student_pwd:
                            st.error("兩次輸入的新密碼不一致。")
                        else:
                            try:
                                changed = admin.rpc("change_student_password", {
                                    "input_seat_no": change_seat.strip(),
                                    "input_old_password": old_student_pwd,
                                    "input_new_password": new_student_pwd,
                                }).execute().data
                                if changed is True:
                                    st.success("學生密碼已更新，請使用新密碼登入。")
                                else:
                                    st.error("座號或目前密碼錯誤，密碼未變更。")
                            except Exception:
                                st.error("目前無法更改密碼，請稍後再試。")
        else:
            with st.container(border=True):
                st.markdown("## :material/shield_person: 管理員登入")
                st.caption("僅限已授權的管理員帳號使用")
                show_admin_password = st.checkbox("顯示密碼", key="show_admin_login_password")
                with st.form("admin_login_form"):
                    username = st.text_input("管理員帳號", key="admin_user", placeholder="請輸入管理員帳號")
                    admin_password = st.text_input(
                        "管理員密碼",
                        type="default" if show_admin_password else "password",
                        key="admin_pwd",
                        placeholder="請輸入管理員密碼",
                    )
                    admin_submitted = st.form_submit_button("🛡️ 登入管理中心", type="primary", use_container_width=True)
                st.button(
                    "清除欄位，重新輸入",
                    key="clear_admin_login",
                    use_container_width=True,
                    on_click=clear_login_inputs,
                    args=("admin_user", "admin_pwd"),
                )
                if admin_submitted:
                    if not username.strip() or not admin_password:
                        st.warning("請輸入管理員帳號與密碼。")
                    else:
                        try:
                            with st.spinner("正在安全驗證管理員權限…"):
                                matched = verify_staff_account(username.strip(), admin_password, ["admin", "teacher", "super_admin"])
                            if matched:
                                set_session("admin", {
                                    "username": matched["username"],
                                    "display_name": matched.get("display_name") or matched["username"],
                                    "staff_role": matched["role"],
                                })
                                st.rerun()
                            else:
                                st.error("登入未成功，請確認帳號密碼，或聯絡最高權限管理員確認帳號狀態。")
                        except Exception:
                            st.error("管理員登入服務暫時無法使用，請稍後再試。")
                with st.expander("🔐 更改管理員密碼"):
                    st.caption("請使用自己的管理員帳號及目前密碼驗證身分。")
                    change_username = st.text_input("管理員帳號", key="staff_change_username")
                    old_staff_pwd = st.text_input("目前密碼", type="password", key="staff_old_pwd")
                    new_staff_pwd = st.text_input("新密碼（至少 8 個字元）", type="password", key="staff_new_pwd")
                    confirm_staff_pwd = st.text_input("再次輸入新密碼", type="password", key="staff_confirm_pwd")
                    if st.button("確認更改管理員密碼", key="staff_change_pwd_button", use_container_width=True):
                        if not all([change_username.strip(), old_staff_pwd, new_staff_pwd, confirm_staff_pwd]):
                            st.warning("請完整填寫所有欄位。")
                        elif len(new_staff_pwd) < 8 or len(new_staff_pwd) > 128:
                            st.warning("新密碼長度需為 8～128 個字元。")
                        elif new_staff_pwd != confirm_staff_pwd:
                            st.error("兩次輸入的新密碼不一致。")
                        else:
                            try:
                                changed = change_staff_password(change_username, old_staff_pwd, new_staff_pwd)
                                if changed:
                                    st.success("管理員密碼已更新，請使用新密碼登入。")
                                else:
                                    st.error("管理員帳號或目前密碼錯誤，或帳號已停用；密碼未變更。")
                            except Exception:
                                st.error("目前無法更改密碼，請稍後再試。")

    # 最新公告：6 秒自動輪播，支援手動切換、暫停／播放及點擊展開。
    if landing_settings["show_student_announcements"]:
        st.subheader(landing_content["tab_announcements"])
        st.caption(landing_content["announcements_caption"])
        try:
            now_utc = datetime.now(timezone.utc)
            landing_notices = (
                admin.table("announcements")
                .select("id, title, content, category, is_pinned, publish_at, expires_at, image_paths")
                .eq("status", "published")
                .order("is_pinned", desc=True)
                .order("publish_at", desc=True)
                .execute().data
            )
            visible_landing_notices = []
            for notice in landing_notices:
                publish_at = datetime.fromisoformat(notice["publish_at"].replace("Z", "+00:00"))
                expires_at = notice.get("expires_at")
                if publish_at <= now_utc and (
                    not expires_at or datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > now_utc
                ):
                    visible_landing_notices.append({
                        "title": str(notice.get("title") or ""),
                        "content": str(notice.get("content") or ""),
                        "category": str(notice.get("category") or landing_content["announcement_default_category"]),
                        "is_pinned": bool(notice.get("is_pinned")),
                        "published_at": str(notice.get("publish_at") or "")[:16].replace("T", " "),
                        "images": [make_url(path) for path in (notice.get("image_paths") or [])],
                    })

            if not visible_landing_notices:
                st.info(landing_content["announcements_empty"])
            else:
                carousel_data = json.dumps(visible_landing_notices, ensure_ascii=False).replace("<", "\\u003c")
                carousel_html = """
                <div id="announcement-carousel" class="ac-shell">
                  <div class="ac-top">
                    <span class="ac-count" id="ac-count"></span>
                    <span class="ac-status" id="ac-status">自動播放中</span>
                  </div>
                  <section class="ac-card" aria-live="polite">
                    <div class="ac-tags" id="ac-tags"></div>
                    <h3 id="ac-title"></h3>
                    <p class="ac-content" id="ac-content"></p>
                    <div class="ac-images" id="ac-images"></div>
                    <button class="ac-expand" id="ac-expand" type="button" aria-expanded="false">查看完整公告⌄</button>
                    <div class="ac-meta" id="ac-meta"></div>
                  </section>
                  <div class="ac-controls">
                    <button type="button" id="ac-prev" aria-label="上一則公告">‹</button>
                    <div class="ac-dots" id="ac-dots"></div>
                    <button type="button" id="ac-next" aria-label="下一則公告">›</button>
                    <button type="button" id="ac-toggle" class="ac-toggle">暫停</button>
                  </div>
                  <div class="ac-hint">每 6 秒自動切換・滑鼠移入時暫停</div>
                </div>
                <style>
                  * { box-sizing: border-box; }
                  body { margin: 0; font-family: Arial, "Noto Sans TC", sans-serif; background: transparent; }
                  .ac-shell { padding: 14px 16px 10px; border: 1px solid #d7e7f5; border-radius: 18px;
                    background: linear-gradient(135deg,#f1f8ff 0%,#e7f2fc 100%); color: #173b61; }
                  .ac-top,.ac-controls { display:flex; align-items:center; justify-content:space-between; gap:10px; }
                  .ac-count { font-size:12px; color:#54718d; font-weight:700; }
                  .ac-status { font-size:12px; color:#28734d; background:#e4f5eb; padding:4px 9px; border-radius:999px; }
                  .ac-card { min-height:150px; margin-top:10px; padding:18px; border-radius:14px; background:#fff;
                    box-shadow:0 3px 12px rgba(39,83,120,.07); }
                  .ac-tags { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:9px; }
                  .ac-tag { font-size:11px; padding:4px 8px; border-radius:999px; color:#315d83; background:#eaf3fb; }
                  .ac-tag.pin { color:#a13c35; background:#fff0ed; }
                  #ac-title { font-size:19px; line-height:1.45; margin:0 0 8px; color:#173b61; }
                  .ac-content { font-size:14px; line-height:1.75; white-space:pre-wrap; margin:0; color:#405c76;
                    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
                  .ac-content.expanded { display:block; overflow:visible; }
                  .ac-images { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin-top:12px; }
                  .ac-images img { width:100%; max-height:260px; object-fit:contain; border-radius:10px; background:#f4f7fa; }
                  .ac-expand { display:none; border:0; background:transparent; color:#28679b; padding:8px 0 0;
                    font-size:12px; cursor:pointer; }
                  .ac-meta { font-size:11px; color:#8295a8; margin-top:10px; }
                  .ac-controls { justify-content:center; margin-top:12px; }
                  .ac-controls button { cursor:pointer; border:1px solid #d4e3f0; color:#315d83; background:#fff;
                    border-radius:10px; min-width:34px; height:32px; padding:0 10px; font-size:14px; }
                  .ac-controls button:focus-visible,.ac-expand:focus-visible { outline:2px solid #397fba; outline-offset:2px; }
                  .ac-dots { display:flex; gap:6px; align-items:center; justify-content:center; }
                  .ac-dot { width:7px!important; min-width:7px!important; height:7px!important; padding:0!important;
                    border:0!important; border-radius:50%!important; background:#c3d5e5!important; }
                  .ac-dot.active { width:19px!important; border-radius:9px!important; background:#397fba!important; }
                  .ac-controls .ac-toggle { font-size:12px; padding:0 12px; }
                  .ac-hint { text-align:center; font-size:10px; color:#8295a8; margin-top:8px; }
                  @media (prefers-reduced-motion: no-preference) {
                    .ac-card { animation: acFade .28s ease; }
                    @keyframes acFade { from { opacity:.55; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
                  }
                </style>
                <script>
                  const notices = __DATA__;
                  let current = 0, paused = false, hoverPaused = false, expanded = false, timer = null;
                  const el = id => document.getElementById(id);
                  const root = el("announcement-carousel");
                  function render() {
                    const n = notices[current];
                    el("ac-count").textContent = (current + 1) + " / " + notices.length;
                    el("ac-tags").replaceChildren();
                    if (n.is_pinned) {
                      const pin = document.createElement("span"); pin.className = "ac-tag pin"; pin.textContent = "📌 置頂";
                      el("ac-tags").appendChild(pin);
                    }
                    const cat = document.createElement("span"); cat.className = "ac-tag"; cat.textContent = n.category;
                    el("ac-tags").appendChild(cat);
                    el("ac-title").textContent = n.title;
                    el("ac-content").textContent = n.content;
                    el("ac-content").classList.toggle("expanded", expanded);
                    const imageBox = el("ac-images");
                    imageBox.replaceChildren();
                    (n.images || []).forEach(src => {
                      const img = document.createElement("img");
                      img.src = src; img.alt = "公告圖片"; img.loading = "lazy";
                      imageBox.appendChild(img);
                    });
                    const expand = el("ac-expand");
                    expand.style.display = n.content.length > 90 ? "inline-block" : "none";
                    expand.textContent = expanded ? "收合公告內容⌃" : "查看完整公告⌄";
                    expand.setAttribute("aria-expanded", String(expanded));
                    el("ac-meta").textContent = n.published_at ? "發布時間：" + n.published_at : "";
                    el("ac-dots").replaceChildren();
                    notices.forEach((_, i) => {
                      const dot = document.createElement("button"); dot.type = "button";
                      dot.className = "ac-dot" + (i === current ? " active" : "");
                      dot.setAttribute("aria-label", "第 " + (i + 1) + " 則公告");
                      dot.addEventListener("click", () => { current = i; expanded = false; render(); restart(); });
                      el("ac-dots").appendChild(dot);
                    });
                    el("ac-prev").disabled = notices.length < 2;
                    el("ac-next").disabled = notices.length < 2;
                    el("ac-toggle").disabled = notices.length < 2;
                    el("ac-status").textContent = paused ? "手動暫停" : (hoverPaused ? "滑鼠停留，暫停中" : "自動播放中");
                    el("ac-toggle").textContent = paused ? "播放" : "暫停";
                  }
                  function move(step) { current = (current + step + notices.length) % notices.length; expanded = false; render(); restart(); }
                  function restart() {
                    if (timer) {
                      clearInterval(timer);
                      timer = null;
                    }
                    if (notices.length > 1 && !paused && !hoverPaused) {
                      timer = setInterval(() => {
                        current = (current + 1) % notices.length;
                        expanded = false;
                        render();
                      }, 6000);
                    }
                    render();
                  }
                  el("ac-prev").addEventListener("click", () => move(-1));
                  el("ac-next").addEventListener("click", () => move(1));
                  el("ac-toggle").addEventListener("click", () => { paused = !paused; restart(); });
                  el("ac-expand").addEventListener("click", () => { expanded = !expanded; render(); });
                  const announcementCard = root.querySelector(".ac-card");
                  announcementCard.addEventListener("mouseenter", () => { hoverPaused = true; restart(); });
                  announcementCard.addEventListener("mouseleave", () => { hoverPaused = false; restart(); });
                  render(); restart();
                </script>
                """.replace("__DATA__", carousel_data)
                st.components.v1.html(carousel_html, height=440, scrolling=True)
        except Exception:
            st.error(landing_content["announcements_error"])

    if landing_settings["show_personal_photo_rules"]:
        st.divider()
        st.subheader(landing_content["personal_rules_title"])
        st.caption("請先閱讀以下規定，點開各項目即可查看完整說明。")

        deadline_text = str(landing_content.get("personal_rules_deadline", "")).strip()
        rules_text = str(landing_content.get("personal_rules_list", "")).strip()
        extra_text = str(landing_content.get("personal_rules_extra", "")).strip()
        contact_text = str(landing_content.get("personal_rules_contact", "")).strip()

        # 從管理員設定的期限文字擷取月日；若無法辨識，仍完整顯示原始期限文字。
        deadline_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", deadline_text + " " + rules_text)
        if deadline_text:
            st.warning("⏰ " + deadline_text)
        if deadline_match:
            try:
                deadline_month, deadline_day = int(deadline_match.group(1)), int(deadline_match.group(2))
                taiwan_now = datetime.now(timezone.utc) + timedelta(hours=8)
                deadline_date = datetime(taiwan_now.year, deadline_month, deadline_day, 23, 59, 59)
                if deadline_date < taiwan_now.replace(tzinfo=None):
                    deadline_date = datetime(taiwan_now.year + 1, deadline_month, deadline_day, 23, 59, 59)
                remaining = deadline_date - taiwan_now.replace(tzinfo=None)
                remaining_days = remaining.days
                if remaining.total_seconds() >= 0:
                    st.info(f"🗓️ 距離繳交期限約還有 **{remaining_days} 天**（{deadline_date.month} 月 {deadline_date.day} 日截止）")
            except ValueError:
                pass

        # 將管理員編輯的原始規則保留完整內容，並醒目提示含有期限或禁止事項的重點。
        important_lines = [
            line.strip().lstrip("#").strip()
            for line in rules_text.splitlines()
            if line.strip() and any(word in line for word in ("必須", "不可", "不得", "禁止", "截止", "期限", "務必"))
        ]
        if important_lines:
            with st.container(border=True):
                st.markdown("**⚠️ 重點提醒**")
                for important_line in important_lines:
                    st.markdown(f"- {important_line}")

        with st.expander("📋 照片規定與注意事項", expanded=False):
            st.markdown(rules_text if rules_text else "目前尚未設定照片注意事項。")
        if extra_text:
            with st.expander("💡 補充說明", expanded=False):
                st.markdown(extra_text)
        if contact_text:
            with st.expander("✉️ 聯絡方式與問題反映", expanded=False):
                st.markdown(contact_text)

    for custom_block in landing_custom_blocks:
        st.divider()
        with st.container(border=True):
            st.subheader(str(custom_block.get("title", "班級資訊"))[:80])
            st.markdown(str(custom_block.get("content", "")))

    if landing_settings["show_class_group_roster"]:
        st.divider()
        st.subheader(landing_content["roster_title"])
        st.caption(landing_content["roster_caption"])
        try:
            landing_students = admin.table("grad_album").select("id, seat_no, name").order("seat_no").execute().data
            landing_signups = admin.table("group_signups").select("student_id, assigned_group").execute().data
            landing_leader_rows = admin.table("group_leaders").select("group_number, leader_student_id").execute().data
            landing_leaders = {item["group_number"]: item["leader_student_id"] for item in landing_leader_rows}
            landing_groups = {}
            landing_assigned_ids = set()
            for signup in landing_signups:
                group_no, student_id = signup.get("assigned_group"), signup.get("student_id")
                if group_no is not None and student_id is not None:
                    landing_groups.setdefault(group_no, []).append(student_id)
                    landing_assigned_ids.add(student_id)
            landing_unassigned = [item for item in landing_students if item.get("id") not in landing_assigned_ids]
            total_group_members = sum(len(set(ids)) for ids in landing_groups.values())
            stats_cols = st.columns(3)
            stats_cols[0].metric("分組數", f"{len(landing_groups)} 組")
            stats_cols[1].metric("已分組", f"{total_group_members} 人")
            stats_cols[2].metric("未分組", f"{len(landing_unassigned)} 人")
            roster_search = st.text_input(
                "🔎 搜尋組員姓名或座號",
                placeholder="輸入姓名或座號，例如：王小明、12",
                key="public_group_roster_search",
            ).strip().casefold()
            if landing_groups:
                group_numbers = sorted(landing_groups)
                landing_columns = st.columns(min(3, len(group_numbers)))
                for index, group_no in enumerate(group_numbers):
                    with landing_columns[index % len(landing_columns)]:
                        member_ids = set(landing_groups[group_no])
                        group_members = [member for member in landing_students if member.get("id") in member_ids]
                        filtered_members = [
                            member for member in group_members
                            if not roster_search
                            or roster_search in str(member.get("name", "")).casefold()
                            or roster_search in str(member.get("seat_no", "")).casefold()
                        ]
                        with st.container(border=True):
                            st.markdown(landing_content["roster_group_title"].format(group_no=group_no))
                            st.caption(f"👥 {len(group_members)} 位組員")
                            if roster_search and not filtered_members:
                                st.caption("沒有符合搜尋條件的組員")
                            for member in filtered_members:
                                is_leader = member.get("id") == landing_leaders.get(group_no)
                                if is_leader:
                                    st.markdown(f"組長：**{member.get('seat_no')} 號｜{member.get('name')}**")
                                else:
                                    st.write(landing_content["roster_member_format"].format(
                                        seat_no=member.get("seat_no"),
                                        leader_prefix="",
                                        name=member.get("name"),
                                    ))
            else:
                st.info(landing_content["roster_empty"])
            if landing_unassigned:
                matching_unassigned = [
                    member for member in landing_unassigned
                    if not roster_search
                    or roster_search in str(member.get("name", "")).casefold()
                    or roster_search in str(member.get("seat_no", "")).casefold()
                ]
                with st.expander(landing_content["roster_unassigned_label"].format(count=len(landing_unassigned))):
                    if roster_search and not matching_unassigned:
                        st.caption("沒有符合搜尋條件的未分組學生")
                    for member in matching_unassigned:
                        st.write(landing_content["roster_unassigned_member_format"].format(
                            seat_no=member.get("seat_no"), name=member.get("name")
                        ))
        except Exception:
            st.warning(landing_content["roster_load_error"])

    st.divider()
    st.markdown("""
    <style>
    @media (max-width: 700px) {
      [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.8rem !important; }
      [data-testid="stHorizontalBlock"] > [data-testid="column"] { flex: 1 1 100% !important; min-width: 100% !important; }
    }
    </style>
    """, unsafe_allow_html=True)

identity = st.session_state.get("identity") or {}
shared_student_content = {}
if role == "student":
    try:
        shared_content_rows = admin.table("site_settings").select("setting_value").eq("setting_key", "student_page_content").limit(1).execute().data
        if shared_content_rows and isinstance(shared_content_rows[0].get("setting_value"), dict):
            shared_student_content = shared_content_rows[0]["setting_value"]
    except Exception:
        pass

def student_ui_text(key, default):
    value = shared_student_content.get(key, default)
    return value if isinstance(value, str) else default

def queue_action_success(message):
    """Keep success feedback visible after the page reruns."""
    st.session_state["_action_success_notice"] = str(message)

if role is not None:
    pending_action_notice = st.session_state.pop("_action_success_notice", None)
    if pending_action_notice:
        st.success(pending_action_notice)
    st.caption(student_ui_text("login_session_caption", "登入有效時間：30 分鐘") if role == "student" else "登入有效時間：30 分鐘")
    if role == "student":
        st.success(student_ui_text("student_login_success", "學生登入成功：{seat_no} 號｜{name}").format(seat_no=identity['seat_no'], name=identity['name']))
    
    # 統一的帳號工具列：三個按鈕維持相同尺寸，並預留足夠寬度容納「更改密碼」。
    toolbar_spacer, refresh_col, password_col, logout_col = st.columns([5, 1.6, 1.6, 1.6])
    with refresh_col:
        if st.button(
            "刷新",
            icon=":material/refresh:",
            help="重新載入頁面資料，保留目前登入狀態",
            use_container_width=True,
            key="refresh_page_button",
        ):
            # 清除資料快取後重新執行頁面；保留登入 session 與目前身分。
            st.cache_data.clear()
            st.session_state["_refresh_completed_notice"] = True
            st.rerun()
    if st.session_state.pop("_refresh_completed_notice", False):
        st.toast("資料已重新載入，登入狀態已保留。", icon="🔄")
    with password_col:
        password_open = st.session_state.get("show_change_password_form", False)
        password_button_label = (
            student_ui_text("change_password_button", "更改密碼") if role == "student" else "更改密碼"
        )
        if st.button(
            password_button_label,
            icon=":material/lock:",
            help="開啟或收合密碼修改表單",
            use_container_width=True,
            key="toggle_change_password",
        ):
            st.session_state["show_change_password_form"] = not password_open
    with logout_col:
        if st.button(
            student_ui_text("logout_button", "登出") if role == "student" else "登出",
            icon=":material/logout:",
            help="結束目前登入",
            use_container_width=True,
            key="logout_button",
        ):
            logout()
    
    if st.session_state.get("show_change_password_form", False):
        with st.container(border=True):
            st.markdown(student_ui_text("password_title", "### 🔐 更改密碼") if role == "student" else "### 🔐 更改密碼")
            if role == "student":
                st.caption(student_ui_text("password_student_caption", "請輸入目前密碼及新密碼完成修改。"))
                old_pwd = st.text_input(student_ui_text("password_current_label", "目前密碼"), type="password", key="logged_student_old_pwd")
                new_pwd = st.text_input(student_ui_text("password_new_label", "新密碼（8～128 個字元）"), type="password", key="logged_student_new_pwd")
                confirm_pwd = st.text_input(student_ui_text("password_confirm_label", "再次輸入新密碼"), type="password", key="logged_student_confirm_pwd")
                if st.button(student_ui_text("password_submit_button", "確認更改密碼"), type="primary", key="logged_student_change_pwd"):
                    if not all([old_pwd, new_pwd, confirm_pwd]):
                        st.warning(student_ui_text("password_fill_warning", "請完整填寫所有欄位。"))
                    elif not 8 <= len(new_pwd) <= 128:
                        st.warning(student_ui_text("password_length_warning", "新密碼長度需為 8～128 個字元。"))
                    elif new_pwd != confirm_pwd:
                        st.error(student_ui_text("password_mismatch_error", "兩次輸入的新密碼不一致。"))
                    else:
                        try:
                            changed = admin.rpc("change_student_password", {
                                "input_seat_no": str(identity["seat_no"]),
                                "input_old_password": old_pwd,
                                "input_new_password": new_pwd,
                            }).execute().data
                            if changed is True:
                                st.success(student_ui_text("password_success", "密碼已更新，請下次使用新密碼登入。") if role == "student" else "密碼已更新，請下次使用新密碼登入。")
                                st.session_state["show_change_password_form"] = False
                            else:
                                st.error(student_ui_text("password_wrong_error", "目前密碼錯誤，密碼未變更。"))
                        except Exception:
                            st.error(student_ui_text("password_general_error", "目前無法更改密碼，請稍後再試。"))
            else:
                st.caption("正在修改目前登入的管理員帳號密碼。")
                old_pwd = st.text_input("目前密碼", type="password", key="logged_staff_old_pwd")
                new_pwd = st.text_input("新密碼（8～128 個字元）", type="password", key="logged_staff_new_pwd")
                confirm_pwd = st.text_input("再次輸入新密碼", type="password", key="logged_staff_confirm_pwd")
                if st.button("確認更改密碼", type="primary", key="logged_staff_change_pwd"):
                    if not all([old_pwd, new_pwd, confirm_pwd]):
                        st.warning("請完整填寫所有欄位。")
                    elif not 8 <= len(new_pwd) <= 128:
                        st.warning("新密碼長度需為 8～128 個字元。")
                    elif new_pwd != confirm_pwd:
                        st.error("兩次輸入的新密碼不一致。")
                    else:
                        try:
                            changed = change_staff_password(identity.get("username", ""), old_pwd, new_pwd)
                            if changed:
                                st.success("密碼已更新，請下次使用新密碼登入。")
                                st.session_state["show_change_password_form"] = False
                            else:
                                st.error("目前密碼錯誤或帳號已停用，密碼未變更。")
                        except Exception:
                            st.error("目前無法更改密碼，請稍後再試。")
    
if role == "student":
    student_display_defaults = {
        "show_class_group_roster": True, "show_student_announcements": True,
        "show_personal_photo_upload": True, "show_my_photos": True,
        "show_group_signup": True, "show_class_group_photo": True,
        "show_personal_photo_rules": True,
    }
    student_display_settings = dict(student_display_defaults)
    student_custom_blocks = []
    student_content_defaults = {
        "class_photo_date": "11 月 6 日（星期五）", "class_photo_time": "上午 08:20",
        "class_photo_location": "健康中心旁的小石桌", "class_photo_clothing": "請穿著制服",
        "class_photo_count": "3 張", "class_photo_actions": "1. YA 手勢\n2. 小愛心\n3. 戳臉",
        "class_photo_notice": "請依照集合時間準時到場；如有異動，請留意畢冊製作組後續公告。",
        "group_notice": "小組拍攝注意事項\n\n（1）需要 4 張\n\n（2）動作需自行決定",
        "personal_rules_deadline": "每位同學都必須繳交，截止日期為 11 月 13 日。",
        "personal_rules_list": "1. 每位同學都必須繳交個人生活照。\n2. 不可用任何方式遮蓋五官。\n3. 請採用七分身拍攝方式。\n4. 修圖請使用電腦進行，避免手機修圖造成圖片呈現不佳。\n5. 請於 11 月 13 日前至指定網址繳交。",
        "personal_rules_extra": "七分身拍攝範例及指定繳交網址尚待提供，公布後會再補上。",
        "personal_rules_contact": "如有任何問題，請直接提出，或私下向相關負責人反映。",
        "roster_title": "👥 全班分組一覽",
        "roster_caption": "所有同學都可以查看目前各組名單；組長會特別標示。",
        "roster_empty": "目前尚未有學生完成分組。",
        "roster_load_error": "目前無法載入全班分組名單，請稍後重新整理。",
        "roster_unassigned_label": "尚未分組（{count} 位）",
        "tab_announcements": "📢 最新公告",
        "tab_personal_upload": "📤 個人生活照繳交",
        "tab_my_photos": "🖼️ 我的照片",
        "tab_group_signup": "👥 分組登記&小組照繳交",
        "tab_class_photo": "📸 班級團體照",
        "tab_personal_rules": "📝 個人生活照須知",
        "no_student_sections": "目前沒有開放顯示的學生頁面內容，請聯絡管理員。",
        "upload_title": "上傳個人生活照",
        "upload_intro": "每位同學都必須繳交個人生活照，請先閱讀「個人生活照須知」再上傳。",
        "upload_file_help": "可多選 JPG、PNG、WEBP，每張上限 10 MB",
        "upload_button": "確認上傳",
        "upload_choose_warning": "請先選擇照片。",
        "upload_file_error": "{filename}：{error}",
        "upload_fail": "{filename} 上傳失敗，請稍後再試。",
        "upload_success": "成功上傳 {count} 張照片。",
        "my_photos_title": "我的照片",
        "my_photos_empty": "目前還沒有上傳照片。",
        "my_photos_error": "照片讀取失敗，請稍後再試。",
        "class_photo_title": "班級團體照拍攝公告",
        "class_photo_actions_label": "**指定動作：**",
        "announcements_caption": "查看畢冊製作組發布的重要通知、拍攝異動及活動提醒。",
        "announcements_empty": "目前沒有已發布的公告。",
        "announcement_pinned": "📌 置頂",
        "announcement_default_category": "一般通知",
        "announcement_published_at": "發布時間：{published_at}",
        "announcements_error": "公告讀取失敗，請稍後再試。",
        "group_signup_title": "小組合照繳交區",
        "group_leader_label": "組長：**{seat_no} 號｜{name}**",
        "group_signup_caption": "由組長建立小組，輸入其他組員的座號即可。系統會自動帶入正確姓名，並將整組名單一次送出。",
        "group_joined": "你已加入第 {group_no} 組，不能再加入其他組別。",
        "group_member_title": "**第 {group_no} 組組員名單**",
        "group_photo_title": "### 📷 本組小組合照（共 4 張）",
        "group_leader_missing": "本組組長尚未完成上傳權限登記，請聯絡管理員協助設定。",
        "group_photo_leader_help": "由組長統一上傳本組 4 張照片。每個欄位可重新上傳替換；每張上限 10 MB。",
        "group_photo_member_help": "本組照片由組長統一上傳，你可以查看目前繳交進度。",
        "group_photo_slot": "**第 {slot} 張**",
        "group_photo_uploaded": "已繳交",
        "group_photo_missing": "尚未繳交",
        "group_photo_choose": "選擇第 {slot} 張",
        "group_photo_upload": "上傳／替換第 {slot} 張",
        "group_photo_success": "第 {slot} 張小組照已上傳。",
        "group_photo_fail": "第 {slot} 張照片上傳失敗，請稍後再試。",
        "group_photo_error": "小組照片讀取失敗，請稍後再試。",
        "group_member_input": "其他組員座號",
        "group_member_placeholder": "例如：2、5、8\n也可以每行輸入一個座號",
        "group_member_help": "不用輸入自己的座號，系統會自動把你列為組長。可用逗號、頓號或換行分隔。",
        "group_submit": "確認組隊並送出",
        "group_need_member": "請至少輸入一位其他組員的座號。",
        "group_self_member": "不用輸入自己的座號，系統會自動加入組長。",
        "group_success": "組隊成功！第 {group_no} 組，共 {member_count} 位組員。",
        "group_duplicate_error": "送出失敗：組員名單有重複，或有人已經加入其他小組。請重新確認座號。",
        "group_seat_error": "送出失敗：有座號查不到，請確認座號是否正確。",
        "group_submit_error": "小組送出失敗，請稍後重試；若持續發生，請聯絡畢冊製作組。",
        "group_load_error": "小組組隊功能目前無法讀取資料，請稍後再試或聯絡畢冊製作組。",
        "personal_rules_title": "個人生活照繳交規範",
        "roster_group_title": "**第 {group_no} 組**",
        "roster_leader_prefix": "組長｜",
        "roster_member_format": "{seat_no} 號｜{leader_prefix}{name}",
        "roster_unassigned_member_format": "{seat_no} 號｜{name}",
        "class_photo_date_label": "**拍攝日期：**",
        "class_photo_time_label": "**集合時間：**",
        "class_photo_location_label": "**集合地點：**",
        "class_photo_clothing_label": "**服裝要求：**",
        "class_photo_count_label": "**預計拍攝：**",
        "group_photo_upload_error": "{error}",
        "login_session_caption": "登入有效時間：30 分鐘",
        "student_login_success": "學生登入成功：{seat_no} 號｜{name}",
        "refresh_button": "🔄 刷新",
        "change_password_button": "🔐 更改密碼",
        "logout_button": "登出",
        "password_title": "### 🔐 更改密碼",
        "password_student_caption": "請輸入目前密碼及新密碼完成修改。",
        "password_current_label": "目前密碼",
        "password_new_label": "新密碼（8～128 個字元）",
        "password_confirm_label": "再次輸入新密碼",
        "password_submit_button": "確認更改密碼",
        "password_fill_warning": "請完整填寫所有欄位。",
        "password_length_warning": "新密碼長度需為 8～128 個字元。",
        "password_mismatch_error": "兩次輸入的新密碼不一致。",
        "password_success": "密碼已更新，請下次使用新密碼登入。",
        "password_wrong_error": "目前密碼錯誤，密碼未變更。",
        "password_general_error": "目前無法更改密碼，請稍後再試。",
    }
    try:
        saved_display_rows = admin.table("site_settings").select("setting_key, setting_value").execute().data
        for saved_row in saved_display_rows:
            saved_key, saved_value = saved_row.get("setting_key"), saved_row.get("setting_value")
            if saved_key in student_display_settings and isinstance(saved_value, bool):
                student_display_settings[saved_key] = saved_value
            elif saved_key == "student_page_content" and isinstance(saved_value, dict):
                for content_key, content_value in saved_value.items():
                    if content_key in student_content_defaults and isinstance(content_value, str):
                        student_content_defaults[content_key] = content_value
            elif saved_key == "student_custom_blocks" and isinstance(saved_value, list):
                student_custom_blocks = [
                    item for item in saved_value
                    if isinstance(item, dict) and str(item.get("title", "")).strip()
                    and isinstance(item.get("content", ""), str)
                ]
    except Exception:
        pass
    student_content = student_content_defaults
    for custom_block in student_custom_blocks:
        if custom_block.get("enabled", True):
            with st.container(border=True):
                st.subheader(str(custom_block.get("title", "班級資訊"))[:80])
                st.markdown(str(custom_block.get("content", "")))
    show_class_group_roster = student_display_settings["show_class_group_roster"]
    if show_class_group_roster:
        st.subheader(student_content["roster_title"])
        st.caption(student_content["roster_caption"])
        try:
            roster_students = (
                admin.table("grad_album")
                .select("id, seat_no, name")
                .order("seat_no").execute().data
            )
            roster_signups = (
                admin.table("group_signups")
                .select("student_id, assigned_group")
                .execute().data
            )
            roster_leader_rows = admin.table("group_leaders").select("group_number, leader_student_id").execute().data
            roster_leaders = {item["group_number"]: item["leader_student_id"] for item in roster_leader_rows}
            roster_groups = {}
            roster_assigned_ids = set()
            for signup in roster_signups:
                group_no = signup.get("assigned_group")
                student_id = signup.get("student_id")
                if group_no is not None and student_id is not None:
                    roster_groups.setdefault(group_no, []).append(student_id)
                    roster_assigned_ids.add(student_id)
            roster_unassigned = [student for student in roster_students if student.get("id") not in roster_assigned_ids]
            total_group_members = sum(len(set(ids)) for ids in roster_groups.values())
            stats_cols = st.columns(3)
            stats_cols[0].metric("分組數", f"{len(roster_groups)} 組")
            stats_cols[1].metric("已分組", f"{total_group_members} 人")
            stats_cols[2].metric("未分組", f"{len(roster_unassigned)} 人")
            roster_search = st.text_input(
                "🔎 搜尋組員姓名或座號",
                placeholder="輸入姓名或座號，例如：王小明、12",
                key="student_group_roster_search",
            ).strip().casefold()
            if roster_groups:
                group_numbers = sorted(roster_groups)
                group_columns = st.columns(min(3, len(group_numbers)))
                for index, group_no in enumerate(group_numbers):
                    with group_columns[index % len(group_columns)]:
                        member_ids = set(roster_groups[group_no])
                        group_members = [student for student in roster_students if student.get("id") in member_ids]
                        filtered_members = [
                            member for member in group_members
                            if not roster_search
                            or roster_search in str(member.get("name", "")).casefold()
                            or roster_search in str(member.get("seat_no", "")).casefold()
                        ]
                        with st.container(border=True):
                            st.markdown(student_content["roster_group_title"].format(group_no=group_no))
                            st.caption(f"👥 {len(group_members)} 位組員")
                            if roster_search and not filtered_members:
                                st.caption("沒有符合搜尋條件的組員")
                            for member in filtered_members:
                                is_leader = member.get("id") == roster_leaders.get(group_no)
                                if is_leader:
                                    st.markdown(f"組長：**{member.get('seat_no')} 號｜{member.get('name')}**")
                                else:
                                    st.write(student_content["roster_member_format"].format(
                                        seat_no=member.get("seat_no"), leader_prefix="", name=member.get("name")
                                    ))
            else:
                st.info(student_content["roster_empty"])
            if roster_unassigned:
                matching_unassigned = [
                    student for student in roster_unassigned
                    if not roster_search
                    or roster_search in str(student.get("name", "")).casefold()
                    or roster_search in str(student.get("seat_no", "")).casefold()
                ]
                with st.expander(student_content["roster_unassigned_label"].format(count=len(roster_unassigned))):
                    if roster_search and not matching_unassigned:
                        st.caption("沒有符合搜尋條件的未分組學生")
                    for student in matching_unassigned:
                        st.write(student_content["roster_unassigned_member_format"].format(
                            seat_no=student.get("seat_no"), name=student.get("name")
                        ))
        except Exception:
            st.warning(student_content["roster_load_error"])
    
    student_tab_specs = [
        ("show_student_announcements", student_content["tab_announcements"]),
        ("show_personal_photo_upload", student_content["tab_personal_upload"]),
        ("show_my_photos", student_content["tab_my_photos"]),
        ("show_group_signup", student_content["tab_group_signup"]),
    ]
    visible_student_tabs = [(key, label) for key, label in student_tab_specs if student_display_settings[key]]
    if visible_student_tabs:
        student_tab_objects = st.tabs([label for _, label in visible_student_tabs])
        student_tab_map = {key: tab for (key, _), tab in zip(visible_student_tabs, student_tab_objects)}
    else:
        student_tab_map = {}
        st.info(student_content["no_student_sections"])
    if "show_personal_photo_upload" in student_tab_map:
        with student_tab_map["show_personal_photo_upload"]:
            st.subheader(student_content["upload_title"])
            st.info(student_content["upload_intro"])
            files = st.file_uploader(
                student_content["upload_file_help"],
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
            )
            if st.button(student_content["upload_button"], type="primary"):
                if not files:
                    st.warning(student_content["upload_choose_warning"])
                else:
                    count = 0
                    for file in files:
                        data, mime, error = image_info(file)
                        if error:
                            st.error(student_content["upload_file_error"].format(filename=file.name, error=error))
                            continue
                        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
                        path = f"{identity['seat_no']}/{uuid.uuid4().hex}.{ext}"
                        try:
                            upload_photo(path, data, mime)
                            count += 1
                        except Exception:
                            st.error(student_content["upload_fail"].format(filename=file.name))
                    if count:
                        queue_action_success(student_content["upload_success"].format(count=count))
                        st.rerun()
    if "show_my_photos" in student_tab_map:
        with student_tab_map["show_my_photos"]:
            st.subheader(student_content["my_photos_title"])
            try:
                paths = list_student_photos(identity["seat_no"])
                if not paths:
                    st.info(student_content["my_photos_empty"])
                else:
                    cols = st.columns(3)
                    for i, path in enumerate(paths):
                        with cols[i % 3]:
                            st.image(make_url(path), use_container_width=True)
            except Exception:
                st.error(student_content["my_photos_error"])
    if "show_student_announcements" in student_tab_map:
        with student_tab_map["show_student_announcements"]:
            st.subheader(student_content["tab_announcements"])
            st.caption(student_content["announcements_caption"])
            try:
                now_utc = datetime.now(timezone.utc)
                notices = (
                    admin.table("announcements")
                    .select("id, title, content, category, is_pinned, publish_at, expires_at, image_paths")
                    .eq("status", "published")
                    .order("is_pinned", desc=True)
                    .order("publish_at", desc=True)
                    .execute().data
                )
                visible_notices = []
                for notice in notices:
                    publish_at = datetime.fromisoformat(notice["publish_at"].replace("Z", "+00:00"))
                    expires_at = notice.get("expires_at")
                    if publish_at <= now_utc and (
                        not expires_at or datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > now_utc
                    ):
                        visible_notices.append(notice)
                if not visible_notices:
                    st.info(student_content["announcements_empty"])
                for notice in visible_notices:
                    with st.container(border=True):
                        flags = []
                        if notice.get("is_pinned"):
                            flags.append(student_content["announcement_pinned"])
                        flags.append(notice.get("category") or student_content["announcement_default_category"])
                        st.markdown(f"### {' '.join(flags)}")
                        st.markdown(f"**{notice['title']}**")
                        st.write(notice["content"])
                        for image_path in (notice.get("image_paths") or []):
                            try:
                                st.image(make_url(image_path), use_container_width=True)
                            except Exception:
                                st.caption("公告圖片暫時無法載入")
                        st.caption(student_content["announcement_published_at"].format(published_at=notice['publish_at'][:16].replace('T', ' ')))
            except Exception:
                st.error(student_content["announcements_error"])
    if "show_group_signup" in student_tab_map:
        with student_tab_map["show_group_signup"]:
            st.subheader(student_content["group_signup_title"])
            st.info(student_content["group_notice"])
            st.write(student_content["group_leader_label"].format(seat_no=identity['seat_no'], name=identity['name']))
            st.caption(student_content["group_signup_caption"])
            try:
                my_group_rows = (
                    admin.table("group_signups")
                    .select("assigned_group")
                    .eq("student_id", identity["id"])
                    .limit(1).execute().data
                )
                if my_group_rows and my_group_rows[0].get("assigned_group"):
                    my_group_no = my_group_rows[0]["assigned_group"]
                    st.success(student_content["group_joined"].format(group_no=my_group_no))
                    member_rows = (
                        admin.table("group_signups")
                        .select("student_id, seat_no, student_name")
                        .eq("assigned_group", my_group_no)
                        .order("seat_no").execute().data
                    )
                    display_leader_rows = (
                        admin.table("group_leaders")
                        .select("leader_student_id")
                        .eq("group_number", my_group_no)
                        .limit(1).execute().data
                    )
                    display_leader_id = display_leader_rows[0]["leader_student_id"] if display_leader_rows else None
                    st.markdown(student_content["group_member_title"].format(group_no=my_group_no))
                    for member in member_rows:
                        if member.get("student_id") == display_leader_id:
                            st.markdown(f"組長：**{member['seat_no']} 號｜{member['student_name']}**")
                        else:
                            st.write(f"{member['seat_no']} 號｜{member['student_name']}")

                    st.divider()
                    st.markdown(student_content["group_photo_title"])
                    try:
                        leader_rows = (
                            admin.table("group_leaders")
                            .select("leader_student_id")
                            .eq("group_number", my_group_no)
                            .limit(1).execute().data
                        )
                        photo_rows = (
                            admin.table("group_photos")
                            .select("photo_slot, storage_path")
                            .eq("group_number", my_group_no)
                            .order("photo_slot").execute().data
                        )
                        photo_by_slot = {row["photo_slot"]: row for row in photo_rows}
                        is_group_leader = bool(
                            leader_rows and leader_rows[0]["leader_student_id"] == identity["id"]
                        )
                        if not leader_rows:
                            st.warning(student_content["group_leader_missing"])
                        elif is_group_leader:
                            st.caption(student_content["group_photo_leader_help"])
                        else:
                            st.caption(student_content["group_photo_member_help"])
                        photo_cols = st.columns(4)
                        for slot in range(1, 5):
                            with photo_cols[slot - 1]:
                                st.markdown(student_content["group_photo_slot"].format(slot=slot))
                                existing_photo = photo_by_slot.get(slot)
                                if existing_photo:
                                    st.image(make_url(existing_photo["storage_path"]), use_container_width=True)
                                    st.success(student_content["group_photo_uploaded"])
                                else:
                                    st.info(student_content["group_photo_missing"])
                                if is_group_leader:
                                    chosen_photo = st.file_uploader(
                                        student_content["group_photo_choose"].format(slot=slot),
                                        type=["jpg", "jpeg", "png", "webp"],
                                        key=f"group_photo_file_{my_group_no}_{slot}",
                                    )
                                    if st.button(
                                        student_content["group_photo_upload"].format(slot=slot),
                                        key=f"group_photo_upload_{my_group_no}_{slot}",
                                        disabled=chosen_photo is None,
                                    ):
                                        photo_data, photo_mime, photo_error = image_info(chosen_photo)
                                        if photo_error:
                                            st.error(student_content["group_photo_upload_error"].format(error=photo_error))
                                        else:
                                            extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[photo_mime]
                                            new_path = f"shoot_groups/{my_group_no}/{slot}_{uuid.uuid4().hex}.{extension}"
                                            try:
                                                upload_photo(new_path, photo_data, photo_mime)
                                                old_path = existing_photo.get("storage_path") if existing_photo else None
                                                admin.table("group_photos").upsert({
                                                    "group_number": my_group_no,
                                                    "photo_slot": slot,
                                                    "leader_student_id": identity["id"],
                                                    "storage_path": new_path,
                                                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                                                }, on_conflict="group_number,photo_slot").execute()
                                                if old_path:
                                                    admin.storage.from_(BUCKET).remove([old_path])
                                                queue_action_success(student_content["group_photo_success"].format(slot=slot))
                                                st.rerun()
                                            except Exception:
                                                st.error(student_content["group_photo_fail"].format(slot=slot))
                    except Exception:
                        st.error(student_content["group_photo_error"])
                else:
                    with st.form("student_create_group_form"):
                        member_seats_text = st.text_area(
                            student_content["group_member_input"],
                            placeholder=student_content["group_member_placeholder"],
                            help=student_content["group_member_help"],
                        )
                        confirm_group = st.form_submit_button(student_content["group_submit"], type="primary")
                    if confirm_group:
                        import re
                        member_seats = [
                            value for value in re.split(r"[,，、\s]+", member_seats_text.strip())
                            if value
                        ]
                        if not member_seats:
                            st.warning(student_content["group_need_member"])
                        elif str(identity["seat_no"]).strip() in member_seats:
                            st.error(student_content["group_self_member"])
                        else:
                            try:
                                result = admin.rpc(
                                    "submit_student_group",
                                    {
                                        "input_leader_student_id": identity["id"],
                                        "input_member_seat_numbers": member_seats,
                                    },
                                ).execute()
                                submitted_group = result.data[0]
                                admin.table("group_leaders").upsert({
                                    "group_number": submitted_group["group_number"],
                                    "leader_student_id": identity["id"],
                                }, on_conflict="group_number").execute()
                                queue_action_success(
                                    student_content["group_success"].format(group_no=submitted_group['group_number'], member_count=submitted_group['member_count'])
                                )
                                st.rerun()
                            except Exception as submit_error:
                                error_text = str(submit_error)
                                if "已經加入其他小組" in error_text or "重複" in error_text:
                                    st.error(student_content["group_duplicate_error"])
                                elif "座號不存在" in error_text:
                                    st.error(student_content["group_seat_error"])
                                else:
                                    st.error(student_content["group_submit_error"])
            except Exception:
                st.error(student_content["group_load_error"])

elif role == "teacher":
    roster_tab, photo_tab = st.tabs(["👥 小組分組名單", "🖼️ 全班照片查詢"])
    with photo_tab:
        st.subheader("全班學生照片")
        st.caption("管理員僅能查看照片，沒有下載、刪除或修改權限。")
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
        st.caption("此頁僅供查詢，管理員無法調整學生組別或修改拍攝資訊。")
        try:
            signups = (
                admin.table("group_signups")
                .select("id, student_id, seat_no, student_name, assigned_group")
                .order("id")
                .execute().data
            )
            students = (
                admin.table("grad_album")
                .select("id, seat_no, name")
                .order("seat_no")
                .execute().data
            )
            assigned = {}
            assigned_student_ids = set()
            for row in signups:
                group_no = row.get("assigned_group")
                if group_no is not None:
                    assigned.setdefault(group_no, []).append(row)
                    assigned_student_ids.add(row.get("student_id"))
            leader_records_for_roster = admin.table("group_leaders").select("group_number, leader_student_id").execute().data
            roster_leaders = {item["group_number"]: item["leader_student_id"] for item in leader_records_for_roster}
            for group_no in sorted(assigned):
                st.markdown(f"### 第 {group_no} 組")
                for row in assigned[group_no]:
                    if row.get("student_id") == roster_leaders.get(group_no):
                        st.markdown(f"組長：**{row.get('seat_no')} 號｜{row.get('student_name')}**")
                    else:
                        st.write(f"{row.get('seat_no')} 號｜{row.get('student_name')}")
            unassigned_students = [
                student for student in students
                if student.get("id") not in assigned_student_ids
            ]
            if unassigned_students:
                st.markdown("### 尚未組隊")
                for student in unassigned_students:
                    st.write(f"{student.get('seat_no')} 號｜{student.get('name')}")
            if not assigned and not unassigned_students:
                st.info("目前沒有可顯示的分組資料。")
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
    is_full_admin = identity.get("staff_role") in ("teacher", "super_admin")
    tab_labels = ["📢 公告管理中心", "🧾 班級分組管理", "🗂️ 全班照片管理", "👤 人員資料管理", "⚙️ 顯示設定"]
    if is_full_admin:
        tab_labels.append("🔐 帳號管理")
    created_tabs = st.tabs(tab_labels)
    group_tab, signup_tab, photo_tab, personnel_tab, display_settings_tab = created_tabs[:5]
    staff_tab = created_tabs[5] if is_full_admin else None
    with signup_tab:
        st.markdown("## 👥 分組管理")
        st.caption("管理全班組隊名單、調整組別、指定組長。拖曳完成後記得按下儲存，才會正式更新。")
        with st.container(border=True):
            st.markdown("**管理小提醒**")
            st.caption("每位學生只能加入一組；組長負責該組四張小組合照的上傳。調整分組不會刪除學生基本資料。")
        try:
            signups = (
                admin.table("group_signups")
                .select("id, student_id, seat_no, student_name, assigned_group")
                .order("id").execute().data
            )
            students = (
                admin.table("grad_album")
                .select("id, seat_no, name")
                .order("seat_no").execute().data
            )
            grouped = {}
            assigned_student_ids = set()
            for row in signups:
                group_no = row.get("assigned_group")
                if group_no is not None:
                    grouped.setdefault(group_no, []).append(row)
                    assigned_student_ids.add(row.get("student_id"))

            ungrouped = [
                student for student in students
                if student.get("id") not in assigned_student_ids
            ]
            assigned_count = len(assigned_student_ids)
            stat_cols = st.columns(3)
            stat_cols[0].metric("全班人數", f"{len(students)} 人")
            stat_cols[1].metric("已完成分組", f"{assigned_count} 人")
            stat_cols[2].metric("尚未組隊", f"{len(ungrouped)} 人")
            st.divider()
            # 同步既有分組到持久化欄位表，讓空組別重新整理後仍保留
            saved_columns = (
                admin.table("student_group_columns")
                .select("group_number").order("group_number").execute().data
            )
            saved_group_numbers = {
                row["group_number"] for row in saved_columns
            }
            for existing_number in grouped:
                if existing_number not in saved_group_numbers:
                    admin.table("student_group_columns").insert(
                        {"group_number": existing_number}
                    ).execute()
                    saved_group_numbers.add(existing_number)

            group_choices = sorted(saved_group_numbers | set(grouped.keys()))

            with st.expander("👤 各組組長設定", expanded=False):
                st.markdown("### 👤 設定各組組長")
                st.caption("每組指定一位組長，只有該組組長可以上傳四張小組合照。")
                try:
                    leader_records = admin.table("group_leaders").select("group_number, leader_student_id").execute().data
                    leaders_by_group = {row["group_number"]: row["leader_student_id"] for row in leader_records}
                    used_leader_ids = set(leaders_by_group.values())
                    for leader_group_no in group_choices:
                        candidates = sorted(
                            grouped.get(leader_group_no, []),
                            key=lambda row: str(row.get("seat_no", ""))
                        )
                        if not candidates:
                            continue
                        current_leader_id = leaders_by_group.get(leader_group_no)
                        available_candidates = [
                            row for row in candidates
                            if row.get("student_id") == current_leader_id
                            or row.get("student_id") not in (used_leader_ids - ({current_leader_id} if current_leader_id else set()))
                        ]
                        candidate_ids = [row["student_id"] for row in available_candidates]
                        if not candidate_ids:
                            st.warning(f"第 {leader_group_no} 組目前沒有可指定的組長，請先確認其他組的組長設定。")
                            continue
                        current_index = candidate_ids.index(current_leader_id) if current_leader_id in candidate_ids else 0
                        with st.form(f"set_group_leader_{leader_group_no}"):
                            selected_leader_id = st.selectbox(
                                f"第 {leader_group_no} 組組長",
                                candidate_ids,
                                index=current_index,
                                format_func=lambda value, rows=available_candidates: next(
                                    f"{row.get('seat_no')} 號｜{row.get('student_name')}"
                                    for row in rows if row.get("student_id") == value
                                ),
                            )
                            save_leader = st.form_submit_button("儲存組長設定")
                        if save_leader:
                            try:
                                admin.table("group_leaders").upsert({
                                    "group_number": leader_group_no,
                                    "leader_student_id": selected_leader_id,
                                }, on_conflict="group_number").execute()
                                queue_action_success(f"第 {leader_group_no} 組組長已設定。")
                                st.rerun()
                            except Exception:
                                st.error(f"第 {leader_group_no} 組組長設定失敗，請確認該學生是否已擔任其他組組長。")
                except Exception:
                    st.error("組長設定讀取失敗，請確認 group_leaders 資料表。")
    
            st.divider()
            st.subheader("🗂️ 分組拖曳看板")
            st.caption("B 版｜橫向欄位看板。每組獨立一欄，學生以卡片呈現；可左右瀏覽並直接拖曳調整組別。")
            if group_choices:
                overview_cols = st.columns(min(len(group_choices) + 1, 4))
                for overview_index, number in enumerate(group_choices):
                    with overview_cols[overview_index % len(overview_cols)]:
                        st.metric(f"第 {number} 組", f"{len(grouped.get(number, []))} 人")
                with overview_cols[len(group_choices) % len(overview_cols)]:
                    st.metric("尚未組隊", f"{len(ungrouped)} 人")
            else:
                st.info("目前還沒有組別，請按「＋ 新增組別」建立第一組。")
            st.caption("拖曳不會立即寫入資料庫；確認所有學生位置正確後，再按「儲存看板上的全班調整」。")
            if st.button("＋ 新增組別", type="secondary", key="admin_add_group_column"):
                try:
                    # 以資料庫最新資料決定編號，避免使用畫面載入時的舊清單。
                    latest_columns = (
                        admin.table("student_group_columns")
                        .select("group_number").order("group_number").execute().data
                    )
                    latest_signups = (
                        admin.table("group_signups")
                        .select("assigned_group").execute().data
                    )
                    occupied_numbers = {
                        int(row["group_number"]) for row in latest_columns
                        if row.get("group_number") is not None
                    }
                    occupied_numbers.update(
                        int(row["assigned_group"]) for row in latest_signups
                        if row.get("assigned_group") is not None
                    )
                    next_number = 1
                    while next_number in occupied_numbers:
                        next_number += 1

                    admin.table("student_group_columns").upsert(
                        {"group_number": next_number},
                        on_conflict="group_number",
                    ).execute()

                    # 回讀驗證：確認空組別已持久保存，重新整理後仍會出現。
                    verify_rows = (
                        admin.table("student_group_columns")
                        .select("group_number")
                        .eq("group_number", next_number)
                        .execute().data
                    )
                    if not verify_rows:
                        raise RuntimeError(
                            f"資料庫沒有讀回第 {next_number} 組，可能是資料表權限或寫入設定問題。"
                        )
                    st.session_state["admin_group_added_notice"] = (
                        f"第 {next_number} 組已新增並保存。"
                    )
                    st.rerun()
                except Exception as e:
                    error_detail = str(e)
                    st.error("新增組別失敗，資料庫回報：")
                    st.code(error_detail[:1500] if error_detail else "未提供詳細錯誤訊息")
                    st.info("請回報上方錯誤內容；不要提供任何密碼或金鑰。")
            added_group_notice = st.session_state.pop("admin_group_added_notice", None)
            if added_group_notice:
                queue_action_success(added_group_notice)
                st.rerun()

            from streamlit_sortables import sort_items
            # 取得組長名單，並將組長標籤放進拖曳卡片文字；儲存時仍以完整標籤對應學生 ID。
            try:
                leader_rows_for_board = admin.table("group_leaders").select(
                    "group_number, leader_student_id"
                ).execute().data
            except Exception:
                leader_rows_for_board = []
            leader_id_by_group = {
                row["group_number"]: row["leader_student_id"]
                for row in leader_rows_for_board
            }
            leader_ids_for_board = set(leader_id_by_group.values())

            # 看板統一使用 grad_album 主資料的座號與姓名，避免舊 group_signups
            # 中的姓名文字與主資料不同，造成拖曳後無法對應到學生。
            student_label_by_id = {
                student["id"]: (
                    f"{student.get('seat_no')} 號｜{student.get('name')}"
                    + ("　👑 組長" if student["id"] in leader_ids_for_board else "")
                )
                for student in students
            }

            # 搜尋只用來快速定位，不會過濾拖曳看板資料，避免儲存時漏掉未顯示的學生。
            search_student = st.text_input(
                "🔎 搜尋學生（座號或姓名）",
                placeholder="輸入座號或姓名快速查找",
                key="admin_group_board_search",
            ).strip()
            if search_student:
                matched_students = [
                    student for student in students
                    if search_student.lower() in str(student.get("seat_no", "")).lower()
                    or search_student.lower() in str(student.get("name", "")).lower()
                ]
                if matched_students:
                    for matched in matched_students:
                        matched_group = next(
                            (row.get("assigned_group") for row in signups
                             if row.get("student_id") == matched["id"]),
                            None,
                        )
                        group_text = f"第 {matched_group} 組" if matched_group is not None else "尚未組隊"
                        leader_text = "｜👑 組長" if matched["id"] in leader_ids_for_board else ""
                        st.caption(
                            f"找到：{matched.get('seat_no')} 號｜{matched.get('name')}｜{group_text}{leader_text}"
                        )
                else:
                    st.caption("找不到符合的學生，請確認座號或姓名。")
            student_lookup = {
                label: student
                for student in students
                for label in [student_label_by_id[student["id"]]]
            }
            group_header_by_number = {
                group_no: f"第 {group_no} 組｜{len(grouped.get(group_no, []))} 人"
                for group_no in group_choices
            }
            ungrouped_header = f"🧺 尚未組隊｜{len(ungrouped)} 人"
            group_boards = [
                {
                    "header": group_header_by_number[group_no],
                    "items": [
                        student_label_by_id[row["student_id"]]
                        for row in sorted(
                            grouped.get(group_no, []),
                            key=lambda item: str(item.get("seat_no", ""))
                        )
                        if row.get("student_id") in student_label_by_id
                    ],
                }
                for group_no in group_choices
            ]
            group_boards.append({
                "header": ungrouped_header,
                "items": [
                    student_label_by_id[student["id"]]
                    for student in ungrouped
                    if student["id"] in student_label_by_id
                ],
            })
            sorted_boards = sort_items(
                group_boards,
                multi_containers=True,
                key="admin_notion_group_board",
            )
            if st.button("儲存看板上的全班調整", type="primary", key="admin_save_all_group_cards"):
                save_step = "整理拖曳後的學生名單"
                try:
                    group_by_header = {
                        group_header_by_number[group_no]: group_no
                        for group_no in group_choices
                    }
                    target_groups = {}
                    save_step = "檢查每位學生是否只出現一次"
                    for board in sorted_boards:
                        header = board.get("header")
                        if header == ungrouped_header:
                            target_group = None
                        elif header in group_by_header:
                            target_group = group_by_header[header]
                        else:
                            raise ValueError("無法辨識拖曳後的組別")
                        for label in board.get("items", []):
                            student = student_lookup.get(label)
                            if not student or student["id"] in target_groups:
                                raise ValueError("學生名單有遺漏或重複")
                            target_groups[student["id"]] = target_group
                    if set(target_groups) != {student["id"] for student in students}:
                        st.error("全班名單不完整或有重複，沒有儲存任何變更。")
                        st.stop()
                    save_step = "比對目前分組與新分組"
                    current_groups = {
                        row.get("student_id"): row.get("assigned_group")
                        for row in signups
                    }
                    save_step = "逐位更新學生分組"
                    for student in students:
                        student_id = student["id"]
                        target_group = target_groups[student_id]
                        current_group = current_groups.get(student_id)
                        if current_group == target_group:
                            continue
                        save_step = f"更新學生 {student.get('seat_no', '')} 號的分組"
                        if target_group is None:
                            if student_id in current_groups:
                                admin.table("group_signups").update(
                                    {"assigned_group": None}
                                ).eq("student_id", student_id).execute()
                        else:
                            admin.rpc(
                                "admin_set_student_group",
                                {
                                    "input_student_id": student_id,
                                    "input_group_number": target_group,
                                },
                            ).execute()
                    queue_action_success("看板上的全班分組調整已儲存，分組名單已更新。")
                    st.rerun()
                except Exception as e:
                    st.error(f"全班分組儲存失敗，錯誤發生於：{save_step}")
                    error_detail = f"{type(e).__name__}: {e}"
                    st.code(error_detail[:1500])
                    st.info("請把上方錯誤文字回報給我；不要貼上任何密碼或金鑰。")

            if group_choices:
                st.divider()
                with st.expander("⚠️ 解散整個組別（請謹慎操作）", expanded=False):
                    st.warning("解散後，該組所有學生會回到「尚未組隊」。只會移除組別與組員關聯，不會刪除學生基本資料。")
                    delete_group_no = st.selectbox(
                        "選擇要刪除的組別",
                        group_choices,
                        format_func=lambda value: f"第 {value} 組（{len(grouped.get(value, []))} 人）",
                        key="admin_delete_group_select",
                    )
                    confirm_delete_group = st.checkbox(
                        f"我確認要解散第 {delete_group_no} 組",
                        key="admin_confirm_delete_group",
                    )
                    if st.button(
                        "刪除分組並讓組員回到未分組",
                        type="secondary",
                        disabled=not confirm_delete_group,
                        key="admin_delete_group_button",
                    ):
                        try:
                            result = admin.rpc(
                                "admin_delete_student_group",
                                {"input_group_number": delete_group_no},
                            ).execute()
                            admin.table("student_group_columns").delete().eq(
                                "group_number", delete_group_no
                            ).execute()
                            released_count = result.data
                            queue_action_success(f"已解散第 {delete_group_no} 組，{released_count} 位學生已回到尚未組隊。")
                            st.rerun()
                        except Exception:
                            st.error("刪除分組失敗，請稍後再試。")

            if ungrouped:
                with st.expander(f"👤 尚未組隊學生（{len(ungrouped)} 人）", expanded=False):
                    for student in ungrouped:
                        st.write(f"{student.get('seat_no')} 號｜{student.get('name')}")
        except Exception:
            st.error("無法讀取小組名單，請確認 group_signups 資料表設定。")
    with group_tab:
        st.markdown('<div id="announcement-center"></div>', unsafe_allow_html=True)
        st.subheader("📢 公告管理中心")
        st.caption("集中管理班級通知。草稿不會顯示給學生；排程公告會在指定時間自動出現在學生的「最新公告」。")

        # 全班分組一覽集中在公告中心管理；名單本身仍即時讀取分組資料表。
        st.subheader("👥 全班分組一覽管理")
        st.caption("設定學生頁面的全班分組名單顯示，並即時預覽各組組長與組員；名單會自動同步分組資料。")
        st.caption("這裡只管理學生頁面的顯示開關與預覽；組別、組長及組員名單會自動同步分組資料，不需要手動編輯公告。")
        try:
            roster_setting_rows = (
                admin.table("site_settings")
                .select("setting_value")
                .eq("setting_key", "show_class_group_roster")
                .limit(1).execute().data
            )
            roster_saved_value = (
                roster_setting_rows[0].get("setting_value")
                if roster_setting_rows else True
            )
            if not isinstance(roster_saved_value, bool):
                roster_saved_value = True
            roster_visible = st.toggle(
                "在學生頁面顯示全班分組一覽",
                value=roster_saved_value,
                key="announcement_center_roster_visibility",
            )
            if st.button("💾 儲存分組一覽顯示設定", key="save_announcement_center_roster_visibility"):
                admin.table("site_settings").upsert({
                    "setting_key": "show_class_group_roster",
                    "setting_value": bool(roster_visible),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="setting_key").execute()
                queue_action_success("全班分組一覽顯示設定已保存。")
                st.rerun()
            if roster_visible:
                st.markdown("**學生頁面預覽**")
                preview_students = admin.table("grad_album").select("id, seat_no, name").order("seat_no").execute().data
                preview_signups = admin.table("group_signups").select("student_id, assigned_group").execute().data
                preview_leader_rows = admin.table("group_leaders").select("group_number, leader_student_id").execute().data
                preview_leaders = {item["group_number"]: item["leader_student_id"] for item in preview_leader_rows}
                preview_groups = {}
                preview_assigned_ids = set()
                for signup in preview_signups:
                    group_no, student_id = signup.get("assigned_group"), signup.get("student_id")
                    if group_no is not None and student_id is not None:
                        preview_groups.setdefault(group_no, set()).add(student_id)
                        preview_assigned_ids.add(student_id)
                preview_stats = st.columns(3)
                preview_stats[0].metric("分組數", f"{len(preview_groups)} 組")
                preview_stats[1].metric("已分組", f"{len(preview_assigned_ids)} 人")
                preview_stats[2].metric("未分組", f"{sum(1 for item in preview_students if item.get('id') not in preview_assigned_ids)} 人")
                for preview_group_no in sorted(preview_groups):
                    preview_members = [item for item in preview_students if item.get("id") in preview_groups[preview_group_no]]
                    with st.container(border=True):
                        st.markdown(f"**第 {preview_group_no} 組**　👥 {len(preview_members)} 位")
                        for member in preview_members:
                            if member.get("id") == preview_leaders.get(preview_group_no):
                                st.markdown(f"組長：**{member.get('seat_no')} 號｜{member.get('name')}**")
                            else:
                                st.write(f"{member.get('seat_no')} 號｜{member.get('name')}")
                preview_unassigned = [item for item in preview_students if item.get("id") not in preview_assigned_ids]
                if preview_unassigned:
                    with st.expander(f"尚未分組（{len(preview_unassigned)} 位）"):
                        for member in preview_unassigned:
                            st.write(f"{member.get('seat_no')} 號｜{member.get('name')}")
            else:
                st.info("目前已關閉學生頁面的全班分組一覽。")
        except Exception as roster_admin_error:
            st.warning(f"全班分組一覽暫時無法載入：{type(roster_admin_error).__name__}：{str(roster_admin_error)[:200]}")

        announcement_categories = ["一般通知", "緊急通知", "拍攝異動", "活動與集合", "照片繳交", "分組通知", "畢冊進度", "班級團體照資訊", "個人生活照繳交規範"]
        taipei_tz = timezone(timedelta(hours=8))
        now_taipei = datetime.now(taipei_tz)
        # 舊版拍攝資訊與生活照規範曾儲存在學生頁面文字設定；提供一次性匯入，避免既有內容遺失。
        try:
            existing_special = (
                admin.table("announcements")
                .select("id, category")
                .in_("category", ["班級團體照資訊", "個人生活照繳交規範"])
                .execute().data
            )
            existing_special_categories = {row.get("category") for row in existing_special}
            if len(existing_special_categories) < 2:
                with st.expander("📦 匯入舊版拍攝資訊／生活照規範", expanded=False):
                    st.caption("如果舊版學生頁面曾設定班級團體照或個人生活照規範，可匯入公告中心，之後統一在這裡編輯。已存在的同類公告不會重複匯入。")
                    if st.button("匯入尚未建立的舊版內容", key="import_legacy_photo_notices"):
                        legacy_rows = admin.table("site_settings").select("setting_key, setting_value").in_(
                            "setting_key", ["student_page_content"]
                        ).execute().data
                        legacy_content = legacy_rows[0].get("setting_value", {}) if legacy_rows else {}
                        if not isinstance(legacy_content, dict):
                            legacy_content = {}
                        legacy_defaults = {
                            "class_photo_date": "11 月 6 日（星期五）",
                            "class_photo_time": "上午 08:20",
                            "class_photo_location": "健康中心旁的小石桌",
                            "class_photo_clothing": "請穿著制服",
                            "class_photo_count": "3 張",
                            "class_photo_actions": "1. YA 手勢\n2. 小愛心\n3. 戳臉",
                            "class_photo_notice": "請依照集合時間準時到場；如有異動，請留意畢冊製作組後續公告。",
                            "personal_rules_deadline": "每位同學都必須繳交，截止日期為 11 月 13 日。",
                            "personal_rules_list": "1. 每位同學都必須繳交個人生活照。\n2. 不可用任何方式遮蓋五官。\n3. 請採用七分身拍攝方式。\n4. 修圖請使用電腦進行，避免手機修圖造成圖片呈現不佳。\n5. 請於 11 月 13 日前至指定網址繳交。",
                            "personal_rules_extra": "七分身拍攝範例及指定繳交網址尚待提供，公布後會再補上。",
                            "personal_rules_contact": "如有任何問題，請直接提出，或私下向相關負責人反映。",
                        }
                        legacy = {**legacy_defaults, **legacy_content}
                        now_utc_iso = datetime.now(timezone.utc).isoformat()
                        imported_count = 0
                        if "班級團體照資訊" not in existing_special_categories:
                            class_body = (
                                f"拍攝日期：{legacy['class_photo_date']}\n"
                                f"集合時間：{legacy['class_photo_time']}\n"
                                f"集合地點：{legacy['class_photo_location']}\n"
                                f"服裝要求：{legacy['class_photo_clothing']}\n"
                                f"預計拍攝：{legacy['class_photo_count']}\n\n"
                                f"指定動作：\n{legacy['class_photo_actions']}\n\n"
                                f"注意事項：\n{legacy['class_photo_notice']}"
                            )
                            admin.table("announcements").insert({
                                "title": "班級團體照拍攝資訊", "content": class_body,
                                "category": "班級團體照資訊", "status": "published",
                                "is_pinned": False, "publish_at": now_utc_iso, "expires_at": None,
                            }).execute()
                            imported_count += 1
                        if "個人生活照繳交規範" not in existing_special_categories:
                            personal_body = (
                                f"{legacy['personal_rules_deadline']}\n\n"
                                f"{legacy['personal_rules_list']}\n\n"
                                f"補充說明：\n{legacy['personal_rules_extra']}\n\n"
                                f"聯絡方式：\n{legacy['personal_rules_contact']}"
                            )
                            admin.table("announcements").insert({
                                "title": "個人生活照繳交規範", "content": personal_body,
                                "category": "個人生活照繳交規範", "status": "published",
                                "is_pinned": False, "publish_at": now_utc_iso, "expires_at": None,
                            }).execute()
                            imported_count += 1
                        queue_action_success(f"已將 {imported_count} 則舊版內容匯入公告中心。")
                        st.rerun()
        except Exception as legacy_status_error:
            # 僅在管理員公告中心顯示診斷摘要；不影響下方一般公告功能。
            st.warning(
                "舊版內容匯入狀態暫時無法讀取；不影響一般公告管理。"
                f"（診斷：{type(legacy_status_error).__name__}：{str(legacy_status_error)[:240]}）"
            )

        with st.expander("➕ 新增公告", expanded=True):
            announcement_templates = {
                "自訂公告": {"category": "一般通知", "title": "", "content": ""},
                "📣 一般通知": {"category": "一般通知", "title": "【班級通知】", "content": "通知事項：\n\n相關日期／時間：\n\n請同學留意，謝謝。"},
                "⚠️ 緊急通知": {"category": "緊急通知", "title": "【重要／緊急通知】", "content": "通知原因：\n\n需要同學配合的事項：\n\n請同學務必留意。"},
                "📸 拍攝時間或地點異動": {"category": "拍攝異動", "title": "【拍攝資訊異動】", "content": "原訂拍攝時間／地點：\n\n調整後時間／地點：\n\n其他注意事項："},
                "📤 照片繳交提醒": {"category": "照片繳交", "title": "【照片繳交提醒】", "content": "繳交項目：\n\n繳交期限：\n\n繳交方式：\n\n注意事項："},
                "👥 分組集合通知": {"category": "分組通知", "title": "【分組集合通知】", "content": "組別：\n\n集合日期：\n\n集合時間：\n\n集合地點：\n\n攜帶物品／注意事項："},
                "📸 班級團體照資訊": {"category": "班級團體照資訊", "title": "班級團體照拍攝資訊", "content": "拍攝日期：\n集合時間：\n集合地點：\n服裝要求：\n預計拍攝張數：\n指定動作：\n\n注意事項："},
                "📝 個人生活照繳交規範": {"category": "個人生活照繳交規範", "title": "個人生活照繳交規範", "content": "繳交期限：\n\n繳交規範：\n1. \n2. \n3. \n\n補充說明：\n\n聯絡方式："},
            }
            selected_template = st.selectbox("公告範本（可再自行修改）", list(announcement_templates.keys()))
            template_data = announcement_templates[selected_template]
            new_notice_images = st.file_uploader(
                "公告圖片（可多選）", type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True, key="new_announcement_images",
                help="可一次選擇多張圖片；每張上限 10 MB，圖片會儲存在私密空間。",
            )
            if new_notice_images:
                st.caption(f"已選擇 {len(new_notice_images)} 張圖片")
                image_cols = st.columns(min(3, len(new_notice_images)))
                for image_index, image_file in enumerate(new_notice_images):
                    image_cols[image_index % len(image_cols)].image(image_file, caption=image_file.name, use_container_width=True)
            with st.form("create_announcement_form", clear_on_submit=True):
                new_notice_title = st.text_input("公告標題", value=template_data["title"], placeholder="例如：明日拍攝時間調整")
                new_notice_category = st.selectbox("公告類型", announcement_categories, index=announcement_categories.index(template_data["category"]))
                new_notice_content = st.text_area("公告內容", value=template_data["content"], height=150, placeholder="請輸入公告內容，可寫集合時間、地點、注意事項等。")
                new_notice_status = st.selectbox("發布狀態", ["draft", "published"], format_func=lambda x: "立即發布／依指定時間發布" if x == "published" else "儲存草稿")
                new_notice_date = st.date_input("發布日期", value=now_taipei.date())
                new_notice_time = st.time_input("發布時間", value=now_taipei.time().replace(second=0, microsecond=0))
                new_notice_pin = st.checkbox("📌 置頂公告")
                new_notice_expiry_enabled = st.checkbox("設定公告下架日期")
                new_notice_expiry = st.date_input("下架日期（當日結束後自動隱藏）", value=now_taipei.date(), disabled=not new_notice_expiry_enabled)
                create_notice = st.form_submit_button("建立公告", type="primary")
            if create_notice:
                if not new_notice_title.strip() or not new_notice_content.strip():
                    st.warning("公告標題和內容都不能空白。")
                else:
                    publish_dt = datetime.combine(new_notice_date, new_notice_time).replace(tzinfo=taipei_tz)
                    expiry_dt = datetime.combine(new_notice_expiry, datetime.max.time()).replace(tzinfo=taipei_tz) if new_notice_expiry_enabled else None
                    if expiry_dt and expiry_dt <= publish_dt:
                        st.error("下架日期必須晚於發布時間。")
                    else:
                        try:
                            created_notice = admin.table("announcements").insert({
                                "title": new_notice_title.strip(),
                                "content": new_notice_content.strip(),
                                "category": new_notice_category,
                                "status": new_notice_status,
                                "is_pinned": new_notice_pin,
                                "publish_at": publish_dt.astimezone(timezone.utc).isoformat(),
                                "expires_at": expiry_dt.astimezone(timezone.utc).isoformat() if expiry_dt else None,
                                "image_paths": [],
                            }).execute()
                            created_rows = created_notice.data or []
                            if new_notice_images:
                                if not created_rows:
                                    raise RuntimeError("公告已建立，但無法取得公告編號，因此圖片尚未上傳。")
                                new_paths = upload_announcement_images(created_rows[0]["id"], new_notice_images)
                                admin.table("announcements").update({"image_paths": new_paths}).eq("id", created_rows[0]["id"]).execute()
                            queue_action_success("公告已建立。")
                            st.rerun()
                        except Exception as create_error:
                            st.error(f"公告建立或圖片上傳失敗：{str(create_error)[:220]}")
        st.divider()
        st.subheader("📋 公告清單與管理")
        try:
            notice_rows = (
                admin.table("announcements")
                .select("*")
                .order("created_at", desc=True)
                .execute().data
            )
            if not notice_rows:
                st.info("目前還沒有公告，先使用上方表單建立第一則公告。")
            for notice in notice_rows:
                notice_id = notice["id"]
                status_label = {"draft": "草稿", "published": "已發布／排程中", "archived": "已下架"}.get(notice.get("status"), "未知")
                pin_label = "📌 " if notice.get("is_pinned") else ""
                with st.expander(f"{pin_label}{notice.get('title')}｜{notice.get('category')}｜{status_label}"):
                    existing_image_paths = notice.get("image_paths") or []
                    if not isinstance(existing_image_paths, list):
                        existing_image_paths = []
                    if existing_image_paths:
                        st.markdown("**目前公告圖片**")
                        preview_cols = st.columns(min(3, len(existing_image_paths)))
                        for image_index, image_path in enumerate(existing_image_paths):
                            try:
                                preview_cols[image_index % len(preview_cols)].image(make_url(image_path), use_container_width=True)
                            except Exception:
                                preview_cols[image_index % len(preview_cols)].caption("圖片預覽暫時無法載入")
                    remove_image_paths = st.multiselect(
                        "要移除的既有圖片（不選取就保留）",
                        options=existing_image_paths,
                        format_func=lambda path: path.rsplit("/", 1)[-1],
                        key=f"notice_remove_images_{notice_id}",
                    )
                    added_image_files = st.file_uploader(
                        "新增公告圖片（可多選）", type=["jpg", "jpeg", "png", "webp"],
                        accept_multiple_files=True, key=f"notice_add_images_{notice_id}",
                        help="每張圖片上限 10 MB，儲存在私密空間。",
                    )
                    if added_image_files:
                        st.caption(f"準備新增 {len(added_image_files)} 張圖片")
                        add_cols = st.columns(min(3, len(added_image_files)))
                        for image_index, image_file in enumerate(added_image_files):
                            add_cols[image_index % len(add_cols)].image(image_file, caption=image_file.name, use_container_width=True)
                    with st.form(f"edit_announcement_{notice_id}"):
                        edit_title = st.text_input("公告標題", value=notice.get("title") or "", key=f"notice_title_{notice_id}")
                        edit_category = st.selectbox("公告類型", announcement_categories, index=announcement_categories.index(notice.get("category")) if notice.get("category") in announcement_categories else 0, key=f"notice_category_{notice_id}")
                        edit_content = st.text_area("公告內容", value=notice.get("content") or "", height=140, key=f"notice_content_{notice_id}")
                        edit_status = st.selectbox("公告狀態", ["draft", "published", "archived"], index=["draft", "published", "archived"].index(notice.get("status") or "draft"), format_func=lambda x: {"draft":"草稿", "published":"發布／排程", "archived":"下架"}[x], key=f"notice_status_{notice_id}")
                        edit_pin = st.checkbox("📌 置頂公告", value=bool(notice.get("is_pinned")), key=f"notice_pin_{notice_id}")
                        old_publish = datetime.fromisoformat(notice["publish_at"].replace("Z", "+00:00")).astimezone(taipei_tz)
                        edit_publish_date = st.date_input("發布日期", value=old_publish.date(), key=f"notice_date_{notice_id}")
                        edit_publish_time = st.time_input("發布時間", value=old_publish.time().replace(tzinfo=None, second=0, microsecond=0), key=f"notice_time_{notice_id}")
                        old_expiry = notice.get("expires_at")
                        expiry_default = datetime.fromisoformat(old_expiry.replace("Z", "+00:00")).astimezone(taipei_tz).date() if old_expiry else now_taipei.date()
                        edit_expiry_enabled = st.checkbox("設定下架日期", value=bool(old_expiry), key=f"notice_expiry_enabled_{notice_id}")
                        edit_expiry_date = st.date_input("下架日期", value=expiry_default, disabled=not edit_expiry_enabled, key=f"notice_expiry_{notice_id}")
                        save_notice = st.form_submit_button("儲存公告修改")
                    if save_notice:
                        if not edit_title.strip() or not edit_content.strip():
                            st.error("公告標題和內容都不能空白。")
                        else:
                            publish_dt = datetime.combine(edit_publish_date, edit_publish_time).replace(tzinfo=taipei_tz)
                            expiry_dt = datetime.combine(edit_expiry_date, datetime.max.time()).replace(tzinfo=taipei_tz) if edit_expiry_enabled else None
                            if expiry_dt and expiry_dt <= publish_dt:
                                st.error("下架日期必須晚於發布時間。")
                            else:
                                try:
                                    admin.table("announcements").update({
                                        "title": edit_title.strip(),
                                        "content": edit_content.strip(),
                                        "category": edit_category,
                                        "status": edit_status,
                                        "is_pinned": edit_pin,
                                        "publish_at": publish_dt.astimezone(timezone.utc).isoformat(),
                                        "expires_at": expiry_dt.astimezone(timezone.utc).isoformat() if expiry_dt else None,
                                        "updated_at": datetime.now(timezone.utc).isoformat(),
                                    }).eq("id", notice_id).execute()
                                    kept_paths = [path for path in existing_image_paths if path not in remove_image_paths]
                                    added_paths = upload_announcement_images(notice_id, added_image_files) if added_image_files else []
                                    final_paths = kept_paths + added_paths
                                    admin.table("announcements").update({
                                        "image_paths": final_paths,
                                        "updated_at": datetime.now(timezone.utc).isoformat(),
                                    }).eq("id", notice_id).execute()
                                    if remove_image_paths:
                                        admin.storage.from_(BUCKET).remove(remove_image_paths)
                                    queue_action_success("公告已更新。")
                                    st.rerun()
                                except Exception as edit_error:
                                    st.error(f"公告更新或圖片處理失敗：{str(edit_error)[:220]}")
                    delete_confirm = st.checkbox("我確認永久刪除此公告", key=f"notice_delete_confirm_{notice_id}")
                    if st.button("🗑️ 永久刪除公告", disabled=not delete_confirm, key=f"delete_notice_{notice_id}"):
                        try:
                            admin.table("announcements").delete().eq("id", notice_id).execute()
                            if existing_image_paths:
                                try:
                                    admin.storage.from_(BUCKET).remove(existing_image_paths)
                                except Exception:
                                    st.warning("公告已刪除，但部分圖片檔案未能同步清除。")
                            queue_action_success("公告已刪除。")
                            st.rerun()
                        except Exception as delete_error:
                            st.error(f"公告刪除失敗：{str(delete_error)[:220]}")
        except Exception:
            st.error("公告清單讀取失敗，請確認 announcements 資料表已建立。")
    with photo_tab:
        st.subheader("全班照片管理")
        st.warning("刪除照片無法復原，請確認選取內容。")
        try:
            st.markdown("### 📷 各組小組合照")
            group_photo_rows = (
                admin.table("group_photos")
                .select("group_number, photo_slot, storage_path")
                .order("group_number").order("photo_slot")
                .execute().data
            )
            if not group_photo_rows:
                st.info("目前尚無小組合照。")
            for group_photo in group_photo_rows:
                p1, p2, p3 = st.columns([2, 3, 1])
                p1.write(f"第 {group_photo['group_number']} 組｜第 {group_photo['photo_slot']} 張")
                try:
                    p2.image(make_url(group_photo["storage_path"]), width=150)
                except Exception:
                    p2.caption("預覽失敗")
                if p3.button("刪除小組照", key=f"admin_group_photo_delete_{group_photo['group_number']}_{group_photo['photo_slot']}"):
                    admin.storage.from_(BUCKET).remove([group_photo["storage_path"]])
                    admin.table("group_photos").delete().eq("group_number", group_photo["group_number"]).eq("photo_slot", group_photo["photo_slot"]).execute()
                    queue_action_success("小組照片已刪除。")
                    st.rerun()
            st.divider()
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
                    queue_action_success("照片已刪除。")
                    st.rerun()
        except Exception:
            st.error("照片清單讀取失敗，請確認 Storage bucket 名稱及權限。")

    with display_settings_tab:
        st.subheader("⚙️ 顯示控制中心")
        st.caption("整合頁面開關、即時預覽、自訂區塊與文字內容管理。")
        visibility_options = [
            ("show_student_announcements", "📢 最新公告", "顯示已發布公告"),
            ("show_personal_photo_upload", "📤 個人生活照繳交", "開放個人照片上傳"),
            ("show_my_photos", "🖼️ 我的照片", "讓學生查看自己的照片"),
            ("show_group_signup", "👥 分組登記&小組照繳交", "顯示分組與小組照片功能"),
            ("show_class_group_photo", "📸 班級團體照資訊", "在最新公告中顯示團體照資訊"),
            ("show_personal_photo_rules", "📝 個人生活照繳交規範", "在最新公告中顯示生活照規範"),
        ]
        try:
            current_rows = admin.table("site_settings").select("setting_key, setting_value").execute().data
            current_settings = {row.get("setting_key"): row.get("setting_value") for row in current_rows}
            student_custom_blocks = current_settings.get("student_custom_blocks", [])
            if not isinstance(student_custom_blocks, list):
                student_custom_blocks = []
            student_custom_blocks = [
                item for item in student_custom_blocks
                if isinstance(item, dict) and str(item.get("title", "")).strip()
                and isinstance(item.get("content", ""), str)
            ]

            st.markdown("### 📢 公告中心連動")
            st.caption("公告內容統一在「公告管理中心」建立、編輯、排程及下架；這裡只控制學生頁面是否顯示公告。")
            try:
                announcement_status_rows = admin.table("announcements").select("id, status, category").execute().data
                published_count = sum(1 for item in announcement_status_rows if item.get("status") == "published")
                draft_count = sum(1 for item in announcement_status_rows if item.get("status") == "draft")
                other_count = len(announcement_status_rows) - published_count - draft_count
                status_cols = st.columns(3)
                status_cols[0].metric("已發布公告", published_count)
                status_cols[1].metric("草稿", draft_count)
                status_cols[2].metric("其他狀態", other_count)
            except Exception:
                st.info("目前無法讀取公告統計，但不影響公告中心內的管理功能。")
            st.markdown('[↗ 前往公告管理中心](#announcement-center)')
            st.divider()

            st.markdown("### ① 頁面顯示與即時預覽")
            control_col, preview_col = st.columns([1, 1.15], gap="large")
            changed_visibility = {}
            with control_col:
                with st.container(border=True):
                    st.markdown("#### 👁️ 學生頁面開關")
                    st.caption("切換後右側預覽立即更新；按儲存才正式套用。")
                    for key, label, description in visibility_options:
                        saved_value = current_settings.get(key, True)
                        default_value = saved_value if isinstance(saved_value, bool) else True
                        changed_visibility[key] = st.toggle(
                            label, value=default_value, key=f"display_toggle_{key}", help=description
                        )
                    enabled_count = sum(bool(value) for value in changed_visibility.values())
                    st.metric("預計顯示項目", f"{enabled_count} / {len(visibility_options)}")
                    if st.button("💾 儲存顯示設定", type="primary", use_container_width=True, key="save_display_center_visibility"):
                        for key, value in changed_visibility.items():
                            admin.table("site_settings").upsert({
                                "setting_key": key, "setting_value": bool(value),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }, on_conflict="setting_key").execute()
                        queue_action_success("學生頁面顯示設定已保存。")
                        st.rerun()

            with preview_col:
                with st.container(border=True):
                    st.markdown("#### 🖥️ 學生頁面即時預覽")
                    preview_device = st.radio(
                        "預覽裝置", ["電腦版", "手機版"], horizontal=True,
                        key="display_center_preview_device", label_visibility="collapsed",
                    )
                    preview_items = [
                        (key, label, description) for key, label, description in visibility_options
                        if changed_visibility.get(key, True)
                    ]
                    if preview_device == "手機版":
                        _, preview_area, _ = st.columns([0.12, 0.76, 0.12])
                    else:
                        preview_area = st.container()
                    with preview_area:
                        with st.container(border=True):
                            st.markdown("**116級國三一畢業紀念冊**")
                            st.caption("學生頁面預覽")
                            for key, label, description in preview_items:
                                if key in ("show_class_group_photo", "show_personal_photo_rules"):
                                    continue
                                with st.container(border=True):
                                    st.markdown(f"**{label}**")
                                    st.caption(description)
                            if changed_visibility.get("show_class_group_photo", True):
                                st.caption("📸 班級團體照資訊：整合顯示於最新公告。")
                            if changed_visibility.get("show_personal_photo_rules", True):
                                st.caption("📝 個人生活照繳交規範：整合顯示於最新公告。")
                            for block in student_custom_blocks:
                                if block.get("enabled", True):
                                    with st.container(border=True):
                                        st.markdown(f"**{block.get('title', '自訂區塊')}**")
                                        st.markdown(str(block.get("content", "")))
                            if not preview_items and not any(item.get("enabled", True) for item in student_custom_blocks):
                                st.info("目前沒有開放顯示的學生頁面內容。")
                    st.caption("此預覽會依目前開關即時更新；未儲存的設定不會影響學生實際頁面。")

            with st.expander("↩️ 一鍵恢復顯示設定預設值", expanded=False):
                st.warning("將 7 個顯示開關恢復為開啟，並清除學生頁面文字覆寫（回到系統預設文字）。不會刪除公告、自訂區塊、學生資料或照片。")
                if st.button("恢復全部顯示設定預設值", key="display_center_reset_request"):
                    st.session_state["confirm_display_center_reset"] = True
                if st.session_state.get("confirm_display_center_reset", False):
                    st.error("最後確認：確定要恢復所有顯示設定及文字內容嗎？")
                    reset_yes, reset_no = st.columns(2)
                    if reset_yes.button("確認恢復預設", type="primary", key="display_center_reset_confirm"):
                        for key, _, _ in visibility_options:
                            admin.table("site_settings").upsert({
                                "setting_key": key, "setting_value": True,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }, on_conflict="setting_key").execute()
                            st.session_state[f"display_toggle_{key}"] = True
                        admin.table("site_settings").upsert({
                            "setting_key": "student_page_content", "setting_value": {},
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }, on_conflict="setting_key").execute()
                        for state_key in list(st.session_state.keys()):
                            if str(state_key).startswith("content_card_"):
                                st.session_state.pop(state_key, None)
                        st.session_state.pop("confirm_display_center_reset", None)
                        queue_action_success("顯示設定及文字內容已恢復系統預設值。")
                        st.rerun()
                    if reset_no.button("取消", key="display_center_reset_cancel"):
                        st.session_state.pop("confirm_display_center_reset", None)
                        st.rerun()

            st.divider()
            st.markdown("### ➕ 自訂學生頁面區塊")
            st.caption("建立專屬資訊卡片，儲存後會立即顯示在學生登入頁面。內容支援一般文字及 Markdown；請勿放入密碼或敏感個資。")
            custom_templates = {
                "自訂空白區塊": ("", ""),
                "📢 重要提醒": ("📢 重要提醒", "請在這裡輸入需要提醒全班同學的事項。"),
                "📸 拍攝資訊": ("📸 拍攝資訊", "拍攝日期：\n集合時間：\n集合地點：\n服裝要求："),
                "📋 繳交說明": ("📋 繳交說明", "繳交期限：\n繳交內容：\n注意事項："),
                "🎉 活動資訊": ("🎉 活動資訊", "活動日期：\n活動時間：\n活動地點：\n活動說明："),
            }
            template_choice = st.selectbox("選擇區塊範本", list(custom_templates), key="custom_block_template_choice")
            template_title, template_content = custom_templates[template_choice]
            with st.form("add_student_custom_block", clear_on_submit=True):
                custom_title = st.text_input("區塊標題", value=template_title, max_chars=80)
                custom_content = st.text_area("區塊內容", value=template_content, height=150)
                custom_enabled = st.checkbox("建立後立即顯示", value=True)
                add_custom_block = st.form_submit_button("＋ 新增自訂區塊", type="primary")
            if add_custom_block:
                if not custom_title.strip() or not custom_content.strip():
                    st.warning("請填寫區塊標題及內容。")
                else:
                    new_block = {
                        "id": uuid.uuid4().hex,
                        "title": custom_title.strip(),
                        "content": custom_content.strip(),
                        "enabled": bool(custom_enabled),
                    }
                    updated_blocks = [*student_custom_blocks, new_block]
                    admin.table("site_settings").upsert({
                        "setting_key": "student_custom_blocks",
                        "setting_value": updated_blocks,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }, on_conflict="setting_key").execute()
                    queue_action_success(f"自訂區塊「{new_block['title']}」已新增並保存。")
                    st.rerun()

            if student_custom_blocks:
                st.markdown("#### 已建立的自訂區塊")
                st.caption("可預覽、編輯、調整順序、隱藏或刪除。")
                for block_index, block in enumerate(student_custom_blocks):
                    block_id = str(block.get("id") or block_index)
                    with st.container(border=True):
                        st.markdown(f"**{block.get('title', '未命名區塊')}**")
                        with st.expander("👀 預覽學生頁面"):
                            st.subheader(str(block.get("title", "")))
                            st.markdown(str(block.get("content", "")))
                        with st.expander("✏️ 編輯區塊"):
                            with st.form(f"edit_custom_block_{block_id}"):
                                edited_title = st.text_input("區塊標題", value=str(block.get("title", "")), max_chars=80)
                                edited_content = st.text_area("區塊內容", value=str(block.get("content", "")), height=140)
                                save_edit = st.form_submit_button("儲存修改", type="primary")
                            if save_edit:
                                if not edited_title.strip() or not edited_content.strip():
                                    st.warning("標題和內容都不能留白。")
                                else:
                                    changed = [dict(item) for item in student_custom_blocks]
                                    changed[block_index]["title"] = edited_title.strip()
                                    changed[block_index]["content"] = edited_content.strip()
                                    admin.table("site_settings").upsert({"setting_key":"student_custom_blocks","setting_value":changed,"updated_at":datetime.now(timezone.utc).isoformat()},on_conflict="setting_key").execute()
                                    queue_action_success("自訂區塊已修改並保存。")
                                    st.rerun()
                        cols = st.columns(4)
                        if cols[0].button("↑ 上移", key=f"custom_up_{block_id}", disabled=block_index == 0):
                            changed = [dict(item) for item in student_custom_blocks]
                            changed[block_index-1], changed[block_index] = changed[block_index], changed[block_index-1]
                            admin.table("site_settings").upsert({"setting_key":"student_custom_blocks","setting_value":changed,"updated_at":datetime.now(timezone.utc).isoformat()},on_conflict="setting_key").execute()
                            queue_action_success("區塊順序已更新。")
                            st.rerun()
                        if cols[1].button("↓ 下移", key=f"custom_down_{block_id}", disabled=block_index == len(student_custom_blocks)-1):
                            changed = [dict(item) for item in student_custom_blocks]
                            changed[block_index], changed[block_index+1] = changed[block_index+1], changed[block_index]
                            admin.table("site_settings").upsert({"setting_key":"student_custom_blocks","setting_value":changed,"updated_at":datetime.now(timezone.utc).isoformat()},on_conflict="setting_key").execute()
                            queue_action_success("區塊順序已更新。")
                            st.rerun()
                        if cols[2].button("隱藏" if block.get("enabled", True) else "顯示", key=f"custom_toggle_{block_id}"):
                            changed = [dict(item) for item in student_custom_blocks]
                            changed[block_index]["enabled"] = not bool(block.get("enabled", True))
                            admin.table("site_settings").upsert({"setting_key":"student_custom_blocks","setting_value":changed,"updated_at":datetime.now(timezone.utc).isoformat()},on_conflict="setting_key").execute()
                            queue_action_success("區塊顯示狀態已更新。")
                            st.rerun()
                        if cols[3].button("刪除", key=f"custom_delete_{block_id}"):
                            st.session_state[f"confirm_custom_delete_{block_id}"] = True
                        if st.session_state.get(f"confirm_custom_delete_{block_id}", False):
                            st.warning("確定要刪除此區塊嗎？")
                            yes, no = st.columns(2)
                            if yes.button("確認刪除", key=f"custom_delete_yes_{block_id}"):
                                changed = [item for index,item in enumerate(student_custom_blocks) if index != block_index]
                                admin.table("site_settings").upsert({"setting_key":"student_custom_blocks","setting_value":changed,"updated_at":datetime.now(timezone.utc).isoformat()},on_conflict="setting_key").execute()
                                st.session_state.pop(f"confirm_custom_delete_{block_id}", None)
                                queue_action_success("自訂區塊已刪除。")
                                st.rerun()
                            if no.button("取消", key=f"custom_delete_no_{block_id}"):
                                st.session_state.pop(f"confirm_custom_delete_{block_id}", None)
                                st.rerun()

            st.divider()
            st.markdown("### 📝 學生頁面文字與內容管理")
            st.caption("依分類卡片修改學生頁面的文字；每項都可預覽、儲存或單獨還原。系統必要代碼會在儲存前檢查。")
            content_defaults = {
                "class_photo_date": "11 月 6 日（星期五）", "class_photo_time": "上午 08:20",
                "class_photo_location": "健康中心旁的小石桌", "class_photo_clothing": "請穿著制服",
                "class_photo_count": "3 張", "class_photo_actions": "1. YA 手勢\n2. 小愛心\n3. 戳臉",
                "class_photo_notice": "請依照集合時間準時到場；如有異動，請留意畢冊製作組後續公告。",
                "group_notice": "小組拍攝注意事項\n\n（1）需要 4 張\n\n（2）動作需自行決定",
                "personal_rules_deadline": "每位同學都必須繳交，截止日期為 11 月 13 日。",
                "personal_rules_list": "1. 每位同學都必須繳交個人生活照。\n2. 不可用任何方式遮蓋五官。\n3. 請採用七分身拍攝方式。\n4. 修圖請使用電腦進行，避免手機修圖造成圖片呈現不佳。\n5. 請於 11 月 13 日前至指定網址繳交。",
                "personal_rules_extra": "七分身拍攝範例及指定繳交網址尚待提供，公布後會再補上。",
                "personal_rules_contact": "如有任何問題，請直接提出，或私下向相關負責人反映。",
                "roster_title": "👥 全班分組一覽",
                "roster_caption": "所有同學都可以查看目前各組名單；組長會特別標示。",
                "roster_empty": "目前尚未有學生完成分組。",
                "roster_load_error": "目前無法載入全班分組名單，請稍後重新整理。",
                "roster_unassigned_label": "尚未分組（{count} 位）",
                "tab_announcements": "📢 最新公告",
                "tab_personal_upload": "📤 個人生活照繳交",
                "tab_my_photos": "🖼️ 我的照片",
                "tab_group_signup": "👥 分組登記&小組照繳交",
                "tab_class_photo": "📸 班級團體照",
                "tab_personal_rules": "📝 個人生活照須知",
                "no_student_sections": "目前沒有開放顯示的學生頁面內容，請聯絡管理員。",
                "upload_title": "上傳個人生活照",
                "upload_intro": "每位同學都必須繳交個人生活照，請先閱讀「個人生活照須知」再上傳。",
                "upload_file_help": "可多選 JPG、PNG、WEBP，每張上限 10 MB",
                "upload_button": "確認上傳",
                "upload_choose_warning": "請先選擇照片。",
                "upload_file_error": "{filename}：{error}",
                "upload_fail": "{filename} 上傳失敗，請稍後再試。",
                "upload_success": "成功上傳 {count} 張照片。",
                "my_photos_title": "我的照片",
                "my_photos_empty": "目前還沒有上傳照片。",
                "my_photos_error": "照片讀取失敗，請稍後再試。",
                "class_photo_title": "班級團體照拍攝公告",
                "class_photo_actions_label": "**指定動作：**",
                "announcements_caption": "查看畢冊製作組發布的重要通知、拍攝異動及活動提醒。",
                "announcements_empty": "目前沒有已發布的公告。",
                "announcement_pinned": "📌 置頂",
                "announcement_default_category": "一般通知",
                "announcement_published_at": "發布時間：{published_at}",
                "announcements_error": "公告讀取失敗，請稍後再試。",
                "group_signup_title": "小組合照繳交區",
                "group_leader_label": "組長：**{seat_no} 號｜{name}**",
                "group_signup_caption": "由組長建立小組，輸入其他組員的座號即可。系統會自動帶入正確姓名，並將整組名單一次送出。",
                "group_joined": "你已加入第 {group_no} 組，不能再加入其他組別。",
                "group_member_title": "**第 {group_no} 組組員名單**",
                "group_photo_title": "### 📷 本組小組合照（共 4 張）",
                "group_leader_missing": "本組組長尚未完成上傳權限登記，請聯絡管理員協助設定。",
                "group_photo_leader_help": "由組長統一上傳本組 4 張照片。每個欄位可重新上傳替換；每張上限 10 MB。",
                "group_photo_member_help": "本組照片由組長統一上傳，你可以查看目前繳交進度。",
                "group_photo_slot": "**第 {slot} 張**",
                "group_photo_uploaded": "已繳交",
                "group_photo_missing": "尚未繳交",
                "group_photo_choose": "選擇第 {slot} 張",
                "group_photo_upload": "上傳／替換第 {slot} 張",
                "group_photo_success": "第 {slot} 張小組照已上傳。",
                "group_photo_fail": "第 {slot} 張照片上傳失敗，請稍後再試。",
                "group_photo_error": "小組照片讀取失敗，請稍後再試。",
                "group_member_input": "其他組員座號",
                "group_member_placeholder": "例如：2、5、8\n也可以每行輸入一個座號",
                "group_member_help": "不用輸入自己的座號，系統會自動把你列為組長。可用逗號、頓號或換行分隔。",
                "group_submit": "確認組隊並送出",
                "group_need_member": "請至少輸入一位其他組員的座號。",
                "group_self_member": "不用輸入自己的座號，系統會自動加入組長。",
                "group_success": "組隊成功！第 {group_no} 組，共 {member_count} 位組員。",
                "group_duplicate_error": "送出失敗：組員名單有重複，或有人已經加入其他小組。請重新確認座號。",
                "group_seat_error": "送出失敗：有座號查不到，請確認座號是否正確。",
                "group_submit_error": "小組送出失敗，請稍後重試；若持續發生，請聯絡畢冊製作組。",
                "group_load_error": "小組組隊功能目前無法讀取資料，請稍後再試或聯絡畢冊製作組。",
                "personal_rules_title": "個人生活照繳交規範",
                "roster_group_title": "**第 {group_no} 組**",
                "roster_leader_prefix": "組長｜",
                "roster_member_format": "{seat_no} 號｜{leader_prefix}{name}",
                "roster_unassigned_member_format": "{seat_no} 號｜{name}",
                "class_photo_date_label": "**拍攝日期：**",
                "class_photo_time_label": "**集合時間：**",
                "class_photo_location_label": "**集合地點：**",
                "class_photo_clothing_label": "**服裝要求：**",
                "class_photo_count_label": "**預計拍攝：**",
                "group_photo_upload_error": "{error}",
                "login_session_caption": "登入有效時間：30 分鐘",
                "student_login_success": "學生登入成功：{seat_no} 號｜{name}",
                "refresh_button": "🔄 刷新",
                "change_password_button": "🔐 更改密碼",
                "logout_button": "登出",
                "password_title": "### 🔐 更改密碼",
                "password_student_caption": "請輸入目前密碼及新密碼完成修改。",
                "password_current_label": "目前密碼",
                "password_new_label": "新密碼（8～128 個字元）",
                "password_confirm_label": "再次輸入新密碼",
                "password_submit_button": "確認更改密碼",
                "password_fill_warning": "請完整填寫所有欄位。",
                "password_length_warning": "新密碼長度需為 8～128 個字元。",
                "password_mismatch_error": "兩次輸入的新密碼不一致。",
                "password_success": "密碼已更新，請下次使用新密碼登入。",
                "password_wrong_error": "目前密碼錯誤，密碼未變更。",
                "password_general_error": "目前無法更改密碼，請稍後再試。",
            }
            saved_content = current_settings.get("student_page_content")
            saved_content = saved_content if isinstance(saved_content, dict) else {}
            field_labels = {
                "class_photo_date": "拍攝日期", "class_photo_time": "集合時間",
                "class_photo_location": "集合地點", "class_photo_clothing": "服裝要求",
                "class_photo_count": "預計拍攝張數", "class_photo_actions": "指定動作",
                "class_photo_notice": "提醒文字", "group_notice": "小組拍攝注意事項",
                "personal_rules_deadline": "截止日期提醒",
                "personal_rules_list": "生活照注意事項（可自行編輯編號及換行）",
                "personal_rules_extra": "補充說明", "personal_rules_contact": "聯絡方式／問題反映文字",
            }
            # Build readable labels for every configurable field. Keep explicit
            # Chinese labels above and provide a safe fallback for all other keys.
            for content_key in content_defaults:
                field_labels.setdefault(
                    content_key,
                    content_key.replace("_", " ").capitalize(),
                )

            content_categories = [
                ("📸 班級團體照", ["class_photo_date", "class_photo_time", "class_photo_location",
                    "class_photo_clothing", "class_photo_count", "class_photo_actions", "class_photo_notice",
                    "class_photo_title", "class_photo_actions_label", "class_photo_date_label",
                    "class_photo_time_label", "class_photo_location_label", "class_photo_clothing_label",
                    "class_photo_count_label"]),
                ("👥 分組與名單", ["group_notice", "roster_title", "roster_caption", "roster_empty",
                    "roster_load_error", "roster_unassigned_label", "roster_group_title",
                    "roster_leader_prefix", "roster_member_format", "roster_unassigned_member_format",
                    "tab_group_signup", "group_signup_title", "group_leader_label", "group_signup_caption",
                    "group_joined", "group_member_title", "group_member_input", "group_member_placeholder",
                    "group_member_help", "group_submit", "group_need_member", "group_self_member",
                    "group_success", "group_duplicate_error", "group_seat_error", "group_submit_error",
                    "group_load_error", "group_photo_title", "group_leader_missing",
                    "group_photo_leader_help", "group_photo_member_help", "group_photo_slot",
                    "group_photo_uploaded", "group_photo_missing", "group_photo_choose",
                    "group_photo_upload", "group_photo_success", "group_photo_fail",
                    "group_photo_error", "group_photo_upload_error"]),
                ("🖼️ 個人照片與繳交", ["personal_rules_deadline", "personal_rules_list",
                    "personal_rules_extra", "personal_rules_contact", "personal_rules_title",
                    "tab_personal_upload", "tab_my_photos", "tab_personal_rules", "upload_title",
                    "upload_intro", "upload_file_help", "upload_button", "upload_choose_warning",
                    "upload_file_error", "upload_fail", "upload_success", "my_photos_title",
                    "my_photos_empty", "my_photos_error"]),
                ("📢 公告與頁籤", ["tab_announcements", "announcements_caption", "announcements_empty",
                    "announcement_pinned", "announcement_default_category", "announcement_published_at",
                    "announcements_error"]),
                ("🔐 登入與操作文字", ["login_session_caption", "student_login_success",
                    "refresh_button", "change_password_button", "logout_button", "password_title",
                    "password_student_caption", "password_current_label", "password_new_label",
                    "password_confirm_label", "password_submit_button", "password_fill_warning",
                    "password_length_warning", "password_mismatch_error", "password_success",
                    "password_wrong_error", "password_general_error"]),
            ]
            # 團體照資訊與個人生活照規範已統一改由「公告管理中心」編輯。
            announcement_managed_keys = {
                key for key in content_defaults
                if key.startswith("class_photo_") or key.startswith("personal_rules_")
            }
            content_categories = [
                (name, [key for key in keys if key not in announcement_managed_keys])
                for name, keys in content_categories
            ]
            included_keys = {key for _, keys in content_categories for key in keys}
            extra_keys = [
                key for key in content_defaults
                if key not in included_keys and key not in announcement_managed_keys
            ]
            if extra_keys:
                content_categories.append(("🧩 其他介面文字", extra_keys))

            st.markdown("#### 🔎 找到要修改的文字")
            st.caption("先選分類或搜尋關鍵字，再修改文字。每張卡片都會標示目前是否使用自訂內容。")
            content_search = st.text_input(
                "搜尋文字設定",
                placeholder="例如：集合時間、組長、照片上傳、登入、錯誤提示",
                key="student_content_card_search",
                label_visibility="collapsed",
            ).strip().casefold()

            token_labels = {
                "class":"班級", "photo":"照片", "date":"日期", "time":"時間",
                "location":"地點", "clothing":"服裝", "count":"數量", "actions":"動作",
                "notice":"提醒", "group":"小組", "personal":"個人", "rules":"規範",
                "deadline":"截止日期", "list":"清單", "extra":"補充說明", "contact":"聯絡方式",
                "roster":"分組名單", "title":"標題", "caption":"說明文字", "empty":"空白提示",
                "load":"讀取", "error":"錯誤", "unassigned":"未分組", "label":"標籤",
                "tab":"頁籤", "announcements":"公告", "upload":"上傳", "my":"我的",
                "file":"檔案", "help":"操作說明", "button":"按鈕", "choose":"選擇",
                "fail":"失敗提示", "success":"成功提示", "pinned":"置頂", "default":"預設",
                "category":"分類", "published":"發布", "leader":"組長", "member":"組員",
                "signup":"登記", "joined":"已加入", "submit":"送出", "need":"必要提醒",
                "self":"本人", "duplicate":"重複", "seat":"座號", "group_photo":"小組合照",
                "slot":"張數欄位", "uploaded":"已繳交", "missing":"尚未繳交",
                "choose":"選擇", "password":"密碼", "login":"登入", "session":"登入時效",
                "refresh":"刷新", "change":"修改", "logout":"登出", "current":"目前",
                "new":"新", "confirm":"再次確認", "fill":"填寫", "length":"長度",
                "mismatch":"不一致", "wrong":"錯誤", "general":"一般",
                "student":"學生", "intro":"引導文字", "format":"格式",
                "actions_label":"動作標題", "date_label":"日期標題", "time_label":"時間標題",
                "location_label":"地點標題", "clothing_label":"服裝標題", "count_label":"數量標題",
                "announcement":"公告", "published_at":"發布時間", "group_signup":"分組登記",
                "member_input":"組員輸入欄", "placeholder":"輸入範例", "upload_error":"上傳錯誤",
            }
            for content_key in content_defaults:
                if content_key not in field_labels:
                    field_labels[content_key] = " ".join(
                        token_labels.get(part, part)
                        for part in content_key.split("_")
                    )

            matching_total = sum(
                1 for _, keys in content_categories for key in keys
                if not content_search
                or content_search in field_labels.get(key, key).casefold()
                or content_search in key.casefold()
                or content_search in content_defaults.get(key, "").casefold()
                or content_search in saved_content.get(key, "").casefold()
            )
            st.caption(f"目前找到 {matching_total} 個項目；修改後請按該項目的「儲存」，才會套用到學生頁面。")
            for category_index, (category_name, category_keys) in enumerate(content_categories):
                matching_keys = [
                    key for key in category_keys
                    if not content_search
                    or content_search in field_labels.get(key, key).casefold()
                    or content_search in key.casefold()
                    or content_search in content_defaults.get(key, "").casefold()
                    or content_search in saved_content.get(key, "").casefold()
                ]
                if not matching_keys:
                    continue
                with st.expander(f"{category_name}　·　{len(matching_keys)} 項", expanded=bool(content_search)):
                    for key in matching_keys:
                        label = field_labels.get(key, key)
                        default_value = content_defaults.get(key, "")
                        saved_value = saved_content.get(key, default_value)
                        if not isinstance(saved_value, str):
                            saved_value = default_value
                        widget_key = f"content_card_{key}"
                        if widget_key not in st.session_state:
                            st.session_state[widget_key] = saved_value
                        edited_value = st.session_state[widget_key]
                        is_customized = key in saved_content
                        with st.container(border=True):
                            title_col, status_col = st.columns([4, 1])
                            with title_col:
                                st.markdown(f"**{label}**")
                            with status_col:
                                st.caption("自訂內容" if is_customized else "系統預設")
                            edited_value = st.text_area(
                                "編輯內容",
                                key=widget_key,
                                height=120 if key in {
                                    "personal_rules_list", "group_notice", "class_photo_actions",
                                    "upload_intro", "group_signup_caption",
                                } else 78,
                                label_visibility="collapsed",
                                help="可使用換行與 Markdown 格式；若文字含有 {seat_no} 等代碼，請保留代碼。",
                            )
                            meta_col, save_col, reset_col = st.columns([2, 1, 1])
                            with meta_col:
                                st.caption(f"{len(edited_value)} 個字元")
                            with save_col:
                                if st.button("💾 儲存", key=f"save_content_{key}", type="primary", use_container_width=True):
                                    required_tokens = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", default_value))
                                    edited_tokens = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", edited_value))
                                    missing_tokens = sorted(required_tokens - edited_tokens)
                                    if not edited_value.strip():
                                        st.warning("內容不能留白；若要恢復原文，請使用「還原預設」。")
                                    elif missing_tokens:
                                        st.error("這段文字含有系統必要代碼，請保留：" + "、".join(missing_tokens))
                                    else:
                                        merged_content = {**saved_content, key: edited_value}
                                        admin.table("site_settings").upsert({
                                            "setting_key": "student_page_content",
                                            "setting_value": merged_content,
                                            "updated_at": datetime.now(timezone.utc).isoformat(),
                                        }, on_conflict="setting_key").execute()
                                        queue_action_success(f"「{label}」已儲存。")
                                        st.rerun()
                            with reset_col:
                                if st.button("↩️ 還原", key=f"reset_content_{key}", use_container_width=True, disabled=not is_customized):
                                    merged_content = dict(saved_content)
                                    merged_content.pop(key, None)
                                    admin.table("site_settings").upsert({
                                        "setting_key": "student_page_content",
                                        "setting_value": merged_content,
                                        "updated_at": datetime.now(timezone.utc).isoformat(),
                                    }, on_conflict="setting_key").execute()
                                    st.session_state[widget_key] = default_value
                                    queue_action_success(f"「{label}」已恢復系統預設值。")
                                    st.rerun()
                            with st.expander("👀 預覽學生實際看到的文字", expanded=False):
                                st.markdown(edited_value if edited_value.strip() else "（目前沒有內容）")
                                if edited_value != saved_value:
                                    st.info("這是尚未儲存的預覽；儲存後才會套用到學生頁面。")
            st.caption("提醒：格式欄位中的 {seat_no}、{name}、{count}、{error}、{group_no} 等代碼必須保留，否則對應資訊可能無法正確顯示。")
        except Exception as settings_error:
            st.error("學生頁面設定操作失敗，請稍後再試或聯絡系統管理員。")
            st.caption(f"錯誤類型：{type(settings_error).__name__}")

    with personnel_tab:
        st.subheader("👤 人員資料管理")
        st.caption("可維護管理員顯示姓名及學生基本資料；不會修改學生密碼、分組關聯或照片。")
        st.markdown("### 我的顯示姓名")
        current_username = (identity.get("username") or "").strip()
        try:
            own_rows = admin.table("staff_accounts").select("display_name").eq("username", current_username).limit(1).execute().data
            current_display_name = (own_rows[0].get("display_name") or current_username) if own_rows else current_username
            with st.form("edit_own_display_name"):
                own_display_name = st.text_input("登入後顯示名稱", value=current_display_name, max_chars=50)
                save_own_name = st.form_submit_button("儲存我的姓名")
            if save_own_name:
                if not own_display_name.strip():
                    st.warning("顯示姓名不可空白。")
                else:
                    admin.table("staff_accounts").update({
                        "display_name": own_display_name.strip(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("username", current_username).execute()
                    identity["display_name"] = own_display_name.strip()
                    st.session_state["identity"] = identity
                    queue_action_success("顯示姓名已更新。")
                    st.rerun()
        except Exception:
            st.error("讀取或更新自己的顯示姓名失敗。")

        st.divider()
        st.markdown("### 學生資料")
        try:
            student_rows = admin.table("grad_album").select("id, seat_no, name").order("seat_no").execute().data
            st.caption(f"目前共 {len(student_rows)} 位學生。修改座號或姓名不會更動學生 ID、密碼、分組及照片。")
            for student_row in student_rows:
                student_id = student_row["id"]
                with st.expander(f"{student_row.get('seat_no')} 號｜{student_row.get('name')}"):
                    with st.form(f"edit_student_profile_{student_id}"):
                        edited_seat = st.text_input("座號", value=str(student_row.get("seat_no") or ""), key=f"edit_student_seat_{student_id}")
                        edited_name = st.text_input("學生姓名", value=str(student_row.get("name") or ""), key=f"edit_student_name_{student_id}", max_chars=50)
                        save_student_profile = st.form_submit_button("儲存學生資料")
                    if save_student_profile:
                        if not edited_seat.strip() or not edited_name.strip():
                            st.warning("座號及姓名都不能空白。")
                        else:
                            duplicate_seat = admin.table("grad_album").select("id").eq("seat_no", edited_seat.strip()).neq("id", student_id).limit(1).execute().data
                            if duplicate_seat:
                                st.error("這個座號已經被其他學生使用。")
                            else:
                                admin.table("grad_album").update({
                                    "seat_no": edited_seat.strip(),
                                    "name": edited_name.strip(),
                                }).eq("id", student_id).execute()
                                queue_action_success("學生資料已更新。")
                                st.rerun()
        except Exception:
            st.error("學生資料讀取或更新失敗，請確認資料表欄位及權限。")

    if is_full_admin and staff_tab is not None:
        with staff_tab:
            is_full_admin = identity.get("staff_role") in ("teacher", "super_admin")
            actor_username = (identity.get("username") or "").strip().lower()
            st.subheader("管理員帳號管理")
            st.caption("帳號資料存放於 Supabase；密碼只保存 PBKDF2 雜湊值，不保存明文。")
            with st.form("create_staff_account", clear_on_submit=True):
                new_username = st.text_input("新帳號")
                new_display_name = st.text_input("顯示姓名")
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
                                "display_name": new_display_name.strip() or new_username.strip(),
                                "role": "admin",
                                "password_hash": hash_staff_password(new_password),
                                "is_active": True,
                            }).execute()
                            queue_action_success("帳號已安全寫入 Supabase。")
                            st.rerun()
                    except Exception:
                        st.error("新增帳號失敗，請稍後再試。")
            st.divider()
            st.subheader("現有帳號")
            try:
                staff_rows = (
                    admin.table("staff_accounts")
                    .select("id, username, display_name, role, is_active, created_at")
                    .order("role")
                    .order("username")
                    .execute().data
                )
                if not staff_rows:
                    st.info("目前沒有管理員帳號。")
                for staff in staff_rows:
                    staff_id = staff["id"]
                    is_protected_account = staff["role"] in ("teacher", "super_admin")
                    role_label = "管理員"
                    with st.expander(f"{role_label}｜{staff['username']}｜{'啟用中' if staff['is_active'] else '已停用'}"):
                        if is_protected_account and not is_full_admin:
                            st.info("此為最高權限管理員帳號，只有最高權限管理員可以修改。")
                            continue
                        with st.form(f"edit_staff_{staff_id}"):
                            display_name_value = st.text_input("顯示姓名", value=staff.get("display_name") or staff["username"], max_chars=50)
                            active_value = st.checkbox("啟用此帳號", value=staff["is_active"])
                            reset_password = st.text_input("更換密碼（留空代表不更換）", type="password")
                            save_staff = st.form_submit_button("儲存帳號設定")
                        if save_staff:
                            try:
                                if is_protected_account and not is_full_admin:
                                    st.error("權限不足：不能修改最高權限管理員帳號。")
                                    st.stop()
                                if staff["role"] == "admin" and staff["is_active"] and not active_value:
                                    active_admins = sum(1 for item in staff_rows if item["role"] == "admin" and item["is_active"])
                                    if active_admins <= 1:
                                        st.error("至少必須保留一位啟用中的管理員。")
                                        st.stop()
                                if not display_name_value.strip():
                                    st.error("顯示姓名不可空白。")
                                    st.stop()
                                updates = {"display_name": display_name_value.strip(), "is_active": active_value, "updated_at": datetime.now(timezone.utc).isoformat()}
                                if reset_password:
                                    if len(reset_password) < 12:
                                        st.error("新密碼至少需要 12 個字元。")
                                        st.stop()
                                    updates["password_hash"] = hash_staff_password(reset_password)
                                admin.table("staff_accounts").update(updates).eq("id", staff_id).execute()
                                queue_action_success("帳號設定已更新。")
                                st.rerun()
                            except Exception:
                                st.error("帳號更新失敗，請稍後再試。")
            except Exception:
                st.error("無法讀取帳號清單，請稍後再試。")
    
