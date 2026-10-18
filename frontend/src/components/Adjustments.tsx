import type { IntakeCard } from '../types'

const RULE: Record<string, string> = {
  age65: 'Age 65 or older', chemo_fever: 'Chemotherapy and fever', suspected_infection: 'Suspected infection',
  opioid: 'Opioid use', steroid_immunosuppressed: 'Steroid or weakened immunity', beta_blocker: 'Beta-blocker', pregnancy: 'Pregnancy',
}
const VITAL: Record<string, { name: string; unit: string }> = {
  hr: { name: 'Heart rate', unit: ' bpm' }, resp_rate: { name: 'Breathing', unit: ' per min' }, spo2: { name: 'SpO2', unit: '%' },
  temp_c: { name: 'Temperature', unit: ' °C' }, sbp: { name: 'Blood pressure', unit: ' mmHg' },
}
const ruleName = (id?: string | null) => (id ? RULE[id] ?? id[0].toUpperCase() + id.slice(1).replace(/_/g, ' ') : 'Adjustment')

/** What the context adjuster changed for this patient: tightened danger limits, with the fact and quote that triggered each rule. */
export default function Adjustments({ card }: { card: IntakeCard | null }) {
  const adj = card?.i5?.adjustments ?? []
  const evidence = card?.i15_items ?? []
  const rules = [...new Set(adj.map((a) => a.rule_id ?? ''))]
  const note = card?.adjuster === 'pending' ? 'Reading the chief complaint…' : card?.adjuster === 'structured only' ? 'From age, sex and medications only.' : null
  return (
    <div className="flex flex-col pt-5 gap-2.5 border-t border-line">
      <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">CONTEXT ADJUSTMENTS</div>
      {card && rules.length === 0 && <div className="text-[14px] leading-5 text-muted">None. Standard limits apply.</div>}
      {rules.map((r) => (
        <div key={r} className="flex flex-col gap-1">
          <div className="text-[15px] leading-5.5 font-[600] text-ink">{ruleName(r)}</div>
          {adj.filter((a) => (a.rule_id ?? '') === r).map((a, i) => {
            const v = VITAL[a.vital ?? '']
            return <div key={i} className="text-[14px] leading-5 text-ink">{v?.name ?? a.vital} danger at {a.value}{v?.unit ?? ''} or {a.bound === 'low' ? 'less' : 'more'}</div>
          })}
          {evidence.filter((e) => e.rule_id === r).map((e, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              {e.fact && <div className="text-[14px] leading-5 text-muted">{e.fact}</div>}
              {e.quote && <div className="pl-3 border-l-2 border-navy text-[14px] leading-5 text-muted">“{e.quote}”</div>}
            </div>
          ))}
        </div>
      ))}
      {note && <div className="text-[13px] leading-4.5 text-muted">{note}</div>}
    </div>
  )
}
