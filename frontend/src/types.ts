// Mirrors backend/contracts.py (I8, I9, I10, I13, I14) plus the HTTP shapes assumed in api.ts.
export type Level = 'safe' | 'warning' | 'danger'
export type Severity = 'warning' | 'urgent' | 'high'
export type VitalKey = 'hr' | 'resp_rate' | 'spo2' | 'temp_c'

export interface VitalRange {
  safe_low?: number | null; safe_high?: number | null
  danger_low?: number | null; danger_high?: number | null
  source?: string | null; reasons?: string[] | null
}
export interface I8 { patient_id: string; hr?: VitalRange | null; resp_rate?: VitalRange | null; spo2?: VitalRange | null; temp_c?: VitalRange | null; sbp?: VitalRange | null }
export interface News2Points { resp_rate?: number | null; spo2?: number | null; on_oxygen?: number | null; sbp?: number | null; hr?: number | null; alertness?: number | null; temp_c?: number | null }
export interface VitalValues { hr?: number | null; resp_rate?: number | null; spo2?: number | null; temp_c?: number | null }
export interface VitalLevels { hr?: Level | null; resp_rate?: Level | null; spo2?: Level | null; temp_c?: Level | null }
export interface I9 {
  patient_id: string; ts?: string | null; level?: Level | null; vital?: string | null; reason?: string | null
  vital_levels?: VitalLevels | null; vital_values?: VitalValues | null
  news2?: number | null; news2_points?: News2Points | null
  trend_prob_fast?: number | null; trend_tier?: string | null; trend_reason_fast?: string | null
}
export interface I10 {
  alert_id: string; patient_id: string; ts?: string | null; severity?: Severity | null
  trigger?: 'vital_danger' | 'news2_total' | 'warning_persisted' | 'trend' | null
  vital?: string | null; supersedes?: string[] | null; resolved?: boolean | null; message?: string | null
}
export interface I13 { patient_id: string; window_end_ts?: string | null; hr?: number | null; resp_rate?: number | null; spo2?: number | null; temp_c?: number | null; clean_seconds?: number | null; run_state?: 'live' | 'running' | 'ended' | null }
export interface I14 { patient_id: string; ts?: string | null; news2?: number | null; news2_points?: News2Points | null }

export interface PatientRow {
  patient_id: string; name: string | null; arrival_ts: string | null; bed: string | null
  called_in_ts: string | null; simulated: boolean
}
export interface RunStatus {
  state: 'live' | 'running' | 'ended'; profile_id?: string | null; patient_id?: string | null
  kind?: 'single' | 'scenario' | null; sim_now?: string | null
}
export interface Wearable { wearable_id: number; label: string; patient_id: string | null; simulated?: boolean }

export interface IntakeRecord {
  patient_id?: string; name?: string; wearable_id?: number; arrival_ts?: string
  age?: number; sex?: 'male' | 'female'; height_cm?: number; weight_kg?: number; pregnant?: boolean | null
  conditions?: string[]; medications?: string[]; chief_complaint?: string
  triage?: { sbp?: number; dbp?: number; alertness?: string; pain?: number; on_oxygen?: boolean; level?: number }
}
export interface IntakeCard { context: IntakeRecord & { bmi?: number | null; drug_classes?: string[] | null; unmatched_medications?: string[] | null }; ranges: I8 | null; adjuster: string }
