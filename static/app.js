document.addEventListener('DOMContentLoaded', () => {
    // 状态机
    const state = {
        current: 'scan', // scan, preview, printing
        file: null,
        token: null,
        node_id: null,
        defaultPrinterId: null,
        nodeEnabled: true,
        defaultPrinterEnabled: true,
        copies: 1,
        color: 'Grayscale',
        duplex: 'None',
        size: 'A4',
        capabilities: null,
        previewTimer: null,
        previewPageIndex: 0,
        previewPageCount: 1
    };

    // 元素绑定
    const sections = {
        scan: document.getElementById('scan-section'),
        preview: document.getElementById('preview-section'),
        printing: document.getElementById('printing-section'),
        disabled: document.getElementById('disabled-section')
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

    function showDisabled(reason) {
        const titleElem = document.getElementById('disabled-title');
        const msgElem = document.getElementById('disabled-message');
        if (reason === 'node') {
            titleElem.innerText = "🚫 节点已禁用";
            msgElem.innerText = "该设备已暂停服务，当前无法提供打印服务。如需使用，请联系现场工作人员处理。";
        } else if (reason === 'printer') {
            titleElem.innerText = "🚫 默认打印机已禁用";
            msgElem.innerText = "默认打印机已暂停服务，当前无法提供打印服务。如需使用，请联系现场工作人员处理。";
        } else {
            titleElem.innerText = "🚫 服务暂不可用";
            msgElem.innerText = "该设备当前已暂停服务。如需使用，请联系现场工作人员处理。";
        }
        showSection('disabled');
    }

    // 获取QR Code
    async function fetchQRCode() {
        try {
            scanStatus.innerText = "正在获取上传链接...";
            const response = await fetch('/api/qr_code');
            const data = await response.json();
            const debugDiv = document.getElementById('debug-url');
            if (response.status === 503 || data.standby) {
                qrImage.src = "";
                state.defaultPrinterId = data.default_printer_id || state.defaultPrinterId;
                state.nodeEnabled = data.node_enabled !== false;
                state.defaultPrinterEnabled = data.default_printer_enabled !== false;
                if (data.disabled) {
                    showDisabled(data.disabled_target);
                    return;
                }
                scanStatus.innerText = data.message || "设备处于待机状态";
                if (debugDiv) {
                    debugDiv.innerHTML = "";
                }
                return;
            }
            if (data.success) {
                qrImage.src = data.qr_url; // 假设后端生成图片URL，或者直接返回base64
                // 如果后端返回的是 data:image/png;base64,... 格式
                state.node_id = data.node_id;
                state.defaultPrinterId = data.default_printer_id || state.defaultPrinterId;
                state.nodeEnabled = data.node_enabled !== false;
                state.defaultPrinterEnabled = data.default_printer_enabled !== false;
                state.capabilities = data.default_printer_capabilities || null;
                scanStatus.innerText = "请扫描二维码上传文件";
                
                // Debug URL
                if (data.text_url) {
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
        } else if (msg.type === 'node_state') {
            state.nodeEnabled = msg.data && msg.data.enabled !== false;
            if (!state.nodeEnabled) {
                showDisabled('node');
            } else if (state.defaultPrinterEnabled && state.current === 'disabled') {
                resetState();
            }
        } else if (msg.type === 'printer_state') {
            const payload = msg.data || {};
            if (payload.printer_id && payload.printer_id === state.defaultPrinterId) {
                state.defaultPrinterEnabled = payload.enabled !== false;
                if (!state.defaultPrinterEnabled) {
                    showDisabled('printer');
                } else if (state.nodeEnabled && state.current === 'disabled') {
                    resetState();
                }
            }
        }
    }

    function showPreview(file) {
        const imageElem = document.getElementById('preview-image');
        if (imageElem) imageElem.src = "";
        
        // 重置设置
        state.copies = 1;
        document.getElementById('copies').value = 1;
        state.previewPageIndex = 0;
        state.previewPageCount = 1;
        updatePageIndicator();
        setupOptionPanels();
        requestPreview();
        
        showSection('preview');
    }

    window.updateCopies = (delta) => {
        let val = parseInt(document.getElementById('copies').value) + delta;
        if (val < 1) val = 1;
        document.getElementById('copies').value = val;
        state.copies = val;
    };

    window.changePreviewPage = (delta) => {
        if (state.previewPageCount <= 1) return;
        let nextIndex = state.previewPageIndex + delta;
        if (nextIndex < 0) nextIndex = 0;
        if (nextIndex >= state.previewPageCount) nextIndex = state.previewPageCount - 1;
        if (nextIndex === state.previewPageIndex) return;
        state.previewPageIndex = nextIndex;
        updatePageIndicator();
        requestPreview();
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
                color_mode: state.color,
                paper_size: state.size,
                duplex: state.duplex
            }
        };

        try {
            showSection('printing');
            document.getElementById('printing-title').innerText = "🖨️ 正在提交...";
            document.getElementById('printing-message').innerText = "系统正在处理您的文档，请勿离开...";
            document.querySelector('.progress-fill').style.width = "0%";
            
            const res = await fetch('/api/print', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const result = await res.json();
            if (result.success) {
                document.getElementById('printing-title').innerText = "🖨️ 正在打印...";
                document.getElementById('printing-message').innerText = "系统正在处理您的文档，请勿离开...";
                document.querySelector('.progress-fill').style.width = "0%";
                // 等待 WebSocket 的 job_status 更新
            } else {
                const message = result.message || "提交失败";
                if (message.includes("禁用")) {
                    showDisabled(message.includes("节点") ? 'node' : 'printer');
                    return;
                }
                alert("提交失败: " + message);
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
            }, 2000);
        } else if (statusData.status === 'failed') {
            titleElem.innerText = "❌ 打印失败";
            msgElem.innerText = statusData.message || "请联系管理员";
            document.getElementById('return-btn').classList.remove('hidden');
        } else {
            titleElem.innerText = "🖨️ 正在打印...";
            msgElem.innerText = "系统正在处理您的文档，请勿离开...";
            document.querySelector('.progress-fill').style.width = "0%";
        }
    }

    function setupOptionPanels() {
        const capabilities = state.capabilities || {};
        const colorModels = Array.isArray(capabilities.color_model) ? capabilities.color_model : [];
        const duplexModes = Array.isArray(capabilities.duplex) ? capabilities.duplex : [];
        const supportsColor = colorModels.some(model => String(model).toLowerCase().includes('rgb') || String(model).toLowerCase().includes('color'));

        const colorOptions = [
            { value: 'Grayscale', label: '黑白', disabled: false },
            { value: 'Color', label: '彩色', disabled: !supportsColor }
        ];

        const duplexSupport = {
            none: duplexModes.length === 0 || duplexModes.some(mode => String(mode).toLowerCase().includes('none')),
            long: duplexModes.some(mode => String(mode).toLowerCase().includes('notumble') || String(mode).toLowerCase().includes('long')),
            short: duplexModes.some(mode => String(mode).toLowerCase().includes('tumble') || String(mode).toLowerCase().includes('short'))
        };

        const duplexOptions = [
            { value: 'None', label: '单面', disabled: !duplexSupport.none },
            { value: 'LongEdge', label: '长边翻转', disabled: !duplexSupport.long },
            { value: 'ShortEdge', label: '短边翻转', disabled: !duplexSupport.short }
        ];

        state.color = normalizeSelection(state.color, colorOptions);
        state.duplex = normalizeSelection(state.duplex, duplexOptions);
        state.size = 'A4';

        renderOptions('color-options', colorOptions, state.color, value => {
            state.color = value;
            schedulePreviewRefresh();
        });
        renderOptions('duplex-options', duplexOptions, state.duplex, value => {
            state.duplex = value;
            schedulePreviewRefresh();
        });
    }

    function normalizeSelection(currentValue, options) {
        const current = options.find(option => option.value === currentValue && !option.disabled);
        if (current) {
            return current.value;
        }
        const firstEnabled = options.find(option => !option.disabled);
        return firstEnabled ? firstEnabled.value : currentValue;
    }

    function renderOptions(containerId, options, selectedValue, onSelect) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        options.forEach(option => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'option-button';
            button.innerText = option.label;
            if (option.disabled) {
                button.classList.add('disabled');
                button.disabled = true;
            }
            if (option.value === selectedValue) {
                button.classList.add('active');
            }
            button.addEventListener('click', () => {
                if (option.disabled) return;
                onSelect(option.value);
                renderOptions(containerId, options, option.value, onSelect);
            });
            container.appendChild(button);
        });
    }

    function updatePageIndicator() {
        const indicator = document.getElementById('page-indicator');
        const prevBtn = document.getElementById('preview-prev');
        const nextBtn = document.getElementById('preview-next');
        if (indicator) {
            indicator.innerText = `${state.previewPageIndex + 1}/${state.previewPageCount}`;
        }
        if (prevBtn) {
            prevBtn.disabled = state.previewPageIndex <= 0;
        }
        if (nextBtn) {
            nextBtn.disabled = state.previewPageIndex >= state.previewPageCount - 1;
        }
    }

    function schedulePreviewRefresh() {
        if (state.previewTimer) {
            clearTimeout(state.previewTimer);
        }
        state.previewTimer = setTimeout(() => {
            requestPreview();
        }, 300);
    }

    async function requestPreview() {
        if (!state.file) return;
        const imageElem = document.getElementById('preview-image');
        try {
            const res = await fetch('/api/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: state.file.file_id,
                    file_url: state.file.file_url,
                    file_name: state.file.file_name,
                    file_type: state.file.file_type,
                    options: {
                        color_mode: state.color,
                        paper_size: state.size,
                        duplex: state.duplex,
                        copies: state.copies,
                        page_index: state.previewPageIndex
                    }
                })
            });
            const result = await res.json();
            if (result.success && result.preview_url) {
                if (imageElem) imageElem.src = result.preview_url;
                if (typeof result.page_count === 'number' && result.page_count > 0) {
                    state.previewPageCount = result.page_count;
                } else {
                    state.previewPageCount = 1;
                }
                if (typeof result.page_index === 'number') {
                    state.previewPageIndex = result.page_index;
                }
                updatePageIndicator();
            } else {
                state.previewPageIndex = 0;
                state.previewPageCount = 1;
                updatePageIndicator();
                if (imageElem) imageElem.src = "";
            }
        } catch (e) {
            state.previewPageIndex = 0;
            state.previewPageCount = 1;
            updatePageIndicator();
            if (imageElem) imageElem.src = "";
        }
    }
});
