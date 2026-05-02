// MAIHERA Graph Node and Edge Types
// Mirror of the Neo4j brain schema

export type NodeType =
  | 'project'
  | 'task'
  | 'person'
  | 'event'
  | 'idea'
  | 'decision'
  | 'feature'
  | 'issue'
  | 'blocker'
  | 'insight'
  | 'component'
  | 'question'

export type NodeStatus =
  | 'active'
  | 'dormant'
  | 'completed'
  | 'archived'
  | 'challenged'

export type NodeSource =
  | 'manual'
  | 'github'
  | 'calendar'
  | 'gmail'
  | 'system'
  | 'dream'
  | 'integration'

export type WorkspaceType =
  | 'personal'
  | 'office'
  | 'shared'

export type NodeVisibility =
  | 'private'
  | 'shared'
  | 'dream-only'

export interface NodeSignals {
  importance: number
  attention: number
  resistance: number
  urgency?: number    // computed live, may be present
}

export interface GraphNode {
  id: string
  type: NodeType
  label: string
  description?: string
  project_id?: string
  source: NodeSource
  status: NodeStatus
  workspace?: WorkspaceType
  visibility?: NodeVisibility

  // Signals — stored flat on Neo4j node
  importance: number
  attention: number
  resistance: number

  // Timestamps
  created_at: string
  last_touched: string
  last_surfaced?: string

  // Decision context (decision nodes only)
  reasoning?: string
  alternatives?: string[]

  // Internal — computed during graph processing
  _urgency?: number
  _search_distance?: number
}

export type EdgeType =
  | 'DEPENDS_ON'
  | 'BELONGS_TO'
  | 'CHALLENGES'
  | 'RELATES_TO'
  | 'ASSIGNED_TO'
  | 'GENERATED_BY'
  | 'IMPROVES'
  | 'BLOCKS'
  | 'HAS_RESISTANCE'

export interface GraphEdge {
  type: EdgeType
  from_id: string
  to_id: string
  properties?: Record<string, unknown>
}

// Force graph format (react-force-graph-2d expects this)
export interface ForceNode extends GraphNode {
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
}

export interface ForceLink {
  source: string | ForceNode
  target: string | ForceNode
  type: EdgeType
  properties?: Record<string, unknown>
}

export interface ForceGraphData {
  nodes: ForceNode[]
  links: ForceLink[]
}

// Node type → display color mapping
export const NODE_COLORS: Record<NodeType, string> = {
  project:   '#3a1a8a',
  task:      '#1a3a5a',
  person:    '#1a5a3a',
  event:     '#3a3a1a',
  idea:      '#1a4a4a',
  decision:  '#3a2a1a',
  feature:   '#2a3a1a',
  issue:     '#5a1a1a',
  blocker:   '#5a2a1a',
  insight:   '#2a1a4a',
  component: '#1a2a4a',
  question:  '#3a1a3a',
}

export const EDGE_COLORS: Record<EdgeType, string> = {
  DEPENDS_ON:    '#0d2035',
  BELONGS_TO:    '#0d2035',
  CHALLENGES:    '#331a00',
  RELATES_TO:    '#0d2035',
  ASSIGNED_TO:   '#0d2035',
  GENERATED_BY:  '#1a1a35',
  IMPROVES:      '#0d2535',
  BLOCKS:        '#350d0d',
  HAS_RESISTANCE:'#350d0d',
}