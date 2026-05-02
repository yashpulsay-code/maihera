"""
MAIHERA Briefing Routes
Manual trigger for morning briefing — used for testing.
In Phase 5, this is triggered automatically on session start.
"""

import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/briefing', tags=['briefing'])

_nudge_service = None


def set_dependencies(nudge_service):
    global _nudge_service
    _nudge_service = nudge_service


@router.post('/trigger')
async def trigger_briefing():
    """Manually trigger the morning briefing."""
    if not _nudge_service:
        raise HTTPException(status_code=503, detail='Nudge service not initialized')
    import asyncio
    asyncio.create_task(_nudge_service.trigger_morning_briefing())
    return {'status': 'briefing triggered'}


@router.delete('/reset')
async def reset_briefing():
    """
    Reset today's briefing log so it can be triggered again.
    Useful during testing.
    """
    if not _nudge_service:
        raise HTTPException(status_code=503, detail='Nudge service not initialized')
    try:
        today = __import__('datetime').date.today().isoformat()
        _nudge_service._db.connection.execute(
            "DELETE FROM briefing_log WHERE date_key = ?", (today,)
        )
        _nudge_service._db.connection.commit()
        return {'status': 'briefing log reset for today'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))