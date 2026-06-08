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
# Helper: Sinh câu trả lời cho chat ảnh (ưu tiên ảnh, RAG bổ sung)
# ---------------------------------------------------------------------------
async def _generate_image_response(
    vision_result: str,
    rag_context: str,
    user_prompt: str,
    history: list,
) -> str:
    """
    Tổng hợp câu trả lời khi có ảnh:
      - Ưu tiên tuyệt đối nội dung trích xuất từ ảnh
      - RAG / tài liệu chỉ dùng để bổ sung / xác nhận
      - Không qua LangGraph
    """
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    rag_section = (
        f"\n\nTài liệu nội bộ tham khảo (chỉ dùng để bổ sung):\n{rag_context}"
        if rag_context else
        "\n\n(Không có tài liệu nội bộ liên quan — hãy trả lời hoàn toàn dựa vào ảnh và kiến thức chung.)"
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT + f"""
CHỈ THỊ XỬ LÝ ẢNH — ĐỌC KỸ:
1. ƯU TIÊN TUYỆT ĐỐI nội dung được trích xuất từ ảnh để trả lời câu hỏi.
2. Nếu ảnh đã có đủ thông tin → trả lời thẳng từ ảnh, không phụ thuộc tài liệu.
3. Tài liệu nội bộ CHỈ dùng để BỔ SUNG hoặc XÁC NHẬN thông tin trong ảnh.
4. Nếu thông tin trong ảnh KHÁC với tài liệu → nêu rõ cả hai, khuyên sinh viên kiểm tra cổng thông tin chính thức.
5. Nếu ảnh bị mờ hoặc không đủ thông tin → nói rõ và dùng tài liệu bổ sung.
6. Tuyệt đối KHÔNG bỏ qua hoặc mâu thuẫn với dữ liệu rõ ràng trong ảnh.

--- Nội dung trích xuất từ ảnh ---
{vision_result}
{rag_section}
"""),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}"),
    ])

    res = get_content(await (prompt_template | llm).ainvoke({
        "query": user_prompt,
        "history": history,
    }))
    return res


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
        # Bước 1: Vision AI đọc ảnh (ưu tiên cao nhất)
        print(f"🖼️  Vision: đang phân tích ảnh...")
        vision_result = await _analyze_image(image_bytes, file.content_type, prompt)
        print(f"🖼️  Vision result ({len(vision_result)} chars): {vision_result[:120]}...")

        # Bước 2: RAG nhanh với câu hỏi GỐC (không phải combined) — chỉ để bổ sung
        print(f"📎 RAG bổ sung cho ảnh: tìm theo câu hỏi gốc '{prompt[:60]}...'")
        rag_context = await quick_rag_search(prompt)
        if rag_context:
            print(f"📎 RAG bổ sung: {len(rag_context)} chars")
        else:
            print(f"📎 RAG bổ sung: không tìm thấy tài liệu liên quan")

        # Bước 3: Tổng hợp — ưu tiên ảnh, RAG chỉ bổ sung (bypass LangGraph)
        response = await _generate_image_response(
            vision_result=vision_result,
            rag_context=rag_context,
            user_prompt=prompt,
            history=history,
        )

    except asyncio.CancelledError:
        return {"response": "", "vision_extract": "", "category": "", "sentiment": ""}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))

    if is_logged_in:
        _persist_chat(session_id, current_user["id"], full_prompt, response)

    return {
        "response":       response,
        "vision_extract": vision_result,
        "category":       "Vision",
        "sentiment":      "Neutral",
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
