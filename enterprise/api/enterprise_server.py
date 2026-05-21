"""
Enterprise FastAPI Server
==========================
Production-grade REST API + WebSocket server for the AI Enterprise Employee Platform.

Endpoints:
  /api/v2/tasks          — Task CRUD
  /api/v2/approvals      — Unified approval queue (all integrations)
  /api/v2/gmail          — Gmail operations
  /api/v2/calendar       — Calendar operations
  /api/v2/whatsapp       — WhatsApp operations
  /api/v2/agents         — 5-agent pipeline control
  /api/v2/assistant      — Smart assistant
  /api/v2/memory         — Memory viewer
  /api/v2/monitoring     — System health
  /api/v2/upload/pdf     — PDF task import
  /ws/v2                 — Real-time WebSocket
  /webhooks/whatsapp     — Twilio webhook receiver
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
    Request, UploadFile, WebSocket, WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger(__name__)

# ── Auth + Queue imports (lazy to avoid import errors when deps are missing) #
try:
    from enterprise.auth.dependencies import get_current_user, get_optional_user, UserClaims
    from enterprise.auth.jwt_handler  import (
        hash_password, verify_password,
        create_access_token, create_refresh_token, decode_token,
    )
    _AUTH_AVAILABLE = True
except ImportError as _auth_err:
    logger.warning("[AUTH] Auth module unavailable: %s", _auth_err)
    _AUTH_AVAILABLE = False
    # Stub so routes compile
    class UserClaims:  # type: ignore
        user_id = "default"; email = ""; plan = "free"
    def get_current_user():  return UserClaims()  # type: ignore
    def get_optional_user(): return None           # type: ignore

try:
    from enterprise.queue.redis_queue import get_queue
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

try:
    from enterprise.billing.stripe_client import get_stripe, PLANS, check_quota
    _BILLING_AVAILABLE = True
except ImportError:
    _BILLING_AVAILABLE = False
    PLANS = {}
    def check_quota(*a, **kw): return True   # type: ignore

# ── Pydantic Models ──────────────────────────────────────────────────────── #

class TaskCreate(BaseModel):
    title: str
    description: str
    priority: str = "medium"
    source: str = "ui"
    requester: str = "user"
    tags: List[str] = []

class ApprovalAction(BaseModel):
    action: str  # "approve" | "reject" | "edit"
    edited_content: Optional[str] = None
    reason: Optional[str] = None

class SmartAssistantRequest(BaseModel):
    instruction: str
    context: Optional[Dict] = None

class GmailReplyRequest(BaseModel):
    to: str
    subject: str
    body: str

class CalendarEventRequest(BaseModel):
    natural_language: str

class WhatsAppSendRequest(BaseModel):
    to: str
    message: str

class DemoStage(BaseModel):
    stage: str
    status: str
    detail: str = ""

class DemoResponse(BaseModel):
    task_id: str
    stages: List[DemoStage]
    final_status: str

class DemoRequest(BaseModel):
    scenario: str

# ── WebSocket Manager ─────────────────────────────────────────────────────── #

class WebSocketManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WebSocket client connected (total: %d)", len(self.active))

    def disconnect(self, ws: WebSocket):
        try:
            self.active.remove(ws)
        except ValueError:
            pass  # already removed by broadcast cleanup

    async def broadcast(self, data: Dict):
        message = json.dumps(data)
        disconnected = []
        for ws in list(self.active):  # snapshot to avoid mutation during iteration
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            try:
                self.active.remove(ws)
            except ValueError:
                pass  # already removed by a concurrent disconnect()

    def broadcast_sync(self, data: Dict):
        """Sync wrapper for use from non-async code."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.broadcast(data))
            else:
                loop.run_until_complete(self.broadcast(data))
        except Exception as e:
            logger.debug("Broadcast sync failed: %s", e)


ws_manager = WebSocketManager()

# ── WhatsApp Event Ring Buffer + Fallback Queue ───────────────────────────── #

_wa_events: List[Dict] = []
_WA_MAX_EVENTS = 500
_web_send_queue: Dict[str, Dict] = {}   # id → {id, to, message, user_id, created_at}

# ── WhatsApp QR / Connection State ───────────────────────────────────────────#
_wa_qr_state: Dict = {
    "status":     "disconnected",   # disconnected | qr_ready | connected | auth_failure
    "qr_image":   None,             # base64 PNG data URL
    "qr_string":  None,             # raw QR string
    "phone":      None,
    "updated_at": None,
}

_wa_accounts: Dict[str, Dict] = {
    "wa-ai-bot": {
        "clientId": "wa-ai-bot",
        "label": "Primary Bot",
        "status": "disconnected",
        "qr_image": None,
        "qr_string": None,
        "phone": None,
        "updated_at": None,
    }
}



async def _wa_emit(evt: Dict, user_id: str = "default") -> None:
    """
    1. Tag the event with event/user_id/timestamp
    2. Append to in-memory ring buffer
    3. Persist to MongoDB (non-blocking, best-effort)
    4. Broadcast to all WebSocket clients
    """
    evt["event"]   = "wa_event"
    evt["user_id"] = evt.get("user_id") or user_id
    evt.setdefault("timestamp", datetime.utcnow().isoformat())
    if "event_id" not in evt:
        evt["event_id"] = str(uuid.uuid4())

    _wa_events.append(evt)
    if len(_wa_events) > _WA_MAX_EVENTS:
        del _wa_events[0]

    # Persist asynchronously — never block the response path
    try:
        from enterprise.integrations.whatsapp.db import persist_event
        asyncio.ensure_future(persist_event(evt))
    except Exception:
        pass

    await ws_manager.broadcast(evt)


# ── Integration Singletons ───────────────────────────────────────────────── #

_gmail_agent = None
_calendar_agent = None
_whatsapp_agent = None
_linkedin_agent = None
_smart_assistant = None
_coordinator = None


async def _send_with_fallback(to: str, message: str, user_id: str = "default") -> Dict:
    """
    Try Twilio first.  On permanent failure (daily limit, invalid number, etc.),
    queue the message for the WhatsApp Web bot (Node.js) to pick up and send.
    Always emits OUT / ERROR events.
    """
    try:
        agent = get_whatsapp_agent()
        result = agent.client.send_message(to=to, body=message)
        if result.success:
            await _wa_emit({
                "type": "OUT", "source": "twilio",
                "from": "manual", "to": to,
                "message": message, "status": "sent",
                "sid": result.data.get("sid"),
            }, user_id=user_id)
            return {"success": True, "channel": "twilio", "sid": result.data.get("sid")}
    except HTTPException:
        pass
    except Exception as exc:
        logger.warning("[FALLBACK] Twilio send failed (%s) — queuing for web bot", exc)

    # Twilio failed — enqueue for web bot via Redis queue (or in-memory fallback)
    if _REDIS_AVAILABLE:
        qid = await get_queue().push(to=to, message=message, user_id=user_id)
    else:
        qid = str(uuid.uuid4())
        _web_send_queue[qid] = {
            "id": qid, "to": to, "message": message,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending",
        }
    await _wa_emit({
        "type": "OUT", "source": "web",
        "from": "fallback_queue", "to": to,
        "message": message, "status": "queued_fallback",
        "queue_id": qid, "fallback_used": True,
    }, user_id=user_id)
    logger.info("[FALLBACK] Message queued for web bot (id=%s)", qid)
    return {"success": True, "channel": "web_fallback", "queue_id": qid}


def get_gmail_agent():
    global _gmail_agent
    if _gmail_agent is None:
        from enterprise.integrations.gmail.agent import GmailAgent
        _gmail_agent = GmailAgent()
        _gmail_agent.connect()
    if not _gmail_agent.client._connected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gmail integration is offline. "
                "Run: python -m enterprise.integrations.gmail.auth"
            ),
        )
    return _gmail_agent


def get_calendar_agent():
    global _calendar_agent
    if _calendar_agent is None:
        from enterprise.integrations.google_calendar.agent import CalendarAgent
        _calendar_agent = CalendarAgent()
        _calendar_agent.connect()
    if not _calendar_agent.client._connected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google Calendar integration is offline. "
                "Run: python -m enterprise.integrations.gmail.auth  (Calendar shares Gmail OAuth)"
            ),
        )
    return _calendar_agent


def get_whatsapp_agent():
    global _whatsapp_agent
    if _whatsapp_agent is None:
        from enterprise.integrations.whatsapp.agent import WhatsAppAgent
        _whatsapp_agent = WhatsAppAgent()
        _whatsapp_agent.connect()
    # Use health_check() — avoids AttributeError if _connected is ever missing,
    # and correctly reflects both Twilio client state and status flag.
    if not _whatsapp_agent.client.health_check():
        raise HTTPException(
            status_code=503,
            detail=(
                "WhatsApp integration is offline. "
                "Check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN in .env and restart."
            ),
        )
    return _whatsapp_agent


def get_smart_assistant():
    global _smart_assistant
    if _smart_assistant is None:
        from enterprise.tasks.smart_assistant import SmartAssistant
        # Gracefully handle any offline integrations — SmartAssistant runs in
        # simulation mode for integrations that aren't connected yet.
        def _try(fn):
            try:
                return fn()
            except Exception:
                return None
        _smart_assistant = SmartAssistant(
            gmail_agent=_try(get_gmail_agent),
            calendar_agent=_try(get_calendar_agent),
            whatsapp_agent=_try(get_whatsapp_agent),
        )
    return _smart_assistant


def get_linkedin_agent():
    global _linkedin_agent
    if _linkedin_agent is None:
        from enterprise.integrations.linkedin.agent import LinkedInAgent
        _linkedin_agent = LinkedInAgent()
        _linkedin_agent.connect()
    return _linkedin_agent


def get_coordinator():
    global _coordinator
    if _coordinator is None:
        from enterprise.agents.coordinator import EnterpriseCoordinator
        _coordinator = EnterpriseCoordinator(
            broadcast_fn=ws_manager.broadcast_sync,
            approval_required=True,
        )
    return _coordinator


# ── App Lifecycle ─────────────────────────────────────────────────────────── #

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Enterprise server starting...")

    # ── Init MongoDB + preload recent WA events ──────────────────────────── #
    try:
        from enterprise.integrations.whatsapp.db import get_db, load_recent_events
        await get_db()
        loaded = await load_recent_events(limit=500)
        if loaded:
            _wa_events.extend(loaded)
            logger.info("[MongoDB] Preloaded %d WA events into cache", len(loaded))
    except Exception as _mongo_exc:
        logger.warning("[MongoDB] Startup preload skipped: %s", _mongo_exc)

    # Start background Gmail polling (every 60s)
    async def poll_gmail():
        while True:
            try:
                agent = get_gmail_agent()
                tasks = agent.poll_once()
                if tasks:
                    auto_sent = [t for t in tasks if getattr(t, "auto_sent", False)]
                    queued    = [t for t in tasks if not getattr(t, "auto_sent", False)]
                    await ws_manager.broadcast({
                        "event": "gmail_new_tasks",
                        "count": len(tasks),
                        "auto_sent": len(auto_sent),
                        "queued_for_approval": len(queued),
                        "task_ids": [t.task_id for t in tasks],
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            except HTTPException as e:
                logger.error("Gmail poll skipped — integration offline: %s", e.detail)
            except Exception as e:
                logger.error("Gmail poll error: %s", e)
            await asyncio.sleep(60)

    gmail_task = asyncio.create_task(poll_gmail())

    # ── Start Autonomous Loop (Gold Tier) ────────────────────────────────── #
    _auto_loop = None
    if os.getenv("AUTONOMOUS_LOOP_ENABLED", "true").lower() != "false":
        try:
            from enterprise.autonomous.loop import AutonomousLoop
            global _autonomous_loop
            _autonomous_loop = AutonomousLoop(
                interval_seconds=int(os.getenv("AUTONOMOUS_LOOP_INTERVAL", "300")),
                ws_emit=ws_manager.broadcast,
            )
            _autonomous_loop.start()
            _auto_loop = _autonomous_loop
            logger.info("Autonomous Loop started (interval=%ds)", _autonomous_loop._interval)
        except Exception as _loop_exc:
            logger.warning("Autonomous Loop failed to start: %s", _loop_exc)

    # ── Start Silver Scheduler ────────────────────────────────────────────── #
    try:
        from enterprise.scheduler import silver_scheduler
        silver_scheduler.start()
        # Schedule daily LinkedIn post at 9 AM equivalent (interval)
        silver_scheduler.schedule_daily_post(
            name="daily-linkedin-post",
            topic="AI automation and enterprise efficiency",
            tone="thought_leadership",
        )
        silver_scheduler.schedule_weekly_report()
        silver_scheduler.schedule_daily_tweet(
            name="daily-twitter-post",
            topic="AI automation and enterprise productivity",
        )
        silver_scheduler.schedule_inbox_check(
            name="gmail-inbox-check",
            interval_seconds=300,
        )
        # Growth & sales schedules (Options A+B)
        silver_scheduler.schedule_engagement_check(
            name="linkedin-engagement",
            interval_seconds=3600,    # every hour
        )
        silver_scheduler.schedule_lead_dm(
            name="hot-lead-dm",
            interval_seconds=7200,    # every 2 hours
        )
        silver_scheduler.schedule_crm_followups(
            name="crm-followups",
            interval_seconds=43200,   # every 12 hours
        )
        logger.info(
            "Silver Scheduler started: LinkedIn post + engagement + lead DM + CRM followups "
            "+ Twitter + weekly report + Gmail check"
        )
    except Exception as _sched_exc:
        logger.warning("Silver Scheduler failed to start: %s", _sched_exc)

    # ── Start Business Orchestrator (Option C) ─────────────────��──────────── #
    try:
        from enterprise.orchestration.business_orchestrator import get_orchestrator
        _orchestrator = get_orchestrator(ws_emit=ws_manager.broadcast)
        _orchestrator.start()
        logger.info("Business Orchestrator started (interval=%ds)", _orchestrator._interval)
    except Exception as _orc_exc:
        logger.warning("Business Orchestrator failed to start: %s", _orc_exc)

    logger.info("Enterprise server ready — Gold Tier active.")
    yield

    gmail_task.cancel()
    if _auto_loop:
        _auto_loop.stop()
    try:
        from enterprise.scheduler import silver_scheduler
        silver_scheduler.stop()
    except Exception:
        pass
    try:
        from enterprise.orchestration.business_orchestrator import get_orchestrator
        get_orchestrator().stop()
    except Exception:
        pass
    logger.info("Enterprise server shutdown.")


# ── FastAPI App ───────────────────────────────────────────────────────────── #

app = FastAPI(
    title="AI Enterprise Employee Platform",
    description="Production-grade autonomous AI automation platform",
    version="2.0.0-enterprise",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Cinematic Demo Endpoints ─────────────────────────────────────────────── #

async def _emit_demo_trace(task_id: str, agent_name: str, stage: str, thought: str, options: list, rejected: list, constraints: list, confidence: float, outcome: str, actions: list = None, observations: list = None):
    trace_id = str(uuid.uuid4())
    data = {
        "trace_id": trace_id,
        "task_id": task_id,
        "agent_name": agent_name,
        "stage": stage,
        "timestamp": datetime.utcnow().isoformat(),
        "observations": observations or [],
        "reasoning": {
            "thought": thought,
            "options_considered": options,
            "rejected_actions": rejected,
            "constraints": constraints,
            "confidence": confidence,
            "expected_outcome": outcome
        } if thought else None,
        "actions": actions or [],
        "metrics": {"total_latency_ms": sum((a.get("latency_ms", 0) for a in (actions or []))), "total_cost_usd": 0.0}
    }
    await ws_manager.broadcast({"event": "trace_event", "data": data})
    return data

async def execute_cinematic_demo(scenario: str, task_id: str):
    import yaml
    from pathlib import Path
    
    VAULT_TASKS = Path(__file__).parent.parent.parent / "vault" / "tasks"
    VAULT_TASKS.mkdir(parents=True, exist_ok=True)
    
    now = datetime.utcnow()
    
    # 1. Base scenario selection
    if scenario == "supplier_failure":
        body = "URGENT: Component supplier XYZ just filed for bankruptcy. We need a recovery plan and an alternative supplier immediately."
    elif scenario == "inventory_crisis":
        body = "ALERT: Warehouse A reports 0 stock for SKUs 123-456. Major disruption incoming."
    elif scenario == "customer_escalation":
        body = "CRITICAL: Enterprise client Acme Corp reports delay in contract delivery. Requesting refunds."
    else:
        body = f"ESCALATION: Critical issue detected in {scenario}."
        
    # Write MD task file to Vault
    filename = f"{now.strftime('%Y-%m-%d')}_demo-{scenario}.md"
    file_path = VAULT_TASKS / filename
    
    frontmatter = {
        "id": task_id,
        "status": "pending",
        "priority": "critical",
        "source": "autonomous-monitor",
        "tags": ["demo", scenario],
        "approval_required": True,
        "created": now.isoformat(timespec="seconds"),
    }
    
    file_path.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n## Request\n\n{body}\n",
        encoding="utf-8"
    )
    
    # Broadcast task creation
    try:
        from memory.database import TaskDatabase
        db = TaskDatabase()
        db.sync_single_task(file_path)
        task_data = db.get_task(task_id)
        if task_data:
            await ws_manager.broadcast({"event": "task_created", "data": task_data})
    except Exception as e:
        logger.warning("DB sync failed: %s", e)
        
    # Stage 1: Observation agent detects crisis
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="ObservationAgent",
        stage="detect",
        thought=f"Anomaly detected in datastream. Extracted high-priority signal: {scenario}.",
        options=["Log warning", "Trigger escalation"],
        rejected=["Log warning (insufficient severity)"],
        constraints=["SLA < 5 mins"],
        confidence=0.99,
        outcome="Escalating to ContradictionEngine.",
        observations=[{"source": "ERP System API", "content": body}]
    )
    
    await asyncio.sleep(2.5)
    
    # Stage 2: Contradiction Engine
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="ContradictionEngine",
        stage="analyze",
        thought="Cross-referencing ERP datalakes with Logistics API. Contradiction detected: ERP status says 'Nominal Transit' but logistics signals confirm halted freight.",
        options=["Ignore API mismatch", "Invalidate ERP data in-memory"],
        rejected=["Ignore API mismatch (high risk of shipping delay)"],
        constraints=["Data consistency", "Auditable signals"],
        confidence=0.94,
        outcome="Contradiction confirmed. Relaying threat intelligence to PlannerAgent.",
        actions=[
            {"tool_name": "query_erp", "params": {"sku": "XYZ-all"}, "latency_ms": 340},
            {"tool_name": "query_logistics", "params": {"supplier": "XYZ"}, "latency_ms": 412}
        ]
    )
    
    await asyncio.sleep(3.0)
    
    # Stage 3: Planner Agent plans strategy
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="PlannerAgent",
        stage="plan",
        thought="Synthesizing multi-modal recovery strategy. Budget cap variance must remain below 15%. Alternate supplier delivery SLA must be under 48 hours.",
        options=["Supplier ABC (Fast, Expensive)", "Supplier DEF (Slow, Cheap)", "Split-order distribution"],
        rejected=["Supplier DEF (SLA violation - takes 5 days)"],
        constraints=["Must arrive in 48h", "Max +15% cost variance"],
        confidence=0.89,
        outcome="Strategy established: Source ABC immediately, trigger ERP update, queue executive notification."
    )
    
    # Update MD file to Awaiting Approval
    plan_text = "## AI Plan\n- [ ] Step 1: Query Supplier ABC for availability\n- [ ] Step 2: Issue PO to Supplier ABC\n- [ ] Step 3: Update ERP"
    frontmatter["status"] = "awaiting-approval"
    file_path.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n## Request\n\n{body}\n\n{plan_text}\n",
        encoding="utf-8"
    )
    
    try:
        db.sync_single_task(file_path)
        await ws_manager.broadcast({"event": "task_update", "data": db.get_task(task_id)})
    except Exception:
        pass
        
    await asyncio.sleep(3.0)
    
    # Stage 4: CEO Approval simulation
    frontmatter["status"] = "approved"
    file_path.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n## Request\n\n{body}\n\n{plan_text}\n",
        encoding="utf-8"
    )
    try:
        db.sync_single_task(file_path)
        await ws_manager.broadcast({"event": "task_update", "data": db.get_task(task_id)})
    except Exception:
        pass
        
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="CEO_Gateway",
        stage="approve",
        thought="Human approval received. Initiating transaction pipeline.",
        options=[],
        rejected=[],
        constraints=[],
        confidence=1.0,
        outcome="Execution authorized by administrator."
    )
    
    await asyncio.sleep(2.0)
    
    # Stage 5: Executor execution step 1 (Success)
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="ExecutorAgent",
        stage="execute",
        thought="Executing Step 1: Checking inventory with alternate Supplier ABC.",
        options=["REST API v2", "GraphQL endpoint"],
        rejected=["GraphQL (higher latency)"],
        constraints=[],
        confidence=0.96,
        outcome="Inventory verified. 10,000 units ready for loading.",
        actions=[{"tool_name": "supplier_api_check", "params": {"supplier": "ABC", "qty": 5000}, "latency_ms": 650}]
    )
    
    await asyncio.sleep(2.5)
    
    # Stage 6: Executor step 2 (FAILURE)
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="ExecutorAgent",
        stage="execute",
        thought="Executing Step 2: Issuing Purchase Order to Supplier ABC.",
        options=["Standard PO API", "Expedited priority channel"],
        rejected=["Standard channel (violates shipping SLA)"],
        constraints=["Strict financial authorization"],
        confidence=0.35,
        outcome="CRITICAL FAILURE: PO endpoint unreachable (HTTP 429 Rate Limit / Socket Timeout).",
        actions=[{"tool_name": "issue_po", "params": {"supplier": "ABC", "type": "expedited"}, "latency_ms": 2100, "success": False, "result": "HTTP 429 Too Many Requests"}]
    )
    
    frontmatter["status"] = "failed"
    file_path.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n## Request\n\n{body}\n\n{plan_text}\n\n## Failure\nHTTP 429 on PO issuance.\n",
        encoding="utf-8"
    )
    try:
        db.sync_single_task(file_path)
        await ws_manager.broadcast({"event": "task_update", "data": db.get_task(task_id)})
    except Exception:
        pass
        
    await asyncio.sleep(3.0)
    
    # Stage 7: Recovery Agent triggers fallback
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="RecoveryAgent",
        stage="recover",
        thought="Detected Executor failure (HTTP 429). Initiating healing protocol: switching from REST API to secure AS2/EDI fallback node.",
        options=["Re-try REST with backoff", "Switch to EDI fallback node", "Rollback transaction"],
        rejected=["Re-try REST (unpredictable latency)", "Rollback (violates downtime SLA)"],
        constraints=["Maintain PO serialization"],
        confidence=0.93,
        outcome="EDI node fallback selected. Re-routing execution pipeline."
    )
    
    await asyncio.sleep(3.0)
    
    # Stage 8: Re-execution via fallback (Success)
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="ExecutorAgent",
        stage="execute",
        thought="Re-executing Step 2 via AS2 protocol on EDI fallback channel.",
        options=["AS2 Protocol node", "SFTP batch transfer"],
        rejected=["SFTP batch (non-real-time)"],
        constraints=["EDI standards compliant"],
        confidence=0.98,
        outcome="PO transmitted and acknowledged via EDI fallback.",
        actions=[{"tool_name": "transmit_edi_po", "params": {"supplier": "ABC", "protocol": "AS2"}, "latency_ms": 1150}]
    )
    
    await asyncio.sleep(2.5)
    
    # Stage 9: Verification & CEO final reporting
    await _emit_demo_trace(
        task_id=task_id,
        agent_name="VerifierAgent",
        stage="verify",
        thought="Verifying completed execution chain against operational goals. Cost variance is +12% (within 15% tolerance). Delivery ETA is 24h (within 48h constraint).",
        options=["Complete task", "Flag for manual audit"],
        rejected=["Flag for manual audit (unnecessary overhead)"],
        constraints=["SLA target compliance"],
        confidence=1.0,
        outcome="Execution path fully compliant. Closing task with success state."
    )
    
    frontmatter["status"] = "completed"
    file_path.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n## Request\n\n{body}\n\n{plan_text}\n\n## Result\nRecovered via EDI fallback. PO Issued.\n",
        encoding="utf-8"
    )
    try:
        db.sync_single_task(file_path)
        await ws_manager.broadcast({"event": "task_update", "data": db.get_task(task_id)})
    except Exception:
        pass

@app.post("/demo/run", response_model=DemoResponse)
async def run_demo(req: DemoRequest, background_tasks: BackgroundTasks):
    """
    Run the ultimate cinematic demo pipeline showing real intelligence, 
    contradiction detection, and failure recovery.
    """
    now = datetime.utcnow()
    task_id = f"demo-{req.scenario}-{now.strftime('%Y%m%d-%H%M%S')}"
    
    background_tasks.add_task(execute_cinematic_demo, req.scenario, task_id)
    
    return DemoResponse(
        task_id=task_id,
        stages=[
            DemoStage(stage="initialize", status="success", detail="Cinematic simulation started"),
            DemoStage(stage="running", status="in_progress", detail="Background swarm active")
        ],
        final_status="running"
    )



# ── WebSocket ─────────────────────────────────────────────────────────────── #

async def _handle_websocket_common(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({
            "event": "connected",
            "message": "Enterprise AI Employee Platform — WebSocket connected",
            "timestamp": datetime.utcnow().isoformat(),
        })
        while True:
            data = await websocket.receive_text()
            # Echo ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@app.websocket("/ws/v2")
async def websocket_endpoint_v2(websocket: WebSocket):
    await _handle_websocket_common(websocket)

@app.websocket("/ws")
async def websocket_endpoint_v1(websocket: WebSocket):
    await _handle_websocket_common(websocket)


# ── Simple liveness probe (used by start_wabot.bat health loop) ───────────── #

@app.get("/health")
async def health_simple():
    """Lightweight liveness probe — always returns 200 immediately."""
    return {"status": "ok"}


# ── System Health ─────────────────────────────────────────────────────────── #

@app.get("/api/v2/health")
async def health():
    """
    System health status for all integrations.
    Returns the cached connection state — no live API calls.
    overall = 'healthy' only when every initialized integration is 'connected'.
    """
    integrations: Dict[str, str] = {}

    for name, agent_var in [
        ("gmail",    _gmail_agent),
        ("calendar", _calendar_agent),
        ("whatsapp", _whatsapp_agent),
        ("linkedin", _linkedin_agent),
    ]:
        if agent_var is None:
            integrations[name] = "offline"
        else:
            try:
                client = getattr(agent_var, "client", None)
                if client is None:
                    # LinkedIn client exposes is_connected directly
                    is_conn = getattr(agent_var, "_connected", False)
                    integrations[name] = "connected" if is_conn else "offline"
                else:
                    status_val = client.get_status().value
                    if status_val in ("requires_auth", "error") and not getattr(client, "_connected", False):
                        integrations[name] = "offline"
                    else:
                        integrations[name] = status_val
            except Exception:
                integrations[name] = "offline"

    # Expose auto-approve modes in health response
    auto_approve_modes = {
        "gmail": os.environ.get("AUTO_APPROVE_EMAILS", "false").lower() == "true",
        "whatsapp": os.environ.get("AUTO_APPROVE_WHATSAPP", "false").lower() == "true",
        "confidence_threshold": float(os.environ.get("CONFIDENCE_THRESHOLD", "0.80")),
    }

    # Cohere: presence-check the key via env (always works without vault passphrase)
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    if not cohere_key:
        try:
            from enterprise.credentials.manager import get_credential_manager
            cm = get_credential_manager()
            cohere_key = cm.get("COHERE_API_KEY") or ""
        except Exception:
            pass
    integrations["cohere"] = "connected" if cohere_key else "offline"

    initialized_statuses = [v for k, v in integrations.items() if v != "offline"]
    if not initialized_statuses:
        overall = "simulation"
    elif all(s == "connected" for s in initialized_statuses):
        overall = "healthy"
    elif any(s == "error" for s in initialized_statuses):
        overall = "error"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "version": "2.0.0-enterprise",
        "timestamp": datetime.utcnow().isoformat(),
        "integrations": integrations,
        "auto_approve": auto_approve_modes,
        "websocket_clients": len(ws_manager.active),
    }


@app.get("/api/v2/health/live")
async def health_live():
    """
    Live connectivity check — makes real API calls to each integration.
    Returns HTTP 200 when all connected, HTTP 503 when any are offline/errored.
    Used by the dashboard Production Mode banner.
    """
    from enterprise.credentials.startup_validator import ProductionStartupValidator
    validator = ProductionStartupValidator()

    results: Dict[str, Any] = {}
    all_ok = True

    # Cohere — live ping
    cohere_ok, cohere_msg = validator._validate_cohere_wrapper()
    results["cohere"] = {"status": "ok" if cohere_ok else "error", "detail": cohere_msg}
    if not cohere_ok:
        all_ok = False

    # Gmail — OAuth profile fetch
    gmail_ok, gmail_msg = validator.validate_gmail()
    results["gmail"] = {"status": "ok" if gmail_ok else "error", "detail": gmail_msg}
    if not gmail_ok:
        all_ok = False

    # Calendar — calendarList fetch
    cal_ok, cal_msg = validator.validate_calendar()
    results["calendar"] = {"status": "ok" if cal_ok else "error", "detail": cal_msg}
    if not cal_ok:
        all_ok = False

    # Twilio/WhatsApp — account fetch
    twilio_ok, twilio_msg = validator.validate_twilio()
    results["whatsapp"] = {"status": "ok" if twilio_ok else "error", "detail": twilio_msg}
    if not twilio_ok:
        all_ok = False

    payload = {
        "status": "ok" if all_ok else "error",
        "integrations": results,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if not all_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload


# ── Tasks ─────────────────────────────────────────────────────────────────── #

@app.post("/api/v2/tasks")
async def create_task(task: TaskCreate, background: BackgroundTasks):
    """Create a new task and run it through the 5-agent pipeline."""
    from enterprise.agents.base import EnterpriseTask
    enterprise_task = EnterpriseTask(
        task_id=str(uuid.uuid4()),
        title=task.title,
        description=task.description,
        source=task.source,
        priority=task.priority,
        requester=task.requester,
    )

    coordinator = get_coordinator()

    def run_pipeline():
        try:
            coordinator.run(enterprise_task)
        except Exception as e:
            logger.error("Pipeline error: %s", e)

    background.add_task(run_pipeline)

    return {
        "task_id": enterprise_task.task_id,
        "title": task.title,
        "status": "pipeline_started",
        "message": "Task created and sent through 5-agent pipeline",
    }


@app.get("/api/v2/tasks")
async def list_tasks():
    """List all tasks from vault and database."""
    try:
        from memory.database import TaskDatabase
        db = TaskDatabase()
        tasks = db.get_all_tasks()
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        return {"tasks": [], "count": 0, "error": str(e)}


# ── Unified Approval Queue ────────────────────────────────────────────────── #

@app.get("/api/v2/approvals")
async def list_approvals():
    """Get all pending approvals across all integrations."""
    approvals = []

    try:
        gmail = get_gmail_agent()
        approvals.extend(gmail.get_pending_approvals())
    except Exception:
        pass

    try:
        calendar = get_calendar_agent()
        approvals.extend(calendar.get_pending_proposals())
    except Exception:
        pass

    try:
        whatsapp = get_whatsapp_agent()
        approvals.extend(whatsapp.get_pending_approvals())
    except Exception:
        pass

    try:
        linkedin = get_linkedin_agent()
        approvals.extend(linkedin.get_pending_approvals())
    except Exception:
        pass

    try:
        assistant = get_smart_assistant()
        approvals.extend(assistant.get_pending_approvals())
    except Exception:
        pass

    try:
        coordinator = get_coordinator()
        approvals.extend([
            {**p, "type": "pipeline_approval"}
            for p in coordinator.get_pending_approvals()
        ])
    except Exception:
        pass

    return {
        "approvals": approvals,
        "count": len(approvals),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/v2/approvals/{approval_id}")
async def process_approval(approval_id: str, action: ApprovalAction):
    """Approve, reject, or edit any pending approval."""
    # Try each agent/coordinator
    agents_with_approval = []

    try:
        agents_with_approval.append(("gmail", get_gmail_agent()))
    except Exception:
        pass
    try:
        agents_with_approval.append(("calendar", get_calendar_agent()))
    except Exception:
        pass
    try:
        agents_with_approval.append(("whatsapp", get_whatsapp_agent()))
    except Exception:
        pass
    try:
        agents_with_approval.append(("linkedin", get_linkedin_agent()))
    except Exception:
        pass
    try:
        agents_with_approval.append(("assistant", get_smart_assistant()))
    except Exception:
        pass
    try:
        agents_with_approval.append(("pipeline", get_coordinator()))
    except Exception:
        pass

    for name, agent in agents_with_approval:
        try:
            if action.action == "approve":
                if name == "pipeline":
                    result = agent.approve(approval_id)
                    if result:
                        await ws_manager.broadcast({
                            "event": "approval_processed",
                            "id": approval_id,
                            "action": "approve",
                            "integration": name,
                        })
                        return {"status": "approved", "integration": name}
                elif action.edited_content and hasattr(agent, "edit_and_approve"):
                    success = agent.edit_and_approve(approval_id, action.edited_content)
                elif hasattr(agent, "approve_and_send"):
                    success = agent.approve_and_send(approval_id)
                elif hasattr(agent, "approve_and_publish"):
                    result_obj = agent.approve_and_publish(approval_id)
                    # approve_and_publish returns PostResult; extract bool
                    success = result_obj.success if hasattr(result_obj, "success") else bool(result_obj)
                elif hasattr(agent, "approve_and_create"):
                    success = agent.approve_and_create(approval_id)
                elif hasattr(agent, "approve_and_execute"):
                    success = agent.approve_and_execute(approval_id)
                else:
                    continue

                if success:
                    await ws_manager.broadcast({
                        "event": "approval_processed",
                        "id": approval_id,
                        "action": "approve",
                        "integration": name,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    return {"status": "approved", "integration": name}

            elif action.action == "reject":
                if hasattr(agent, "reject"):
                    success = agent.reject(approval_id)
                    if success:
                        await ws_manager.broadcast({
                            "event": "approval_processed",
                            "id": approval_id,
                            "action": "reject",
                            "integration": name,
                        })
                        return {"status": "rejected", "integration": name}

        except Exception as e:
            logger.debug("Approval try failed for %s: %s", name, e)
            continue

    raise HTTPException(status_code=404, detail=f"Approval not found: {approval_id}")


# ── Gmail ─────────────────────────────────────────────────────────────────── #

@app.get("/api/v2/gmail/unread")
async def gmail_list_unread(max_results: int = 20):
    """List unread Gmail messages."""
    agent = get_gmail_agent()
    messages = agent.client.list_unread(max_results)
    return {
        "messages": [
            {
                "id": m.id,
                "subject": m.subject,
                "from": m.sender,
                "from_email": m.sender_email,
                "snippet": m.snippet,
                "date": m.date,
                "is_unread": m.is_unread,
            }
            for m in messages
        ],
        "count": len(messages),
    }


@app.post("/api/v2/gmail/poll")
async def gmail_poll():
    """Trigger an immediate Gmail poll cycle."""
    agent = get_gmail_agent()
    tasks = agent.poll_once()

    auto_sent = [t for t in tasks if getattr(t, "auto_sent", False)]
    queued    = [t for t in tasks if not getattr(t, "auto_sent", False)]

    await ws_manager.broadcast({
        "event": "gmail_polled",
        "new_tasks": len(tasks),
        "auto_sent": len(auto_sent),
        "queued_for_approval": len(queued),
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {
        "new_tasks": len(tasks),
        "auto_sent": len(auto_sent),
        "queued_for_approval": len(queued),
        "task_ids": [t.task_id for t in tasks],
    }


@app.get("/api/v2/gmail/status")
async def gmail_status():
    agent = get_gmail_agent()
    stats = agent.get_stats() if hasattr(agent, "get_stats") else {}
    return {
        "status": agent.client.get_status().value,
        "email": getattr(agent.client, "_email_address", "unknown"),
        "pending_approvals": len(agent.get_pending_approvals()),
        "auto_approve_enabled": stats.get("auto_approve_enabled", False),
        "confidence_threshold": stats.get("confidence_threshold", 0.80),
        "stats": stats,
    }


@app.get("/api/v2/gmail/auth-url")
async def gmail_auth_url():
    """Generates a visual OAuth2 authorization consent URL for Gmail."""
    from enterprise.integrations.gmail.auth import GmailAuthFlow
    flow = GmailAuthFlow()
    client_id = flow.creds.require("GMAIL_CLIENT_ID", "Google OAuth2 Client ID")
    redirect_uri = flow.creds.get("GMAIL_REDIRECT_URI", "http://localhost:8000/api/v2/gmail/callback")
    url = flow._build_auth_url(client_id, redirect_uri)
    return {"auth_url": url}


@app.get("/api/v2/gmail/callback")
async def gmail_callback(code: str):
    """Google OAuth2 callback URL. Exchanges code for tokens and persists them."""
    from enterprise.integrations.gmail.auth import GmailAuthFlow
    from fastapi.responses import RedirectResponse
    flow = GmailAuthFlow()
    client_id = flow.creds.require("GMAIL_CLIENT_ID")
    client_secret = flow.creds.require("GMAIL_CLIENT_SECRET")
    redirect_uri = flow.creds.get("GMAIL_REDIRECT_URI", "http://localhost:8000/api/v2/gmail/callback")
    
    token = flow._exchange_code(code, client_id, client_secret, redirect_uri)
    flow.creds.store_oauth_token("GMAIL", token)
    flow.creds._write_token_file("GMAIL", token)
    
    # Broadcast to reload UI
    await ws_manager.broadcast({
        "event": "gmail_status_update",
        "status": "connected",
        "email": token.get("email", "connected"),
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    return RedirectResponse(url="http://localhost:3000/gmail?success=true")


@app.post("/api/v2/gmail/disconnect")
async def gmail_disconnect():
    """Disconnects and wipes the Gmail OAuth credentials."""
    from enterprise.integrations.gmail.auth import GmailAuthFlow
    from pathlib import Path
    flow = GmailAuthFlow()
    flow.creds.delete_oauth_token("GMAIL")
    
    token_path = Path(".credentials/gmail_token.json")
    if token_path.exists():
        try:
            token_path.unlink()
        except Exception:
            pass
            
    await ws_manager.broadcast({
        "event": "gmail_status_update",
        "status": "disconnected",
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {"status": "ok"}



# ── Google Calendar ───────────────────────────────────────────────────────── #

@app.post("/api/v2/calendar/schedule")
async def schedule_meeting(req: CalendarEventRequest):
    """Parse natural language and propose a calendar event."""
    agent = get_calendar_agent()
    proposal = agent.propose_meeting(req.natural_language)
    if not proposal:
        raise HTTPException(status_code=422, detail="Could not parse meeting request")
    return {
        "proposal_id": proposal.proposal_id,
        "title": proposal.title,
        "attendees": proposal.attendees,
        "start": proposal.start,
        "end": proposal.end,
        "status": proposal.status,
    }


@app.get("/api/v2/calendar/upcoming")
async def calendar_upcoming(max_results: int = 10):
    agent = get_calendar_agent()
    events = agent.client.list_upcoming(max_results)
    return {
        "events": [e.__dict__ for e in events],
        "count": len(events),
    }


# ── WhatsApp ──────────────────────────────────────────────────────────────── #

@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook.
    POST URL: https://<your-ngrok>.ngrok-free.app/webhooks/whatsapp

    IMPORTANT: Always returns HTTP 200 with valid TwiML containing a <Message>.
    Twilio Sandbox shows its default fallback when it receives empty TwiML —
    so we NEVER return <Response></Response>. The reply is delivered via TwiML
    only (not REST API) to avoid duplicate messages.
    """
    # ── 1. Parse form data safely ─────────────────────────────────────── #
    try:
        form_data = dict(await request.form())
    except Exception as exc:
        logger.error("[WhatsApp WEBHOOK] Failed to parse form data: %s", exc)
        form_data = {}

    sender  = form_data.get("From", "unknown").strip()
    body    = form_data.get("Body", "").strip()
    msg_sid = form_data.get("MessageSid", "")

    print(f"[WhatsApp WEBHOOK] From={sender!r} Body={body!r} SID={msg_sid}")
    logger.info("[WhatsApp WEBHOOK] From=%s Body=%r SID=%s", sender, body[:100], msg_sid)

    reply_text: Optional[str] = None

    # ── 1b. CRM pipeline + Sales flow — fire-and-forget ─────────────── #
    if body and sender != "unknown":
        async def _run_crm_and_sales_bg():
            try:
                phone = sender.replace("whatsapp:", "").strip()

                # Check if this number is in an active sales conversion flow
                try:
                    from enterprise.sales.whatsapp_conversion_flow import get_whatsapp_flow
                    flow = get_whatsapp_flow()
                    if flow.is_sales_lead(phone):
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            flow.handle_whatsapp_message,
                            body, phone,
                        )
                        return  # Sales flow handled it — skip generic CRM scoring
                except Exception as _flow_exc:
                    logger.debug("[WhatsApp WEBHOOK] Sales flow skipped: %s", _flow_exc)

                # Standard CRM intent scoring
                from enterprise.crm.pipeline import SalesPipeline
                pipeline = SalesPipeline()
                await asyncio.get_event_loop().run_in_executor(
                    None, pipeline.process_message, body, phone, "", "", "whatsapp"
                )
            except Exception as _bg_exc:
                logger.debug("[WhatsApp WEBHOOK] CRM/sales bg task failed: %s", _bg_exc)
        asyncio.ensure_future(_run_crm_and_sales_bg())

    # ── 2. Generate AI reply (sync call offloaded to thread) ──────────── #
    try:
        agent = get_whatsapp_agent()
        msg_obj = agent.client.parse_webhook(form_data)

        if msg_obj and body:
            user_id = form_data.get("AccountSid", "default")[:16]

            from enterprise.integrations.whatsapp.db import get_chat_meta, get_ai_settings
            chat_meta   = await get_chat_meta(user_id, sender)
            ai_settings = await get_ai_settings(user_id)

            # Emit IN event to dashboard
            await _wa_emit({
                "type": "IN", "source": "twilio",
                "from": sender, "to": form_data.get("To", ""),
                "message": body, "status": "received", "sid": msg_sid,
            }, user_id=user_id)

            skip_ai = (
                chat_meta.get("blocked", False)
                or chat_meta.get("muted", False)
                or not chat_meta.get("ai_enabled", True)
                or not ai_settings.get("ai_enabled", True)
            )

            if not skip_ai:
                # _generate_reply calls Cohere (blocking I/O) — run in thread
                # so we don't block the FastAPI event loop.
                history = agent._conversation_history.get(sender, [])
                history.append({"role": "user", "content": body,
                                 "timestamp": datetime.utcnow().isoformat()})
                loop = asyncio.get_event_loop()
                reply_text = await loop.run_in_executor(
                    None, agent._generate_reply, msg_obj, history
                )
                if reply_text:
                    history.append({"role": "assistant", "content": reply_text,
                                    "timestamp": datetime.utcnow().isoformat()})
                    agent._conversation_history[sender] = history[-12:]

    except HTTPException as exc:
        logger.warning("[WhatsApp WEBHOOK] Agent unavailable: %s", exc.detail)
    except Exception as exc:
        logger.error("[WhatsApp WEBHOOK] Unhandled error: %s", exc, exc_info=True)

    # ── 3. Guarantee a non-empty reply ────────────────────────────────── #
    if not reply_text:
        reply_text = f"Samajh gaya: {body}" if body else "Main aapki baat sun raha hoon."

    logger.info("[WhatsApp WEBHOOK] Reply → %r", reply_text[:120])

    # ── 4. Build TwiML — wrapped so ANY crash still returns 200 ──────── #
    try:
        twiml_resp = MessagingResponse()
        twiml_resp.message(reply_text)
        return Response(
            content=str(twiml_resp),
            media_type="application/xml",
            status_code=200,
        )
    except Exception as twiml_exc:
        logger.error("[WhatsApp WEBHOOK] TwiML build failed: %s", twiml_exc)
        # Raw XML fallback — Twilio always gets 200
        safe = reply_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Response(
            content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{safe}</Message></Response>",
            media_type="application/xml",
            status_code=200,
        )


@app.post("/api/v2/whatsapp/send")
async def whatsapp_send(req: WhatsAppSendRequest):
    """Send a WhatsApp message immediately via Twilio REST API."""
    # Normalise number to E.164.  Strip leading zeros then prepend '+'.
    # e.g. 03140332320 → +3140332320  (caller must supply country code)
    # e.g. whatsapp:+923140332320 → kept as-is after the prefix is stripped
    to = req.to.strip()
    if to.startswith("whatsapp:"):
        to = to[len("whatsapp:"):]
    # Remove all spaces/dashes for cleanliness
    to = to.replace(" ", "").replace("-", "")
    if not to.startswith("+"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid phone number '{req.to}'. "
                "Use E.164 format with country code, e.g. +923140332320"
            ),
        )

    agent = get_whatsapp_agent()
    result = agent.client.send_message(to=to, body=req.message)
    if result.success:
        await _wa_emit({
            "type": "OUT",
            "source": "twilio",
            "from": "manual",
            "to": to,
            "message": req.message,
            "status": "sent",
            "sid": result.data.get("sid"),
        })
        return {"status": "sent", "sid": result.data.get("sid"), "to": to}
    await _wa_emit({
        "type": "ERROR",
        "source": "twilio",
        "from": "manual",
        "to": to,
        "message": req.message,
        "status": "failed",
        "error": result.error,
    })
    raise HTTPException(status_code=500, detail=result.error)


@app.get("/api/v2/whatsapp/status")
async def whatsapp_status():
    agent = get_whatsapp_agent()
    return {
        "status": agent.client.get_status().value,
        "pending_approvals": len(agent.get_pending_approvals()),
    }


@app.post("/api/v2/whatsapp/test")
async def whatsapp_test():
    """
    Send a test WhatsApp message to the configured WHATSAPP_TO number.
    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, and WHATSAPP_TO.
    Sends directly (no approval gate) — for connectivity verification only.
    """
    try:
        from enterprise.credentials.manager import get_credential_manager
        creds = get_credential_manager()

        account_sid = creds.get("TWILIO_ACCOUNT_SID") or os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = creds.get("TWILIO_AUTH_TOKEN")  or os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = creds.get("TWILIO_WHATSAPP_FROM") or os.environ.get("TWILIO_WHATSAPP_FROM")
        to_number   = creds.get("WHATSAPP_TO") or os.environ.get("WHATSAPP_TO")

        missing = [k for k, v in {
            "TWILIO_ACCOUNT_SID": account_sid,
            "TWILIO_AUTH_TOKEN": auth_token,
            "TWILIO_WHATSAPP_FROM": from_number,
            "WHATSAPP_TO": to_number,
        }.items() if not v]

        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing credentials: {', '.join(missing)}. "
                       f"Set them via: python -m enterprise.credentials.cli",
            )

        from twilio.rest import Client as TwilioClient
        client = TwilioClient(account_sid, auth_token)
        message = client.messages.create(
            from_=from_number,
            to=to_number,
            body="[AI Employee] WhatsApp test message — connection verified.",
        )

        return {
            "status": "sent",
            "sid": message.sid,
            "to": to_number,
            "from": from_number,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WhatsApp test failed: {e}")


# ── WhatsApp Monitoring Endpoints ────────────────────────────────────────── #

@app.get("/api/v2/whatsapp/logs")
async def whatsapp_logs(
    limit: int = 50,
    page: int = 1,
    type: Optional[str] = None,       # IN | OUT | AI | ERROR
    source: Optional[str] = None,     # web | twilio
    user_id: str = "default",
):
    """
    Paginated WA event log.
    Falls back to the in-memory cache when MongoDB is unavailable.
    """
    from enterprise.integrations.whatsapp.db import fetch_events_page
    db_result = await fetch_events_page(user_id, page, limit, type, source)

    # If DB returned results, use them
    if db_result["total"] > 0:
        return db_result

    # Fallback: serve from in-memory ring buffer
    evts = [e for e in _wa_events if e.get("user_id", "default") == user_id]
    if type:
        evts = [e for e in evts if e.get("type") == type]
    if source:
        evts = [e for e in evts if e.get("source") == source]
    total = len(evts)
    start = (page - 1) * limit
    page_evts = list(reversed(evts))[start: start + limit]
    return {"events": page_evts, "total": total, "page": page, "limit": limit}


@app.get("/api/v2/whatsapp/chats")
async def whatsapp_chats(user_id: str = "default"):
    """
    Group WA events by contact, merged with DB chat metadata (tags, mute, etc.).
    """
    from enterprise.integrations.whatsapp.db import list_chat_metas
    skip = {"AI Agent", "manual", "ai", "bot", "fallback_queue", "fallback", ""}

    # Build contact map from in-memory cache
    chats: Dict[str, Dict] = {}
    for evt in _wa_events:
        if evt.get("user_id", "default") != user_id:
            continue
        if evt.get("type") not in ("IN", "OUT", "AI"):
            continue
        contact = evt.get("from") if evt.get("type") == "IN" else evt.get("to", "")
        if not contact or contact in skip:
            continue
        if contact not in chats:
            chats[contact] = {
                "contact": contact,
                "display_name": evt.get("sender_name", contact),
                "messages": [],
                "last_activity": evt.get("timestamp", ""),
                "unread": 0,
                "source": evt.get("source", "twilio"),
            }
        chats[contact]["messages"].append(evt)
        chats[contact]["last_activity"] = evt.get("timestamp", "")
        if evt.get("type") == "IN":
            chats[contact]["unread"] += 1

    # Merge DB metadata (tags, muted, blocked, ai_enabled)
    db_metas = {m["contact_id"]: m for m in await list_chat_metas(user_id)}
    result = []
    for cid, chat in chats.items():
        meta = db_metas.get(cid, {})
        result.append({**chat, **{k: meta[k] for k in ("tags", "muted", "blocked", "ai_enabled", "notes", "display_name") if k in meta}})

    result.sort(key=lambda c: c.get("last_activity") or "", reverse=True)
    return {"chats": result}


@app.post("/api/v2/whatsapp/events")
async def receive_wa_event(request: Request):
    """Receive events from the WhatsApp Web (Node.js) bot."""
    try:
        payload = await request.json()
        await _wa_emit({**payload, "source": payload.get("source", "web")})
        return {"ok": True}
    except Exception as exc:
        logger.warning("[WA-EVENTS] Bad payload: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── WhatsApp QR / Connection Endpoints ───────────────────────────────────── #

class QRUpdateRequest(BaseModel):
    status:     str                    # qr_ready | connected | disconnected | auth_failure
    qr_image:   Optional[str] = None  # base64 PNG data URL
    qr_string:  Optional[str] = None  # raw QR string
    phone:      Optional[str] = None  # connected phone number
    clientId:   Optional[str] = "wa-ai-bot"
    label:      Optional[str] = None


@app.post("/api/v2/whatsapp/qr-update")
async def wa_qr_update(req: QRUpdateRequest):
    """Called by the Node.js bot to push QR code / connection status changes."""
    global _wa_accounts, _wa_qr_state
    client_id = req.clientId or "wa-ai-bot"
    
    if client_id not in _wa_accounts:
        _wa_accounts[client_id] = {
            "clientId": client_id,
            "label": req.label or f"WhatsApp {client_id.replace('client-', '')}",
            "status": "disconnected",
            "qr_image": None,
            "qr_string": None,
            "phone": None,
            "updated_at": None,
        }

    _wa_accounts[client_id].update({
        "status":     req.status,
        "qr_image":   req.qr_image,
        "qr_string":  req.qr_string,
        "phone":      req.phone,
        "updated_at": datetime.utcnow().isoformat(),
    })
    
    if req.label:
        _wa_accounts[client_id]["label"] = req.label

    # Backwards compatibility for single-client endpoints
    if client_id == "wa-ai-bot":
        _wa_qr_state.update(_wa_accounts[client_id])

    logger.info("[WA-QR] Client %s status → %s | phone=%s", client_id, req.status, req.phone)
    
    # Broadcast to dashboard in real-time
    await ws_manager.broadcast({
        "event":      "wa_accounts_update",
        "accounts":   list(_wa_accounts.values()),
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"ok": True}


@app.get("/api/v2/whatsapp/qr")
async def wa_qr_get():
    """Return current WhatsApp connection state + QR image for backward compatibility."""
    return {
        "status":     _wa_qr_state["status"],
        "qr_image":   _wa_qr_state.get("qr_image"),
        "phone":      _wa_qr_state.get("phone"),
        "updated_at": _wa_qr_state.get("updated_at"),
    }


@app.get("/api/v2/whatsapp/accounts")
async def wa_accounts_list():
    """List all configured/connected WhatsApp accounts."""
    global _wa_accounts
    return {
        "accounts": list(_wa_accounts.values()),
        "count": len(_wa_accounts),
    }


class CreateAccountRequest(BaseModel):
    label: Optional[str] = None


@app.post("/api/v2/whatsapp/accounts/create")
async def wa_account_create(req: CreateAccountRequest):
    """Dynamically register a new WhatsApp account session and spawn it via queue."""
    global _wa_accounts
    client_id = f"client-{int(datetime.utcnow().timestamp())}"
    
    _wa_accounts[client_id] = {
        "clientId": client_id,
        "label": req.label or f"Account {client_id.replace('client-', '')}",
        "status": "disconnected",
        "qr_image": None,
        "qr_string": None,
        "phone": None,
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    cmd_id = f"cmd-{int(datetime.utcnow().timestamp())}"
    cmd = {
        "id": cmd_id,
        "type": "CREATE_CLIENT",
        "clientId": client_id,
        "label": _wa_accounts[client_id]["label"],
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    
    # Push CREATE_CLIENT to queue
    _web_send_queue[cmd_id] = cmd
    
    await ws_manager.broadcast({
        "event": "wa_accounts_update",
        "accounts": list(_wa_accounts.values()),
        "updated_at": datetime.utcnow().isoformat(),
    })
    
    return {"status": "ok", "clientId": client_id}


@app.delete("/api/v2/whatsapp/accounts/{client_id}")
async def wa_account_delete(client_id: str):
    """Delete a WhatsApp account session and destroy client instance via queue."""
    global _wa_accounts
    if client_id in _wa_accounts:
        del _wa_accounts[client_id]
        
    cmd_id = f"cmd-{int(datetime.utcnow().timestamp())}"
    cmd = {
        "id": cmd_id,
        "type": "DELETE_CLIENT",
        "clientId": client_id,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    
    # Push DELETE_CLIENT to queue
    _web_send_queue[cmd_id] = cmd
    
    await ws_manager.broadcast({
        "event": "wa_accounts_update",
        "accounts": list(_wa_accounts.values()),
        "updated_at": datetime.utcnow().isoformat(),
    })
    
    return {"status": "ok"}



# ── Chat Metadata Endpoints ───────────────────────────────────────────────── #

class ChatMetaUpdate(BaseModel):
    display_name: Optional[str] = None
    tags: Optional[List[str]] = None
    muted: Optional[bool] = None
    blocked: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    notes: Optional[str] = None


@app.get("/api/v2/whatsapp/chats/{contact_id:path}")
async def get_chat(contact_id: str, user_id: str = "default"):
    from enterprise.integrations.whatsapp.db import get_chat_meta
    return await get_chat_meta(user_id, contact_id)


@app.put("/api/v2/whatsapp/chats/{contact_id:path}")
async def update_chat(contact_id: str, body: ChatMetaUpdate, user_id: str = "default"):
    from enterprise.integrations.whatsapp.db import upsert_chat_meta
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await upsert_chat_meta(user_id, contact_id, updates)
    await ws_manager.broadcast({
        "event": "wa_chat_updated",
        "contact": contact_id,
        "updates": updates,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return result


@app.get("/api/v2/whatsapp/chats/{contact_id:path}/export")
async def export_chat(contact_id: str, format: str = "json", user_id: str = "default"):
    """Export a contact's full chat history as JSON or CSV."""
    from enterprise.integrations.whatsapp.db import get_contact_events
    from fastapi.responses import StreamingResponse
    import io, csv as csv_mod

    evts = await get_contact_events(user_id, contact_id)

    # Fallback to in-memory if DB empty
    if not evts:
        evts = [
            e for e in _wa_events
            if e.get("from") == contact_id or e.get("to") == contact_id
        ]

    if format == "csv":
        fields = ["timestamp", "type", "source", "from", "to", "message", "status", "sid"]
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(evts)
        buf.seek(0)
        fname = f"chat_{contact_id.replace('whatsapp:', '').replace(':', '_')}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # JSON
    return JSONResponse(content={"contact": contact_id, "events": evts, "count": len(evts)})


# ── AI Settings Endpoints ─────────────────────────────────────────────────── #

class AISettingsUpdate(BaseModel):
    ai_model: Optional[str] = None       # "cohere" | "openai"
    temperature: Optional[float] = None  # 0.0 – 1.0
    system_prompt: Optional[str] = None
    ai_enabled: Optional[bool] = None


@app.get("/api/v2/whatsapp/settings")
async def get_settings(user_id: str = "default"):
    from enterprise.integrations.whatsapp.db import get_ai_settings
    return await get_ai_settings(user_id)


@app.put("/api/v2/whatsapp/settings")
async def update_settings(body: AISettingsUpdate, user_id: str = "default"):
    from enterprise.integrations.whatsapp.db import update_ai_settings
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await update_ai_settings(user_id, updates)
    await ws_manager.broadcast({
        "event": "wa_settings_updated",
        "updates": updates,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return result


# ── Smart Send (with Twilio → Web fallback) ───────────────────────────────── #

class SmartSendRequest(BaseModel):
    to: str
    message: str
    user_id: str = "default"


@app.post("/api/v2/whatsapp/send-smart")
async def whatsapp_send_smart(req: SmartSendRequest):
    """Send via Twilio, automatically fall back to WhatsApp Web bot on failure."""
    to = req.to.strip().replace(" ", "").replace("-", "")
    if to.startswith("whatsapp:"):
        to = to[len("whatsapp:"):]
    if not to.startswith("+"):
        raise HTTPException(status_code=400, detail=f"Invalid E.164 number: {req.to}")
    result = await _send_with_fallback(to, req.message, req.user_id)
    return result


# ── WhatsApp Web Bot Queue (fallback channel) ─────────────────────────────── #

@app.get("/api/v2/whatsapp/web-queue")
async def get_web_queue():
    """Node.js bot polls this to pick up queued outbound messages."""
    if _REDIS_AVAILABLE:
        items = await get_queue().pop_batch(max_items=10)
        return {"items": items, "count": len(items)}
    # In-memory fallback
    pending = [v for v in _web_send_queue.values() if v.get("status") == "pending"]
    return {"items": pending, "count": len(pending)}


@app.post("/api/v2/whatsapp/web-queue/{queue_id}/done")
async def queue_done(queue_id: str, request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    to      = body.get("to", "")
    message = body.get("message", "")

    if _REDIS_AVAILABLE:
        await get_queue().ack(queue_id)
    elif queue_id in _web_send_queue:
        item = _web_send_queue[queue_id]
        _web_send_queue[queue_id]["status"] = "sent"
        to      = item.get("to", "")
        message = item.get("message", "")

    await _wa_emit({
        "type": "OUT", "source": "web",
        "from": "web_bot", "to": to,
        "message": message, "status": "sent", "queue_id": queue_id,
    })
    return {"ok": True}


@app.post("/api/v2/whatsapp/web-queue/{queue_id}/failed")
async def queue_failed(queue_id: str, request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    error = body.get("error", "Web bot could not deliver message")

    if _REDIS_AVAILABLE:
        # Find item details before nacking
        pass  # nack handled below
    elif queue_id in _web_send_queue:
        _web_send_queue[queue_id]["status"] = "failed"

    await _wa_emit({
        "type": "ERROR", "source": "web",
        "from": "web_bot", "to": body.get("to", ""),
        "message": body.get("message", ""),
        "status": "failed", "error": error, "queue_id": queue_id,
    })
    return {"ok": True}


@app.get("/api/v2/whatsapp/queue/stats")
async def queue_stats():
    """Redis queue depth + DLQ stats."""
    if not _REDIS_AVAILABLE:
        in_mem = sum(1 for v in _web_send_queue.values() if v.get("status") == "pending")
        return {"queue_depth": in_mem, "dlq_depth": 0, "backend": "in-memory"}
    q = get_queue()
    return {
        "queue_depth": await q.depth(),
        "dlq_depth":   await q.dlq_depth(),
        "backend":     "redis",
    }


@app.post("/api/v2/whatsapp/queue/retry-dlq")
async def retry_dlq():
    """Move all DLQ messages back to the main queue."""
    if not _REDIS_AVAILABLE:
        return {"moved": 0, "backend": "in-memory"}
    count = await get_queue().retry_dlq()
    return {"moved": count, "backend": "redis"}


# ── Twilio Delivery Status Callback ──────────────────────────────────────── #

@app.post("/webhooks/whatsapp/status")
async def whatsapp_delivery_status(request: Request):
    """
    Twilio calls this URL when a message status changes (sent → delivered → read).
    Configure in Twilio console: Status Callback URL = <server>/webhooks/whatsapp/status
    """
    form = dict(await request.form())
    sid    = form.get("MessageSid", "")
    status = form.get("MessageStatus", "")

    if sid and status:
        # Update MongoDB
        from enterprise.integrations.whatsapp.db import update_event_status
        await update_event_status(sid, status)

        # Update in-memory cache
        for evt in _wa_events:
            if evt.get("sid") == sid:
                evt["status"] = status

        # Broadcast status update to dashboard
        await ws_manager.broadcast({
            "event": "wa_delivery_status",
            "sid": sid,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        })

    return JSONResponse(content="", status_code=204)


# ── WhatsApp Web (whatsapp-web.js) AI Reply Endpoint ─────────────────────── #

class WAWebReplyRequest(BaseModel):
    message:   str
    from_:     str = Field("", alias="from")
    sender:    str = ""                       # display name
    is_group:  bool = False
    chat_name: str = ""
    history:   list[dict] = Field(default_factory=list)  # prior turns for context

    class Config:
        populate_by_name = True


@app.post("/api/v2/whatsapp/ai-reply")
async def whatsapp_ai_reply(req: WAWebReplyRequest):
    """
    Called by the whatsapp-web.js Node.js bot for every incoming message.

    Flow:
      Node.js bot  →  POST here with {message, from, sender, is_group, chat_name, history}
      →  Cohere generates conversational reply  (falls back to local logic)
      →  returns {"reply": "...", "model": "..."}
      →  Node.js sends reply back to the WhatsApp chat

    Always returns HTTP 200 with a usable reply string.
    """
    body      = (req.message or "").strip()
    sender_id = req.from_ or "unknown"
    name      = req.sender or sender_id
    is_group  = req.is_group
    chat_name = req.chat_name or name

    logger.info(
        "[WA-WEB INCOMING] From=%s Chat=%r Group=%s Body=%r",
        name, chat_name, is_group, body[:120],
    )

    if not body:
        return {"reply": "", "model": "none"}

    user_id = "default"  # web bot is single-user for now

    # Gate: check AI + chat settings before generating
    from enterprise.integrations.whatsapp.db import get_chat_meta, get_ai_settings
    chat_meta  = await get_chat_meta(user_id, sender_id)
    ai_settings = await get_ai_settings(user_id)

    # Emit IN event for incoming web bot message
    await _wa_emit({
        "type": "IN", "source": "web",
        "from": sender_id, "to": "bot",
        "message": body, "status": "received",
        "sender_name": name, "chat_name": chat_name, "is_group": is_group,
    }, user_id=user_id)

    # Update contact memory asynchronously
    try:
        from enterprise.memory.contact_memory import auto_update_from_message
        asyncio.ensure_future(auto_update_from_message(user_id, sender_id, body, name))
    except Exception:
        pass

    # Skip AI reply when blocked / AI disabled
    skip_ai = (
        chat_meta.get("blocked", False)
        or chat_meta.get("muted", False)
        or not chat_meta.get("ai_enabled", True)
        or not ai_settings.get("ai_enabled", True)
    )
    if skip_ai:
        return {"reply": "", "model": "none"}

    # Fetch contact memory to enrich the system prompt
    contact_memory_fragment = ""
    try:
        from enterprise.memory.contact_memory import get_memory_for_contact
        mem = await get_memory_for_contact(user_id, sender_id)
        contact_memory_fragment = mem.to_prompt_fragment()
    except Exception:
        pass

    base_prompt = ai_settings.get("system_prompt")
    enriched_prompt = f"{contact_memory_fragment}\n\n{base_prompt}" if contact_memory_fragment and base_prompt else (contact_memory_fragment or base_prompt)

    # Check quota before generating
    if _BILLING_AVAILABLE:
        try:
            from enterprise.integrations.whatsapp.db import get_user_by_id
            user = await get_user_by_id(user_id)
            if user and not check_quota(user.get("plan", "free"), user.get("usage", {}), "ai_calls"):
                logger.warning("[QUOTA] User %s exceeded AI quota", user_id)
                return {"reply": "", "model": "quota_exceeded"}
        except Exception:
            pass

    reply = await _wa_web_generate_reply(
        body, sender_id, name, chat_name, is_group, req.history,
        temperature=ai_settings.get("temperature", 0.75),
        system_prompt=enriched_prompt,
        ai_model=ai_settings.get("ai_model", "cohere"),
    )
    logger.info("[WA-WEB REPLY] To=%s Reply=%r", name, reply[:120])

    if reply:
        await _wa_emit({
            "type": "AI", "source": "web",
            "from": "AI Agent", "to": sender_id,
            "message": reply, "status": "generated",
            "sender_name": name,
        }, user_id=user_id)

        # Track usage
        try:
            from enterprise.integrations.whatsapp.db import increment_usage
            asyncio.ensure_future(increment_usage(user_id, ai_calls=1))
        except Exception:
            pass

    return {"reply": reply, "model": ai_settings.get("ai_model", "cohere")}


async def _wa_web_generate_reply(
    body: str,
    sender_id: str,
    name: str,
    chat_name: str,
    is_group: bool,
    history: list,
    temperature: float = 0.75,
    system_prompt: Optional[str] = None,
    ai_model: str = "cohere",
) -> str:
    """Generate AI reply using configured model; local fallback on any failure."""
    try:
        from enterprise.credentials.manager import get_credential_manager
        creds = get_credential_manager()

        if ai_model == "openai":
            api_key = creds.get("OPENAI_API_KEY")
            if api_key:
                reply = await asyncio.get_event_loop().run_in_executor(
                    None, _openai_reply_sync,
                    api_key, body, name, chat_name, is_group, history, temperature, system_prompt
                )
                if reply:
                    return reply

        # Default: Cohere
        api_key = creds.get("COHERE_API_KEY")
        if api_key:
            reply = await asyncio.get_event_loop().run_in_executor(
                None, _cohere_reply_sync,
                api_key, body, name, chat_name, is_group, history, temperature, system_prompt
            )
            if reply:
                return reply
    except Exception as exc:
        logger.warning("[WA-WEB] AI call failed (%s) — using local fallback", exc)

    return _wa_web_local_reply(body)


def _cohere_reply_sync(
    api_key: str,
    body: str,
    name: str,
    chat_name: str,
    is_group: bool,
    history: list,
    temperature: float = 0.75,
    system_prompt: Optional[str] = None,
) -> str:
    """Blocking Cohere call with conversation history — run in executor."""
    import cohere
    from enterprise.integrations.whatsapp.db import DEFAULT_AI_SETTINGS

    context_tag = f"[Group: {chat_name}]" if is_group else f"[DM from: {name}]"
    prompt = system_prompt or DEFAULT_AI_SETTINGS["system_prompt"]

    messages: list[dict] = [{"role": "system", "content": prompt}]
    for turn in (history or [])[:-1]:
        role = turn.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": turn["content"]})
    messages.append({"role": "user", "content": f"{context_tag}\n{body}"})

    co = cohere.ClientV2(api_key)
    response = co.chat(
        model="command-a-03-2025",
        messages=messages,
        max_tokens=200,
        temperature=temperature,
    )
    return response.message.content[0].text.strip()


def _openai_reply_sync(
    api_key: str,
    body: str,
    name: str,
    chat_name: str,
    is_group: bool,
    history: list,
    temperature: float = 0.75,
    system_prompt: Optional[str] = None,
) -> str:
    """Blocking OpenAI call — run in executor."""
    try:
        import openai  # type: ignore
        from enterprise.integrations.whatsapp.db import DEFAULT_AI_SETTINGS

        client = openai.OpenAI(api_key=api_key)
        context_tag = f"[Group: {chat_name}]" if is_group else f"[DM from: {name}]"
        prompt = system_prompt or DEFAULT_AI_SETTINGS["system_prompt"]

        messages: list[dict] = [{"role": "system", "content": prompt}]
        for turn in (history or [])[:-1]:
            role = turn.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": turn["content"]})
        messages.append({"role": "user", "content": f"{context_tag}\n{body}"})

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,  # type: ignore
            max_tokens=200,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("[OpenAI] Call failed: %s", exc)
        return ""


def _wa_web_local_reply(body: str) -> str:
    """Instant local fallback — always returns a usable string."""
    b = body.lower()

    if any(w in b for w in ("hi", "hello", "hey", "salam", "hola", "greetings")):
        return "Hello! How can I help you today?"

    if any(w in b for w in ("thanks", "thank you", "shukran", "jazakallah")):
        return "You're welcome! Anything else I can help with?"

    if any(w in b for w in ("bye", "goodbye", "later", "cya", "ttyl")):
        return "Take care! Feel free to message anytime."

    if any(w in b for w in ("help", "support", "issue", "problem")):
        return "I'm here to help! Could you share more details?"

    if any(w in b for w in ("price", "cost", "how much", "rate")):
        return "Happy to help with pricing. Could you share more about what you need?"

    if "?" in body:
        return "Great question! Let me look into that and get back to you shortly."

    return "Got your message! I'll get back to you shortly."


# ── Auth Endpoints ───────────────────────────────────────────────────────── #

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/api/v2/auth/register")
async def auth_register(req: RegisterRequest):
    """Create a new user account and return JWT tokens."""
    if not _AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth module unavailable")
    from enterprise.integrations.whatsapp.db import create_user, get_user_by_email
    import pymongo.errors  # type: ignore

    existing = await get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())[:16]
    hashed  = hash_password(req.password)

    try:
        user = await create_user(
            user_id=user_id,
            email=req.email,
            hashed_password=hashed,
            name=req.name,
            plan="free",
        )
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "E11000" in str(exc):
            raise HTTPException(status_code=409, detail="Email already registered")
        raise HTTPException(status_code=500, detail=f"Registration failed: {exc}")

    claims = {"user_id": user_id, "email": req.email, "plan": "free"}
    return {
        "access_token":  create_access_token(claims),
        "refresh_token": create_refresh_token(claims),
        "token_type":    "bearer",
        "user": {k: user.get(k) for k in ("user_id", "email", "name", "plan")},
    }


@app.post("/api/v2/auth/login")
async def auth_login(req: LoginRequest):
    """Authenticate user and return JWT tokens."""
    if not _AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth module unavailable")
    from enterprise.integrations.whatsapp.db import get_user_by_email, update_user

    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    await update_user(user["user_id"], {"last_login": datetime.utcnow().isoformat()})

    claims = {"user_id": user["user_id"], "email": user["email"], "plan": user.get("plan", "free")}
    return {
        "access_token":  create_access_token(claims),
        "refresh_token": create_refresh_token(claims),
        "token_type":    "bearer",
        "user": {k: user.get(k) for k in ("user_id", "email", "name", "plan")},
    }


@app.post("/api/v2/auth/refresh")
async def auth_refresh(req: RefreshRequest):
    """Issue a new access token from a valid refresh token."""
    if not _AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth module unavailable")
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    claims = {k: payload[k] for k in ("user_id", "email", "plan") if k in payload}
    return {
        "access_token": create_access_token(claims),
        "token_type":   "bearer",
    }


@app.get("/api/v2/auth/me")
async def auth_me(current_user: "UserClaims" = Depends(get_current_user)):
    """Return current user profile."""
    from enterprise.integrations.whatsapp.db import get_user_by_id
    user = await get_user_by_id(current_user.user_id)
    if not user:
        # Fallback for no-MongoDB mode
        return {
            "user_id": current_user.user_id,
            "email":   current_user.email,
            "plan":    current_user.plan,
        }
    return {k: user.get(k) for k in ("user_id", "email", "name", "plan", "usage", "created_at", "last_login")}


# ── Analytics Endpoints ───────────────────────────────────────────────────── #

@app.get("/api/v2/analytics")
async def analytics(user_id: str = "default", days: int = 30):
    """Aggregate analytics: message trends, top contacts, AI stats."""
    from enterprise.integrations.whatsapp.db import (
        get_message_trends, get_top_contacts, get_ai_stats
    )
    trends, top, ai_stats = await asyncio.gather(
        get_message_trends(user_id, days),
        get_top_contacts(user_id, 10),
        get_ai_stats(user_id),
    )

    # Summary from in-memory cache (fast, no DB needed)
    evts = [e for e in _wa_events if e.get("user_id", "default") == user_id]
    total_in  = sum(1 for e in evts if e.get("type") == "IN")
    total_out = sum(1 for e in evts if e.get("type") == "OUT")
    total_ai  = sum(1 for e in evts if e.get("type") == "AI")
    total_err = sum(1 for e in evts if e.get("type") == "ERROR")

    return {
        "summary": {
            "total_in":  total_in,
            "total_out": total_out,
            "total_ai":  total_ai,
            "total_errors": total_err,
            "total": len(evts),
        },
        "trends":       trends,
        "top_contacts": top,
        "ai_stats":     ai_stats,
        "period_days":  days,
        "timestamp":    datetime.utcnow().isoformat(),
    }


# ── Billing Endpoints ─────────────────────────────────────────────────────── #

class CheckoutRequest(BaseModel):
    plan: str   # "pro" | "enterprise"
    success_url: str
    cancel_url: str

class PortalRequest(BaseModel):
    return_url: str


@app.get("/api/v2/billing/plans")
async def billing_plans():
    """Return available subscription plans."""
    if not _BILLING_AVAILABLE:
        return {"plans": {}, "billing_enabled": False}
    return {"plans": PLANS, "billing_enabled": True}


@app.post("/api/v2/billing/checkout")
async def billing_checkout(
    req: CheckoutRequest,
    current_user: "UserClaims" = Depends(get_current_user),
):
    """Create a Stripe checkout session for plan upgrade."""
    if not _BILLING_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing not configured")

    stripe = get_stripe()
    if not stripe.enabled:
        raise HTTPException(status_code=503, detail="Stripe not configured — set STRIPE_SECRET_KEY")

    plan = PLANS.get(req.plan)
    if not plan or not plan.get("price_id"):
        raise HTTPException(status_code=400, detail=f"Invalid plan: {req.plan}")

    from enterprise.integrations.whatsapp.db import get_user_by_id, update_user
    user = await get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Create Stripe customer on first checkout
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer_id = stripe.create_customer(
            email=user.get("email", ""),
            name=user.get("name", ""),
            user_id=current_user.user_id,
        )
        if customer_id:
            await update_user(current_user.user_id, {"stripe_customer_id": customer_id})

    if not customer_id:
        raise HTTPException(status_code=500, detail="Could not create Stripe customer")

    url = stripe.create_checkout_session(
        customer_id=customer_id,
        price_id=plan["price_id"],
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        user_id=current_user.user_id,
    )
    if not url:
        raise HTTPException(status_code=500, detail="Could not create checkout session")

    return {"checkout_url": url, "plan": req.plan}


@app.post("/api/v2/billing/portal")
async def billing_portal(
    req: PortalRequest,
    current_user: "UserClaims" = Depends(get_current_user),
):
    """Create a Stripe billing portal session for subscription management."""
    if not _BILLING_AVAILABLE:
        raise HTTPException(status_code=503, detail="Billing not configured")

    stripe = get_stripe()
    from enterprise.integrations.whatsapp.db import get_user_by_id
    user = await get_user_by_id(current_user.user_id)
    customer_id = user.get("stripe_customer_id") if user else None
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found — subscribe first")

    url = stripe.create_portal_session(customer_id=customer_id, return_url=req.return_url)
    if not url:
        raise HTTPException(status_code=500, detail="Could not create portal session")
    return {"portal_url": url}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription events."""
    if not _BILLING_AVAILABLE:
        return {"ok": True}

    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    stripe  = get_stripe()
    event   = stripe.parse_webhook(payload, sig)
    if not event:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    etype = event.get("type", "")
    data  = event.get("data", {}).get("object", {})

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        cust_id = data.get("customer")
        status  = data.get("status")
        sub_id  = data.get("id")

        # Map price_id → plan name
        price_id = None
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")

        new_plan = "free"
        if _BILLING_AVAILABLE:
            for pname, pdata in PLANS.items():
                if pdata.get("price_id") == price_id:
                    new_plan = pname
                    break

        if status == "active" and cust_id:
            from enterprise.integrations.whatsapp.db import get_db
            db = await get_db()
            if db:
                user = await db.users.find_one({"stripe_customer_id": cust_id})
                if user:
                    await db.users.update_one(
                        {"stripe_customer_id": cust_id},
                        {"$set": {"plan": new_plan, "stripe_subscription_id": sub_id}},
                    )
                    logger.info("[Stripe] User %s upgraded to %s", user.get("user_id"), new_plan)

    elif etype == "customer.subscription.deleted":
        cust_id = data.get("customer")
        if cust_id:
            from enterprise.integrations.whatsapp.db import get_db
            db = await get_db()
            if db:
                await db.users.update_one(
                    {"stripe_customer_id": cust_id},
                    {"$set": {"plan": "free", "stripe_subscription_id": None}},
                )

    return {"received": True}


# ── LinkedIn ─────────────────────────────────────────────────────────────── #

class LinkedInPostRequest(BaseModel):
    topic: str
    tone: str = "professional"
    visibility: str = "PUBLIC"
    custom_text: Optional[str] = None


@app.post("/api/v2/linkedin/post")
async def linkedin_create_post(req: LinkedInPostRequest):
    """Generate a LinkedIn post draft and queue for approval."""
    agent = get_linkedin_agent()
    draft = agent.create_post(
        topic=req.topic,
        tone=req.tone,
        visibility=req.visibility,
        custom_text=req.custom_text,
    )
    await ws_manager.broadcast({
        "event": "linkedin_draft_created",
        "draft_id": draft.draft_id,
        "topic": draft.topic,
        "simulation": agent.client.is_simulation,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {
        "draft_id": draft.draft_id,
        "topic": draft.topic,
        "tone": draft.tone,
        "post_text": draft.post_text,
        "hashtags": draft.hashtags,
        "visibility": draft.visibility,
        "status": draft.status,
        "simulation_mode": agent.client.is_simulation,
    }


@app.get("/api/v2/linkedin/pending")
async def linkedin_pending():
    """List LinkedIn posts pending approval."""
    agent = get_linkedin_agent()
    return {
        "pending": agent.get_pending_approvals(),
        "count": len(agent.get_pending_approvals()),
        "simulation_mode": agent.client.is_simulation,
    }


@app.post("/api/v2/linkedin/publish/{draft_id}")
async def linkedin_publish(draft_id: str):
    """Approve and publish a pending LinkedIn post."""
    agent = get_linkedin_agent()
    result = agent.approve_and_publish(draft_id)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Publish failed")
    await ws_manager.broadcast({
        "event": "linkedin_post_published",
        "draft_id": draft_id,
        "post_id": result.post_id,
        "simulated": result.simulated,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {
        "post_id": result.post_id,
        "url": result.url,
        "simulated": result.simulated,
    }


@app.get("/api/v2/linkedin/status")
async def linkedin_status():
    agent = get_linkedin_agent()
    return {
        "connected": agent.client.is_connected,
        "simulation_mode": agent.client.is_simulation,
        "pending_approvals": len(agent.get_pending_approvals()),
    }


# ── Smart Assistant ───────────────────────────────────────────────────────── #

@app.post("/api/v2/assistant")
async def smart_assistant(req: SmartAssistantRequest):
    """Process a natural language instruction."""
    assistant = get_smart_assistant()
    action = assistant.process(req.instruction, req.context)

    await ws_manager.broadcast({
        "event": "assistant_action_created",
        "action_id": action.action_id,
        "type": action.action_type,
        "summary": action.summary,
        "timestamp": datetime.utcnow().isoformat(),
    })

    return {
        "action_id": action.action_id,
        "action_type": action.action_type,
        "summary": action.summary,
        "confidence": action.confidence,
        "recipients": action.recipients,
        "subject": action.subject,
        "body": action.body,
        "status": action.status,
        "requires_approval": True,
    }


# ── PDF Upload ────────────────────────────────────────────────────────────── #

@app.post("/api/v2/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload a PDF and extract task specifications.
    Returns parsed task with execution plan and README draft.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    try:
        from enterprise.tasks.pdf_parser import PDFTaskParser
        pdf_bytes = await file.read()
        parser = PDFTaskParser()
        task = parser.parse_bytes(pdf_bytes, file.filename)

        await ws_manager.broadcast({
            "event": "pdf_parsed",
            "task_id": task.task_id,
            "title": task.title,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {
            "task_id": task.task_id,
            "title": task.title,
            "description": task.description,
            "objectives": task.objectives,
            "deliverables": task.deliverables,
            "deadline": task.deadline,
            "priority": task.priority,
            "project_structure": task.project_structure,
            "execution_plan": task.execution_plan,
            "readme_draft": task.readme_draft,
            "confidence": task.confidence,
            "source_file": task.source_file,
        }
    except Exception as e:
        logger.error("PDF parse failed: %s", e)
        raise HTTPException(status_code=500, detail=f"PDF parsing failed: {e}")


# ── Agent Pipeline ────────────────────────────────────────────────────────── #

@app.post("/api/v2/agents/run")
async def run_agent_pipeline(task: TaskCreate, background: BackgroundTasks):
    """Run a task through the full 5-agent pipeline."""
    from enterprise.agents.base import EnterpriseTask
    enterprise_task = EnterpriseTask(
        task_id=str(uuid.uuid4()),
        title=task.title,
        description=task.description,
        source=task.source,
        priority=task.priority,
        requester=task.requester,
    )

    coordinator = get_coordinator()

    def run():
        coordinator.run(enterprise_task)

    background.add_task(run)
    return {
        "task_id": enterprise_task.task_id,
        "status": "pipeline_started",
        "stages": ["planner", "compliance", "security_guard", "awaiting_approval", "executor", "reviewer"],
    }


@app.get("/api/v2/agents/pending")
async def get_pipeline_approvals():
    """Get pipeline runs awaiting human approval."""
    coordinator = get_coordinator()
    return {
        "pending": coordinator.get_pending_approvals(),
        "count": len(coordinator.get_pending_approvals()),
    }


# ── Memory Viewer ─────────────────────────────────────────────────────────── #

@app.get("/api/v2/memory")
async def memory_stats():
    try:
        from platinum.memory.memory_store import MemoryStore
        store = MemoryStore()
        stats = store.get_stats()
        recent = store.recall(category=None, limit=10)
        return {
            "stats": stats,
            "recent_memories": recent,
        }
    except Exception as e:
        return {"stats": {}, "recent_memories": [], "error": str(e)}


# ── Monitoring ────────────────────────────────────────────────────────────── #

@app.get("/api/v2/monitoring")
async def monitoring():
    try:
        from platinum.monitoring.monitor import SystemMonitor
        monitor = SystemMonitor()
        return monitor.get_dashboard_data()
    except Exception as e:
        return {
            "status": "limited",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


@app.get("/api/v2/audit-logs")
async def audit_logs(limit: int = 50):
    """Return recent audit log entries."""
    logs = []
    try:
        log_dir = Path(__file__).parent.parent.parent / "vault" / "logs"
        jsonl_files = sorted(log_dir.glob("*.jsonl"), reverse=True)[:3]
        for f in jsonl_files:
            for line in f.read_text(encoding="utf-8", errors="replace").strip().split("\n"):
                if line:
                    try:
                        logs.append(json.loads(line))
                    except Exception:
                        pass
        logs = logs[:limit]
    except Exception as e:
        logger.debug("Audit log read error: %s", e)

    return {"logs": logs, "count": len(logs)}


# ══════════════════════════════════════════════════════════════════════════════
# GOLD TIER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── Autonomous Loop ───────────────────────────────────────────────────────── #

_autonomous_loop = None

def _get_autonomous_loop():
    global _autonomous_loop
    if _autonomous_loop is None:
        from enterprise.autonomous.loop import AutonomousLoop
        _autonomous_loop = AutonomousLoop(
            interval_seconds=int(os.getenv("AUTONOMOUS_LOOP_INTERVAL", "300")),
            ws_emit=ws_manager.broadcast,
        )
    return _autonomous_loop


@app.post("/api/v2/autonomous/start")
async def autonomous_start():
    """Start the autonomous reasoning loop."""
    loop = _get_autonomous_loop()
    if loop.is_running:
        return {"status": "already_running", "iterations": loop._iteration_count}
    loop.start()
    return {"status": "started", "interval_seconds": loop._interval}


@app.post("/api/v2/autonomous/stop")
async def autonomous_stop():
    """Stop the autonomous reasoning loop."""
    loop = _get_autonomous_loop()
    loop.stop()
    return {"status": "stopped", "iterations_completed": loop._iteration_count}


@app.post("/api/v2/autonomous/pause")
async def autonomous_pause():
    """Pause/resume the autonomous loop."""
    loop = _get_autonomous_loop()
    if loop.is_paused:
        loop.resume()
        return {"status": "resumed"}
    loop.pause()
    return {"status": "paused"}


@app.get("/api/v2/autonomous/status")
async def autonomous_status():
    """Get autonomous loop status and recent history."""
    loop = _get_autonomous_loop()
    return {
        **loop.get_status(),
        "history": loop.get_history(n=5),
    }


# ── CEO Report ────────────────────────────────────────────────────────────── #

@app.post("/api/v2/reports/ceo")
async def generate_ceo_report(background: BackgroundTasks, lookback_days: int = 7):
    """Generate a CEO briefing report (runs in background)."""
    def _run():
        try:
            from enterprise.autonomous.ceo_reporter import CEOReporter
            reporter = CEOReporter(lookback_days=lookback_days)
            report = reporter.generate()
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(ws_manager.broadcast({
                        "event": "ceo_report_generated",
                        "report_id": report.report_id,
                        "period": report.period,
                        "saved_to": report.saved_to,
                    }))
            except Exception:
                pass
        except Exception as e:
            logger.error("CEO report generation failed: %s", e)

    background.add_task(_run)
    return {"status": "generating", "lookback_days": lookback_days}


@app.get("/api/v2/reports/latest")
async def get_latest_report():
    """Return the most recently generated CEO report."""
    try:
        reports_dir = Path(__file__).parent.parent.parent / "vault" / "reports"
        latest = reports_dir / "LATEST_CEO_REPORT.md"
        if latest.exists():
            return {
                "found": True,
                "markdown": latest.read_text(encoding="utf-8"),
                "path": str(latest),
            }
        # Fallback: find most recent report file
        reports = sorted(reports_dir.glob("ceo_report_*.md"), reverse=True)
        if reports:
            return {
                "found": True,
                "markdown": reports[0].read_text(encoding="utf-8"),
                "path": str(reports[0]),
            }
    except Exception as e:
        logger.debug("Report read error: %s", e)
    return {"found": False, "markdown": "", "path": None}


@app.get("/api/v2/reports/list")
async def list_reports():
    """List all generated CEO reports."""
    try:
        reports_dir = Path(__file__).parent.parent.parent / "vault" / "reports"
        reports = sorted(reports_dir.glob("ceo_report_*.md"), reverse=True)
        return {
            "reports": [
                {"filename": r.name, "path": str(r), "size": r.stat().st_size,
                 "created": datetime.fromtimestamp(r.stat().st_mtime).isoformat()}
                for r in reports[:20]
            ],
            "count": len(reports),
        }
    except Exception:
        return {"reports": [], "count": 0}


# ── Content Planner ───────────────────────────────────────────────────────── #

class ContentPlanRequest(BaseModel):
    platform: str = "linkedin"
    topic: Optional[str] = None
    tone: str = "professional"
    auto_post: bool = False


@app.post("/api/v2/content/generate")
async def generate_content(req: ContentPlanRequest):
    """Generate content for a platform. Optionally auto-post if confidence ≥ 0.85."""
    from enterprise.autonomous.content_planner import ContentPlanner
    planner = ContentPlanner()
    plan = planner.generate_daily_post(
        platform=req.platform,
        override_topic=req.topic,
        override_tone=req.tone,
    )
    result = {
        "plan_id": plan.plan_id,
        "platform": plan.platform,
        "topic": plan.topic,
        "tone": plan.tone,
        "text": plan.text,
        "hashtags": plan.hashtags,
        "confidence": plan.confidence,
        "auto_post_eligible": planner.should_auto_post(plan),
    }

    if req.auto_post and planner.should_auto_post(plan) and req.platform == "linkedin":
        agent = get_linkedin_agent()
        draft = agent.create_post(topic=plan.topic, tone=plan.tone, custom_text=plan.text)
        post_result = agent.approve_and_publish(draft.draft_id)
        result["auto_posted"] = post_result.success
        result["post_id"] = post_result.post_id
        result["simulated"] = post_result.simulated
    else:
        result["auto_posted"] = False

    await ws_manager.broadcast({"event": "content_generated", **result})
    return result


@app.post("/api/v2/content/twitter-thread")
async def generate_twitter_thread(topic: Optional[str] = None):
    """Generate a Twitter/X thread."""
    from enterprise.autonomous.content_planner import ContentPlanner
    planner = ContentPlanner()
    tweets = planner.generate_twitter_thread(topic=topic)
    return {"tweets": tweets, "count": len(tweets)}


# ── LinkedIn Auto-Post ────────────────────────────────────────────────────── #

@app.post("/api/v2/linkedin/auto-post")
async def linkedin_auto_post(background: BackgroundTasks):
    """Trigger today's scheduled LinkedIn post (runs in background)."""
    def _run():
        try:
            from enterprise.autonomous.content_planner import ContentPlanner
            planner = ContentPlanner()
            plan = planner.generate_daily_post(platform="linkedin")

            agent = get_linkedin_agent()
            draft = agent.create_post(topic=plan.topic, tone=plan.tone, custom_text=plan.text)

            if planner.should_auto_post(plan):
                result = agent.approve_and_publish(draft.draft_id)
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(ws_manager.broadcast({
                            "event": "linkedin_auto_posted",
                            "post_id": result.post_id,
                            "simulated": result.simulated,
                            "confidence": plan.confidence,
                        }))
                except Exception:
                    pass
            else:
                logger.info("[auto-post] Queued for approval (confidence=%.2f)", plan.confidence)
        except Exception as e:
            logger.error("[auto-post] Failed: %s", e)

    background.add_task(_run)
    return {"status": "scheduled", "message": "Auto-post triggered in background"}


# ── Odoo Accounting ───────────────────────────────────────────────────────── #

_odoo_agent = None

def _get_odoo_agent():
    global _odoo_agent
    if _odoo_agent is None:
        from enterprise.integrations.odoo.agent import OdooAgent
        _odoo_agent = OdooAgent()
        _odoo_agent.connect()
    return _odoo_agent


class OdooInvoiceRequest(BaseModel):
    partner_name: str
    amount: float
    description: str
    auto_approve: bool = False


@app.post("/api/v2/odoo/invoice")
async def odoo_create_invoice(req: OdooInvoiceRequest):
    """Create an Odoo invoice (queued for approval unless auto_approve=True)."""
    agent = _get_odoo_agent()
    action = agent.request_invoice(
        partner_name=req.partner_name,
        amount=req.amount,
        description=req.description,
        auto_approve=req.auto_approve,
    )
    return {
        "action_id": action.action_id,
        "status": action.status,
        "description": action.description,
        "simulated": agent.client.is_simulation,
        "result": action.result.data if action.result else None,
    }


@app.get("/api/v2/odoo/invoices")
async def odoo_get_invoices(limit: int = 20):
    """List invoices from Odoo."""
    agent = _get_odoo_agent()
    result = agent.get_invoices(limit=limit)
    return {
        "invoices": result.data,
        "simulated": result.simulated,
        "success": result.success,
    }


@app.get("/api/v2/odoo/balance")
async def odoo_balance():
    """Get Odoo financial summary."""
    agent = _get_odoo_agent()
    result = agent.get_balance()
    return {"balance": result.data, "simulated": result.simulated}


@app.get("/api/v2/odoo/status")
async def odoo_status():
    agent = _get_odoo_agent()
    return {
        "connected": agent.client.is_connected,
        "simulation_mode": agent.client.is_simulation,
        "pending_approvals": len(agent.get_pending_approvals()),
    }


# ── Twitter/X ─────────────────────────────────────────────────────────────── #

_twitter_client = None

def _get_twitter_client():
    global _twitter_client
    if _twitter_client is None:
        from enterprise.integrations.social.twitter import TwitterClient
        _twitter_client = TwitterClient()
        _twitter_client.connect()
    return _twitter_client


class TweetRequest(BaseModel):
    text: str
    thread: Optional[list] = None


@app.post("/api/v2/social/tweet")
async def post_tweet(req: TweetRequest):
    """Post a tweet or thread."""
    client = _get_twitter_client()
    if req.thread:
        results = client.post_thread(req.thread)
        return {
            "success": all(r.success for r in results),
            "tweets": [{"id": r.tweet_id, "simulated": r.simulated} for r in results],
        }
    result = client.tweet(req.text)
    return {
        "success": result.success,
        "tweet_id": result.tweet_id,
        "url": result.tweet_url,
        "simulated": result.simulated,
    }


@app.get("/api/v2/social/status")
async def social_status():
    """Status of all social media integrations."""
    twitter = _get_twitter_client()
    linkedin = get_linkedin_agent()
    return {
        "twitter": {"connected": twitter.is_connected, "simulation": twitter.is_simulation},
        "linkedin": {"connected": linkedin.client.is_connected, "simulation": linkedin.client.is_simulation},
    }


# ── Error Recovery Dashboard ──────────────────────────────────────────────── #

@app.get("/api/v2/errors/recent")
async def recent_errors(n: int = 20):
    """Return recent error log entries from the error recovery system."""
    try:
        from enterprise.recovery.error_recovery import ErrorLog
        return {
            "errors": ErrorLog.get_recent(n),
            "total_count": ErrorLog.get_count(),
        }
    except Exception as e:
        return {"errors": [], "total_count": 0, "error": str(e)}


@app.delete("/api/v2/errors/clear")
async def clear_errors():
    """Clear in-memory error log."""
    from enterprise.recovery.error_recovery import ErrorLog
    ErrorLog.clear()
    return {"status": "cleared"}


# ── MCP Server Proxy ──────────────────────────────────────────────────────── #

class MCPCallRequest(BaseModel):
    tool: str
    params: dict = {}


@app.post("/api/v2/mcp/call")
async def mcp_call(req: MCPCallRequest):
    """
    Proxy MCP tool calls directly through the enterprise server.
    Avoids needing a separate MCP server process for basic use.
    """
    import httpx
    mcp_port = int(os.getenv("MCP_PORT", "8001"))
    mcp_url = f"http://127.0.0.1:{mcp_port}/call"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(mcp_url, json={"tool": req.tool, "params": req.params})
            return resp.json()
    except Exception as e:
        # MCP server not running — execute inline
        logger.warning("[MCP Proxy] MCP server unavailable (%s) — executing inline", e)
        try:
            from mcp_servers.enterprise_mcp.server import TOOL_HANDLERS
            handler = TOOL_HANDLERS.get(req.tool)
            if not handler:
                raise HTTPException(status_code=400, detail=f"Unknown tool: {req.tool}")
            result = await handler(req.params)
            return {"success": result.get("success", True), "result": result.get("data"), "tool": req.tool}
        except ImportError:
            raise HTTPException(status_code=503, detail="MCP server not available. Start it with: python mcp-servers/enterprise-mcp/server.py")


# ══════════════════════════════════════════════════════════════════════════════
# TASK 8 — LEAD GENERATION + AUTO SALES CRM
# ══════════════════════════════════════════════════════════════════════════════

class LeadIngestRequest(BaseModel):
    message: str
    sender_id: str
    sender_name: str = ""
    sender_company: str = ""
    channel: str = "whatsapp"      # whatsapp | email | linkedin | twitter
    source: str = "whatsapp"


@app.post("/api/v2/crm/ingest")
async def crm_ingest_message(req: LeadIngestRequest):
    """
    Ingest a message from any channel, score intent, and run auto-sales pipeline.
    This is called automatically when WhatsApp/Email messages arrive.
    """
    from enterprise.crm.pipeline import SalesPipeline
    pipeline = SalesPipeline()
    result = pipeline.process_message(
        message=req.message,
        sender_id=req.sender_id,
        sender_name=req.sender_name,
        sender_company=req.sender_company,
        channel=req.channel,
        source=req.source,
    )
    await ws_manager.broadcast({
        "event": "lead_processed",
        "lead_id": result.lead_id,
        "action": result.action_taken,
        "auto_sent": result.auto_sent,
        "intent_level": result.intent_result.level if result.intent_result else "unknown",
        "intent_score": result.intent_result.score if result.intent_result else 0,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {
        "lead_id": result.lead_id,
        "action_taken": result.action_taken,
        "auto_sent": result.auto_sent,
        "requires_approval": result.requires_approval,
        "channel": result.channel_used,
        "intent": {
            "score": result.intent_result.score if result.intent_result else 0,
            "level": result.intent_result.level if result.intent_result else "cold",
            "recommended_action": result.intent_result.recommended_action if result.intent_result else "no_action",
        } if result.intent_result else {},
    }


@app.get("/api/v2/crm/leads")
async def crm_leads(
    status: Optional[str] = None,
    source: Optional[str] = None,
    intent_level: Optional[str] = None,
    limit: int = 50,
):
    """List CRM leads with optional filters."""
    from enterprise.crm.models import get_crm_db
    db = get_crm_db()
    leads = db.get_leads(status=status, source=source, intent_level=intent_level, limit=limit)
    return {
        "leads": [l.to_dict() for l in leads],
        "count": len(leads),
    }


@app.get("/api/v2/crm/leads/{lead_id}")
async def crm_get_lead(lead_id: str):
    """Get a specific lead with all activities."""
    from enterprise.crm.models import get_crm_db
    db = get_crm_db()
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    activities = db.get_activities(lead_id)
    return {
        "lead": lead.to_dict(),
        "activities": [{"activity_id": a.activity_id, "type": a.type,
                        "content": a.content, "outcome": a.outcome, "created_at": a.created_at}
                       for a in activities],
    }


@app.patch("/api/v2/crm/leads/{lead_id}")
async def crm_update_lead(lead_id: str, updates: dict):
    """Update a lead's status, notes, deal_value, etc."""
    from enterprise.crm.models import get_crm_db
    db = get_crm_db()
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    for key, value in updates.items():
        if hasattr(lead, key):
            setattr(lead, key, value)
    db.update_lead(lead)
    return {"status": "updated", "lead_id": lead_id}


@app.post("/api/v2/crm/leads/{lead_id}/send")
async def crm_send_to_lead(lead_id: str, body: dict):
    """Manually send a message to a specific lead."""
    from enterprise.crm.models import get_crm_db, Activity
    import uuid
    db = get_crm_db()
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    message = body.get("message", "")
    channel = body.get("channel", lead.channel)

    sent = False
    from enterprise.crm.pipeline import SalesPipeline
    pipeline = SalesPipeline()
    sent = pipeline._send_via_channel(lead, message, channel)

    db.log_activity(Activity(
        activity_id=uuid.uuid4().hex[:12],
        lead_id=lead_id,
        type=f"{channel}_sent",
        content=message[:500],
        outcome="manual_send",
    ))
    return {"sent": sent, "channel": channel, "lead_id": lead_id}


@app.get("/api/v2/crm/pipeline")
async def crm_pipeline():
    """Get pipeline stats and revenue summary."""
    from enterprise.crm.models import get_crm_db
    db = get_crm_db()
    return {
        "pipeline": db.get_pipeline_stats(),
        "revenue": db.get_revenue_stats(),
    }


@app.post("/api/v2/crm/followups")
async def crm_run_followups(background: BackgroundTasks):
    """Trigger follow-up sequences for hot leads."""
    def _run():
        from enterprise.crm.pipeline import SalesPipeline
        sent = SalesPipeline().run_followups()
        logger.info("[CRM] Follow-ups sent: %d", sent)
    background.add_task(_run)
    return {"status": "triggered"}


@app.post("/api/v2/crm/analyze")
async def crm_analyze_text(body: dict):
    """Analyze any text for buying signals and intent score."""
    from enterprise.crm.detector import get_detector
    text = body.get("text", "")
    name = body.get("name", "")
    company = body.get("company", "")
    detector = get_detector()
    result = detector.analyze(text, name, company)
    return {
        "score": result.score,
        "level": result.level,
        "is_buying": result.is_buying,
        "signals_found": result.signals_found,
        "recommended_action": result.recommended_action,
        "personalized_opener": result.personalized_opener,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TASK 9 — LINKEDIN BOT LEVEL AUTOMATION
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v2/linkedin/bot/run")
async def linkedin_bot_run(background: BackgroundTasks):
    """Run the full LinkedIn daily automation cycle."""
    def _run():
        try:
            from enterprise.integrations.linkedin.bot import LinkedInBot
            bot = LinkedInBot()
            bot.connect()
            results = bot.run_daily_automation()
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(ws_manager.broadcast({
                        "event": "linkedin_bot_completed",
                        **results,
                        "timestamp": datetime.utcnow().isoformat(),
                    }))
            except Exception:
                pass
        except Exception as e:
            logger.error("[LinkedIn Bot] Daily run failed: %s", e)
    background.add_task(_run)
    return {"status": "started", "message": "LinkedIn daily automation running in background"}


@app.post("/api/v2/linkedin/bot/reply-comments")
async def linkedin_reply_comments():
    """Fetch recent comments and auto-reply to them."""
    from enterprise.integrations.linkedin.bot import LinkedInBot
    bot = LinkedInBot()
    bot.connect()
    events = bot.fetch_recent_engagement()
    replied = 0
    leads_found = 0
    for event in events:
        if event.event_type == "comment":
            if bot.auto_reply_comment(event):
                replied += 1
            lead_id = bot.detect_lead_from_engagement(event)
            if lead_id:
                leads_found += 1
    return {
        "comments_found": len(events),
        "replies_sent": replied,
        "leads_detected": leads_found,
    }


@app.post("/api/v2/linkedin/bot/detect-leads")
async def linkedin_detect_leads():
    """Scan LinkedIn engagement for hot leads."""
    from enterprise.integrations.linkedin.bot import LinkedInBot
    from enterprise.crm.models import get_crm_db
    bot = LinkedInBot()
    bot.connect()
    events = bot.fetch_recent_engagement()
    leads = []
    for event in events:
        lead_id = bot.detect_lead_from_engagement(event)
        if lead_id:
            leads.append({"lead_id": lead_id, "actor": event.actor_name, "content": event.content[:100]})

    return {
        "events_scanned": len(events),
        "leads_detected": len(leads),
        "leads": leads,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TASK 14 — VAULT SYNC SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v2/vault/stats")
async def vault_stats():
    """Get vault folder statistics."""
    from enterprise.vault_sync.sync import get_vault_sync
    vault = get_vault_sync()
    return {
        "stats": vault.get_stats(),
        "needs_action": [f.name for f in vault.list_needs_action()[:10]],
        "in_progress": [f.name for f in vault.list_in_progress()],
        "pending_approval": [f.name for f in vault.list_pending_approval()[:10]],
    }


@app.post("/api/v2/vault/claim/{filename}")
async def vault_claim_task(filename: str, agent_id: str = "api"):
    """Claim a task from needs_action/ by moving it to in_progress/."""
    from enterprise.vault_sync.sync import get_vault_sync
    vault = get_vault_sync()
    path = vault.claim_task(f"needs_action/{filename}", agent_id=agent_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"File not found or already claimed: {filename}")
    return {"status": "claimed", "path": str(path), "filename": path.name}


@app.post("/api/v2/vault/complete/{filename}")
async def vault_complete_task(filename: str):
    """Move a task from in_progress/ to done/."""
    from enterprise.vault_sync.sync import get_vault_sync
    vault = get_vault_sync()
    src = vault.vault / "in_progress" / filename
    path = vault.complete_task(src)
    if not path:
        raise HTTPException(status_code=404, detail=f"File not found in in_progress/: {filename}")
    return {"status": "completed", "path": str(path)}


@app.post("/api/v2/vault/sync")
async def vault_git_sync(message: str = "vault: auto-sync from API"):
    """Commit and push vault changes to git."""
    from enterprise.vault_sync.sync import get_vault_sync
    vault = get_vault_sync()
    success = vault.git_sync(commit_message=message)
    vault.update_dashboard()
    return {"synced": success, "message": message}


# ══════════════════════════════════════════════════════════════════════════════
# TASK 15 — SECURITY
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v2/security/scan")
async def security_scan():
    """Run a security scan for exposed secrets."""
    from enterprise.security.scanner import SecurityScanner
    scanner = SecurityScanner()
    result = scanner.scan_for_secrets()
    missing_gitignore = scanner.check_gitignore()
    valid_creds, cred_msg = scanner.verify_credential_encryption()
    return {
        "files_scanned": result.scanned_files,
        "violations": len(result.violations),
        "critical": result.critical_count,
        "clean": not result.has_violations,
        "violations_detail": [
            {"file": v.file_path, "line": v.line_number, "type": v.pattern_name, "severity": v.severity}
            for v in result.violations[:20]
        ],
        "gitignore_missing": missing_gitignore,
        "credentials_encrypted": valid_creds,
        "credentials_message": cred_msg,
    }


@app.post("/api/v2/security/install-hook")
async def security_install_hook():
    """Install git pre-commit security hook."""
    from enterprise.security.scanner import SecurityScanner
    scanner = SecurityScanner()
    ok = scanner.install_git_hook()
    return {"installed": ok}


# ══════════════════════════════════════════════════════════════════════════════
# TASK 16 — MCP SERVER REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v2/mcp/servers")
async def mcp_list_servers():
    """List all available MCP servers and their status."""
    servers = {
        "enterprise": {"port": int(os.getenv("MCP_PORT", 8001)), "tools": ["send_email","send_whatsapp","post_linkedin","create_odoo_invoice","post_tweet","generate_content"]},
        "email":      {"port": int(os.getenv("EMAIL_MCP_PORT", 8002)), "tools": ["send_email","draft_email","list_unread","reply_email","search_email"]},
        "whatsapp":   {"port": int(os.getenv("WA_MCP_PORT", 8003)), "tools": ["send_message","broadcast","get_status"]},
        "linkedin":   {"port": int(os.getenv("LI_MCP_PORT", 8004)), "tools": ["post","auto_post","reply_comment","detect_leads","get_status"]},
        "odoo":       {"port": int(os.getenv("ODOO_MCP_PORT", 8005)), "tools": ["create_invoice","list_invoices","get_balance","create_expense","approve_action"]},
        "twitter":    {"port": int(os.getenv("TWITTER_MCP_PORT", 8006)), "tools": ["tweet","post_thread","get_status"]},
    }
    # Check health of each
    import httpx
    for name, info in servers.items():
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"http://127.0.0.1:{info['port']}/health")
                info["status"] = "online" if resp.status_code == 200 else "error"
        except Exception:
            info["status"] = "offline"
    return {"servers": servers}


# ══════════════════════════════════════════════════════════════════════════════
# GROWTH ENGINE — Option A: Auto Growth System
# ══════════════════════════════════════════════════════════════════════════════

class GrowthPostRequest(BaseModel):
    topic: Optional[str] = None
    simulate: bool = False

@app.post("/api/v2/growth/post")
async def growth_post(req: GrowthPostRequest, background_tasks: BackgroundTasks):
    """
    Trigger the daily LinkedIn growth cycle (generate + publish post).
    Set simulate=true for a dry run that returns the text without posting.
    """
    def _run():
        from enterprise.growth.growth_engine import get_growth_engine
        return get_growth_engine().run_daily_cycle(
            force_topic=req.topic,
            simulate=req.simulate,
        )
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return {
        "success":   result.success,
        "post_url":  result.post_url,
        "topic":     result.topic,
        "simulated": result.simulated,
        "error":     result.error,
        "preview":   result.post_text[:200] if result.post_text else "",
    }

@app.post("/api/v2/growth/engage")
async def growth_engage():
    """Run LinkedIn engagement cycle (reply to comments + DMs, detect leads)."""
    def _run():
        from enterprise.growth.engagement_agent import get_engagement_agent
        return get_engagement_agent().run()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return {
        "dm_replies":       result.dm_replies,
        "comment_replies":  result.comment_replies,
        "leads_detected":   result.leads_detected,
        "errors":           result.errors,
    }

@app.get("/api/v2/growth/stats")
async def growth_stats():
    """Return today's growth stats (posts published, topics used)."""
    from enterprise.growth.growth_engine import get_growth_engine
    return get_growth_engine().get_today_stats()


# ══════════════════════════════════════════════════════════════════════════════
# SALES SYSTEM — Option B: Money System
# ══════════════════════════════════════════════════════════════════════════════

class DMRequest(BaseModel):
    profile_url: str
    name: str
    company: str = ""
    lead_id: Optional[str] = None
    context: str = ""

class SalesMessageRequest(BaseModel):
    message: str
    lead_id: str
    stage: str = "greeting"

class WAConversionRequest(BaseModel):
    lead_id: str

@app.post("/api/v2/sales/dm")
async def sales_send_dm(req: DMRequest):
    """Send a personalized LinkedIn DM to a prospect."""
    def _run():
        from enterprise.sales.dm_agent import get_dm_agent, DMTarget
        target = DMTarget(
            profile_url=req.profile_url,
            name=req.name,
            company=req.company,
            lead_id=req.lead_id,
            context=req.context,
        )
        return get_dm_agent().send_dm(target)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return {
        "success":      result.success,
        "queued":       result.queued,
        "message_sent": result.message_sent[:120] if result.message_sent else "",
        "error":        result.error,
    }

@app.post("/api/v2/sales/dm/hot-leads")
async def sales_dm_hot_leads():
    """DM all uncontacted HOT/BUYING CRM leads (up to daily budget)."""
    def _run():
        from enterprise.orchestration.decision_engine import get_decision_engine
        from enterprise.sales.dm_agent import get_dm_agent, DMTarget
        targets = get_decision_engine().select_dm_targets(limit=10)
        if not targets:
            return []
        agent = get_dm_agent()
        dm_targets = [
            DMTarget(
        profile_url=lead.linkedin_url,
                name=lead.name,
                company=lead.company or "",
                lead_id=lead.lead_id,
            )
            for lead in targets if lead.linkedin_url
        ]
        return agent.send_bulk(dm_targets)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _run)
    return {
        "total":   len(results),
        "sent":    sum(1 for r in results if r.success and not r.queued),
        "queued":  sum(1 for r in results if r.queued),
        "failed":  sum(1 for r in results if not r.success),
    }

@app.post("/api/v2/sales/message")
async def sales_handle_message(req: SalesMessageRequest):
    """Run an incoming message through the SalesAgent conversation engine."""
    from enterprise.sales.sales_agent import get_sales_agent
    from enterprise.crm.models import get_crm_db, Lead, IntentLevel, LeadSource
    import uuid
    # Load or stub lead
    try:
        from enterprise.crm.models import _CRM_DB_PATH
        import sqlite3
        conn = sqlite3.connect(str(_CRM_DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM leads WHERE lead_id=?", (req.lead_id,)).fetchone()
        conn.close()
        d = dict(row)
        d["pitch_sent"] = bool(d["pitch_sent"])
        lead = Lead.from_dict(d)
    except Exception:
        lead = Lead(
            lead_id=req.lead_id,
            name="Prospect",
            source=LeadSource.WHATSAPP,
            channel="whatsapp",
            message="",
        )
    response = get_sales_agent().handle_message(
        message=req.message,
        lead=lead,
        current_stage=req.stage,
    )
    return {
        "reply":     response.reply,
        "new_stage": response.new_stage,
        "escalate":  response.escalate,
    }

@app.post("/api/v2/sales/migrate-to-whatsapp")
async def sales_migrate_to_whatsapp(req: WAConversionRequest):
    """Send the LinkedIn DM asking the lead for their WhatsApp number."""
    def _run():
        from enterprise.sales.whatsapp_conversion_flow import get_whatsapp_flow
        from enterprise.crm.models import _CRM_DB_PATH, Lead
        import sqlite3
        try:
            conn = sqlite3.connect(str(_CRM_DB_PATH))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE lead_id=?", (req.lead_id,)).fetchone()
            conn.close()
            d = dict(row)
            d["pitch_sent"] = bool(d["pitch_sent"])
            lead = Lead.from_dict(d)
            return get_whatsapp_flow().initiate_migration(lead)
        except Exception as e:
            return False
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, _run)
    return {"success": success, "lead_id": req.lead_id}

@app.get("/api/v2/sales/conversations")
async def sales_conversations():
    """List active WhatsApp sales conversations."""
    try:
        import json
        from pathlib import Path
        conv_file = Path(__file__).parent.parent.parent / ".credentials" / "wa_conversations.json"
        if not conv_file.exists():
            return {"conversations": []}
        convs = json.loads(conv_file.read_text())
        return {
            "conversations": [
                {
                    "phone":      phone,
                    "name":       state.get("name"),
                    "stage":      state.get("stage"),
                    "updated_at": state.get("updated_at"),
                    "turns":      len(state.get("history", [])) // 2,
                }
                for phone, state in convs.items()
            ]
        }
    except Exception as exc:
        return {"conversations": [], "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# BUSINESS ORCHESTRATOR — Option C: Full Autonomous Business
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v2/orchestrator/start")
async def orchestrator_start():
    """Start the autonomous business orchestrator loop."""
    from enterprise.orchestration.business_orchestrator import get_orchestrator
    orc = get_orchestrator(ws_emit=ws_manager.broadcast)
    if orc.is_running:
        return {"status": "already_running"}
    orc.start()
    return {"status": "started", "interval_seconds": orc._interval}

@app.post("/api/v2/orchestrator/stop")
async def orchestrator_stop():
    """Stop the business orchestrator."""
    from enterprise.orchestration.business_orchestrator import get_orchestrator
    get_orchestrator().stop()
    return {"status": "stopped"}

@app.post("/api/v2/orchestrator/run-now")
async def orchestrator_run_now():
    """Run one orchestrator cycle immediately (synchronous)."""
    def _run():
        from enterprise.orchestration.business_orchestrator import get_orchestrator
        return get_orchestrator().run_cycle_now()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return {
        "cycle":           result.cycle,
        "actions_run":     result.actions_run,
        "leads_generated": result.leads_generated,
        "messages_sent":   result.messages_sent,
        "errors":          result.errors,
        "duration_s":      round(result.duration_s, 2),
    }

@app.get("/api/v2/orchestrator/status")
async def orchestrator_status():
    """Return orchestrator running status and last cycle summary."""
    from enterprise.orchestration.business_orchestrator import get_orchestrator
    return get_orchestrator().get_status()

@app.get("/api/v2/orchestrator/history")
async def orchestrator_history(n: int = 10):
    """Return the last N orchestrator cycles."""
    from enterprise.orchestration.business_orchestrator import get_orchestrator
    return {"history": get_orchestrator().get_history(n=n)}

@app.get("/api/v2/orchestrator/decision")
async def orchestrator_decision():
    """Ask the DecisionEngine what it would do right now (no execution)."""
    from enterprise.orchestration.decision_engine import get_decision_engine
    engine = get_decision_engine()
    ctx    = engine.build_context()
    result = engine.decide(ctx)
    return {
        "priority_actions": result.priority_actions,
        "reasoning":        result.reasoning,
        "context": {
            "hour":                  ctx.hour,
            "posts_today":           ctx.posts_today,
            "hot_leads_waiting":     ctx.hot_leads_waiting,
            "active_wa_convs":       ctx.active_wa_convs,
            "dms_sent_today":        ctx.dms_sent_today,
            "pitched_leads_stale":   ctx.pitched_leads_stale,
            "report_due":            ctx.report_due,
        },
    }


# ── Serve Next.js UI (production build) ──────────────────────────────────── #

ui_out = Path(__file__).parent.parent.parent / "dashboard" / "out"
if ui_out.exists():
    app.mount("/", StaticFiles(directory=str(ui_out), html=True), name="ui")


# ── Entry Point ───────────────────────────────────────────────────────────── #

def start_enterprise_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(
        "enterprise.api.enterprise_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    start_enterprise_server()
