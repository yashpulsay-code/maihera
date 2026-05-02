import { useEffect, useRef } from 'react'
import { useGraphStore } from '../../stores/graphStore'
import { useUIStore } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import { useVoiceStore } from '../../stores/voiceStore'
import { NODE_COLORS } from '../../types/graph'
import type { GraphNode } from '../../types/graph'
import { wsService } from '../../services/websocket'

function relativeTime(isoString: string): string {
  try {
    const diff = (Date.now() - new Date(isoString).getTime()) / 1000
    if (diff < 3600) return `${Math.floor(diff / 60)} minutes ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`
    return `${Math.floor(diff / 86400)} days ago`
  } catch {
    return ''
  }
}

function SignalBar({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color: string
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px' }}>
      <span style={{ fontSize: '8px', color: '#1e3a5a', width: '58px', flexShrink: 0 }}>
        {label}
      </span>
      <div style={{
        flex: 1, height: '2px', background: '#0e1d30',
        borderRadius: '2px', position: 'relative',
      }}>
        <div style={{
          position: 'absolute', left: 0, top: 0,
          width: `${Math.round(value * 100)}%`,
          height: '100%', borderRadius: '2px',
          background: color,
          transition: 'width 0.3s ease',
        }} />
      </div>
      <span style={{ fontSize: '8px', color: '#2a5070', width: '28px', textAlign: 'right' }}>
        {value.toFixed(2)}
      </span>
    </div>
  )
}

function NodeInspect({ node }: { node: GraphNode }) {
  const { setRightPanelMode } = useUIStore()
  const nodeColor = NODE_COLORS[node.type] ?? '#1a2a3a'

  const handleAskMaihera = () => {
    wsService.send('chat', { text: `Tell me about ${node.label}`, context_node_id: node.id })
    setRightPanelMode('chat')
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', padding: '12px',
    }}>

      {/* Back button */}
      <button
        onClick={() => setRightPanelMode('chat')}
        style={{
          background: 'transparent',
          border: 'none',
          color: '#2a5070',
          fontSize: '9px',
          cursor: 'pointer',
          textAlign: 'left',
          padding: '0 0 12px 0',
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
        }}
      >
        ← Back to chat
      </button>

      {/* Node type badge */}
      <div style={{
        fontSize: '8px',
        letterSpacing: '0.1em',
        color: nodeColor,
        textTransform: 'uppercase',
        marginBottom: '4px',
      }}>
        {node.type}
        {node.project_id && (
          <span style={{ color: '#1e3a5a', marginLeft: '6px' }}>
            · {node.project_id.slice(0, 8)}
          </span>
        )}
      </div>

      {/* Node label */}
      <div style={{
        fontSize: '14px',
        color: '#5aaad4',
        fontWeight: 500,
        lineHeight: 1.3,
        marginBottom: '8px',
      }}>
        {node.label}
      </div>

      {/* Description */}
      {node.description && (
        <div style={{
          fontSize: '10px',
          color: '#2a5070',
          lineHeight: 1.6,
          marginBottom: '12px',
          borderBottom: '0.5px solid #0e1d30',
          paddingBottom: '12px',
        }}>
          {node.description}
        </div>
      )}

      {/* Signals */}
      <div style={{ marginBottom: '12px' }}>
        <div style={{
          fontSize: '8px', letterSpacing: '0.1em',
          color: '#1e3a5a', textTransform: 'uppercase',
          marginBottom: '8px',
        }}>
          Signals
        </div>
        <SignalBar label='Importance' value={node.importance ?? 0} color='#1a5a8a' />
        <SignalBar label='Attention'  value={node.attention  ?? 0} color='#1a6a4a' />
        <SignalBar label='Resistance' value={node.resistance ?? 0} color='#8a2a1a' />
        <SignalBar label='Urgency'    value={node._urgency   ?? 0} color='#8a6a1a' />
      </div>

      {/* Meta */}
      <div style={{
        display: 'flex', gap: '6px', flexWrap: 'wrap',
        marginBottom: '12px',
        borderTop: '0.5px solid #0e1d30',
        paddingTop: '10px',
      }}>
        {[node.status, node.workspace, node.source].filter(Boolean).map(tag => (
          <span key={tag} style={{
            fontSize: '8px',
            padding: '2px 6px',
            borderRadius: '3px',
            border: '0.5px solid #0e2235',
            color: '#2a5070',
          }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Last touched */}
      {node.last_touched && (
        <div style={{ fontSize: '8px', color: '#1e3a5a', marginBottom: '16px' }}>
          Last touched {relativeTime(node.last_touched)}
        </div>
      )}

      {/* Ask MAIHERA */}
      <button
        onClick={handleAskMaihera}
        style={{
          marginTop: 'auto',
          background: '#0a1a2e',
          border: '0.5px solid #1a4a6a',
          borderRadius: '6px',
          color: '#4a9ecc',
          fontSize: '10px',
          padding: '8px 12px',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        Ask MAIHERA about this →
      </button>
    </div>
  )
}

function ChatPanel() {
  const { messages } = useChatStore()
  const { isSpeaking, currentText } = useVoiceStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: '12px',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
    }}>
      {messages.length === 0 && (
        <div style={{
          fontSize: '10px',
          color: '#1e3a5a',
          textAlign: 'center',
          marginTop: '40px',
          lineHeight: 1.6,
        }}>
          MAIHERA is watching.<br />
          <span style={{ color: '#0e2a3a' }}>
            She'll speak when something needs your attention.
          </span>
        </div>
      )}

      {messages.map(msg => (
        <div
          key={msg.id}
          style={{
            display: 'flex',
            flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
            alignItems: 'flex-start',
            gap: '8px',
          }}
        >
          {/* Avatar */}
          {msg.role === 'maihera' && (
            <div style={{
              width: '20px', height: '20px',
              borderRadius: '50%',
              background: '#3a1a8a',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '8px',
              color: '#8a6adc',
              marginTop: '1px',
            }}>
              M
            </div>
          )}

          {/* Bubble */}
          <div style={{
            maxWidth: '80%',
            background: msg.role === 'maihera' ? '#0a1520' : '#0a1a2e',
            border: `0.5px solid ${msg.role === 'maihera' ? '#0e2235' : '#0e2a44'}`,
            borderRadius: msg.role === 'maihera'
              ? '2px 8px 8px 8px'
              : '8px 2px 8px 8px',
            padding: '8px 10px',
          }}>
            <div style={{
              fontSize: '11px',
              color: msg.role === 'maihera' ? '#4a8aaa' : '#3a7a7a',
              lineHeight: 1.5,
            }}>
              {msg.text}
            </div>
            <div style={{
              fontSize: '8px',
              color: '#1e3a5a',
              marginTop: '4px',
              textAlign: msg.role === 'user' ? 'right' : 'left',
            }}>
              {new Date(msg.timestamp).toLocaleTimeString([], {
                hour: '2-digit', minute: '2-digit'
              })}
            </div>
          </div>
        </div>
      ))}

      {/* Speaking indicator */}
      {isSpeaking && currentText && (
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
        }}>
          <div style={{
            width: '20px', height: '20px',
            borderRadius: '50%',
            background: '#3a1a8a',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '8px',
            color: '#8a6adc',
          }}>
            M
          </div>
          <div style={{
            background: '#0a1520',
            border: '0.5px solid #0e2235',
            borderRadius: '2px 8px 8px 8px',
            padding: '8px 12px',
            display: 'flex',
            gap: '3px',
            alignItems: 'center',
          }}>
            {[0, 1, 2].map(i => (
              <div
                key={i}
                style={{
                  width: '4px', height: '4px',
                  borderRadius: '50%',
                  background: '#3a8fd4',
                  animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                }}
              />
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

export function RightPanel() {
  const { rightPanelMode, selectedNodeId } = useUIStore()
  const { nodes } = useGraphStore()

  const selectedNode = selectedNodeId ? nodes.get(selectedNodeId) : null

  return (
    <div style={{
      width: '300px',
      minWidth: '300px',
      height: '100%',
      background: 'rgba(8,12,20,0.88)',
      borderLeft: '0.5px solid #0e1d30',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      flexShrink: 0,
    }}>

      {/* Panel header */}
      <div style={{
        padding: '10px 12px',
        borderBottom: '0.5px solid #0e1d30',
        fontSize: '8px',
        letterSpacing: '0.12em',
        color: '#1e3a5a',
        textTransform: 'uppercase',
        flexShrink: 0,
      }}>
        {rightPanelMode === 'chat' ? 'MAIHERA' : 'Node inspect'}
      </div>

      {/* Panel content */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {rightPanelMode === 'inspect' && selectedNode
          ? <NodeInspect node={selectedNode} />
          : <ChatPanel />
        }
      </div>

      {/* Pulse animation keyframes */}
      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
          40% { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </div>
  )
}