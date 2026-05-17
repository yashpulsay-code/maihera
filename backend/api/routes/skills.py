"""
MAIHERA Skills Routes — stub
Full implementation in Phase 4. Stub prevents import error on startup.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/skills", tags=["skills"])

_orchestrator = None


def set_dependencies(orchestrator) -> None:
    global _orchestrator
    _orchestrator = orchestrator


@router.get("/")
async def list_skills():
    if _orchestrator is None:
        return {"skills": []}
    try:
        registry = getattr(_orchestrator, "skill_registry", None)
        if registry:
            return {"skills": list(registry.keys())}
        return {"skills": []}
    except Exception:
        return {"skills": []}