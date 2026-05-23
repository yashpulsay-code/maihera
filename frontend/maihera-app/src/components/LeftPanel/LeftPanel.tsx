import { useGraphStore } from '../../stores/graphStore'
import { useSessionStore } from '../../stores/sessionStore'
import { useUIStore } from '../../stores/uiStore'
import { wsService } from '../../services/websocket'
import type { GraphNode } from '../../types/graph'

interface ScheduleEvent {
  time: string
  title: string
  active?: boolean
}

const mockSchedule: ScheduleEvent[] = [
  { time: '11:00', title: 'Design sync', active: true },
  { time: '13:30', title: 'Product review' },
  { time: '17:00', title: '1:1 with manager' },
]

function relativeTime(isoString: string): string {
  try {
    const diff = (Date.now() - new Date(isoString).getTime()) / 1000
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return ''
  }
}

function resistanceColor(resistance: number): string {
  if (resistance >= 0.6) return '#cc4a00'
  if (resistance >= 0.35) return '#cc8800'
  return '#1a5a3a'
}

// ── Standalone fetch action — no recursion risk ───────────────────────

async function submitProposalAction(
  nodeId: string,
  action: 'approve' | 'dismiss'
): Promise<void> {
  try {
    await fetch(`http://localhost:8000/brain/nodes/${nodeId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: action === 'approve' ? 'active' : 'archived'
      })
    })
  } catch (err) {
    console.error('[Proposals] Action failed:', err)
  }
}

// ── Proposal Card ─────────────────────────────────────────────────────

function ProposalCard({ node, onAction }: {
  node: GraphNode
  onAction: (id: string, action: 'approve' | 'dismiss') => void
}) {
  const isChallenge = node.description?.includes('[SELF_IMPROVEMENT]') ||
                      node.description?.includes('[DESIGN_CHALLENGE]')

  const labelColor = isChallenge ? '#cc8800' : '#4a9ecc'

  return (
    <div style={{
      background: 'rgba(10,18,30,0.7)',
      border: `0.5px solid ${isChallenge ? '#331a00' : '#0e2235'}`,
      borderRadius: '6px',
      padding: '8px 10px',
      marginBottom: '7px',
    }}>
      <div style={{
        fontSize: '7px',
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: labelColor,
        marginBottom: '4px',
      }}>
        {isChallenge ? 'proposal' : 'insight'}
      </div>

      <div style={{
        fontSize: '9px',
        color: '#4a8ab0',
        lineHeight: 1.4,
        marginBottom: '4px',
      }}>
        {node.label}
      </div>

      {node.description && (
        <div style={{
          fontSize: '8px',
          color: '#1e3a5a',
          lineHeight: 1.4,
          marginBottom: '7px',
          display: '-webkit-box',
          WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        } as React.CSSProperties}>
          {node.description.replace(/\[.*?\]\s*/g, '')}
        </div>
      )}

      <div style={{ display: 'flex', gap: '6px' }}>
        <button
          onClick={() => onAction(node.id, 'approve')}
          style={{
            flex: 1,
            height: '20px',
            border: '0.5px solid #1a4a2a',
            borderRadius: '4px',
            background: 'rgba(10,40,20,0.6)',
            color: '#1a9e6a',
            fontSize: '8px',
            cursor: 'pointer',
            letterSpacing: '0.06em',
          }}
        >
          Approve
        </button>
        <button
          onClick={() => onAction(node.id, 'dismiss')}
          style={{
            flex: 1,
            height: '20px',
            border: '0.5px solid #2a1a0e',
            borderRadius: '4px',
            background: 'rgba(30,10,5,0.5)',
            color: '#6a3a2a',
            fontSize: '8px',
            cursor: 'pointer',
            letterSpacing: '0.06em',
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────

export function LeftPanel() {
  const { nodes, upsertNode } = useGraphStore()
  const { energyLevel, maiheraStatus } = useSessionStore()
  const { leftPanelCollapsed, toggleLeftPanel } = useUIStore()

  const highSignalNodes: GraphNode[] = Array.from(nodes.values())
    .filter(n =>
      n.status === 'active' &&
      n.type !== 'project' &&
      (n.importance >= 0.5 || n.resistance >= 0.4)
    )
    .sort((a, b) => (b.importance + b.attention) - (a.importance + a.attention))
    .slice(0, 4)

  const dreamProposals: GraphNode[] = Array.from(nodes.values())
    .filter(n =>
      n.source === 'dream' &&
      n.status === 'active' &&
      (n.type === 'idea' || n.type === 'insight')
    )
    .sort((a, b) => b.importance - a.importance)
    .slice(0, 5)

  // Renamed to onProposalAction — calls submitProposalAction, no recursion
  const onProposalAction = async (
    nodeId: string,
    action: 'approve' | 'dismiss'
  ) => {
    const existing = nodes.get(nodeId)
    if (existing) {
      upsertNode({
        ...existing,
        status: action === 'approve' ? 'active' : 'archived'
      })
    }
    await submitProposalAction(nodeId, action)
  }

  return (
    <div style={{
      width: leftPanelCollapsed ? '0px' : '220px',
      minWidth: leftPanelCollapsed ? '0px' : '220px',
      height: '100%',
      background: 'rgba(8,12,20,0.88)',
      borderRight: leftPanelCollapsed ? 'none' : '0.5px solid #0e1d30',
      backdropFilter: 'blur(4px)',
      overflow: 'hidden',
      transition: 'width 0.25s ease, min-width 0.25s ease',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
    }}>

      {/* Collapse toggle */}
      <div
        onClick={toggleLeftPanel}
        style={{
          position: 'absolute',
          left: leftPanelCollapsed ? '4px' : '196px',
          top: '50px',
          width: '16px',
          height: '32px',
          background: '#0a1520',
          border: '0.5px solid #0e2235',
          borderRadius: '0 4px 4px 0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          zIndex: 10,
          transition: 'left 0.25s ease',
        }}
      >
        <span style={{ fontSize: '8px', color: '#2a5070' }}>
          {leftPanelCollapsed ? '›' : '‹'}
        </span>
      </div>

      <div style={{
        opacity: leftPanelCollapsed ? 0 : 1,
        transition: 'opacity 0.15s ease',
        overflow: 'hidden auto',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '12px 0',
      }}>

        {/* Section: Today */}
        <div style={{ padding: '0 14px 10px', borderBottom: '0.5px solid #0e1d30', marginBottom: '10px' }}>
          <div style={{ fontSize: '8px', letterSpacing: '0.12em', color: '#1e3a5a', textTransform: 'uppercase', marginBottom: '8px' }}>
            Today
          </div>
          {mockSchedule.map((event, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: '7px' }}>
              <span style={{ fontSize: '9px', color: '#2a5070', minWidth: '32px', fontVariantNumeric: 'tabular-nums', paddingTop: '1px' }}>
                {event.time}
              </span>
              <div style={{
                width: '5px', height: '5px', borderRadius: '50%', marginTop: '3px', flexShrink: 0,
                background: event.active ? '#4a9ecc' : '#1a3a5a',
                boxShadow: event.active ? '0 0 4px #4a9ecc' : 'none',
              }} />
              <span style={{ fontSize: '9px', color: event.active ? '#4a9ecc' : '#3a6a90', lineHeight: 1.4 }}>
                {event.title}{event.active ? ' · now' : ''}
              </span>
            </div>
          ))}
        </div>

        {/* Section: High Signal */}
        <div style={{ padding: '0 14px 10px', borderBottom: '0.5px solid #0e1d30', marginBottom: '10px' }}>
          <div style={{ fontSize: '8px', letterSpacing: '0.12em', color: '#1e3a5a', textTransform: 'uppercase', marginBottom: '8px' }}>
            High signal
          </div>
          {highSignalNodes.length === 0 ? (
            <div style={{ fontSize: '9px', color: '#1e3a5a' }}>No active signals.</div>
          ) : highSignalNodes.map(node => (
            <div key={node.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: '7px' }}>
              <div style={{
                width: '3px', minHeight: '28px', borderRadius: '2px', flexShrink: 0,
                background: resistanceColor(node.resistance),
              }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '9px', color: '#3a6a90', lineHeight: 1.3 }}>{node.label}</div>
                <div style={{ fontSize: '8px', color: '#1e3a5a', marginTop: '1px' }}>
                  {node.last_touched ? relativeTime(node.last_touched) : ''}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Section: Energy */}
        <div style={{ padding: '0 14px 10px', borderBottom: '0.5px solid #0e1d30', marginBottom: '10px' }}>
          <div style={{ fontSize: '8px', letterSpacing: '0.12em', color: '#1e3a5a', textTransform: 'uppercase', marginBottom: '8px' }}>
            Energy today
          </div>
          {energyLevel === null ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '9px', color: '#1e3a5a' }}>Not checked in yet</span>
              <span
                onClick={() => wsService.send('session_start', {})}
                style={{ fontSize: '9px', color: '#2a6088', cursor: 'pointer', textDecoration: 'underline' }}
              >
                Check in
              </span>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '9px', color: '#2a5070' }}>{energyLevel} / 10</span>
              <div style={{ display: 'flex', gap: '3px' }}>
                {Array.from({ length: 10 }, (_, i) => (
                  <div key={i} style={{
                    width: '5px', height: '5px', borderRadius: '50%',
                    background: i < energyLevel ? '#1a9e6a' : '#0e1d30',
                    border: i < energyLevel ? 'none' : '0.5px solid #1a3a5a',
                  }} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Section: Dream Mode Proposals */}
        <div style={{ padding: '0 14px 10px' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '8px',
          }}>
            <div style={{ fontSize: '8px', letterSpacing: '0.12em', color: '#1e3a5a', textTransform: 'uppercase' }}>
              Dream proposals
            </div>
            {dreamProposals.length > 0 && (
              <div style={{
                fontSize: '7px',
                color: '#2a5070',
                background: 'rgba(20,40,60,0.6)',
                border: '0.5px solid #0e2235',
                borderRadius: '8px',
                padding: '1px 6px',
              }}>
                {dreamProposals.length}
              </div>
            )}
          </div>

          {maiheraStatus === 'dream' ? (
            <div style={{ fontSize: '9px', color: '#2a5070', lineHeight: 1.5 }}>
              Dream Mode active — working...
            </div>
          ) : dreamProposals.length === 0 ? (
            <div style={{ fontSize: '9px', color: '#1e3a5a', lineHeight: 1.5 }}>
              No proposals yet. Dream Mode activates after 10 minutes idle.
            </div>
          ) : (
            dreamProposals.map(node => (
              <ProposalCard
                key={node.id}
                node={node}
                onAction={onProposalAction}
              />
            ))
          )}
        </div>

      </div>
    </div>
  )
}