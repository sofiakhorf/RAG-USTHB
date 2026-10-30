
/**
 * Shared HTTP client for every backend call.
 * Requests use the same-origin Next.js proxy.
 */

export const API_BASE_URL = ''

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError extends Error {
  constructor({
    message,
    status = 0,
    code = 'request_failed',
    fieldErrors = {},
  }) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

export function isAuthError(error) {
  return error instanceof ApiError &&
    (error.status === 401 || error.status === 403)
}

function readCookie(name) {
  if (typeof document === 'undefined') return null

  const escapedName = name.replace(
    /[.*+?^${}()|[\]\\]/g,
    '\\$&'
  )

  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${escapedName}=([^;]*)`)
  )

  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Always request a fresh CSRF cookie from Django.
 */
export async function ensureCsrfToken() {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/auth/csrf/`,
      {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {
          Accept: 'application/json',
        },
      }
    )

    if (!response.ok) {
      throw new Error(`CSRF request failed: ${response.status}`)
    }

    const token = readCookie('csrftoken')

    if (!token) {
      throw new Error('CSRF cookie was not found.')
    }

    return token
  } catch (cause) {
    throw new ApiError({
      message: cause?.message || 'Could not obtain CSRF token.',
      status: 0,
      code: 'csrf_unavailable',
    })
  }
}

export function resetCsrfToken() {
  // No in-memory token is cached anymore.
}

/**
 * Parse Django REST Framework error responses.
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
    }
  }

  return { fieldErrors, message, code }
}

async function readResponse(response) {
  const contentType = response.headers.get('content-type') || ''
  const raw = await response.text()

  if (!raw) return null

  try {
    return contentType.includes('application/json')
      ? JSON.parse(raw)
      : { detail: raw.slice(0, 300) }
  } catch {
    return { detail: raw.slice(0, 300) }
  }
}

/**
 * Perform one API request.
 */
export async function apiFetch(path, options = {}) {
  const {
    method = 'GET',
    body,
    signal,
    retries = 1,
  } = options

  const normalizedMethod = method.toUpperCase()
  const isMutating = MUTATING_METHODS.has(normalizedMethod)

  // Get a fresh CSRF token before every mutating request.
  let token = null

  if (isMutating) {
    token = await ensureCsrfToken()
  }

  const headers = {
    Accept: 'application/json',
    ...options.headers,
  }

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  if (isMutating) {
    headers['X-CSRFToken'] = token
  }

  let response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: normalizedMethod,
      credentials: 'same-origin',
      cache: 'no-store',
      headers,
      signal,
      body: body === undefined
        ? undefined
        : JSON.stringify(body),
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause

    throw new ApiError({
      message: cause?.message || 'The server could not be reached.',
      status: 0,
      code: 'network',
    })
  }

  const parsed = await readResponse(response)

  // Retry once only when Django explicitly reports a CSRF failure.
  const csrfFailed =
    response.status === 403 &&
    isMutating &&
    typeof parsed?.detail === 'string' &&
    /csrf/i.test(parsed.detail)

  if (csrfFailed && retries > 0) {
    return apiFetch(path, {
      ...options,
      retries: retries - 1,
    })
  }

  if (!response.ok) {
    const { fieldErrors, message, code } = parseErrorBody(parsed)

    throw new ApiError({
      message: message || `Request failed with status ${response.status}.`,
      status: response.status,
      code: parsed?.error || code,
      fieldErrors,
    })
  }

  return parsed
}

export const api = {
  get: (path, options) =>
    apiFetch(path, { ...options, method: 'GET' }),

  post: (path, body, options) =>
    apiFetch(path, { ...options, method: 'POST', body }),

  delete: (path, options) =>
    apiFetch(path, { ...options, method: 'DELETE' }),
}
