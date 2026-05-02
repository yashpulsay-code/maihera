import React, { useEffect, useState } from 'react'
import { useSessionStore } from '../../stores/sessionStore'
import { useUIStore } from '../../stores/uiStore'

type ElectronStyle = React.CSSProperties & { WebkitAppRegion?: string }

const STATUS_COLORS = {
  watching: '#1a9e6a',
  thinking: '#cc8800',
  speaking: '#3a8fd4',
  dream:    '#6a3a9e',
}

const STATUS_LABELS = {
  watching: 'Watching',
  thinking: 'Thinking',
  speaking: 'Speaking',
  dream:    'Dream Mode',
}

const WORKSPACE_LABELS = {
  office:   'Office hours',
  personal: 'Personal mode',
  weekend:  'Weekend',
}

function formatDateTime(date: Date): string {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const day = days[date.getDay()]
  const d = date.getDate()
  const month = months[date.getMonth()]
  const hours = date.getHours()
  const minutes = date.getMinutes().toString().padStart(2, '0')
  const ampm = hours >= 12 ? 'PM' : 'AM'
  const h = (hours % 12 || 12).toString()
  return `${day} ${d} ${month} · ${h}:${minutes} ${ampm}`
}

export function TopBar() {
  const [time, setTime] = useState(() => formatDateTime(new Date()))
  const { maiheraStatus, workspaceContext } = useSessionStore()
  const { toggleLeftPanel } = useUIStore()

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(formatDateTime(new Date()))
    }, 1000)
    return () => clearInterval(interval)
  }, [])

  const statusColor = STATUS_COLORS[maiheraStatus]
  const statusLabel = STATUS_LABELS[maiheraStatus]
  const workspaceLabel = workspaceContext
    ? WORKSPACE_LABELS[workspaceContext]
    : null

  return (
    <div style={{
      height: '38px',
      background: 'rgba(8,12,20,0.96)',
      borderBottom: '0.5px solid #0e1d30',
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      gap: '12px',
      flexShrink: 0,
      userSelect: 'none',
      WebkitAppRegion: 'drag',
    } as ElectronStyle}>

      {/* Logo — no-drag so it stays clickable */}
      <span
        onClick={toggleLeftPanel}
        style={{
          fontSize: '11px',
          fontWeight: 600,
          color: '#3a8fd4',
          letterSpacing: '0.14em',
          cursor: 'pointer',
          WebkitAppRegion: 'no-drag',
        } as ElectronStyle}
      >
        MAIHERA
      </span>

      <div style={{ width: '0.5px', height: '16px', background: '#0e1d30' }} />

      {/* Time */}
      <span style={{
        fontSize: '11px',
        color: '#2a5070',
        fontVariantNumeric: 'tabular-nums',
      }}>
        {time}
      </span>

      {/* Workspace pill */}
      {workspaceLabel && (
        <>
          <div style={{ width: '0.5px', height: '16px', background: '#0e1d30' }} />
          <span style={{
            fontSize: '9px',
            padding: '2px 8px',
            borderRadius: '20px',
            border: '0.5px solid #0e2a44',
            color: '#2a6088',
          }}>
            {workspaceLabel}
          </span>
        </>
      )}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Status indicator */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        WebkitAppRegion: 'no-drag',
      } as ElectronStyle}>
        <div style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          background: statusColor,
          boxShadow: `0 0 5px ${statusColor}`,
          transition: 'background 0.3s, box-shadow 0.3s',
        }} />
        <span style={{
          fontSize: '10px',
          color: statusColor,
          transition: 'color 0.3s',
        }}>
          {statusLabel}
        </span>
      </div>

      {/* Frameless window controls */}
      <div style={{
        display: 'flex',
        gap: '8px',
        marginLeft: '12px',
        WebkitAppRegion: 'no-drag',
      } as ElectronStyle}>
        {(['minimizeWindow', 'maximizeWindow', 'closeWindow'] as const).map((action, i) => (
          <div
            key={action}
            onClick={() => window.maihera?.[action]()}
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              background: (['#cc8800', '#1a9e6a', '#cc4a4a'] as string[])[i],
              cursor: 'pointer',
              opacity: 0.7,
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '0.7')}
          />
        ))}
      </div>

    </div>
  )
}