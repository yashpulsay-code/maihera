import { useState, useRef, useCallback } from 'react'
import { useChatStore } from '../../stores/chatStore'
import { useSessionStore } from '../../stores/sessionStore'
import { wsService } from '../../services/websocket'

const FOCUS_COLOR = '#cc8800'
const FOCUS_ACTIVE_BG = 'rgba(30,20,0,0.8)'

export function BottomBar() {
  const [isRecording, setIsRecording] = useState(false)
  const [recordingError, setRecordingError] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const { inputDraft, setDraft, clearDraft, addMessage } = useChatStore()
  const { focusModeActive, focusSessionId, energyLevel, setFocusMode } = useSessionStore()

  // ── Text send ─────────────────────────────────────────────────

  const sendText = useCallback(() => {
    const text = inputDraft.trim()
    if (!text) return
    addMessage({ role: 'user', text, node_ids: [] })
    wsService.send('chat', { text })
    clearDraft()
  }, [inputDraft, addMessage, clearDraft])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') sendText()
  }

  // ── Voice record ──────────────────────────────────────────────

  const startRecording = async () => {
    setRecordingError(false)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []

      recorder.ondataavailable = e => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        await transcribeAudio(blob)
      }

      recorder.start()
      mediaRecorderRef.current = recorder
      setIsRecording(true)
    } catch (err) {
      console.error('[Voice] Microphone access denied:', err)
      setRecordingError(true)
    }
  }

  const stopRecording = () => {
    mediaRecorderRef.current?.stop()
    mediaRecorderRef.current = null
    setIsRecording(false)
  }

  const handleVoiceButton = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const transcribeAudio = async (blob: Blob) => {
    try {
      const formData = new FormData()
      formData.append('file', blob, 'recording.webm')

      const res = await fetch('http://localhost:8000/voice/transcribe', {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()

      if (data.text && data.text.trim()) {
        addMessage({ role: 'user', text: data.text.trim(), node_ids: [] })
        wsService.send('chat', { text: data.text.trim() })
      }
    } catch (err) {
      console.error('[Voice] Transcription failed:', err)
      setRecordingError(true)
    }
  }

  // ── Focus mode ────────────────────────────────────────────────

  const handleFocusMode = () => {
    if (focusModeActive) {
      // End focus session
      wsService.send('focus_mode', {
        active: false,
        session_id: focusSessionId
      })
      setFocusMode(false, null)
    } else {
      // Start focus session
      const sessionId = `focus-${Date.now()}`
      wsService.send('focus_mode', {
        active: true,
        session_id: sessionId,
        energy_level: energyLevel
      })
      setFocusMode(true, sessionId)
    }
  }

  return (
    <div style={{
      height: '48px',
      background: 'rgba(8,12,20,0.94)',
      borderTop: '0.5px solid #0e1d30',
      display: 'flex',
      alignItems: 'center',
      padding: '0 12px',
      gap: '10px',
      flexShrink: 0,
    }}>

      {/* Voice button */}
      <button
        onClick={handleVoiceButton}
        title={isRecording ? 'Stop recording' : 'Start voice input'}
        style={{
          width: '32px',
          height: '32px',
          borderRadius: '50%',
          border: `0.5px solid ${isRecording ? '#cc4a4a' : recordingError ? '#cc4a00' : '#1a3a5a'}`,
          background: isRecording ? 'rgba(80,10,10,0.6)' : 'transparent',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          transition: 'all 0.2s ease',
        }}
      >
        {/* Mic icon */}
        <svg width='12' height='14' viewBox='0 0 12 14' fill='none'>
          <rect
            x='3.5' y='0.5' width='5' height='8'
            rx='2.5'
            stroke={isRecording ? '#cc4a4a' : '#3a7aaa'}
            strokeWidth='1'
          />
          <path
            d='M1 7c0 2.76 2.24 5 5 5s5-2.24 5-5'
            stroke={isRecording ? '#cc4a4a' : '#3a7aaa'}
            strokeWidth='1'
            fill='none'
          />
          <line
            x1='6' y1='12' x2='6' y2='13.5'
            stroke={isRecording ? '#cc4a4a' : '#3a7aaa'}
            strokeWidth='1'
          />
        </svg>
      </button>

      {/* Text input */}
      <input
        type='text'
        value={inputDraft}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          isRecording
            ? 'Recording… click mic to stop'
            : 'Talk to MAIHERA…'
        }
        style={{
          flex: 1,
          height: '30px',
          background: '#0a1520',
          border: '0.5px solid #0e2235',
          borderRadius: '6px',
          padding: '0 10px',
          fontSize: '11px',
          color: '#4a8aaa',
          outline: 'none',
          caretColor: '#3a7aaa',
        }}
      />

      {/* Focus mode button */}
      <button
        onClick={handleFocusMode}
        style={{
          height: '28px',
          padding: '0 12px',
          borderRadius: '20px',
          border: `0.5px solid ${focusModeActive ? FOCUS_COLOR : '#0e2a44'}`,
          background: focusModeActive ? FOCUS_ACTIVE_BG : 'transparent',
          color: focusModeActive ? FOCUS_COLOR : '#2a5070',
          fontSize: '9px',
          cursor: 'pointer',
          whiteSpace: 'nowrap',
          flexShrink: 0,
          transition: 'all 0.2s ease',
          letterSpacing: '0.05em',
        }}
      >
        {focusModeActive ? '● Focused' : 'Focus mode'}
      </button>

    </div>
  )
}