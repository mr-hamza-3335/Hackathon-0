"""FastAPI server — Silver upgrade API + orchestrator background thread.

Provides REST endpoints and WebSocket for the web dashboard while running
the existing AIEmployeeOrchestrator in a daemon thread.
"""

import asyncio
import logging
import shutil
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from orchestrator.config import config
from orchestrator.orchestrator import AIEmployeeOrchestrator
from orchestrator.task_manager import TaskStatus
from watchers.utils.markdown_parser import parse_frontmatter, update_frontmatter
from memory.database import TaskDatabase
from api.schemas import (
    TaskCreate, TaskResponse, TaskListResponse,
    ApproveResponse, LogEntry, LogsResponse,
    DemoStage, DemoResponse,
    ToolInfo, ToolExecuteRequest, ToolExecuteResponse,
    PluginInfo, ApprovalQueueItem,
    AgentPipelineRequest, AgentPipelineResponse,
    MemoryStoreRequest, MemoryRecallRequest,
    HealthResponse, MonitoringDashboardResponse,
    ScheduleTaskRequest,
)
from api.websocket import manager

logger = logging.getLogger("silver.api")

# ---------------------------------------------------------------------------
# Globals (set during lifespan)
# ---------------------------------------------------------------------------
db: TaskDatabase | None = None
orchestrator: AIEmployeeOrchestrator | None = None
_orchestrator_thread: threading.Thread | None = None

UI_DIR = Path(__file__).parent.parent / "ui"
VAULT_TASKS = config.vault.tasks
VAULT_LOGS = config.vault.logs
NEEDS_ACTION_DIR = config.vault.root / "needs_action"


# ---------------------------------------------------------------------------
# Background vault sync (async loop for WebSocket broadcasts)
# ---------------------------------------------------------------------------

async def _vault_sync_loop() -> None:
    """Poll vault every 2 seconds, detect changes, broadcast via WebSocket."""
    prev_snapshot: dict[str, str] = {}
    while True:
        try:
            if db is None:
                await asyncio.sleep(2)
                continue

            db.sync_from_vault(VAULT_TASKS)
            tasks = db.get_all_tasks()
            current_snapshot = {t["id"]: t["status"] for t in tasks}

            # Detect changes
            for task_id, status in current_snapshot.items():
                old_status = prev_snapshot.get(task_id)
                if old_status != status:
                    task_data = db.get_task(task_id)
                    if task_data:
                        await manager.broadcast("task_update", task_data)

            # Detect new tasks
            new_ids = set(current_snapshot) - set(prev_snapshot)
            for task_id in new_ids:
                if task_id not in prev_snapshot:
                    continue  # already handled above

            prev_snapshot = current_snapshot

        except Exception as e:
            logger.debug(f"Vault sync error: {e}")

        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, sync vault, start orchestrator thread + sync loop."""
    global db, orchestrator, _orchestrator_thread

    # Init database
    db = TaskDatabase()
    db.sync_from_vault(VAULT_TASKS)
    logger.info(f"Database initialized, synced from vault")

    # Start orchestrator in daemon thread
    orchestrator = AIEmployeeOrchestrator()
    _orchestrator_thread = threading.Thread(
        target=orchestrator.run,
        daemon=True,
        name="orchestrator",
    )
    _orchestrator_thread.start()
    logger.info("Orchestrator started in background thread")

    # Start async vault sync loop
    sync_task = asyncio.create_task(_vault_sync_loop())

    yield

    # Shutdown
    sync_task.cancel()
    if orchestrator:
        orchestrator._running = False
    if db:
        db.close()
    logger.info("Silver server shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Personal AI Employee — Silver",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the main dashboard page."""
    index_path = UI_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(task: TaskCreate):
    """Create a new task by writing a markdown file to vault/tasks/."""
    now = datetime.now(timezone.utc)
    task_id = f"task-{now.strftime('%Y%m%d-%H%M%S')}-{now.strftime('%f')[:4]}"
    slug = task.title.lower().replace(' ', '-')[:40]
    filename = f"{now.strftime('%Y-%m-%d')}_{slug}-{now.strftime('%f')[:4]}.md"

    frontmatter = {
        "id": task_id,
        "status": "pending",
        "priority": task.priority,
        "source": "web-ui",
        "tags": [],
        "approval_required": True,
        "created": now.isoformat(timespec="seconds"),
    }
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = f"## Request\n\n{task.body}" if task.body else "## Request\n\n(No description provided)"
    content = f"---\n{yaml_str}---\n\n{body}\n"

    # Write task file
    file_path = VAULT_TASKS / filename
    file_path.write_text(content, encoding="utf-8")

    # Write trigger for orchestrator pickup
    trigger = VAULT_TASKS / ".trigger"
    trigger.write_text(task_id, encoding="utf-8")

    # Sync to database
    task_data = db.sync_single_task(file_path)

    # Broadcast via WebSocket
    await manager.broadcast("task_created", task_data)

    return TaskResponse(**task_data)


@app.get("/tasks", response_model=TaskListResponse)
async def list_tasks(status: str | None = Query(None)):
    """List all tasks, optionally filtered by status."""
    db.sync_from_vault(VAULT_TASKS)
    tasks = db.get_all_tasks(status=status)
    return TaskListResponse(
        tasks=[TaskResponse(**t) for t in tasks],
        count=len(tasks),
    )


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Get a single task by ID."""
    db.sync_from_vault(VAULT_TASKS)
    task_data = db.get_task(task_id)
    if not task_data:
        raise HTTPException(404, f"Task {task_id} not found")
    return TaskResponse(**task_data)


@app.post("/approve/{task_id}", response_model=ApproveResponse)
async def approve_task(task_id: str):
    """Approve a task by updating its frontmatter to status: approved."""
    db.sync_from_vault(VAULT_TASKS)
    task_data = db.get_task(task_id)
    if not task_data:
        raise HTTPException(404, f"Task {task_id} not found")

    if task_data["status"] != "awaiting-approval":
        raise HTTPException(
            400,
            f"Task is '{task_data['status']}', not 'awaiting-approval'",
        )

    # Find the task file
    file_path = Path(task_data["file_path"])
    if not file_path.exists():
        # Search for it
        for md_file in VAULT_TASKS.glob("*.md"):
            fm, _ = parse_frontmatter(md_file)
            if fm.get("id") == task_id:
                file_path = md_file
                break
        else:
            raise HTTPException(404, f"Task file not found for {task_id}")

    # Update frontmatter
    update_frontmatter(file_path, {"status": "approved"})

    # Clean up needs_action copy
    needs_copy = NEEDS_ACTION_DIR / file_path.name
    if needs_copy.exists():
        needs_copy.unlink()

    # Sync to DB
    db.sync_single_task(file_path)
    db.record_transition(task_id, "awaiting-approval", "approved")

    # Broadcast
    updated = db.get_task(task_id)
    await manager.broadcast("task_update", updated)

    return ApproveResponse(
        task_id=task_id,
        status="approved",
        message="Task approved — orchestrator will execute it",
    )


@app.get("/logs/{task_id}", response_model=LogsResponse)
async def get_logs(task_id: str):
    """Get all log entries related to a task."""
    logs: list[LogEntry] = []

    if not VAULT_LOGS.exists():
        return LogsResponse(task_id=task_id, logs=[])

    for log_file in sorted(VAULT_LOGS.glob("*.md")):
        if log_file.name.startswith("_"):
            continue
        try:
            fm, body = parse_frontmatter(log_file)
            if fm.get("task_id") == task_id:
                logs.append(LogEntry(
                    filename=log_file.name,
                    timestamp=fm.get("timestamp", ""),
                    content=body,
                ))
        except Exception:
            pass

    return LogsResponse(task_id=task_id, logs=logs)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"event":"pong","data":{}}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/demo/run", response_model=DemoResponse)
async def run_demo():
    """Run a demo pipeline: create → plan → approve → execute → archive."""
    stages: list[DemoStage] = []
    now = datetime.now(timezone.utc)
    task_id = f"demo-{now.strftime('%Y%m%d-%H%M%S')}"
    filename = f"{now.strftime('%Y-%m-%d')}_demo-pipeline.md"

    # Stage 1: Create task
    frontmatter = {
        "id": task_id,
        "status": "pending",
        "priority": "medium",
        "source": "demo",
        "tags": ["demo"],
        "approval_required": True,
        "created": now.isoformat(timespec="seconds"),
    }
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = "## Request\n\nDemo pipeline test — send a test email to team@example.com."
    content = f"---\n{yaml_str}---\n\n{body}\n"

    file_path = VAULT_TASKS / filename
    file_path.write_text(content, encoding="utf-8")
    db.sync_single_task(file_path)
    stages.append(DemoStage(stage="create", status="success", detail=f"Created {task_id}"))
    await manager.broadcast("task_created", db.get_task(task_id))

    # Stage 2: Simulate planning
    plan_text = (
        "## Proposed Plan\n\n"
        "- [ ] Step 1: Gather report data (tool: none, approval: no)\n"
        "- [ ] Step 2: Draft email (tool: draft_email, approval: yes)\n"
        "- [ ] Step 3: Send email (tool: send_email, approval: yes)\n"
    )
    fm, existing_body = parse_frontmatter(file_path)
    fm["status"] = "awaiting-approval"
    new_body = existing_body + "\n\n" + plan_text
    yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    file_path.write_text(f"---\n{yaml_str}---\n\n{new_body}\n", encoding="utf-8")

    # Copy to needs_action
    needs_copy = NEEDS_ACTION_DIR / filename
    NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(file_path), str(needs_copy))

    db.sync_single_task(file_path)
    db.record_transition(task_id, "pending", "awaiting-approval")
    stages.append(DemoStage(stage="plan", status="success", detail="Plan generated"))
    await manager.broadcast("task_update", db.get_task(task_id))

    # Stage 3: Auto-approve
    update_frontmatter(file_path, {"status": "approved"})
    if needs_copy.exists():
        needs_copy.unlink()
    db.sync_single_task(file_path)
    db.record_transition(task_id, "awaiting-approval", "approved")
    stages.append(DemoStage(stage="approve", status="success", detail="Auto-approved"))
    await manager.broadcast("task_update", db.get_task(task_id))

    # Stage 4: Simulate execution
    update_frontmatter(file_path, {"status": "executing"})
    db.sync_single_task(file_path)
    db.record_transition(task_id, "approved", "executing")

    result_text = (
        "**Step 1** [+] Gather report data\n"
        "- Tool: `none`\n- Status: success\n- Duration: 0ms\n\n"
        "**Step 2** [+] Draft email\n"
        "- Tool: `draft_email`\n- Status: success (simulated)\n- Duration: 50ms\n\n"
        "**Step 3** [+] Send email\n"
        "- Tool: `send_email`\n- Status: success (simulated)\n- Duration: 30ms\n"
    )
    fm2, body2 = parse_frontmatter(file_path)
    fm2["status"] = "completed"
    new_body2 = body2 + "\n\n## Execution Result\n\n" + result_text
    yaml_str2 = yaml.dump(fm2, default_flow_style=False, sort_keys=False)
    file_path.write_text(f"---\n{yaml_str2}---\n\n{new_body2}\n", encoding="utf-8")

    db.sync_single_task(file_path)
    db.record_transition(task_id, "executing", "completed")
    stages.append(DemoStage(stage="execute", status="success", detail="3 steps completed"))

    # Stage 5: Archive
    archive_dir = VAULT_TASKS / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / filename
    shutil.move(str(file_path), str(archive_path))
    db.sync_single_task(archive_path)
    stages.append(DemoStage(stage="archive", status="success", detail=f"Archived to {archive_path.name}"))
    await manager.broadcast("task_update", db.get_task(task_id))

    return DemoResponse(
        task_id=task_id,
        stages=stages,
        final_status="completed",
    )


# ---------------------------------------------------------------------------
# Gold Tier Endpoints
# ---------------------------------------------------------------------------

@app.get("/tools", response_model=list[ToolInfo])
async def list_tools():
    """List all registered tools (Gold tier)."""
    from gold.tools.base import tool_registry
    return [ToolInfo(**t) for t in tool_registry.list_tools()]


@app.post("/tools/execute", response_model=ToolExecuteResponse)
async def execute_tool(req: ToolExecuteRequest):
    """Execute a tool action (Gold tier)."""
    from gold.tools.base import tool_executor
    result = tool_executor.execute(req.tool, req.action, req.params)
    return ToolExecuteResponse(
        tool=result.tool, action=result.action,
        success=result.success, output=result.output,
        error=result.error, duration_ms=result.duration_ms,
        risk_tier=result.risk_tier,
    )


@app.get("/plugins", response_model=list[PluginInfo])
async def list_plugins():
    """List all loaded plugins (Gold tier)."""
    from plugins.base import plugin_manager
    return [PluginInfo(**p) for p in plugin_manager.get_loaded_plugins()]


@app.get("/approvals", response_model=list[ApprovalQueueItem])
async def get_approval_queue():
    """Get pending action approvals (Gold tier)."""
    from gold.security.permissions import permissions
    pending = permissions.get_pending_approvals()
    return [
        ApprovalQueueItem(
            id=r.id, action=r.action, tool=r.tool,
            risk_tier=str(r.risk_tier), requested_at=r.requested_at,
            status=r.status,
        )
        for r in pending
    ]


@app.post("/approvals/{request_id}/approve")
async def approve_action(request_id: str):
    """Approve a pending action (Gold tier)."""
    from gold.security.permissions import permissions
    if permissions.approve_request(request_id):
        return {"status": "approved", "request_id": request_id}
    raise HTTPException(404, f"Request {request_id} not found or already processed")


@app.post("/approvals/{request_id}/deny")
async def deny_action(request_id: str, reason: str = ""):
    """Deny a pending action (Gold tier)."""
    from gold.security.permissions import permissions
    if permissions.deny_request(request_id, reason):
        return {"status": "denied", "request_id": request_id}
    raise HTTPException(404, f"Request {request_id} not found or already processed")


@app.post("/agents/pipeline", response_model=AgentPipelineResponse)
async def run_agent_pipeline(req: AgentPipelineRequest):
    """Run the multi-agent pipeline on a task (Gold tier)."""
    from gold.agents.coordinator import AgentCoordinator
    coordinator = AgentCoordinator(vault_root=str(config.vault.root))
    ctx = coordinator.run_pipeline(req.task_id, req.title, req.body)
    return AgentPipelineResponse(
        task_id=ctx.task_id,
        plan=ctx.plan,
        execution_results=ctx.execution_results,
        review_verdict=ctx.review_verdict,
        reasoning_log=ctx.get_reasoning_log(),
    )


# ---------------------------------------------------------------------------
# Platinum Tier Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check (Platinum tier)."""
    from platinum.monitoring.monitor import monitor
    status = monitor.health.get_status()
    return HealthResponse(**status)


@app.get("/monitoring", response_model=MonitoringDashboardResponse)
async def monitoring_dashboard():
    """Full monitoring dashboard (Platinum tier)."""
    from platinum.monitoring.monitor import monitor
    return MonitoringDashboardResponse(**monitor.get_dashboard_data())


@app.get("/alerts")
async def get_alerts():
    """Get active alerts (Platinum tier)."""
    from platinum.monitoring.monitor import monitor
    return monitor.alerts.get_all_alerts()


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert (Platinum tier)."""
    from platinum.monitoring.monitor import monitor
    if monitor.alerts.acknowledge(alert_id):
        return {"status": "acknowledged", "alert_id": alert_id}
    raise HTTPException(404, f"Alert {alert_id} not found")


@app.post("/memory/store")
async def store_memory(req: MemoryStoreRequest):
    """Store a memory entry (Platinum tier)."""
    from platinum.memory.memory_store import MemoryStore
    store = MemoryStore()
    mid = store.store(req.category, req.key, req.value, req.tags, req.importance)
    store.close()
    return {"id": mid, "status": "stored"}


@app.post("/memory/recall")
async def recall_memory(req: MemoryRecallRequest):
    """Recall memories (Platinum tier)."""
    from platinum.memory.memory_store import MemoryStore
    store = MemoryStore()
    results = store.recall(req.category, req.key, req.tags, req.limit)
    store.close()
    return {"results": results, "count": len(results)}


@app.get("/memory/search")
async def search_memory(q: str = Query("")):
    """Search memory (Platinum tier)."""
    from platinum.memory.memory_store import MemoryStore
    store = MemoryStore()
    results = store.search(q)
    store.close()
    return {"results": results, "count": len(results)}


@app.get("/memory/stats")
async def memory_stats():
    """Get memory statistics (Platinum tier)."""
    from platinum.memory.memory_store import MemoryStore
    store = MemoryStore()
    stats = store.get_stats()
    store.close()
    return stats


@app.get("/scheduler/tasks")
async def get_scheduled_tasks():
    """List scheduled tasks (Platinum tier)."""
    from platinum.scheduler.scheduler import scheduler
    return scheduler.get_scheduled_tasks()


@app.get("/scheduler/status")
async def scheduler_status():
    """Get scheduler worker status (Platinum tier)."""
    from platinum.scheduler.scheduler import scheduler
    return scheduler.get_worker_status()


# ---------------------------------------------------------------------------
# Static files (mount AFTER routes so routes take precedence)
# ---------------------------------------------------------------------------

if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
