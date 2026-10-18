import { useEffect, useState } from 'react'
import * as api from '../api'
import { show } from '../lib'
import { useStore } from '../store'
import type { Wearable } from '../types'

const Ok = ({ ok }: { ok: boolean }) => (
  <svg width="16" height="16" viewBox="0 0 14 14" style={{ flexShrink: 0 }}>
    {ok ? <><circle cx="7" cy="7" r="6.5" fill="#2B7A57" /><path d="M3.5 7.2 L6 9.6 L10.5 4.6" fill="none" stroke="#FFFFFF" strokeWidth="1.6" /></>
      : <circle cx="7" cy="7" r="5.5" fill="none" stroke="#56616B" strokeWidth="1.6" strokeDasharray="3 2" />}
  </svg>
)

/** Live checks for the selected strap, read from the I13 of the patient the strap already feeds (if any). */
export default function StrapCheck({ wearableId }: { wearableId: number | null }) {
  const s = useStore()
  const [w, setW] = useState<Wearable | null>(null)
  useEffect(() => {
    if (wearableId == null) { setW(null); return }
    let alive = true
    const f = () => api.getWearables().then((l) => alive && setW(l.find((x) => x.wearable_id === wearableId) ?? null)).catch(() => {})
    f(); const h = setInterval(f, 3000)
    return () => { alive = false; clearInterval(h) }
  }, [wearableId])
  if (wearableId == null) return null
  const i13 = w?.patient_id ? s.i13[w.patient_id] : undefined
  const contact = (i13?.clean_seconds ?? (i13?.hr != null ? 1 : 0)) > 0
  return (
    <div className="flex flex-col p-4 rounded-[8px] gap-3 bg-fog">
      <div className="text-[15px] leading-5 font-[600] text-ink">Checking strap {wearableId}</div>
      <Row ok={!!i13} text="Bluetooth connected" />
      <Row ok={contact} text="Skin contact is good" />
      <Row ok={i13?.hr != null} text="Heart rate" value={i13?.hr != null ? `${show(i13.hr)} bpm` : ''} />
      <Row ok={i13?.resp_rate != null} text="Breathing rate" value={i13?.resp_rate != null ? `${show(i13.resp_rate)} /min` : ''} />
    </div>
  )
}
const Row = ({ ok, text, value }: { ok: boolean; text: string; value?: string }) => (
  <div className="flex items-center gap-2.5"><Ok ok={ok} /><div className="text-[14px] leading-5 grow basis-0 text-ink">{text}</div><div className="font-mono text-[15px] leading-5 font-[600] text-ink">{value}</div></div>
)
