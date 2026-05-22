import os
import base64
import sqlite3
import httpx
from typing import Dict, TypedDict, Union, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_chroma import Chroma
from bs4 import BeautifulSoup
import re
import time

# Xác định đường dẫn gốc dự án dựa vào vị trí file backend/app.py
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# Nạp file .env nằm ở thư mục gốc dự án
env_path = os.path.join(PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=env_path, override=True)

# --- Cấu hình các đường dẫn tuyệt đối ---
DB_PATH = os.path.join(PROJECT_ROOT, "database", "chat_history.db")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "database", "chroma_db")
STATIC_PATH = os.path.join(PROJECT_ROOT, "static")

def init_db():
    # Tạo thư mục chứa database nếu chưa có
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_message(session_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (session_id, role, content)
        VALUES (?, ?, ?)
    """, (session_id, role, content))
    conn.commit()
    conn.close()

def load_history(session_id: str) -> List[BaseMessage]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for role, content in rows:
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "bot":
            history.append(AIMessage(content=content))
    return history

def clear_session_history(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM messages WHERE session_id = ?
    """, (session_id,))
    conn.commit()
    conn.close()

# Khởi tạo DB khi chạy app
init_db()

# --- Cấu hình Gemini ---
google_api_key = os.getenv('GOOGLE_API_KEY')
llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0.2)
search_tool = DuckDuckGoSearchResults()

# --- RAG Setup ---
# LỰA CHỌN 1: Dùng mô hình cục bộ (Local Embedding) - Miễn phí 100%, Offline, Không giới hạn Quota (Đang sử dụng)
embeddings = HuggingFaceEmbeddings(model_name="keepitreal/vietnamese-sbert")

# LỰA CHỌN 2: Dùng Google Gemini API (Online) - Chất lượng cao, nhưng giới hạn 15 RPM / 1500 RPD cho gói Free
# Để sử dụng lựa chọn này, hãy comment Lựa chọn 1 ở trên và bỏ comment Lựa chọn 2 ở dưới.
# class SafeGoogleEmbeddings(GoogleGenerativeAIEmbeddings):
#     def embed_documents(self, texts: list[str]) -> list[list[float]]:
#         from google.genai import types
#         import time
#         if not texts: return []
#         contents = [types.Content(parts=[types.Part.from_text(text=t if t.strip() else "rỗng")]) for t in texts]
#         max_retries = 8
#         delay = 10.0
#         for attempt in range(max_retries):
#             try:
#                 response = self.client.models.embed_content(model=self.model, contents=contents)
#                 return [emb.values for emb in response.embeddings]
#             except Exception as e:
#                 err_msg = str(e)
#                 if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
#                     print(f"⚠️ Đụng độ Rate Limit (429). Đang ngủ {delay} giây và thử lại...")
#                     time.sleep(delay)
#                     delay *= 1.5
#                 else: raise e
#         raise Exception("Rate limit exceeded")
#
# # Thử mô hình mới: models/gemini-embedding-2
# embeddings = SafeGoogleEmbeddings(model="models/gemini-embedding-2", google_api_key=google_api_key)
# # Hoặc mô hình cũ ban đầu: models/embedding-001
# # embeddings = SafeGoogleEmbeddings(model="models/embedding-001", google_api_key=google_api_key)

vector_store = None
if os.path.exists(CHROMA_PATH):
    vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
else:
    print(f"⚠️ Chưa có CSDL ChromaDB tại {CHROMA_PATH}. Tính năng RAG có thể không hoạt động.")

# --- System Prompt ---
SYSTEM_PROMPT = """
Bạn là một AI Mentor CNTT (Công nghệ thông tin) chuyên nghiệp, nhiệt tình và giàu kinh nghiệm.
Nhiệm vụ của bạn là hỗ trợ sinh viên CNTT trong việc học tập, giải quyết vấn đề kỹ thuật và định hướng nghề nghiệp.

Phong cách phản hồi:
1. Chuyên nghiệp nhưng gần gũi, giống như một người tiền bối (Mentor).
2. Giải thích rõ ràng, dễ hiểu, tránh dùng quá nhiều thuật ngữ mà không giải thích.
3. Khi giải thích code: không chỉ đưa ra đáp án, hãy giải thích tại sao lại làm như vậy và hướng dẫn cách debug.
4. Luôn khuyến khích sinh viên tự tìm tòi và phát triển tư duy logic.
5. Nếu câu hỏi không liên quan đến CNTT, hãy khéo léo từ chối và hướng sinh viên quay lại chủ đề học tập.
"""

def get_content(response: any) -> str:
    if isinstance(response, str): return response
    if hasattr(response, 'content'):
        content = response.content
        if isinstance(content, str): return content
        if isinstance(content, list):
            return "".join([part.get('text', '') if isinstance(part, dict) else str(part) for part in content])
    return str(response)

# 2. LangGraph Logic
class State(TypedDict):
    query: str
    category: str
    sentiment: str
    search_result: str
    rag_result: str
    router_decision: str
    history: List[BaseMessage]
    response: str

###
def categorize(state: State) -> State:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Classify this IT student query into: Programming, Roadmap, Career, Projects, GeneralIT."),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}")
    ])
    chain = prompt | llm
    res = get_content(chain.invoke({"query": state["query"], "history": state.get("history", [])}))
    category = "GeneralIT"
    for cat in ["Programming", "Roadmap", "Career", "Projects", "GeneralIT"]:
        if cat.lower() in res.lower():
            category = cat
            break
    return {"category": category}
######

def analyze_sentiment(state: State) -> State:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Analyze student sentiment: Frustrated or Neutral."),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}")
    ])
    chain = prompt | llm
    res = get_content(chain.invoke({"query": state["query"], "history": state.get("history", [])}))
    return {"sentiment": "Frustrated" if "Frustrated" in res else "Neutral"}

def route_query(state: State) -> State:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a smart router for an IT University Chatbot.
Decide if the student's query should be answered using:
1. 'internal': for internal university rules, curriculum, student handbook, or specific regulations.
2. 'external': for general IT knowledge, programming help, career trends, or finding people on the web.
Respond with exactly one word: 'internal' or 'external'."""),
        ("human", "{query}")
    ])
    chain = prompt | llm
    res = get_content(chain.invoke({"query": state["query"]}))
    decision = "internal" if "internal" in res.lower() else "external"
    print(f"🧭 Router Decision: {decision}")
    return {"router_decision": decision}

def retrieve_rag(state: State) -> State:
    if vector_store is None:
        print("⚠️ Không tìm thấy ChromaDB, bỏ qua RAG.")
        return {"rag_result": ""}
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    docs = retriever.invoke(state["query"])
    
    if not docs:
        print("⚠️ Không tìm thấy thông tin trong CSDL nội bộ.")
        return {"rag_result": ""}
        
    context = "\n\n".join([f"Nguồn: {d.metadata.get('source_file', 'Unknown')} (Phân loại: {d.metadata.get('category', 'Chung')})\nNội dung: {d.page_content}" for d in docs])
    print(f"📚 RAG đã tìm thấy {len(docs)} đoạn văn bản phù hợp.")
    return {"rag_result": context}

async def fetch_and_extract_text_async(url: str) -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.extract()
                
            text = soup.get_text(separator=' ', strip=True)
            return text[:4000]
    except Exception as e:
        print(f"⚠️ Lỗi cào dữ liệu từ {url}: {e}")
        return ""

async def web_search_node(state: State) -> State:
    keywords = [
        "mới nhất", "xu hướng", "phiên bản", "năm 2024", "năm 2025", 
        "thị trường", "market", "latest", "trường", "đại học", 
        "có không", "liệt kê", "danh sách", "tiến sĩ", "thạc sĩ", "giáo viên", "giảng viên"
    ]
    should_search = any(kw in state["query"].lower() for kw in keywords) or state["category"] in ["Roadmap", "Career"]
    
    if should_search:
        try:
            q = state['query'].lower()
            if "tây nguyên" in q and ("giảng viên" in q or "giáo viên" in q or "danh sách" in q):
                search_query = "site:ttn.edu.vn danh sách giảng viên bộ môn công nghệ thông tin"
            else:
                search_query = state['query']
            
            print(f"🚀 Đang tìm kiếm DuckDuckGo: {search_query}")
            search_results_str = search_tool.run(search_query)
            
            links = re.findall(r"link:\s*(https?://[^\s,]+)", search_results_str)
            
            if not links:
                print("⚠️ Không tìm thấy link nào từ kết quả tìm kiếm. Sử dụng snippet thô.")
                return {"search_result": search_results_str}
                
            combined_text = ""
            for link in links[:2]:
                print(f"🚀 Đang cào dữ liệu thực tế từ: {link}")
                extracted = await fetch_and_extract_text_async(link)
                if extracted:
                    combined_text += f"\n--- Nội dung từ {link} ---\n{extracted}\n"
            
            if combined_text:
                return {"search_result": combined_text}
            else:
                return {"search_result": search_results_str}
                
        except Exception as e:
            print(f"⚠️ Lỗi web search node: {e}")
            return {"search_result": "Could not perform search."}
    return {"search_result": "No search needed."}

def generate_response(state: State) -> State:
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT + """
    CHỈ THỊ ĐẶC BIỆT:
    1. Ưu tiên sử dụng 'Dữ liệu nội bộ (RAG)' để trả lời các câu hỏi về quy chế, trường học. Chú ý đọc phần `(Phân loại: ...)` để biết tài liệu thuộc năm nào hoặc mảng nào. Nếu có xung đột dữ liệu giữa các năm, bắt buộc lấy năm mới nhất (ví dụ: 2026 ưu tiên hơn 2025) trừ khi sinh viên hỏi cụ thể về năm cũ.
    2. Nếu không có 'Dữ liệu nội bộ', hãy dựa vào 'Dữ liệu thô từ Web'.
    3. Nếu câu hỏi yêu cầu tìm giảng viên, hãy bốc chính xác tên từ Web.
    4. Nếu dữ liệu RAG và Web mâu thuẫn nhau, hãy ưu tiên RAG và thông báo cho sinh viên biết.
    5. Không được bịa đặt thông tin. Nếu không tìm thấy dữ liệu, hãy thẳng thắn nói không biết.
    6. Khi trả lời về học phí hoặc điểm số, hãy luôn nhắc sinh viên kiểm tra lại trên cổng thông tin chính thức.
    Dữ liệu nội bộ (RAG):
    {rag_result}
    
    Dữ liệu thô từ Web:
    {search_result}
    """),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}")
    ])
    chain = prompt | llm
    res = get_content(chain.invoke({
        "category": state["category"],
        "sentiment": state["sentiment"],
        "rag_result": state.get("rag_result", ""),
        "search_result": state.get("search_result", ""),
        "query": state["query"],
        "history": state.get("history", [])
    }))
    return {"response": res}

######
workflow = StateGraph(State)
workflow.add_node("categorize", categorize)
workflow.add_node("analyze_sentiment", analyze_sentiment)
workflow.add_node("route_query", route_query)
workflow.add_node("retrieve_rag", retrieve_rag)
workflow.add_node("web_search", web_search_node)
workflow.add_node("generate_response", generate_response)

workflow.add_edge("categorize", "analyze_sentiment")
workflow.add_edge("analyze_sentiment", "route_query")

def route_after_decision(state: State):
    if state["router_decision"] == "internal":
        return "retrieve_rag"
    else:
        return "web_search"

workflow.add_conditional_edges("route_query", route_after_decision, {
    "retrieve_rag": "retrieve_rag",
    "web_search": "web_search"
})

def route_after_rag(state: State):
    if not state.get("rag_result"):
        print("🔄 Fallback: Chuyển sang Web Search vì RAG không có dữ liệu.")
        return "web_search"
    return "generate_response"

workflow.add_conditional_edges("retrieve_rag", route_after_rag, {
    "web_search": "web_search",
    "generate_response": "generate_response"
})

workflow.add_edge("web_search", "generate_response")
workflow.add_edge("generate_response", END)
workflow.set_entry_point("categorize")
#####

checkpointer = MemorySaver()
bot_app = workflow.compile(checkpointer=checkpointer)

# 3. FastAPI App
app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

async def analyze_image_with_gemini(image_bytes: bytes, mime_type: str, prompt: str) -> str:
    image_data = base64.b64encode(image_bytes).decode("utf-8")
    vision_message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
            },
            {
                "type": "text",
                "text": prompt if prompt else "Hãy mô tả chi tiết nội dung trong ảnh này bằng tiếng Việt. Nếu có code, hãy đọc và giải thích. Nếu có lỗi, hãy phân tích và đề xuất cách sửa.",
            },
        ]
    )
    response = await llm.ainvoke([vision_message])
    return get_content(response)

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        history = load_history(request.session_id)
        if len(history) > 10:
            history = history[-10:]

        config = {"configurable": {"thread_id": request.session_id}}
        inputs = {
            "query": request.message,
            "history": history
        }
        
        results = await bot_app.ainvoke(inputs, config=config)
        
        save_message(request.session_id, "user", request.message)
        save_message(request.session_id, "bot", results["response"])
            
        return {
            "response": results["response"],
            "category": results["category"],
            "sentiment": results["sentiment"]
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat-image")
async def chat_image(
    session_id: str = Form("default"),
    message: str = Form(""),
    file: UploadFile = File(...)
):
    try:
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]
        mime_type = file.content_type
        if mime_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Định dạng không hỗ trợ: {mime_type}. Chỉ chấp nhận JPG, PNG, GIF, WEBP, BMP.")

        image_bytes = await file.read()
        if len(image_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Ảnh quá lớn. Vui lòng upload ảnh nhỏ hơn 10MB.")

        history = load_history(session_id)
        if len(history) > 10:
            history = history[-10:]

        prompt = message if message.strip() else "Hãy phân tích nội dung trong ảnh này."
        full_prompt = f"[Người dùng gửi kèm một ảnh]\nCâu hỏi: {prompt}"

        vision_result = await analyze_image_with_gemini(image_bytes, mime_type, prompt)
        combined_query = f"Dưới đây là nội dung được trích xuất từ ảnh của sinh viên:\n\n{vision_result}\n\nDựa vào đó, hãy trả lời câu hỏi: {prompt}"

        config = {"configurable": {"thread_id": f"{session_id}_img"}}
        inputs = {
            "query": combined_query,
            "history": history
        }
        results = await bot_app.ainvoke(inputs, config=config)

        save_message(session_id, "user", full_prompt)
        save_message(session_id, "bot", results["response"])

        return {
            "response": results["response"],
            "vision_extract": vision_result,
            "category": results.get("category", ""),
            "sentiment": results.get("sentiment", "")
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{session_id}")
async def get_chat_history(session_id: str):
    try:
        history = load_history(session_id)
        messages = []
        for msg in history:
            role = "user" if isinstance(msg, HumanMessage) else "bot"
            messages.append({
                "role": role,
                "content": msg.content
            })
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear-history")
async def clear_history_endpoint(request: ChatRequest):
    try:
        clear_session_history(request.session_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if not os.path.exists(STATIC_PATH):
    os.makedirs(STATIC_PATH)

app.mount("/", StaticFiles(directory=STATIC_PATH, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
