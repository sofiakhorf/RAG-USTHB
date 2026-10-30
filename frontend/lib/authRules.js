/**
 * Client-side mirror of the account rules the backend enforces.
 *
 * `backend/users/validators.py` is the authority; these constants exist only so
 * the form can react while the student types instead of waiting for a round
 * trip. They must be kept in step with that file - if the two ever disagree,
 * the server wins and the form shows the server's message.
 */

/** The only domain a student may register with. */
export const UNIVERSITY_EMAIL_DOMAIN = 'etu.usthb.dz'

/** A student password is exactly this many digits - a numeric PIN. */
export const PASSWORD_LENGTH = 8

/** A matricule is a short administrative number. */
export const MAX_MATRICULE_LENGTH = 30

/**
 * Departments offered at registration.
 *
 * `value` is what is sent to the backend; `key` selects the label in the
 * translation dictionary.
 */
export const DEPARTMENT_OPTIONS = [
  { value: 'computer_science', key: 'computerScience' },
  { value: 'mathematics', key: 'mathematics' },
  { value: 'physics', key: 'physics' },
  { value: 'chemistry', key: 'chemistry' },
  { value: 'electronics', key: 'electronics' },
  { value: 'civil_engineering', key: 'civilEngineering' },
]

/** `name@etu.usthb.dz`, any case, exactly one `@`, no whitespace. */
export const UNIVERSITY_EMAIL_PATTERN = new RegExp(
  `^[^@\\s]+@${UNIVERSITY_EMAIL_DOMAIN.replace(/\./g, '\\.')}$`,
  'i',
)

/**
 * Map a stored department key to its translation key.
 *
 * The profile page reads a department the student chose long ago, so it may be
 * a value this build does not offer (an older list, or a value edited in the
 * admin). Returning `null` in that case lets the caller show the raw value
 * rather than blank the field.
 *
 * @param {string} department Backend key, e.g. `computer_science`.
 * @returns {string|null} A key under `t.auth.departments`, or `null`.
 */
export function departmentLabelKey(department) {
  const match = DEPARTMENT_OPTIONS.find((option) => option.value === department)
  return match ? match.key : null
}

/** Exactly eight ASCII digits. `[0-9]` rather than `\d`, so Arabic-Indic
 *  digits typed on a non-Latin keypad are refused consistently with the
 *  backend. */
export const PIN_PATTERN = /^[0-9]{8}$/

/**
 * Validate a university e-mail.
 *
 * @param {string} value
 * @returns {string|null} `null` when valid, otherwise a dictionary key under
 *   `t.auth.validation`.
 */
export function validateUniversityEmail(value) {
  const candidate = String(value ?? '').trim()

  if (!candidate) return 'emailRequired'
  if (!UNIVERSITY_EMAIL_PATTERN.test(candidate)) return 'emailDomain'

  return null
}

/**
 * Validate the numeric PIN.
 *
 * @param {string} value
 * @returns {string|null} `null` when valid, otherwise a validation key.
 */
export function validatePin(value) {
  const candidate = String(value ?? '')

  if (!candidate) return 'passwordRequired'
  if (!PIN_PATTERN.test(candidate)) return 'passwordFormat'

  return null
}
