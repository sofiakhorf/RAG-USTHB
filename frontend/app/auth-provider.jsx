'use client'

/**
 * Global authentication state.
 *
 * The backend session cookie is the single source of truth. This provider asks
 * `GET /api/auth/me/` once on mount and keeps the result in memory, so every
 * page agrees on who is signed in without each one re-asking.
 *
 * Three distinct states are kept apart on purpose:
 *
 *   `loading`       the check has not answered yet
 *   `authenticated` a session exists
 *   `anonymous`     the backend said 401 - genuinely nobody
 *   `error`         the backend could not be reached
 *
 * `anonymous` and `error` must never be conflated: "you are signed out" and
 * "the server is down" call for different screens.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Loader2, TriangleAlert } from 'lucide-react'
import * as authService from '@/services/authService'
import { ROUTES } from '@/lib/routes'
import { useLang } from './rag-lang-provider'

const RagAuthContext = createContext(null)

/** Only same-origin absolute paths are accepted as a post-login destination. */
export function safeNextPath(candidate) {
  if (typeof candidate !== 'string') return null
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return null
  return candidate
}

export function RagAuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading')

  const refresh = useCallback(async () => {
    try {
      const current = await authService.fetchCurrentUser()
      setUser(current)
      setStatus(current ? 'authenticated' : 'anonymous')
      return current
    } catch {
      // Unreachable backend: claiming "signed out" would be a lie, and
      // silently treating it as anonymous would bounce the user to /login for
      // no reason. Surface it and let the guard show a retry screen.
      setUser(null)
      setStatus('error')
      return null
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (credentials) => {
    const signedIn = await authService.login(credentials)
    setUser(signedIn)
    setStatus('authenticated')
    return signedIn
  }, [])

  const logout = useCallback(async () => {
    await authService.logout()
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo(
    () => ({
      user,
      status,
      isAuthenticated: status === 'authenticated',
      isLoading: status === 'loading',
      /** True when the backend could not be reached at all. */
      isOffline: status === 'error',
      login,
      logout,
      refresh,
    }),
    [user, status, login, logout, refresh],
  )

  return <RagAuthContext.Provider value={value}>{children}</RagAuthContext.Provider>
}

export function useAuth() {
  const context = useContext(RagAuthContext)
  if (!context) {
    throw new Error('useAuth() must be used inside <RagAuthProvider>.')
  }
  return context
}

function BlockingScreen({ children }) {
  return (
    <main
      role="status"
      aria-live="polite"
      className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background px-6 text-center text-foreground"
    >
      {children}
    </main>
  )
}

/** Full-page placeholder shown while the session check is in flight. */
function AuthLoading() {
  const { t } = useLang()
  return (
    <BlockingScreen>
      <Loader2 size={26} className="animate-spin text-link" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">{t.auth.guard.loading}</p>
    </BlockingScreen>
  )
}

/** Shown when the backend cannot be reached - offers a real retry. */
function AuthUnavailable() {
  const { t } = useLang()
  const { refresh } = useAuth()

  return (
    <BlockingScreen>
      <span className="flex size-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
        <TriangleAlert size={22} aria-hidden="true" />
      </span>
      <p className="max-w-sm text-sm leading-7 text-muted-foreground">{t.auth.guard.unavailable}</p>
      <button
        type="button"
        onClick={refresh}
        className="inline-flex min-h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-bold text-primary-foreground transition hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {t.auth.guard.retry}
      </button>
    </BlockingScreen>
  )
}

/**
 * Route guard for `/chat` and `/profile`.
 *
 * Anonymous visitors are sent to `/login` carrying the page they wanted, so
 * they land back on it after signing in. A direct URL hit is therefore just as
 * protected as a click through the UI.
 */
export function RequireAuth({ children }) {
  const { status } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (status === 'anonymous') {
      const next = safeNextPath(pathname)
      router.replace(next ? `${ROUTES.login}?next=${encodeURIComponent(next)}` : ROUTES.login)
    }
  }, [status, router, pathname])

  if (status === 'loading') return <AuthLoading />
  if (status === 'error') return <AuthUnavailable />
  if (status !== 'authenticated') return <AuthLoading /> // redirecting

  return children
}

/** Keeps a signed-in student off the sign-in / sign-up pages. */
export function RedirectIfAuthenticated({ children }) {
  const { status } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (status === 'authenticated') router.replace(ROUTES.chat)
  }, [status, router])

  if (status === 'loading' || status === 'authenticated') return <AuthLoading />

  return children
}
