"""
MAIHERA Gmail Routes
Send-only email endpoints. All emails go to Yash's main account.
Never sends autonomously — explicit command only.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gmail", tags=["gmail"])

_brain_service = None


def set_dependencies(brain_service):
    global _brain_service
    _brain_service = brain_service


class SendEmailRequest(BaseModel):
    subject: str
    body: str
    html: bool = False


class SendWithAttachmentRequest(BaseModel):
    subject: str
    body: str
    attachment_path: str
    filename: Optional[str] = None


@router.post("/send")
async def send_email(request: SendEmailRequest):
    """
    Send a plain or HTML email to Yash's main account.
    Always sends from maihera.ai@gmail.com to yashpulsay@gmail.com.
    """
    from services.gmail_service import gmail_service
    try:
        result = await gmail_service.send(
            subject=request.subject,
            body=request.body,
            html=request.html
        )
        return {"status": "sent", "result": result}
    except Exception as e:
        logger.error("Gmail send failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/brain-export")
async def send_brain_export():
    """
    Send the latest brain export JSON as email attachment.
    Locates the most recent backup file automatically.
    """
    if not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )

    from services.gmail_service import gmail_service
    from pathlib import Path
    import os

    backup_dir = Path(__file__).parent.parent.parent.parent / 'backups'
    if not backup_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="No backups directory found"
        )

    exports = sorted(backup_dir.glob("maihera_brain_*.json"), reverse=True)
    if not exports:
        # Trigger a fresh export first
        export_path = _brain_service.export_to_json()
    else:
        export_path = str(exports[0])

    try:
        result = await gmail_service.send_brain_export(export_path)
        return {"status": "sent", "export": export_path, "result": result}
    except Exception as e:
        logger.error("Brain export email failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/analysis-findings")
async def send_analysis_findings():
    """
    Send the latest Presence analysis findings as email.
    Fetches finding nodes from brain and formats as email.
    """
    if not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )

    from services.gmail_service import gmail_service

    # Fetch analysis finding nodes from brain
    all_nodes = (
        _brain_service.list_nodes(node_type='decision') +
        _brain_service.list_nodes(node_type='feature') +
        _brain_service.list_nodes(node_type='insight')
    )

    findings = [
        n for n in all_nodes
        if n.get('source_ref') == 'github:yashpulsay-code/Presence'
    ]

    if not findings:
        raise HTTPException(
            status_code=404,
            detail="No analysis findings found in brain"
        )

    # Convert nodes to finding format
    formatted = [
        {
            "type": n.get('type', 'insight'),
            "label": n.get('label', ''),
            "description": n.get('description', ''),
            "evidence": n.get('evidence', []),
            "confidence": n.get('importance', 0.5),
        }
        for n in sorted(findings, key=lambda x: x.get('importance', 0), reverse=True)
    ]

    try:
        result = await gmail_service.send_analysis_findings(formatted)
        return {
            "status": "sent",
            "findings_count": len(formatted),
            "result": result
        }
    except Exception as e:
        logger.error("Analysis findings email failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def gmail_status():
    """Check if Gmail service is properly authenticated."""
    from services.google_auth_service import google_auth
    try:
        authenticated = google_auth.is_authenticated()
        return {
            "status": "connected" if authenticated else "not authenticated",
            "from": "maihera.ai@gmail.com",
            "to": "yashpulsay@gmail.com",
            "mode": "send-only"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}