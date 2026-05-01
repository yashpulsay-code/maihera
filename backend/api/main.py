"""
MAIHERA API — Main Application
FastAPI entry point with lifespan management.
Initializes all services on startup, shuts down cleanly.
"""

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _brain_service, _neo4j_driver, _llm_router
    global _classifier, _decay_worker, _ws_manager

    logger.info("=" * 50)
    logger.info("MAIHERA starting up...")
    logger.info("=" * 50)

    try:
        from api.websocket_manager import WebSocketManager
        _ws_manager = WebSocketManager()
        logger.info("[1/6] WebSocket manager ready.")

        from brain.brain_service import get_brain_service
        _brain_service, _neo4j_driver = get_brain_service()
        logger.info("[2/6] Brain service ready.")

        from llm.router import LLMRouter
        _llm_router = LLMRouter()
        logger.info("[3/6] LLM router ready.")

        from brain.classifier import NodeClassifier
        _classifier = NodeClassifier(llm_router=_llm_router)
        logger.info("[4/6] Node classifier ready.")

        from api.routes import brain as brain_routes
        from api.routes import chat as chat_routes
        brain_routes.set_dependencies(_brain_service, _ws_manager)
        chat_routes.set_dependencies(
            _brain_service, _llm_router, _classifier
        )
        logger.info("[5/6] Route dependencies injected.")

        from workers.decay_worker import DecayWorker
        _decay_worker = DecayWorker(_brain_service)
        _decay_worker.start()
        logger.info("[6/6] Decay worker started.")

        logger.info("=" * 50)
        logger.info("MAIHERA is live. Boss, I am ready.")
        logger.info("=" * 50)

        yield

    finally:
        logger.info("MAIHERA shutting down...")
        if _decay_worker:
            _decay_worker.stop()
            logger.info("Decay worker stopped.")
        if _neo4j_driver:
            _neo4j_driver.close()
            logger.info("Neo4j driver closed.")
        logger.info("MAIHERA shutdown complete.")


app = FastAPI(
    title="MAIHERA",
    description="M.A.I.H.E.R.A — Mai He Raja, Mai He Rani",
    version="0.1.0-phase1",
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
        if _brain_service:
            graph = _brain_service.get_full_graph()
            await _ws_manager.broadcast_graph_update(
                graph, event_type="initial_graph"
            )
        while True:
            data = await websocket.receive_text()
            logger.debug("WebSocket message: %s", data[:50])
    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket)


@app.get("/health")
async def health():
    return {
        "status": "live",
        "version": "0.1.0-phase1",
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