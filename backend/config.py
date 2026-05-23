"""
config.py — Cấu hình toàn cục: đường dẫn, biến môi trường, hằng số.
"""
import os
from dotenv import load_dotenv

# --- Đường dẫn dự án ---
BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# Nạp .env từ thư mục gốc
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"), override=True)

# --- Đường dẫn tài nguyên ---
DB_PATH      = os.path.join(PROJECT_ROOT, "database", "chat_history.db")
CHROMA_PATH  = os.path.join(PROJECT_ROOT, "database", "chroma_db")
STATIC_PATH  = os.path.join(PROJECT_ROOT, "static")

# --- Gemini ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# --- JWT ---
SECRET_KEY                    = os.getenv("SECRET_KEY", "ai-mentor-super-secret-key-2025-change-me")
ALGORITHM                     = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES   = 60 * 24 * 7   # 7 ngày

# --- Gmail SMTP ---
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")       # Gmail của bạn
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # App Password (16 ký tự)
SMTP_FROM     = os.getenv("SMTP_FROM", SMTP_USER) # Mặc định dùng chính SMTP_USER

# --- OTP ---
OTP_EXPIRE_MINUTES = 10   # Mã OTP hết hạn sau 10 phút
