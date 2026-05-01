"""
MAIHERA API Routes — Brain
All endpoints for node and edge operations on the brain graph.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/brain", tags=["brain"])


# ── Request Models ────────────────────────────────────────────────────

class CreateNodeRequest(BaseModel):
    type: str
    label: str
    description: str
    project_id: Optional[str] = None
    source: str = "manual"
    importance: float = 0.5
    attention: float = 0.3
    status: str = "active"
    visibility: str = "private"
    workspace: str = "personal"
    reasoning: Optional[str] = None
    alternatives: Optional[list[str]] = None

class UpdateNodeRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    importance: Optional[float] = None
    attention: Optional[float] = None
    workspace: Optional[str] = None

class UpdateSignalRequest(BaseModel):
    signal: str
    value: float

class CreateEdgeRequest(BaseModel):
    from_id: str
    to_id: str
    edge_type: str
    properties: Optional[dict] = None

class CreateResistanceRequest(BaseModel):
    from_id: str
    to_id: str
    score: float
    reason: str
    evidence: list[str] = []
    maihera_response: str = "surface"
    trend: str = "stable"


# ── Dependency injection helpers ──────────────────────────────────────
# brain_service and ws_manager are set by main.py at startup

_brain = None
_ws = None

def set_dependencies(brain_service, ws_manager):
    global _brain, _ws
    _brain = brain_service
    _ws = ws_manager

def get_brain():
    if _brain is None:
        raise HTTPException(
            status_code=503,
            detail="Brain service not initialized"
        )
    return _brain


# ── Node Endpoints ────────────────────────────────────────────────────

@router.post("/nodes")
async def create_node(request: CreateNodeRequest):
    brain = get_brain()
    try:
        import uuid
        from datetime import datetime
        node_data = {
            "id": str(uuid.uuid4()),
            "type": request.type,
            "label": request.label,
            "description": request.description,
            "project_id": request.project_id,
            "source": request.source,
            "importance": request.importance,
            "attention": request.attention,
            "status": request.status,
            "visibility": request.visibility,
            "workspace": getattr(request, 'workspace', 'personal'),
            "reasoning": request.reasoning,
            "alternatives": request.alternatives,
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
        }
        node_id = brain.create_node(node_data)
        graph = brain.get_full_graph()
        await _ws.broadcast_graph_update(graph)
        return {"node_id": node_id, "status": "created"}
    except Exception as e:
        logger.error("Create node error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    brain = get_brain()
    node = brain.get_node(node_id)
    if not node:
        raise HTTPException(
            status_code=404, detail="Node not found"
        )
    return node


@router.patch("/nodes/{node_id}")
async def update_node(node_id: str, request: UpdateNodeRequest):
    brain = get_brain()
    updates = {
        k: v for k, v in request.model_dump().items()
        if v is not None
    }
    if not updates:
        raise HTTPException(
            status_code=400, detail="No updates provided"
        )
    brain.update_node(node_id, updates)
    graph = brain.get_full_graph()
    await _ws.broadcast_graph_update(graph)
    return {"status": "updated", "fields": list(updates.keys())}


@router.get("/nodes")
async def list_nodes(
    project_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    brain = get_brain()
    nodes = brain.list_nodes(
        project_id=project_id,
        node_type=type,
        status=status
    )
    return {"nodes": nodes, "count": len(nodes)}


@router.post("/nodes/{node_id}/signal")
async def update_signal(node_id: str, request: UpdateSignalRequest):
    brain = get_brain()
    try:
        brain.update_signal(node_id, request.signal, request.value)
        return {
            "status": "updated",
            "signal": request.signal,
            "value": request.value
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/nodes/{node_id}/urgency")
async def get_urgency(node_id: str):
    brain = get_brain()
    urgency = brain.compute_urgency(node_id)
    return {"node_id": node_id, "urgency": urgency}


# ── Edge Endpoints ────────────────────────────────────────────────────

@router.post("/edges")
async def create_edge(request: CreateEdgeRequest):
    brain = get_brain()
    try:
        brain.create_edge(
            request.from_id,
            request.to_id,
            request.edge_type,
            request.properties
        )
        graph = brain.get_full_graph()
        await _ws.broadcast_graph_update(graph)
        return {"status": "created", "edge_type": request.edge_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edges/resistance")
async def create_resistance_edge(request: CreateResistanceRequest):
    brain = get_brain()
    try:
        from brain.schema import ResistanceEdge
        from datetime import datetime
        resistance = ResistanceEdge(
            score=request.score,
            reason=request.reason,
            evidence=request.evidence,
            maihera_response=request.maihera_response,
            trend=request.trend,
            since=datetime.utcnow().isoformat()
        )
        brain.create_resistance_edge(
            request.from_id, request.to_id, resistance
        )
        return {"status": "created", "score": request.score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{node_id}/edges")
async def get_node_edges(
    node_id: str,
    direction: str = Query("both")
):
    brain = get_brain()
    edges = brain.get_edges(node_id, direction=direction)
    return {"edges": edges, "count": len(edges)}


# ── Graph Endpoints ───────────────────────────────────────────────────

@router.get("/graph")
async def get_full_graph():
    brain = get_brain()
    graph = brain.get_full_graph()
    return graph


@router.get("/graph/{project_id}")
async def get_project_graph(project_id: str):
    brain = get_brain()
    graph = brain.get_project_graph(project_id)
    return graph


@router.get("/search")
async def search_nodes(
    q: str = Query(..., min_length=2),
    project_id: Optional[str] = Query(None)
):
    brain = get_brain()
    results = brain.search_nodes(q, project_id=project_id)
    return {"results": results, "count": len(results)}


@router.get("/stats")
async def get_stats():
    brain = get_brain()
    return brain.get_stats()


@router.get("/high-signal")
async def get_high_signal_nodes(
    importance: float = Query(0.6),
    attention: float = Query(0.4)
):
    brain = get_brain()
    nodes = brain.get_high_signal_nodes(importance, attention)
    return {"nodes": nodes, "count": len(nodes)}