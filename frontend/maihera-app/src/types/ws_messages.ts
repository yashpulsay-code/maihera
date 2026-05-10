// MAIHERA WebSocket Message Types
// Every message follows: { type, payload, timestamp }

import type { GraphNode, GraphEdge } from './graph'

export interface WSMessage<T> {
  type: string
  payload: T
  timestamp: string
}

// ── Graph Messages ─────────────────────────────────────────────

export interface FullSyncPayload {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface NodeUpsertPayload extends GraphNode {}

export interface NodeDeletePayload {
  id: string
}

export interface EdgeUpsertPayload extends GraphEdge {}

export interface EdgeDeletePayload {
  id: string
}

export interface SignalUpdatePayload {
  id: string
  signals: {
    importance: number
    attention: number
    resistance: number
    urgency: number
  }
}

// ── Voice Messages ─────────────────────────────────────────────

export interface MaiheraSpeak {
  text: string
  node_ids: string[]
  priority: 'urgent' | 'normal'
  audio_file?: string
}

// ── Briefing Messages ──────────────────────────────────────────

export interface BriefingSegmentPayload {
  text: string
  node_ids: string[]
  segment_index: number
}

// ── Session Messages ───────────────────────────────────────────

export interface FocusModeChangePayload {
  active: boolean
  session_id: string | null
}

export interface NudgeQueueUpdatePayload {
  nudges: PendingNudge[]
}

export interface PendingNudge {
  id: string
  text: string
  node_ids: string[]
  priority: 'urgent' | 'normal'
  suppressed_at: string
}

export interface SystemStatusPayload {
  status: 'watching' | 'thinking' | 'speaking' | 'dream'
}

// ── Confirmation Messages ──────────────────────────────────────

export interface ConfirmationRequestedPayload {
  confirmation_id: string
  task_id: string
  action_summary: string
  full_detail: Record<string, unknown>
  expires_at: string
}

export interface ConfirmationResolvedPayload {
  confirmation_id: string
  resolved_by: 'voice' | 'text' | 'auto' | 'timeout'
  action_summary: string
}

export interface ConfirmationExpiredPayload {
  confirmation_id: string
  action_summary: string
}

// ── Union Type ─────────────────────────────────────────────────

export type AnyWSMessage =
  | WSMessage<FullSyncPayload>
  | WSMessage<NodeUpsertPayload>
  | WSMessage<NodeDeletePayload>
  | WSMessage<EdgeUpsertPayload>
  | WSMessage<EdgeDeletePayload>
  | WSMessage<SignalUpdatePayload>
  | WSMessage<MaiheraSpeak>
  | WSMessage<Record<string, never>>       // briefing_start, briefing_end
  | WSMessage<BriefingSegmentPayload>
  | WSMessage<FocusModeChangePayload>
  | WSMessage<NudgeQueueUpdatePayload>
  | WSMessage<SystemStatusPayload>
  | WSMessage<ConfirmationRequestedPayload>
  | WSMessage<ConfirmationResolvedPayload>
  | WSMessage<ConfirmationExpiredPayload>

// ── Inbound (frontend → backend) ──────────────────────────────

export interface OutboundMessage {
  type: 'session_start' | 'chat' | 'energy_checkin' | 'focus_mode' | 'speech_next' | 'confirm' | 'cancel_confirmation'
  payload: Record<string, unknown>
}