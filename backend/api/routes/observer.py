"""
MAIHERA Observer Routes
Exposes system observer state, file watcher config,
and avoidance detector status via REST API.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/observer", tags=["observer"])

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "observer_config.json"

_system_observer = None
_file_watcher    = None
_avoidance_detector = None


def set_dependencies(system_observer, file_watcher, avoidance_detector):
    global _system_observer, _file_watcher, _avoidance_detector
    _system_observer    = system_observer
    _file_watcher       = file_watcher
    _avoidance_detector = avoidance_detector


@router.get("/status")
async def observer_status():
    """Current observer state — active app, context, watched folders."""
    return {
        "observer_running": (
            _system_observer.is_running if _system_observer else False
        ),
        "current_context": (
            _system_observer._current_context
            if _system_observer else None
        ),
        "current_app": (
            _system_observer._current_label
            if _system_observer else None
        ),
        "file_watcher_running": (
            _file_watcher.is_running if _file_watcher else False
        ),
        "watched_folders": (
            _file_watcher.watched_folders if _file_watcher else []
        ),
    }


@router.get("/config")
async def get_observer_config():
    """Return current observer_config.json contents."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found.")
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500, detail=f"Config malformed: {e}"
        )


@router.put("/config/folders")
async def update_watched_folders(payload: dict):
    """
    Update watched_folders in observer_config.json.
    File watcher reloads within 60 seconds automatically.
    payload: { "folders": ["C:\\path1", "C:\\path2"] }
    """
    folders = payload.get("folders")
    if not isinstance(folders, list):
        raise HTTPException(
            status_code=400,
            detail="payload must be { folders: string[] }"
        )

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        config["watched_folders"] = folders

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        logger.info(
            "Observer config updated — %d watched folders.", len(folders)
        )
        return {
            "status": "updated",
            "watched_folders": folders,
            "note": "File watcher reloads within 60 seconds."
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update config: {e}"
        )


@router.put("/config/whitelist")
async def update_app_whitelist(payload: dict):
    """
    Update app_whitelist in observer_config.json.
    Observer reloads within 60 seconds automatically.
    payload: { "whitelist": [{"process": "X.exe", "context": "coding", "label": "X"}] }
    """
    whitelist = payload.get("whitelist")
    if not isinstance(whitelist, list):
        raise HTTPException(
            status_code=400,
            detail="payload must be { whitelist: AppEntry[] }"
        )

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        config["app_whitelist"] = whitelist

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        logger.info(
            "Observer config updated — %d whitelisted apps.",
            len(whitelist)
        )
        return {
            "status": "updated",
            "app_whitelist": whitelist,
            "note": "Observer reloads within 60 seconds."
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update config: {e}"
        )