document.addEventListener('DOMContentLoaded', () => {
    // 状态机
    const state = {
        current: 'scan', // scan, preview, printing
        file: null,
        token: null,
        expiresAt: null,
        node_id: null,
        defaultPrinterId: null,
        copies: 1,
        color: 'Grayscale',
        duplex: 'None',
        size: 'A4',
        capabilities: null,
        previewTimer: null,
        previewPageIndex: 0,
        previewPageCount: 1
    };

    // 定时器
    let tokenRefreshTimer = null;
    let expiryCountdownInterval = null;
    let autoReturnTimer = null;          // 自动返回首页定时器
    let autoReturnCountdown = null;      // 自动返回倒计时显示定时器

    // 元素绑定
    const sections = {
        scan: document.getElementById('scan-section'),
        preview: document.getElementById('preview-section'),
        printing: document.getElementById('printing-section')
    };

    const qrImage = document.getElementById('qr-code');
    const qrExpiryElem = document.getElementById('qr-expiry');
    const refreshBtn = document.getElementById('refresh-qr-btn');
    const qrLoadingElem = document.getElementById('qr-loading');

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
        
        // 只在扫码页面保持刷新定时器
        if (name !== 'scan') {
            clearTokenRefreshTimer();
            clearExpiryCountdown();
        }
    }


    // 获取QR Code
    async function fetchQRCode() {
        try {
            // 显示加载遮罩
            if (qrLoadingElem) qrLoadingElem.style.display = 'flex';
                
            if (qrExpiryElem) qrExpiryElem.innerText = "";
            if (refreshBtn) refreshBtn.style.display = "none";
                
            const response = await fetch('/api/qr_code');
            const data = await response.json();
                
            if (response.status === 503 || data.standby) {
                qrImage.src = "";
                state.defaultPrinterId = data.default_printer_id || state.defaultPrinterId;
                
                // 处理禁用状态：不再跳转到 disabled 页面，而是显示错误提示
                if (data.disabled) {
                    const target = data.disabled_target;
                    if (qrExpiryElem) {
                        if (target === 'node') {
                            qrExpiryElem.innerText = "❌ 该设备已暂停服务，当前无法提供打印服务。如需使用，请联系现场工作人员处理。";
                        } else if (target === 'printer') {
                            qrExpiryElem.innerText = "❌ 默认打印机已暂停服务，当前无法提供打印服务。如需使用，请联系现场工作人员处理。";
                        } else {
                            qrExpiryElem.innerText = "❌ 服务暂不可用，请联系现场工作人员处理。";
                        }
                        qrExpiryElem.style.color = "#f44336";
                    }
                    // 显示刷新按钮
                    if (refreshBtn) refreshBtn.style.display = "inline-block";
                    return;
                }
                
                if (qrExpiryElem) {
                    qrExpiryElem.innerText = data.message || "设备处于待机状态";
                }
                return;
            }
                
            // 检查是否是错误响应（刷新时的错误）
            if (!data.success) {
                const errorCode = data.error_code || 'unknown';
                const errorMessage = data.message || '获取二维码失败';
                    
                console.error('获取二维码失败:', errorCode, errorMessage);
                    
                // 清除二维码图片
                qrImage.src = "";
                    
                // 根据错误码显示不同的提示
                if (errorCode === 'node_disabled') {
                    // 节点被禁用
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = "❌ 此节点已被管理员禁用，请联系管理员解除禁用后手动点击刷新按钮";
                        qrExpiryElem.style.color = "#f44336";
                    }
                } else if (errorCode === 'printer_disabled') {
                    // 打印机被禁用
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = "❌ 所选打印机已被管理员禁用，请联系管理员解除禁用后手动点击刷新按钮";
                        qrExpiryElem.style.color = "#f44336";
                    }
                } else if (errorCode === 'printer_not_found') {
                    // 打印机不存在
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = "❌ 打印机不存在，请联系管理员检查配置";
                        qrExpiryElem.style.color = "#f44336";
                    }
                } else if (errorCode === 'printer_not_belong_to_node') {
                    // 打印机不属于该节点
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = "❌ 打印机配置错误，打印机不属于此节点，请联系管理员检查配置";
                        qrExpiryElem.style.color = "#f44336";
                    }
                } else if (errorCode === 'node_not_found') {
                    // 节点不存在
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = "❌ 节点配置错误，节点不存在，请联系管理员检查配置";
                        qrExpiryElem.style.color = "#f44336";
                    }
                } else {
                    // 其他错误
                    if (qrExpiryElem) {
                        qrExpiryElem.innerText = `❌ ${errorMessage}，请稍后重试或联系管理员`;
                        qrExpiryElem.style.color = "#f44336";
                    }
                }
                    
                // 显示刷新按钮
                if (refreshBtn) refreshBtn.style.display = "inline-block";
                    
                // 清除定时器
                clearTokenRefreshTimer();
                clearExpiryCountdown();
                    
                return;
            }
                
            if (data.success) {
                qrImage.src = data.qr_url; // 假设后端生成图片URL，或者直接返回 base64
                // 如果后端返回的是 data:image/png;base64,... 格式
                state.node_id = data.node_id;
                state.token = data.token;
                state.expiresAt = data.expires_at;
                state.defaultPrinterId = data.default_printer_id || state.defaultPrinterId;
                state.capabilities = data.default_printer_capabilities || null;
                if (refreshBtn) refreshBtn.style.display = "inline-block";
                if (qrExpiryElem) qrExpiryElem.style.color = ""; // 重置颜色
                    
                // 启动自动刷新和倒计时
                setupTokenRefresh();
            } else {
                if (qrExpiryElem) {
                    qrExpiryElem.innerText = "获取失败: " + data.message;
                }
            }
        } catch (e) {
            if (qrExpiryElem) {
                qrExpiryElem.innerText = "网络错误，请重试";
            }
            console.error(e);
        } finally {
            // 隐藏加载遮罩
            if (qrLoadingElem) qrLoadingElem.style.display = 'none';
        }
    }
    
    // 设置凭证自动刷新
    function setupTokenRefresh() {
        // 清除旧的定时器
        clearTokenRefreshTimer();
        clearExpiryCountdown();
        
        if (!state.expiresAt) return;
        
        try {
            const expiresAt = new Date(state.expiresAt);
            const now = new Date();
            
            // 提前30秒刷新
            const refreshIn = expiresAt - now - 30000;
            
            console.log(`二维码将在 ${Math.round(refreshIn / 1000)} 秒后自动刷新`);
            
            if (refreshIn > 0) {
                tokenRefreshTimer = setTimeout(() => {
                    if (state.current === 'scan') {
                        console.log('自动刷新二维码');
                        fetchQRCode();
                    }
                }, refreshIn);
            }
            
            // 启动倒计时显示
            startExpiryCountdown();
            
        } catch (e) {
            console.error('设置自动刷新失败:', e);
        }
    }
    
    // 启动过期倒计时显示
    function startExpiryCountdown() {
        if (!qrExpiryElem || !state.expiresAt) return;
        
        function updateCountdown() {
            if (!state.expiresAt) return;
            
            const expiresAt = new Date(state.expiresAt);
            const now = new Date();
            const remaining = Math.max(0, Math.floor((expiresAt - now) / 1000));
            
            if (remaining > 0) {
                const minutes = Math.floor(remaining / 60);
                const seconds = remaining % 60;
                qrExpiryElem.innerText = `二维码有效期：${minutes}分${seconds}秒`;
            } else {
                qrExpiryElem.innerText = "二维码已过期，请刷新";
                qrExpiryElem.style.color = "#f44336";
                clearExpiryCountdown();
            }
        }
        
        updateCountdown();
        expiryCountdownInterval = setInterval(updateCountdown, 1000);
    }
    
    // 清除刷新定时器
    function clearTokenRefreshTimer() {
        if (tokenRefreshTimer) {
            clearTimeout(tokenRefreshTimer);
            tokenRefreshTimer = null;
        }
    }
    
    // 清除倒计时
    function clearExpiryCountdown() {
        if (expiryCountdownInterval) {
            clearInterval(expiryCountdownInterval);
            expiryCountdownInterval = null;
        }
    }
    
    // 手动刷新二维码
    window.refreshQRCode = () => {
        console.log('手动刷新二维码');
        fetchQRCode();
    };

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
        } else if (msg.type === 'cloud_error') {
            const errorData = msg.data || {};
            const errorCode = errorData.code || 'unknown';
            if (errorCode === 'node_deleted') {
                // 节点被管理员删除，在扫码页面显示错误提示
                if (qrExpiryElem) {
                    qrExpiryElem.innerText = "❌ 该设备已被管理员移除，当前无法提供打印服务。请联系现场工作人员处理。";
                    qrExpiryElem.style.color = "#f44336";
                }
                if (qrImage) qrImage.src = "";
                if (refreshBtn) refreshBtn.style.display = "inline-block";
                return;
            }
            // 处理云端错误（submit_print_params 被拒绝）
            if (state.current === 'printing') {
                handlePrintError(errorData);
            }
        } else if (msg.type === 'job_status' || msg.type === 'job_update') {
            // 处理打印任务状态更新（兼容 job_status 和 job_update）
            const jobData = msg.data || {};
            console.log('打印任务状态更新:', jobData);
            updatePrintStatus(jobData);
        }
        // 注：node_state/printer_state 已从云端废弃，不再处理
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
        // 清理预览文件（如果有）
        if (state.file && state.file.file_id) {
            fetch('/api/cleanup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: state.file.file_id })
            }).catch(e => console.error('清理文件失败:', e));
        }
        
        state.file = null;
        clearAutoReturnTimer();  // 清除自动返回定时器
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
            
            // 重置打印页面状态
            const titleElem = document.getElementById('printing-title');
            const msgElem = document.getElementById('printing-message');
            const returnBtn = document.getElementById('return-btn');
            const progressFill = document.querySelector('.progress-fill');
            
            titleElem.innerText = "🖨️ 正在提交...";
            msgElem.innerText = "系统正在处理您的文档，请勿离开...";
            progressFill.style.width = "0%";
            returnBtn.classList.add('hidden');
            clearAutoReturnTimer();
            
            const res = await fetch('/api/print', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const result = await res.json();
            
            if (result.success) {
                // 提交成功，等待云端响应（print_job 或 error）
                titleElem.innerText = "🖨️ 正在打印...";
                msgElem.innerText = "系统正在处理您的文档，请勿离开...";
            } else {
                // 本地检查失败（如打印机禁用）
                const errorCode = result.error_code || 'unknown';
                
                if (errorCode === 'printer_disabled' || errorCode === 'node_disabled') {
                    // 本地发现禁用，显示错误
                    titleElem.innerText = errorCode === 'node_disabled' ? "❌ 节点已被禁用" : "❌ 打印机已被禁用";
                    msgElem.innerText = result.message || "无法提交打印任务";
                    returnBtn.classList.remove('hidden');
                    startAutoReturn(5);
                } else {
                    // 其他错误
                    titleElem.innerText = "❌ 提交失败";
                    msgElem.innerText = result.message || "提交失败，请重试";
                    returnBtn.classList.remove('hidden');
                    startAutoReturn(5);
                }
            }
        } catch (e) {
            console.error("提交打印异常:", e);
            const titleElem = document.getElementById('printing-title');
            const msgElem = document.getElementById('printing-message');
            const returnBtn = document.getElementById('return-btn');
            
            titleElem.innerText = "❌ 网络错误";
            msgElem.innerText = "无法连接到服务器，请检查网络连接";
            returnBtn.classList.remove('hidden');
            startAutoReturn(5);
        }
    };

    function updatePrintStatus(statusData) {
        if (state.current !== 'printing') return;

        const msgElem = document.getElementById('printing-message');
        const titleElem = document.getElementById('printing-title');
        const returnBtn = document.getElementById('return-btn');
        
        if (statusData.status === 'completed') {
            titleElem.innerText = "✅ 打印完成";
            msgElem.innerText = "请取走您的文件，感谢使用！";
            document.querySelector('.progress-fill').style.width = "100%";
            
            // 显示返回按钮并启动5秒自动返回
            returnBtn.classList.remove('hidden');
            startAutoReturn(5);
        } else if (statusData.status === 'failed') {
            titleElem.innerText = "❌ 打印失败";
            msgElem.innerText = statusData.message || "打印过程中发生错误，请联系管理员";
            
            // 显示返回按钮并启动5秒自动返回
            returnBtn.classList.remove('hidden');
            startAutoReturn(5);
        } else {
            titleElem.innerText = "🖨️ 正在打印...";
            msgElem.innerText = "系统正在处理您的文档，请勿离开...";
            document.querySelector('.progress-fill').style.width = "0%";
        }
    }
    
    // 处理打印错误（submit_print_params 被云端拒绝）
    function handlePrintError(errorData) {
        const errorCode = errorData.code || 'unknown';
        const errorMessage = errorData.message || '提交打印任务失败';
        
        console.error('打印任务被拒绝:', errorCode, errorMessage);
        
        const titleElem = document.getElementById('printing-title');
        const msgElem = document.getElementById('printing-message');
        const returnBtn = document.getElementById('return-btn');
        
        // 根据错误码显示不同的提示
        if (errorCode === 'node_disabled') {
            titleElem.innerText = "❌ 节点已被禁用";
            msgElem.innerText = "此节点已被管理员禁用，无法提交打印任务。请联系管理员处理。";
        } else if (errorCode === 'printer_disabled') {
            titleElem.innerText = "❌ 打印机已被禁用";
            msgElem.innerText = "所选打印机已被管理员禁用，无法提交打印任务。请联系管理员处理。";
        } else if (errorCode === 'printer_not_found') {
            titleElem.innerText = "❌ 打印机不存在";
            msgElem.innerText = "所选打印机不存在，请联系管理员检查配置。";
        } else if (errorCode === 'printer_not_belong_to_node') {
            titleElem.innerText = "❌ 打印机配置错误";
            msgElem.innerText = "打印机不属于此节点，请联系管理员检查配置。";
        } else {
            titleElem.innerText = "❌ 提交失败";
            msgElem.innerText = errorMessage || "提交打印任务失败，请稍后重试或联系管理员。";
        }
        
        // 清除进度条
        document.querySelector('.progress-fill').style.width = "0%";
        
        // 显示返回按钮并启动5秒自动返回
        returnBtn.classList.remove('hidden');
        startAutoReturn(3);  // 3秒后自动返回，体验更流畅
    }
    
    // 启动自动返回倒计时
    function startAutoReturn(seconds) {
        clearAutoReturnTimer();  // 先清除旧的定时器
        
        const countdownElem = document.getElementById('printing-countdown');
        if (!countdownElem) return;
        
        let remaining = seconds;
        countdownElem.style.display = 'block';
        countdownElem.innerText = `${remaining} 秒后自动返回首页`;
        
        // 启动倒计时显示
        autoReturnCountdown = setInterval(() => {
            remaining--;
            if (remaining > 0) {
                countdownElem.innerText = `${remaining} 秒后自动返回首页`;
            } else {
                clearAutoReturnTimer();
                resetState();
            }
        }, 1000);
        
        // 启动自动返回定时器
        autoReturnTimer = setTimeout(() => {
            clearAutoReturnTimer();
            resetState();
        }, seconds * 1000);
    }
    
    // 清除自动返回定时器
    function clearAutoReturnTimer() {
        if (autoReturnTimer) {
            clearTimeout(autoReturnTimer);
            autoReturnTimer = null;
        }
        if (autoReturnCountdown) {
            clearInterval(autoReturnCountdown);
            autoReturnCountdown = null;
        }
        const countdownElem = document.getElementById('printing-countdown');
        if (countdownElem) {
            countdownElem.style.display = 'none';
            countdownElem.innerText = '';
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
