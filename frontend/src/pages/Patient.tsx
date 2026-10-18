import { useEffect, useState } from 'react'
import * as api from '../api'
import { Glyph, SEV, VITALS, fmtClock, go, levelBorder, show, useApp, waitingMin } from '../lib'
import { openAlerts, tileSeverity, useStore } from '../store'
import type { I10, I9, IntakeCard, VitalKey } from '../types'
import VitalChart from '../components/VitalChart'
import SensorModal from '../components/SensorModal'

const KIND: Record<string, string> = { trend: 'TREND', news2_total: 'NEWS2', vital_danger: 'VITAL IN DANGER', warning_persisted: 'VITAL OUTSIDE USUAL' }
const POINTS: Record<VitalKey, 'hr' | 'resp_rate' | 'spo2' | 'temp_c'> = { hr: 'hr', resp_rate: 'resp_rate', spo2: 'spo2', temp_c: 'temp_c' }
const cap = (s?: string | null) => (s ? s[0].toUpperCase() + s.slice(1).replace('_', ' ') : '')

export default function Patient({ id }: { id: string }) {
  const { mode, now, allPatients, patients } = useApp()
  const s = useStore()
  const [vital, setVital] = useState<VitalKey>('resp_rate')
  const [rows, setRows] = useState<I9[]>([])
  const [card, setCard] = useState<IntakeCard | null>(null)
  const [modal, setModal] = useState(false)

  const p = allPatients.find((x) => x.patient_id === id)
  const i9 = s.i9[id], i13 = s.i13[id], i14 = s.i14[id], i8 = s.i8[id] ?? card?.ranges ?? undefined
  const tsKey = i9?.ts
  useEffect(() => { api.getHistory(id).then(setRows).catch(() => {}) }, [id, tsKey])
  useEffect(() => { api.getCard(id).then(setCard).catch(() => setCard(null)) }, [id, modal])

  const alerts = openAlerts(s, id).sort((a, b) => (b.severity === 'high' ? 1 : 0) - (a.severity === 'high' ? 1 : 0))
  const sev = tileSeverity(s, id)
  const c = SEV[sev]
  const news2 = mode === 'live' ? 0 : i14?.news2 ?? i9?.news2
  const pts = mode === 'live' ? null : i14?.news2_points ?? i9?.news2_points
  const ctx = card?.context
  const idx = patients.findIndex((x) => x.patient_id === id)
  const wait = waitingMin(p?.arrival_ts, now)
  const sub = [ctx?.age != null ? `${ctx.age} ${ctx.sex === 'female' ? 'F' : ctx.sex === 'male' ? 'M' : ''}`.trim() : null,
    ctx?.height_cm != null || ctx?.weight_kg != null ? `${show(ctx?.height_cm)} cm, ${show(ctx?.weight_kg)} kg` : null,
    ctx?.triage?.level != null ? `triage level ${ctx.triage.level}` : null].filter(Boolean).join(' · ')

  const why = (a: I10) => (a.trigger === 'trend' ? i9?.trend_reason_fast : i9?.reason)
  const danger = (['resp_rate', 'spo2', 'hr', 'temp_c'] as const).map((k) => {
    const r = i8?.[k]; if (!r) return null
    const parts = [r.danger_low != null ? `${r.danger_low} or less` : null, r.danger_high != null ? `${r.danger_high} or more` : null].filter(Boolean)
    return parts.length ? { k, text: parts.join(' · ') } : null
  }).filter(Boolean) as { k: VitalKey; text: string }[]

  const t = ctx?.triage
  return (
    <div className="flex flex-col min-h-screen">
      <div className="flex items-center h-19 shrink-0 px-10 gap-5 bg-fog border-b border-line">
        <button onClick={() => go('/')} className="flex items-center w-35 shrink-0 gap-2 bg-transparent border-0 p-0 text-[15px] leading-5 font-[500] text-navy">
          <svg width="16" height="16" viewBox="0 0 16 16"><path d="M10 3 L5 8 L10 13" fill="none" stroke="#1B365D" strokeWidth="2" /></svg>Board
        </button>
        <div className="flex grow basis-0 min-w-0 gap-2 overflow-hidden">
          {patients.map((q, i) => {
            const qs = tileSeverity(s, q.patient_id), qc = SEV[qs], cur = q.patient_id === id
            const n = mode === 'live' ? 0 : s.i14[q.patient_id]?.news2 ?? s.i9[q.patient_id]?.news2
            const border = cur ? 'border-2 border-navy' : qs === 'low' ? 'border border-line' : qs === 'amber' ? 'border-2 border-urgent-solid' : 'border-2 border-high'
            return (
              <button key={q.patient_id} onClick={() => go(`/patient/${q.patient_id}`)} className={`basis-42 min-w-42 w-42 h-13 shrink-0 flex items-center justify-between px-3 rounded-[6px] ${qs === 'low' ? 'bg-ground' : qc.card.split(' ')[0]} ${border}`}>
                <div className="flex flex-col text-left">
                  <div className="font-mono text-[11px] leading-3.5 text-muted">{i + 1}</div>
                  <div className="text-[13px] leading-4.5 font-[600] text-ink truncate max-w-24">{(q.name ?? q.patient_id).split(' ').slice(-1)[0]}</div>
                </div>
                <div className="flex items-center gap-1.5"><Glyph sev={qs} size={10} /><div className={`font-mono text-[18px] leading-5.5 font-[600] ${qc.num}`}>{show(n)}</div></div>
              </button>
            )
          })}
        </div>
        <div className="font-mono text-[14px] leading-5 text-muted">{fmtClock(now)}</div>
      </div>

      <div className="flex items-end justify-between shrink-0 pt-7 pb-5 px-10">
        <div className="flex flex-col gap-1.5">
          <div className="text-[13px] leading-4.5 tracking-[0.04em] text-muted">
            {[idx >= 0 ? `Arrival ${idx + 1} of ${patients.length}` : null, fmtClock(p?.arrival_ts), wait != null ? `waiting ${wait} min` : null].filter(Boolean).join(' · ')}
          </div>
          <div className="text-[36px] leading-10 tracking-[-0.015em] font-[600] text-ink">{p?.name ?? ctx?.name ?? id}</div>
          <div className="text-[15px] leading-5.5 text-muted">{sub}</div>
        </div>
        <div className="flex items-center gap-4">
          <div className={`text-[16px] leading-5 font-[600] ${c.text}`}>{c.word}</div>
          <div className={`flex items-center h-18 px-5 rounded-[6px] gap-3 ${c.box}`}>
            <Glyph sev={sev} size={20} />
            <div className={`font-mono text-[44px] leading-12 font-[600] ${c.num}`}>{show(news2)}</div>
            <div className="font-mono text-[13px] leading-4 text-muted">NEWS2</div>
          </div>
        </div>
      </div>

      <div className="flex grow basis-0 min-h-0 pb-8 gap-10 px-10">
        <div className="flex flex-col grow basis-0 min-w-0 gap-5">
          <div className="flex shrink-0 items-start gap-6">
            <div className="flex flex-col shrink-0 gap-2">
              <div className="font-mono text-[11px] leading-3.5 tracking-[0.08em] text-muted">LIVE · SELECT ONE TO CHART</div>
              <div className="flex gap-3">
                {VITALS.map((v) => {
                  const val = i13?.[v.key] ?? i9?.vital_values?.[v.key]
                  const lv = i9?.vital_levels?.[v.key]
                  const sel = vital === v.key
                  const pt = pts?.[POINTS[v.key]]
                  return (
                    <button key={v.key} onClick={() => setVital(v.key)} className={`text-left flex flex-col w-37.5 shrink-0 py-2.5 px-3 rounded-[6px] gap-1 border-l-4 ${levelBorder(lv)} ${sel ? 'bg-fog' : 'bg-ground'}`}>
                      <div className={`font-mono text-[12px] leading-4 tracking-[0.06em] ${sel ? 'font-[600] text-navy' : 'text-muted'}`}>{v.label}</div>
                      <div className="flex items-baseline gap-1.25 h-8.5">
                        <div className={`font-mono text-[30px] leading-8.5 font-[600] ${lv === 'danger' ? 'text-high' : lv === 'warning' ? 'text-urgent' : 'text-ink'}`}>{show(val)}</div>
                        {val != null && <div className="text-[12px] leading-4 text-muted">{v.unit}</div>}
                      </div>
                      <div className="font-mono text-[11px] leading-3.5 text-muted h-3.5">{pt != null ? `${pt} pt${pt === 1 ? '' : 's'}` : ''}</div>
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex flex-col grow basis-0 min-w-0 gap-2">
              <div className="font-mono text-[11px] leading-3.5 tracking-[0.08em] text-muted">AT TRIAGE · NO CHART</div>
              <div className="flex gap-2">
                {[
                  ['BP', t?.sbp != null ? `${t.sbp}${t.dbp != null ? '/' + t.dbp : ''}` : '', pts?.sbp],
                  ['ALERTNESS', cap(t?.alertness), pts?.alertness],
                  ['ON O2', t?.on_oxygen == null ? '' : t.on_oxygen ? 'Yes' : 'No', pts?.on_oxygen],
                ].map(([l, v, pt]) => (
                  <div key={l as string} className="flex flex-col grow basis-0 min-w-0 py-2.75 px-2.5 rounded-[6px] gap-1 bg-fog border-l-4 border-l-low">
                    <div className="font-mono text-[12px] leading-4 tracking-[0.06em] text-muted">{l}</div>
                    <div className="font-mono text-[18px] leading-8.5 font-[600] text-ink h-8.5">{v}</div>
                    <div className="font-mono text-[11px] leading-3.5 text-muted h-3.5">{pt != null ? `${pt} pts` : ''}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-end justify-between shrink-0 pt-2">
            <div className="flex flex-col gap-0.5">
              <div className="text-[20px] leading-6.5 font-[600] text-ink">{VITALS.find((v) => v.key === vital)!.title}</div>
              <div className="text-[14px] leading-5 text-muted">Since check-in</div>
            </div>
            <div className="flex items-center gap-4.5 text-[13px] leading-4.5 text-muted">
              <Legend cls="bg-high-tint border-high" t="Danger" /><Legend cls="bg-urgent-tint border-urgent-solid" t="Warning" /><Legend cls="bg-low-tint border-low" t="Safe for this patient" />
            </div>
          </div>
          <VitalChart rows={rows} vital={vital} range={i8?.[vital]} />
        </div>

        <div className="flex flex-col w-85 shrink-0 pl-8 gap-6 border-l border-line">
          <div className="flex flex-col gap-2">
            <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">WHY URGENT</div>
            {alerts.length === 0 && <div className="text-[15px] leading-5.75 text-muted">No open alerts.</div>}
            {alerts.map((a) => (
              <div key={a.alert_id} className="flex flex-col gap-1 pb-2">
                <div className="font-mono text-[11px] leading-3.5 tracking-[0.08em] text-muted">{KIND[a.trigger ?? ''] ?? 'ALERT'}</div>
                <div className="text-[15px] leading-5.75 font-[600] text-ink">{a.message}</div>
                {why(a) && <div className="text-[14px] leading-5 text-muted">{why(a)}</div>}
              </div>
            ))}
          </div>
          <div className="flex flex-col pt-5 gap-2.5 border-t border-line">
            <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">PATIENT INFORMATION</div>
            {ctx?.chief_complaint && <div className="pl-3 border-l-2 border-navy text-[15px] leading-5.5 text-ink">“{ctx.chief_complaint}”</div>}
            <div className="flex flex-col gap-1.5">
              <Info k="Age, sex" v={[ctx?.age, ctx?.sex].filter((x) => x != null).join(', ')} />
              <Info k="Height, weight" v={ctx?.height_cm != null ? `${ctx.height_cm} cm, ${ctx.weight_kg ?? ''} kg` : ''} />
              <Info k="History" v={(ctx?.conditions ?? []).map((x) => cap(x)).join(', ')} />
              <Info k="Medications" v={(ctx?.medications ?? []).join(', ')} />
              <Info k="Triage" v={t ? [t.level != null ? `Level ${t.level}` : null, t.pain != null ? `pain ${t.pain} of 10` : null].filter(Boolean).join(', ') : ''} />
              <div className="flex gap-3">
                <div className="w-23 shrink-0 text-[13px] leading-5 text-muted">Sensor</div>
                <div className="grow basis-0 min-w-0 text-[14px] leading-5 text-ink">{p?.bed ?? (ctx?.wearable_id != null ? `Strap ${ctx.wearable_id}` : '')}</div>
                <button onClick={() => setModal(true)} className="flex items-center shrink-0 gap-1.5 bg-transparent border-0 p-0 text-[13px] leading-5 font-[500] text-navy">
                  <svg width="14" height="14" viewBox="0 0 14 14"><path d="M1 7 H4 L5.5 3.5 L8 10.5 L9.5 7 H13" fill="none" stroke="#1B365D" strokeWidth="1.6" /></svg>Change
                </button>
              </div>
            </div>
          </div>
          {danger.length > 0 && (
            <div className="flex flex-col pt-5 gap-2 border-t border-line">
              <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">DANGER LIMITS</div>
              {danger.map((d) => (
                <div key={d.k} className="flex justify-between">
                  <div className="text-[14px] leading-5 text-ink">{VITALS.find((v) => v.key === d.k)!.title}</div>
                  <div className="font-mono text-[14px] leading-5 font-[500] text-ink">{d.text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {modal && <SensorModal patientId={id} onClose={() => setModal(false)} />}
    </div>
  )
}
const Legend = ({ cls, t }: { cls: string; t: string }) => <div className="flex items-center gap-1.5"><div className={`rounded-[2px] shrink-0 border size-3.5 ${cls}`} />{t}</div>
const Info = ({ k, v }: { k: string; v: string }) => (
  <div className="flex gap-3"><div className="w-23 shrink-0 text-[13px] leading-5 text-muted">{k}</div><div className="grow basis-0 min-w-0 text-[14px] leading-5 text-ink">{v}</div></div>
)
