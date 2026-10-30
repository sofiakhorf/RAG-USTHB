/**
 * Authentication API client for the RAG-USTHB frontend.
 *
 * Mirrors the Django endpoints in `backend/users/`:
 *
 *   POST /api/auth/register/   create a student account
 *   POST /api/auth/login/      start a session
 *   POST /api/auth/logout/     end it
 *   GET  /api/auth/me/         describe the current session
 *
 * Authentication is a **Django session cookie** managed by the browser. This
 * module never reads, writes or stores a token, and there is no secret here -
 * only relative paths that `next.config.mjs` proxies to the backend.
 *
 * The backend is the sole authority on every rule (e-mail domain, PIN format,
 * uniqueness). The checks in `lib/authRules.js` exist to give instant feedback;
 * a failure here always wins.
 */

import { api, ApiError, isAuthError, resetCsrfToken } from './apiClient'

export { ApiError, isAuthError }

export const AUTH_ENDPOINTS = {
  register: '/api/auth/register/',
  login: '/api/auth/login/',
  logout: '/api/auth/logout/',
  me: '/api/auth/me/',
}

/**
 * Backend `public_user_payload()` -> the shape the UI consumes.
 *
 * The API speaks snake_case and deliberately exposes no more than
 * `id`, `full_name`, `matricule`, `department`, `email`. There is no password
 * or password hash in this object at any point, and nothing is added here that
 * the backend does not send.
 */
function normalizeUser(user) {
  if (!user) return null
  return {
    id: user.id,
    fullName: user.full_name ?? '',
    matricule: user.matricule ?? '',
    department: user.department ?? '',
    email: user.email ?? '',
  }
}

/**
 * Create a student account.
 *
 * @param {object} profile
 * @param {string} profile.fullName
 * @param {string} profile.matricule
 * @param {string} profile.department Backend key, e.g. `computer_science`.
 * @param {string} profile.email University e-mail.
 * @param {string} profile.password Exactly 8 digits.
 * @param {string} profile.confirmPassword Must match `password`.
 * @returns {Promise<object>} The created account's public projection.
 * @throws {ApiError} With `fieldErrors` when a rule is broken.
 */
export async function register({ fullName, matricule, department, email, password, confirmPassword }) {
  const body = await api.post(AUTH_ENDPOINTS.register, {
    full_name: fullName,
    matricule,
    department,
    email,
    password,
    confirm_password: confirmPassword,
  })

  return normalizeUser(body?.user)
}

/**
 * Sign in. On success the browser receives the `sessionid` cookie.
 *
 * @param {{ email: string, password: string }} credentials
 * @returns {Promise<object>} The signed-in student's public projection.
 * @throws {ApiError} `400` for a malformed e-mail, `401` for bad credentials.
 */
export async function login({ email, password }) {
  const body = await api.post(AUTH_ENDPOINTS.login, { email, password })

  return normalizeUser(body?.user)
}

/**
 * End the current session server-side and expire the cookie.
 *
 * @returns {Promise<void>}
 */
export async function logout() {
  try {
    await api.post(AUTH_ENDPOINTS.logout, {})
  } finally {
    // Whatever happened, the browser must stop believing it is signed in.
    resetCsrfToken()
  }
}

/**
 * Describe the current session.
 *
 * @returns {Promise<object|null>} The user, or `null` when nobody is signed in.
 *   A network failure is *not* treated as "signed out" - it is rethrown, so the
 *   UI can tell "session expired" apart from "backend is down".
 */
export async function fetchCurrentUser() {
  try {
    const body = await api.get(AUTH_ENDPOINTS.me)
    return normalizeUser(body?.user)
  } catch (error) {
    if (isAuthError(error)) return null
    throw error
  }
}
