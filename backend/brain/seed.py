"""
MAIHERA Brain Layer — Seed Data
Creates structural scaffolding only.
Descriptions are intentionally minimal — MAIHERA learns
about projects by exploring them in Phase 3+, not from
fed information at birth.
Idempotent — safe to run multiple times.
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from brain.brain_service import get_brain_service


def now() -> str:
    return datetime.utcnow().isoformat()


def make_node(type_, label, description, source="manual",
              status="active", importance=0.5, attention=0.3,
              project_id=None, workspace="personal", **kwargs) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": type_,
        "label": label,
        "description": description,
        "source": source,
        "status": status,
        "importance": importance,
        "attention": attention,
        "project_id": project_id,
        "workspace": workspace,
        "visibility": "private",
        "resistance": 0.0,
        "current_load": 0.0,
        "trust_level": 0.3,
        "created_at": now(),
        "last_touched": now(),
        **kwargs
    }


def node_exists(brain, label: str) -> str | None:
    """
    Check if a node with this label already exists.
    Returns node id if found, None if not.
    Idempotency key.
    """
    nodes = brain.list_nodes()
    for n in nodes:
        if n.get('label') == label:
            return n['id']
    return None


def seed(brain) -> dict:
    """
    Seed the brain with structural scaffolding only.
    No rich descriptions — MAIHERA builds her own knowledge
    through exploration in Phase 3+.
    Returns dict of created/existing node ids by name.
    """
    created = {}
    skipped = []

    print("\nSeeding MAIHERA brain graph (structural scaffolding)...")
    print("-" * 50)

    # ── Project: Presence ─────────────────────────────────────────
    # Minimal anchor — MAIHERA reads the codebase in Phase 3
    # and forms her own independent assessment

    existing = node_exists(brain, "Presence")
    if existing:
        print(f"  [SKIP] Presence project already exists ({existing})")
        created['presence'] = existing
        skipped.append('presence')
    else:
        node = make_node(
            type_="project",
            label="Presence",
            description=(
                "Personal AI companion app. "
                "Status: completed, in maintenance mode. "
                "MAIHERA will read the full codebase in Phase 3 "
                "and form her own independent assessment."
            ),
            importance=0.75,
            attention=0.4,
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['presence'] = node_id
        print(f"  [CREATE] Presence project anchor: {node_id}")

    # ── Project: MAIHERA ──────────────────────────────────────────
    # MAIHERA tracks her own development — meta-awareness

    existing = node_exists(brain, "MAIHERA")
    if existing:
        print(f"  [SKIP] MAIHERA project already exists ({existing})")
        created['maihera'] = existing
        skipped.append('maihera')
    else:
        node = make_node(
            type_="project",
            label="MAIHERA",
            description=(
                "This system. Currently in Phase 1 of 7 build phases. "
                "MAIHERA tracks her own development as a project "
                "and can flag things she thinks are wrong about "
                "her own architecture."
            ),
            importance=0.95,
            attention=0.9,
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['maihera'] = node_id
        print(f"  [CREATE] MAIHERA project anchor: {node_id}")

    # ── Self Node: Yash ───────────────────────────────────────────
    # Schedule is seeded from known facts — not discoverable
    # through observation alone. Everything else grows over time:
    # energy_level (daily check-in), focus_style (Phase 5 inference),
    # current_load (computed from active nodes), trust_level
    # (grows with track record), energy_pattern (Phase 5 learning)

    existing = node_exists(brain, "Yash")
    if existing:
        print(f"  [SKIP] Self node already exists ({existing})")
        created['self'] = existing
        skipped.append('self')
    else:
        node = make_node(
            type_="person",
            label="Yash",
            description=(
                "Owner. UI/UX Designer, B.Tech IT. "
                "GitHub: yashpulsay-code. "
                "Known schedule: office Mon-Fri 11AM-7:30PM IST, "
                "bus commute 9AM daily, gym 9:30PM daily, "
                "personal project work after 11PM IST. "
                "Everything else MAIHERA learns through interaction."
            ),
            importance=1.0,
            attention=1.0,
            workspace="personal",
            trust_level=0.3,
            current_load=0.2,
            focus_style=None,
            energy_level=None,
            energy_pattern=None
        )
        node_id = brain.create_node(node)
        created['self'] = node_id
        print(f"  [CREATE] Self node (Yash): {node_id}")

    # ── Task: Complete Phase 1 ────────────────────────────────────

    existing = node_exists(brain, "Complete Phase 1 Implementation")
    if existing:
        print(f"  [SKIP] Phase 1 task already exists ({existing})")
        created['phase1_task'] = existing
        skipped.append('phase1_task')
    else:
        node = make_node(
            type_="task",
            label="Complete Phase 1 Implementation",
            description=(
                "Complete all 15 steps of Phase 1 — The Brain is Born."
            ),
            importance=0.9,
            attention=0.9,
            project_id=created.get('maihera'),
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['phase1_task'] = node_id
        print(f"  [CREATE] Phase 1 task: {node_id}")

    # ── Task: GitHub Repo (completed) ────────────────────────────

    existing = node_exists(brain, "Create MAIHERA GitHub Repository")
    if existing:
        print(f"  [SKIP] GitHub task already exists ({existing})")
        created['github_task'] = existing
        skipped.append('github_task')
    else:
        node = make_node(
            type_="task",
            label="Create MAIHERA GitHub Repository",
            description=(
                "Create the GitHub repository for MAIHERA. Completed."
            ),
            status="completed",
            importance=0.7,
            attention=0.1,
            project_id=created.get('maihera'),
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['github_task'] = node_id
        print(f"  [CREATE] GitHub repo task (completed): {node_id}")

    # ── Issue stubs: Presence known weaknesses ────────────────────
    # Thin stubs only — MAIHERA will enrich or replace these
    # after reading the Presence codebase in Phase 3.
    # She may challenge these framings entirely.

    existing = node_exists(
        brain, "Presence — Personality Mimicry Accuracy"
    )
    if existing:
        print(f"  [SKIP] Personality issue already exists ({existing})")
        created['personality_issue'] = existing
        skipped.append('personality_issue')
    else:
        node = make_node(
            type_="issue",
            label="Presence — Personality Mimicry Accuracy",
            description=(
                "Known weakness flagged at project creation. "
                "MAIHERA will assess this independently in Phase 3 "
                "after reading the codebase."
            ),
            importance=0.7,
            attention=0.3,
            project_id=created.get('presence'),
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['personality_issue'] = node_id
        print(f"  [CREATE] Personality mimicry stub: {node_id}")

    existing = node_exists(brain, "Presence — Basic UI Animations")
    if existing:
        print(f"  [SKIP] UI issue already exists ({existing})")
        created['ui_issue'] = existing
        skipped.append('ui_issue')
    else:
        node = make_node(
            type_="issue",
            label="Presence — Basic UI Animations",
            description=(
                "Known weakness flagged at project creation. "
                "MAIHERA will assess this independently in Phase 3."
            ),
            importance=0.5,
            attention=0.2,
            project_id=created.get('presence'),
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['ui_issue'] = node_id
        print(f"  [CREATE] UI animations stub: {node_id}")

    # ── Feature stub: Presence Product Pipeline ───────────────────
    # Direction flagged by Yash — MAIHERA tracks it as a node
    # but will develop her own view on feasibility in Phase 3+

    existing = node_exists(brain, "Presence — Product Pipeline")
    if existing:
        print(f"  [SKIP] Product pipeline already exists ({existing})")
        created['pipeline_feature'] = existing
        skipped.append('pipeline_feature')
    else:
        node = make_node(
            type_="feature",
            label="Presence — Product Pipeline",
            description=(
                "Future direction: allow any user to upload WhatsApp "
                "chat history and generate a custom personality "
                "simulation. Core technology proven. "
                "Productization layer not yet built."
            ),
            importance=0.65,
            attention=0.25,
            project_id=created.get('presence'),
            workspace="personal"
        )
        node_id = brain.create_node(node)
        created['pipeline_feature'] = node_id
        print(f"  [CREATE] Product pipeline stub: {node_id}")

    # ── Edges ─────────────────────────────────────────────────────

    print("\nCreating edges...")

    if 'phase1_task' not in skipped and 'maihera' in created:
        brain.create_edge(
            created['phase1_task'],
            created['maihera'],
            'BELONGS_TO'
        )
        print("  [EDGE] Phase 1 task → BELONGS_TO → MAIHERA")

    if 'github_task' not in skipped and 'maihera' in created:
        brain.create_edge(
            created['github_task'],
            created['maihera'],
            'BELONGS_TO'
        )
        print("  [EDGE] GitHub task → BELONGS_TO → MAIHERA")

    for key, label in [
        ('personality_issue', 'Personality stub'),
        ('ui_issue', 'UI stub'),
        ('pipeline_feature', 'Product pipeline stub'),
    ]:
        if key not in skipped and 'presence' in created:
            brain.create_edge(
                created[key],
                created['presence'],
                'BELONGS_TO'
            )
            print(f"  [EDGE] {label} → BELONGS_TO → Presence")

    return created


if __name__ == "__main__":
    print("Initializing MAIHERA brain services...")
    brain, driver = get_brain_service()

    try:
        created = seed(brain)

        print("\n" + "=" * 50)
        print("Seed complete.")
        print(f"Nodes processed: {len(created)}")

        stats = brain.get_stats()
        print(f"\nBrain graph state:")
        print(f"  Total nodes : {stats['node_count']}")
        print(f"  Total edges : {stats['edge_count']}")
        print(f"  By type     : {stats['type_counts']}")
        print(f"\nNote: MAIHERA starts with structural anchors only.")
        print(f"Knowledge grows through exploration from Phase 3 onwards.")

    finally:
        driver.close()