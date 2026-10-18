import { createContext, useContext } from 'react'
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
  { key: 'hr', label: 'HEART RATE', short: 'HR', unit: 'bpm', title: 'Heart rate' },
  { key: 'resp_rate', label: 'BREATHING', short: 'RESP', unit: 'per min', title: 'Breathing rate' },
  { key: 'spo2', label: 'SPO2', short: 'SPO2', unit: '%', title: 'SpO2' },
  { key: 'temp_c', label: 'TEMP', short: 'TEMP', unit: '°C', title: 'Temperature' },
] as const

export const show = (v: number | null | undefined) => (v == null ? '' : Number.isInteger(v) ? String(v) : v.toFixed(1))

export type Sev = 'low' | 'amber' | 'high'
export const SEV = {
  low: { word: 'Low', text: 'text-muted', num: 'text-ink', card: 'bg-low-tint border border-low', box: 'bg-low-tint border border-low' },
  amber: { word: 'Medium', text: 'text-urgent', num: 'text-urgent', card: 'bg-urgent-tint border-2 border-urgent-solid', box: 'bg-urgent-tint border border-urgent-solid' },
  high: { word: 'High', text: 'text-high', num: 'text-high', card: 'bg-high-tint border-2 border-high', box: 'bg-high-tint border border-high' },
} as const

export function Glyph({ sev, size = 12 }: { sev: Sev; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" style={{ flexShrink: 0 }}>
      {sev === 'low' && <circle cx="7" cy="7" r="5.5" fill="none" stroke="#2B7A57" strokeWidth="2.4" />}
      {sev === 'amber' && <path d="M7 1 L13.5 13 L0.5 13 Z" fill="#E8A317" />}
      {sev === 'high' && <path d="M7 0.5 L13.5 7 L7 13.5 L0.5 7 Z" fill="#B7261E" />}
    </svg>
  )
}

export const levelBorder = (l?: string | null) =>
  l === 'danger' ? 'border-l-high' : l === 'warning' ? 'border-l-urgent-solid' : 'border-l-low'

/** Vital tag colour follows its NEWS2 points (0 green, 1-2 amber, 3 red); falls back to the engine's level without points. */
export const levelFromPoints = (pts?: number | null, fallback?: string | null) =>
  pts == null ? fallback : pts >= 3 ? 'danger' : pts >= 1 ? 'warning' : 'safe'
