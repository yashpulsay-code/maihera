import { create } from 'zustand'

export interface SpeechItem {
  id?: string
  text: string
  node_ids: string[]
  priority: 'urgent' | 'normal'
  queued_at: string
}

interface VoiceState {
  isSpeaking: boolean
  currentText: string | null
  queue: SpeechItem[]
  pendingAudioFile: string | null

  // Actions
  setSpeaking: (speaking: boolean, text?: string) => void
  enqueueItem: (item: SpeechItem) => void
  dequeueItem: () => void
  setPendingAudio: (filename: string) => void
  clearPendingAudio: () => void
  clearQueue: () => void
}

export const useVoiceStore = create<VoiceState>((set) => ({
  isSpeaking: false,
  currentText: null,
  queue: [],
  pendingAudioFile: null,

  setSpeaking: (speaking, text) => set({
    isSpeaking: speaking,
    currentText: speaking ? (text ?? null) : null
  }),

  enqueueItem: (item) => set(state => ({
    queue: [...state.queue, item]
  })),

  dequeueItem: () => set(state => ({
    queue: state.queue.slice(1)
  })),

  setPendingAudio: (filename) => set({ pendingAudioFile: filename }),
  clearPendingAudio: () => set({ pendingAudioFile: null }),
  clearQueue: () => set({ queue: [], isSpeaking: false, currentText: null })
}))