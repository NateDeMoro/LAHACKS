import { useStore } from '../store'

/** Shown while the dashboard socket is down, so old numbers are never mistaken for live ones. */
export default function ConnectionBanner() {
  const { connected } = useStore()
  if (connected) return null
  return <div role="alert" className="px-10 py-2 bg-high-tint border-b border-high text-body font-[600] text-high">Connection lost. Numbers may be out of date.</div>
}
