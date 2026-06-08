(function() {
    // 1. URL trỏ đến Server chạy Chatbot (mặc định lấy theo host file widget.js được load)
    const scriptTag = document.currentScript;
    const chatbotUrl = scriptTag ? new URL(scriptTag.src).origin : window.location.origin;

    // 2. Chèn CSS của widget trực tiếp vào thẻ HEAD của web chính
    const style = document.createElement('style');
    style.innerHTML = `
        /* Bong bóng chat nổi */
        .ai-chatbot-widget-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: linear-gradient(135deg, #3a7bd5, #00d2ff);
            color: #fff;
            box-shadow: 0 4px 16px rgba(0, 210, 255, 0.4);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        .ai-chatbot-widget-btn:hover {
            transform: scale(1.08) translateY(-2px);
            box-shadow: 0 6px 24px rgba(0, 210, 255, 0.6);
        }
        .ai-chatbot-widget-btn i {
            font-size: 24px;
            transition: transform 0.3s ease;
        }

        /* Khung Iframe chứa Chatbot */
        .ai-chatbot-iframe-container {
            position: fixed;
            bottom: 90px;
            right: 20px;
            width: 380px;
            height: 600px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.1);
            overflow: hidden;
            z-index: 999999;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            transform: translateY(30px) scale(0.9);
            opacity: 0;
            pointer-events: none;
            transform-origin: bottom right;
        }
        .ai-chatbot-iframe-container.active {
            transform: translateY(0) scale(1);
            opacity: 1;
            pointer-events: auto;
        }
        .ai-chatbot-iframe-container iframe {
            width: 100%;
            height: 100%;
            border: none;
            background: #0f172a;
        }

        /* Responsive cho Mobile */
        @media (max-width: 768px) {
            .ai-chatbot-iframe-container {
                bottom: 0;
                right: 0;
                width: 100% !important;
                height: 100% !important;
                border-radius: 0;
                transform: translateY(100%);
            }
            .ai-chatbot-iframe-container.active {
                transform: translateY(0);
            }
            .ai-chatbot-widget-btn.active {
                bottom: calc(100% - 50px);
                right: 15px;
                width: 36px;
                height: 36px;
                background: #ef4444;
                box-shadow: none;
            }
        }
    `;
    document.head.appendChild(style);

    // 3. Tạo cấu trúc HTML
    const iframeContainer = document.createElement('div');
    iframeContainer.className = 'ai-chatbot-iframe-container';
    
    const iframe = document.createElement('iframe');
    iframeContainer.appendChild(iframe);
    document.body.appendChild(iframeContainer);

    const widgetBtn = document.createElement('div');
    widgetBtn.className = 'ai-chatbot-widget-btn';
    widgetBtn.innerHTML = '<i class="fas fa-comments"></i>';
    document.body.appendChild(widgetBtn);

    // Tự động tải FontAwesome nếu web chính chưa có
    if (!document.querySelector('link[href*="font-awesome"]')) {
        const fa = document.createElement('link');
        fa.rel = 'stylesheet';
        fa.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css';
        document.head.appendChild(fa);
    }

    // 4. Sự kiện đóng/mở chat
    let isLoaded = false;
    widgetBtn.addEventListener('click', function() {
        const isActive = iframeContainer.classList.contains('active');
        if (!isActive) {
            if (!isLoaded) {
                iframe.src = `${chatbotUrl}/?embed=true`;
                isLoaded = true;
            }
            iframeContainer.classList.add('active');
            widgetBtn.classList.add('active');
            widgetBtn.innerHTML = '<i class="fas fa-times"></i>';
        } else {
            iframeContainer.classList.remove('active');
            widgetBtn.classList.remove('active');
            widgetBtn.innerHTML = '<i class="fas fa-comments"></i>';
        }
    });
})();
