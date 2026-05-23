"""
database.py — Khởi tạo SQLite và toàn bộ hàm CRUD:
  - users               : tài khoản người dùng
  - chat_sessions       : phiên hội thoại
  - messages            : tin nhắn
  - email_verifications : OTP xác minh email
"""
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import bcrypt
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from config import DB_PATH, OTP_EXPIRE_MINUTES


# ---------------------------------------------------------------------------
# Password hashing (dùng bcrypt trực tiếp, tránh xung đột passlib)
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def init_db() -> None:
    """Tạo các bảng nếu chưa tồn tại."""
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            user_id    INTEGER NOT NULL,
            title      TEXT DEFAULT 'Cuộc trò chuyện mới',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_verifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            otp_code   TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            is_used    INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------
def create_user(username: str, email: str, password: str) -> dict:
    """Tạo người dùng mới. Raises ValueError nếu username/email trùng."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, hash_password(password))
        )
        conn.commit()
        return {"id": cur.lastrowid, "username": username, "email": email}
    except sqlite3.IntegrityError as e:
        raise ValueError(str(e))
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, username, email, password_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1], "email": row[2], "password_hash": row[3]}
    return None


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1], "email": row[2]}
    return None


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------
def get_user_sessions(user_id: int) -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
        SELECT session_id, title, created_at, updated_at
        FROM chat_sessions
        WHERE user_id = ?
        ORDER BY updated_at DESC
    """, (user_id,))
    rows = conn.fetchall() if False else cur.fetchall()
    conn.close()
    return [
        {"session_id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]


def create_session(user_id: int, title: str = "Cuộc trò chuyện mới") -> dict:
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO chat_sessions (session_id, user_id, title) VALUES (?, ?, ?)",
        (session_id, user_id, title)
    )
    conn.commit()
    conn.close()
    return {"session_id": session_id, "title": title}


def delete_session(session_id: str, user_id: int) -> None:
    """Xóa phiên chat. Raises PermissionError nếu user không sở hữu."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM chat_sessions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id)
    )
    if not cur.fetchone():
        conn.close()
        raise PermissionError("Không có quyền xóa phiên này.")
    cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def rename_session(session_id: str, user_id: int, new_title: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "UPDATE chat_sessions SET title = ? WHERE session_id = ? AND user_id = ?",
        (new_title, session_id, user_id)
    )
    conn.commit()
    conn.close()


def session_belongs_to_user(session_id: str, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT 1 FROM chat_sessions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id)
    )
    result = cur.fetchone() is not None
    conn.close()
    return result


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------
def save_message(session_id: str, role: str, content: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()


def load_history(session_id: str) -> List[BaseMessage]:
    """Trả về lịch sử dạng LangChain messages."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    )
    rows = cur.fetchall()
    conn.close()
    history: List[BaseMessage] = []
    for role, content in rows:
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "bot":
            history.append(AIMessage(content=content))
    return history


def load_history_raw(session_id: str) -> List[dict]:
    """Trả về lịch sử dạng dict (dùng cho API response)."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]


def clear_session_history(session_id: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def update_session_time(session_id: str) -> None:
    """Cập nhật updated_at khi có tin nhắn mới."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,)
    )
    conn.commit()
    conn.close()


def auto_title_session(session_id: str, user_id: int, first_message: str) -> None:
    """Tự động đặt tiêu đề từ tin nhắn đầu (chỉ khi vẫn còn tên mặc định)."""
    title = first_message[:50] + ("..." if len(first_message) > 50 else "")
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        "SELECT title FROM chat_sessions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id)
    )
    row = cur.fetchone()
    if row and row[0] == "Cuộc trò chuyện mới":
        cur.execute(
            "UPDATE chat_sessions SET title = ? WHERE session_id = ?",
            (title, session_id)
        )
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# OTP Email Verification
# ---------------------------------------------------------------------------
def create_otp(email: str) -> str:
    """Tạo OTP 6 số, lưu DB (vô hiệu cụ trước), trả về code."""
    code       = f"{random.randint(0, 999999):06d}"
    expires_at = (datetime.now() + timedelta(minutes=OTP_EXPIRE_MINUTES)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    # Hủy các OTP chưa dùng cũ của email này
    cur.execute(
        "UPDATE email_verifications SET is_used = 1 WHERE email = ? AND is_used = 0",
        (email,)
    )
    cur.execute(
        "INSERT INTO email_verifications (email, otp_code, expires_at) VALUES (?, ?, ?)",
        (email, code, expires_at)
    )
    conn.commit()
    conn.close()
    return code


def verify_otp(email: str, code: str) -> bool:
    """Xác minh OTP. Trả True và đánh dấu đã dùng nếu hợp lệ."""
    now  = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
        SELECT id FROM email_verifications
        WHERE email = ? AND otp_code = ? AND is_used = 0 AND expires_at > ?
    """, (email, code, now))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE email_verifications SET is_used = 1 WHERE id = ?", (row[0],))
        conn.commit()
    conn.close()
    return row is not None


def cleanup_expired_otps() -> None:
    """Dọn OTP hết hạn (gọi kèm mỗi lần tạo OTP mới)."""
    now  = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("DELETE FROM email_verifications WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()


def email_already_registered(email: str) -> bool:
    """Kiểm tra email đã có tài khoản chưa."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE email = ?", (email,))
    result = cur.fetchone() is not None
    conn.close()
    return result
