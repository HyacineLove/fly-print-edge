document.addEventListener('DOMContentLoaded', () => {
    const discoveredList = document.getElementById('discovered-list');
    const managedList = document.getElementById('managed-list');
    const statusElem = document.getElementById('admin-status');
    const nodeStatusElem = document.getElementById('node-status');
    const refreshDiscoveredBtn = document.getElementById('refresh-discovered');
    const refreshManagedBtn = document.getElementById('refresh-managed');

    const state = {
        discovered: [],
        managed: [],
        defaultId: null,
        nodeEnabled: true
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
            const enabled = printer.enabled !== false;
            const badgeClass = enabled ? 'badge badge-success' : 'badge badge-danger';
            const badgeText = enabled ? '启用' : '禁用';
            return `
                <div class="list-item" data-id="${printer.id}">
                    <div>
                        <div class="item-title">${title} ${isDefault ? '<span class="badge">默认</span>' : ''} <span class="${badgeClass}">${badgeText}</span></div>
                        <div class="item-subtitle">${subtitle}</div>
                        <div class="item-meta">${meta}</div>
                    </div>
                    <div class="item-actions">
                        <button class="btn btn-outline" data-action="default">设为默认</button>
                        <button class="btn btn-danger" data-action="delete">删除</button>
                    </div>
                </div>
            `;
        }).join('');
    };

    const renderNodeStatus = () => {
        if (!nodeStatusElem) {
            return;
        }
        const badgeClass = state.nodeEnabled ? 'badge badge-success' : 'badge badge-danger';
        const badgeText = state.nodeEnabled ? '启用' : '禁用';
        nodeStatusElem.innerHTML = `<span>节点状态</span><span class="${badgeClass}">${badgeText}</span>`;
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
            setStatus('');
        } else {
            setStatus(data.message || '刷新失败');
        }
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
            setStatus('添加成功');
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
            setStatus('删除成功');
            await loadManaged();
            await loadDiscovered();
        } else {
            setStatus(data.message || '删除失败');
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
    });

    refreshDiscoveredBtn.addEventListener('click', loadDiscovered);
    refreshManagedBtn.addEventListener('click', loadManaged);

    loadDiscovered();
    loadManaged();

    const startEventSource = () => {
        const source = new EventSource('/api/events');
        source.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'printer_deleted') {
                    loadManaged();
                    loadDiscovered();
                }
                if (data.type === 'node_state') {
                    state.nodeEnabled = data.data && data.data.enabled !== false;
                    renderNodeStatus();
                }
                if (data.type === 'printer_state') {
                    const payload = data.data || {};
                    const printerId = payload.printer_id;
                    const enabled = payload.enabled !== false;
                    const target = state.managed.find((printer) => printer.id === printerId);
                    if (target) {
                        target.enabled = enabled;
                        renderManaged();
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
