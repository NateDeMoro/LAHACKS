import { useState } from 'react'
import * as api from '../api'
import { useApp } from '../lib'
import { useStore } from '../store'
import type { IntakeRecord } from '../types'
import StrapPicker from './StrapPicker'
import StrapCheck from './StrapCheck'

/** B2a: swap the strap on an existing patient by re-posting their intake record with a new wearable_id (ASSUMED to re-assign). */
export default function SensorModal({ patientId, onClose }: { patientId: string; onClose: () => void }) {
  const { refresh, allPatients } = useApp()
  const s = useStore()
  const [sel, setSel] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  void s
  const use = async () => {
    if (sel == null) return
    setBusy(true); setErr(null)
    try {
      const { context } = await api.getCard(patientId)
      const { bmi, drug_classes, unmatched_medications, ...rec } = context
      void bmi; void drug_classes; void unmatched_medications
      await api.postIntake({ ...(rec as IntakeRecord), patient_id: patientId, wearable_id: sel })
      await refresh(); onClose()
    } catch (e) { setErr(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  void allPatients
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-[#11171D73]" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="relative w-120 max-h-[90vh] overflow-y-auto flex flex-col pt-7 pb-6 px-8 rounded-[10px] gap-5 bg-ground shadow-[#11171D40_0px_12px_40px]">
        <button onClick={onClose} aria-label="Close" className="absolute top-5 right-5 size-8 flex items-center justify-center rounded-[6px] bg-transparent border-0">
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 2 L12 12 M12 2 L2 12" fill="none" stroke="#56616B" strokeWidth="1.6" /></svg>
        </button>
        <div className="flex flex-col gap-2">
          <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">HEART RATE SENSOR</div>
          <div className="text-[22px] leading-7 font-[600] text-ink">Link a strap to this patient</div>
          <div className="text-[14px] leading-5.25 text-muted">Wet the electrodes and fit the strap snug under the chest. Close the Polar app on your phone so it doesn't hold the connection.</div>
        </div>
        <StrapPicker value={sel} onChange={setSel} currentPatientId={patientId} />
        <StrapCheck wearableId={sel} />
        {err && <div className="text-[13px] text-high">{err}</div>}
        <div className="flex justify-end pt-1 gap-2.5">
          <button onClick={onClose} className="flex items-center h-11 px-5 rounded-[6px] bg-ground border border-edge text-[15px] leading-5 font-[500] text-ink">Cancel</button>
          <button disabled={sel == null || busy} onClick={use} className="flex items-center h-11 px-5 rounded-[6px] bg-navy text-[15px] leading-5 font-[600] text-ground">{sel == null ? 'Use strap' : `Use strap ${sel}`}</button>
        </div>
      </div>
    </div>
  )
}
