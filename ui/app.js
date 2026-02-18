// Silver Dashboard — API calls, WebSocket, rendering

const API = '';  // Same origin
let ws = null;
let currentFilter = 'all';
let tasks = [];

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById('ws-status').textContent = 'Connected';
        document.getElementById('ws-status').className = 'ws-status connected';
    };

    ws.onclose = () => {
        document.getElementById('ws-status').textContent = 'Disconnected';
        document.getElementById('ws-status').className = 'ws-status disconnected';
        // Auto-reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleWSEvent(msg.event, msg.data);
    };
}

function handleWSEvent(eventType, data) {
    if (eventType === 'task_created' || eventType === 'task_update') {
        // Refresh the task list
        loadTasks();
        const action = eventType === 'task_created' ? 'created' : 'updated';
        showToast(`Task ${data.id} ${action}: ${data.status}`, 'info');
    } else if (eventType === 'pong') {
        // Ignore pong
    }
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

async function loadTasks() {
    try {
        const url = currentFilter === 'all' ? '/tasks' : `/tasks?status=${currentFilter}`;
        const resp = await fetch(url);
        const data = await resp.json();
        tasks = data.tasks;
        renderTaskList();
    } catch (err) {
        console.error('Failed to load tasks:', err);
    }
}

async function createTask(e) {
    e.preventDefault();
    const title = document.getElementById('task-title').value.trim();
    const body = document.getElementById('task-body').value.trim();
    const priority = document.getElementById('task-priority').value;

    if (!title) return;

    try {
        const resp = await fetch('/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, body, priority }),
        });

        if (resp.ok) {
            const task = await resp.json();
            showToast(`Task "${task.title}" created`, 'success');
            document.getElementById('create-form').reset();
            loadTasks();
        } else {
            const err = await resp.json();
            showToast(`Error: ${err.detail}`, 'error');
        }
    } catch (err) {
        showToast('Failed to create task', 'error');
    }
}

async function approveTask(taskId) {
    try {
        const resp = await fetch(`/approve/${taskId}`, { method: 'POST' });
        if (resp.ok) {
            showToast(`Task ${taskId} approved`, 'success');
            loadTasks();
        } else {
            const err = await resp.json();
            showToast(`Error: ${err.detail}`, 'error');
        }
    } catch (err) {
        showToast('Failed to approve task', 'error');
    }
}

async function loadLogs() {
    const taskId = document.getElementById('log-task-id').value.trim();
    if (!taskId) return;

    const viewer = document.getElementById('log-viewer');
    viewer.innerHTML = '<div class="empty-state">Loading...</div>';

    try {
        const resp = await fetch(`/logs/${taskId}`);
        const data = await resp.json();

        if (data.logs.length === 0) {
            viewer.innerHTML = '<div class="empty-state">No logs found for this task</div>';
            return;
        }

        viewer.innerHTML = data.logs.map(log => `
            <div class="log-entry">
                <span class="log-time">${log.timestamp}</span>
                <span class="log-action">${log.filename}</span>
                <div>${escapeHtml(log.content).substring(0, 200)}</div>
            </div>
        `).join('');
    } catch (err) {
        viewer.innerHTML = '<div class="empty-state">Failed to load logs</div>';
    }
}

async function runDemo() {
    const btn = document.getElementById('demo-btn');
    const stagesEl = document.getElementById('demo-stages');
    btn.disabled = true;
    btn.textContent = 'Running...';
    stagesEl.innerHTML = '';

    try {
        const resp = await fetch('/demo/run', { method: 'POST' });
        const data = await resp.json();

        stagesEl.innerHTML = data.stages.map(s => `
            <li class="demo-stage">
                <span class="stage-icon">${s.status === 'success' ? '\u2705' : '\u274C'}</span>
                <strong>${s.stage}</strong>: ${s.detail}
            </li>
        `).join('');

        showToast(`Demo complete: ${data.final_status}`, 'success');
        loadTasks();
    } catch (err) {
        showToast('Demo pipeline failed', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Run Demo Pipeline';
    }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderTaskList() {
    const list = document.getElementById('task-list');

    if (tasks.length === 0) {
        list.innerHTML = '<li class="empty-state">No tasks found</li>';
        return;
    }

    list.innerHTML = tasks.map(task => `
        <li class="task-item" onclick="showTaskDetail('${task.id}')">
            <div class="task-item-header">
                <span class="task-title">${escapeHtml(task.title || task.id)}</span>
                <div class="task-meta">
                    <span class="badge badge-${task.priority}">${task.priority}</span>
                    <span class="badge badge-${task.status}">${task.status}</span>
                    ${task.status === 'awaiting-approval'
                        ? `<button class="btn btn-success btn-sm" onclick="event.stopPropagation(); approveTask('${task.id}')">Approve</button>`
                        : ''}
                </div>
            </div>
            <div class="task-meta">
                <span>${task.id}</span>
                <span>${task.source || ''}</span>
            </div>
        </li>
    `).join('');
}

function showTaskDetail(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;

    document.getElementById('modal-title').textContent = task.title || task.id;
    document.getElementById('modal-body').innerHTML = `
        <p><strong>ID:</strong> ${task.id}</p>
        <p><strong>Status:</strong> <span class="badge badge-${task.status}">${task.status}</span></p>
        <p><strong>Priority:</strong> <span class="badge badge-${task.priority}">${task.priority}</span></p>
        <p><strong>Source:</strong> ${task.source}</p>
        <p><strong>Created:</strong> ${task.created}</p>
        <p><strong>Tags:</strong> ${(task.tags || []).join(', ') || 'none'}</p>
        <hr style="border-color: var(--border); margin: 12px 0;">
        <pre>${escapeHtml(task.body)}</pre>
        ${task.status === 'awaiting-approval'
            ? `<button class="btn btn-success" style="margin-top: 12px;" onclick="approveTask('${task.id}'); closeModal();">Approve Task</button>`
            : ''}
    `;

    document.getElementById('modal-overlay').classList.add('active');

    // Auto-fill log viewer
    document.getElementById('log-task-id').value = taskId;
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('modal-overlay').classList.remove('active');
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        loadTasks();
    });
});

// ---------------------------------------------------------------------------
// Toast Notifications
// ---------------------------------------------------------------------------

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.getElementById('create-form').addEventListener('submit', createTask);
connectWebSocket();
loadTasks();

// Refresh tasks every 10 seconds as backup
setInterval(loadTasks, 10000);
