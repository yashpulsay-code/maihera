"""
MAIHERA Signal Defaults
Centralized signal initialization for integration-sourced nodes.
All integrations use this — never hardcode signals in service files.

node_weight encodes epistemological confidence:
  1.0 = human-authored (Yash said this matters)
  0.8 = analysis-generated (MAIHERA assessed this)
  0.7 = system-generated (calendar, GitHub, Gmail)
  0.5 = low-confidence inference

Decay rates are faster for system-generated nodes —
they should earn their place through interaction,
not persist purely because they were recently created.
"""

from brain.schema import NodeSource, NodeStatus, WorkspaceType

# ── Default signal tables by source ──────────────────────────────────

SIGNAL_DEFAULTS = {
    NodeSource.MANUAL: {
        'importance':  0.6,
        'attention':   0.8,
        'node_weight': 1.0,
        'resistance':  0.0,
    },
    NodeSource.CALENDAR: {
        'importance':  0.4,
        'attention':   0.6,   # overridden by proximity calc
        'node_weight': 0.7,
        'resistance':  0.0,
    },
    NodeSource.GITHUB: {
        'importance':  0.4,
        'attention':   0.6,
        'node_weight': 0.7,
        'resistance':  0.0,
    },
    NodeSource.GMAIL: {
        'importance':  0.2,
        'attention':   0.3,
        'node_weight': 0.7,
        'resistance':  0.0,
    },
    NodeSource.DREAM: {
        'importance':  0.5,
        'attention':   0.7,
        'node_weight': 0.8,
        'resistance':  0.0,
    },
    NodeSource.INTEGRATION: {
        'importance':  0.3,
        'attention':   0.5,
        'node_weight': 0.7,
        'resistance':  0.0,
    },
    NodeSource.SYSTEM: {
        'importance':  0.3,
        'attention':   0.4,
        'node_weight': 0.6,
        'resistance':  0.0,
    },
}

# ── Attention modifiers by proximity (calendar events) ───────────────

def calendar_attention(hours_until: float) -> float:
    """
    Compute attention for a calendar event based on
    how many hours until it starts.
    """
    if hours_until <= 0:
        return 1.0    # happening now or past
    elif hours_until <= 24:
        return 1.0    # today
    elif hours_until <= 72:
        return 0.8    # within 3 days
    elif hours_until <= 168:
        return 0.6    # within 7 days
    else:
        return 0.4    # further out


# ── Importance modifiers by analysis priority ─────────────────────────

def analysis_importance(priority: int) -> float:
    """
    Compute importance for a codebase analysis finding
    based on priority rank (1=highest, 10=lowest).
    """
    priority = max(1, min(10, priority))
    return round(0.8 - ((priority - 1) * (0.4 / 9)), 3)


# ── Main accessor ─────────────────────────────────────────────────────

def get_defaults(source: NodeSource) -> dict:
    """
    Return signal defaults for a given node source.
    Always returns a copy — never mutate the defaults table.
    """
    defaults = SIGNAL_DEFAULTS.get(source, SIGNAL_DEFAULTS[NodeSource.INTEGRATION])
    return dict(defaults)