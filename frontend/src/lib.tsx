import { createContext, useContext } from 'react'
import { staleSecs, useStore } from './store'
import type { PatientRow, RunStatus } from './types'

export type Mode = 'live' | 'sim'
export interface Ctx {
  mode: Mode; setMode: (m: Mode) => void
  patients: PatientRow[]      // visible: right mode, not called in, arrival order
  allPatients: PatientRow[]
  run: RunStatus | null
  now: number                 // ms; sim_now in Simulation mode, wall clock in Live mode
  refresh: () => Promise<void>
  route: string
}
export const AppCtx = createContext<Ctx>(null as unknown as Ctx)
export const useApp = () => useContext(AppCtx)

export const go = (hash: string) => { location.hash = hash }

const TZ = 'America/Los_Angeles'
export const fmtClock = (ms: number | string | null | undefined) =>
  ms == null ? '' : new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ })
export const waitingMin = (arrival: string | null | undefined, now: number) =>
  arrival ? Math.max(0, Math.round((now - Date.parse(arrival)) / 60000)) : null

export const VITALS = [
  { key: 'hr', label: 'Heart rate', short: 'HR', unit: 'bpm', title: 'Heart rate' },
  { key: 'resp_rate', label: 'Breathing', short: 'Resp', unit: 'per min', title: 'Breathing rate' },
  { key: 'spo2', label: 'SpO2', short: 'SpO2', unit: '%', title: 'SpO2' },
  { key: 'temp_c', label: 'Temp', short: 'Temp', unit: '°C', title: 'Temperature' },
] as const

export const show = (v: number | null | undefined) => (v == null ? '' : Number.isInteger(v) ? String(v) : v.toFixed(1))

export type Sev = 'low' | 'amber' | 'high'
export const SEV = {
  low: { word: 'Low', text: 'text-muted', num: 'text-ink', card: 'bg-ground border border-line', box: 'bg-ground border border-line' },
  amber: { word: 'Medium', text: 'text-urgent', num: 'text-ink', card: 'bg-urgent-tint border-2 border-urgent-solid', box: 'bg-urgent-tint border border-urgent-solid' },
  high: { word: 'High', text: 'text-high', num: 'text-ink', card: 'bg-high-tint border-2 border-high', box: 'bg-high-tint border border-high' },
} as const

export function Glyph({ sev, size = 12 }: { sev: Sev; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" style={{ flexShrink: 0 }}>
      {sev === 'low' && <circle cx="7" cy="7" r="5.5" fill="none" stroke="#8C98A1" strokeWidth="2.4" />}
      {sev === 'amber' && <path d="M7 1 L13.5 13 L0.5 13 Z" fill="#E8A317" />}
      {sev === 'high' && <path d="M7 0.5 L13.5 7 L7 13.5 L0.5 7 Z" fill="#B7261E" />}
    </svg>
  )
}

// Safe and unknown stay neutral so only vitals that need a look carry colour.
export const levelBorder = (l?: string | null) =>
  l === 'danger' ? 'border-l-high' : l === 'warning' ? 'border-l-urgent-solid' : 'border-l-line'

/** Seconds since this patient's last data frame, or null when fresh, never seen, or no stream is expected. */
export function useStale(pid: string): number | null {
  const { mode, run } = useApp()
  const s = useStore()
  if (run?.state === 'ended' || (mode === 'sim' && run?.state !== 'running')) return null
  return staleSecs(s, pid, Date.now())
}
export const fmtStale = (secs: number) => `No data for ${secs < 60 ? `${secs} s` : `${Math.floor(secs / 60)} min`}`

/** Vital tag colour follows its NEWS2 points (0 green, 1-2 amber, 3 red); falls back to the engine's level without points. */
export const levelFromPoints = (pts?: number | null, fallback?: string | null) =>
  pts == null ? fallback : pts >= 3 ? 'danger' : pts >= 1 ? 'warning' : 'safe'
