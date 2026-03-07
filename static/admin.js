document.addEventListener('DOMContentLoaded', () => {
    const discoveredList = document.getElementById('discovered-list');
    const managedList = document.getElementById('managed-list');
    const statusElem = document.getElementById('admin-status');
    const nodeStatusElem = document.getElementById('node-status');
    const refreshDiscoveredBtn = document.getElementById('refresh-discovered');
    const refreshManagedBtn = document.getElementById('refresh-managed');
    const reregisterNodeBtn = document.getElementById('reregister-node-btn');
    const showPrinterReregisterBtn = document.getElementById('show-printer-reregister-btn');

    const state = {
        discovered: [],
        managed: [],
        defaultId: null,
        nodeEnabled: true,
        cloudRegistered: false,
        cloudConnected: false,
        cloudNodeId: null,
        printerErrors: {}  // 记录每个打印机的错误状态，用于判断是否显示重新注册按钮
    };

    const setStatus = (text) => {
        statusElem.textContent = text || '';
    };

    const renderDiscovered = () => {
        if (!state.discovered.length) {
            discoveredList.innerHTML = '<div class="empty">暂无可添加打印机</div>';
            return;
        }
        discoveredList.innerHTML = state.discovered.map((printer, index) => {
            const title = printer.name || '未命名打印机';
            const subtitle = `${printer.type || ''} ${printer.make_model || ''}`.trim() || '未知型号';
            const meta = printer.location || printer.status || '未知状态';
            return `
                <div class="list-item" data-index="${index}">
                    <div>
                        <div class="item-title">${title}</div>
                        <div class="item-subtitle">${subtitle}</div>
                        <div class="item-meta">${meta}</div>
                    </div>
                    <div class="item-actions">
                        <button class="btn btn-primary" data-action="add">添加</button>
                    </div>
                </div>
            `;
        }).join('');
    };

    const renderManaged = () => {
        if (!state.managed.length) {
            managedList.innerHTML = '<div class="empty">暂无管理中的打印机</div>';
            return;
        }
        managedList.innerHTML = state.managed.map((printer) => {
            const title = printer.name || '未命名打印机';
            const subtitle = `${printer.type || ''} ${printer.make_model || ''}`.trim() || '未知型号';
            const meta = printer.location || printer.added_time || '已添加';
            const isDefault = printer.id === state.defaultId;
            // 只有当节点已注册且该打印机有错误时才显示重新注册按钮
            const hasError = state.printerErrors[printer.id];
            const canReregister = state.cloudRegistered && state.cloudConnected && hasError;
            const reregisterBtn = canReregister ? '<button class="btn btn-outline" data-action="reregister">重新注册</button>' : '';
            return `
                <div class="list-item" data-id="${printer.id}">
                    <div>
                        <div class="item-title">${title} ${isDefault ? '<span class="badge">默认</span>' : ''}</div>
                        <div class="item-subtitle">${subtitle}</div>
                        <div class="item-meta">${meta}</div>
                    </div>
                    <div class="item-actions">
                        <button class="btn btn-outline" data-action="default">设为默认</button>
                        <button class="btn btn-danger" data-action="delete">删除</button>
                        ${reregisterBtn}
                    </div>
                </div>
            `;
        }).join('');
    };

    const renderNodeStatus = () => {
        if (!nodeStatusElem) {
            return;
        }
        const registered = state.cloudRegistered;
        const connected = state.cloudConnected;
        let text = '';
        if (!registered) {
            text = '节点未注册';
        } else if (!connected) {
            text = '节点已注册，未连接云端';
        } else {
            text = '节点已注册，连接正常';
        }
        const badgeClass = connected ? 'badge badge-success' : 'badge badge-danger';
        nodeStatusElem.innerHTML = `<span>节点状态</span><span class="${badgeClass}">${text}</span>`;
    };

    const updateNodeActions = () => {
        if (!reregisterNodeBtn) {
            return;
        }
        // 节点未注册或未连接时允许手动重新注册
        if (!state.cloudRegistered || !state.cloudConnected) {
            reregisterNodeBtn.style.display = 'inline-block';
        } else {
            reregisterNodeBtn.style.display = 'none';
        }
    };

    const loadDiscovered = async () => {
        setStatus('正在刷新发现列表...');
        const response = await fetch('/api/admin/printers/discovered');
        const data = await response.json();
        if (data.success) {
            state.discovered = data.items || [];
            renderDiscovered();
            setStatus('');
        } else {
            setStatus(data.message || '刷新失败');
        }
    };

    const loadManaged = async () => {
        setStatus('正在刷新管理列表...');
        const response = await fetch('/api/admin/printers/managed');
        const data = await response.json();
        if (data.success) {
            state.managed = data.items || [];
            state.defaultId = data.default_printer_id || null;
            state.nodeEnabled = data.node_enabled !== false;
            renderManaged();
            renderNodeStatus();
            updateNodeActions();
            setStatus('');
        } else {
            setStatus(data.message || '刷新失败');
        }
    };

    const loadCloudStatus = async () => {
        try {
            const response = await fetch('/api/admin/cloud/status');
            const data = await response.json();
            if (data.success) {
                state.cloudRegistered = !!(data.enabled && data.registered);
                state.cloudConnected = !!data.connected;
                state.cloudNodeId = data.node_id || null;
            } else {
                state.cloudRegistered = false;
                state.cloudConnected = false;
                state.cloudNodeId = null;
            }
        } catch (error) {
            state.cloudRegistered = false;
            state.cloudConnected = false;
            state.cloudNodeId = null;
        }
        renderNodeStatus();
        updateNodeActions();
    };

    const addPrinter = async (index) => {
        const printer = state.discovered[index];
        if (!printer) {
            return;
        }
        setStatus('正在添加打印机...');
        const response = await fetch('/api/admin/printers/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(printer)
        });
        const data = await response.json();
        if (data.success) {
            // 检查云端注册状态
            if (data.cloud_registered === false && data.cloud_error) {
                // 云端注册失败，标记错误状态
                if (data.printer_id) {
                    state.printerErrors[data.printer_id] = true;
                }
                setStatus(`打印机添加成功，但云端注册失败: ${data.cloud_error}`);
            } else {
                setStatus('添加成功');
            }
            await loadManaged();
            await loadDiscovered();
        } else {
            setStatus(data.message || '添加失败');
        }
    };

    const setDefaultPrinter = async (printerId) => {
        if (!printerId) {
            return;
        }
        setStatus('正在设置默认打印机...');
        const response = await fetch('/api/admin/printers/default', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ printer_id: printerId })
        });
        const data = await response.json();
        if (data.success) {
            state.defaultId = data.default_printer_id || printerId;
            renderManaged();
            setStatus('默认打印机已更新');
        } else {
            setStatus(data.message || '设置失败');
        }
    };

    const deletePrinter = async (printerId) => {
        if (!printerId) {
            return;
        }
        setStatus('正在删除打印机...');
        const response = await fetch(`/api/admin/printers/${printerId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (data.success) {
            // 检查是否有云端删除警告
            if (data.warning) {
                setStatus(`删除成功（${data.warning}）`);
            } else {
                setStatus('删除成功');
            }
            await loadManaged();
            await loadDiscovered();
        } else {
            setStatus(data.message || '删除失败');
        }
    };

    const reregisterPrinter = async (printerId) => {
        if (!printerId) {
            return;
        }
        if (!state.cloudRegistered) {
            setStatus('节点未注册，无法重新注册打印机');
            return;
        }
        setStatus('正在重新注册打印机...');
        try {
            const response = await fetch(`/api/admin/printers/${printerId}/reregister`, {
                method: 'POST'
            });
            const data = await response.json();
            if (data.success) {
                setStatus(data.message || '重新注册成功');
                // 清除错误标记
                delete state.printerErrors[printerId];
                await loadManaged();
            } else {
                setStatus(data.message || '重新注册失败');
            }
        } catch (error) {
            setStatus('网络错误，重新注册失败');
        }
    };

    const reregisterNode = async () => {
        setStatus('正在重新注册节点...');
        try {
            const response = await fetch('/api/admin/node/reregister', {
                method: 'POST'
            });
            const data = await response.json();
            if (data.success) {
                setStatus(data.message || '节点重新注册成功');
                // 节点重新注册后，清空所有打印机错误标记（需要重新检查）
                state.printerErrors = {};
                await loadCloudStatus();
                await loadManaged();
            } else {
                setStatus(data.message || '节点重新注册失败');
            }
        } catch (error) {
            setStatus('网络错误，节点重新注册失败');
        }
    };

    discoveredList.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        if (target.dataset.action === 'add') {
            const item = target.closest('.list-item');
            const index = item ? Number(item.dataset.index) : -1;
            if (index >= 0) {
                addPrinter(index);
            }
        }
    });

    managedList.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const item = target.closest('.list-item');
        if (!item) {
            return;
        }
        const printerId = item.dataset.id;
        if (target.dataset.action === 'default') {
            setDefaultPrinter(printerId);
        }
        if (target.dataset.action === 'delete') {
            deletePrinter(printerId);
        }
        if (target.dataset.action === 'reregister') {
            reregisterPrinter(printerId);
        }
    });

    refreshDiscoveredBtn.addEventListener('click', loadDiscovered);
    refreshManagedBtn.addEventListener('click', loadManaged);
    if (reregisterNodeBtn) {
        reregisterNodeBtn.addEventListener('click', reregisterNode);
    }
    if (showPrinterReregisterBtn) {
        showPrinterReregisterBtn.addEventListener('click', () => {
            // 为所有打印机显示重新注册按钮
            state.managed.forEach(printer => {
                state.printerErrors[printer.id] = true;
            });
            renderManaged();
            setStatus('已开启打印机维护模式，可对有问题的打印机执行重新注册');
        });
    }

    // 先加载云端状态，再加载列表，确保按钮显隐正确
    loadCloudStatus().then(() => {
        loadDiscovered();
        loadManaged();
    });

    const startEventSource = () => {
        const source = new EventSource('/api/events');
        source.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                
                // 处理本地状态变更事件（自动刷新列表）
                if (msg.type === 'printer_added' || msg.type === 'printer_deleted' || msg.type === 'default_printer_changed') {
                    console.log('收到打印机变更事件，自动刷新列表');
                    loadManaged();
                    loadDiscovered();
                } else if (msg.type === 'node_status_changed') {
                    console.log('收到节点状态变更事件，自动刷新状态');
                    loadCloudStatus();
                }
                
                // 处理云端错误
                if (msg.type === 'cloud_error') {
                    const payload = msg.data || {};
                    const code = payload.code || 'unknown';
                    const message = payload.message || '';
                    if (code === 'node_deleted') {
                        // 节点被管理员删除，更新状态并提示管理员
                        state.cloudRegistered = false;
                        state.cloudConnected = false;
                        setStatus(message || '节点已被管理员删除，请点击“重新注册节点”按钮重新注册');
                        renderNodeStatus();
                        updateNodeActions();
                    }
                }
            } catch (error) {
                return;
            }
        };
        source.onerror = () => {
            source.close();
            setTimeout(startEventSource, 3000);
        };
    };

    startEventSource();
});
