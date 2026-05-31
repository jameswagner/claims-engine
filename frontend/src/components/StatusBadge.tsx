import type { ClaimStatus } from '../types/claim'

const STYLES: Record<ClaimStatus, string> = {
  CREATED:                'bg-gray-100 text-gray-700',
  VALIDATED:              'bg-blue-100 text-blue-700',
  SUBMITTING:             'bg-amber-100 text-amber-800',
  SUBMITTED:              'bg-yellow-100 text-yellow-800',
  CLEARINGHOUSE_REJECTED: 'bg-orange-100 text-orange-800',
  ADJUDICATED:            'bg-purple-100 text-purple-700',
  PAID:                   'bg-green-100 text-green-700',
  DENIED:                 'bg-red-100 text-red-700',
}

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide ${STYLES[status]}`}>
      {status}
    </span>
  )
}
