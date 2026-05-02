import { useVoiceStore } from '../stores/voiceStore'
import { useSessionStore } from '../stores/sessionStore'

let audioElement: HTMLAudioElement | null = null
let isInitialized = false

function playAudioFile(filepath: string): void {
  const voice = useVoiceStore.getState()
  const session = useSessionStore.getState()

  // Clean up previous audio element
  if (audioElement) {
    audioElement.pause()
    audioElement.src = ''
    audioElement = null
  }

  // Convert Windows path to file:// URL
  const fileUrl = `file:///${filepath.replace(/\\/g, '/')}`

  audioElement = new Audio(fileUrl)

  audioElement.onplay = () => {
    const currentItem = useVoiceStore.getState().queue[0]
    voice.setSpeaking(true, currentItem?.text)
    session.setStatus('speaking')
  }

  audioElement.onended = () => {
    voice.setSpeaking(false)
    voice.dequeueItem()
    voice.clearPendingAudio()
    session.setStatus('watching')

    // Check if more items in queue
    const remaining = useVoiceStore.getState().queue
    if (remaining.length > 1) {
      // Signal backend to synthesize next item
      // Import here to avoid circular dependency
      import('./websocket').then(({ wsService }) => {
        wsService.send('speech_next', {})
      })
    }
  }

  audioElement.onerror = (err) => {
    console.error('[Audio] Playback error:', err)
    voice.setSpeaking(false)
    voice.clearPendingAudio()
    session.setStatus('watching')
  }

  audioElement.play().catch(err => {
    console.error('[Audio] Play failed:', err)
  })
}

export function initAudio(): void {
  if (isInitialized) return
  isInitialized = true

  // Listen for audio files from Electron main process
  if (window.maihera?.onAudioFile) {
    window.maihera.onAudioFile((filepath: string) => {
      console.log('[Audio] File ready:', filepath)
      playAudioFile(filepath)
    })
    console.log('[Audio] Audio service initialized.')
  } else {
    console.warn('[Audio] window.maihera not available — running in browser mode, audio disabled.')
  }
}

// Extend window type for TypeScript
declare global {
  interface Window {
    maihera: {
      onAudioFile: (callback: (filepath: string) => void) => void
      minimizeWindow: () => void
      maximizeWindow: () => void
      closeWindow: () => void
      getAppPath: () => Promise<string>
    }
  }
}