// Number / date formatting helpers. All tolerate null/undefined and render an em
// dash so the UI never shows "NaN" or "undefined".
const DASH = '—'

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH
  return Math.round(n).toLocaleString('en-US')
}

export function fmtCompact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

export function fmtPct(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return DASH
  return `${n.toFixed(digits)}%`
}

export function fmtMs(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return DASH
  return `${n.toFixed(digits)} ms`
}

export function fmtDate(value: string | number | Date | null | undefined): string {
  if (value == null) return DASH
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function fmtDateTime(value: string | number | Date | null | undefined): string {
  if (value == null) return DASH
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
