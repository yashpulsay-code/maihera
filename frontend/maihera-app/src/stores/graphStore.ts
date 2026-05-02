import { create } from 'zustand'
import type { GraphNode, GraphEdge, ForceGraphData, ForceNode, ForceLink } from '../types/graph'

interface GraphState {
  nodes: Map<string, GraphNode>
  edges: Map<string, GraphEdge>
  lastSync: string | null

  // Actions
  fullSync: (nodes: GraphNode[], edges: GraphEdge[]) => void
  upsertNode: (node: GraphNode) => void
  deleteNode: (id: string) => void
  upsertEdge: (edge: GraphEdge) => void
  deleteEdge: (id: string) => void
  updateSignals: (id: string, signals: Partial<GraphNode>) => void

  // Selector — converts to force graph format
  getForceGraphData: () => ForceGraphData
}

export const useGraphStore = create<GraphState>((set, get) => ({
  nodes: new Map(),
  edges: new Map(),
  lastSync: null,

  fullSync: (nodes, edges) => {
    const nodeMap = new Map<string, GraphNode>()
    const edgeMap = new Map<string, GraphEdge>()
    nodes.forEach(n => nodeMap.set(n.id, n))
    edges.forEach((e, i) => edgeMap.set(`${e.from_id}-${e.type}-${e.to_id}-${i}`, e))
    set({ nodes: nodeMap, edges: edgeMap, lastSync: new Date().toISOString() })
  },

  upsertNode: (node) => set(state => {
    const nodes = new Map(state.nodes)
    nodes.set(node.id, node)
    return { nodes }
  }),

  deleteNode: (id) => set(state => {
    const nodes = new Map(state.nodes)
    nodes.delete(id)
    return { nodes }
  }),

  upsertEdge: (edge) => set(state => {
    const edges = new Map(state.edges)
    const key = `${edge.from_id}-${edge.type}-${edge.to_id}`
    edges.set(key, edge)
    return { edges }
  }),

  deleteEdge: (id) => set(state => {
    const edges = new Map(state.edges)
    edges.delete(id)
    return { edges }
  }),

  updateSignals: (id, signals) => set(state => {
    const nodes = new Map(state.nodes)
    const existing = nodes.get(id)
    if (existing) {
      nodes.set(id, { ...existing, ...signals })
    }
    return { nodes }
  }),

  getForceGraphData: (): ForceGraphData => {
    const { nodes, edges } = get()
    const forceNodes: ForceNode[] = Array.from(nodes.values()) as ForceNode[]
    const forceLinks: ForceLink[] = Array.from(edges.values()).map(e => ({
      source: e.from_id,
      target: e.to_id,
      type: e.type,
      properties: e.properties
    }))
    return { nodes: forceNodes, links: forceLinks }
  }
}))