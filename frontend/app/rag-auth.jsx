'use client'

/**
 * Sign-in and sign-up screens.
 *
 * Both live in one `AuthShell` because they share every piece of chrome - the
 * header, the aside, the field styles - and differ only in the fields they show
 * and the endpoint they post to. They are routed as `/login` and `/register`
 * (`app/login/page.jsx`, `app/register/page.jsx`).
 *
 * Validation
 * ----------
 * The rules in `lib/authRules.js` mirror `backend/users/validators.py` so the
 * student gets feedback while typing. The server is still the authority: when
 * it rejects something the client allowed, its message wins and is shown on the
 * offending field.
 *
 * Navigation
 * ----------
 * A successful sign-in goes to the chatbot, or back to the page that bounced
 * the student here (`?next=`). A successful sign-up goes to `/login` - it does
 * **not** sign the student in, because the flow asks for one.
 */

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ChevronDown,
  Eye,
  EyeOff,
  GraduationCap,
  IdCard,
  Info,
  Loader2,
  LockKeyhole,
  Mail,
  TriangleAlert,
  UserRound,
  UserRoundCheck,
} from 'lucide-react'
import { RagLangToggle, useLang } from './rag-lang-provider'
import { RagThemeToggle } from './rag-theme-provider'
import * as authService from '@/services/authService'
import { DEPARTMENT_OPTIONS, validatePin, validateUniversityEmail } from '@/lib/authRules'
import { safeNextPath, useAuth } from './auth-provider'
import { ROUTES } from '@/lib/routes'

/** Backend field name -> the key this form keeps in state. */
const FIELD_NAME_MAP = {
  full_name: 'fullName',
  matricule: 'matricule',
  department: 'department',
  email: 'email',
  password: 'password',
  confirm_password: 'confirmPassword',
}

const EMPTY_VALUES = {
  fullName: '',
  matricule: '',
  department: '',
  email: '',
  password: '',
  confirmPassword: '',
}

/* -------------------------------------------------------------------------- */
/*                                  Field UI                                   */
/* -------------------------------------------------------------------------- */

function FieldError({ id, message }) {
  if (!message) return null
  return (
    <p
      id={id}
      role="alert"
      className="mt-1.5 flex items-start gap-1.5 text-[11px] font-semibold leading-5 text-destructive"
    >
      <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
      {message}
    </p>
  )
}

function TextField({
  id,
  label,
  icon: Icon,
  error,
  hint,
  type = 'text',
  ltr = false,
  trailingIcon,
  onTrailingClick,
  trailingLabel,
  trailingPressed,
  ...inputProps
}) {
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ')

  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-xs font-bold text-foreground">
        {label}
      </label>
      <div className="relative">
        <Icon
          size={17}
          aria-hidden="true"
          className="pointer-events-none absolute start-3.5 top-1/2 -translate-y-1/2 text-link"
        />
        <input
          id={id}
          type={type}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={describedBy || undefined}
          className={`h-12 w-full rounded-xl border bg-muted/60 ps-11 text-sm text-foreground outline-none transition focus:bg-card focus:ring-4 ${
            ltr ? 'text-start' : ''
          } ${
            error
              ? 'border-destructive focus:border-destructive focus:ring-destructive/10'
              : 'border-input focus:border-link focus:ring-link/10'
          } ${trailingIcon ? 'pe-12' : 'pe-4'}`}
          dir={ltr ? 'ltr' : undefined}
          {...inputProps}
        />
        {trailingIcon && (
          <button
            type="button"
            onClick={onTrailingClick}
            aria-label={trailingLabel}
            aria-pressed={trailingPressed}
            className="absolute end-2 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-deep-blue focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            {trailingIcon}
          </button>
        )}
      </div>
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-[11px] leading-5 text-muted-foreground">
          {hint}
        </p>
      )}
      <FieldError id={errorId} message={error} />
    </div>
  )
}

function PasswordField({ id, label, visible, onToggle, visibilityLabels, ...inputProps }) {
  return (
    <TextField
      id={id}
      label={label}
      icon={LockKeyhole}
      type={visible ? 'text' : 'password'}
      ltr
      trailingIcon={visible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
      trailingLabel={visible ? visibilityLabels.hide : visibilityLabels.show}
      trailingPressed={visible}
      onTrailingClick={onToggle}
      {...inputProps}
    />
  )
}

/* -------------------------------------------------------------------------- */
/*                                  Auth shell                                 */
/* -------------------------------------------------------------------------- */

function AuthShell({ mode }) {
  const isRegister = mode === 'register'
  const { t, isRtl } = useLang()
  const router = useRouter()
  const { login } = useAuth()

  const [values, setValues] = useState(EMPTY_VALUES)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const [isConfirmVisible, setIsConfirmVisible] = useState(false)

  // Guards against setting state after a redirect has unmounted the form.
  const mountedRef = useRef(true)

  function updateField(name) {
    return (event) => {
      const { value } = event.target
      setValues((current) => ({ ...current, [name]: value }))
      // Clear the field's error as soon as the student starts fixing it, so a
      // corrected form does not keep shouting about a problem that is gone.
      setErrors((current) => {
        if (!current[name]) return current
        const next = { ...current }
        delete next[name]
        return next
      })
    }
  }

  function validate() {
    const next = {}
    const trimmed = {
      fullName: values.fullName.trim(),
      matricule: values.matricule.trim(),
      email: values.email.trim(),
    }

    if (isRegister) {
      if (!trimmed.fullName) next.fullName = t.auth.validation.fullNameRequired
      else if (trimmed.fullName.length < 2) next.fullName = t.auth.validation.fullNameMin

      if (!trimmed.matricule) next.matricule = t.auth.validation.matriculeRequired

      if (!values.department) next.department = t.auth.validation.departmentRequired
    }

    const emailProblem = validateUniversityEmail(trimmed.email)
    if (emailProblem) next.email = t.auth.validation[emailProblem]

    const pinProblem = validatePin(values.password)
    if (pinProblem) next.password = t.auth.validation[pinProblem]

    if (isRegister) {
      if (!values.confirmPassword) {
        next.confirmPassword = t.auth.validation.confirmPasswordRequired
      } else if (values.password !== values.confirmPassword) {
        next.confirmPassword = t.auth.validation.passwordMismatch
      }
    }

    return next
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setFormError(null)
    setSuccess(null)

    const clientProblems = validate()

    if (Object.keys(clientProblems).length > 0) {
      setErrors(clientProblems)
      return
    }

    setIsSubmitting(true)

    try {
      if (isRegister) {
        await authService.register({
          fullName: values.fullName.trim(),
          matricule: values.matricule.trim(),
          department: values.department,
          email: values.email.trim(),
          password: values.password,
          confirmPassword: values.confirmPassword,
        })

        // Registration deliberately does not sign the student in, so they land
        // on the sign-in page rather than being logged in behind their back.
        router.replace(ROUTES.login)
        return
      }

      await login({
        email: values.email.trim(),
        password: values.password,
      })

      // `?next=` is only honoured when it points back inside this app, so a
      // crafted link cannot bounce the student to another origin.
      const next = safeNextPath(new URLSearchParams(window.location.search).get('next'))
      router.replace(next ?? ROUTES.chat)
    } catch (error) {
      if (!mountedRef.current) return

      if (error?.status === 401) {
        setFormError(t.auth.status.invalidCredentials)
      } else if (error?.code === 'network') {
        setFormError(t.auth.guard.unavailable)
      } else if (error?.fieldErrors && Object.keys(error.fieldErrors).length > 0) {
        // The server names its fields in snake_case; map what we recognise and
        // surface the rest as a form-level message rather than dropping them.
        const next = {}
        const leftovers = []

        for (const [serverField, message] of Object.entries(error.fieldErrors)) {
          const local = FIELD_NAME_MAP[serverField]
          if (local) next[local] = message
          else leftovers.push(message)
        }

        setErrors(next)
        setFormError(leftovers[0] ?? null)
      } else {
        setFormError(error?.message || t.auth.guard.unavailable)
      }
    } finally {
      if (mountedRef.current) setIsSubmitting(false)
    }
  }

  const submitLabel = isSubmitting
    ? t.auth.buttons.submitting
    : isRegister
      ? t.auth.buttons.signUp
      : t.auth.buttons.signIn

  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center overflow-x-hidden bg-background px-4 py-8 text-foreground sm:px-6 sm:py-10">
      <div aria-hidden="true" className="pointer-events-none absolute -start-40 -top-40 size-[440px] rounded-full bg-link/[0.07] blur-[100px]" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-48 -end-32 size-[480px] rounded-full bg-sidebar/[0.06] blur-[110px]" />

      <section aria-labelledby="auth-heading" className="relative w-full max-w-6xl overflow-hidden rounded-[28px] border border-border bg-card shadow-[0_28px_90px_-48px_rgba(11,45,92,0.4)] sm:rounded-[32px]">
        <div className="grid lg:min-h-[690px] lg:grid-cols-[1fr_0.95fr]">
          <div className="p-5 sm:p-8 lg:p-11 xl:p-14">
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => router.replace(ROUTES.home)}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-xs font-bold text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span aria-hidden="true" className={isRtl ? '' : 'rotate-180'}>
                  <ChevronDown size={16} className="-rotate-90" />
                </span>
                {t.auth.backHome}
              </button>

              <div className="flex items-center gap-2">
                <RagLangToggle showLabel={false} />
                <RagThemeToggle />
              </div>
            </div>

            <div className="mx-auto mt-8 max-w-md sm:mt-10">
              <div className="mt-2">
                <p dir="ltr" className="text-left text-xs font-extrabold tracking-wide text-link">
                  {t.auth.eyebrow}
                </p>
                <h1 id="auth-heading" className="mt-2 text-2xl font-extrabold leading-10 text-deep-blue sm:text-3xl">
                  {isRegister ? t.auth.registerTitle : t.auth.loginTitle}
                </h1>
                <p className="mt-2 text-sm leading-7 text-muted-foreground">
                  {isRegister ? t.auth.registerDescription : t.auth.loginDescription}
                </p>
              </div>

              <form key={mode} noValidate onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
                {isRegister && (
                  <>
                    <TextField
                      id="full-name"
                      label={t.auth.fields.fullName}
                      icon={UserRound}
                      name="name"
                      autoComplete="name"
                      placeholder={t.auth.fields.fullNamePlaceholder}
                      value={values.fullName}
                      onChange={updateField('fullName')}
                      error={errors.fullName}
                    />
                    <TextField
                      id="matricule"
                      label={t.auth.fields.matricule}
                      icon={IdCard}
                      name="matricule"
                      autoComplete="off"
                      inputMode="text"
                      ltr
                      placeholder={t.auth.fields.matriculePlaceholder}
                      value={values.matricule}
                      onChange={updateField('matricule')}
                      error={errors.matricule}
                    />
                    <div>
                      <label htmlFor="department" className="mb-2 block text-xs font-bold text-foreground">
                        {t.auth.fields.department}
                      </label>
                      <div className="relative">
                        <GraduationCap
                          size={17}
                          aria-hidden="true"
                          className="pointer-events-none absolute start-3.5 top-1/2 -translate-y-1/2 text-link"
                        />
                        <select
                          id="department"
                          name="department"
                          value={values.department}
                          onChange={updateField('department')}
                          aria-invalid={errors.department ? 'true' : undefined}
                          aria-describedby={errors.department ? 'department-error' : undefined}
                          className={`h-12 w-full appearance-none rounded-xl border bg-muted/60 ps-11 pe-10 text-sm outline-none transition focus:bg-card focus:ring-4 ${
                            errors.department
                              ? 'border-destructive text-destructive focus:border-destructive focus:ring-destructive/10'
                              : 'border-input text-foreground focus:border-link focus:ring-link/10'
                          }`}
                        >
                          <option value="">{t.auth.fields.departmentPlaceholder}</option>
                          {DEPARTMENT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {t.auth.departments[option.key]}
                            </option>
                          ))}
                        </select>
                        <ChevronDown
                          size={16}
                          aria-hidden="true"
                          className="pointer-events-none absolute end-3.5 top-1/2 -translate-y-1/2 text-muted-foreground"
                        />
                      </div>
                      <FieldError id="department-error" message={errors.department} />
                    </div>
                  </>
                )}

                <TextField
                  id="email"
                  label={t.auth.fields.email}
                  icon={Mail}
                  type="email"
                  name="email"
                  autoComplete="email"
                  inputMode="email"
                  ltr
                  placeholder={t.auth.fields.emailPlaceholder}
                  value={values.email}
                  onChange={updateField('email')}
                  error={errors.email}
                  hint={t.auth.hints.emailDomain}
                />

                <PasswordField
                  id="password"
                  label={t.auth.fields.password}
                  name="password"
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                  inputMode="numeric"
                  maxLength={64}
                  placeholder={t.auth.fields.passwordPlaceholder}
                  value={values.password}
                  onChange={updateField('password')}
                  error={errors.password}
                  hint={t.auth.hints.passwordFormat}
                  visible={isPasswordVisible}
                  onToggle={() => setIsPasswordVisible((visible) => !visible)}
                  visibilityLabels={{ show: t.auth.buttons.showPassword, hide: t.auth.buttons.hidePassword }}
                />

                {isRegister && (
                  <PasswordField
                    id="confirm-password"
                    label={t.auth.fields.confirmPassword}
                    name="confirmPassword"
                    autoComplete="new-password"
                    inputMode="numeric"
                    maxLength={64}
                    placeholder={t.auth.fields.confirmPasswordPlaceholder}
                    value={values.confirmPassword}
                    onChange={updateField('confirmPassword')}
                    error={errors.confirmPassword}
                    visible={isConfirmVisible}
                    onToggle={() => setIsConfirmVisible((visible) => !visible)}
                    visibilityLabels={{
                      show: t.auth.buttons.showPassword,
                      hide: t.auth.buttons.hidePassword,
                    }}
                  />
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="mt-1 inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-extrabold text-primary-foreground shadow-sm transition hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-wait disabled:opacity-75"
                >
                  {isSubmitting && <Loader2 size={17} className="animate-spin" aria-hidden="true" />}
                  {submitLabel}
                </button>
              </form>

              {formError && (
                <div
                  role="alert"
                  className="mt-4 flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/10 px-3.5 py-3 text-xs leading-6 text-foreground"
                >
                  <TriangleAlert size={16} className="mt-0.5 shrink-0 text-destructive" aria-hidden="true" />
                  <p>{formError}</p>
                </div>
              )}

              {success && (
                <div
                  role="status"
                  className="mt-4 flex items-start gap-2.5 rounded-xl border border-link/25 bg-primary/25 px-3.5 py-3 text-xs leading-6 text-deep-blue"
                >
                  <Info size={16} className="mt-0.5 shrink-0 text-link" aria-hidden="true" />
                  <p>{success}</p>
                </div>
              )}

              <p className="mt-5 text-center text-xs text-muted-foreground">
                {isRegister ? (
                  <>
                    {t.auth.links.haveAccount}{' '}
                    <button
                      type="button"
                      onClick={() => router.replace(ROUTES.login)}
                      className="rounded-md font-bold text-link transition hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      {t.auth.links.signIn}
                    </button>
                  </>
                ) : (
                  <>
                    {t.auth.links.noAccount}{' '}
                    <button
                      type="button"
                      onClick={() => router.replace(ROUTES.register)}
                      className="rounded-md font-bold text-link transition hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      {t.auth.links.createOne}
                    </button>
                  </>
                )}
              </p>
            </div>
          </div>

          <aside className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-10 text-sidebar-foreground lg:flex xl:p-12">
            <div aria-hidden="true" className="pointer-events-none absolute -start-24 -top-24 size-80 rounded-full bg-link/35 blur-[80px]" />
            <div aria-hidden="true" className="pointer-events-none absolute -bottom-36 -end-24 size-96 rounded-full border-[50px] border-white/[0.05]" />

            <div className="relative z-10 flex items-center gap-3">
              <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-card p-1.5 shadow-sm">
                <img
                  src="/usthb-logo.png"
                  alt={t.auth.aside.logoAlt}
                  width="100"
                  height="99"
                  className="size-full object-contain"
                />
              </span>
              <div>
                <p dir="ltr" className="text-base font-extrabold tracking-tight">RAG-USTHB</p>
                <p className="mt-1 text-[11px] text-sidebar-foreground/65">{t.auth.aside.university}</p>
              </div>
            </div>

            <div className="relative z-10 my-12">
              <span className="inline-flex items-center gap-2 rounded-full border border-sidebar-foreground/15 bg-sidebar-foreground/[0.07] px-3 py-1.5 text-[11px] font-bold text-sidebar-foreground/85">
                <GraduationCap size={15} aria-hidden="true" />
                {t.auth.aside.badge}
              </span>
              <h2 className="mt-5 max-w-lg text-3xl font-extrabold leading-[1.55] xl:text-4xl">
                {t.auth.aside.title}
              </h2>
              <p className="mt-4 max-w-md text-sm leading-7 text-sidebar-foreground/70">
                {t.auth.aside.description}
              </p>
            </div>

            <div className="relative z-10 rounded-2xl border border-sidebar-foreground/15 bg-sidebar-foreground/[0.07] p-4">
              <p className="text-xs font-extrabold text-sidebar-foreground/90">{t.auth.aside.rulesTitle}</p>
              <div className="mt-4 flex flex-col gap-3">
                <div className="flex items-center gap-3 rounded-xl border border-sidebar-foreground/10 bg-sidebar-foreground/[0.06] px-3 py-2.5">
                  <Mail size={16} className="shrink-0 text-sidebar-foreground/80" aria-hidden="true" />
                  <span dir="ltr" className="text-xs text-sidebar-foreground/75">{t.auth.aside.rule1}</span>
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-sidebar-foreground/10 bg-sidebar-foreground/[0.06] px-3 py-2.5">
                  <LockKeyhole size={16} className="shrink-0 text-sidebar-foreground/80" aria-hidden="true" />
                  <span className="text-xs text-sidebar-foreground/75">{t.auth.aside.rule2}</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <footer className="relative mt-5 text-center text-[10px] leading-5 text-muted-foreground lg:mt-0">
        <span className="inline-flex items-center gap-1.5">
          <GraduationCap size={13} aria-hidden="true" />
          {t.auth.footer}
        </span>
      </footer>
    </main>
  )
}

/** Sign-in page - `/login`. */
export function RagLogin() {
  return <AuthShell mode="login" />
}

/** Sign-up page - `/register`. */
export function RagRegister() {
  return <AuthShell mode="register" />
}
