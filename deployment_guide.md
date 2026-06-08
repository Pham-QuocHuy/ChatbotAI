# Hướng dẫn Triển khai Chatbot AI lên Render & Tích hợp vào Website

Tài liệu này hướng dẫn chi tiết cách đưa phần **Backend Chatbot** lên **Render.com** (miễn phí) và nhúng **Bong bóng chat (Widget)** vào website đang chạy của bạn.

---

## 1. Chuẩn bị mã nguồn trước khi deploy

Để deploy lên Render thông qua GitHub, bạn cần đẩy dự án này lên một kho lưu trữ (repository) GitHub cá nhân.

### Bước 1: Cho phép Render đọc đúng cổng (Port)
> [!NOTE]
> Chúng tôi đã cập nhật file `backend/app.py` để tự động nhận dạng cổng dịch vụ được Render cấp phát qua biến môi trường `PORT`. Do đó bạn không cần cấu hình cứng cổng `8004` nữa.

### Bước 2: Chuẩn bị Cơ sở dữ liệu Tri thức (ChromaDB)
Vì Render sử dụng **ổ đĩa tạm thời (ephemeral storage)** ở gói miễn phí (mọi file mới sinh ra khi chạy sẽ bị xóa sạch khi server tự động khởi động lại sau 24h hoặc khi deploy mới), phương án tối ưu và miễn phí nhất là:
1. Chạy nạp dữ liệu tài liệu (RAG) dưới máy local của bạn trước bằng lệnh:
   ```bash
   python backend/ingest.py
   ```
2. Lệnh này sẽ tạo thư mục `database/chroma_db/` chứa toàn bộ dữ liệu vector tri thức đã được số hóa.
3. Tiến hành commit và đẩy (push) cả thư mục `database/chroma_db/` này lên GitHub. Khi đó, cơ sở dữ liệu tri thức sẽ được đóng gói sẵn và triển khai như một phần mã nguồn tĩnh, giúp chatbot hoạt động ngay mà không sợ mất dữ liệu.

---

## 2. Các bước triển khai Backend lên Render.com

### Bước 1: Tạo tài khoản và liên kết GitHub
1. Truy cập [Render.com](https://render.com) và đăng ký tài khoản (khuyên dùng Đăng nhập bằng GitHub).
2. Nhấp vào nút **New +** ở góc phải màn hình và chọn **Web Service**.
3. Kết nối với tài khoản GitHub của bạn và chọn Repository chứa dự án Chatbot này.

### Bước 2: Cấu hình Web Service trên Render
Tại trang cấu hình dịch vụ, thiết lập các thông số như sau:

| Trường cấu hình | Giá trị thiết lập |
| :--- | :--- |
| **Name** | `ai-mentor-chatbot` (hoặc tên tùy chọn) |
| **Region** | Chọn khu vực gần Việt Nam nhất (ví dụ: `Singapore` hoặc `Oregon`) |
| **Branch** | `main` (hoặc nhánh chứa code của bạn) |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python backend/app.py` |
| **Instance Type** | Chọn **Free** (Miễn phí) |

### Bước 3: Cấu hình biến môi trường (Environment Variables)
Cuộn xuống phần **Advanced** -> Nhấp vào **Add Environment Variable** để thêm các khóa bảo mật quan trọng (Tuyệt đối không lưu các khóa này trực tiếp trong code):

1. **`GOOGLE_API_KEY`**: Dán khóa API Gemini của bạn vào đây.
2. **`SMTP_USER`** (Không bắt buộc): Email gửi OTP (ví dụ: `yourname@gmail.com`).
3. **`SMTP_PASSWORD`** (Không bắt buộc): Mật khẩu ứng dụng 16 ký tự của Gmail.
4. **`SECRET_KEY`** (Không bắt buộc): Khóa bí mật mã hóa JWT Token (nếu muốn thay đổi giá trị mặc định).

Nhấp vào **Create Web Service** và chờ từ 3-5 phút để Render tự động build và chạy ứng dụng. Khi hoàn thành, Render sẽ cung cấp cho bạn một đường dẫn dạng:
`https://ai-mentor-chatbot.onrender.com`

---

## 3. Tích hợp Bong bóng Chat vào Website của bạn

Sau khi Backend trên Render đã chạy thành công (trạng thái là **Live**):

### Bước 1: Nhúng mã script vào website chính
Mở mã nguồn website đang chạy của bạn (WordPress, Laravel, HTML tĩnh...), chèn đoạn mã dưới đây vào cuối trang, ngay trước thẻ đóng `</body>`:

```html
<!-- Nhúng Chatbot AI Mentor -->
<script src="https://ai-mentor-chatbot.onrender.com/widget.js" async></script>
```
*(Hãy thay thế `https://ai-mentor-chatbot.onrender.com` bằng URL thực tế mà Render cấp cho bạn).*

### Bước 2: Kiểm tra hoạt động
1. Tải lại website chính của bạn. Bạn sẽ thấy một bong bóng chat hình tròn màu xanh hiện lên ở góc dưới cùng bên phải.
2. Click vào bong bóng chat, cửa sổ chatbot sẽ hiện lên.
3. Hãy thử gõ một câu hỏi bất kỳ (ví dụ: *"Học phí ngành CNTT thế nào?"*) để kiểm tra xem hệ thống có phản hồi bình thường không.

---

## 4. Lưu ý quan trọng khi dùng gói Render Free
* **Chế độ ngủ đông (Cold Start):** Nếu không có ai truy cập chatbot trong vòng 15 phút, Render sẽ tạm thời đưa server về trạng thái ngủ. Lần truy cập tiếp theo (khi click mở bong bóng chat) sẽ mất khoảng 30-50 giây để khởi động lại server.
* **Lịch sử chat SQLite:** File database lưu lịch sử trò chuyện `chat_history.db` sẽ bị reset mỗi lần Render restart (ở bản Free). Để lưu lịch sử vĩnh viễn, bạn có thể cấu hình Render liên kết với database **PostgreSQL** ngoài hoặc nâng cấp lên gói có **Persistent Disk** của Render.
