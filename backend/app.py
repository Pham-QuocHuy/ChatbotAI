"""
app.py — Entry point của ứng dụng FastAPI.

Chỉ làm 3 việc:
  1. Khởi tạo FastAPI app và include các router
  2. Mount thư mục static
  3. Chạy uvicorn (khi gọi trực tiếp)
"""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from config import STATIC_PATH
from database import init_db
from routes.auth_routes    import router as auth_router
from routes.session_routes import router as session_router
from routes.chat_routes    import router as chat_router

# ---------------------------------------------------------------------------
# Khởi tạo database
# ---------------------------------------------------------------------------
init_db()

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title       = "AI Mentor IT",
    description = "Hệ thống tư vấn sinh viên CNTT thông minh",
    version     = "2.0.0",
)

# Cấu hình CORS cho phép tất cả các nguồn truy cập (hoặc cấu hình domain cụ thể)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)       # /auth/*
app.include_router(session_router)    # /sessions/*
app.include_router(chat_router)       # /chat, /chat-image, /history, /clear-history

# ---------------------------------------------------------------------------
# Mount Static Files (frontend)
# ---------------------------------------------------------------------------
os.makedirs(STATIC_PATH, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_PATH, html=True), name="static")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port)
