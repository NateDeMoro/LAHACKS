import { useSyncExternalStore } from 'react'
import type { I8, I9, I10, I13, I14 } from './types'

export interface State {
  connected: boolean
  i8: Record<string, I8>
  i9: Record<string, I9>
  i13: Record<string, I13>
  i14: Record<string, I14>
  alerts: Record<string, I10> // open alerts by alert_id
}

let state: State = { connected: false, i8: {}, i9: {}, i13: {}, i14: {}, alerts: {} }
const listeners = new Set<() => void>()
const set = (s: State) => { state = s; listeners.forEach((l) => l()) }

export function handleMessage(msg: { type: string; data: any }) {
  const d = msg.data
  if (!d) return
  switch (msg.type) {
    case 'I8': return set({ ...state, i8: { ...state.i8, [d.patient_id]: d } })
    case 'I9': return set({ ...state, i9: { ...state.i9, [d.patient_id]: d } })
    case 'I13': return set({ ...state, i13: { ...state.i13, [d.patient_id]: d } })
    case 'I14': return set({ ...state, i14: { ...state.i14, [d.patient_id]: d } })
    case 'I10': {
      const alerts = { ...state.alerts }
      for (const old of d.supersedes ?? []) delete alerts[old]
      if (d.resolved) delete alerts[d.alert_id]
      else alerts[d.alert_id] = d
      return set({ ...state, alerts })
    }
  }
}
export const setConnected = (connected: boolean) => set({ ...state, connected })
export const getState = () => state
export const useStore = () => useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } }, () => state)

const rank: Record<string, number> = { warning: 1, urgent: 1, high: 2 }
export function openAlerts(s: State, pid: string): I10[] {
  return Object.values(s.alerts).filter((a) => a.patient_id === pid)
}
/** Alert text without the "<wearable label>: " prefix the alert logic adds. */
export const alertText = (a: I10) => (a.message ?? '').replace(/^[^:]*:\s*/, '')
/** "Outside usual" (personal baseline) alerts: shown quietly, never colour a tile. */
export const isMinor = (a: I10) => a.trigger === 'warning_persisted'
/** Alerts with the ones that matter first, minor ones last. */
export const rankedAlerts = (s: State, pid: string): I10[] =>
  openAlerts(s, pid).sort((a, b) => (+isMinor(a) - +isMinor(b)) || ((b.severity === 'high' ? 1 : 0) - (a.severity === 'high' ? 1 : 0)))
/** Tile colour: the NEWS2 band (0-4 low green, 5-6 medium amber, 7+ high red), raised by any open non-minor alert (warning/urgent -> amber, high -> red). */
export function tileSeverity(s: State, pid: string, news2?: number | null): 'low' | 'amber' | 'high' {
  let top = (news2 ?? 0) >= 7 ? 2 : (news2 ?? 0) >= 5 ? 1 : 0
  for (const a of openAlerts(s, pid)) if (!isMinor(a)) top = Math.max(top, rank[a.severity ?? ''] ?? 0)
  return top === 2 ? 'high' : top === 1 ? 'amber' : 'low'
}
