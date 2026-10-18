import { useCallback, useEffect, useState } from 'react'
import * as api from '../api'
import { useApp } from '../lib'
import type { Wearable } from '../types'

/** Strap list shared by check-in and the sensor modal. Simulated straps are hidden in Live mode.
 *  currentPatientId: a strap already on this patient stays selectable (modal). */
export default function StrapPicker({ value, onChange, currentPatientId }: { value: number | null; onChange: (id: number) => void; currentPatientId?: string }) {
  const { mode, allPatients } = useApp()
  const [list, setList] = useState<Wearable[] | null>(null)
  const [err, setErr] = useState(false)
  const load = useCallback(() => { setErr(false); api.getWearables().then(setList).catch(() => setErr(true)) }, [])
  useEffect(load, [load])
  const nameOf = (pid: string) => allPatients.find((p) => p.patient_id === pid)?.name ?? pid
  const shown = (list ?? []).filter((w) => (mode === 'live' ? !w.simulated : !!w.simulated))
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="text-[13px] leading-4.5 font-[500] text-ink">Straps found nearby</div>
        <button onClick={load} className="flex items-center gap-1.5 bg-transparent border-0 p-0 text-[13px] leading-4.5 font-[500] text-navy">
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M12 7 A5 5 0 1 1 9.5 2.7 M12 2 V5 H9" fill="none" stroke="#1B365D" strokeWidth="1.6" /></svg>
          Scan again
        </button>
      </div>
      {err && <div className="text-[13px] text-high">Could not load straps.</div>}
      {list && shown.length === 0 && <div className="text-[13px] text-muted">No straps available.</div>}
      {shown.map((w) => {
        const own = !!currentPatientId && w.patient_id === currentPatientId
        const taken = !!w.patient_id && !own
        const sel = value === w.wearable_id
        return (
          <button key={w.wearable_id} disabled={taken} onClick={() => onChange(w.wearable_id)}
            className={`text-left flex items-center rounded-[6px] gap-3 ${taken ? 'bg-fog py-3.25 px-3.75' : sel ? 'bg-ground border-2 border-navy py-3 px-3.5' : 'bg-ground border border-edge py-3.25 px-3.75'}`}>
            <svg width="18" height="18" viewBox="0 0 18 18" style={{ flexShrink: 0 }}>
              <circle cx="9" cy="9" r="8" fill="none" stroke={taken ? '#C5CDD3' : sel ? '#1B365D' : '#8C98A1'} strokeWidth="2" />
              {sel && <circle cx="9" cy="9" r="4" fill="#1B365D" />}
            </svg>
            <div className="flex flex-col grow basis-0 min-w-0 gap-px">
              <div className={`text-[15px] leading-5 font-[600] ${taken ? 'text-muted' : 'text-ink'}`}>{w.label}</div>
              <div className="font-mono text-[12px] leading-4 text-muted">#{w.wearable_id}</div>
            </div>
            <div className={`text-[13px] leading-4.5 ${own ? 'font-[600] text-low' : 'text-muted'}`}>{own ? 'Linked' : taken ? `On ${nameOf(w.patient_id!)}` : 'Available'}</div>
          </button>
        )
      })}
    </div>
  )
}
