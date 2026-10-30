export function createId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/** Human readable file size used by the upload notice and document rows. */
export function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB'

  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent

  return `${value >= 10 || exponent === 0 ? Math.round(value) : value.toFixed(1)} ${units[exponent]}`
}

/** Minimal RFC-5322-style check: something@domain.tld */
export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

const RELATIVE_UNITS = [
  { unit: 'year', ms: 365 * 24 * 60 * 60 * 1000 },
  { unit: 'month', ms: 30 * 24 * 60 * 60 * 1000 },
  { unit: 'week', ms: 7 * 24 * 60 * 60 * 1000 },
  { unit: 'day', ms: 24 * 60 * 60 * 1000 },
  { unit: 'hour', ms: 60 * 60 * 1000 },
  { unit: 'minute', ms: 60 * 1000 },
]

/**
 * Language-aware "12 minutes ago" built from a timestamp, so the sidebar never
 * stores a translated literal.
 */
export function formatRelativeTime(timestamp, locale = 'en-US', now = Date.now()) {
  if (!Number.isFinite(timestamp)) return ''

  const elapsed = timestamp - now
  const magnitude = Math.abs(elapsed)

  for (const { unit, ms } of RELATIVE_UNITS) {
    if (magnitude >= ms) {
      return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
        .format(Math.round(elapsed / ms), unit)
    }
  }

  return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(0, 'minute')
}
