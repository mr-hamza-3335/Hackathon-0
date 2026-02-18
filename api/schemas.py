"""Pydantic request/response models for the Silver API."""

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """Request body for creating a new task."""
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field("", max_length=5000)
    priority: str = Field("medium", pattern=r"^(high|medium|low)$")


class TaskResponse(BaseModel):
    """Single task in API responses."""
    id: str
    status: str
    priority: str
    source: str
    title: str
    body: str
    tags: list[str] = []
    approval_required: bool = True
    file_path: str = ""
    created: str = ""
    last_updated: str = ""


class TaskListResponse(BaseModel):
    """Response for GET /tasks."""
    tasks: list[TaskResponse]
    count: int


class ApproveResponse(BaseModel):
    """Response for POST /approve/{task_id}."""
    task_id: str
    status: str
    message: str


class LogEntry(BaseModel):
    """A single log file entry."""
    filename: str
    timestamp: str
    content: str


class LogsResponse(BaseModel):
    """Response for GET /logs/{task_id}."""
    task_id: str
    logs: list[LogEntry]


class DemoStage(BaseModel):
    """A single stage result in the demo pipeline."""
    stage: str
    status: str
    detail: str = ""


class DemoResponse(BaseModel):
    """Response for POST /demo/run."""
    task_id: str
    stages: list[DemoStage]
    final_status: str


# ── Gold tier schemas ────────────────────────────────────────────────

class ToolInfo(BaseModel):
    """Info about a registered tool."""
    name: str
    description: str
    actions: dict[str, str] = {}


class ToolExecuteRequest(BaseModel):
    """Request to execute a tool action."""
    tool: str
    action: str
    params: dict = {}


class ToolExecuteResponse(BaseModel):
    """Response from tool execution."""
    tool: str
    action: str
    success: bool
    output: dict | list | str | None = None
    error: str = ""
    duration_ms: int = 0
    risk_tier: str = ""


class PluginInfo(BaseModel):
    """Info about a loaded plugin."""
    name: str
    version: str
    description: str
    tools: list[str] = []


class ApprovalQueueItem(BaseModel):
    """An item in the approval queue."""
    id: str
    action: str
    tool: str
    risk_tier: str
    requested_at: str
    status: str


class AgentPipelineRequest(BaseModel):
    """Request to run the multi-agent pipeline."""
    task_id: str
    title: str
    body: str


class AgentPipelineResponse(BaseModel):
    """Response from multi-agent pipeline."""
    task_id: str
    plan: str
    execution_results: list[dict] = []
    review_verdict: str
    reasoning_log: str


# ── Platinum tier schemas ────────────────────────────────────────────

class MemoryStoreRequest(BaseModel):
    """Request to store a memory."""
    category: str
    key: str
    value: str
    tags: list[str] = []
    importance: int = 5


class MemoryRecallRequest(BaseModel):
    """Request to recall memories."""
    category: str | None = None
    key: str | None = None
    tags: list[str] = []
    limit: int = 20


class HealthResponse(BaseModel):
    """System health response."""
    overall: str
    checks: list[dict]


class MonitoringDashboardResponse(BaseModel):
    """Full monitoring dashboard data."""
    health: dict
    metrics: dict
    alerts: list[dict]
    timestamp: str


class ScheduleTaskRequest(BaseModel):
    """Request to schedule a task."""
    name: str
    schedule_type: str = "once"
    delay_seconds: int = 0
    interval_seconds: int = 0
    max_runs: int = 0
