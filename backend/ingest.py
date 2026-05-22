import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Xác định đường dẫn gốc dự án dựa vào vị trí file backend/ingest.py
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# Nạp file .env nằm ở thư mục gốc dự án
env_path = os.path.join(PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=env_path, override=True)

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

def load_documents():
    """Tải tất cả các file PDF, TXT, MD trong thư mục data/"""
    if not os.path.exists(DATA_DIR):
        print(f"⚠️ Thư mục {DATA_DIR} không tồn tại. Đang tạo...")
        os.makedirs(DATA_DIR)
        return []

    documents = []
    for root, _, files in os.walk(DATA_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                # Lấy tên thư mục chứa file để làm phân loại (category)
                folder_name = os.path.basename(root)
                category = folder_name if folder_name != "data" else "Chung"

                if file.endswith('.pdf'):
                    loader = PyPDFLoader(file_path)
                    docs = loader.load()
                    # Cập nhật metadata
                    for d in docs:
                        d.metadata['source_file'] = file
                        d.metadata['category'] = category
                    documents.extend(docs)
                    print(f"✅ Đã tải: [{category}] {file}")
                elif file.endswith('.txt') or file.endswith('.md'):
                    loader = TextLoader(file_path, encoding='utf-8')
                    docs = loader.load()
                    for d in docs:
                        d.metadata['source_file'] = file
                        d.metadata['category'] = category
                    documents.extend(docs)
                    print(f"✅ Đã tải: [{category}] {file}")
            except Exception as e:
                print(f"❌ Lỗi khi tải file {file}: {e}")
    return documents

def split_text(documents):
    """Cắt nhỏ văn bản thành các chunks"""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        add_start_index=True,
    )
    chunks = text_splitter.split_documents(documents)
    # Lọc bỏ các chunk rỗng hoặc chỉ chứa khoảng trắng để tránh lỗi IndexError của langchain_chroma
    chunks = [c for c in chunks if c.page_content and c.page_content.strip()]
    print(f"🔪 Đã cắt thành {len(chunks)} chunks.")
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

    # Lưu tất cả chunks cùng một lúc (vì chạy cục bộ không lo bị giới hạn API)
    print(f"📦 Đang bắt đầu lưu {len(chunks)} chunks vào ChromaDB...")
    db = Chroma.from_documents(
        chunks,
        embeddings,
        persist_directory=CHROMA_PATH
    )
    print(f"💾 Đã lưu thành công tất cả {len(chunks)} chunks vào {CHROMA_PATH}.")

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
