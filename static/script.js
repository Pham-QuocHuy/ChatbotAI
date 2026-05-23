/* ============================================================
   AI Mentor IT — Main Script
   Features: Auth (Login/Register/Logout), Chat Sessions, Image,
             Stop Generation (AbortController)
============================================================ */

document.addEventListener('DOMContentLoaded', () => {

    // ── DOM References ──────────────────────────────────────────
    const chatForm              = document.getElementById('chat-form');
    const userInput             = document.getElementById('user-input');
    const chatMessages          = document.getElementById('chat-messages');
    const typingIndicator       = document.getElementById('typing-indicator');
    const clearChatBtn          = document.getElementById('clear-chat');
    const uploadImageBtn        = document.getElementById('upload-image-btn');
    const imageInput            = document.getElementById('image-input');
    const imagePreviewContainer = document.getElementById('image-preview-container');
    const imagePreview          = document.getElementById('image-preview');
    const imageNameSpan         = document.getElementById('image-name');
    const removeImageBtn        = document.getElementById('remove-image');
    const newChatBtn            = document.getElementById('new-chat-btn');
    const sessionsList          = document.getElementById('sessions-list');
    const sessionsSection       = document.getElementById('sessions-section');
    const guestHint             = document.getElementById('guest-hint');
    const userMenu              = document.getElementById('user-menu');
    const headerLoginBtn        = document.getElementById('header-login-btn');
    const userAvatarBtn         = document.getElementById('user-avatar-btn');
    const userDropdown          = document.getElementById('user-dropdown');
    const headerUsernameEl      = document.getElementById('header-username');
    const userAvatarInitial     = document.getElementById('user-avatar-initial');
    const dropdownAvatarInitial = document.getElementById('dropdown-avatar-initial');
    const dropdownUsernameEl    = document.getElementById('dropdown-username');
    const dropdownEmailEl       = document.getElementById('dropdown-email');
    const sessionSubtitle       = document.getElementById('session-subtitle');

    // ── State ─────────────────────────────────────────────
    let currentUser           = null;   // { id, username, email }
    let authToken             = null;   // JWT
    let currentSession        = null;   // session_id đang dùng
    let selectedImageFile     = null;
    let currentAbortController = null;  // AbortController cho request đang chạy

    // ── Extra DOM refs cho Stop button ───────────────────────
    const sendBtn  = document.getElementById('send-btn');
    const sendIcon = document.getElementById('send-icon');
    const stopIcon = document.getElementById('stop-icon');

    // ── Marked Config ───────────────────────────────────────────
    marked.setOptions({ breaks: true, gfm: true });

    // ════════════════════════════════════════════════════════════
    // AUTH STORAGE
    // ════════════════════════════════════════════════════════════
    function saveAuthToStorage(token, user) {
        localStorage.setItem('auth_token', token);
        localStorage.setItem('auth_user', JSON.stringify(user));
    }

    function loadAuthFromStorage() {
        const token = localStorage.getItem('auth_token');
        const userStr = localStorage.getItem('auth_user');
        if (token && userStr) {
            try {
                return { token, user: JSON.parse(userStr) };
            } catch { return null; }
        }
        return null;
    }

    function clearAuthStorage() {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user');
        localStorage.removeItem('last_session_id');
    }

    // ════════════════════════════════════════════════════════════
    // AUTH MODAL
    // ════════════════════════════════════════════════════════════
    window.openAuthModal = function(tab = 'login') {
        document.getElementById('auth-overlay').style.display = 'flex';
        switchAuthTab(tab);
        // Clear errors
        document.getElementById('login-error').style.display = 'none';
        document.getElementById('register-error').style.display = 'none';
    };

    window.closeAuthModal = function() {
        document.getElementById('auth-overlay').style.display = 'none';
    };

    window.switchAuthTab = function(tab) {
        const loginForm    = document.getElementById('form-login');
        const registerForm = document.getElementById('form-register');
        const tabLogin     = document.getElementById('tab-login');
        const tabRegister  = document.getElementById('tab-register');

        if (tab === 'login') {
            loginForm.style.display = 'block';
            registerForm.style.display = 'none';
            tabLogin.classList.add('active');
            tabRegister.classList.remove('active');
        } else {
            loginForm.style.display = 'none';
            registerForm.style.display = 'block';
            tabLogin.classList.remove('active');
            tabRegister.classList.add('active');
        }
    };

    // Đóng modal khi click overlay
    document.getElementById('auth-overlay').addEventListener('click', (e) => {
        if (e.target === document.getElementById('auth-overlay')) {
            closeAuthModal();
        }
    });

    // Enter key in auth forms
    document.getElementById('login-password').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleLogin();
    });
    document.getElementById('reg-password').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleRegister();
    });

    // ════════════════════════════════════════════════════════════
    // AUTH ACTIONS
    // ════════════════════════════════════════════════════════════
    window.togglePasswordVisibility = function(inputId, btn) {
        const input = document.getElementById(inputId);
        const icon  = btn.querySelector('i');
        if (input.type === 'password') {
            input.type = 'text';
            icon.classList.replace('fa-eye', 'fa-eye-slash');
        } else {
            input.type = 'password';
            icon.classList.replace('fa-eye-slash', 'fa-eye');
        }
    };

    function showAuthError(containerId, message) {
        const el = document.getElementById(containerId);
        el.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
        el.style.display = 'flex';
    }

    function setButtonLoading(btnId, loading) {
        const btn = document.getElementById(btnId);
        if (loading) {
            btn.disabled = true;
            btn.innerHTML = `<span class="btn-spinner"></span>`;
        } else {
            btn.disabled = false;
            // Restore original based on id
            if (btnId === 'login-btn') {
                btn.innerHTML = `<span class="btn-text">Đăng nhập</span><i class="fas fa-arrow-right"></i>`;
            } else if (btnId === 'send-otp-btn') {
                btn.innerHTML = `<span class="btn-text">Gửi mã xác minh</span><i class="fas fa-paper-plane"></i>`;
            } else {
                btn.innerHTML = `<span class="btn-text">Hoàn tất đăng ký</span><i class="fas fa-rocket"></i>`;
            }
        }
    }

    window.handleLogin = async function() {
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        document.getElementById('login-error').style.display = 'none';

        if (!username || !password) {
            showAuthError('login-error', 'Vui lòng nhập đầy đủ thông tin.');
            return;
        }

        setButtonLoading('login-btn', true);
        try {
            const res = await fetch('/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (!res.ok) {
                showAuthError('login-error', data.detail || 'Đăng nhập thất bại.');
                return;
            }
            await onLoginSuccess(data.access_token, data.user);
            closeAuthModal();
        } catch (err) {
            showAuthError('login-error', 'Lỗi kết nối. Vui lòng thử lại.');
        } finally {
            setButtonLoading('login-btn', false);
        }
    };

    let otpTimerInterval = null;

    // --- Xử lý 6 ô nhập OTP ---
    const otpBoxes = document.querySelectorAll('.otp-box');
    otpBoxes.forEach((box, index) => {
        // Nhập số tự nhảy sang ô tiếp theo
        box.addEventListener('input', (e) => {
            box.value = box.value.replace(/[^0-9]/g, '');
            if (box.value && index < otpBoxes.length - 1) {
                otpBoxes[index + 1].focus();
            }
            if (box.value) box.classList.add('filled');
            else box.classList.remove('filled');
        });

        // Nhấn Backspace tự quay về ô trước
        box.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !box.value && index > 0) {
                otpBoxes[index - 1].focus();
                otpBoxes[index - 1].classList.remove('filled');
            }
        });

        // Hỗ trợ Paste nguyên dãy 6 số
        box.addEventListener('paste', (e) => {
            e.preventDefault();
            const pastedData = (e.clipboardData || window.clipboardData).getData('text').replace(/[^0-9]/g, '').slice(0, 6);
            if (!pastedData) return;
            for (let i = 0; i < pastedData.length; i++) {
                otpBoxes[i].value = pastedData[i];
                otpBoxes[i].classList.add('filled');
                if (i < 5) otpBoxes[i + 1].focus();
                else otpBoxes[i].focus();
            }
        });
    });

    function getOtpValue() {
        return Array.from(otpBoxes).map(b => b.value).join('');
    }

    function startOtpCountdown() {
        clearInterval(otpTimerInterval);
        const timerEl = document.getElementById('otp-timer');
        timerEl.classList.remove('expired');
        let timeLeft = 10 * 60; // 10 phút

        otpTimerInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft <= 0) {
                clearInterval(otpTimerInterval);
                timerEl.textContent = "00:00";
                timerEl.classList.add('expired');
                document.getElementById('send-otp-btn').disabled = false;
                return;
            }
            const m = Math.floor(timeLeft / 60).toString().padStart(2, '0');
            const s = (timeLeft % 60).toString().padStart(2, '0');
            timerEl.textContent = `${m}:${s}`;
        }, 1000);
    }

    window.backToRegStep1 = function() {
        document.getElementById('reg-step-2').style.display = 'none';
        document.getElementById('reg-step-1').style.display = 'block';
    }

    window.handleSendOtp = async function() {
        const username = document.getElementById('reg-username').value.trim();
        const email    = document.getElementById('reg-email').value.trim();
        const password = document.getElementById('reg-password').value;
        const errorEl  = document.getElementById('register-error');
        errorEl.style.display = 'none';

        if (!username || !email || !password) {
            showAuthError('register-error', 'Vui lòng nhập đầy đủ thông tin trước khi gửi mã.');
            return;
        }

        setButtonLoading('send-otp-btn', true);
        try {
            const res = await fetch('/auth/send-otp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            const data = await res.json();
            if (!res.ok) {
                showAuthError('register-error', data.detail || 'Không thể gửi mã xác minh.');
                return;
            }

            // Đổi sang bước 2
            document.getElementById('reg-step-1').style.display = 'none';
            document.getElementById('reg-step-2').style.display = 'block';
            document.getElementById('otp-email-display').textContent = email;
            document.getElementById('otp-error').style.display = 'none';
            
            // Xóa OTP cũ (nếu có)
            otpBoxes.forEach(b => { b.value = ''; b.classList.remove('filled'); });
            otpBoxes[0].focus();

            startOtpCountdown();
        } catch (err) {
            showAuthError('register-error', 'Lỗi kết nối khi gửi mã.');
        } finally {
            setButtonLoading('send-otp-btn', false);
        }
    };

    window.handleRegister = async function() {
        const username = document.getElementById('reg-username').value.trim();
        const email    = document.getElementById('reg-email').value.trim();
        const password = document.getElementById('reg-password').value;
        const otpCode  = getOtpValue();
        const errorEl  = document.getElementById('otp-error');
        errorEl.style.display = 'none';

        if (otpCode.length !== 6) {
            showAuthError('otp-error', 'Vui lòng nhập đủ 6 số xác minh.');
            return;
        }

        setButtonLoading('register-btn', true);
        try {
            const res = await fetch('/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, email, password, otp_code: otpCode })
            });
            const data = await res.json();
            if (!res.ok) {
                showAuthError('otp-error', data.detail || 'Xác minh thất bại.');
                return;
            }
            clearInterval(otpTimerInterval);
            await onLoginSuccess(data.access_token, data.user);
            closeAuthModal();
        } catch (err) {
            showAuthError('otp-error', 'Lỗi kết nối. Vui lòng thử lại.');
        } finally {
            setButtonLoading('register-btn', false);
        }
    };

    window.handleLogout = function() {
        currentUser    = null;
        authToken      = null;
        currentSession = null;
        clearAuthStorage();
        updateUIForGuest();
        // Reset chat
        chatMessages.innerHTML = buildWelcomeMessage();
        sessionSubtitle.textContent = 'Hỗ trợ học tập, đồ án và định hướng nghề nghiệp';
        closeUserDropdown();
    };

    async function onLoginSuccess(token, user) {
        authToken   = token;
        currentUser = user;
        saveAuthToStorage(token, user);
        updateUIForUser(user);
        await loadSessions();
    }

    // ════════════════════════════════════════════════════════════
    // UI STATE HELPERS
    // ════════════════════════════════════════════════════════════
    function updateUIForUser(user) {
        // Sidebar
        sessionsSection.style.display = 'flex';
        guestHint.style.display = 'none';
        // Header
        userMenu.style.display = 'flex';
        headerLoginBtn.style.display = 'none';
        // Fill user info
        const initial = user.username.charAt(0).toUpperCase();
        userAvatarInitial.textContent = initial;
        dropdownAvatarInitial.textContent = initial;
        headerUsernameEl.textContent = user.username;
        dropdownUsernameEl.textContent = user.username;
        dropdownEmailEl.textContent = user.email;
    }

    function updateUIForGuest() {
        sessionsSection.style.display = 'none';
        guestHint.style.display = 'block';
        userMenu.style.display = 'none';
        headerLoginBtn.style.display = 'flex';
        sessionsList.innerHTML = '';
    }

    // ════════════════════════════════════════════════════════════
    // USER DROPDOWN
    // ════════════════════════════════════════════════════════════
    window.toggleUserDropdown = function() {
        const isOpen = userDropdown.style.display !== 'none';
        if (isOpen) {
            closeUserDropdown();
        } else {
            userDropdown.style.display = 'block';
            userAvatarBtn.classList.add('open');
        }
    };

    function closeUserDropdown() {
        userDropdown.style.display = 'none';
        userAvatarBtn.classList.remove('open');
    }

    document.addEventListener('click', (e) => {
        if (!userMenu.contains(e.target)) {
            closeUserDropdown();
        }
    });

    // ════════════════════════════════════════════════════════════
    // SESSION MANAGEMENT
    // ════════════════════════════════════════════════════════════
    async function loadSessions() {
        if (!authToken) return;
        try {
            const res = await fetch('/sessions', { headers: authHeaders() });
            if (!res.ok) {
                if (res.status === 401) { handleLogout(); return; }
                return;
            }
            const data = await res.json();
            renderSessions(data.sessions);

            // Khôi phục session cuối hoặc tạo mới
            const lastSessionId = localStorage.getItem('last_session_id');
            const found = data.sessions.find(s => s.session_id === lastSessionId);
            if (found) {
                await switchSession(found.session_id, found.title);
            } else if (data.sessions.length > 0) {
                const latest = data.sessions[0];
                await switchSession(latest.session_id, latest.title);
            } else {
                // Tạo phiên đầu tiên
                await createNewSession();
            }
        } catch (err) {
            console.error('loadSessions error:', err);
        }
    }

    function renderSessions(sessions) {
        sessionsList.innerHTML = '';
        sessions.forEach(s => {
            const item = buildSessionItem(s);
            sessionsList.appendChild(item);
        });
    }

    function buildSessionItem(session) {
        const div = document.createElement('div');
        div.classList.add('session-item');
        div.dataset.sessionId = session.session_id;
        if (session.session_id === currentSession) div.classList.add('active');

        div.innerHTML = `
            <i class="fas fa-comment-dots session-icon"></i>
            <span class="session-title" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</span>
            <button class="session-delete" title="Xóa phiên" onclick="deleteSessionHandler(event, '${session.session_id}')">
                <i class="fas fa-trash-alt"></i>
            </button>
        `;

        div.addEventListener('click', (e) => {
            if (e.target.closest('.session-delete')) return;
            switchSession(session.session_id, session.title);
        });

        return div;
    }

    async function switchSession(sessionId, title) {
        currentSession = sessionId;
        localStorage.setItem('last_session_id', sessionId);
        sessionSubtitle.textContent = title;

        // Update active UI
        document.querySelectorAll('.session-item').forEach(el => {
            el.classList.toggle('active', el.dataset.sessionId === sessionId);
        });

        // Load history
        await loadChatHistory(sessionId);
    }

    async function createNewSession() {
        if (!authToken) return;
        try {
            const res = await fetch('/sessions', {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: 'Cuộc trò chuyện mới' })
            });
            if (!res.ok) return;
            const session = await res.json();

            // Thêm vào đầu danh sách
            const item = buildSessionItem(session);
            sessionsList.prepend(item);

            await switchSession(session.session_id, session.title);

            // Reset chat UI
            chatMessages.innerHTML = buildWelcomeMessage();
        } catch (err) {
            console.error('createNewSession error:', err);
        }
    }

    window.deleteSessionHandler = async function(e, sessionId) {
        e.stopPropagation();
        if (!confirm('Bạn có chắc muốn xóa phiên chat này không?')) return;
        try {
            const res = await fetch(`/sessions/${sessionId}`, {
                method: 'DELETE',
                headers: authHeaders()
            });
            if (!res.ok) return;

            // Remove from DOM
            const item = sessionsList.querySelector(`[data-session-id="${sessionId}"]`);
            if (item) item.remove();

            // Nếu đang xem phiên vừa xóa → tạo phiên mới
            if (currentSession === sessionId) {
                const remaining = sessionsList.querySelector('.session-item');
                if (remaining) {
                    const sid = remaining.dataset.sessionId;
                    const title = remaining.querySelector('.session-title').textContent;
                    await switchSession(sid, title);
                } else {
                    await createNewSession();
                }
            }
        } catch (err) {
            console.error('deleteSession error:', err);
        }
    };

    // Cập nhật tiêu đề phiên trong sidebar sau khi có tin nhắn đầu
    function updateSessionTitleInUI(sessionId, newTitle) {
        const item = sessionsList.querySelector(`[data-session-id="${sessionId}"]`);
        if (item) {
            const titleEl = item.querySelector('.session-title');
            if (titleEl) {
                titleEl.textContent = newTitle;
                titleEl.title = newTitle;
            }
        }
        if (sessionId === currentSession) {
            sessionSubtitle.textContent = newTitle;
        }
    }

    newChatBtn.addEventListener('click', async () => {
        if (!authToken) {
            // Guest: chỉ xóa giao diện, không tạo session
            chatMessages.innerHTML = buildWelcomeMessage();
            currentSession = null;
        } else {
            await createNewSession();
        }
    });

    // ════════════════════════════════════════════════════════════
    // LOAD CHAT HISTORY
    // ════════════════════════════════════════════════════════════
    async function loadChatHistory(sessionId) {
        if (!authToken || !sessionId) return;
        try {
            const res = await fetch(`/history/${sessionId}`, { headers: authHeaders() });
            if (!res.ok) return;
            const data = await res.json();

            if (data.messages && data.messages.length > 0) {
                chatMessages.innerHTML = '';
                data.messages.forEach(msg => {
                    let content = msg.content;
                    if (msg.role === 'user' && content.startsWith('[Người dùng gửi kèm một ảnh]')) {
                        const lines = content.split('\n');
                        const promptLine = lines.find(l => l.startsWith('Câu hỏi: '));
                        content = promptLine ? promptLine.substring(9) : '📷 Đã gửi một ảnh';
                    }
                    addMessage(content, msg.role === 'user' ? 'user' : 'bot');
                });
            } else {
                chatMessages.innerHTML = buildWelcomeMessage();
            }
        } catch (err) {
            console.error('loadChatHistory error:', err);
        }
    }

    // ════════════════════════════════════════════════════════════
    // MESSAGE RENDERING
    // ════════════════════════════════════════════════════════════
    function buildWelcomeMessage() {
        return `
            <div class="message bot">
                <div class="avatar"><i class="fas fa-robot"></i></div>
                <div class="content">
                    Chào em! Anh là AI Mentor IT của em đây. Em đang gặp khó khăn gì trong việc học tập hay cần định hướng gì không? Đừng ngần ngại chia sẻ nhé! 🚀
                </div>
            </div>`;
    }

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

        if (imageUrl) {
            const imgEl = document.createElement('img');
            imgEl.src = imageUrl;
            imgEl.classList.add('message-image');
            content.appendChild(imgEl);
        }

        if (text) {
            if (sender === 'bot') {
                const textDiv = document.createElement('div');
                textDiv.innerHTML = marked.parse(text);
                content.appendChild(textDiv);
                setTimeout(() => Prism.highlightAllUnder(content), 50);
            } else {
                const textDiv = document.createElement('div');
                textDiv.textContent = text;
                content.appendChild(textDiv);
            }
        }

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(content);
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    };

    // ════════════════════════════════════════════════════════════
    // AUTH HEADERS HELPER
    // ════════════════════════════════════════════════════════════
    function authHeaders() {
        const h = {};
        if (authToken) h['Authorization'] = `Bearer ${authToken}`;
        return h;
    }

    // ════════════════════════════════════════════════════════════
    // IMAGE HANDLING
    // ════════════════════════════════════════════════════════════
    uploadImageBtn.addEventListener('click', () => imageInput.click());

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
        uploadImageBtn.classList.add('has-image');
    });

    removeImageBtn.addEventListener('click', clearSelectedImage);

    function clearSelectedImage() {
        selectedImageFile = null;
        imageInput.value  = '';
        imagePreview.src  = '';
        imageNameSpan.textContent = '';
        imagePreviewContainer.style.display = 'none';
        uploadImageBtn.classList.remove('has-image');
    }

    // Paste ảnh từ clipboard
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

    // ════════════════════════════════════════════════════════════
    // LOADING STATE (tùy chỉnh nút Send ⇔ Stop)
    // ════════════════════════════════════════════════════════════
    function setLoadingState(isLoading) {
        // Input
        userInput.disabled      = isLoading;
        uploadImageBtn.disabled = isLoading;

        // Icon Send / Stop
        sendIcon.style.display  = isLoading ? 'none'  : 'inline-block';
        stopIcon.style.display  = isLoading ? 'inline-block' : 'none';

        // Class đổi màu nút
        sendBtn.classList.toggle('stop-mode', isLoading);
        sendBtn.title = isLoading ? 'Dừng lại' : 'Gửi tin nhắn';

        // Typing indicator
        typingIndicator.style.display = isLoading ? 'flex' : 'none';
        if (isLoading) chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // ════════════════════════════════════════════════════════════
    // CHAT SUBMIT
    // ════════════════════════════════════════════════════════════
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // ══ Nếu đang ở chế độ Stop → hủy request ══
        if (sendBtn.classList.contains('stop-mode')) {
            if (currentAbortController) {
                currentAbortController.abort();
                currentAbortController = null;
            }
            return;
        }

        const message = userInput.value.trim();
        if (!message && !selectedImageFile) return;

        // Đảm bảo có session_id
        let sessionId = currentSession;
        if (!sessionId) {
            if (authToken) {
                await createNewSession();
                sessionId = currentSession;
            } else {
                sessionId = 'guest_' + Math.random().toString(36).substring(7);
                currentSession = sessionId;
            }
        }

        const imageObjectUrl = selectedImageFile ? URL.createObjectURL(selectedImageFile) : null;
        addMessage(message, 'user', imageObjectUrl);
        userInput.value = '';

        // ══ Bắt đầu loading state ══
        currentAbortController = new AbortController();
        setLoadingState(true);

        try {
            let data;

            if (selectedImageFile) {
                const formData = new FormData();
                formData.append('session_id', sessionId);
                formData.append('message', message);
                formData.append('file', selectedImageFile);
                clearSelectedImage();

                const res = await fetch('/chat-image', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: formData,
                    signal: currentAbortController.signal
                });
                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || 'Lỗi server');
                }
                data = await res.json();
            } else {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message, session_id: sessionId }),
                    signal: currentAbortController.signal
                });
                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || 'Lỗi server');
                }
                data = await res.json();
            }

            // ══ Hoàn thành ══
            setLoadingState(false);
            currentAbortController = null;
            addMessage(data.response, 'bot');
            userInput.focus();

            // Refresh session title
            if (authToken && message) {
                const reloadRes = await fetch('/sessions', { headers: authHeaders() });
                if (reloadRes.ok) {
                    const reloadData = await reloadRes.json();
                    const updatedSession = reloadData.sessions.find(s => s.session_id === sessionId);
                    if (updatedSession) updateSessionTitleInUI(sessionId, updatedSession.title);
                    renderSessions(reloadData.sessions);
                    document.querySelectorAll('.session-item').forEach(el => {
                        el.classList.toggle('active', el.dataset.sessionId === currentSession);
                    });
                }
            }

        } catch (err) {
            setLoadingState(false);
            currentAbortController = null;

            // AbortError = người dùng tự dừng → không hiện lỗi đỏ
            if (err.name === 'AbortError') {
                addMessage('⏸️ Đã dừng. Bạn có thể gõ câu hỏi tiếp theo!', 'bot');
            } else {
                console.error('Chat error:', err);
                addMessage(`❌ Xin lỗi, có lỗi xảy ra: ${err.message}. Vui lòng thử lại sau!`, 'bot');
            }
            userInput.focus();
        }
    });


    // ════════════════════════════════════════════════════════════
    // CLEAR CHAT (Xóa nội dung phiên hiện tại)
    // ════════════════════════════════════════════════════════════
    clearChatBtn.addEventListener('click', async () => {
        if (!confirm('Bạn có chắc muốn xóa toàn bộ nội dung cuộc trò chuyện này không?')) return;

        if (authToken && currentSession) {
            try {
                await fetch('/clear-history', {
                    method: 'POST',
                    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: '', session_id: currentSession })
                });
            } catch (err) {
                console.error('clear-history error:', err);
            }
        }

        chatMessages.innerHTML = buildWelcomeMessage();
        clearSelectedImage();
    });

    // ════════════════════════════════════════════════════════════
    // UTILITY
    // ════════════════════════════════════════════════════════════
    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ════════════════════════════════════════════════════════════
    // INIT — Khởi chạy khi tải trang
    // ════════════════════════════════════════════════════════════
    async function init() {
        const saved = loadAuthFromStorage();
        if (saved) {
            // Xác thực token còn hạn không
            try {
                const res = await fetch('/auth/me', {
                    headers: { 'Authorization': `Bearer ${saved.token}` }
                });
                if (res.ok) {
                    const user = await res.json();
                    authToken   = saved.token;
                    currentUser = user;
                    updateUIForUser(user);
                    await loadSessions();
                } else {
                    // Token hết hạn
                    clearAuthStorage();
                    updateUIForGuest();
                }
            } catch {
                clearAuthStorage();
                updateUIForGuest();
            }
        } else {
            updateUIForGuest();
        }

        userInput.focus();
    }

    init();
});
