"""
MAIHERA Calendar Routes
Endpoints for Google Calendar integration and event management.
"""

import logging
from fastapi import APIRouter, HTTPException
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calendar", tags=["calendar"])

_calendar_service = None
_brain_service = None


def set_dependencies(calendar_service, brain_service):
    global _calendar_service, _brain_service
    _calendar_service = calendar_service
    _brain_service = brain_service


@router.post("/sync")
async def sync_calendar_events(days_ahead: int = 14):
    """
    Sync upcoming Google Calendar events to the brain graph.
    Creates or updates event nodes and links them to persons/projects.
    """
    if not _calendar_service or not _brain_service:
        raise HTTPException(
            status_code=503,
            detail="Calendar or brain service not initialized"
        )

    try:
        summary = await _calendar_service.sync_to_brain(_brain_service)
        return {
            "status": "success",
            "message": f"Synced {summary['created']} created, "
                       f"{summary['updated']} updated, "
                       f"{summary['linked']} linked, "
                       f"{summary['unlinked']} unlinked events",
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Calendar sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events/today")
async def get_todays_events():
    """Get today's calendar events."""
    if not _calendar_service:
        raise HTTPException(
            status_code=503,
            detail="Calendar service not initialized"
        )

    try:
        events = await _calendar_service.get_todays_events()
        return {
            "status": "success",
            "events": events,
            "count": len(events)
        }
    except Exception as e:
        logger.error(f"Failed to fetch today's events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/worker/stats")
async def get_worker_stats():
    """Return calendar polling worker statistics."""
    if not _calendar_service:
        return {"status": "not initialized"}
    # Stats accessed via the service — worker stats injected separately
    return {"status": "running", "message": "Calendar worker active"}

@router.get("/events/upcoming")
async def get_upcoming_events(days_ahead: int = 14):
    """Get upcoming calendar events."""
    if not _calendar_service:
        raise HTTPException(
            status_code=503,
            detail="Calendar service not initialized"
        )

    try:
        events = await _calendar_service.fetch_upcoming_events(days_ahead)
        return {
            "status": "success",
            "events": events,
            "count": len(events),
            "days_ahead": days_ahead
        }
    except Exception as e:
        logger.error(f"Failed to fetch upcoming events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/service/status")
async def get_calendar_service_status():
    """Check if Google Calendar service is properly configured."""
    if not _calendar_service:
        return {"status": "error", "message": "Calendar service not initialized"}

    try:
        service = _calendar_service.get_service()
        # Test the service with a simple API call
        service.calendarList().list().execute()
        return {"status": "connected", "message": "Google Calendar connected"}
    except Exception as e:
        logger.error(f"Calendar service error: {e}")
        return {"status": "error", "message": str(e)}