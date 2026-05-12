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
_calendar_service = None
_calendar_worker  = None
_github_service = None
_github_worker  = None
_standup_active: bool = False
_standup_question_index: int = 0
_orchestrator = None
_confirmation_broker = None

async def _handle_ws_chat(
    text: str,
    context_node_id: str | None,
    brain_service,
    llm_router,
    ws_manager,
    voice_service,
    confirmation_broker=None,
) -> None:
    """Handle a chat message received via WebSocket."""
    global _standup_active, _standup_question_index

    # ── Confirmation routing — checked before everything else ─────
    if _confirmation_broker:
        consumed = await _confirmation_broker.resolve(
            text=text, resolved_by="text"
        )
        if consumed:
            await ws_manager.send_system_status("watching")
            return

    try:
        await ws_manager.send_system_status("thinking")

        # ── Standup routing ───────────────────────────────────────
        from services.standup_service import standup_service

        if _standup_active:
            # Process this message as a standup answer
            result = await standup_service.process_answer(
                brain_service=brain_service,
                llm_router=llm_router,
                question_index=_standup_question_index,
                answer=text
            )
            logger.info(
                "Standup Q%d processed: %s",
                _standup_question_index, result.get('summary', '')
            )

            # Get next question
            next_q = standup_service.get_next_question(
                brain_service, _standup_question_index
            )
            _standup_question_index += 1

            if next_q:
                # Ask next question
                await voice_service.enqueue_speech(
                    text=next_q,
                    node_ids=[],
                    priority="normal"
                )
                await ws_manager.send_maihera_speak(
                    text=next_q,
                    node_ids=[],
                    priority="normal"
                )
            else:
                # Standup complete
                _standup_active = False
                _standup_question_index = 0
                standup_service.mark_complete(brain_service)
                closing = (
                    "Got it Boss. Standup done. "
                    "I'll flag anything that needs attention as the day develops."
                )
                await voice_service.enqueue_speech(
                    text=closing,
                    node_ids=[],
                    priority="normal"
                )
                await ws_manager.send_maihera_speak(
                    text=closing,
                    node_ids=[],
                    priority="normal"
                )

            await ws_manager.send_system_status("watching")
            return

        # ── Normal chat routing ───────────────────────────────────

        # Check if this message is triggering standup start
        # (only if standup should run today and hasn't started yet)
        trigger_words = ['standup', 'stand up', 'check in', 'daily']
        if (
            any(w in text.lower() for w in trigger_words)
            and standup_service.should_run_today(brain_service)
        ):
            _standup_active = True
            _standup_question_index = 0
            first_q = standup_service.get_first_question()
            await voice_service.enqueue_speech(
                text=first_q,
                node_ids=[],
                priority="normal"
            )
            await ws_manager.send_maihera_speak(
                text=first_q,
                node_ids=[],
                priority="normal"
            )
            await ws_manager.send_system_status("watching")
            return

        # Standard conversation
        from llm.persona import build_system_prompt

        self_node = None
        active_projects = []

        projects = brain_service.list_nodes(node_type='project')
        active_projects = [
            p for p in projects if p.get('status') == 'active'
        ]

        all_persons = brain_service.list_nodes(node_type='person')
        for p in all_persons:
            if p.get('label') == 'Yash':
                self_node = p
                break

        high_signal_nodes = brain_service.get_high_signal_nodes(
            importance_threshold=0.5,
            attention_threshold=0.2
        )

        extra_context = ""
        if context_node_id:
            node = brain_service.get_node(context_node_id)
            if node:
                extra_context = (
                    f"\n\nThe user is asking about this specific node: "
                    f"'{node.get('label')}' (type: {node.get('type')}, "
                    f"status: {node.get('status')}). "
                    f"Description: {node.get('description', 'none')}."
                )

        system_prompt = build_system_prompt(
            self_node=self_node,
            active_projects=active_projects,
            high_signal_nodes=high_signal_nodes
        ) + extra_context

        response_text = await llm_router.route(
            task_type='conversation',
            messages=[{"role": "user", "content": text}],
            system_prompt=system_prompt,
            max_tokens=300
        )

        if not response_text:
            return

        if voice_service:
            await voice_service.enqueue_speech(
                text=response_text,
                node_ids=[context_node_id] if context_node_id else [],
                priority="normal"
            )

        await ws_manager.send_system_status("watching")

    except Exception as e:
        logger.error("WS chat handler error: %s", e)
        await ws_manager.send_system_status("watching")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _brain_service, _neo4j_driver, _llm_router
    global _classifier, _decay_worker, _ws_manager
    global _voice_service, _nudge_service
    global _calendar_service, _calendar_worker
    global _github_service, _github_worker

    logger.info("=" * 50)
    logger.info("MAIHERA starting up...")
    logger.info("=" * 50)

    try:
        from api.websocket_manager import WebSocketManager
        _ws_manager = WebSocketManager()
        logger.info("[1/17] WebSocket manager ready.")

        from brain.brain_service import get_brain_service
        _brain_service, _neo4j_driver = get_brain_service()
        logger.info("[2/17] Brain service ready.")

        from llm.router import LLMRouter
        _llm_router = LLMRouter()
        logger.info("[3/17] LLM router ready.")

        from brain.classifier import NodeClassifier
        _classifier = NodeClassifier(llm_router=_llm_router)
        logger.info("[4/17] Node classifier ready.")

        from orchestrator.confirmation_broker import ConfirmationBroker
        _confirmation_broker = ConfirmationBroker(db=_brain_service.db)
        _confirmation_broker.set_ws_manager(_ws_manager)
        logger.info("[5/17] ConfirmationBroker ready.")

        from orchestrator.orchestrator import Orchestrator
        from orchestrator.tool_registry import register_all_tools
        _orchestrator = Orchestrator(
            db=_brain_service.db,
            confirmation_broker=_confirmation_broker,
        )
        _orchestrator.set_ws_manager(_ws_manager)
        register_all_tools(_orchestrator)
        logger.info("[6/17] Orchestrator ready — 13 tools registered.")

        from api.routes import brain as brain_routes
        from api.routes import chat as chat_routes
        from api.routes.voice import router as voice_router
        from api.routes.briefing import router as briefing_router  
        from api.routes import briefing as briefing_routes          
        brain_routes.set_dependencies(_brain_service, _ws_manager)
        chat_routes.set_dependencies(_brain_service, _llm_router, _classifier)
        app.include_router(voice_router)
        app.include_router(briefing_router)                         
        logger.info("[7/17] Route dependencies injected.")

        from workers.decay_worker import DecayWorker
        _decay_worker = DecayWorker(_brain_service)
        _decay_worker.start()
        logger.info("[8/17] Decay worker started.")
        
        from services.voice_service import VoiceService
        _voice_service = VoiceService()
        _voice_service.set_ws_manager(_ws_manager)
        _voice_service.start()
        logger.info("[9/17] Voice service started.")
        _confirmation_broker.set_voice_service(_voice_service)
        _orchestrator.set_voice_service(_voice_service)

        from services.nudge_service import NudgeService
        _nudge_service = NudgeService(
            brain_service=_brain_service,
            voice_service=_voice_service,
            db_manager=_brain_service.db
        )
        _nudge_service.set_ws_manager(_ws_manager)
        _nudge_service.set_llm_router(_llm_router)
        _decay_worker.add_nudge_job(_nudge_service)
        briefing_routes.set_dependencies(_nudge_service)
        logger.info("[10/17] Nudge service ready.")

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        _confirmation_broker_scheduler = AsyncIOScheduler()
        _confirmation_broker_scheduler.add_job(
            _confirmation_broker.expire_stale,
            trigger="interval",
            minutes=2,
            id="confirmation_expiry",
        )
        _confirmation_broker_scheduler.start()
        logger.info("Confirmation expiry scheduler started.")

        from services.calendar_service import CalendarService
        from workers.calendar_worker import CalendarWorker
        from api.routes.calendar import router as calendar_router
        from api.routes import calendar as calendar_routes
        _calendar_service = CalendarService()
        _calendar_worker  = CalendarWorker(_calendar_service, _brain_service)
        _calendar_worker.start() 
        calendar_routes.set_dependencies(_calendar_service, _brain_service)
        app.include_router(calendar_router)
        logger.info("[11/17] Calendar service ready.")

        from services.github_service import GitHubService
        from workers.github_worker import GitHubWorker
        _github_service = GitHubService()
        _github_worker  = GitHubWorker(_github_service, _brain_service)
        _github_worker.start()
        logger.info("[12/17] GitHub service ready.")

        from api.routes.analysis import router as analysis_router
        from api.routes import analysis as analysis_routes
        analysis_routes.set_dependencies(_brain_service, _llm_router)
        app.include_router(analysis_router)
        logger.info("[13/17] Analysis routes ready.")

        from api.routes.orchestrator import router as orchestrator_router
        from api.routes import orchestrator as orchestrator_routes
        orchestrator_routes.set_dependencies(_orchestrator, _confirmation_broker)
        app.include_router(orchestrator_router)
        logger.info("[14/17] Orchestrator routes ready.")

        from api.routes.skills import router as skills_router
        from api.routes import skills as skills_routes
        skills_routes.set_dependencies(_orchestrator)
        app.include_router(skills_router)
        logger.info("[15/17] Skills routes ready.")

        from services.context_capture_service import ContextCaptureService
        from api.routes.capture import router as capture_router
        from api.routes import capture as capture_routes
        _capture_service = ContextCaptureService(
            brain_service=_brain_service,
            db=_brain_service.db,
            classifier=_classifier,
            llm_router=_llm_router,
        )
        capture_routes.set_dependencies(_capture_service)
        app.include_router(capture_router)

        _decay_worker.scheduler.add_job(
            _capture_service.expire_stale,
            trigger="cron",
            hour=3,
            minute=0,
            id="capture_expiry",
            replace_existing=True,
        )
        logger.info("[16/17] Context Capture service ready.")

        from api.routes.gmail import router as gmail_router
        from api.routes import gmail as gmail_routes
        gmail_routes.set_dependencies(_brain_service)
        app.include_router(gmail_router)
        logger.info("[17/17] Gmail service ready.")

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
        if _calendar_worker:
            _calendar_worker.stop()
            logger.info("Calendar worker stopped.")
        if _github_worker:
            _github_worker.stop()
            logger.info("GitHub worker stopped.")
        if _neo4j_driver:
            _neo4j_driver.close()
            logger.info("Neo4j driver closed.")
        _confirmation_broker_scheduler.shutdown()
        logger.info("MAIHERA shutdown complete.")


app = FastAPI(
    title="MAIHERA",
    description="M.A.I.H.E.R.A — Mai He Raja, Mai He Rani",
    version="0.3.0-phase3",
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
                    # Activate standup state if applicable
                    from services.standup_service import standup_service
                    if standup_service.should_run_today(_brain_service):
                        global _standup_active, _standup_question_index
                        _standup_active = True
                        _standup_question_index = 0

                elif msg_type == "chat":
                    text = payload.get("text", "").strip()
                    context_node_id = payload.get("context_node_id")
                    if not text:
                        continue
                    logger.info("chat via WS: %.60s", text)
                    if _brain_service and _llm_router:
                        asyncio.create_task(
                        _handle_ws_chat(
                            text, context_node_id,
                            _brain_service, _llm_router,
                            _ws_manager, _voice_service,
                            confirmation_broker=_confirmation_broker,
                        )
                    )

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
                    logger.info("speech_next received — playback complete.")
                    if _voice_service:
                        _voice_service.signal_playback_done()

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
        "version": "0.3.0-phase3",
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