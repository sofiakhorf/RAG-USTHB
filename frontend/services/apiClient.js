/**
 * Shared HTTP client for every backend call.
 *
 * Requests are **relative** (`/api/...`) because `next.config.mjs` proxies that
 * path onto Django. Same-origin means the session cookie travels automatically
 * and no CORS or token storage is involved.
 *
 * CSRF
 * ----
 * Django protects every mutating request with a double-submit token. The flow
 * is:
 *
 *   1. `GET /api/auth/csrf/` seeds the `csrftoken` cookie (same-origin, so the
 *      browser keeps it).
 *   2. Every POST/PUT/PATCH/DELETE echoes it back in the `X-CSRFToken` header.
 *   3. If Django ever rejects it (the cookie can be rotated), the token is
 *      re-seeded and the request is retried **once** - so a stale tab recovers
 *      instead of failing mysteriously.
 *
 * No secret is read here. The only configuration is the path prefix, which is
 * empty because the proxy makes the backend look local.
 */

/** Base path for all API calls. Empty = same origin, proxied by Next.js. */
export const API_BASE_URL = ''

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/** Thrown for any non-2xx answer, carrying everything the UI needs to react. */
export class ApiError extends Error {
  /**
   * @param {object} options
   * @param {string} options.message Human-readable fallback message.
   * @param {number} [options.status] HTTP status code.
   * @param {string} [options.code] Machine-readable code (`detail`, `rag_unavailable`...).
   * @param {Record<string,string>} [options.fieldErrors] Per-field validation messages.
   */
  constructor({ message, status = 0, code = 'request_failed', fieldErrors = {} }) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

/** True when a failure means "nobody is signed in". */
export function isAuthError(error) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403)
}

let csrfToken = null

function readCookie(name) {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Make sure the CSRF cookie exists and is cached for the headers.
 *
 * @returns {Promise<string|null>} The token, or null if the seed failed.
 */
export async function ensureCsrfToken() {
  if (csrfToken) return csrfToken

  try {
    await fetch(`${API_BASE_URL}/api/auth/csrf/`, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
  } catch {
    // A failed seed is reported by the real request below, not here.
    return null
  }

  csrfToken = readCookie('csrftoken')
  return csrfToken
}

/** Forget the cached token; the next request re-seeds it. */
export function resetCsrfToken() {
  csrfToken = null
}

/**
 * Turn a DRF error body into a flat, UI-ready shape.
 *
 * DRF reports field problems as `{"email": ["message"]}` and top-level ones as
 * `{"detail": "message"}`. Anything that is not a plain string is ignored so a
 * nested payload cannot end up rendered verbatim.
 */
function parseErrorBody(body) {
  const fieldErrors = {}
  let message = ''
  let code = 'request_failed'

  if (!body || typeof body !== 'object') {
    return { fieldErrors, message, code }
  }

  if (typeof body.detail === 'string') {
    message = body.detail
  }
  if (typeof body.error === 'string') {
    code = body.error
  }

  for (const [key, value] of Object.entries(body)) {
    if (key === 'detail' || key === 'error') continue

    if (Array.isArray(value) && typeof value[0] === 'string') {
      fieldErrors[key] = value[0]
      if (!message) message = value[0]
    } else if (typeof value === 'string') {
      fieldErrors[key] = value
      if (!message) message = value
    } else if (value && typeof value === 'object') {
      // Nested: {"email": {"email": "…"}} from a nested serializer.
      const [firstKey, firstValue] = Object.entries(value)[0] ?? []
      if (typeof firstValue === 'string') {
        fieldErrors[key] = firstValue
        if (!message) message = firstValue
      } else if (Array.isArray(firstValue) && typeof firstValue[0] === 'string') {
        fieldErrors[key] = firstValue[0]
        if (!message) message = firstValue[0]
      } else if (firstKey) {
        fieldErrors[firstKey] = String(firstValue)
      }
    }
  }

  return { fieldErrors, message, code }
}

/**
 * Perform one API call.
 *
 * @param {string} path e.g. `/api/auth/login/`.
 * @param {object} [options]
 * @param {string} [options.method] Defaults to `GET`.
 * @param {object} [options.body] JSON-serialised request body.
 * @param {AbortSignal} [options.signal]
 * @param {number} [options.retries] Internal; used for the one CSRF retry.
 * @returns {Promise<any>} The parsed JSON body.
 * @throws {ApiError} On network failure or a non-2xx response.
 */
export async function apiFetch(path, options = {}) {
  const { method = 'GET', body, signal, retries = 1 } = options
  const isMutating = MUTATING_METHODS.has(method.toUpperCase())

  if (isMutating) await ensureCsrfToken()

  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (isMutating && csrfToken) headers['X-CSRFToken'] = csrfToken

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: 'same-origin',
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw new ApiError({
      message: cause?.message ?? 'The server could not be reached.',
      status: 0,
      code: 'network',
    })
  }

  // CSRF cookie rotated since the seed - re-seed once and try again, rather
  // than surfacing a confusing 403 to the user.
  if (response.status === 403 && isMutating && retries > 0) {
    const text = await response.text()
    if (/csrf/i.test(text)) {
      resetCsrfToken()
      return apiFetch(path, { ...options, retries: retries - 1 })
    }
    return apiFetch(path, { ...options, retries: 0 })
  }

  const contentType = response.headers.get('content-type') ?? ''
  const raw = await response.text()
  let parsed = null

  if (raw) {
    try {
      parsed = contentType.includes('application/json') ? JSON.parse(raw) : { detail: raw }
    } catch {
      parsed = { detail: raw.slice(0, 300) }
    }
  }

  if (!response.ok) {
    const { fieldErrors, message, code } = parseErrorBody(parsed)
    throw new ApiError({
      message: message || `Request failed with status ${response.status}.`,
      status: response.status,
      code: parsed?.error ?? code,
      fieldErrors,
    })
  }

  return parsed
}

export const api = {
  get: (path, options) => apiFetch(path, { ...options, method: 'GET' }),
  post: (path, body, options) => apiFetch(path, { ...options, method: 'POST', body }),
  delete: (path, options) => apiFetch(path, { ...options, method: 'DELETE' }),
}
