"""
MAIHERA API Routes — Chat
Handles conversation with MAIHERA and node creation
from natural language input.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_brain = None
_router_llm = None
_classifier = None

def set_dependencies(brain_service, llm_router, classifier):
    global _brain, _router_llm, _classifier
    _brain = brain_service
    _router_llm = llm_router
    _classifier = classifier


class ChatMessage(BaseModel):
    message: str
    session_id: str
    create_node_if_detected: bool = True


class ChatResponse(BaseModel):
    response: str
    session_id: str
    node_created: Optional[dict] = None


@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatMessage):
    if not _router_llm:
        raise HTTPException(
            status_code=503,
            detail="LLM router not initialized"
        )

    try:
        from llm.persona import build_system_prompt

       # Get live context for system prompt from brain graph
        self_node = None
        active_projects = []
        high_signal_nodes = []

        if _brain:
            # Fetch active projects
            projects = _brain.list_nodes(node_type='project')
            active_projects = [
                p for p in projects
                if p.get('status') == 'active'
            ]

            # Fetch self node (Yash)
            all_persons = _brain.list_nodes(node_type='person')
            for p in all_persons:
                if p.get('label') == 'Yash':
                    self_node = p
                    break

            # Fetch high signal nodes for context
            # These are the only nodes MAIHERA may reference
            high_signal_nodes = _brain.get_high_signal_nodes(
                importance_threshold=0.5,
                attention_threshold=0.2
            )

        system_prompt = build_system_prompt(
            self_node=self_node,
            active_projects=active_projects,
            high_signal_nodes=high_signal_nodes
        )

        messages = [{"role": "user", "content": request.message}]

        response_text = await _router_llm.route(
            task_type='conversation',
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=800
        )

        # Detect and create nodes from input
        node_created = None
        if (request.create_node_if_detected
                and _brain and _classifier):
            project_names = [
                p.get('label', '') for p in active_projects
            ]
            classification = await _classifier.classify(
                request.message, project_names
            )

            # Only create node if input looks actionable
            actionable_types = {
                'task', 'issue', 'feature', 'decision',
                'blocker', 'question'
            }
            if (classification['type'] in actionable_types
                    and len(request.message) > 20):

                import uuid
                from datetime import datetime

                # Resolve project_id from hint
                project_id = None
                hint = classification.get('project_id_hint')
                if hint and _brain:
                    projects_list = _brain.list_nodes(
                        node_type='project'
                    )
                    for p in projects_list:
                        if hint.lower() in p.get(
                            'label', ''
                        ).lower():
                            project_id = p['id']
                            break

                node_data = {
                    "id": str(uuid.uuid4()),
                    "type": classification['type'],
                    "label": classification['label'],
                    "description": classification['description'],
                    "project_id": project_id,
                    "source": "manual",
                    "importance": classification['importance_hint'],
                    "attention": 0.7,
                    "status": "active",
                    "visibility": "private",
                    "workspace": "personal",
                    "resistance": 0.0,
                    "current_load": 0.0,
                    "trust_level": 0.3,
                    "created_at": datetime.utcnow().isoformat(),
                    "last_touched": datetime.utcnow().isoformat(),
                }
                node_id = _brain.create_node(node_data)
                node_created = {
                    "node_id": node_id,
                    "type": classification['type'],
                    "label": classification['label'],
                    "project": hint
                }
                logger.info(
                    "Node auto-created from chat: %s (%s)",
                    classification['label'],
                    classification['type']
                )

        return ChatResponse(
            response=response_text,
            session_id=request.session_id,
            node_created=node_created
        )

    except Exception as e:
        logger.error("Chat error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quota")
async def get_quota_status():
    """Return current LLM quota status."""
    if not _router_llm:
        raise HTTPException(
            status_code=503, detail="LLM router not initialized"
        )
    return _router_llm.get_quota_status()


@router.get("/log")
async def get_request_log():
    """Return recent LLM request log."""
    if not _router_llm:
        raise HTTPException(
            status_code=503, detail="LLM router not initialized"
        )
    return {"log": _router_llm.get_request_log(last_n=20)}