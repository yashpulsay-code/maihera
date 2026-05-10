"""
MAIHERA API Routes — Orchestrator
Submit tasks, check status, cancel tasks,
and query pending confirmations.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])

_orchestrator = None
_confirmation_broker = None


def set_dependencies(orchestrator, confirmation_broker):
    global _orchestrator, _confirmation_broker
    _orchestrator = orchestrator
    _confirmation_broker = confirmation_broker


# ── Request / Response Models ─────────────────────────────────────

class SubmitTaskRequest(BaseModel):
    action_type: str
    tool_name: str
    payload: dict
    explicit_instruction: bool = False


class SubmitTaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    action_type: str
    tool_name: str
    status: str
    requires_confirmation: bool
    confirmation_id: Optional[str]
    retry_count: int
    last_error: Optional[str]
    result: Optional[str]
    verified: bool
    created_at: str
    completed_at: Optional[str]


class PendingConfirmationsResponse(BaseModel):
    count: int
    confirmations: list[dict]


# ── Routes ────────────────────────────────────────────────────────

@router.post("/submit", response_model=SubmitTaskResponse)
async def submit_task(request: SubmitTaskRequest):
    """
    Submit a task for execution via the Orchestrator.
    If the tool requires confirmation, the task enters
    pending_confirmation state and Yash is notified.
    If always_allow, the task executes immediately.
    """
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )
    try:
        task_id = await _orchestrator.submit(
            action_type=request.action_type,
            tool_name=request.tool_name,
            payload=request.payload,
            explicit_instruction=request.explicit_instruction,
        )
        task = await _orchestrator.get_status(task_id)
        status = task["status"] if task else "submitted"
        message = (
            "Task queued for execution."
            if status == "queued"
            else "Awaiting your confirmation, Boss."
            if status == "pending_confirmation"
            else f"Task status: {status}"
        )
        return SubmitTaskResponse(
            task_id=task_id,
            status=status,
            message=message
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("submit_task error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get the current status of a submitted task."""
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )
    task = await _orchestrator.get_status(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found."
        )
    return TaskStatusResponse(
        task_id=task["id"],
        action_type=task["action_type"],
        tool_name=task["tool_name"],
        status=task["status"],
        requires_confirmation=bool(task["requires_confirmation"]),
        confirmation_id=task.get("confirmation_id"),
        retry_count=task["retry_count"],
        last_error=task.get("last_error"),
        result=task.get("result"),
        verified=bool(task.get("verified", 0)),
        created_at=task["created_at"],
        completed_at=task.get("completed_at"),
    )


@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a pending or queued task."""
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )
    await _orchestrator.cancel(task_id)
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/confirmations", response_model=PendingConfirmationsResponse)
async def get_pending_confirmations():
    """Return all pending confirmations awaiting Yash's response."""
    if not _confirmation_broker:
        raise HTTPException(
            status_code=503,
            detail="ConfirmationBroker not initialized."
        )
    pending = _confirmation_broker.db.get_pending_confirmations()
    return PendingConfirmationsResponse(
        count=len(pending),
        confirmations=pending
    )


@router.get("/tasks")
async def list_tasks(status: Optional[str] = None, limit: int = 20):
    """List orchestrator tasks, optionally filtered by status."""
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )
    tasks = _orchestrator.db.list_orchestrator_tasks(
        status=status, limit=limit
    )
    return {"count": len(tasks), "tasks": tasks}


@router.get("/tools")
async def list_tools():
    """List all registered tools with their autonomy tiers."""
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )
    tools = [
        {
            "name": t.name,
            "action_type": t.action_type,
            "autonomy_tier": t.autonomy_tier.value,
            "timeout_seconds": t.timeout_seconds,
            "max_retries": t.max_retries,
        }
        for t in _orchestrator._tool_registry.values()
    ]
    return {"count": len(tools), "tools": tools}