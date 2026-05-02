"""
MAIHERA API — Main Application
FastAPI entry point with lifespan management.
Initializes all services on startup, shuts down cleanly.
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / '.env')

logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

_brain_service = None
_neo4j_driver = None
_llm_router = None
_classifier = None
_decay_worker = None
_ws_manager = None
_voice_service = None
_nudge_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _brain_service, _neo4j_driver, _llm_router
    global _classifier, _decay_worker, _ws_manager
    global _voice_service, _nudge_service

    logger.info("=" * 50)
    logger.info("MAIHERA starting up...")
    logger.info("=" * 50)

    try:
        from api.websocket_manager import WebSocketManager
        _ws_manager = WebSocketManager()
        logger.info("[1/8] WebSocket manager ready.")

        from brain.brain_service import get_brain_service
        _brain_service, _neo4j_driver = get_brain_service()
        logger.info("[2/8] Brain service ready.")

        from llm.router import LLMRouter
        _llm_router = LLMRouter()
        logger.info("[3/8] LLM router ready.")

        from brain.classifier import NodeClassifier
        _classifier = NodeClassifier(llm_router=_llm_router)
        logger.info("[4/8] Node classifier ready.")

        from api.routes import brain as brain_routes
        from api.routes import chat as chat_routes
        from api.routes.voice import router as voice_router
        brain_routes.set_dependencies(_brain_service, _ws_manager)
        chat_routes.set_dependencies(
            _brain_service, _llm_router, _classifier
        )
        app.include_router(voice_router)
        logger.info("[5/8] Route dependencies injected.")

        from workers.decay_worker import DecayWorker
        _decay_worker = DecayWorker(_brain_service)
        _decay_worker.start()
        logger.info("[6/8] Decay worker started.")
        
        from services.voice_service import VoiceService
        _voice_service = VoiceService()
        _voice_service.set_ws_manager(_ws_manager)
        _voice_service.start()
        logger.info("[7/8] Voice service started.")

        from services.nudge_service import NudgeService
        _nudge_service = NudgeService(
            brain_service=_brain_service,
            voice_service=_voice_service,
            db_manager=_brain_service.db
        )
        _nudge_service.set_ws_manager(_ws_manager)
        _nudge_service.set_llm_router(_llm_router)
        _decay_worker.add_nudge_job(_nudge_service)
        logger.info("[8/8] Nudge service ready.")

        logger.info("=" * 50)
        logger.info("MAIHERA is live. Boss, I am ready.")
        logger.info("=" * 50)

        yield

    finally:
        logger.info("MAIHERA shutting down...")
        if _decay_worker:
            _decay_worker.stop()
            logger.info("Decay worker stopped.")
        if _voice_service:
            _voice_service.stop()
            logger.info("Voice service stopped.")
        if _neo4j_driver:
            _neo4j_driver.close()
            logger.info("Neo4j driver closed.")
        logger.info("MAIHERA shutdown complete.")


app = FastAPI(
    title="MAIHERA",
    description="M.A.I.H.E.R.A — Mai He Raja, Mai He Rani",
    version="0.2.0-phase2",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "app://.",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes.brain import router as brain_router
from api.routes.chat import router as chat_router

app.include_router(brain_router)
app.include_router(chat_router)


@app.websocket("/ws/brain")
async def websocket_brain(websocket: WebSocket):
    if _ws_manager is None:
        await websocket.close(code=1011)
        return

    await _ws_manager.connect(websocket)

    try:
        # Send full graph snapshot on connect
        if _brain_service:
            graph = _brain_service.get_full_graph()
            await _ws_manager.send_full_sync(graph)
            await _ws_manager.send_system_status("watching")

        # Inbound message loop
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                payload = msg.get("payload", {})

                if msg_type == "session_start":
                    logger.info("session_start received.")
                    if _nudge_service:
                        asyncio.create_task(
                            _nudge_service.trigger_morning_briefing()
                        )

                elif msg_type == "chat":
                    logger.info("chat message received.")
                    # Phase 2: chat handler goes here (Step 14)

                elif msg_type == "energy_checkin":
                    level = payload.get("level")
                    logger.info("energy_checkin: %s", level)
                    if level is not None and _brain_service:
                        _brain_service.update_self_node_energy(int(level))
                        if _nudge_service:
                            from services.nudge_service import low_energy_mode
                            import services.nudge_service as ns
                            ns.low_energy_mode = int(level) <= 3
                        await _ws_manager.send_system_status("watching")

                elif msg_type == "focus_mode":
                    active = payload.get("active", False)
                    session_id = payload.get("session_id")
                    energy_level = payload.get("energy_level")
                    logger.info(
                        "focus_mode: active=%s session=%s",
                        active, session_id
                    )
                    if _nudge_service and _brain_service:
                        if active and session_id:
                            _brain_service.db.start_focus_session(
                                session_id=session_id,
                                energy_level=energy_level
                            )
                            await _ws_manager.send_focus_mode_change(
                                active=True,
                                session_id=session_id
                            )
                        elif not active and session_id:
                            asyncio.create_task(
                                _nudge_service.deliver_focus_session_summary(
                                    session_id
                                )
                            )
                            await _ws_manager.send_focus_mode_change(
                                active=False,
                                session_id=None
                            )

                elif msg_type == "speech_next":
                    logger.info("speech_next received.")
                    # Phase 2: voice queue drain goes here (Step 9)

                else:
                    logger.debug("Unknown WS type: %s", msg_type)

            except json.JSONDecodeError:
                logger.warning("Non-JSON WebSocket message received.")

    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket)

@app.get("/health")
async def health():
    return {
        "status": "live",
        "version": "0.2.0-phase2",
        "message": "MAIHERA is running, Boss."
    }


@app.get("/health/full")
async def health_full():
    health_data = {"status": "live", "services": {}}

    if _brain_service:
        try:
            stats = _brain_service.get_stats()
            health_data["services"]["brain"] = {
                "status": "ok", "stats": stats
            }
        except Exception as e:
            health_data["services"]["brain"] = {
                "status": "error", "error": str(e)
            }
    else:
        health_data["services"]["brain"] = {
            "status": "not initialized"
        }

    if _llm_router:
        health_data["services"]["llm_router"] = {
            "status": "ok",
            "quota": _llm_router.get_quota_status()
        }
    else:
        health_data["services"]["llm_router"] = {
            "status": "not initialized"
        }

    if _decay_worker:
        health_data["services"]["decay_worker"] = {
            "status": "ok",
            "stats": _decay_worker.get_stats()
        }
    else:
        health_data["services"]["decay_worker"] = {
            "status": "not initialized"
        }

    if _ws_manager:
        health_data["services"]["websocket"] = {
            "status": "ok",
            "connections": _ws_manager.connection_count
        }

    return health_data