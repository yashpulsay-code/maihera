"""
MAIHERA API Routes — Skills
List available skills and execute them via the Orchestrator.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])

_orchestrator = None


def set_dependencies(orchestrator):
    global _orchestrator
    _orchestrator = orchestrator


# ── Models ────────────────────────────────────────────────────────

class ExecuteSkillRequest(BaseModel):
    skill_id: str
    payload: dict
    # payload provides seed values for step 0 template resolution
    # e.g. {"title": "Presence bug", "body": "...", "repo": "Presence"}


class ExecuteSkillResponse(BaseModel):
    skill_id: str
    skill_name: str
    status: str
    steps_completed: int
    steps_total: int
    error: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────

@router.get("/")
async def list_skills():
    """List all available skills with their steps."""
    from orchestrator.skill_registry import list_skills as _list
    return {"count": len(_list()), "skills": _list()}


@router.get("/{skill_id}")
async def get_skill(skill_id: str):
    """Get a single skill definition by ID."""
    from orchestrator.skill_registry import get_skill as _get
    skill = _get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_id}' not found."
        )
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "steps": [
            {
                "index": s.index,
                "tool_name": s.tool_name,
                "action_type": s.action_type,
                "on_failure": s.on_failure.value,
                "depends_on": s.depends_on,
            }
            for s in skill.steps
        ],
    }


@router.post("/execute", response_model=ExecuteSkillResponse)
async def execute_skill(request: ExecuteSkillRequest):
    """
    Execute a skill by ID.
    The payload provides seed values for the first step's
    template resolution. Skills execute asynchronously —
    confirmation prompts will appear in chat if required.
    """
    if not _orchestrator:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not initialized."
        )

    from orchestrator.skill_registry import get_skill, SkillExecutor
    skill = get_skill(request.skill_id)
    if not skill:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{request.skill_id}' not found."
        )

    try:
        executor = SkillExecutor(orchestrator=_orchestrator)
        result = await executor.execute(
            skill=skill,
            initial_payload=request.payload,
        )
        completed = sum(
            1 for s in result.steps if s.status == "completed"
        )
        return ExecuteSkillResponse(
            skill_id=result.skill_id,
            skill_name=result.skill_name,
            status=result.status,
            steps_completed=completed,
            steps_total=len(skill.steps),
            error=result.error,
        )
    except Exception as e:
        logger.error("execute_skill error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))