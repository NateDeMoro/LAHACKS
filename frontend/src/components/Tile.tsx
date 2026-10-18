import { go, Glyph, levelBorder, SEV, VITALS, fmtClock, show, useApp, waitingMin } from '../lib'
import { openAlerts, tileSeverity, useStore } from '../store'
import type { PatientRow } from '../types'

export default function Tile({ p, index }: { p: PatientRow; index: number }) {
  const { mode, now } = useApp()
  const s = useStore()
  const sev = tileSeverity(s, p.patient_id)
  const c = SEV[sev]
  const i13 = s.i13[p.patient_id], i9 = s.i9[p.patient_id], i14 = s.i14[p.patient_id]
  const alerts = openAlerts(s, p.patient_id)
  const top = [...alerts].sort((a, b) => (b.severity === 'high' ? 1 : 0) - (a.severity === 'high' ? 1 : 0))[0]
  const news2 = mode === 'live' ? 0 : i14?.news2 ?? i9?.news2
  const wait = waitingMin(p.arrival_ts, now)
  const note = top?.message ?? (i9?.level && i9.level !== 'safe' ? i9.reason : null)
  return (
    <button onClick={() => go(`/patient/${p.patient_id}`)} className={`text-left flex flex-col grow basis-0 min-w-0 py-4 px-4.5 rounded-[8px] gap-2.5 ${c.card}`}>
      <div className="flex items-center justify-between h-4.5 shrink-0">
        <div className="font-mono text-[13px] leading-4.5 text-muted">{index + 1} · in {fmtClock(p.arrival_ts)}</div>
        <div className="flex items-center gap-1.5">
          <Glyph sev={sev} />
          <div className={`text-[13px] leading-4.5 font-[600] ${c.text}`}>{c.word}</div>
        </div>
      </div>
      <div className="flex flex-col gap-0.5">
        <div className="text-[20px] leading-6.5 font-[600] text-ink">{p.name ?? p.patient_id}</div>
        <div className="text-[13px] leading-4.5 text-muted">{[p.bed, wait != null ? `waiting ${wait} min` : null].filter(Boolean).join(' · ')}</div>
      </div>
      <div className="flex items-baseline gap-2 h-13">
        <div className={`font-mono text-[48px] leading-13 font-[600] ${c.num}`}>{show(news2)}</div>
        <div className="font-mono text-[12px] leading-4 text-muted">NEWS2</div>
      </div>
      <div className="flex gap-1.5">
        {VITALS.map((v) => {
          const val = i13?.[v.key] ?? i9?.vital_values?.[v.key]
          return (
            <div key={v.key} className={`grow basis-0 min-w-0 flex flex-col py-1.25 px-2 rounded-[4px] gap-px bg-ground border border-line border-l-3 ${levelBorder(i9?.vital_levels?.[v.key])}`}>
              <div className="h-3.5 font-mono text-[11px] leading-3.5 text-muted">{v.short}</div>
              <div className="font-mono text-[16px] leading-5 text-ink h-5">{show(val)}</div>
            </div>
          )
        })}
      </div>
      <div className="text-[14px] leading-5 min-h-10 text-muted">{note ?? ''}</div>
    </button>
  )
}
