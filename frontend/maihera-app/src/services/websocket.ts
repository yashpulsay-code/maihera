import { useGraphStore } from '../stores/graphStore'
import { useVoiceStore } from '../stores/voiceStore'
import { useSessionStore } from '../stores/sessionStore'
import { useUIStore } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import type { AnyWSMessage, MaiheraSpeak, BriefingSegmentPayload } from '../types/ws_messages'

const WS_URL = 'ws://localhost:8000/ws/brain'
const RECONNECT_DELAY_MS = 3000

class WebSocketService {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private isConnecting = false
  private manualClose = false

  connect(url: string = WS_URL): void {
    if (this.isConnecting || this.ws?.readyState === WebSocket.OPEN) return
    this.isConnecting = true
    this.manualClose = false

    console.log('[WS] Connecting to', url)

    try {
      this.ws = new WebSocket(url)
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err)
      this.isConnecting = false
      this.scheduleReconnect(url)
      return
    }

    this.ws.onopen = () => {
      console.log('[WS] Connected.')
      this.isConnecting = false
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data) as AnyWSMessage
        this.handleMessage(msg)
      } catch (err) {
        console.warn('[WS] Failed to parse message:', err)
      }
    }

    this.ws.onclose = () => {
      console.log('[WS] Disconnected.')
      this.isConnecting = false
      this.ws = null
      if (!this.manualClose) {
        this.scheduleReconnect(url)
      }
    }

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err)
    }
  }

  private handleMessage(msg: AnyWSMessage): void {
    const { type, payload } = msg

    const graph = useGraphStore.getState()
    const voice = useVoiceStore.getState()
    const session = useSessionStore.getState()
    const ui = useUIStore.getState()
    const chat = useChatStore.getState()

    switch (type) {

      case 'full_sync': {
        const p = payload as { nodes: any[], edges: any[] }
        graph.fullSync(p.nodes, p.edges)
        console.log('[WS] full_sync — nodes:', p.nodes.length, 'edges:', p.edges.length)
        break
      }

      case 'node_upsert':
        graph.upsertNode(payload as any)
        break

      case 'node_delete':
        graph.deleteNode((payload as { id: string }).id)
        break

      case 'edge_upsert':
        graph.upsertEdge(payload as any)
        break

      case 'edge_delete':
        graph.deleteEdge((payload as { id: string }).id)
        break

      case 'signal_update': {
        const p = payload as { id: string, signals: any }
        graph.updateSignals(p.id, p.signals)
        break
      }

      case 'maihera_speak': {
        const p = payload as MaiheraSpeak
        voice.enqueueItem({
          text: p.text,
          node_ids: p.node_ids,
          priority: p.priority,
          queued_at: msg.timestamp
        })
        if (p.audio_file) {
          // Playback trigger only — don't add duplicate chat message
          voice.setPendingAudio(p.audio_file)
        } else {
          // First notification — add to chat
          chat.addMessage({
            role: 'maihera',
            text: p.text,
            node_ids: p.node_ids
          })
        }
        break
      }

      case 'briefing_start':
        ui.setBriefing(true)
        console.log('[WS] Briefing started.')
        break

      case 'briefing_segment': {
        const p = payload as BriefingSegmentPayload
        ui.setHighlightedNodes(p.node_ids)
        break
      }

      case 'briefing_end':
        ui.setBriefing(false)
        ui.clearHighlights()
        console.log('[WS] Briefing ended.')
        break

      case 'focus_mode_change': {
        const p = payload as { active: boolean, session_id: string | null }
        session.setFocusMode(p.active, p.session_id)
        break
      }

      case 'nudge_queue_update': {
        const p = payload as { nudges: any[] }
        session.setNudgeQueue(p.nudges)
        break
      }

      case 'system_status': {
        const p = payload as { status: any }
        session.setStatus(p.status)
        break
      }

      default:
        console.debug('[WS] Unknown message type:', type)
    }
  }

  send(type: string, payload: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, payload }))
    } else {
      console.warn('[WS] Cannot send — not connected. Type:', type)
    }
  }

  private scheduleReconnect(url: string): void {
    if (this.reconnectTimer) return
    console.log(`[WS] Reconnecting in ${RECONNECT_DELAY_MS}ms...`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect(url)
    }, RECONNECT_DELAY_MS)
  }

  disconnect(): void {
    this.manualClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

// Singleton instance
export const wsService = new WebSocketService()