import { useEffect, useState } from 'react'
import * as api from '../api'
import { Glyph, SEV, VITALS, fmtClock, fmtStale, go, levelBorder, levelFromPoints, show, useApp, useStale, waitingMin } from '../lib'
import Adjustments from '../components/Adjustments'
import RangeBars from '../components/RangeBars'
import WhyUrgent from '../components/WhyUrgent'
import { rankedAlerts, tileSeverity, useStore } from '../store'
import type { I9, IntakeCard, VitalKey, VitalRange } from '../types'
import ConditionLimits from '../components/ConditionLimits'
import VitalChart from '../components/VitalChart'
import SensorModal from '../components/SensorModal'

const POINTS: Record<VitalKey, 'hr' | 'resp_rate' | 'spo2' | 'temp_c'> = { hr: 'hr', resp_rate: 'resp_rate', spo2: 'spo2', temp_c: 'temp_c' }
const cap = (s?: string | null) => (s ? s[0].toUpperCase() + s.slice(1).replace('_', ' ') : '')
const dangerText = (r?: VitalRange | null) =>
  r ? [r.danger_low != null ? `≤${r.danger_low}` : null, r.danger_high != null ? `≥${r.danger_high}` : null].filter(Boolean).join(' · ') : ''

export default function Patient({ id }: { id: string }) {
  const { mode, now, allPatients, patients } = useApp()
  const s = useStore()
  const [vital, setVital] = useState<VitalKey>('resp_rate')
  const [rows, setRows] = useState<I9[]>([])
  const [card, setCard] = useState<IntakeCard | null>(null)
  const [modal, setModal] = useState(false)
  const stale = useStale(id)

  const p = allPatients.find((x) => x.patient_id === id)
  const i9 = s.i9[id], i13 = s.i13[id], i14 = s.i14[id], i8 = s.i8[id] ?? card?.ranges ?? undefined
  const tsKey = i9?.ts
  useEffect(() => { api.getHistory(id).then(setRows).catch(() => {}) }, [id, tsKey])
  useEffect(() => {
    let t: number | undefined
    const load = () => api.getCard(id).then((c) => { setCard(c); if (c.adjuster === 'pending' || c.conditions?.state === 'pending') t = window.setTimeout(load, 3000) }).catch(() => setCard(null))
    load()
    return () => window.clearTimeout(t)
  }, [id, modal])

  const alerts = rankedAlerts(s, id)
  const news2 = mode === 'live' ? 0 : i14?.news2 ?? i9?.news2
  const sev = tileSeverity(s, id, news2)
  const c = SEV[sev]
  const pts = mode === 'live' ? null : i14?.news2_points ?? i9?.news2_points
  const ctx = card?.context
  const idx = patients.findIndex((x) => x.patient_id === id)
  const wait = waitingMin(p?.arrival_ts, now)
  const sub = [ctx?.age != null ? `${ctx.age} ${ctx.sex === 'female' ? 'F' : ctx.sex === 'male' ? 'M' : ''}`.trim() : null,
    ctx?.height_cm != null || ctx?.weight_kg != null ? `${show(ctx?.height_cm)} cm, ${show(ctx?.weight_kg)} kg` : null,
    ctx?.triage?.level != null ? `triage level ${ctx.triage.level}` : null].filter(Boolean).join(' · ')

  const t = ctx?.triage
  return (
    <div className="flex flex-col min-h-screen">
      <div className="flex items-center h-19 shrink-0 px-10 gap-5 bg-fog border-b border-line">
        <button onClick={() => go('/')} className="flex items-center w-35 shrink-0 gap-2 bg-transparent border-0 p-0 text-[15px] leading-5 font-[500] text-navy">
          <svg width="16" height="16" viewBox="0 0 16 16"><path d="M10 3 L5 8 L10 13" fill="none" stroke="#1B365D" strokeWidth="2" /></svg>Board
        </button>
        <div className="flex grow basis-0 min-w-0 gap-2 overflow-hidden">
          {patients.map((q, i) => {
            const n = mode === 'live' ? 0 : s.i14[q.patient_id]?.news2 ?? s.i9[q.patient_id]?.news2
            const qs = tileSeverity(s, q.patient_id, n), qc = SEV[qs], cur = q.patient_id === id
            const border = cur ? 'border-2 border-navy' : qs === 'low' ? 'border border-line' : qs === 'amber' ? 'border-2 border-urgent-solid' : 'border-2 border-high'
            return (
              <button key={q.patient_id} onClick={() => go(`/patient/${q.patient_id}`)} className={`basis-42 min-w-42 w-42 h-13 shrink-0 flex items-center justify-between px-3 rounded-[6px] ${qc.card.split(' ')[0]} ${border}`}>
                <div className="flex flex-col text-left">
                  <div className="font-mono text-micro text-muted">{i + 1}</div>
                  <div className="text-small font-[600] text-ink truncate max-w-24">{(q.name ?? q.patient_id).split(' ').slice(-1)[0]}</div>
                </div>
                <div className="flex items-center gap-1.5"><Glyph sev={qs} size={10} /><div className={`font-mono text-heading font-[600] ${qc.num}`}>{show(n)}</div></div>
              </button>
            )
          })}
        </div>
        <div className="font-mono text-[14px] leading-5 text-muted">{fmtClock(now)}</div>
      </div>

      <div className="flex items-end justify-between shrink-0 pt-7 pb-5 px-10">
        <div className="flex flex-col gap-1.5">
          <div className="text-small text-muted">
            {[idx >= 0 ? `Arrival ${idx + 1} of ${patients.length}` : null, fmtClock(p?.arrival_ts), wait != null ? `waiting ${wait} min` : null].filter(Boolean).join(' · ')}
          </div>
          <div className="text-title font-[600] text-ink">{p?.name ?? ctx?.name ?? id}</div>
          <div className="text-body text-muted">{sub}</div>
          {stale != null && <div className="text-body font-[600] text-urgent">{fmtStale(stale)}</div>}
        </div>
        <div className="flex items-center gap-4">
          <div className={`text-body font-[600] ${c.text}`}>{c.word}</div>
          <div className={`flex items-center h-18 px-5 rounded-[6px] gap-3 ${c.box}`}>
            <Glyph sev={sev} size={20} />
            <div className={`font-mono text-hero font-[600] ${c.num}`}>{show(news2)}</div>
            <div className="text-small text-muted">NEWS2</div>
          </div>
        </div>
      </div>

      <div className="flex grow basis-0 min-h-0 pb-8 gap-10 px-10">
        <div className="flex flex-col grow basis-0 min-w-0 gap-5">
          <div className="flex shrink-0 items-start gap-6">
            <div className={`flex flex-col shrink-0 gap-2 ${stale != null ? 'opacity-50' : ''}`}>
              <div className="text-small font-[600] text-muted">Live vitals · pick one to chart</div>
              <div className="flex gap-3">
                {VITALS.map((v) => {
                  const val = i13?.[v.key] ?? i9?.vital_values?.[v.key]
                  const sel = vital === v.key
                  const pt = pts?.[POINTS[v.key]]
                  const lv = levelFromPoints(pt, i9?.vital_levels?.[v.key])
                  return (
                    <button key={v.key} onClick={() => setVital(v.key)} aria-pressed={sel} className={`text-left flex flex-col w-37.5 shrink-0 py-2.5 px-3 rounded-[6px] gap-1 border-l-4 ${levelBorder(lv)} ${sel ? 'bg-fog' : 'bg-ground'}`}>
                      <div className={`text-small ${sel ? 'font-[600] text-navy' : 'text-muted'}`}>{v.label}</div>
                      <div className="flex items-baseline gap-1.25 h-8">
                        <div className={`font-mono text-value font-[600] ${lv === 'danger' ? 'text-high' : lv === 'warning' ? 'text-urgent' : 'text-ink'}`}>{show(val)}</div>
                        {val != null && <div className="text-micro text-muted">{v.unit}</div>}
                      </div>
                      <div className="font-mono text-micro text-muted h-4">{pt != null ? `${pt} pt${pt === 1 ? '' : 's'}` : ''}</div>
                      <div className="text-micro text-muted h-4 whitespace-nowrap">{dangerText(i8?.[v.key]) && `Danger ${dangerText(i8?.[v.key])}`}</div>
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex flex-col grow basis-0 min-w-0 gap-2">
              <div className="text-small font-[600] text-muted">Taken at triage</div>
              <div className="flex gap-2">
                {[
                  ['Blood pressure', t?.sbp != null ? `${t.sbp}${t.dbp != null ? '/' + t.dbp : ''}` : '', pts?.sbp],
                  ['Alertness', cap(t?.alertness), pts?.alertness],
                  ['On oxygen', t?.on_oxygen == null ? '' : t.on_oxygen ? 'Yes' : 'No', pts?.on_oxygen],
                ].map(([l, v, pt]) => (
                  <div key={l as string} className={`flex flex-col grow basis-0 min-w-0 py-2.5 px-2.5 rounded-[6px] gap-1 bg-fog border-l-4 ${levelBorder(levelFromPoints(pt as number | null | undefined))}`}>
                    <div className="text-small text-muted">{l}</div>
                    <div className="font-mono text-heading font-[600] text-ink h-8 leading-8">{v}</div>
                    <div className="font-mono text-micro text-muted h-4">{pt != null ? `${pt} pts` : ''}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-end justify-between shrink-0 pt-2">
            <div className="flex flex-col gap-0.5">
              <div className="text-heading font-[600] text-ink">{VITALS.find((v) => v.key === vital)!.title}</div>
              <div className="text-body text-muted">Since check-in</div>
            </div>
            <div className="flex items-center gap-4.5 text-small text-muted">
              <Legend cls="bg-high-tint border-high" t="Danger" /><Legend cls="bg-urgent-tint border-urgent-solid" t="Warning" /><Legend cls="bg-low-tint border-low" t="Safe for this patient" />
            </div>
          </div>
          <VitalChart rows={rows} vital={vital} range={i8?.[vital]} />
        </div>

        <div className="flex flex-col w-85 shrink-0 pl-8 gap-6 border-l border-line">
          <WhyUrgent alerts={alerts} />
          {ctx?.chief_complaint && <div className="pl-3 border-l-2 border-navy text-body text-ink">“{ctx.chief_complaint}”</div>}
          <div className="flex flex-col pt-5 gap-3 border-t border-line">
            <div className="text-small font-[600] text-muted">Patient details</div>
            <div className="flex flex-col gap-1.5">
              <Info k="BMI" v={ctx?.bmi != null ? String(ctx.bmi) : ''} />
              <Info k="History" v={(ctx?.conditions ?? []).map((x) => cap(x)).join(', ')} />
              <Info k="Medications" v={(ctx?.medications ?? []).join(', ')} />
              <Info k="Pain" v={t?.pain != null ? `${t.pain} of 10` : ''} />
              <div className="flex gap-3">
                <div className="w-23 shrink-0 text-small text-muted">Sensor</div>
                <div className="grow basis-0 min-w-0 text-body text-ink">{p?.bed ?? (ctx?.wearable_id != null ? `Strap ${ctx.wearable_id}` : '')}</div>
                <button onClick={() => setModal(true)} className="flex items-center shrink-0 gap-1.5 bg-transparent border-0 p-0 text-small font-[500] text-navy">
                  <svg width="14" height="14" viewBox="0 0 14 14"><path d="M1 7 H4 L5.5 3.5 L8 10.5 L9.5 7 H13" fill="none" stroke="#1B365D" strokeWidth="1.6" /></svg>Change
                </button>
              </div>
            </div>
          </div>
          <Adjustments card={card} />
          <ConditionLimits card={card} />
          <RangeBars ranges={i8} values={{ hr: i13?.hr ?? i9?.vital_values?.hr, resp_rate: i13?.resp_rate ?? i9?.vital_values?.resp_rate, spo2: i13?.spo2 ?? i9?.vital_values?.spo2, temp_c: i13?.temp_c ?? i9?.vital_values?.temp_c }} />
        </div>
      </div>
      {modal && <SensorModal patientId={id} onClose={() => setModal(false)} />}
    </div>
  )
}
const Legend = ({ cls, t }: { cls: string; t: string }) => <div className="flex items-center gap-1.5"><div className={`rounded-[2px] shrink-0 border size-3.5 ${cls}`} />{t}</div>
const Info = ({ k, v }: { k: string; v: string }) => (
  <div className="flex gap-3"><div className="w-23 shrink-0 text-small text-muted">{k}</div><div className="grow basis-0 min-w-0 text-body text-ink">{v}</div></div>
)
