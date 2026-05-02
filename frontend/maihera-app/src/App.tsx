import { useEffect } from 'react'
import { TopBar } from './components/TopBar/TopBar'
import { LeftPanel } from './components/LeftPanel/LeftPanel'
import { CenterGraph } from './components/CenterGraph/CenterGraph'
import { RightPanel } from './components/RightPanel/RightPanel'
import { BottomBar } from './components/BottomBar/BottomBar'
import { wsService } from './services/websocket'
import { initAudio } from './services/audio'

export default function App() {
  useEffect(() => {
    // Initialize audio playback listener
    initAudio()

    // Connect WebSocket to backend
    const connectTimer = setTimeout(() => {
      wsService.connect()
    }, 500)

    const sessionTimer = setTimeout(() => {
      wsService.send('session_start', {})
    }, 2500)

    return () => {
      clearTimeout(connectTimer)
      clearTimeout(sessionTimer)
      wsService.disconnect()
    }
  }, [])

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      width: '100vw',
      background: '#080c14',
      overflow: 'hidden',
    }}>

      {/* Top bar — full width, fixed height */}
      <TopBar />

      {/* Main area — fills remaining height */}
      <div style={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
        position: 'relative',
      }}>
        <LeftPanel />
        <CenterGraph />
        <RightPanel />
      </div>

      {/* Bottom bar — spans center + right */}
      <BottomBar />

    </div>
  )
}