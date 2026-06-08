"""
ai_engine.py — LangGraph AI Workflow:
  - Khởi tạo LLM (Gemini), embedding, vector store
  - Định nghĩa State và các node xử lý
  - Build và compile graph → bot_app
"""
import os
import re
import httpx
import tempfile
import shutil
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
    # Vì ChromaDB C++ backend (hnswlib) không đọc được đường dẫn Unicode tiếng Việt trên Windows,
    # chúng ta copy dữ liệu sang thư mục tạm hệ thống để load.
    temp_dir = os.path.join(tempfile.gettempdir(), "chroma_temp_run")
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        shutil.copytree(CHROMA_PATH, temp_dir)
        vector_store = Chroma(persist_directory=temp_dir, embedding_function=embeddings)
        print(f"✅ Đã tải ChromaDB từ {CHROMA_PATH} thông qua thư mục tạm {temp_dir}")
    except Exception as e:
        print(f"❌ Lỗi khi tải ChromaDB index: {e}")
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
    rag_target_folder: str


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


# ---------------------------------------------------------------------------
# Keyword mapping cho RAG target folder
# ---------------------------------------------------------------------------
RAG_FOLDER_KEYWORDS = {
    "de_cuong_hoc_phan": [
        # Đề cương, syllabus, thi cử
        "đề cương", "syllabus", "kiểm tra", "bài tập",
        "thang điểm", "cách tính điểm", "hình thức thi",
        "nội dung môn", "lịch thi", "thi cuối kỳ", "thi giữa kỳ",
        "môn học phần", "học phần",
        # Tên môn ngắn — match linh hoạt hơn
        "cấu trúc dữ liệu", "giải thuật",
        "lập trình hướng đối tượng", "lập trình căn bản",
        "cơ sở dữ liệu", "hệ điều hành", "mạng máy tính",
        "kiến trúc máy tính", "trí tuệ nhân tạo",
        "an toàn thông tin", "an ninh mạng",
        "phát triển web", "lập trình web",
        "công nghệ phần mềm", "kiểm thử phần mềm",
        "xử lý ảnh", "thị giác máy tính",
        "học máy", "khai phá dữ liệu",
        "toán rời rạc", "đại số tuyến tính", "xác suất thống kê",
        # Prefix "môn" với tên môn
        "môn lập trình", "môn toán", "môn vật lý", "môn mạng",
        "môn cơ sở dữ liệu", "môn hệ điều hành", "môn kiến trúc",
        "môn trí tuệ nhân tạo", "môn an toàn", "môn web",
        "môn cấu trúc dữ liệu", "môn giải thuật",
    ],

    "chuong_trinh_dao_tao": [
        "chương trình đào tạo", "khung chương trình", "tín chỉ yêu cầu",
        "số tín chỉ", "cấu trúc chương trình", "lộ trình học",
        "các môn học", "danh sách môn", "môn bắt buộc", "môn tự chọn",
        "học kỳ nào học", "năm mấy học môn",
    ],
    "quy_che_dao_tao": [
        "học phí", "mức phí", "khoản thu", "đóng tiền",
        "học bổng", "miễn giảm học phí", "hỗ trợ tài chính",
        "quy chế", "quy định", "điểm cảnh báo", "cảnh báo học vụ",
        "buộc thôi học", "điều kiện tốt nghiệp", "xét tốt nghiệp",
        "điểm rèn luyện", "xếp loại học lực", "điểm trung bình tích lũy",
        "nghỉ học", "bảo lưu", "thôi học",
    ],
    "nghien_cuu_va_do_an": [
        "đồ án", "luận văn", "khóa luận", "nghiên cứu khoa học",
        "đề tài nghiên cứu", "báo cáo tốt nghiệp", "hội đồng bảo vệ",
        "giáo viên hướng dẫn đồ án", "thực tập tốt nghiệp",
    ],
    "hoat_dong_ngoai_khoa": [
        "câu lạc bộ", "clb", "ngoại khóa", "hoạt động ngoài giờ",
        "tình nguyện", "đoàn thanh niên", "hội sinh viên",
        "sự kiện", "cuộc thi", "hackathon", "workshop ngoại khóa",
    ],
    "thong_tin_nganh_cntt": [
        "giảng viên", "giáo viên", "thầy", "cô giáo",
        "khoa cntt", "bộ môn", "ban chủ nhiệm", "trưởng khoa",
        "liên hệ khoa", "thông tin ngành", "giới thiệu ngành",
        "tuyển sinh", "điểm chuẩn", "chỉ tiêu",
    ],
}


def analyze_rag_target(state: State) -> State:
    """
    Xác định thư mục dữ liệu phù hợp nhất với câu hỏi.
    Chiến lược: Keyword match trước → LLM fallback cho câu mơ hồ.
    """
    query = state["query"].lower()

    # Bước 1: Keyword match theo từng folder (ưu tiên theo thứ tự)
    priority_order = [
        "de_cuong_hoc_phan",
        "quy_che_dao_tao",
        "nghien_cuu_va_do_an",
        "hoat_dong_ngoai_khoa",
        "chuong_trinh_dao_tao",
        "thong_tin_nganh_cntt",
    ]
    for folder in priority_order:
        keywords = RAG_FOLDER_KEYWORDS.get(folder, [])
        matched = [k for k in keywords if k in query]
        if matched:
            print(f"🎯 RAG Target Folder: {folder} [keyword: {matched[0]}]")
            return {"rag_target_folder": folder}

    # Bước 2: Fallback LLM cho câu không khớp keyword nào
    print(f"🎯 RAG Target Folder: fallback to LLM...")
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a smart router. Based on the user's query, determine which folder of internal documents is most relevant.
Options:
- chuong_trinh_dao_tao: questions about curriculum, subjects list, credits, training programs structure.
- de_cuong_hoc_phan: questions about course syllabus, exams format, grading of SPECIFIC subjects.
- hoat_dong_ngoai_khoa: clubs, extracurriculars, volunteer work.
- nghien_cuu_va_do_an: scientific research, graduation projects, thesis.
- quy_che_dao_tao: rules, regulations, tuition fees, scholarships, academic warnings, points policy.
- thong_tin_nganh_cntt: IT department info, teachers, staff, admission info.
- all: if it doesn't clearly fit one or covers multiple.

Respond with exactly ONE option from the list above."""),
        ("human", "{query}"),
    ])
    res = get_content((prompt | llm).invoke({"query": state["query"]})).strip().lower()
    valid_folders = ["chuong_trinh_dao_tao", "de_cuong_hoc_phan", "hoat_dong_ngoai_khoa",
                     "nghien_cuu_va_do_an", "quy_che_dao_tao", "thong_tin_nganh_cntt"]

    target = "all"
    for folder in valid_folders:
        if folder in res:
            target = folder
            break

    print(f"🎯 RAG Target Folder: {target} [llm]")
    return {"rag_target_folder": target}


def retrieve_rag(state: State) -> State:
    """Tìm kiếm trong ChromaDB nội bộ với Multi-Query và Fallback."""
    if vector_store is None:
        return {"rag_result": ""}
    
    target_folder = state.get("rag_target_folder", "all")
    
    # 1. Multi-Query: LLM tự mở rộng câu hỏi thành 3 biến thể
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Bạn là trợ lý AI. Nhiệm vụ của bạn là tạo ra 2 câu hỏi biến thể bằng tiếng Việt, có cùng ý nghĩa với câu hỏi gốc của người dùng, để giúp tối ưu hóa việc tìm kiếm tài liệu trong cơ sở dữ liệu vector. Mỗi câu hỏi nằm trên 1 dòng, không đánh số hay gạch đầu dòng."),
        ("human", "{query}")
    ])
    try:
        res = get_content((prompt | llm).invoke({"query": state["query"]}))
        variations = [q.strip() for q in res.split("\n") if q.strip()][:2]
        queries = [state["query"]] + variations
    except Exception:
        queries = [state["query"]]
    
    # 2. Tìm kiếm cho tất cả các câu hỏi
    all_docs = []
    seen_contents = set()
    
    search_kwargs = {"k": 12}
    if target_folder != "all":
        search_kwargs["filter"] = {"category": target_folder}
        
    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    
    for q in queries:
        docs = retriever.invoke(q)
        for d in docs:
            if d.page_content not in seen_contents:
                seen_contents.add(d.page_content)
                all_docs.append(d)
                
    # 3. Cơ chế Fallback nếu không tìm thấy trong thư mục được nhắm mục tiêu
    if not all_docs and target_folder != "all":
        print(f"⚠️ Không tìm thấy kết quả ở thư mục '{target_folder}', đang Fallback tìm trên toàn bộ hệ thống...")
        search_kwargs_fallback = {"k": 12}
        retriever_fallback = vector_store.as_retriever(search_kwargs=search_kwargs_fallback)
        for q in queries:
            docs = retriever_fallback.invoke(q)
            for d in docs:
                if d.page_content not in seen_contents:
                    seen_contents.add(d.page_content)
                    all_docs.append(d)
    
    if not all_docs:
        return {"rag_result": ""}
    
    # Lấy tối đa 15 documents unique để LLM đọc
    all_docs = all_docs[:15]
    
    context = "\n\n".join(
        f"Nguồn: {d.metadata.get('source_file', 'Unknown')} "
        f"(Phân loại: {d.metadata.get('category', 'Chung')})\nNội dung: {d.page_content}"
        for d in all_docs
    )
    print(f"📚 RAG: {len(all_docs)} đoạn phù hợp (Filter: {target_folder}, Multi-Query: {len(queries)} câu)")
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
    """Tìm kiếm web với DuckDuckGo + cào nội dung thực tế.
    Luôn giới hạn trong site:ttn.edu.vn cho các câu hỏi về trường.
    """
    # Từ khoá kích hoạt web search
    keywords = [
        "mới nhất", "xu hướng", "phiên bản", "năm 2024", "năm 2025",
        "thị trường", "market", "latest", "trường", "đại học",
        "có không", "liệt kê", "danh sách", "tiến sĩ", "thạc sĩ",
        "giáo viên", "giảng viên",
        # Học phí và số liệu cụ thể theo năm
        "học phí", "mức phí", "bao nhiêu", "chi phí học",
        "năm 2022", "năm 2023", "năm 2021", "học kỳ", "học bổng",
        "miễn giảm", "đóng tiền", "khoản thu",
    ]
    should_search = (
        any(kw in state["query"].lower() for kw in keywords)
        or state["category"] in ["Roadmap", "Career"]
    )
    if not should_search:
        return {"search_result": "No search needed."}

    try:
        # Luôn scope về ttn.edu.vn (Đại học Tây Nguyên)
        search_query = f"{state['query']} site:ttn.edu.vn"
        print(f"🔍 DuckDuckGo (ttn.edu.vn): {search_query}")
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
   Nếu nói rõ năm nào thì phải trả lời chính xác năm đó.
2. Nếu không có dữ liệu nội bộ → dùng 'Dữ liệu từ Web'.
   Nếu tra cứu từ web phải là trang ttn.edu.vn, tập trung vào ngành cntt là chính.
   Không được lấy thông tin từ các trang web khác.
   Nếu không tìm thấy từ web thì trả lời là không tìm thấy chứ không được bịa.
3. Nếu cần tìm giảng viên → bốc chính xác tên từ Web.
4. RAG và Web mâu thuẫn → ưu tiên RAG, thông báo cho sinh viên.
5. KHÔNG BỊA THÔNG TIN — NGHIÊM NGẶT:
   - Chỉ đưa ra số liệu (học phí, điểm, ngày tháng) khi tài liệu CÓ GHI RÕ RÀNG.
   - Nếu RAG chỉ có thông tin LIÊN QUAN nhưng KHÔNG TRẢ LỜI TRỰC TIẾP câu hỏi
     (VD: hỏi "học phí 2022" nhưng RAG chỉ có "hỗ trợ học phí dân tộc") →
     PHẢI nói thẳng: "Tài liệu nội bộ chưa có thông tin cụ thể về [vấn đề này].
     Bạn nên kiểm tra tại website chính thức: https://www.ttn.edu.vn hoặc
     liên hệ Phòng Kế hoạch Tài chính của trường."
   - TUYỆT ĐỐI KHÔNG suy đoán hay đưa ra số liệu không có trong tài liệu.
6. Về học phí / điểm số trước tiên kiểm tra các dữ liệu nội bộ (RAG) nếu không có thì tìm kiếm trên web →  nếu ko có nữa thì nhắc kiểm tra cổng thông tin chính thức ttn.edu.vn.
7. NẾU USER YÊU CẦU LIỆT KÊ DANH SÁCH, BẮT BUỘC LIỆT KÊ ĐẦY ĐỦ 100%.

Dữ liệu nội bộ (RAG):
{rag_result}

Dữ liệu từ Web (ttn.edu.vn):
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
    rag = state.get("rag_result", "")
    if not rag:
        print("🔄 RAG không có dữ liệu → Web Search")
        return "web_search"
    # Câu hỏi về số liệu cụ thể (học phí, năm...) → luôn bổ sung web search
    # dù RAG có kết quả (để tránh RAG trả kết quả liên quan nhưng không đúng)
    factual_keywords = [
        "học phí", "bao nhiêu", "mức phí", "chi phí học",
        "năm 2022", "năm 2023", "năm 2021", "khoản thu", "đóng tiền",
        "học bổng", "miễn giảm",
    ]
    query = state.get("query", "").lower()
    if any(kw in query for kw in factual_keywords):
        print("📊 Câu hỏi số liệu cụ thể → Bổ sung Web Search song song RAG")
        return "web_search"
    return "generate_response"


_workflow = StateGraph(State)
_workflow.add_node("categorize",       categorize)
_workflow.add_node("analyze_sentiment", analyze_sentiment)
_workflow.add_node("route_query",      route_query)
_workflow.add_node("analyze_rag_target", analyze_rag_target)
_workflow.add_node("retrieve_rag",     retrieve_rag)
_workflow.add_node("web_search",       web_search_node)
_workflow.add_node("generate_response", generate_response)

_workflow.set_entry_point("categorize")
_workflow.add_edge("categorize",        "analyze_sentiment")
_workflow.add_edge("analyze_sentiment", "route_query")
_workflow.add_conditional_edges("route_query",  _route_after_decision,
                                {"retrieve_rag": "analyze_rag_target", "web_search": "web_search"})
_workflow.add_edge("analyze_rag_target", "retrieve_rag")
_workflow.add_conditional_edges("retrieve_rag", _route_after_rag,
                                {"web_search": "web_search", "generate_response": "generate_response"})
_workflow.add_edge("web_search",        "generate_response")
_workflow.add_edge("generate_response", END)

# Compiled app — import từ các route
bot_app = _workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Quick RAG Search — dùng cho chat ảnh (bypass graph)
# ---------------------------------------------------------------------------
async def quick_rag_search(query: str) -> str:
    """
    Tìm kiếm RAG nhanh mà không đi qua LangGraph.
    Dùng khi có ảnh đính kèm: câu hỏi GỐC (không phải combined_query)
    được dùng để tìm tài liệu bổ sung, ưu tiên thấp hơn nội dung ảnh.
    """
    if vector_store is None:
        return ""

    try:
        # Bước 1: Xác định thư mục target (tái dụng node hiện có)
        target_state = analyze_rag_target({"query": query,
                                           "rag_target_folder": "all",
                                           "category": "", "sentiment": "",
                                           "search_result": "", "rag_result": "",
                                           "router_decision": "", "history": [],
                                           "response": ""})

        # Bước 2: Retrieve (tái dụng node hiện có)
        search_state = {
            "query": query,
            "rag_target_folder": target_state.get("rag_target_folder", "all"),
            "category": "", "sentiment": "",
            "search_result": "", "rag_result": "",
            "router_decision": "", "history": [], "response": "",
        }
        result_state = retrieve_rag(search_state)
        return result_state.get("rag_result", "")
    except Exception as e:
        print(f"⚠️ quick_rag_search lỗi: {e}")
        return ""

