import { go, fmtClock, fmtStale, Glyph, levelBorder, levelFromPoints, SEV, show, useApp, useStale, VITALS, waitingMin } from '../lib'
import { alertText, rankedAlerts, tileSeverity, useStore } from '../store'
import type { PatientRow } from '../types'

export default function Tile({ p, index }: { p: PatientRow; index: number }) {
  const { mode, now } = useApp()
  const s = useStore()
  const stale = useStale(p.patient_id)
  const i13 = s.i13[p.patient_id], i9 = s.i9[p.patient_id], i14 = s.i14[p.patient_id]
  const news2 = mode === 'live' ? 0 : i14?.news2 ?? i9?.news2
  const sev = tileSeverity(s, p.patient_id, news2)
  const c = SEV[sev]
  const pts = i14?.news2_points ?? i9?.news2_points
  const top = rankedAlerts(s, p.patient_id)[0]
  const wait = waitingMin(p.arrival_ts, now)
  const note = (top && alertText(top)) || (i9?.level && i9.level !== 'safe' ? i9.reason : null)
  return (
    <button onClick={() => go(`/patient/${p.patient_id}`)} className={`text-left flex flex-col grow basis-0 min-w-0 py-4 px-4.5 rounded-[8px] gap-2.5 ${c.card}`}>
      <div className="flex items-center justify-between h-4.5 shrink-0">
        <div className="font-mono text-small text-muted">{index + 1} · in {fmtClock(p.arrival_ts)}</div>
        <div className="flex items-center gap-1.5">
          <Glyph sev={sev} />
          <div className={`text-small font-[600] ${c.text}`}>{c.word}</div>
        </div>
      </div>
      <div className="flex flex-col gap-0.5">
        <div className="text-heading font-[600] text-ink">{p.name ?? p.patient_id}</div>
        <div className="text-small text-muted">{[p.bed, wait != null ? `waiting ${wait} min` : null].filter(Boolean).join(' · ')}</div>
      </div>
      <div className={`flex flex-col gap-2.5 ${stale != null ? 'opacity-50' : ''}`}>
        <div className="flex items-baseline gap-2 h-11">
          <div className={`font-mono text-hero font-[600] ${c.num}`}>{show(news2)}</div>
          <div className="text-micro text-muted">NEWS2</div>
        </div>
        <div className="flex gap-1.5">
          {VITALS.map((v) => {
            const val = i13?.[v.key] ?? i9?.vital_values?.[v.key]
            return (
              <div key={v.key} className={`grow basis-0 min-w-0 flex flex-col py-1.25 px-2 rounded-[4px] gap-px bg-ground border border-line border-l-3 ${levelBorder(levelFromPoints(pts?.[v.key], i9?.vital_levels?.[v.key]))}`}>
                <div className="h-4 text-micro text-muted">{v.short}</div>
                <div className="font-mono text-[16px] leading-5 text-ink h-5">{show(val)}</div>
              </div>
            )
          })}
        </div>
      </div>
      {stale != null
        ? <div className="text-body min-h-10 font-[600] text-urgent">{fmtStale(stale)}</div>
        : <div className="text-body min-h-10 text-muted">{note ?? ''}</div>}
    </button>
  )
}
