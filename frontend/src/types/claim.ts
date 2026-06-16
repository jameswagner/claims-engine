export type ClaimStatus =
  | 'CREATED'
  | 'VALIDATED'
  | 'SUBMITTING'
  | 'SUBMITTED'
  | 'CLEARINGHOUSE_REJECTED'
  | 'ADJUDICATED'
  | 'PAID'
  | 'DENIED'

export interface ClaimEvent {
  id: string
  from_status: ClaimStatus
  to_status: ClaimStatus
  reason: string | null
  idempotency_key: string | null
  triggered_at: string
}

export interface Claim {
  id: string
  patient_name: string
  provider_name: string
  cpt_code: string
  diagnosis_code: string
  insurance_payer: string
  status: ClaimStatus
  billed_amount: number
  allowed_amount: number | null
  paid_amount: number | null
  patient_responsibility: number | null
  adjustment_reason: string | null
  created_at: string
  updated_at: string
}

export interface ClaimDetail extends Claim {
  events: ClaimEvent[]
}

export interface PayerDenialRate {
  payer: string
  total: number
  denied: number
  denial_rate_pct: number
}

export interface CptDenialRate {
  cpt_code: string
  total: number
  denied: number
  denial_rate_pct: number
}

export interface PayerAdjDays {
  payer: string
  avg_days: number
}

export interface ClaimsAnalytics {
  claims_by_status: Record<string, number>
  denial_rate_by_payer: PayerDenialRate[]
  denial_rate_by_cpt: CptDenialRate[]
  avg_days_to_adjudication_by_payer: PayerAdjDays[]
  aging_summary: { over_14_days: number; over_30_days: number }
  resubmission_success_rate: { resubmitted: number; eventually_paid: number; rate_pct: number }
  throughput_last_24h: { created: number; submitted: number; paid: number; denied: number }
}

export interface DenialRateDailyPoint {
  date: string
  payer: string
  total: number
  denied: number
  denial_rate_pct: number
}

export interface PosDenialRate {
  payer: string
  place_of_service: string
  total: number
  denied: number
  denial_rate_pct: number
}

export interface FastForwardStatus {
  running: boolean
  day: number
  total_days: number
  claims_created: number
}

export interface FastForwardResult {
  day_index: number
  date_written: string | null
  complete: boolean
}
