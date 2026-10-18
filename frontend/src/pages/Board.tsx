import { useState } from 'react'
import * as api from '../api'
import { Glyph, fmtClock, go, useApp, type Mode } from '../lib'
import { tileSeverity, useStore } from '../store'
import Tile from '../components/Tile'

const ghost = 'flex items-center h-9 px-3.5 rounded-[6px] gap-1.5 bg-ground border border-edge text-[14px] leading-5 font-[500] text-ink'

export default function Board() {
  const { mode, setMode, patients, run, now, refresh } = useApp()
  const s = useStore()
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const act = (name: string, fn: () => Promise<unknown>) => async () => {
    if (busy) return
    setBusy(name); setErr(null)
    try { await fn() } catch (e) { setErr(String((e as Error).message ?? e)) }
    try { await refresh() } finally { setBusy(null) }
  }
  const sevs = patients.map((p) => tileSeverity(s, p.patient_id))
  const highs = sevs.filter((x) => x === 'high').length, ambers = sevs.filter((x) => x === 'amber').length
  const rows: typeof patients[] = []
  for (let i = 0; i < patients.length; i += 3) rows.push(patients.slice(i, i + 3))
  const scenarioOn = run?.state === 'running'
  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between shrink-0 pt-7 pb-5 px-10">
        <div className="flex flex-col gap-1">
          <div className="text-[28px] leading-8 tracking-[-0.01em] font-[600] text-ink">Waiting room</div>
          <div className="text-[14px] leading-5 text-muted">{patients.length} patients · first come, first served · order never changes</div>
        </div>
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2">
            <label className="flex items-center h-9 px-3 rounded-[6px] gap-2.5 bg-ground border border-edge">
              <span className="font-mono text-[11px] leading-3.5 tracking-[0.08em] text-muted">MODE</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} className="bg-transparent text-[14px] leading-5 font-[500] text-ink outline-none cursor-pointer">
                <option value="live">Live</option>
                <option value="sim">Simulation</option>
              </select>
            </label>
            {mode === 'sim' ? (
              <div className="flex items-center gap-1.5">
                <button disabled={!!busy} onClick={act('start', api.simStart)} className="flex items-center h-9 px-3.5 rounded-[6px] gap-1.5 bg-navy text-[14px] leading-5 font-[500] text-ground">Start</button>
                <button disabled={!!busy} onClick={act('stop', api.simStop)} className={ghost}>Stop</button>
                <button disabled={!!busy} onClick={act('reset', api.simReset)} className={ghost}>Reset</button>
                <button disabled={!!busy || !scenarioOn} onClick={act('skip10', () => api.simSkip(10))} className={ghost}>+10m</button>
                <button disabled={!!busy || !scenarioOn} onClick={act('skip15', () => api.simSkip(15))} className={ghost}>+15m</button>
              </div>
            ) : (
              <button onClick={() => go('/checkin')} className="flex items-center h-9 px-3.5 rounded-[6px] bg-navy text-[14px] leading-5 font-[500] text-ground">Check in a patient</button>
            )}
          </div>
          <div className="w-px h-7 shrink-0 bg-line" />
          <div className="flex items-center gap-2"><Glyph sev="high" size={14} /><div className="font-mono text-[20px] leading-6 font-[500] text-high">{highs}</div><div className="text-[14px] leading-5 font-[500] text-ink">high</div></div>
          <div className="flex items-center gap-2"><Glyph sev="amber" size={14} /><div className="font-mono text-[20px] leading-6 font-[500] text-urgent">{ambers}</div><div className="text-[14px] leading-5 font-[500] text-ink">urgent</div></div>
          <div className="w-px h-7 shrink-0 bg-line" />
          <div className="font-mono text-[16px] leading-5 text-muted" title={mode === 'sim' ? 'simulated time' : 'time'}>{fmtClock(now)}</div>
        </div>
      </div>
      {err && <div className="px-10 pb-2 text-[13px] text-high">{err}</div>}
      <div className="flex flex-col pb-8 gap-4 px-10">
        {patients.length === 0 && <div className="text-[15px] text-muted py-10">{mode === 'sim' ? 'No simulated patients. Press Start.' : 'No live patients. Check one in.'}</div>}
        {rows.map((r, ri) => (
          <div key={ri} className="flex gap-4">
            {r.map((p, i) => <Tile key={p.patient_id} p={p} index={ri * 3 + i} />)}
            {Array.from({ length: 3 - r.length }, (_, k) => <div key={k} className="grow basis-0" />)}
          </div>
        ))}
      </div>
    </div>
  )
}
