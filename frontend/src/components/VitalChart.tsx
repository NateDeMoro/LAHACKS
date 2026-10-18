import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmtClock } from '../lib'
import type { I9, VitalKey, VitalRange } from '../types'

export default function VitalChart({ rows, vital, range }: { rows: I9[]; vital: VitalKey; range?: VitalRange | null }) {
  const data = rows.map((r) => ({ t: Date.parse(r.ts ?? ''), v: r.vital_values?.[vital] ?? null })).filter((d) => !Number.isNaN(d.t))
  const vals = data.map((d) => d.v).filter((x): x is number => x != null)
  const edges = [range?.safe_low, range?.safe_high, range?.danger_low, range?.danger_high].filter((x): x is number => x != null)
  const all = [...vals, ...edges]
  if (all.length === 0) return <div className="h-86 flex items-center justify-center text-[14px] text-muted">No readings yet.</div>
  const span = Math.max(...all) - Math.min(...all) || 1
  const lo = Math.min(...all) - span * 0.15, hi = Math.max(...all) + span * 0.15
  const r = range ?? {}
  // Bands from the patient's I8: danger beyond danger edges, warning between danger and safe edges, safe inside.
  const dl = r.danger_low ?? null, sl = r.safe_low ?? null, sh = r.safe_high ?? null, dh = r.danger_high ?? null
  const bands: [number, number, string][] = []
  if (range) {
    const sLo = sl ?? dl ?? lo, sHi = sh ?? dh ?? hi
    if (dl != null) bands.push([lo, dl, '#FBE6E3'])
    if (dl != null && sl != null) bands.push([dl, sl, '#FDF0D3'])
    else if (sl != null) bands.push([lo, sl, '#FDF0D3'])
    bands.push([sLo, sHi, '#E3F1E9'])
    if (sh != null && dh != null) bands.push([sh, dh, '#FDF0D3'])
    else if (sh != null) bands.push([sh, hi, '#FDF0D3'])
    if (dh != null) bands.push([dh, hi, '#FBE6E3'])
  }
  return (
    <div className="h-86 w-full">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 10, right: 20, bottom: 4, left: 0 }}>
          {bands.map(([a, b, fill], i) => <ReferenceArea key={i} y1={a} y2={b} fill={fill} fillOpacity={1} stroke="none" ifOverflow="hidden" />)}
          <CartesianGrid vertical={false} stroke="#FFFFFF" />
          {dl != null && <ReferenceLine y={dl} stroke="#B7261E" strokeDasharray="6 4" label={{ value: `DANGER AT ${dl}`, position: 'insideBottomLeft', fill: '#B7261E', fontSize: 12, fontFamily: 'IBM Plex Mono' }} />}
          {dh != null && <ReferenceLine y={dh} stroke="#B7261E" strokeDasharray="6 4" label={{ value: `DANGER FROM ${dh}`, position: 'insideTopLeft', fill: '#B7261E', fontSize: 12, fontFamily: 'IBM Plex Mono' }} />}
          <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={fmtClock} tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12, fill: '#56616B' }} axisLine={false} tickLine={false} />
          <YAxis domain={[lo, hi]} tickFormatter={(v: number) => String(Math.round(v * 10) / 10)} tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12, fill: '#56616B' }} axisLine={false} tickLine={false} width={44} />
          <Tooltip labelFormatter={(t) => fmtClock(Number(t))} formatter={(v) => [String(v), vital]} />
          <Line type="monotone" dataKey="v" stroke="#11171D" strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
