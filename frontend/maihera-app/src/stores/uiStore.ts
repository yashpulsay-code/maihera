import { create } from 'zustand'

export type RightPanelMode = 'chat' | 'inspect'

interface UIState {
  rightPanelMode: RightPanelMode
  selectedNodeId: string | null
  briefingActive: boolean
  leftPanelCollapsed: boolean
  highlightedNodeIds: Set<string>

  // Actions
  setRightPanelMode: (mode: RightPanelMode) => void
  selectNode: (id: string | null) => void
  setBriefing: (active: boolean) => void
  toggleLeftPanel: () => void
  setHighlightedNodes: (ids: string[]) => void
  clearHighlights: () => void
}

export const useUIStore = create<UIState>((set) => ({
  rightPanelMode: 'chat',
  selectedNodeId: null,
  briefingActive: false,
  leftPanelCollapsed: false,
  highlightedNodeIds: new Set(),

  setRightPanelMode: (mode) => set({ rightPanelMode: mode }),

  selectNode: (id) => set({
    selectedNodeId: id,
    rightPanelMode: id ? 'inspect' : 'chat'
  }),

  setBriefing: (active) => set({ briefingActive: active }),
  toggleLeftPanel: () => set(state => ({
    leftPanelCollapsed: !state.leftPanelCollapsed
  })),

  setHighlightedNodes: (ids) => set({
    highlightedNodeIds: new Set(ids)
  }),

  clearHighlights: () => set({
    highlightedNodeIds: new Set()
  })
}))