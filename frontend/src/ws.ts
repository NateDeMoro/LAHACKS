import { handleMessage, setConnected } from './store'

/** Opens /ws/dashboard and reconnects with a short backoff. Call once. */
export function startSocket() {
  let ws: WebSocket | null = null
  let timer: number | undefined
  let stopped = false
  const connect = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`)
    ws.onopen = () => setConnected(true)
    ws.onmessage = (e) => { try { handleMessage(JSON.parse(e.data)) } catch { /* ignore bad frame */ } }
    ws.onclose = () => { setConnected(false); if (!stopped) timer = window.setTimeout(connect, 1500) }
    ws.onerror = () => ws?.close()
  }
  connect()
  return () => { stopped = true; clearTimeout(timer); ws?.close() }
}
