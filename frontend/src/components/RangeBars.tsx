import { VITALS, show } from '../lib'
import type { I8 } from '../types'

// Visible span of each bar. Wide enough to hold the danger limits with room beyond them.
const AXIS = { hr: [30, 150], resp_rate: [4, 32], spo2: [80, 100], temp_c: [34, 41] } as const
const KEYS = ['hr', 'resp_rate', 'spo2', 'temp_c'] as const

/** One bar per vital for this patient: green safe band, amber warning bands, red danger zones, the limits labelled, and a tick at the current value. */
export default function RangeBars({ ranges, values }: { ranges?: I8 | null; values: Partial<Record<(typeof KEYS)[number], number | null | undefined>> }) {
  const rows = KEYS.map((k) => ({ k, r: ranges?.[k] })).filter((x) => x.r)
  if (!rows.length) return null
  return (
    <div className="flex flex-col pt-5 gap-4 border-t border-line">
      <div className="font-mono text-[12px] leading-4 tracking-[0.08em] text-muted">RANGES FOR THIS PATIENT</div>
      {rows.map(({ k, r }) => {
        const [lo, hi] = AXIS[k]
        const pos = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))
        const dl = r!.danger_low ?? null, sl = r!.safe_low ?? null, sh = r!.safe_high ?? null, dh = r!.danger_high ?? null
        // Zone edges from left to right; a missing limit means that side has no zone.
        const edges = [dl != null ? pos(dl) : 0, sl != null ? pos(sl) : dl != null ? pos(dl) : 0, sh != null ? pos(sh) : dh != null ? pos(dh) : 100, dh != null ? pos(dh) : 100]
        const zones = [
          { from: 0, to: edges[0], cls: 'bg-high' }, { from: edges[0], to: edges[1], cls: 'bg-urgent-solid' },
          { from: edges[1], to: edges[2], cls: 'bg-low' }, { from: edges[2], to: edges[3], cls: 'bg-urgent-solid' }, { from: edges[3], to: 100, cls: 'bg-high' },
        ].filter((z) => z.to > z.from)
        const cur = values[k]
        const labels = [{ v: dl, danger: true }, { v: sl, danger: false }, { v: sh, danger: false }, { v: dh, danger: true }].filter((l) => l.v != null) as { v: number; danger: boolean }[]
        return (
          <div key={k} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between">
              <div className="text-[14px] leading-5 text-ink">{VITALS.find((v) => v.key === k)!.title}</div>
              {cur != null && <div className="font-mono text-[13px] leading-4.5 text-muted">now {show(cur)}</div>}
            </div>
            <div className="relative h-2 rounded-full overflow-hidden bg-line">
              {zones.map((z, i) => <div key={i} className={`absolute top-0 bottom-0 ${z.cls}`} style={{ left: `${z.from}%`, width: `${z.to - z.from}%` }} />)}
            </div>
            {cur != null && <div className="relative h-0"><div className="absolute -top-4.5 w-0.5 h-3 bg-ink" style={{ left: `${pos(cur)}%` }} /></div>}
            <div className="relative h-4">
              {labels.map((l, i) => (
                <div key={i} className={`absolute font-mono text-[11px] leading-4 ${l.danger ? 'text-high' : 'text-ink'}`}
                  style={{ left: `${pos(l.v)}%`, transform: `translateX(${pos(l.v) > 94 ? '-100%' : pos(l.v) < 6 ? '0' : '-50%'})` }}>{show(l.v)}</div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
