import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from './api'
import { startMockFeed } from './mock'
import { AppCtx, type Mode } from './lib'
import { startSocket } from './ws'
import type { PatientRow, RunStatus } from './types'
import Board from './pages/Board'
import Patient from './pages/Patient'
import CheckIn from './pages/CheckIn'
import ConnectionBanner from './components/ConnectionBanner'

const readRoute = () => location.hash.replace(/^#/, '') || '/'

export default function App() {
  const [mode, setMode] = useState<Mode>('live')
  const [all, setAll] = useState<PatientRow[]>([])
  const [run, setRun] = useState<RunStatus | null>(null)
  const [tick, setTick] = useState(0)
  const [route, setRoute] = useState(readRoute())

  useEffect(() => (api.MOCK ? startMockFeed() : startSocket()), [])
  useEffect(() => { const f = () => setRoute(readRoute()); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  useEffect(() => { const h = setInterval(() => setTick((t) => t + 1), 1000); return () => clearInterval(h) }, [])

  const refresh = useCallback(async () => {
    const [p, r] = await Promise.allSettled([api.getPatients(), api.getRun()])
    if (p.status === 'fulfilled') setAll(p.value)
    if (r.status === 'fulfilled') setRun(r.value)
  }, [])
  useEffect(() => { refresh(); const h = setInterval(refresh, 2000); return () => clearInterval(h) }, [refresh])

  const patients = useMemo(() => all
    .filter((p) => !p.called_in_ts && p.simulated === (mode === 'sim'))
    .sort((a, b) => Date.parse(a.arrival_ts ?? '') - Date.parse(b.arrival_ts ?? '')), [all, mode])
  const now = mode === 'sim' && run?.sim_now ? Date.parse(run.sim_now) : Date.now()
  void tick

  const ctx = { mode, setMode, patients, allPatients: all, run, now, refresh, route }
  const m = route.match(/^\/patient\/(.+)$/)
  return (
    <AppCtx.Provider value={ctx}>
      <div className="min-h-screen bg-ground text-[12px] leading-4">
        <ConnectionBanner />
        {m ? <Patient id={decodeURIComponent(m[1])} /> : route === '/checkin' ? <CheckIn /> : <Board />}
      </div>
    </AppCtx.Provider>
  )
}
