import { create } from 'zustand'

export interface ChatMessage {
  id: string
  role: 'user' | 'maihera'
  text: string
  timestamp: string
  node_ids?: string[]
}

interface ChatState {
  messages: ChatMessage[]
  inputDraft: string

  // Actions
  addMessage: (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  setDraft: (draft: string) => void
  clearDraft: () => void
  clearMessages: () => void
}

let _msgCounter = 0

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  inputDraft: '',

  addMessage: (msg) => set(state => ({
    messages: [
      ...state.messages,
      {
        ...msg,
        id: `msg-${++_msgCounter}-${Date.now()}`,
        timestamp: new Date().toISOString()
      }
    ]
  })),

  setDraft: (draft) => set({ inputDraft: draft }),
  clearDraft: () => set({ inputDraft: '' }),
  clearMessages: () => set({ messages: [] })
}))