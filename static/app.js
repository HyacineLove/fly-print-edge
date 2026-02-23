document.addEventListener('DOMContentLoaded', () => {
    // 状态机
    const state = {
        current: 'scan', // scan, preview, printing
        file: null,
        token: null,
        node_id: null,
        copies: 1,
        color: 'Grayscale',
        duplex: 'None',
        size: 'A4'
    };

    // 元素绑定
    const sections = {
        scan: document.getElementById('scan-section'),
        preview: document.getElementById('preview-section'),
        printing: document.getElementById('printing-section')
    };

    const qrImage = document.getElementById('qr-code');
    const scanStatus = document.getElementById('scan-status');

    // 初始化
    init();

    function init() {
        showSection('scan');
        fetchQRCode();
        setupWebSocket();
    }

    function showSection(name) {
        Object.values(sections).forEach(s => s.style.display = 'none');
        sections[name].style.display = 'flex';
        state.current = name;
    }

    // 获取QR Code
    async function fetchQRCode() {
        try {
            scanStatus.innerText = "正在获取上传链接...";
            const response = await fetch('/api/qr_code');
            const data = await response.json();
            
            if (data.success) {
                qrImage.src = data.qr_url; // 假设后端生成图片URL，或者直接返回base64
                // 如果后端返回的是 data:image/png;base64,... 格式
                state.node_id = data.node_id;
                scanStatus.innerText = "请扫描二维码上传文件";
                
                // Debug URL
                if (data.text_url) {
                    const debugDiv = document.getElementById('debug-url');
                    if (debugDiv) {
                        debugDiv.innerHTML = `<a href="${data.text_url}" target="_blank">🔍 Debug Link</a>`;
                    }
                }
            } else {
                scanStatus.innerText = "获取失败: " + data.message;
            }
        } catch (e) {
            scanStatus.innerText = "网络错误，请重试";
            console.error(e);
        }
    }

    // WebSocket / SSE 连接
    function setupWebSocket() {
        const statusElem = document.getElementById('connection-status');
        
        // 使用 SSE 监听事件
        const eventSource = new EventSource('/api/events');

        eventSource.onopen = () => {
            console.log("SSE Connected");
            if (statusElem) statusElem.innerText = "🟢 服务已连接";
        };

        eventSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        };

        eventSource.onerror = (err) => {
            console.error("SSE Error:", err);
            if (statusElem) statusElem.innerText = "🔴 服务连接断开，正在重连...";
            // 自动重连由浏览器处理
        };
    }

    function handleMessage(msg) {
        console.log("收到消息:", msg);
        if (msg.type === 'preview_file') {
            state.file = msg.data;
            showPreview(msg.data);
        } else if (msg.type === 'job_status') {
            updatePrintStatus(msg.data);
        }
    }

    function showPreview(file) {
        document.getElementById('file-name').innerText = file.file_name;
        document.getElementById('file-size').innerText = (file.file_size / 1024).toFixed(2) + " KB";
        document.getElementById('file-type').innerText = file.file_type;
        
        // 重置设置
        state.copies = 1;
        document.getElementById('copies').value = 1;
        
        showSection('preview');
    }

    window.updateCopies = (delta) => {
        let val = parseInt(document.getElementById('copies').value) + delta;
        if (val < 1) val = 1;
        document.getElementById('copies').value = val;
        state.copies = val;
    };

    window.resetState = () => {
        state.file = null;
        showSection('scan');
        fetchQRCode(); // 刷新Token
    };

    window.submitPrint = async () => {
        if (!state.file) return;

        const payload = {
            task_token: state.file.task_token,
            file_id: state.file.file_id,
            options: {
                copies: parseInt(document.getElementById('copies').value),
                color_mode: document.getElementById('color-mode').value,
                paper_size: document.getElementById('paper-size').value,
                duplex: document.getElementById('duplex').value
            }
        };

        try {
            showSection('printing');
            document.getElementById('printing-title').innerText = "🖨️ 正在提交...";
            
            const res = await fetch('/api/print', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const result = await res.json();
            if (result.success) {
                document.getElementById('printing-title').innerText = "🖨️ 正在打印...";
                // 等待 WebSocket 的 job_status 更新
            } else {
                alert("提交失败: " + result.message);
                showSection('preview');
            }
        } catch (e) {
            alert("提交异常");
            console.error(e);
            showSection('preview');
        }
    };

    function updatePrintStatus(statusData) {
        if (state.current !== 'printing') return;

        const msgElem = document.getElementById('printing-message');
        const titleElem = document.getElementById('printing-title');
        
        if (statusData.status === 'completed') {
            titleElem.innerText = "✅ 打印完成";
            msgElem.innerText = "请取走您的文件，感谢使用！";
            document.querySelector('.progress-fill').style.width = "100%";
            
            setTimeout(() => {
                resetState();
            }, 5000);
        } else if (statusData.status === 'failed') {
            titleElem.innerText = "❌ 打印失败";
            msgElem.innerText = statusData.message || "请联系管理员";
            document.getElementById('return-btn').classList.remove('hidden');
        } else {
            // progress update
            msgElem.innerText = `状态: ${statusData.status}`;
        }
    }
});
