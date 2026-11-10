import streamlit as st
import uuid
import hmac
import base64
import hashlib
import secrets
import json
import time
import requests
import logging
from cryptography.fernet import Fernet
from importlib.metadata import version
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

logger = logging.getLogger("grad_album.google_oauth")
logger.setLevel(logging.INFO)

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


# Google Drive 自動備份（僅管理員設定；Supabase 仍為主要儲存）
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DRIVE_REDIRECT_URI = "https://grad-album-kevza6xaafopua2faoaimw.streamlit.app/"

def _google_token_cipher():
    client_secret = str(st.secrets.get("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip()
    if not client_secret:
        raise RuntimeError("缺少 GOOGLE_OAUTH_CLIENT_SECRET")
    derived_key = hashlib.sha256(
        ("grad-album-google-drive-refresh-token-v1:" + client_secret).encode("utf-8")
    ).digest()
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(derived_key))

def load_google_drive_config():
    rows = (
        admin.table("site_settings")
        .select("setting_value")
        .eq("setting_key", "google_drive_backup_config")
        .limit(1).execute().data
    )
    value = rows[0].get("setting_value") if rows else {}
    return value if isinstance(value, dict) else {}

def save_google_drive_config(config):
    admin.table("site_settings").upsert({
        "setting_key": "google_drive_backup_config",
        "setting_value": config,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="setting_key").execute()

def save_google_oauth_pending_state(state):
    # Persist OAuth state server-side so the callback still works if the
    # browser opens a fresh Streamlit session during Google's redirect.
    admin.table("site_settings").upsert({
        "setting_key": "google_drive_oauth_pending_state",
        "setting_value": {"state": state, "created_at": time.time()},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="setting_key").execute()

def consume_google_oauth_pending_state():
    rows = (
        admin.table("site_settings")
        .select("setting_value")
        .eq("setting_key", "google_drive_oauth_pending_state")
        .limit(1).execute().data
    )
    pending = rows[0].get("setting_value") if rows else {}
    # Remove the pending value before validating it: a callback is one-use.
    admin.table("site_settings").delete().eq(
        "setting_key", "google_drive_oauth_pending_state"
    ).execute()
    if not isinstance(pending, dict):
        return None
    created_at = pending.get("created_at")
    if not isinstance(created_at, (int, float)) or time.time() - created_at > 600:
        return None
    return pending.get("state")

def save_google_oauth_result(status, message):
    # Persist the callback result so it remains visible after a fresh Streamlit session.
    admin.table("site_settings").upsert({
        "setting_key": "google_drive_oauth_last_result",
        "setting_value": {
            "status": status,
            "message": str(message)[:500],
            "created_at": time.time(),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="setting_key").execute()

def build_google_oauth_url():
    client_id = str(st.secrets.get("GOOGLE_OAUTH_CLIENT_ID", "")).strip()
    if not client_id:
        raise RuntimeError("缺少 GOOGLE_OAUTH_CLIENT_ID")
    state = secrets.token_urlsafe(32)
    save_google_oauth_pending_state(state)
    logger.info("Google OAuth: pending state saved to Supabase")
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "redirect_uri": GOOGLE_DRIVE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def exchange_google_oauth_code(code):
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": str(st.secrets.get("GOOGLE_OAUTH_CLIENT_ID", "")).strip(),
            "client_secret": str(st.secrets.get("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip(),
            "redirect_uri": GOOGLE_DRIVE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=25,
    )
    response.raise_for_status()
    return response.json()

def get_google_drive_access_token(config):
    cached = st.session_state.get("google_drive_access_token_cache") or {}
    if cached.get("access_token") and cached.get("expires_at", 0) > time.time() + 90:
        return cached["access_token"]
    encrypted_refresh = config.get("refresh_token_encrypted")
    if not encrypted_refresh:
        raise RuntimeError("尚未完成 Google 帳戶授權")
    try:
        refresh_token = _google_token_cipher().decrypt(encrypted_refresh.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise RuntimeError("Google 授權資料無法解密，請重新連結 Google 帳戶") from exc
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": str(st.secrets.get("GOOGLE_OAUTH_CLIENT_ID", "")).strip(),
            "client_secret": str(st.secrets.get("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=25,
    )
    response.raise_for_status()
    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("Google 未回傳存取權杖，請重新連結帳戶")
    st.session_state["google_drive_access_token_cache"] = {
        "access_token": access_token,
        "expires_at": time.time() + int(token_data.get("expires_in", 3600)),
    }
    return access_token

def google_drive_api_request(method, url, access_token, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Authorization"] = "Bearer " + access_token
    response = requests.request(method, url, headers=headers, timeout=45, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}

def ensure_google_group_folder(access_token, root_folder_id, group_number):
    folder_name = f"第{int(group_number):02d}組"
    query = (
        f"'{root_folder_id}' in parents and "
        f"name='{folder_name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    result = google_drive_api_request(
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        access_token,
        params={"q": query, "fields": "files(id,name)", "pageSize": 100},
    )
    folders = result.get("files", [])
    if folders:
        return folders[0]["id"]
    created = google_drive_api_request(
        "POST",
        "https://www.googleapis.com/drive/v3/files",
        access_token,
        json={
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_folder_id],
        },
        params={"fields": "id,name"},
    )
    return created["id"]

def backup_group_photo_to_drive(group_number, slot, photo_data, mime_type, extension, config):
    root_folder_id = str(config.get("folder_id", "")).strip()
    if not root_folder_id:
        raise RuntimeError("尚未選擇 Google Drive 備份資料夾")
    access_token = get_google_drive_access_token(config)
    group_folder_id = ensure_google_group_folder(access_token, root_folder_id, group_number)
    taiwan_now = datetime.now(timezone(timedelta(hours=8)))
    filename = (
        f"第{int(group_number):02d}組_第{int(slot):02d}張_"
        f"{taiwan_now.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}.{extension}"
    )
    metadata = {
        "name": filename,
        "mimeType": mime_type,
        "parents": [group_folder_id],
    }
    boundary = "grad_album_" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + json.dumps(metadata, ensure_ascii=False)
        + f"\r\n--{boundary}\r\n"
        + f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + photo_data + f"\r\n--{boundary}--".encode("ascii")
    return google_drive_api_request(
        "POST",
        "https://www.googleapis.com/upload/drive/v3/files",
        access_token,
        params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
    )

@st.cache_resource
def get_google_drive_folder_picker_component():
    html = """
    <div class="drive-picker-wrap">
      <button id="drive-picker-open" type="button">📁 選擇 Google Drive 備份資料夾</button>
      <div id="drive-picker-status" role="status">請選擇要存放畢冊照片備份的資料夾。</div>
    </div>
    """
    css = """
    .drive-picker-wrap { display:flex; flex-direction:column; gap:10px; font-family:var(--st-font); }
    #drive-picker-open { border:1px solid var(--st-primary-color); border-radius:9px; padding:10px 14px; background:var(--st-secondary-background-color); color:var(--st-text-color); font-weight:600; cursor:pointer; }
    #drive-picker-open:disabled { opacity:.6; cursor:wait; }
    #drive-picker-status { color:var(--st-text-color); font-size:13px; }
    """
    js = """
    export default function(component) {
      const { parentElement, data, setStateValue } = component;
      const button = parentElement.querySelector("#drive-picker-open");
      const status = parentElement.querySelector("#drive-picker-status");
      if (!button || button.dataset.bound === "1") return;
      button.dataset.bound = "1";
      button.onclick = async () => {
        button.disabled = true;
        status.textContent = "正在載入 Google Drive 選擇器…";
        try {
          if (!data?.access_token || !data?.api_key || !data?.project_number) {
            throw new Error("Google Picker 設定不完整，請重新整理頁面。");
          }
          const loadPicker = () => new Promise((resolve, reject) => {
            const load = () => {
              if (!window.gapi?.load) return reject(new Error("Google API 載入失敗"));
              window.gapi.load("picker", { callback: resolve, onerror: () => reject(new Error("Picker 載入失敗")) });
            };
            if (window.gapi?.load) return load();
            const script = document.createElement("script");
            script.src = "https://apis.google.com/js/api.js";
            script.async = true;
            script.onload = load;
            script.onerror = () => reject(new Error("無法載入 Google API"));
            document.head.appendChild(script);
          });
          await loadPicker();
          const folderView = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
            .setIncludeFolders(true)
            .setSelectFolderEnabled(true)
            .setMimeTypes("application/vnd.google-apps.folder");
          const picker = new google.picker.PickerBuilder()
            .addView(folderView)
            .setOAuthToken(data.access_token)
            .setDeveloperKey(data.api_key)
            .setAppId(String(data.project_number))
            .setCallback((payload) => {
              if (payload.action === google.picker.Action.PICKED && payload.docs?.length) {
                const selected = payload.docs[0];
                setStateValue("folder", {
                  id: selected.id,
                  name: selected.name || "已選擇的資料夾"
                });
                status.textContent = "已選取：" + (selected.name || "Google Drive 資料夾") + "，正在儲存設定…";
              } else if (payload.action === google.picker.Action.CANCEL) {
                status.textContent = "已取消選擇。";
                button.disabled = false;
              }
            })
            .build();
          picker.setVisible(true);
          button.disabled = false;
          status.textContent = "請在 Google Drive 視窗中選擇資料夾。";
        } catch (error) {
          status.textContent = error?.message || "Google Picker 無法開啟，請稍後再試。";
          button.disabled = false;
        }
      };
    }
    """
    return st.components.v2.component(
        name="google_drive_folder_picker",
        html=html,
        css=css,
        js=js,
    )

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

# 學生使用暫停開關：預設暫停；管理員可在「顯示設定」中重新開放。
student_access_paused = True
try:
    pause_rows = admin.table("site_settings").select("setting_value").eq("setting_key", "student_access_paused").limit(1).execute().data
    if pause_rows and isinstance(pause_rows[0].get("setting_value"), bool):
        student_access_paused = pause_rows[0]["setting_value"]
except Exception:
    # 無法確認設定時採取保護性預設，避免學生端意外開放；管理員登入仍可使用。
    student_access_paused = True

role = current_role()

# Handle Google's OAuth callback before the login gate. Streamlit may create a
# fresh session when Google redirects back, so the one-time state is verified
# against the server-side pending record rather than session_state.
oauth_code = st.query_params.get("code")
oauth_state = st.query_params.get("state")
oauth_error = st.query_params.get("error")
if oauth_code or oauth_error:
    logger.info("Google OAuth: callback received; code_present=%s error_present=%s", bool(oauth_code), bool(oauth_error))
    try:
        expected_state = consume_google_oauth_pending_state()
        logger.info("Google OAuth: pending state lookup completed; state_found=%s", bool(expected_state))
        if oauth_error:
            raise RuntimeError("Google 授權未完成：" + str(oauth_error))
        if not expected_state or not oauth_state or not hmac.compare_digest(
            str(expected_state), str(oauth_state)
        ):
            raise RuntimeError("Google 授權驗證未通過，請重新開始連結。")
        logger.info("Google OAuth: state validation passed; exchanging authorization code")
        token_data = exchange_google_oauth_code(str(oauth_code))
        logger.info("Google OAuth: authorization code exchange completed")
        refresh_token = token_data.get("refresh_token")
        logger.info("Google OAuth: refresh token returned=%s", bool(refresh_token))
        config = load_google_drive_config()
        if refresh_token:
            config["refresh_token_encrypted"] = _google_token_cipher().encrypt(
                refresh_token.encode("utf-8")
            ).decode("ascii")
        elif not config.get("refresh_token_encrypted"):
            raise RuntimeError("Google 沒有提供長期授權權杖，請重新連結並確認授權畫面。")
        config["connected"] = True
        save_google_drive_config(config)
        logger.info("Google OAuth: encrypted credentials saved to Supabase successfully")
        success_message = "Google 帳戶授權成功！請重新登入管理員，再選擇備份資料夾。"
        save_google_oauth_result("success", success_message)
        logger.info("Google OAuth: callback completed successfully")
        st.session_state["google_drive_oauth_flash"] = ("success", success_message)
        st.session_state.pop("google_drive_access_token_cache", None)
    except Exception as oauth_exc:
        logger.exception("Google OAuth: callback failed; exception_type=%s", type(oauth_exc).__name__)
        error_message = "Google 授權處理失敗：" + str(oauth_exc)[:400]
        try:
            save_google_oauth_result("error", error_message)
        except Exception:
            pass
        st.session_state["google_drive_oauth_flash"] = ("error", error_message)
    finally:
        logger.info("Google OAuth: clearing callback query parameters and rerunning app")
        st.query_params.clear()
        st.rerun()

oauth_flash = st.session_state.pop("google_drive_oauth_flash", None)
if oauth_flash:
    if oauth_flash[0] == "success":
        st.success(oauth_flash[1])
    else:
        st.error(oauth_flash[1])

if role == "student" and student_access_paused:
    st.warning("🔒 學生網站目前暫停開放")
    st.info("畢業紀念冊網站目前正在暫停學生使用，請留意管理員後續公告。")
    st.stop()

if role is None:
    student_tab, admin_tab = st.tabs(["學生登入", "管理員登入"])
    with student_tab:
        if student_access_paused:
            st.warning("🔒 學生網站目前暫停開放")
            st.info("畢業紀念冊網站目前暫停學生登入及使用；管理員仍可正常登入與管理。")
        else:
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
    with admin_tab:
        st.subheader("管理員登入")
        username = st.text_input("管理員帳號", key="admin_user")
        password = st.text_input("管理員密碼", type="password", key="admin_pwd")
        if st.button("登入", type="primary", use_container_width=True, key="admin_login_button"):
            try:
                matched = verify_staff_account(username, password, ["admin", "teacher", "super_admin"])
                if matched:
                    set_session("admin", {
                        "username": matched["username"],
                        "display_name": matched.get("display_name") or matched["username"],
                        "staff_role": matched["role"],
                    })
                    st.rerun()
                else:
                    st.error("管理員帳號或密碼錯誤，或帳號已停用。")
            except Exception:
                st.error("管理員登入驗證暫時無法使用，請稍後再試。")
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
    st.stop()

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

st.caption(student_ui_text("login_session_caption", "登入有效時間：30 分鐘") if role == "student" else "登入有效時間：30 分鐘")
if role == "student":
    st.success(student_ui_text("student_login_success", "學生登入成功：{seat_no} 號｜{name}").format(seat_no=identity['seat_no'], name=identity['name']))
else:
    st.success(f"{identity.get('display_name') or identity.get('username') or '管理員'}，你好！")

# 登入後常用操作：靠右排列，刷新不會清除登入狀態。
toolbar_spacer, refresh_col, password_col, logout_col = st.columns([5, 1.25, 1.4, 1])
with refresh_col:
    if st.button(student_ui_text("refresh_button", "🔄 刷新") if role == "student" else "🔄 刷新", use_container_width=True, key="refresh_page_button"):
        st.rerun()
with password_col:
    if st.button(student_ui_text("change_password_button", "🔐 更改密碼") if role == "student" else "🔐 更改密碼", use_container_width=True, key="toggle_change_password"):
        st.session_state["show_change_password_form"] = not st.session_state.get("show_change_password_form", False)
with logout_col:
    if st.button(student_ui_text("logout_button", "登出") if role == "student" else "登出", use_container_width=True, key="logout_button"):
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
        "tab_group_signup": "👥 分組登記＆小組照繳交",
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
        "group_signup_title": "分組登記與小組合照繳交",
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
    except Exception:
        pass
    student_content = student_content_defaults
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
            if roster_groups:
                group_numbers = sorted(roster_groups)
                group_columns = st.columns(min(3, len(group_numbers)))
                for index, group_no in enumerate(group_numbers):
                    with group_columns[index % len(group_columns)]:
                        with st.container(border=True):
                            st.markdown(student_content["roster_group_title"].format(group_no=group_no))
                            member_ids = set(roster_groups[group_no])
                            group_members = [student for student in roster_students if student.get("id") in member_ids]
                            for member in group_members:
                                leader_prefix = student_content["roster_leader_prefix"] if member.get("id") == roster_leaders.get(group_no) else ""
                                st.write(student_content["roster_member_format"].format(seat_no=member.get("seat_no"), leader_prefix=leader_prefix, name=member.get("name")))
            else:
                st.info(student_content["roster_empty"])
            roster_unassigned = [student for student in roster_students if student.get("id") not in roster_assigned_ids]
            if roster_unassigned:
                with st.expander(student_content["roster_unassigned_label"].format(count=len(roster_unassigned))):
                    for student in roster_unassigned:
                        st.write(student_content["roster_unassigned_member_format"].format(seat_no=student.get("seat_no"), name=student.get("name")))
        except Exception:
            st.warning(student_content["roster_load_error"])
    
    student_tab_specs = [
        ("show_student_announcements", student_content["tab_announcements"]),
        ("show_personal_photo_upload", student_content["tab_personal_upload"]),
        ("show_my_photos", student_content["tab_my_photos"]),
        ("show_group_signup", student_content["tab_group_signup"]),
        ("show_class_group_photo", student_content["tab_class_photo"]),
        ("show_personal_photo_rules", student_content["tab_personal_rules"]),
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
                        st.success(student_content["upload_success"].format(count=count))
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
    if "show_class_group_photo" in student_tab_map:
        with student_tab_map["show_class_group_photo"]:
            st.subheader(student_content["class_photo_title"])
            st.markdown(f"{student_content['class_photo_date_label']} {student_content['class_photo_date']}")
            st.markdown(f"{student_content['class_photo_time_label']} {student_content['class_photo_time']}")
            st.markdown(f"{student_content['class_photo_location_label']} {student_content['class_photo_location']}")
            st.markdown(f"{student_content['class_photo_clothing_label']} {student_content['class_photo_clothing']}")
            st.markdown(f"{student_content['class_photo_count_label']} {student_content['class_photo_count']}")
            st.markdown(student_content["class_photo_actions_label"])
            st.markdown(student_content["class_photo_actions"])
            st.warning(student_content["class_photo_notice"])
    if "show_student_announcements" in student_tab_map:
        with student_tab_map["show_student_announcements"]:
            st.subheader(student_content["tab_announcements"])
            st.caption(student_content["announcements_caption"])
            try:
                now_utc = datetime.now(timezone.utc)
                notices = (
                    admin.table("announcements")
                    .select("id, title, content, category, is_pinned, publish_at, expires_at")
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
                        leader_prefix = student_content["roster_leader_prefix"] if member.get("student_id") == display_leader_id else ""
                        st.write(student_content["roster_member_format"].format(seat_no=member['seat_no'], leader_prefix=leader_prefix, name=member['student_name']))

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
                                                st.success(student_content["group_photo_success"].format(slot=slot))
                                                try:
                                                    drive_config = load_google_drive_config()
                                                    if drive_config.get("refresh_token_encrypted") and drive_config.get("folder_id"):
                                                        drive_result = backup_group_photo_to_drive(
                                                            my_group_no, slot, photo_data, photo_mime, extension, drive_config
                                                        )
                                                        st.success("☁️ Google Drive 備份成功：" + str(drive_result.get("name", "照片已備份")))
                                                    else:
                                                        st.warning("照片已安全存入 Supabase；Google Drive 尚未完成授權或資料夾設定，因此這次未備份。")
                                                except Exception as drive_backup_error:
                                                    st.warning("照片已安全存入 Supabase，但 Google Drive 備份未成功；不影響原照片。請管理員檢查備份設定。")
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
                                st.success(
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
    if "show_personal_photo_rules" in student_tab_map:
        with student_tab_map["show_personal_photo_rules"]:
            st.subheader(student_content["personal_rules_title"])
            st.warning(student_content["personal_rules_deadline"])
            st.markdown(student_content["personal_rules_list"])
            st.info(student_content["personal_rules_extra"])
            st.caption(student_content["personal_rules_contact"])

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
                    leader_prefix = "組長｜" if row.get("student_id") == roster_leaders.get(group_no) else ""
                    st.write(f"{row.get('seat_no')} 號｜{leader_prefix}{row.get('student_name')}")
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
    tab_labels = ["📢 公告管理中心", "🧾 小組登記與分組", "🗂️ 全班照片管理", "👤 人員資料管理", "⚙️ 顯示設定", "☁️ Google Drive 備份"]
    if is_full_admin:
        tab_labels.append("🔐 帳號管理")
    created_tabs = st.tabs(tab_labels)
    group_tab, signup_tab, photo_tab, personnel_tab, display_settings_tab = created_tabs[:5]
    drive_tab = created_tabs[5]
    staff_tab = created_tabs[6] if is_full_admin else None
    with signup_tab:
        st.subheader("學生自行組隊結果")
        st.caption("學生由組長建立小組並一次送出；每位學生只能屬於一組。管理員可查看各組名單及尚未組隊的學生。")
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
            st.write(
                f"全班 {len(students)} 位學生｜已組隊 {assigned_count} 位｜"
                f"尚未組隊 {len(ungrouped)} 位"
            )
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
                            st.success(f"第 {leader_group_no} 組組長已設定。")
                            st.rerun()
                        except Exception:
                            st.error(f"第 {leader_group_no} 組組長設定失敗，請確認該學生是否已擔任其他組組長。")
            except Exception:
                st.error("組長設定讀取失敗，請確認 group_leaders 資料表。")

            st.subheader("分組管理看板")
            if group_choices:
                st.markdown("**目前組別：** " + "　｜　".join(
                    f"第 {number} 組（{len(grouped.get(number, []))} 人）"
                    for number in group_choices
                ))
            else:
                st.info("目前還沒有組別，請按「＋ 新增組別」建立第一組。")
            st.caption("Notion 看板模式：每個組別是一個直向欄位，學生是一張張卡片。可橫向查看所有組別，並把學生拖曳到任何組別或「尚未組隊」。")
            if st.button("＋ 新增組別", type="secondary", key="admin_add_group_column"):
                try:
                    next_number = 1
                    while next_number in group_choices:
                        next_number += 1
                    admin.table("student_group_columns").insert(
                        {"group_number": next_number}
                    ).execute()
                    st.success(f"已新增第 {next_number} 組。")
                    st.rerun()
                except Exception as e:
                    error_detail = str(e)
                    st.error("新增組別失敗，資料庫回報：")
                    st.code(error_detail[:1200] if error_detail else "未提供詳細錯誤訊息")
                    st.info("請將上方錯誤內容回報，以便精確修復；不需要提供任何密碼或金鑰。")

            from streamlit_sortables import sort_items
            # 看板統一使用 grad_album 主資料的座號與姓名，避免舊 group_signups
            # 中的姓名文字與主資料不同，造成拖曳後無法對應到學生。
            student_label_by_id = {
                student["id"]: f"{student.get('seat_no')} 號｜{student.get('name')}"
                for student in students
            }
            student_lookup = {
                label: student
                for student in students
                for label in [student_label_by_id[student["id"]]]
            }
            group_boards = [
                {
                    "header": f"第 {group_no} 組",
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
                "header": "尚未組隊",
                "items": [
                    student_label_by_id[student["id"]]
                    for student in ungrouped
                    if student["id"] in student_label_by_id
                ],
            })
            st.caption(
                f"目前 {len(group_choices)} 個組別｜全班 {len(students)} 位學生｜"
                f"已分組 {assigned_count} 位｜尚未組隊 {len(ungrouped)} 位"
            )
            sorted_boards = sort_items(
                group_boards,
                multi_containers=True,
                key="admin_notion_group_board",
            )
            if st.button("儲存看板上的全班調整", type="primary", key="admin_save_all_group_cards"):
                save_step = "整理拖曳後的學生名單"
                try:
                    group_by_header = {
                        f"第 {group_no} 組": group_no
                        for group_no in group_choices
                    }
                    target_groups = {}
                    save_step = "檢查每位學生是否只出現一次"
                    for board in sorted_boards:
                        header = board.get("header")
                        if header == "尚未組隊":
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
                    st.success("看板上的全班分組調整已儲存。")
                    st.rerun()
                except Exception as e:
                    st.error(f"全班分組儲存失敗，錯誤發生於：{save_step}")
                    error_detail = f"{type(e).__name__}: {e}"
                    st.code(error_detail[:1500])
                    st.info("請把上方錯誤文字回報給我；不要貼上任何密碼或金鑰。")

            if group_choices:
                st.markdown("### 刪除整組")
                st.warning("刪除後，該組所有學生會回到「尚未組隊」，不會刪除學生資料。")
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
                        st.success(f"已解散第 {delete_group_no} 組，{released_count} 位學生已回到尚未組隊。")
                        st.rerun()
                    except Exception:
                        st.error("刪除分組失敗，請稍後再試。")

            if ungrouped:
                st.markdown("### 尚未組隊")
                for student in ungrouped:
                    st.write(f"{student.get('seat_no')} 號｜{student.get('name')}")
        except Exception:
            st.error("無法讀取小組名單，請確認 group_signups 資料表設定。")
    with group_tab:
        st.subheader("📢 公告管理中心")
        st.caption("集中管理班級通知。草稿不會顯示給學生；排程公告會在指定時間自動出現在學生的「最新公告」。")
        announcement_categories = ["一般通知", "緊急通知", "拍攝異動", "活動與集合", "照片繳交", "分組通知", "畢冊進度"]
        taipei_tz = timezone(timedelta(hours=8))
        now_taipei = datetime.now(taipei_tz)
        with st.expander("➕ 新增公告", expanded=True):
            announcement_templates = {
                "自訂公告": {"category": "一般通知", "title": "", "content": ""},
                "📣 一般通知": {"category": "一般通知", "title": "【班級通知】", "content": "通知事項：\n\n相關日期／時間：\n\n請同學留意，謝謝。"},
                "⚠️ 緊急通知": {"category": "緊急通知", "title": "【重要／緊急通知】", "content": "通知原因：\n\n需要同學配合的事項：\n\n請同學務必留意。"},
                "📸 拍攝時間或地點異動": {"category": "拍攝異動", "title": "【拍攝資訊異動】", "content": "原訂拍攝時間／地點：\n\n調整後時間／地點：\n\n其他注意事項："},
                "📤 照片繳交提醒": {"category": "照片繳交", "title": "【照片繳交提醒】", "content": "繳交項目：\n\n繳交期限：\n\n繳交方式：\n\n注意事項："},
                "👥 分組集合通知": {"category": "分組通知", "title": "【分組集合通知】", "content": "組別：\n\n集合日期：\n\n集合時間：\n\n集合地點：\n\n攜帶物品／注意事項："},
            }
            selected_template = st.selectbox("公告範本（可再自行修改）", list(announcement_templates.keys()))
            template_data = announcement_templates[selected_template]
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
                            admin.table("announcements").insert({
                                "title": new_notice_title.strip(),
                                "content": new_notice_content.strip(),
                                "category": new_notice_category,
                                "status": new_notice_status,
                                "is_pinned": new_notice_pin,
                                "publish_at": publish_dt.astimezone(timezone.utc).isoformat(),
                                "expires_at": expiry_dt.astimezone(timezone.utc).isoformat() if expiry_dt else None,
                            }).execute()
                            st.success("公告已建立。")
                            st.rerun()
                        except Exception:
                            st.error("公告建立失敗，請稍後再試。")
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
                                    st.success("公告已更新。")
                                    st.rerun()
                                except Exception:
                                    st.error("公告更新失敗，請稍後再試。")
                    delete_confirm = st.checkbox("我確認永久刪除此公告", key=f"notice_delete_confirm_{notice_id}")
                    if st.button("🗑️ 永久刪除公告", disabled=not delete_confirm, key=f"delete_notice_{notice_id}"):
                        try:
                            admin.table("announcements").delete().eq("id", notice_id).execute()
                            st.success("公告已刪除。")
                            st.rerun()
                        except Exception:
                            st.error("公告刪除失敗，請稍後再試。")
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
                p1, p2, p3, p4 = st.columns([2, 3, 1.2, 1.2])
                p1.write(f"第 {group_photo['group_number']} 組｜第 {group_photo['photo_slot']} 張")
                try:
                    p2.image(make_url(group_photo["storage_path"]), width=150)
                except Exception:
                    p2.caption("預覽失敗")
                try:
                    group_photo_raw = admin.storage.from_(BUCKET).download(group_photo["storage_path"])
                    p3.download_button(
                        "下載小組照",
                        data=group_photo_raw,
                        file_name=group_photo["storage_path"].split("/")[-1],
                        mime="image/jpeg",
                        key=f"admin_group_photo_download_{group_photo['group_number']}_{group_photo['photo_slot']}",
                        use_container_width=True,
                    )
                except Exception:
                    p3.caption("下載失敗")
                if p4.button("刪除小組照", key=f"admin_group_photo_delete_{group_photo['group_number']}_{group_photo['photo_slot']}"):
                    admin.storage.from_(BUCKET).remove([group_photo["storage_path"]])
                    admin.table("group_photos").delete().eq("group_number", group_photo["group_number"]).eq("photo_slot", group_photo["photo_slot"]).execute()
                    st.success("小組照片已刪除。")
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
                    st.success("照片已刪除。")
                    st.rerun()
        except Exception:
            st.error("照片清單讀取失敗，請確認 Storage bucket 名稱及權限。")

    with display_settings_tab:
        st.subheader("⚙️ 學生頁面設定")
        st.caption("學生頁面有 7 個獨立顯示開關；固定文字、標題、按鈕、提示及密碼操作文字都能編輯。公告標題與內容仍由公告管理中心維護；格式中的 {seat_no}、{name}、{count} 等欄位請保留。")
        visibility_options = [
            ("show_class_group_roster", "👥 全班分組一覽"),
            ("show_student_announcements", "📢 最新公告"),
            ("show_personal_photo_upload", "📤 個人生活照繳交"),
            ("show_my_photos", "🖼️ 我的照片"),
            ("show_group_signup", "👥 分組登記＆小組照繳交"),
            ("show_class_group_photo", "📸 班級團體照"),
            ("show_personal_photo_rules", "📝 個人生活照須知"),
        ]
        try:
            current_rows = admin.table("site_settings").select("setting_key, setting_value").execute().data
            current_settings = {row.get("setting_key"): row.get("setting_value") for row in current_rows}
            with st.form("student_page_visibility_settings"):
                st.markdown("### 👁️ 顯示開關")
                changed_visibility = {}
                pause_students_toggle = st.toggle("🔒 暫停學生登入及網站使用", value=current_settings.get("student_access_paused", True) is True, help="開啟後學生無法登入或繼續使用；管理員仍可正常登入及管理。")
                for key, label in visibility_options:
                    val = current_settings.get(key, True)
                    changed_visibility[key] = st.toggle(label, value=val if isinstance(val, bool) else True)
                save_visibility = st.form_submit_button("儲存顯示開關", type="primary")
            if save_visibility:
                for key, val in changed_visibility.items():
                    admin.table("site_settings").upsert({"setting_key": key, "setting_value": val, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="setting_key").execute()
                admin.table("site_settings").upsert({"setting_key": "student_access_paused", "setting_value": pause_students_toggle, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="setting_key").execute()
                st.success("學生頁面顯示設定及暫停狀態已更新。")
                st.rerun()

            st.divider()
            st.markdown("### ✏️ 內容設定")
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
                "tab_group_signup": "👥 分組登記＆小組照繳交",
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
                "group_signup_title": "分組登記與小組合照繳交",
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
            with st.form("student_page_content_settings"):
                edited_content = {}
                st.markdown("#### 📸 班級團體照")
                for key, label in [
                    ("class_photo_date", "拍攝日期"), ("class_photo_time", "集合時間"),
                    ("class_photo_location", "集合地點"), ("class_photo_clothing", "服裝要求"),
                    ("class_photo_count", "預計拍攝張數"), ("class_photo_actions", "指定動作"),
                    ("class_photo_notice", "提醒文字"),
                ]:
                    edited_content[key] = st.text_area(label, value=saved_content.get(key, content_defaults[key]), key="edit_"+key, height=75)
                st.markdown("#### 👥 分組拍攝注意事項")
                edited_content["group_notice"] = st.text_area("小組拍攝注意事項", value=saved_content.get("group_notice", content_defaults["group_notice"]), key="edit_group_notice", height=90)
                st.markdown("#### 📝 個人生活照須知")
                for key, label in [
                    ("personal_rules_deadline", "截止日期提醒"),
                    ("personal_rules_list", "生活照注意事項（可自行編輯編號及換行）"),
                    ("personal_rules_extra", "補充說明"), ("personal_rules_contact", "聯絡方式／問題反映文字"),
                ]:
                    edited_content[key] = st.text_area(label, value=saved_content.get(key, content_defaults[key]), key="edit_"+key, height=100)
                st.markdown("#### 🧩 其他學生頁面文字")
                content_labels = {
                    "roster_title": "全班分組一覽標題",
                    "roster_caption": "全班分組一覽說明",
                    "roster_empty": "尚無分組提示",
                    "roster_load_error": "名單載入失敗提示",
                    "roster_unassigned_label": "未分組區塊標題（{count} 會代入人數）",
                    "tab_announcements": "最新公告頁籤名稱",
                    "tab_personal_upload": "個人生活照繳交頁籤名稱",
                    "tab_my_photos": "我的照片頁籤名稱",
                    "tab_group_signup": "分組登記頁籤名稱",
                    "tab_class_photo": "班級團體照頁籤名稱",
                    "tab_personal_rules": "個人生活照須知頁籤名稱",
                    "no_student_sections": "所有區塊關閉時的提示",
                    "upload_title": "生活照上傳標題",
                    "upload_intro": "生活照上傳說明",
                    "upload_file_help": "照片格式與大小提示",
                    "upload_button": "生活照上傳按鈕",
                    "upload_choose_warning": "未選擇照片提示",
                    "upload_file_error": "檔案檢查錯誤（{filename}、{error}）",
                    "upload_fail": "照片上傳失敗提示（{filename}）",
                    "upload_success": "照片上傳成功提示（{count}）",
                    "my_photos_title": "我的照片標題",
                    "my_photos_empty": "沒有照片提示",
                    "my_photos_error": "照片讀取失敗提示",
                    "class_photo_title": "班級團體照標題",
                    "class_photo_actions_label": "指定動作欄位標題",
                    "announcements_caption": "最新公告說明",
                    "announcements_empty": "沒有公告提示",
                    "announcement_pinned": "置頂標籤",
                    "announcement_default_category": "公告預設分類",
                    "announcement_published_at": "公告發布時間文字（{published_at}）",
                    "announcements_error": "公告讀取失敗提示",
                    "group_signup_title": "分組登記區塊標題",
                    "group_leader_label": "組長資訊格式（{seat_no}、{name}）",
                    "group_signup_caption": "分組建立說明",
                    "group_joined": "已加入組別提示（{group_no}）",
                    "group_member_title": "組員名單標題（{group_no}）",
                    "group_photo_title": "小組合照標題",
                    "group_leader_missing": "未設定組長提示",
                    "group_photo_leader_help": "組長上傳說明",
                    "group_photo_member_help": "組員查看說明",
                    "group_photo_slot": "照片欄位名稱（{slot}）",
                    "group_photo_uploaded": "照片已繳交狀態",
                    "group_photo_missing": "照片未繳交狀態",
                    "group_photo_choose": "選擇照片欄位（{slot}）",
                    "group_photo_upload": "上傳／替換按鈕（{slot}）",
                    "group_photo_success": "小組照片成功提示（{slot}）",
                    "group_photo_fail": "小組照片失敗提示（{slot}）",
                    "group_photo_error": "小組照片讀取失敗提示",
                    "group_member_input": "組員座號輸入欄名稱",
                    "group_member_placeholder": "組員座號輸入範例",
                    "group_member_help": "組員座號輸入說明",
                    "group_submit": "建立小組按鈕",
                    "group_need_member": "未輸入組員提示",
                    "group_self_member": "輸入自己座號提示",
                    "group_success": "組隊成功提示（{group_no}、{member_count}）",
                    "group_duplicate_error": "重複組員／已加入其他組別錯誤",
                    "group_seat_error": "座號查無資料錯誤",
                    "group_submit_error": "組隊送出失敗錯誤",
                    "group_load_error": "分組資料讀取失敗錯誤",
                    "personal_rules_title": "個人生活照須知標題"
                }
                for key, label in content_labels.items():
                    edited_content[key] = st.text_area(label, value=saved_content.get(key, content_defaults[key]), key="edit_"+key, height=65)
                st.markdown("#### 🧾 動態標籤與格式")
                extra_content_labels = {
                    "roster_group_title": "分組標題格式",
                    "roster_leader_prefix": "組長標示文字",
                    "roster_member_format": "組員名單格式（{seat_no}、{leader_prefix}、{name}）",
                    "roster_unassigned_member_format": "未分組名單格式（{seat_no}、{name}）",
                    "class_photo_date_label": "拍攝日期欄位標籤",
                    "class_photo_time_label": "集合時間欄位標籤",
                    "class_photo_location_label": "集合地點欄位標籤",
                    "class_photo_clothing_label": "服裝要求欄位標籤",
                    "class_photo_count_label": "拍攝張數欄位標籤",
                    "group_photo_upload_error": "小組照片格式錯誤提示（{error} 會代入錯誤原因）",
                }
                for key, label in extra_content_labels.items():
                    edited_content[key] = st.text_area(label, value=saved_content.get(key, content_defaults[key]), key="edit_"+key, height=65)
                st.markdown("#### 🔐 學生登入與密碼操作文字")
                shared_ui_labels = {
                    "login_session_caption": "登入時間提示",
                    "student_login_success": "學生登入成功訊息格式",
                    "refresh_button": "刷新按鈕文字",
                    "change_password_button": "更改密碼按鈕文字",
                    "logout_button": "登出按鈕文字",
                    "password_title": "更改密碼區塊標題",
                    "password_student_caption": "學生更改密碼說明",
                    "password_current_label": "目前密碼欄位標籤",
                    "password_new_label": "新密碼欄位標籤",
                    "password_confirm_label": "確認新密碼欄位標籤",
                    "password_submit_button": "確認更改密碼按鈕",
                    "password_fill_warning": "欄位未填寫提示",
                    "password_length_warning": "密碼長度錯誤提示",
                    "password_mismatch_error": "密碼不一致提示",
                    "password_success": "密碼更新成功提示",
                    "password_wrong_error": "目前密碼錯誤提示",
                    "password_general_error": "密碼更新失敗提示"
                }
                for key, label in shared_ui_labels.items():
                    edited_content[key] = st.text_area(label, value=saved_content.get(key, content_defaults[key]), key="edit_"+key, height=65)
                save_content = st.form_submit_button("儲存內容設定", type="primary")
            if save_content:
                admin.table("site_settings").upsert({"setting_key": "student_page_content", "setting_value": edited_content, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="setting_key").execute()
                st.success("學生頁面內容已更新。")
                st.rerun()
        except Exception:
            st.error("讀取或儲存學生頁面設定失敗，請確認 site_settings 資料表及權限。")

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
                    st.success("顯示姓名已更新。")
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
                                st.success("學生資料已更新。")
                                st.rerun()
        except Exception:
            st.error("學生資料讀取或更新失敗，請確認資料表欄位及權限。")

    with drive_tab:
        # Show a persisted OAuth callback result after the admin signs in again.
        try:
            oauth_result_rows = (
                admin.table("site_settings")
                .select("setting_value")
                .eq("setting_key", "google_drive_oauth_last_result")
                .limit(1).execute().data
            )
            if oauth_result_rows:
                oauth_result = oauth_result_rows[0].get("setting_value") or {}
                result_age = time.time() - float(oauth_result.get("created_at", 0) or 0)
                if result_age <= 86400:
                    if oauth_result.get("status") == "success":
                        st.success(str(oauth_result.get("message") or "Google 授權成功。"))
                    else:
                        st.error(str(oauth_result.get("message") or "Google 授權失敗，未取得詳細原因。"))
                admin.table("site_settings").delete().eq(
                    "setting_key", "google_drive_oauth_last_result"
                ).execute()
        except Exception:
            st.warning("目前無法讀取 Google 授權診斷結果，請稍後再試。")
        st.subheader("☁️ Google Drive 自動備份")
        st.caption("Supabase 仍是主要照片儲存位置；Google Drive 只保存額外備份。此設定只有管理員能操作。")
        st.info("第一次使用請先連結 Google 帳戶，再選擇備份資料夾。網站會在每次小組合照成功存入 Supabase 後，自動備份到這個資料夾。")
        try:
            drive_config = load_google_drive_config()
            if not drive_config.get("refresh_token_encrypted"):
                st.warning("尚未連結 Google 帳戶。")
                if st.button("🔗 開始連結 Google 帳戶", key="google_drive_start_oauth"):
                    try:
                        oauth_url = build_google_oauth_url()
                        st.link_button("前往 Google 授權", oauth_url, type="primary")
                        st.caption("請使用擁有備份資料夾的 Google 帳戶登入並同意 drive.file 權限。")
                    except Exception as oauth_setup_error:
                        st.error("無法開始 Google 授權：" + str(oauth_setup_error)[:300])
            else:
                st.success("Google 帳戶已完成授權。")
                try:
                    access_token_for_picker = get_google_drive_access_token(drive_config)
                    picker_component = get_google_drive_folder_picker_component()
                    picker_result = picker_component(
                        data={
                            "access_token": access_token_for_picker,
                            "api_key": str(st.secrets.get("GOOGLE_PICKER_API_KEY", "")).strip(),
                            "project_number": str(st.secrets.get("GOOGLE_CLOUD_PROJECT_NUMBER", "")).strip(),
                        },
                        default={"folder": None},
                        on_folder_change=lambda: None,
                        key="google_drive_folder_picker",
                        height=90,
                    )
                    selected_folder = getattr(picker_result, "folder", None)
                    if isinstance(selected_folder, dict) and selected_folder.get("id"):
                        if selected_folder["id"] != drive_config.get("folder_id"):
                            drive_config["folder_id"] = selected_folder["id"]
                            drive_config["folder_name"] = selected_folder.get("name", "Google Drive 備份資料夾")
                            save_google_drive_config(drive_config)
                            st.success("備份資料夾已儲存：" + drive_config["folder_name"])
                            st.rerun()
                    if drive_config.get("folder_id"):
                        st.success("目前備份位置：" + str(drive_config.get("folder_name") or "已選擇的資料夾"))
                        st.caption("資料夾 ID 已安全儲存；不會公開顯示完整連結。")
                    else:
                        st.warning("尚未選擇備份資料夾。請按上方按鈕選擇。")
                except Exception as picker_error:
                    st.error("Google Drive 尚未準備完成：" + str(picker_error)[:400])
                    if st.button("重新連結 Google 帳戶", key="google_drive_reauth"):
                        st.session_state.pop("google_drive_access_token_cache", None)
                        st.link_button("前往 Google 授權", build_google_oauth_url(), type="primary")
                st.divider()
                if st.button("🔄 重新授權 Google 帳戶", key="google_drive_force_reauth"):
                    st.session_state.pop("google_drive_access_token_cache", None)
                    st.link_button("前往 Google 授權", build_google_oauth_url(), type="primary")
            st.caption("備份檔案會依組別建立子資料夾，並保留每次上傳的獨立版本。")
            st.divider()
            st.markdown("### 📦 手動備份現有小組照片")
            st.caption("將目前 Supabase「小組合照」資料表中的照片補備份到 Google Drive；不會刪除或修改 Supabase 原始照片。")
            manual_backup_disabled = not (drive_config.get("refresh_token_encrypted") and drive_config.get("folder_id"))
            if st.button("☁️ 立即備份所有小組合照", key="google_drive_manual_backup", type="primary", use_container_width=True, disabled=manual_backup_disabled):
                try:
                    current_group_photos = (
                        admin.table("group_photos")
                        .select("group_number, photo_slot, storage_path")
                        .order("group_number")
                        .order("photo_slot")
                        .execute().data
                    )
                    if not current_group_photos:
                        st.info("目前沒有可備份的小組合照。")
                    else:
                        completed = 0
                        failed = []
                        progress = st.progress(0, text="準備備份小組合照…")
                        total = len(current_group_photos)
                        for index, photo_row in enumerate(current_group_photos, start=1):
                            path = str(photo_row.get("storage_path") or "")
                            try:
                                raw_photo = admin.storage.from_(BUCKET).download(path)
                                extension = path.rsplit(".", 1)[-1].lower() if "." in path else "jpg"
                                mime_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(extension)
                                if not mime_type:
                                    raise RuntimeError("不支援的照片格式")
                                backup_group_photo_to_drive(
                                    photo_row["group_number"],
                                    photo_row["photo_slot"],
                                    raw_photo,
                                    mime_type,
                                    "jpg" if extension == "jpeg" else extension,
                                    drive_config,
                                )
                                completed += 1
                            except Exception:
                                failed.append(f"第{photo_row.get('group_number')}組第{photo_row.get('photo_slot')}張")
                            progress.progress(index / total, text=f"備份進度：{index}/{total}")
                        progress.empty()
                        if completed:
                            st.success(f"完成備份 {completed} 張小組合照。")
                        if failed:
                            st.warning("以下照片備份失敗：" + "、".join(failed[:20]))
                        if not failed:
                            st.success("所有現有小組合照都已送往 Google Drive。")
                except Exception as manual_backup_error:
                    st.error("手動備份未完成：" + str(manual_backup_error)[:300])
        except Exception as drive_setup_error:
            st.error("Google Drive 設定讀取失敗：" + str(drive_setup_error)[:400])

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
                            st.success("帳號已安全寫入 Supabase。")
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
                                st.success("帳號設定已更新。")
                                st.rerun()
                            except Exception:
                                st.error("帳號更新失敗，請稍後再試。")
            except Exception:
                st.error("無法讀取帳號清單，請稍後再試。")
    
