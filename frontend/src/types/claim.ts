export type ClaimStatus =
  | 'CREATED'
  | 'VALIDATED'
  | 'SUBMITTED'
  | 'ADJUDICATED'
  | 'PAID'
  | 'DENIED'

export interface ClaimEvent {
  id: string
  from_status: ClaimStatus
  to_status: ClaimStatus
  reason: string | null
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
