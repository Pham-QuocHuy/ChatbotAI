"""
ai_engine.py — LangGraph AI Workflow:
  - Khởi tạo LLM (Gemini), embedding, vector store
  - Định nghĩa State và các node xử lý
  - Build và compile graph → bot_app
"""
import os
import re
import httpx
from typing import TypedDict, List

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_chroma import Chroma
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from bs4 import BeautifulSoup

from config import GOOGLE_API_KEY, CHROMA_PATH

# ---------------------------------------------------------------------------
# LLM + Embedding + Search Tool
# ---------------------------------------------------------------------------
llm          = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0.2)
search_tool  = DuckDuckGoSearchResults()

# Dùng mô hình local Vietnamese SBERT (miễn phí, offline)
embeddings   = HuggingFaceEmbeddings(model_name="keepitreal/vietnamese-sbert")

vector_store = None
if os.path.exists(CHROMA_PATH):
    vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
else:
    print(f"⚠️ Chưa có ChromaDB tại {CHROMA_PATH}. Tính năng RAG tắt.")

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
Bạn là một AI Mentor CNTT (Công nghệ thông tin) chuyên nghiệp, nhiệt tình và giàu kinh nghiệm.
Nhiệm vụ của bạn là hỗ trợ sinh viên CNTT trong việc học tập, giải quyết vấn đề kỹ thuật và định hướng nghề nghiệp.

Phong cách phản hồi:
1. Chuyên nghiệp nhưng gần gũi, giống như một người tiền bối (Mentor).
2. Giải thích rõ ràng, dễ hiểu, tránh dùng quá nhiều thuật ngữ mà không giải thích.
3. Khi giải thích code: không chỉ đưa ra đáp án, hãy giải thích tại sao và hướng dẫn debug.
4. Luôn khuyến khích sinh viên tự tìm tòi và phát triển tư duy logic.
5. Nếu câu hỏi không liên quan đến CNTT, hãy khéo léo từ chối và hướng sinh viên quay lại chủ đề.
"""

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class State(TypedDict):
    query:           str
    category:        str
    sentiment:       str
    search_result:   str
    rag_result:      str
    router_decision: str
    history:         List[BaseMessage]
    response:        str


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def get_content(response) -> str:
    """Trích xuất text từ LLM response (str hoặc object)."""
    if isinstance(response, str):
        return response
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
    return str(response)


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------
def categorize(state: State) -> State:
    """Phân loại câu hỏi vào 1 trong 5 nhóm."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Classify this IT student query into exactly one of: Programming, Roadmap, Career, Projects, GeneralIT."),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}"),
    ])
    res = get_content((prompt | llm).invoke({"query": state["query"], "history": state.get("history", [])}))
    category = "GeneralIT"
    for cat in ["Programming", "Roadmap", "Career", "Projects", "GeneralIT"]:
        if cat.lower() in res.lower():
            category = cat
            break
    return {"category": category}


def analyze_sentiment(state: State) -> State:
    """Phân tích cảm xúc: Frustrated hoặc Neutral."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Analyze student sentiment: Frustrated or Neutral."),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}"),
    ])
    res = get_content((prompt | llm).invoke({"query": state["query"], "history": state.get("history", [])}))
    return {"sentiment": "Frustrated" if "Frustrated" in res else "Neutral"}


def route_query(state: State) -> State:
    """Quyết định tìm kiếm nội bộ (RAG) hay web ngoài."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a smart router for an IT University Chatbot.
Decide if the student's query should be answered using:
1. 'internal': for internal university rules, curriculum, student handbook, or specific regulations.
2. 'external': for general IT knowledge, programming help, career trends, or finding people on the web.
Respond with exactly one word: 'internal' or 'external'."""),
        ("human", "{query}"),
    ])
    res = get_content((prompt | llm).invoke({"query": state["query"]}))
    decision = "internal" if "internal" in res.lower() else "external"
    print(f"🧭 Router: {decision}")
    return {"router_decision": decision}


def retrieve_rag(state: State) -> State:
    """Tìm kiếm trong ChromaDB nội bộ."""
    if vector_store is None:
        return {"rag_result": ""}
    docs = vector_store.as_retriever(search_kwargs={"k": 3}).invoke(state["query"])
    if not docs:
        return {"rag_result": ""}
    context = "\n\n".join(
        f"Nguồn: {d.metadata.get('source_file', 'Unknown')} "
        f"(Phân loại: {d.metadata.get('category', 'Chung')})\nNội dung: {d.page_content}"
        for d in docs
    )
    print(f"📚 RAG: {len(docs)} đoạn phù hợp")
    return {"rag_result": context}


async def _fetch_text(url: str) -> str:
    """Cào text từ URL (helper nội bộ)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.extract()
            return soup.get_text(separator=" ", strip=True)[:4000]
    except Exception as e:
        print(f"⚠️ Lỗi cào {url}: {e}")
        return ""


async def web_search_node(state: State) -> State:
    """Tìm kiếm web với DuckDuckGo + cào nội dung thực tế."""
    keywords = [
        "mới nhất", "xu hướng", "phiên bản", "năm 2024", "năm 2025",
        "thị trường", "market", "latest", "trường", "đại học",
        "có không", "liệt kê", "danh sách", "tiến sĩ", "thạc sĩ",
        "giáo viên", "giảng viên",
    ]
    should_search = (
        any(kw in state["query"].lower() for kw in keywords)
        or state["category"] in ["Roadmap", "Career"]
    )
    if not should_search:
        return {"search_result": "No search needed."}

    try:
        q = state["query"].lower()
        search_query = (
            "site:ttn.edu.vn danh sách giảng viên bộ môn công nghệ thông tin"
            if "tây nguyên" in q and any(w in q for w in ["giảng viên", "giáo viên", "danh sách"])
            else state["query"]
        )
        print(f"🔍 DuckDuckGo: {search_query}")
        raw = search_tool.run(search_query)
        links = re.findall(r"link:\s*(https?://[^\s,]+)", raw)

        if not links:
            return {"search_result": raw}

        combined = ""
        for link in links[:2]:
            print(f"🌐 Cào: {link}")
            text = await _fetch_text(link)
            if text:
                combined += f"\n--- Nội dung từ {link} ---\n{text}\n"

        return {"search_result": combined or raw}
    except Exception as e:
        print(f"⚠️ Web search lỗi: {e}")
        return {"search_result": "Could not perform search."}


def generate_response(state: State) -> State:
    """Tổng hợp và sinh câu trả lời cuối cùng."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT + """
CHỈ THỊ ĐẶC BIỆT:
1. Ưu tiên 'Dữ liệu nội bộ (RAG)' cho các câu hỏi về quy chế, trường học.
   Đọc phần `(Phân loại: ...)` để biết tài liệu thuộc năm nào.
   Nếu xung đột giữa các năm → ưu tiên năm mới nhất.
2. Nếu không có dữ liệu nội bộ → dùng 'Dữ liệu từ Web'.
3. Nếu cần tìm giảng viên → bốc chính xác tên từ Web.
4. RAG và Web mâu thuẫn → ưu tiên RAG, thông báo cho sinh viên.
5. Không bịa thông tin. Nếu không biết → nói thẳng.
6. Về học phí / điểm số → nhắc kiểm tra cổng thông tin chính thức.

Dữ liệu nội bộ (RAG):
{rag_result}

Dữ liệu từ Web:
{search_result}
"""),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}"),
    ])
    res = get_content((prompt | llm).invoke({
        "category":      state["category"],
        "sentiment":     state["sentiment"],
        "rag_result":    state.get("rag_result", ""),
        "search_result": state.get("search_result", ""),
        "query":         state["query"],
        "history":       state.get("history", []),
    }))
    return {"response": res}


# ---------------------------------------------------------------------------
# Build Graph
# ---------------------------------------------------------------------------
def _route_after_decision(state: State) -> str:
    return "retrieve_rag" if state["router_decision"] == "internal" else "web_search"


def _route_after_rag(state: State) -> str:
    if not state.get("rag_result"):
        print("🔄 RAG không có dữ liệu → Web Search")
        return "web_search"
    return "generate_response"


_workflow = StateGraph(State)
_workflow.add_node("categorize",       categorize)
_workflow.add_node("analyze_sentiment", analyze_sentiment)
_workflow.add_node("route_query",      route_query)
_workflow.add_node("retrieve_rag",     retrieve_rag)
_workflow.add_node("web_search",       web_search_node)
_workflow.add_node("generate_response", generate_response)

_workflow.set_entry_point("categorize")
_workflow.add_edge("categorize",        "analyze_sentiment")
_workflow.add_edge("analyze_sentiment", "route_query")
_workflow.add_conditional_edges("route_query",  _route_after_decision,
                                {"retrieve_rag": "retrieve_rag", "web_search": "web_search"})
_workflow.add_conditional_edges("retrieve_rag", _route_after_rag,
                                {"web_search": "web_search", "generate_response": "generate_response"})
_workflow.add_edge("web_search",        "generate_response")
_workflow.add_edge("generate_response", END)

# Compiled app — import từ các route
bot_app = _workflow.compile(checkpointer=MemorySaver())
