import { alertText, isMinor } from '../store'
import type { I10 } from '../types'

const KIND: Record<string, string> = { trend: 'Predicted', news2_total: 'NEWS2 score', vital_danger: 'Vital in danger' }
const SEVERITY: Record<string, { word: string; text: string; bar: string }> = {
  high: { word: 'High', text: 'text-high', bar: 'border-l-high' },
  urgent: { word: 'Medium', text: 'text-urgent', bar: 'border-l-urgent-solid' },
  warning: { word: 'Medium', text: 'text-urgent', bar: 'border-l-urgent-solid' },
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const POINTS = /,\s*(\d+) points?$/

/** Splits the engine's alert text into a headline and a detail line, e.g. "NEWS2 8 (SpO2, breathing)". */
function parts(a: I10) {
  const t = alertText(a)
  const m = t.match(/^(.*?)\s*\((.*)\)$/)
  if (m) return { head: cap(m[1]), detail: a.trigger === 'news2_total' ? `Driven by ${m[2]}` : cap(m[2]) }
  const pts = t.match(POINTS)
  return { head: cap(t.replace(POINTS, '')), detail: pts ? `${pts[1]} NEWS2 point${pts[1] === '1' ? '' : 's'}` : null }
}

/** Open alerts, most important first. "Outside usual" alerts are left out: the coloured vital tags already show them. */
export default function WhyUrgent({ alerts }: { alerts: I10[] }) {
  const main = alerts.filter((a) => !isMinor(a))
  return (
    <div className="flex flex-col gap-3">
      <div className="text-small font-[600] text-muted">Why urgent</div>
      {main.length === 0 && <div className="text-body text-muted">Nothing urgent right now.</div>}
      {main.map((a) => {
        const sev = SEVERITY[a.severity ?? ''] ?? SEVERITY.warning
        const { head, detail } = parts(a)
        return (
          <div key={a.alert_id} className={`flex flex-col gap-1 pl-3 border-l-3 ${sev.bar}`}>
            <div className="flex items-center justify-between text-micro">
              <div className="text-muted">{KIND[a.trigger ?? ''] ?? 'ALERT'}</div>
              <div className={`font-[600] ${sev.text}`}>{sev.word}</div>
            </div>
            <div className="text-heading font-[600] text-ink">{head}</div>
            {detail && <div className="text-body text-muted">{detail}</div>}
          </div>
        )
      })}
    </div>
  )
}
