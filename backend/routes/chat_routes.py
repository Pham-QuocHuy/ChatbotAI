"""
routes/chat_routes.py — Các endpoint chat chính:
  POST /chat              → Gửi tin nhắn văn bản
  POST /chat-image        → Gửi ảnh + câu hỏi
  GET  /history/{sid}     → Lấy lịch sử phiên chat
  POST /clear-history     → Xóa lịch sử phiên
"""
import asyncio
import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from ai_engine import bot_app, llm, get_content
from auth import get_current_user, require_auth
from database import (
    auto_title_session,
    clear_session_history,
    load_history,
    load_history_raw,
    save_message,
    session_belongs_to_user,
    update_session_time,
)

router = APIRouter(tags=["Chat"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message:    str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Helper: Phân tích ảnh với Gemini Vision
# ---------------------------------------------------------------------------
async def _analyze_image(image_bytes: bytes, mime_type: str, prompt: str) -> str:
    """Gửi ảnh lên Gemini và trả về mô tả / phân tích."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(content=[
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        {"type": "text", "text": prompt or
            "Hãy mô tả chi tiết ảnh bằng tiếng Việt. Nếu có code hãy đọc và giải thích. Nếu có lỗi hãy phân tích."},
    ])
    return get_content(await llm.ainvoke([message]))


# ---------------------------------------------------------------------------
# Helper: Lưu tin nhắn và cập nhật session (chỉ khi đã đăng nhập)
# ---------------------------------------------------------------------------
def _persist_chat(session_id: str, user_id: int, user_msg: str, bot_msg: str) -> None:
    save_message(session_id, "user", user_msg)
    save_message(session_id, "bot",  bot_msg)
    update_session_time(session_id)
    auto_title_session(session_id, user_id, user_msg)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/chat", summary="Chat văn bản")
async def chat(
    request: ChatRequest,
    current_user: Optional[dict] = Depends(get_current_user),
):
    is_logged_in = current_user is not None

    # Kiểm tra quyền sở hữu session
    if is_logged_in and not session_belongs_to_user(request.session_id, current_user["id"]):
        raise HTTPException(403, "Phiên chat không hợp lệ.")

    # Lấy lịch sử (chỉ khi đã đăng nhập)
    history = load_history(request.session_id) if is_logged_in else []
    if len(history) > 10:
        history = history[-10:]

    try:
        config  = {"configurable": {"thread_id": request.session_id}}
        results = await bot_app.ainvoke(
            {"query": request.message, "history": history},
            config=config
        )
    except asyncio.CancelledError:
        # Client đã ngắt kết nối (nhấn Stop) → im lặng, không crash server
        return {"response": "", "category": "", "sentiment": ""}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))

    # Lưu DB nếu đã đăng nhập
    if is_logged_in:
        _persist_chat(request.session_id, current_user["id"], request.message, results["response"])

    return {
        "response":  results["response"],
        "category":  results["category"],
        "sentiment": results["sentiment"],
    }


@router.post("/chat-image", summary="Chat với ảnh đính kèm")
async def chat_image(
    session_id: str               = Form("default"),
    message:    str               = Form(""),
    file:       UploadFile        = File(...),
    current_user: Optional[dict]  = Depends(get_current_user),
):
    # Kiểm tra định dạng ảnh
    allowed = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]
    if file.content_type not in allowed:
        raise HTTPException(400, f"Định dạng không hỗ trợ: {file.content_type}.")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ảnh quá lớn. Vui lòng upload ảnh nhỏ hơn 10MB.")

    is_logged_in = current_user is not None

    if is_logged_in and not session_belongs_to_user(session_id, current_user["id"]):
        raise HTTPException(403, "Phiên chat không hợp lệ.")

    history = load_history(session_id) if is_logged_in else []
    if len(history) > 10:
        history = history[-10:]

    prompt      = message.strip() or "Hãy phân tích nội dung trong ảnh này."
    full_prompt = f"[Người dùng gửi kèm một ảnh]\nCâu hỏi: {prompt}"

    try:
        vision_result  = await _analyze_image(image_bytes, file.content_type, prompt)
        combined_query = (
            f"Dưới đây là nội dung được trích xuất từ ảnh của sinh viên:\n\n"
            f"{vision_result}\n\nDựa vào đó, hãy trả lời câu hỏi: {prompt}"
        )
        config  = {"configurable": {"thread_id": f"{session_id}_img"}}
        results = await bot_app.ainvoke(
            {"query": combined_query, "history": history},
            config=config
        )
    except asyncio.CancelledError:
        return {"response": "", "vision_extract": "", "category": "", "sentiment": ""}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))

    if is_logged_in:
        _persist_chat(session_id, current_user["id"], full_prompt, results["response"])

    return {
        "response":       results["response"],
        "vision_extract": vision_result,
        "category":       results.get("category", ""),
        "sentiment":      results.get("sentiment", ""),
    }


@router.get("/history/{session_id}", summary="Lấy lịch sử phiên chat")
async def get_chat_history(
    session_id: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    # Guest không có lịch sử
    if current_user is None:
        return {"messages": []}
    if not session_belongs_to_user(session_id, current_user["id"]):
        raise HTTPException(403, "Không có quyền xem phiên này.")
    return {"messages": load_history_raw(session_id)}


@router.post("/clear-history", summary="Xóa lịch sử phiên chat")
async def clear_history_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(require_auth),
):
    if not session_belongs_to_user(request.session_id, current_user["id"]):
        raise HTTPException(403, "Không có quyền xóa phiên này.")
    clear_session_history(request.session_id)
    return {"status": "success"}
