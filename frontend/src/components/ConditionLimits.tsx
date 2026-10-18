import type { ConditionItem, IntakeCard } from '../types'

type View = 'loading' | 'error' | 'applied' | 'none'

const VITALS = ['hr', 'resp_rate', 'spo2', 'temp_c'] as const

/** One line per typed condition saying what happened to it; never claims a limit changed unless one did. */
function line(i: ConditionItem, drafted: boolean, failed: boolean): string {
  const name = i.canonical ?? i.typed ?? 'Condition'
  switch (i.status) {
    case 'checklist': return `${i.typed}: counted as ${(i.checklist ?? '').replace('_', ' ')}. It changes the fitted ranges, with no separate limit.`
    case 'found': return drafted ? `${name}: limit applied (see below).` : failed ? `${name}: recognized, but the evidence lookup failed.` : `${name}: recognized. No limit change suggested.`
    case 'ambiguous': return `${i.typed}: matches several conditions (${(i.candidates ?? []).slice(0, 3).map((c) => c.canonical).join(', ')}). Nothing applied.`
    case 'not_found': return `${i.typed}: not found. Nothing applied.`
    case 'unavailable': return `${i.typed}: the lookup service did not answer.`
    default: return `${i.typed}: no result.`
  }
}

/** The result of the typed conditions: loading, error, applied, or no adjustment, kept visibly different. */
export default function ConditionLimits({ card }: { card: IntakeCard | null }) {
  const c = card?.conditions
  if (!c) return null
  const items = c.resolution?.items ?? []
  const drafted = (card?.i15_items ?? []).filter((e) => e.rule_id?.startsWith('draft:'))
  const draftCodes = new Set(drafted.map((e) => e.rule_id!.slice(6)))
  const reasons = VITALS.flatMap((v) => (card?.ranges?.[v]?.reasons ?? []).filter((r) => r.includes('draft (')))
  const errors = [...(c.infra_errors ?? []), ...(items.some((i) => i.status === 'unavailable') ? ['Condition lookup unavailable'] : [])]
  const view: View = c.state === 'pending' ? 'loading' : c.state === 'failed' || (errors.length > 0 && drafted.length === 0) ? 'error' : drafted.length > 0 ? 'applied' : 'none'

  return (
    <div className="flex flex-col pt-5 gap-2.5 border-t border-line">
      <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">TYPED CONDITIONS</div>
      {view === 'loading' && <div className="text-[14px] leading-5 text-muted">Checking the typed conditions… Standard limits apply until this finishes.</div>}
      {view === 'error' && (
        <div className="flex flex-col gap-1 p-3 rounded-[6px] bg-high-tint">
          <div className="text-[14px] leading-5 font-[600] text-high">Could not check the typed conditions</div>
          <div className="text-[14px] leading-5 text-ink">Standard limits apply.{c.state === 'failed' ? '' : ` ${errors.join('; ')}`}</div>
        </div>
      )}
      {view === 'none' && <div className="text-[14px] leading-5 text-ink">No adjustment. Standard limits apply.</div>}
      {view === 'applied' && <div className="text-[14px] leading-5 text-ink">Warning limits adjusted for this patient. Unreviewed.</div>}
      {c.state === 'done' && view !== 'error' && errors.length > 0 && (
        <div className="text-[13px] leading-4.5 text-high">Some could not be checked: {errors.join('; ')}</div>
      )}
      {c.state === 'done' && items.map((i, k) => (
        <div key={k} className="text-[14px] leading-5 text-muted">{line(i, !!i.code && draftCodes.has(i.code), view === 'error')}</div>
      ))}
      {view === 'applied' && reasons.map((r, k) => <div key={k} className="text-[14px] leading-5 text-ink">{r.replace(/ warning limit/, ' warning at')}</div>)}
      {view === 'applied' && drafted.map((e, k) => (
        <div key={k} className="flex flex-col gap-0.5">
          {(e.sources ?? []).map((s, j) => (
            <div key={j} className="pl-3 border-l-2 border-navy text-[13px] leading-4.5 text-muted">{s.title} ({s.year}), PMID {s.id}: “{s.passage}”</div>
          ))}
        </div>
      ))}
      {(c.suggestions ?? []).length > 0 && view !== 'loading' && (
        <div className="text-[13px] leading-4.5 text-muted">A suggested step would not change this patient's band, so it was skipped.</div>
      )}
    </div>
  )
}
