import { useRef, useEffect, useCallback, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { useGraphStore } from '../../stores/graphStore'
import { useUIStore } from '../../stores/uiStore'
import { NODE_COLORS, EDGE_COLORS } from '../../types/graph'
import type { ForceNode, ForceLink } from '../../types/graph'

const NODE_SIZE_MIN = 4
const NODE_SIZE_MAX = 12

export function CenterGraph() {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<any>(null)

  const nodes = useGraphStore(s => s.nodes)
  const edges = useGraphStore(s => s.edges)
  const getForceGraphData = useGraphStore(s => s.getForceGraphData)
  const { highlightedNodeIds, selectNode } = useUIStore()

  const dimensions = useRef({ width: 800, height: 600 })

  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        dimensions.current = {
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        }
        if (graphRef.current) {
          graphRef.current.width(entry.contentRect.width)
          graphRef.current.height(entry.contentRect.height)
        }
      }
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  const graphData = useMemo(() => {
    return getForceGraphData()
  }, [nodes, edges])

  const nodeColor = useCallback((node: ForceNode) => {
    if (highlightedNodeIds.has(node.id)) return '#ffffff'
    return NODE_COLORS[node.type] ?? '#1a2a3a'
  }, [highlightedNodeIds])

  const nodeSize = useCallback((node: ForceNode) => {
    const importance = node.importance ?? 0.5
    return NODE_SIZE_MIN + importance * (NODE_SIZE_MAX - NODE_SIZE_MIN)
  }, [])

  const linkColor = useCallback((link: ForceLink) => {
    return EDGE_COLORS[link.type] ?? '#0d2035'
  }, [])

  const onNodeClick = useCallback((node: ForceNode) => {
    selectNode(node.id)
  }, [selectNode])

  const onBackgroundClick = useCallback(() => {
    selectNode(null)
  }, [selectNode])

  const handleZoomIn = () => graphRef.current?.zoom(
    graphRef.current.zoom() * 1.3, 300
  )
  const handleZoomOut = () => graphRef.current?.zoom(
    graphRef.current.zoom() * 0.7, 300
  )
  const handleRecenter = () => graphRef.current?.zoomToFit(400, 40)

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1,
        position: 'relative',
        overflow: 'hidden',
        background: '#080c14',
      }}
    >
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        width={dimensions.current.width}
        height={dimensions.current.height}
        backgroundColor='#080c14'
        nodeColor={nodeColor as any}
        nodeVal={nodeSize as any}
        nodeLabel={(node: any) => `${node.label} [${node.type}]`}
        linkColor={linkColor as any}
        linkWidth={1}
        onNodeClick={onNodeClick as any}
        onBackgroundClick={onBackgroundClick}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
          if (globalScale < 1.2) return
          const label = node.label as string
          const fontSize = 10 / globalScale
          ctx.font = `${fontSize}px sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.fillStyle = 'rgba(100,160,200,0.7)'
          ctx.fillText(
            label.length > 20 ? label.slice(0, 18) + '…' : label,
            node.x,
            node.y + (nodeSize(node as ForceNode) / globalScale) + 2
          )
        }}
        cooldownTicks={80}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
      />

      {/* Graph controls */}
      <div style={{
        position: 'absolute',
        bottom: '60px',
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        gap: '6px',
        zIndex: 10,
      }}>
        {[
          { label: '+', action: handleZoomIn },
          { label: '−', action: handleZoomOut },
          { label: '⊙', action: handleRecenter },
        ].map(({ label, action }) => (
          <button
            key={label}
            onClick={action}
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '6px',
              border: '0.5px solid #0e2235',
              background: 'rgba(8,12,20,0.88)',
              color: '#2a5070',
              fontSize: '14px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Node count */}
      <div style={{
        position: 'absolute',
        top: '8px',
        left: '8px',
        fontSize: '8px',
        color: '#1e3a5a',
        letterSpacing: '0.08em',
      }}>
        {graphData.nodes.length} nodes · {graphData.links.length} edges
      </div>
    </div>
  )
}