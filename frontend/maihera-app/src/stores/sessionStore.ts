import { create } from 'zustand'
import type { PendingNudge } from '../types/ws_messages'

export type WorkspaceContext = 'office' | 'personal' | 'weekend' | null
export type MaiheraStatus = 'watching' | 'thinking' | 'speaking' | 'dream'

interface SessionState {
  focusModeActive: boolean
  focusSessionId: string | null
  energyLevel: number | null
  workspaceContext: WorkspaceContext
  maiheraStatus: MaiheraStatus
  nudgeQueue: PendingNudge[]
  lowEnergyMode: boolean

  // Actions
  setFocusMode: (active: boolean, sessionId: string | null) => void
  setEnergy: (level: number) => void
  setWorkspace: (context: WorkspaceContext) => void
  setStatus: (status: MaiheraStatus) => void
  setNudgeQueue: (nudges: PendingNudge[]) => void
}

export const useSessionStore = create<SessionState>((set) => ({
  focusModeActive: false,
  focusSessionId: null,
  energyLevel: null,
  workspaceContext: null,
  maiheraStatus: 'watching',
  nudgeQueue: [],
  lowEnergyMode: false,

  setFocusMode: (active, sessionId) => set({
    focusModeActive: active,
    focusSessionId: active ? sessionId : null
  }),

  setEnergy: (level) => set({
    energyLevel: level,
    lowEnergyMode: level <= 3
  }),

  setWorkspace: (context) => set({ workspaceContext: context }),
  setStatus: (status) => set({ maiheraStatus: status }),
  setNudgeQueue: (nudges) => set({ nudgeQueue: nudges })
}))