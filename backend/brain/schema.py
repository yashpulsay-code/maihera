"""
MAIHERA Brain Layer — Neo4j Schema
Defines all node types, signal structures, edge types,
and creates constraints and indexes on Neo4j Aura.
"""

import os
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator

load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))


# ── Enums ─────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    PROJECT = "project"
    TASK = "task"
    PERSON = "person"
    EVENT = "event"
    IDEA = "idea"
    DECISION = "decision"
    FEATURE = "feature"
    ISSUE = "issue"
    BLOCKER = "blocker"
    INSIGHT = "insight"
    COMPONENT = "component"
    QUESTION = "question"

class NodeSource(str, Enum):
    MANUAL = "manual"
    GITHUB = "github"
    CALENDAR = "calendar"
    GMAIL = "gmail"
    SYSTEM = "system"
    DREAM = "dream"
    INTEGRATION = "integration"

class NodeStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    CHALLENGED = "challenged"

class NodeVisibility(str, Enum):
    PRIVATE = "private"
    SHARED = "shared"
    DREAM_ONLY = "dream-only"

class RelationshipType(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    BELONGS_TO = "BELONGS_TO"
    CHALLENGES = "CHALLENGES"
    RELATES_TO = "RELATES_TO"
    ASSIGNED_TO = "ASSIGNED_TO"
    GENERATED_BY = "GENERATED_BY"
    IMPROVES = "IMPROVES"
    BLOCKS = "BLOCKS"
    HAS_RESISTANCE = "HAS_RESISTANCE"

class ResistanceReason(str, Enum):
    BLOCKED = "blocked"
    OVERWHELMED = "overwhelmed"
    DISENGAGED = "disengaged"
    UNCLEAR = "unclear"
    AVOIDANT = "avoidant"
    EXTERNAL = "external"

class MAIHERAResponse(str, Enum):
    PUSH = "push"
    REFRAME = "reframe"
    ASSIST = "assist"
    SURFACE = "surface"
    HOLD = "hold"

class ResistanceTrend(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"

class FocusStyle(str, Enum):
    DEEP_WORK = "deep-work"
    CONTEXT_SWITCHER = "context-switcher"
    DEADLINE_DRIVEN = "deadline-driven"

class WorkspaceType(str, Enum):
    PERSONAL = "personal"
    OFFICE = "office"
    SHARED = "shared"


# ── Pydantic Models ────────────────────────────────────────────────────

class NodeSchema(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: NodeType
    label: str
    description: str
    project_id: Optional[str] = None
    source: NodeSource = NodeSource.MANUAL
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    last_touched: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    last_surfaced: Optional[str] = None
    status: NodeStatus = NodeStatus.ACTIVE
    visibility: NodeVisibility = NodeVisibility.PRIVATE
    workspace: WorkspaceType = WorkspaceType.PERSONAL
    embedding_ref: Optional[str] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    attention: float = Field(default=0.3, ge=0.0, le=1.0)
    resistance: float = Field(default=0.0, ge=0.0, le=1.0)
    # Decision node fields
    reasoning: Optional[str] = None
    alternatives: Optional[list[str]] = None
    outcome: Optional[str] = None
    # Self node fields
    energy_pattern: Optional[str] = None
    energy_level: Optional[int] = Field(default=None, ge=1, le=10)
    focus_style: Optional[FocusStyle] = None
    current_load: float = Field(default=0.0, ge=0.0, le=1.0)
    trust_level: float = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator('importance', 'attention', 'resistance',
                     'current_load', 'trust_level')
    @classmethod
    def clamp_float(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ResistanceEdge(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reason: ResistanceReason
    since: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    source: NodeSource = NodeSource.MANUAL
    evidence: list[str] = Field(default_factory=list)
    maihera_response: MAIHERAResponse
    last_intervention: Optional[str] = None
    trend: ResistanceTrend = ResistanceTrend.STABLE


# ── Schema Setup ───────────────────────────────────────────────────────

CONSTRAINTS = [
    "CREATE CONSTRAINT maihera_node_id IF NOT EXISTS "
    "FOR (n:Node) REQUIRE n.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX maihera_node_type IF NOT EXISTS "
    "FOR (n:Node) ON (n.type)",

    "CREATE INDEX maihera_node_project IF NOT EXISTS "
    "FOR (n:Node) ON (n.project_id)",

    "CREATE INDEX maihera_node_status IF NOT EXISTS "
    "FOR (n:Node) ON (n.status)",

    "CREATE INDEX maihera_node_last_touched IF NOT EXISTS "
    "FOR (n:Node) ON (n.last_touched)",
]


def setup_schema(driver) -> None:
    """Create all constraints and indexes on Neo4j."""
    with driver.session() as session:
        for constraint in CONSTRAINTS:
            session.run(constraint)
            print(f"  Constraint applied: {constraint[:60]}...")
        for index in INDEXES:
            session.run(index)
            print(f"  Index applied: {index[:60]}...")
    print("Schema setup complete.")


def get_driver():
    """Create and return a Neo4j driver from environment."""
    uri = os.getenv('NEO4J_URI')
    user = os.getenv('NEO4J_USER')
    password = os.getenv('NEO4J_PASSWORD')
    if not all([uri, user, password]):
        raise ValueError(
            "Missing Neo4j credentials in .env — "
            "NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD required"
        )
    return GraphDatabase.driver(uri, auth=(user, password))


if __name__ == "__main__":
    print("Setting up MAIHERA Neo4j schema...")
    driver = get_driver()
    try:
        driver.verify_connectivity()
        print("Connection verified.")
        setup_schema(driver)
    finally:
        driver.close()
    print("Done.")