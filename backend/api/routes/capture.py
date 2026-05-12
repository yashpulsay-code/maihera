"""
MAIHERA API Routes — Context Capture
Zero-friction thought capture from any device.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/capture", tags=["capture"])

_capture_service = None


def set_dependencies(capture_service):
    global _capture_service
    _capture_service = capture_service


class CaptureRequest(BaseModel):
    text: str
    project_hint: Optional[str] = None
    workspace: str = "personal"


class TriageRequest(BaseModel):
    action: str        # promote | merge | archive
    capture_id: str
    target_node_id: Optional[str] = None   # required for merge
    reason: Optional[str] = None           # optional for archive


@router.post("/")
async def capture_thought(request: CaptureRequest):
    """
    Capture a thought and stage it for triage.
    Returns node summary and confirmation message.
    """
    if not _capture_service:
        raise HTTPException(
            status_code=503,
            detail="Capture service not initialized."
        )
    if not request.text or len(request.text.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Capture text too short."
        )
    result = await _capture_service.capture(
        raw_text=request.text,
        project_hint=request.project_hint,
        workspace=request.workspace,
    )
    return result


@router.get("/staged")
async def get_staged():
    """Return all staged captures awaiting triage."""
    if not _capture_service:
        raise HTTPException(
            status_code=503,
            detail="Capture service not initialized."
        )
    captures = _capture_service.get_staged_captures()
    return {
        "count": len(captures),
        "captures": captures,
    }


@router.post("/triage")
async def triage_capture(request: TriageRequest):
    """
    Triage a staged capture.
    action: promote | merge | archive
    """
    if not _capture_service:
        raise HTTPException(
            status_code=503,
            detail="Capture service not initialized."
        )

    if request.action == "promote":
        success = _capture_service.promote(request.capture_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Capture {request.capture_id} not found or already triaged."
            )
        return {"status": "promoted", "capture_id": request.capture_id}

    elif request.action == "merge":
        if not request.target_node_id:
            raise HTTPException(
                status_code=400,
                detail="target_node_id required for merge."
            )
        success = _capture_service.merge(
            request.capture_id, request.target_node_id
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Capture or target node not found."
            )
        return {
            "status": "merged",
            "capture_id": request.capture_id,
            "merged_into": request.target_node_id,
        }

    elif request.action == "archive":
        success = _capture_service.archive(
            request.capture_id,
            reason=request.reason or "Manual archive",
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Capture {request.capture_id} not found."
            )
        return {"status": "archived", "capture_id": request.capture_id}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{request.action}'. Use: promote | merge | archive"
        )


@router.get("/count")
async def get_staged_count():
    """Return count of staged captures — used by left panel badge."""
    if not _capture_service:
        raise HTTPException(
            status_code=503,
            detail="Capture service not initialized."
        )
    count = _capture_service.get_staged_count()
    briefing_text = _capture_service.get_triage_briefing_text()
    return {"count": count, "briefing_text": briefing_text}