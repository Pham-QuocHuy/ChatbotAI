"""
routes/auth_routes.py — API xác thực người dùng:
  POST /auth/send-otp  → Gửi mã OTP về email (bước 1 đăng ký)
  POST /auth/register  → Xác minh OTP + tạo tài khoản (bước 2)
  POST /auth/login     → Đăng nhập, nhận JWT
  GET  /auth/me        → Lấy thông tin user hiện tại
"""
import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel

from auth import create_access_token, require_auth
from database import (
    create_user,
    get_user_by_username,
    verify_password,
    create_otp,
    verify_otp,
    cleanup_expired_otps,
    email_already_registered,
)
from email_service import send_otp_email

router = APIRouter(prefix="/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SendOtpRequest(BaseModel):
    email: str


class RegisterRequest(BaseModel):
    username: str
    email:    str
    password: str
    otp_code: str   # Mã OTP nhập từ email


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Helper: gửi email trong background (không block response)
# ---------------------------------------------------------------------------
def _send_email_background(to_email: str, code: str) -> None:
    try:
        send_otp_email(to_email, code)
        print(f"✉️  OTP gửi thành công → {to_email}")
    except Exception as e:
        print(f"❌ Gửi email thất bại: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/send-otp", summary="Gửi mã OTP xác minh về email")
async def send_otp(req: SendOtpRequest, background_tasks: BackgroundTasks):
    email = req.email.strip().lower()

    if "@" not in email:
        raise HTTPException(400, "Email không hợp lệ.")
    if email_already_registered(email):
        raise HTTPException(409, "Email này đã được sử dụng để đăng ký tài khoản.")

    # Dọn OTP hết hạn
    cleanup_expired_otps()

    # Tạo OTP và gửi trong background
    code = create_otp(email)
    background_tasks.add_task(_send_email_background, email, code)

    return {"status": "sent", "message": f"Mã xác minh đã được gửi về {email}"}


@router.post("/register", summary="Đăng ký tài khoản (cần OTP hợp lệ)")
async def register(req: RegisterRequest):
    # Validation cơ bản
    if len(req.username.strip()) < 3:
        raise HTTPException(400, "Tên đăng nhập phải có ít nhất 3 ký tự.")
    if len(req.password) < 6:
        raise HTTPException(400, "Mật khẩu phải có ít nhất 6 ký tự.")
    if "@" not in req.email:
        raise HTTPException(400, "Email không hợp lệ.")
    if len(req.otp_code) != 6 or not req.otp_code.isdigit():
        raise HTTPException(400, "Mã xác minh phải là 6 chữ số.")

    # Xác minh OTP
    if not verify_otp(req.email.strip().lower(), req.otp_code.strip()):
        raise HTTPException(400, "Mã xác minh không đúng hoặc đã hết hạn. Vui lòng gửi lại mã mới.")

    try:
        user  = create_user(req.username.strip(), req.email.strip().lower(), req.password)
        token = create_access_token({"sub": str(user["id"])})
        return {
            "access_token": token,
            "token_type":   "bearer",
            "user":         {"id": user["id"], "username": user["username"], "email": user["email"]},
        }
    except ValueError as e:
        msg = str(e)
        if "username" in msg:
            raise HTTPException(409, "Tên đăng nhập đã tồn tại.")
        if "email" in msg:
            raise HTTPException(409, "Email đã được sử dụng.")
        raise HTTPException(400, msg)


@router.post("/login", summary="Đăng nhập")
async def login(req: LoginRequest):
    user = get_user_by_username(req.username.strip())
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng.")

    token = create_access_token({"sub": str(user["id"])})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user":         {"id": user["id"], "username": user["username"], "email": user["email"]},
    }


@router.get("/me", summary="Lấy thông tin user hiện tại")
async def me(current_user: dict = Depends(require_auth)):
    return current_user
