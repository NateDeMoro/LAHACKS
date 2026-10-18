import { useState } from 'react'
import * as api from '../api'
import { fmtClock, go, useApp } from '../lib'
import type { IntakeRecord } from '../types'
import StrapPicker from '../components/StrapPicker'
import StrapCheck from '../components/StrapCheck'

const CONDITIONS = ['hypertension', 'asthma', 'cancer', 'diabetes', 'thyroid', 'copd', 'liver', 'heart_disease', 'stroke', 'heart_failure']
const label = (c: string) => (c === 'copd' ? 'COPD' : c[0].toUpperCase() + c.slice(1).replace('_', ' '))
const ALERT = [['alert', 'Alert'], ['new_confusion', 'New confusion'], ['voice', 'Voice'], ['pain', 'Pain'], ['unresponsive', 'Unresponsive']] as const

const input = 'h-11 flex items-center px-3 rounded-[6px] border border-edge text-[15px] leading-5 text-ink bg-ground w-full'
const H = ({ t }: { t: string }) => <div className="text-[15px] leading-5.5 font-[600] text-ink">{t}</div>
const F = ({ t, children, grow = 1 }: { t: string; children: React.ReactNode; grow?: number }) => (
  <div className="flex flex-col min-w-0 gap-1.5" style={{ flex: `${grow} 1 0` }}><div className="text-[13px] leading-4.5 font-[500] text-ink">{t}</div>{children}</div>
)
function Seg<T extends string | number>({ opts, value, onChange, mono }: { opts: readonly (readonly [T, string])[]; value: T | null; onChange: (v: T) => void; mono?: boolean }) {
  return (
    <div className="h-11 flex rounded-[6px] border border-edge">
      {opts.map(([v, l]) => (
        <button key={String(v)} type="button" onClick={() => onChange(v)} className={`grow basis-0 rounded-[5px] text-[14px] leading-5 ${mono ? 'font-mono' : ''} ${value === v ? 'bg-navy text-ground font-[500]' : 'bg-transparent text-ink'}`}>{l}</button>
      ))}
    </div>
  )
}
const num = (s: string) => (s.trim() === '' || Number.isNaN(Number(s)) ? undefined : Number(s))

export default function CheckIn() {
  const { mode, now, patients, refresh } = useApp()
  const [name, setName] = useState(''); const [age, setAge] = useState(''); const [sex, setSex] = useState<'male' | 'female' | null>(null)
  const [h, setH] = useState(''); const [w, setW] = useState(''); const [preg, setPreg] = useState<boolean | null>(null)
  const [conds, setConds] = useState<string[]>([]); const [meds, setMeds] = useState<string[]>([]); const [medIn, setMedIn] = useState('')
  const [cc, setCc] = useState(''); const [sbp, setSbp] = useState(''); const [dbp, setDbp] = useState('')
  const [esi, setEsi] = useState<number | null>(null); const [o2, setO2] = useState<boolean | null>(null)
  const [alertness, setAlertness] = useState<string | null>(null); const [pain, setPain] = useState<number | null>(null)
  const [strap, setStrap] = useState<number | null>(null)
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null)

  // Demo shortcut: the presenter's own intake (6 ft = 183 cm, 170 lb = 77.1 kg), on the live strap.
  const autofill = () => {
    setName('Nate DeMoro'); setAge('21'); setSex('male'); setH('183'); setW('77.1'); setPreg(null)
    setConds(['thyroid', 'stroke', 'heart_failure']); setMeds(['Methimazole 5 mg']); setMedIn('')
    setCc('Overly tired for the last week or two, achy, and my throat has been a bit sore.')
    setSbp('120'); setDbp('67'); setEsi(5); setO2(false); setAlertness('alert'); setPain(3); setStrap(1)
  }

  const addMed = () => { const m = medIn.trim(); if (m && !meds.includes(m)) setMeds([...meds, m]); setMedIn('') }
  const ready = strap != null && !!name.trim()

  const submit = async () => {
    setBusy(true); setErr(null)
    const rec: IntakeRecord = {
      name: name.trim(), wearable_id: strap!, age: num(age), sex: sex ?? undefined, height_cm: num(h), weight_kg: num(w),
      pregnant: sex === 'female' ? preg : null, conditions: conds, medications: meds, chief_complaint: cc.trim() || undefined,
      triage: { sbp: num(sbp), dbp: num(dbp), level: esi ?? undefined, on_oxygen: o2 ?? undefined, alertness: alertness ?? undefined, pain: pain ?? undefined },
    }
    try { await api.postIntake(rec); await refresh(); go('/') } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col min-h-screen">
      <div className="flex items-center justify-between h-13 shrink-0 px-10 bg-fog border-b border-line">
        <button onClick={() => go('/')} className="flex items-center gap-2 bg-transparent border-0 p-0 text-[15px] leading-5 font-[500] text-navy">
          <svg width="16" height="16" viewBox="0 0 16 16"><path d="M10 3 L5 8 L10 13" fill="none" stroke="#1B365D" strokeWidth="2" /></svg>Board
        </button>
        <div className="font-mono text-[14px] leading-5 text-muted">{fmtClock(now)}</div>
      </div>
      <div className="flex items-end justify-between pt-7 pb-5 px-10">
        <div className="flex flex-col gap-1.5">
          <div className="text-title font-[600] text-ink">Check in a patient</div>
          <div className="text-[15px] leading-5.5 text-muted">Arrival {patients.length + 1} · {fmtClock(now)} · patient ID assigned when you check in</div>
        </div>
        <button onClick={autofill} className="h-9 px-4 rounded-[6px] border border-edge bg-ground text-[14px] leading-5 font-[500] text-ink">Autofill my details</button>
      </div>
      <div className="flex pb-6 gap-10 px-10">
        <div className="flex flex-col grow basis-0 min-w-0 gap-7">
          <div className="flex flex-col gap-3.5">
            <H t="Patient" />
            <div className="flex gap-4">
              <F t="Name" grow={2}><input className={input} value={name} onChange={(e) => setName(e.target.value)} /></F>
              <F t="Age"><input className={`${input} font-mono`} inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value)} /></F>
              <F t="Sex" grow={2}><Seg opts={[['male', 'Male'], ['female', 'Female']] as const} value={sex} onChange={setSex} /></F>
            </div>
            <div className="flex gap-4">
              <F t="Height (cm)"><input className={`${input} font-mono`} inputMode="decimal" value={h} onChange={(e) => setH(e.target.value)} /></F>
              <F t="Weight (kg)"><input className={`${input} font-mono`} inputMode="decimal" value={w} onChange={(e) => setW(e.target.value)} /></F>
              <F t="Pregnant">{sex === 'female' ? <Seg opts={[['no', 'No'], ['yes', 'Yes']] as const} value={preg == null ? null : preg ? 'yes' : 'no'} onChange={(v) => setPreg(v === 'yes')} /> : <div className={`${input} bg-fog border-0 text-[14px] text-muted`}>Not applicable</div>}</F>            </div>
          </div>
          <div className="flex flex-col pt-6 gap-3.5 border-t border-line">
            <H t="Health history" />
            <div className="flex flex-col gap-2">
              <div className="text-[13px] leading-4.5 font-[500] text-ink">Conditions</div>
              <div className="flex flex-wrap gap-2">
                {CONDITIONS.map((c) => {
                  const on = conds.includes(c)
                  return <button key={c} type="button" onClick={() => setConds(on ? conds.filter((x) => x !== c) : [...conds, c])} className={`h-9 flex items-center px-3.5 rounded-[18px] gap-1.5 text-[14px] leading-5 border ${on ? 'bg-navy border-navy text-ground font-[500]' : 'bg-ground border-edge text-ink'}`}>{on && <svg width="12" height="12" viewBox="0 0 14 14"><path d="M2 7.5 L5.5 11 L12 3.5" fill="none" stroke="#FFFFFF" strokeWidth="2" /></svg>}{label(c)}</button>
                })}
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="text-[13px] leading-4.5 font-[500] text-ink">Medications</div>
              <div className="flex items-center flex-wrap min-h-13 py-2 px-3 rounded-[6px] gap-2 border border-edge">
                {meds.map((m) => (
                  <div key={m} className="flex items-center h-8 pr-2.5 pl-3 rounded-[4px] gap-2 bg-fog text-[14px] leading-5 text-ink">{m}
                    <button type="button" onClick={() => setMeds(meds.filter((x) => x !== m))} aria-label={`Remove ${m}`} className="bg-transparent border-0 p-0"><svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 2 L8 8 M8 2 L2 8" stroke="#56616B" strokeWidth="1.6" /></svg></button>
                  </div>
                ))}
                <input value={medIn} onChange={(e) => setMedIn(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addMed() } }} onBlur={addMed}
                  placeholder="Type a name and press Enter" className="grow basis-40 min-w-0 outline-none text-[14px] leading-5 text-ink bg-transparent" />
              </div>
            </div>
          </div>
          <div className="flex flex-col pt-6 gap-3.5 border-t border-line">
            <H t="Reason for visit" />
            <F t="Chief complaint, in the patient's words">
              <textarea value={cc} onChange={(e) => setCc(e.target.value)} className="min-h-19 p-3 rounded-[6px] border border-edge text-[15px] leading-5.5 text-ink" />
            </F>
          </div>
          <div className="flex flex-col pt-6 gap-4 border-t border-line">
            <H t="Taken at triage" />
            <div className="flex items-start gap-4">
              <F t="Blood pressure (mmHg)" grow={2}>
                <div className="flex items-center gap-2"><input className={`${input} font-mono`} inputMode="numeric" value={sbp} onChange={(e) => setSbp(e.target.value)} /><span className="font-mono text-[18px] text-muted">/</span><input className={`${input} font-mono`} inputMode="numeric" value={dbp} onChange={(e) => setDbp(e.target.value)} /></div>
              </F>
              <F t="Triage level (ESI)" grow={3}><Seg mono opts={[[1, '1'], [2, '2'], [3, '3'], [4, '4'], [5, '5']] as const} value={esi} onChange={setEsi} /></F>
              <F t="On supplemental oxygen" grow={2}><Seg opts={[['no', 'No'], ['yes', 'Yes']] as const} value={o2 == null ? null : o2 ? 'yes' : 'no'} onChange={(v) => setO2(v === 'yes')} /></F>
            </div>
            <F t="Alertness"><Seg opts={ALERT} value={alertness as any} onChange={setAlertness} /></F>
            <F t="Pain, 0 to 10"><Seg mono opts={Array.from({ length: 11 }, (_, i) => [i, String(i)] as const)} value={pain} onChange={setPain} /></F>
          </div>
        </div>
        <div className="flex flex-col w-100 shrink-0 pl-8 gap-4 border-l border-line">
          <div className="flex flex-col gap-2">
            <div className="text-[22px] leading-7 font-[600] text-ink">Link a strap to this patient</div>
            <div className="text-[14px] leading-5.25 text-muted">Wet the electrodes and fit the strap snug under the chest. Close the Polar app on your phone so it doesn't hold the connection.</div>
          </div>
          <StrapPicker value={strap} onChange={setStrap} />
          <StrapCheck wearableId={strap} />
          {mode === 'live' && <div className="text-[13px] leading-4.75 text-muted">The strap measures heart rate and breathing. Blood pressure comes from triage.</div>}
        </div>
      </div>
      <div className="flex items-center justify-between shrink-0 py-4 px-10 bg-fog border-t border-line mt-auto">
        <div className="text-[14px] leading-5 text-high">{err}</div>
        <div className="flex items-center gap-3">
          <button onClick={() => go('/')} className="h-12 flex items-center px-5 rounded-[6px] bg-ground border border-edge text-[15px] leading-5 font-[500] text-ink">Cancel</button>
          <button disabled={!ready || busy} onClick={submit} className="h-12 flex items-center px-7 rounded-[6px] bg-navy text-[15px] leading-5 font-[600] text-ground">Check in and start monitoring</button>
        </div>
      </div>
    </div>
  )
}
