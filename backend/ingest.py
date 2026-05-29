import os
import re
import unicodedata
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

# Xác định đường dẫn gốc dự án dựa vào vị trí file backend/ingest.py
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# Nạp file .env nằm ở thư mục gốc dự án
env_path = os.path.join(PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=env_path, override=True)

if pytesseract is not None:
    custom_tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if custom_tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = custom_tesseract_cmd

# 1. Cấu hình các đường dẫn tuyệt đối
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "database", "chroma_db")

# Kiểm tra API KEY
google_api_key = os.getenv('GOOGLE_API_KEY')
if not google_api_key:
    print("❌ Lỗi: Không tìm thấy GOOGLE_API_KEY trong file .env")
    exit(1)

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

COMMON_NOISE_PATTERNS = [
    r"^\s*trang\s+\d+(\s*/\s*\d+)?\s*$",
    r"^\s*page\s+\d+(\s*/\s*\d+)?\s*$",
    r"^\s*\d+\s*$",
]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _normalize_text(text: str) -> str:
    """Chuẩn hóa Unicode và khoảng trắng."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_line(line: str) -> bool:
    """Nhận diện dòng rác (số trang, dòng quá ngắn, ký tự nhiễu)."""
    candidate = line.strip().lower()
    if not candidate:
        return True
    if len(candidate) <= 2:
        return True
    for pattern in COMMON_NOISE_PATTERNS:
        if re.match(pattern, candidate):
            return True
    return False


def clean_document_content(text: str) -> str:
    """Làm sạch văn bản trích xuất từ PDF/TXT/MD."""
    text = _normalize_text(text)
    if not text:
        return ""

    lines = [ln.strip() for ln in text.splitlines()]
    kept_lines = [ln for ln in lines if not _is_noise_line(ln)]

    # Gộp lại, giữ đoạn văn có xuống dòng để hỗ trợ chia chunk theo ngữ nghĩa.
    cleaned = "\n".join(kept_lines)
    cleaned = _normalize_text(cleaned)
    return cleaned


def enrich_metadata(file_path: str, category: str) -> dict:
    """Bổ sung metadata để retrieval chính xác hơn."""
    source_file = os.path.basename(file_path)
    lower_name = source_file.lower()
    year_match = re.search(r"(20\d{2})", lower_name)
    year = year_match.group(1) if year_match else "unknown"

    doc_type = "general"
    if "hoc_phi" in lower_name or "học phí" in lower_name:
        doc_type = "tuition"
    elif "hoc_bong" in lower_name or "học bổng" in lower_name:
        doc_type = "scholarship"
    elif "chuong_trinh_dao_tao" in lower_name:
        doc_type = "curriculum"
    elif "de_cuong" in lower_name or "đề cương" in lower_name:
        doc_type = "course_outline"
    elif "quy_che" in lower_name or "quy chế" in lower_name:
        doc_type = "regulation"

    return {
        "source_file": source_file,
        "category": category,
        "year": year,
        "doc_type": doc_type,
    }


def _ocr_image_file(file_path: str) -> str:
    """OCR cho file ảnh bằng pytesseract."""
    if Image is None or pytesseract is None:
        return ""
    try:
        with Image.open(file_path) as img:
            text = pytesseract.image_to_string(img, lang="vie+eng")
            return clean_document_content(text)
    except Exception as e:
        print(f"⚠️ OCR ảnh lỗi ({os.path.basename(file_path)}): {e}")
        return ""


def _ocr_pdf_page(file_path: str, page_number_zero_based: int) -> str:
    """OCR một trang PDF scan bằng PyMuPDF + pytesseract."""
    if fitz is None or Image is None or pytesseract is None:
        return ""
    doc = None
    try:
        doc = fitz.open(file_path)
        if page_number_zero_based < 0 or page_number_zero_based >= len(doc):
            return ""
        page = doc[page_number_zero_based]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        mode = "RGB" if pix.n >= 3 else "L"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img, lang="vie+eng")
        return clean_document_content(text)
    except Exception as e:
        print(f"⚠️ OCR PDF trang {page_number_zero_based + 1} lỗi ({os.path.basename(file_path)}): {e}")
        return ""
    finally:
        if doc is not None:
            doc.close()


def _maybe_warn_ocr_dependencies():
    """Thông báo thiếu dependency OCR (nếu có)."""
    if Image is None or pytesseract is None or fitz is None:
        print("ℹ️ OCR ảnh/PDF scan chưa đầy đủ dependency. Cần: pillow, pytesseract, pymupdf và Tesseract OCR.")


def load_documents():
    """Tải tất cả các file PDF/TXT/MD và OCR ảnh trong thư mục data/"""
    if not os.path.exists(DATA_DIR):
        print(f"⚠️ Thư mục {DATA_DIR} không tồn tại. Đang tạo...")
        os.makedirs(DATA_DIR)
        return []

    _maybe_warn_ocr_dependencies()

    documents = []
    for root, _, files in os.walk(DATA_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                # Lấy tên thư mục chứa file để làm phân loại (category)
                folder_name = os.path.basename(root)
                category = folder_name if folder_name != "data" else "Chung"
                base_metadata = enrich_metadata(file_path, category)
                file_ext = os.path.splitext(file)[1].lower()

                if file_ext == ".pdf":
                    loader = PyPDFLoader(file_path)
                    docs = loader.load()
                    for d in docs:
                        cleaned_text = clean_document_content(d.page_content)

                        # Nếu trang PDF scan trích text rỗng/quá ngắn thì OCR bổ sung.
                        if len(cleaned_text) < 40:
                            page_idx = int(d.metadata.get("page", 0))
                            ocr_text = _ocr_pdf_page(file_path, page_idx)
                            if ocr_text:
                                cleaned_text = ocr_text
                                d.metadata["ocr_used"] = True
                            else:
                                d.metadata["ocr_used"] = False
                        else:
                            d.metadata["ocr_used"] = False

                        d.page_content = cleaned_text
                        d.metadata.update(base_metadata)
                    documents.extend(docs)
                    print(f"✅ Đã tải: [{category}] {file}")
                elif file_ext in {".txt", ".md"}:
                    loader = TextLoader(file_path, encoding='utf-8')
                    docs = loader.load()
                    for d in docs:
                        d.page_content = clean_document_content(d.page_content)
                        d.metadata.update(base_metadata)
                    documents.extend(docs)
                    print(f"✅ Đã tải: [{category}] {file}")
                elif file_ext in IMAGE_EXTENSIONS:
                    ocr_text = _ocr_image_file(file_path)
                    if ocr_text:
                        image_doc = Document(
                            page_content=ocr_text,
                            metadata={**base_metadata, "ocr_used": True, "source_type": "image"},
                        )
                        documents.append(image_doc)
                        print(f"✅ OCR ảnh: [{category}] {file}")
                    else:
                        print(f"⚠️ Không OCR được ảnh hoặc ảnh không có text: {file}")
            except Exception as e:
                print(f"❌ Lỗi khi tải file {file}: {e}")
    return documents

def split_text(documents):
    """Cắt nhỏ văn bản thành các chunks"""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200,
        length_function=len,
        add_start_index=True,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
    )
    chunks = text_splitter.split_documents(documents)
    
    # Lọc bỏ các chunk rỗng hoặc chỉ chứa khoảng trắng để tránh lỗi IndexError của langchain_chroma
    chunks = [c for c in chunks if c.page_content and c.page_content.strip() and len(c.page_content.strip()) >= 50]
    
    # Ánh xạ thư mục sang tên dễ hiểu
    CATEGORY_MAP = {
        "chuong_trinh_dao_tao": "Chương trình đào tạo",
        "de_cuong_hoc_phan": "Đề cương học phần",
        "hoat_dong_ngoai_khoa": "Hoạt động ngoại khóa",
        "nghien_cuu_va_do_an": "Nghiên cứu và đồ án",
        "quy_che_dao_tao": "Quy chế đào tạo",
        "thong_tin_nganh_cntt": "Thông tin ngành CNTT",
    }
    
    # Tiêm Metadata trực tiếp vào đầu mỗi Chunk
    for c in chunks:
        cat_raw = c.metadata.get("category", "Chung")
        human_cat = CATEGORY_MAP.get(cat_raw, cat_raw)
        source_file = c.metadata.get("source_file", "Không rõ")
        prefix = f"[Chủ đề: {human_cat} | File: {source_file}]\n"
        c.page_content = prefix + c.page_content

    print(f"🔪 Đã cắt thành {len(chunks)} chunks và dán nhãn Metadata.")
    return chunks

def save_to_chroma(chunks):
    """Lưu chunks vào CSDL Chroma"""
    # Xóa CSDL cũ nếu tồn tại để cập nhật mới
    if os.path.exists(CHROMA_PATH):
        import shutil
        shutil.rmtree(CHROMA_PATH)
    else:
        # Đảm bảo có thư mục chứa database
        os.makedirs(os.path.dirname(CHROMA_PATH), exist_ok=True)

    print(f"📦 Đang bắt đầu lưu {len(chunks)} chunks vào ChromaDB...")

    # Sử dụng thư mục tạm của hệ thống (không có tiếng Việt) để ghi index
    import tempfile
    import shutil

    temp_dir = tempfile.mkdtemp()
    try:
        db = Chroma.from_documents(
            chunks,
            embeddings,
            persist_directory=temp_dir
        )
        # Đóng client ChromaDB sạch sẽ để hoàn thành ghi file index HNSW xuống đĩa
        if hasattr(db, "_client") and hasattr(db._client, "close"):
            print("⏳ Đang đóng ChromaDB client để đồng bộ ghi file index HNSW...")
            db._client.close()

        # Copy toàn bộ thư mục tạm về thư mục chroma_db thực tế của dự án
        shutil.copytree(temp_dir, CHROMA_PATH, dirs_exist_ok=True)
        print(f"💾 Đã lưu thành công tất cả {len(chunks)} chunks vào {CHROMA_PATH}.")
    finally:
        # Xóa thư mục tạm
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

def main():
    print("🚀 Bắt đầu quá trình nạp dữ liệu (Ingestion)...")
    docs = load_documents()
    if not docs:
        print("⚠️ Không có tài liệu nào để nạp. Hãy thêm file vào thư mục data/")
        return
    
    chunks = split_text(docs)
    save_to_chroma(chunks)
    print("🎉 Hoàn tất!")

if __name__ == "__main__":
    main()
