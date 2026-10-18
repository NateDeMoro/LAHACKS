// Every HTTP call lives here. Shapes marked ASSUMED are routes not yet on main (backend branch sim-ff);
// adjust them here only. VITE_MOCK=1 serves fixture data from mock.ts instead of the network.
import type { I9, IntakeCard, IntakeRecord, PatientRow, RunStatus, Wearable } from './types'
import * as mock from './mock'

export const MOCK = import.meta.env.VITE_MOCK === '1'

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${method} ${url}: ${r.status} ${await r.text().catch(() => '')}`)
  return r.json() as Promise<T>
}

// ASSUMED: [{patient_id, name, arrival_ts, bed, called_in_ts|null, simulated}]
export const getPatients = (): Promise<PatientRow[]> => MOCK ? mock.patients() : req('GET', '/patients')
// ASSUMED: no body
export const calledIn = (id: string): Promise<unknown> => MOCK ? mock.calledIn(id) : req('POST', `/patients/${encodeURIComponent(id)}/called-in`)
// ASSUMED: I9 rows since arrival, time order
export const getHistory = (id: string): Promise<I9[]> => MOCK ? mock.history(id) : req('GET', `/patients/${encodeURIComponent(id)}/history`)

// RunStatus gains kind and sim_now (ASSUMED)
export const getRun = (): Promise<RunStatus> => MOCK ? mock.run() : req('GET', '/sim/run')
export const simStart = (): Promise<RunStatus> => MOCK ? mock.start() : req('POST', '/sim/scenario')
export const simStop = (): Promise<RunStatus> => MOCK ? mock.stop() : req('POST', '/sim/run/stop')
export const simReset = (): Promise<RunStatus> => MOCK ? mock.reset() : req('POST', '/sim/run/reset')
// ASSUMED: body {minutes}; resolves when replay is done; 409 if no scenario
export const simSkip = (minutes: number): Promise<RunStatus> => MOCK ? mock.skip(minutes) : req('POST', '/sim/skip', { minutes })

// ASSUMED: each row also has `simulated: boolean`
export const getWearables = (): Promise<Wearable[]> => MOCK ? mock.wearables() : req('GET', '/intake/wearables')
// I2 gains optional `name` (ASSUMED)
export const postIntake = (rec: IntakeRecord): Promise<{ wearable_id: number; patient_id: string }> => MOCK ? mock.intake(rec) : req('POST', '/intake', rec)
export const getCard = (id: string): Promise<IntakeCard> => MOCK ? mock.card(id) : req('GET', `/intake/${encodeURIComponent(id)}`)
