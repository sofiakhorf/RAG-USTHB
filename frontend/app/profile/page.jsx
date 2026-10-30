'use client'

/**
 * The student's profile — `/profile`.
 *
 * Route-guarded, so an anonymous visitor is sent to `/login` with this path in
 * `?next=`, exactly like `/chat`.
 *
 * Everything shown here comes from the backend's `GET /api/auth/me/` payload
 * via the auth provider. That payload is the narrow projection defined by
 * `public_user_payload()` - `id`, `full_name`, `matricule`, `department`,
 * `email` - and never contains a password or a password hash, so there is
 * nothing here that has to be filtered out before rendering.
 *
 * Deliberately read-only: the specification rules out editing and avatars, so
 * this page offers no form, no file picker and no save button. Its only actions
 * are the two ways out - back to the chatbot, or sign out.
 */

import { useState } from 'react'
import { ArrowLeft, GraduationCap, IdCard, Loader2, LogOut, Mail, UserRound } from 'lucide-react'
import { RequireAuth, useAuth } from '../auth-provider'
import { RagLangToggle, useLang } from '../rag-lang-provider'
import { RagThemeToggle } from '../rag-theme-provider'
import { useAppNavigation } from '../useAppNavigation'
import { departmentLabelKey } from '@/lib/authRules'
import { ROUTES } from '@/lib/routes'

/** One read-only field. Labels come from `t.profile`; values never do. */
function Field({ id, label, value, icon: Icon, ltr = false }) {
  return (
    <div className="rounded-2xl border border-border bg-card px-4 py-3.5">
      <p className="flex items-center gap-2 text-[11px] font-bold text-muted-foreground">
        <Icon size={14} className="shrink-0 text-link" aria-hidden="true" />
        {label}
      </p>
      {/* `dir="ltr"` only on values that are inherently left-to-right - the
          e-mail and the matricule - so an Arabic reader sees the rest aligned
          to the right margin while the address itself stays readable. */}
      <p
        dir={ltr ? 'ltr' : undefined}
        className={`mt-1.5 break-words text-sm font-semibold text-foreground ${ltr ? 'text-start' : ''}`}
      >
        {value || '—'}
      </p>
    </div>
  )
}

function ProfileScreen() {
  const { t, isRtl } = useLang()
  const navigate = useAppNavigation()
  const { user, logout } = useAuth()

  const [isSigningOut, setIsSigningOut] = useState(false)

  // The stored department is a backend key (`computer_science`). Translate it
  // when this build knows the key; otherwise show it raw rather than a dash -
  // a student whose department we cannot name should still see *something*
  // true about their own account.
  const departmentKey = departmentLabelKey(user?.department)
  const departmentLabel = departmentKey
    ? t.auth.departments[departmentKey]
    : user?.department

  async function handleLogout() {
    setIsSigningOut(true)
    try {
      await logout()
    } finally {
      navigate('home')
    }
  }

  return (
    <main className="min-h-dvh bg-background text-foreground">
      <div className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-6 sm:py-10">
        <header className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => navigate('chat')}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-card px-4 text-xs font-bold text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <ArrowLeft size={15} aria-hidden="true" className={isRtl ? 'rotate-180' : ''} />
            {t.profile.backToChat}
          </button>

          <div className="flex items-center gap-2">
            <RagLangToggle showLabel={false} />
            <RagThemeToggle />
          </div>
        </header>

        <section className="mt-6 overflow-hidden rounded-[24px] border border-border bg-card shadow-[0_24px_70px_-45px_rgba(11,45,92,0.45)]">
          <div className="relative overflow-hidden bg-sidebar px-5 py-7 text-sidebar-foreground sm:px-7">
            <div aria-hidden="true" className="pointer-events-none absolute -end-16 -top-20 size-56 rounded-full bg-link/30 blur-[70px]" />
            <div className="relative z-10 flex items-start gap-3">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-card p-1.5 shadow-sm">
                <img
                  src="/usthb-logo.png"
                  alt={t.auth.aside.logoAlt}
                  width="100"
                  height="99"
                  className="size-full object-contain"
                />
              </span>
              <div className="min-w-0">
                <p className="truncate text-lg font-extrabold leading-7">{user?.fullName}</p>
                <p dir="ltr" className="mt-1 truncate text-left text-xs text-sidebar-foreground/70">
                  {user?.email}
                </p>
              </div>
            </div>
          </div>

          <div className="px-5 py-6 sm:px-7">
            <p className="text-xs leading-6 text-muted-foreground">{t.profile.subtitle}</p>

            <dl className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field id="full-name" label={t.profile.fullName} value={user?.fullName} icon={UserRound} />
              </div>
              <Field id="matricule" label={t.profile.matricule} value={user?.matricule} icon={IdCard} ltr />
              <Field id="department" label={t.profile.department} value={departmentLabel} icon={GraduationCap} />
              <div className="sm:col-span-2">
                <Field id="email" label={t.profile.email} value={user?.email} icon={Mail} ltr />
              </div>
            </dl>

            <div className="mt-6 flex flex-col gap-2 border-t border-border pt-5 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => navigate('chat')}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-link/35 bg-secondary/60 px-5 text-xs font-bold text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <ArrowLeft size={15} aria-hidden="true" className={isRtl ? 'rotate-180' : ''} />
                {t.profile.backToChat}
              </button>
              <button
                type="button"
                onClick={handleLogout}
                disabled={isSigningOut}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-destructive/35 bg-destructive/10 px-5 text-xs font-bold text-destructive transition hover:bg-destructive/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-70"
              >
                {isSigningOut ? (
                  <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                ) : (
                  <LogOut size={15} aria-hidden="true" />
                )}
                {t.profile.logout}
              </button>
            </div>
          </div>
        </section>

        <p className="mt-5 text-center text-[11px] leading-5 text-muted-foreground">
          {t.sidebar.footer}
          <span dir="ltr" className="mt-0.5 block">USTHB · Algiers</span>
        </p>
      </div>
    </main>
  )
}

/** `/profile` */
export default function ProfilePage() {
  return (
    <RequireAuth>
      <ProfileScreen />
    </RequireAuth>
  )
}
