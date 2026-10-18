// Fixture data for VITE_MOCK=1. Mirrors the waiting-room demo: Live (presenter) plus six simulated patients.
import { handleMessage, setConnected } from './store'
import type { I8, I9, I10, IntakeCard, IntakeRecord, PatientRow, RunStatus, VitalValues, Wearable } from './types'

const BASE = Date.parse('2026-10-17T22:30:00-07:00')
const MIN = 60_000
const sim = { running: false, minutes: 0, runId: 0 }
const nowMs = () => BASE + sim.minutes * MIN
const iso = (ms: number) => new Date(ms).toISOString()

interface Spec { key: string; name: string; bed: string; arriveMin: number; age: number; sex: 'male' | 'female'; vitals: (m: number) => VitalValues; wearable: number }
const lin = (a: number, b: number, m: number, m0: number, m1: number) => a + (b - a) * Math.min(1, Math.max(0, (m - m0) / (m1 - m0)))
const SPECS: Spec[] = [
  { key: 'h1', name: 'Marcus Reyes', bed: 'Bed 1', arriveMin: -50, age: 24, sex: 'male', wearable: 11, vitals: () => ({ hr: 72, resp_rate: 14, spo2: 98, temp_c: 36.6 }) },
  { key: 'h2', name: 'Priya Nair', bed: 'Bed 2', arriveMin: -40, age: 41, sex: 'female', wearable: 12, vitals: () => ({ hr: 78, resp_rate: 15, spo2: 97, temp_c: 36.8 }) },
  { key: 'john', name: 'John Chamberlain', bed: 'Bed 3', arriveMin: -20, age: 67, sex: 'male', wearable: 13, vitals: (m) => ({
      hr: m < 31 ? 84 : lin(88, 104, m, 31, 40), resp_rate: m < 31 ? lin(15, 24, m, 12, 22) : lin(24, 27, m, 31, 40),
      spo2: m < 31 ? lin(97, 92, m, 12, 22) : lin(92, 89, m, 31, 40), temp_c: m < 31 ? 36.9 : lin(37.2, 38.6, m, 31, 40) }) },
  { key: 'u1', name: 'Dana Whitfield', bed: 'Bed 4', arriveMin: -15, age: 55, sex: 'female', wearable: 14, vitals: () => ({ hr: 96, resp_rate: 20, spo2: 95, temp_c: 37.4 }) },
  { key: 'c1', name: 'Omar Karim', bed: 'Bed 5', arriveMin: -10, age: 33, sex: 'male', wearable: 15, vitals: () => ({ hr: 88, resp_rate: 18, spo2: 96, temp_c: 37.1 }) },
  { key: 'c2', name: 'Elena Lindqvist', bed: 'Bed 6', arriveMin: -5, age: 29, sex: 'female', wearable: 16, vitals: () => ({ hr: 82, resp_rate: 17, spo2: 97, temp_c: 36.7 }) },
]
const pid = (s: Spec) => `sim-${sim.runId}-${s.key}`
const calledInOf = (s: Spec) => (s.key === 'h1' && sim.minutes >= 25 ? iso(BASE + 25 * MIN) : null)

export const patients = async (): Promise<PatientRow[]> => {
  const rows: PatientRow[] = [{ patient_id: 'demo-001', name: 'Presenter', arrival_ts: iso(Date.now() - 12 * MIN), bed: 'Strap 1', called_in_ts: null, simulated: false }]
  if (sim.running) for (const s of SPECS) rows.push({ patient_id: pid(s), name: s.name, arrival_ts: iso(BASE + s.arriveMin * MIN), bed: s.bed, called_in_ts: calledInOf(s), simulated: true })
  return rows
}
export const calledIn = async (_id?: string) => ({})
export const run = async (): Promise<RunStatus> => sim.running
  ? { state: 'running', kind: 'scenario', sim_now: iso(nowMs()) } : { state: 'live', kind: null, sim_now: null }
export const start = async () => { sim.runId++; sim.running = true; sim.minutes = 20; publishAll(); return run() }
export const stop = async () => { sim.running = false; return { state: 'ended', kind: 'scenario', sim_now: iso(nowMs()) } as RunStatus }
export const reset = async () => { sim.running = false; sim.minutes = 0; return run() }
export const skip = async (m: number) => {
  if (!sim.running) throw new Error('409 no scenario running')
  sim.minutes += m; publishAll(); return run()
}

const rangeOf = (v: string) => ({ resp_rate: { safe_low: 12, safe_high: 20, danger_low: 8, danger_high: 25 }, hr: { safe_low: 51, safe_high: 90, danger_low: 40, danger_high: 131 },
  spo2: { safe_low: 96, safe_high: null, danger_low: 91, danger_high: null }, temp_c: { safe_low: 36.1, safe_high: 38, danger_low: 35, danger_high: 39.1 } } as any)[v]
const ranges = (id: string): I8 => ({ patient_id: id, hr: rangeOf('hr'), resp_rate: rangeOf('resp_rate'), spo2: rangeOf('spo2'), temp_c: rangeOf('temp_c') })
const levelOf = (v: string, x: number | null | undefined) => {
  const r = rangeOf(v); if (x == null) return 'safe' as const
  if ((r.danger_low != null && x <= r.danger_low) || (r.danger_high != null && x >= r.danger_high)) return 'danger' as const
  if ((r.safe_low != null && x < r.safe_low) || (r.safe_high != null && x > r.safe_high)) return 'warning' as const
  return 'safe' as const
}
const news2Of = (v: VitalValues) => {
  let n = 0; const r = v.resp_rate ?? 16, o = v.spo2 ?? 98, h = v.hr ?? 70, t = v.temp_c ?? 37
  n += r <= 8 ? 3 : r <= 11 ? 1 : r <= 20 ? 0 : r <= 24 ? 2 : 3
  n += o <= 91 ? 3 : o <= 93 ? 2 : o <= 95 ? 1 : 0
  n += h <= 40 ? 3 : h <= 50 ? 1 : h <= 90 ? 0 : h <= 110 ? 1 : h <= 130 ? 2 : 3
  n += t <= 35 ? 3 : t <= 36 ? 1 : t <= 38 ? 0 : t <= 39 ? 1 : 2
  return n
}
const i9At = (s: Spec, m: number): I9 => {
  const v = s.vitals(m)
  const lv = { hr: levelOf('hr', v.hr), resp_rate: levelOf('resp_rate', v.resp_rate), spo2: levelOf('spo2', v.spo2), temp_c: levelOf('temp_c', v.temp_c) }
  const worst = (['resp_rate', 'spo2', 'hr', 'temp_c'] as const).find((k) => lv[k] === 'danger') ?? (['resp_rate', 'spo2', 'hr', 'temp_c'] as const).find((k) => lv[k] === 'warning')
  const trend = s.key === 'john' && m >= 23 && m < 31
  return { patient_id: pid(s), ts: iso(BASE + m * MIN), level: worst ? lv[worst] : 'safe', vital: worst ?? null,
    reason: worst ? `${worst === 'resp_rate' ? 'breathing' : worst} ${v[worst]?.toFixed(0)}, ${lv[worst]}` : null,
    vital_levels: lv, vital_values: v, news2: news2Of(v), trend_tier: trend ? 'warning' : null,
    trend_reason_fast: trend ? 'SpO2 may reach 90 within 15 min' : null }
}
export const history = async (id: string): Promise<I9[]> => {
  const s = SPECS.find((x) => id === pid(x)); if (!s) return []
  const out: I9[] = []
  for (let m = s.arriveMin; m <= sim.minutes; m++) out.push(i9At(s, m))
  return out
}

const sentAlerts = new Set<string>()
function alertsFor(s: Spec, i9: I9): I10[] {
  const out: I10[] = []; const id = pid(s)
  if (s.key === 'john' && i9.trend_tier) out.push({ alert_id: `${id}-trend`, patient_id: id, severity: 'warning', trigger: 'trend', vital: 'spo2', message: 'Bed 3: may reach danger soon (SpO2 may reach 90% within 15 min)' })
  if (s.key === 'john' && (i9.news2 ?? 0) >= 7 && i9.level === 'danger') out.push({ alert_id: `${id}-news2`, patient_id: id, severity: 'high', trigger: 'news2_total', message: `Bed 3: NEWS2 ${i9.news2} (SpO2, breathing)` })
  if (s.key === 'u1') out.push({ alert_id: `${id}-w`, patient_id: id, severity: 'urgent', trigger: 'warning_persisted', vital: 'hr', message: 'Bed 4: heart rate 96 above usual' })
  return out
}
function publishAll() {
  if (!sim.running) return
  for (const s of SPECS) {
    if (calledInOf(s)) continue
    const i9 = i9At(s, sim.minutes)
    handleMessage({ type: 'I8', data: ranges(pid(s)) })
    handleMessage({ type: 'I9', data: i9 })
    handleMessage({ type: 'I14', data: { patient_id: pid(s), news2: i9.news2 } })
    const john = s.key === 'john'
    if (john && sim.minutes >= 45) handleMessage({ type: 'I10', data: { alert_id: `${pid(s)}-trend`, patient_id: pid(s), resolved: true } })
    const want = alertsFor(s, i9)
    if (john && want.some((a) => a.trigger === 'news2_total')) handleMessage({ type: 'I10', data: { ...want.find((a) => a.trigger === 'news2_total')!, supersedes: [`${pid(s)}-trend`] } })
    for (const a of want) if (!sentAlerts.has(a.alert_id) && a.trigger !== 'news2_total') { sentAlerts.add(a.alert_id); handleMessage({ type: 'I10', data: a }) }
  }
}
export function startMockFeed() {
  setConnected(true)
  const tick = () => {
    const jit = (x: number | null | undefined, d: number) => (x == null ? null : +(x + (Math.random() - 0.5) * d).toFixed(1))
    handleMessage({ type: 'I13', data: { patient_id: 'demo-001', hr: jit(74, 3), resp_rate: jit(16, 1), spo2: null, temp_c: null, run_state: 'live' } })
    handleMessage({ type: 'I14', data: { patient_id: 'demo-001', news2: 2 } })
    handleMessage({ type: 'I9', data: { patient_id: 'demo-001', level: 'safe', vital_values: { hr: 74, resp_rate: 16 }, news2: 2 } })
    if (!sim.running) return
    for (const s of SPECS) {
      const v = s.vitals(sim.minutes)
      handleMessage({ type: 'I13', data: { patient_id: pid(s), hr: jit(v.hr, 2), resp_rate: jit(v.resp_rate, 0.6), spo2: jit(v.spo2, 0.6), temp_c: jit(v.temp_c, 0.1), run_state: 'running' } })
    }
  }
  tick(); const h = setInterval(tick, 1000)
  return () => clearInterval(h)
}

export const wearables = async (): Promise<Wearable[]> => [
  { wearable_id: 1, label: 'Strap 1 · Bed 4', patient_id: 'demo-001', simulated: false },
  { wearable_id: 2, label: 'Strap 2 · Bed 5', patient_id: null, simulated: false },
  { wearable_id: 3, label: 'Strap 3 · Bed 1', patient_id: null, simulated: false },
  ...SPECS.map((s) => ({ wearable_id: s.wearable, label: `Sim strap · ${s.bed}`, patient_id: sim.running ? pid(s) : null, simulated: true })),
]
export const intake = async (rec: IntakeRecord) => ({ wearable_id: rec.wearable_id ?? 1, patient_id: rec.patient_id ?? 'demo-001' })
export const card = async (id: string): Promise<IntakeCard> => {
  const s = SPECS.find((x) => id === pid(x))
  const r = ranges(id)
  return { ranges: r, adjuster: 'done', context: { patient_id: id, name: s?.name ?? 'Presenter', age: s?.age ?? 30, sex: s?.sex ?? 'male', height_cm: 172, weight_kg: 94, bmi: 31.8,
    conditions: ['hypertension', 'diabetes'], medications: ['Metoprolol', 'Lisinopril'], chief_complaint: 'Fever and chills for two days, barely eating, feel weak.',
    triage: { sbp: 128, dbp: 80, alertness: 'alert', pain: 3, on_oxygen: false, level: 3 }, wearable_id: s?.wearable ?? 1 },
    conditions: condCard(id) }
}
// Typed-condition states for the profile card, by patient id (try /patient/cond-loading etc. with VITE_MOCK=1).
const found = { typed: 'sepsis', canonical: 'Sepsis', code: 'A41.9', status: 'found' as const }
function condCard(id: string): IntakeCard['conditions'] {
  if (id === 'cond-loading') return { state: 'pending', resolution: null }
  if (id === 'cond-failed') return { state: 'failed', resolution: null }
  if (id === 'cond-error') return { state: 'done', infra_errors: ['A41.9: PubMed did not answer'], resolution: { items: [found] } }
  if (id === 'cond-none') return { state: 'done', resolution: { items: [{ typed: 'eczema', canonical: 'Eczema', code: 'L30.9', status: 'found' }, { typed: 'blorptic syndrome', status: 'not_found' }] } }
  return null
}
