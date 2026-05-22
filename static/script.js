document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatMessages = document.getElementById('chat-messages');
    const typingIndicator = document.getElementById('typing-indicator');
    const clearChatBtn = document.getElementById('clear-chat');
    const uploadImageBtn = document.getElementById('upload-image-btn');
    const imageInput = document.getElementById('image-input');
    const imagePreviewContainer = document.getElementById('image-preview-container');
    const imagePreview = document.getElementById('image-preview');
    const imageNameSpan = document.getElementById('image-name');
    const removeImageBtn = document.getElementById('remove-image');

    // Retrieve or generate a persistent session ID
    let sessionId = localStorage.getItem('chat_session_id');
    if (!sessionId) {
        sessionId = Math.random().toString(36).substring(7);
        localStorage.setItem('chat_session_id', sessionId);
    }

    // Track selected image file
    let selectedImageFile = null;

    // Configure marked options
    marked.setOptions({
        breaks: true,
        gfm: true
    });

    // ---- Message Rendering ----
    const addMessage = (text, sender, imageUrl = null) => {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender);

        const avatar = document.createElement('div');
        avatar.classList.add('avatar');
        avatar.innerHTML = sender === 'bot'
            ? '<i class="fas fa-robot"></i>'
            : '<i class="fas fa-user"></i>';

        const content = document.createElement('div');
        content.classList.add('content');

        // Nếu có ảnh kèm (tin nhắn user)
        if (imageUrl) {
            const imgEl = document.createElement('img');
            imgEl.src = imageUrl;
            imgEl.classList.add('message-image');
            content.appendChild(imgEl);
        }

        // Nội dung text
        if (text) {
            if (sender === 'bot') {
                const textDiv = document.createElement('div');
                textDiv.innerHTML = marked.parse(text);
                content.appendChild(textDiv);
                // Tô màu cú pháp code bằng PrismJS
                setTimeout(() => {
                    Prism.highlightAllUnder(content);
                }, 50);
            } else {
                if (text) {
                    const textDiv = document.createElement('div');
                    textDiv.textContent = text;
                    content.appendChild(textDiv);
                }
            }
        }

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(content);
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    // ---- Load Chat History from SQLite ----
    const loadChatHistory = async () => {
        try {
            const response = await fetch(`/history/${sessionId}`);
            if (response.ok) {
                const data = await response.json();
                if (data.messages && data.messages.length > 0) {
                    // Xóa tin nhắn mặc định nếu có lịch sử
                    chatMessages.innerHTML = '';
                    data.messages.forEach(msg => {
                        let contentText = msg.content;
                        let isUser = msg.role === 'user';
                        
                        // Xử lý hiển thị thông báo ảnh nếu là ảnh cũ
                        if (isUser && contentText.startsWith('[Người dùng gửi kèm một ảnh]')) {
                            const lines = contentText.split('\n');
                            const promptLine = lines.find(l => l.startsWith('Câu hỏi: '));
                            contentText = promptLine ? promptLine.substring(9) : 'Gửi kèm một ảnh';
                        }
                        addMessage(contentText, isUser ? 'user' : 'bot');
                    });
                }
            }
        } catch (error) {
            console.error('Lỗi khi tải lịch sử chat:', error);
        }
    };

    // Khởi chạy tải lịch sử khi mở trang
    loadChatHistory();

    // ---- Image Selection ----
    uploadImageBtn.addEventListener('click', () => {
        imageInput.click();
    });

    imageInput.addEventListener('change', () => {
        const file = imageInput.files[0];
        if (!file) return;

        const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'];
        if (!allowedTypes.includes(file.type)) {
            alert('❌ Chỉ hỗ trợ file ảnh: JPG, PNG, GIF, WEBP, BMP');
            imageInput.value = '';
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            alert('❌ File ảnh quá lớn! Vui lòng chọn ảnh nhỏ hơn 10MB.');
            imageInput.value = '';
            return;
        }

        selectedImageFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            imagePreview.src = e.target.result;
            imageNameSpan.textContent = file.name;
            imagePreviewContainer.style.display = 'flex';
        };
        reader.readAsDataURL(file);

        // Đổi icon nút upload -> màu xanh để báo hiệu đã chọn
        uploadImageBtn.classList.add('has-image');
    });

    // ---- Remove Image ----
    removeImageBtn.addEventListener('click', () => {
        clearSelectedImage();
    });

    function clearSelectedImage() {
        selectedImageFile = null;
        imageInput.value = '';
        imagePreview.src = '';
        imageNameSpan.textContent = '';
        imagePreviewContainer.style.display = 'none';
        uploadImageBtn.classList.remove('has-image');
    }

    // ---- Form Submit ----
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();

        // Phải có ít nhất text hoặc ảnh
        if (!message && !selectedImageFile) return;

        // Hiển thị tin nhắn user
        const imageObjectUrl = selectedImageFile ? URL.createObjectURL(selectedImageFile) : null;
        addMessage(message, 'user', imageObjectUrl);
        userInput.value = '';

        // Show typing indicator
        typingIndicator.style.display = 'flex';
        chatMessages.scrollTop = chatMessages.scrollHeight;

        try {
            let data;

            if (selectedImageFile) {
                // ---- Gửi ảnh qua /chat-image ----
                const formData = new FormData();
                formData.append('session_id', sessionId);
                formData.append('message', message);
                formData.append('file', selectedImageFile);

                clearSelectedImage();

                const response = await fetch('/chat-image', {
                    method: 'POST',
                    body: formData,
                });

                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || 'Network response was not ok');
                }
                data = await response.json();
            } else {
                // ---- Gửi text thuần qua /chat ----
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message, session_id: sessionId }),
                });

                if (!response.ok) throw new Error('Network response was not ok');
                data = await response.json();
            }

            typingIndicator.style.display = 'none';
            addMessage(data.response, 'bot');

        } catch (error) {
            console.error('Error:', error);
            typingIndicator.style.display = 'none';
            addMessage(`❌ Xin lỗi em, có lỗi xảy ra: ${error.message}. Em vui lòng thử lại sau nhé!`, 'bot');
        }
    });

    // ---- Clear Chat ----
    clearChatBtn.addEventListener('click', async () => {
        if (confirm('Em có chắc chắn muốn xóa toàn bộ cuộc trò chuyện này không?')) {
            try {
                await fetch('/clear-history', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: '', session_id: sessionId }),
                });
            } catch (error) {
                console.error('Lỗi khi xóa lịch sử trên server:', error);
            }
            
            chatMessages.innerHTML = `
                <div class="message bot">
                    <div class="avatar"><i class="fas fa-robot"></i></div>
                    <div class="content">Chào em! Anh đã sẵn sàng hỗ trợ em từ đầu. Em muốn hỏi gì hoặc gửi ảnh nào nào?</div>
                </div>
            `;
            clearSelectedImage();
        }
    });

    // Paste ảnh từ clipboard (Ctrl+V)
    document.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) {
                    selectedImageFile = file;
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                        imagePreview.src = ev.target.result;
                        imageNameSpan.textContent = 'Ảnh từ clipboard';
                        imagePreviewContainer.style.display = 'flex';
                    };
                    reader.readAsDataURL(file);
                    uploadImageBtn.classList.add('has-image');
                }
                break;
            }
        }
    });

    // Focus input on load
    userInput.focus();
});
