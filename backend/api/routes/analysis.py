"""
MAIHERA Analysis Routes
Endpoints for codebase analysis operations.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["analysis"])

_brain_service = None
_llm_router = None


def set_dependencies(brain_service, llm_router):
    global _brain_service, _llm_router
    _brain_service = brain_service
    _llm_router = llm_router


@router.post("/presence/run")
async def run_presence_analysis():
    """
    Trigger full analysis of Presence codebase.
    Returns summary or cooldown message.
    """
    if not _brain_service or not _llm_router:
        raise HTTPException(
            status_code=503,
            detail="Brain service or LLM router not initialized"
        )

    from services.codebase_analysis_service import codebase_analysis_service

    result = await codebase_analysis_service.run_first_analysis(
        _brain_service,
        _llm_router
    )

    if result.get("status") == "cooldown":
        last_run = codebase_analysis_service._get_last_run_timestamp(_brain_service)
        if last_run:
            next_available = (
                datetime.fromisoformat(last_run) + timedelta(hours=48)
            ).isoformat()
            return {
                "status": "cooldown",
                "message": f"Cooldown active. Next run available at {next_available}"
            }
        return {
            "status": "cooldown",
            "message": "Cooldown active, next run time unknown"
        }

    return result


@router.get("/presence/status")
async def get_presence_analysis_status():
    """Return last run timestamp and node count from github_state."""
    if not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )

    from services.codebase_analysis_service import codebase_analysis_service

    last_run = codebase_analysis_service._get_last_run_timestamp(_brain_service)
    cooldown_ok = codebase_analysis_service._check_cooldown(_brain_service)

    node_count = 0
    if last_run:
        try:
            projects = _brain_service.list_nodes(node_type="project")
            presence_project_id = None
            for p in projects:
                label = p.get("label", "").lower()
                if "presence" in label or "github" in label:
                    presence_project_id = p.get("id")
                    break

            if presence_project_id:
                nodes = _brain_service.list_nodes(
                    project_id=presence_project_id
                )
                node_count = sum(
                    1 for n in nodes
                    if n.get('source_ref') == 'github:yashpulsay-code/Presence'
                )
        except Exception as e:
            logger.warning(f"Could not count analysis nodes: {e}")

    return {
        "last_run": last_run,
        "cooldown_active": not cooldown_ok,
        "nodes_created": node_count
    }

@router.get("/presence/drip-status")
async def get_drip_status():
    """Return current drip state — how many findings surfaced vs remaining."""
    if not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )
    from services.drip_service import drip_service
    return drip_service.get_drip_status(_brain_service)


@router.post("/presence/drip-reset")
async def reset_drip():
    """
    Reset drip state — all findings become unsurfaced.
    Use after a new analysis pass generates fresh findings.
    """
    if not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )
    from services.drip_service import drip_service
    drip_service.reset(_brain_service)
    return {"status": "reset", "message": "All findings marked unsurfaced."}