'use client'

import { useState } from 'react'
import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  Eye,
  EyeOff,
  FileText,
  GraduationCap,
  IdCard,
  Info,
  Loader2,
  LockKeyhole,
  Mail,
  UserRound,
} from 'lucide-react'

function AuthTextField({ id, label, icon: Icon, direction = 'rtl', ...inputProps }) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-xs font-bold text-[#243247]">
        {label}
      </label>
      <div className="relative">
        <Icon
          size={17}
          aria-hidden="true"
          className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-[#1565C0]"
        />
        <input
          id={id}
          dir={direction}
          {...inputProps}
          className={`h-12 w-full rounded-xl border border-[#C9D7E8] bg-[#F4F7FB] pr-11 pl-4 text-sm text-[#243247] outline-none transition placeholder:text-[#243247]/45 focus:border-[#1565C0] focus:bg-white focus:ring-4 focus:ring-[#1565C0]/10 ${direction === 'ltr' ? 'text-left' : 'text-right'}`}
        />
      </div>
    </div>
  )
}

export function RagAuth({ initialMode = 'login', onNavigate, onOpenDemo }) {
  const [mode, setMode] = useState(initialMode === 'register' ? 'register' : 'login')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const [status, setStatus] = useState('')

  const isRegister = mode === 'register'

  function changeMode(nextMode) {
    setMode(nextMode)
    setStatus('')
    setIsPasswordVisible(false)
  }

  function handleSubmit(event) {
    event.preventDefault()
    if (isSubmitting) return

    setIsSubmitting(true)
    setStatus('')

    window.setTimeout(() => {
      setIsSubmitting(false)
      setStatus('خدمة الحسابات غير متصلة في هذه المعاينة، ولم يتم تسجيل الدخول أو إنشاء حساب. يمكنك استكشاف المنصة كزائر.')
    }, 650)
  }

  function handleForgotPassword() {
    setStatus('استعادة كلمة المرور غير متاحة قبل ربط خدمة الحسابات الجامعية.')
  }

  return (
    <main dir="rtl" className="relative flex min-h-dvh flex-col items-center justify-center overflow-x-hidden bg-[#F4F7FB] px-4 py-8 text-[#243247] sm:px-6 sm:py-10">
      <div aria-hidden="true" className="pointer-events-none absolute -left-40 -top-40 size-[440px] rounded-full bg-[#1565C0]/[0.07] blur-[100px]" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-48 -right-32 size-[480px] rounded-full bg-[#0B2D5C]/[0.06] blur-[110px]" />

      <section aria-labelledby="auth-heading" className="relative w-full max-w-6xl overflow-hidden rounded-[28px] border border-[#C9D7E8] bg-white shadow-[0_28px_90px_-48px_rgba(11,45,92,0.4)] sm:rounded-[32px]">
        <div className="grid lg:min-h-[690px] lg:grid-cols-[1fr_0.95fr]">
          <div className="p-5 sm:p-8 lg:p-11 xl:p-14">
            <div className="flex items-center justify-between gap-4">
              <button
                type="button"
                onClick={() => onNavigate('home')}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-xs font-bold text-[#0B2D5C] transition hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0]"
              >
                <ArrowRight size={16} aria-hidden="true" />
                العودة إلى الرئيسية
              </button>
              <span dir="ltr" className="text-xs font-extrabold tracking-wide text-[#0B2D5C] lg:hidden">RAG-USTHB</span>
            </div>

            <div className="mx-auto mt-8 max-w-md sm:mt-10">
              <div role="group" aria-label="اختيار نوع الحساب" className="grid grid-cols-2 rounded-xl bg-[#F4F7FB] p-1.5">
                <button
                  type="button"
                  aria-pressed={!isRegister}
                  onClick={() => changeMode('login')}
                  className={`min-h-11 rounded-lg px-3 text-sm font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0] ${
                    !isRegister ? 'bg-white text-[#0B2D5C] shadow-sm' : 'text-[#243247]/65 hover:text-[#0B2D5C]'
                  }`}
                >
                  تسجيل الدخول
                </button>
                <button
                  type="button"
                  aria-pressed={isRegister}
                  onClick={() => changeMode('register')}
                  className={`min-h-11 rounded-lg px-3 text-sm font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0] ${
                    isRegister ? 'bg-white text-[#0B2D5C] shadow-sm' : 'text-[#243247]/65 hover:text-[#0B2D5C]'
                  }`}
                >
                  حساب جديد
                </button>
              </div>

              <div className="mt-7">
                <p className="text-xs font-extrabold text-[#1565C0]">RAG-USTHB · بوابتك الدراسية</p>
                <h1 id="auth-heading" className="mt-2 text-2xl font-extrabold leading-10 text-[#0B2D5C] sm:text-3xl">
                  {isRegister ? 'أنشئ حسابك الجامعي' : 'مرحباً بعودتك'}
                </h1>
                <p className="mt-2 text-sm leading-7 text-[#243247]/65">
                  {isRegister
                    ? 'أدخل بياناتك للانضمام إلى مساحة الدراسة الأكاديمية.'
                    : 'سجّل الدخول لمتابعة موادك ومحادثاتك الدراسية.'}
                </p>
              </div>

              <form key={mode} onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
                {isRegister && (
                  <>
                    <AuthTextField
                      id="full-name"
                      label="الاسم الكامل"
                      icon={UserRound}
                      type="text"
                      name="name"
                      autoComplete="name"
                      placeholder="الاسم واللقب"
                      required
                    />
                    <AuthTextField
                      id="student-id"
                      label="رقم الطالب / Matricule"
                      icon={IdCard}
                      type="text"
                      name="studentId"
                      autoComplete="off"
                      inputMode="text"
                      direction="ltr"
                      placeholder="مثال: 202312345"
                      required
                    />
                    <div>
                      <label htmlFor="department" className="mb-2 block text-xs font-bold text-[#243247]">
                        القسم
                      </label>
                      <div className="relative">
                        <GraduationCap
                          size={17}
                          aria-hidden="true"
                          className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-[#1565C0]"
                        />
                        <select
                          id="department"
                          name="department"
                          defaultValue="informatics"
                          className="h-12 w-full appearance-none rounded-xl border border-[#C9D7E8] bg-[#F4F7FB] pr-11 pl-10 text-sm text-[#243247] outline-none transition focus:border-[#1565C0] focus:bg-white focus:ring-4 focus:ring-[#1565C0]/10"
                        >
                          <option value="informatics">قسم الإعلام الآلي</option>
                          <option value="mathematics">قسم الرياضيات</option>
                          <option value="physics">قسم الفيزياء</option>
                          <option value="chemistry">قسم الكيمياء</option>
                          <option value="electronics">قسم الإلكترونيات</option>
                          <option value="civil-engineering">قسم الهندسة المدنية</option>
                        </select>
                        <ChevronDown
                          size={16}
                          aria-hidden="true"
                          className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#243247]/55"
                        />
                      </div>
                    </div>
                  </>
                )}

                <AuthTextField
                  id="university-email"
                  label="البريد الجامعي"
                  icon={Mail}
                  type="email"
                  name="email"
                  autoComplete="email"
                  direction="ltr"
                  placeholder="name@usthb.dz"
                  required
                />

                <div>
                  <label htmlFor="password" className="mb-2 block text-xs font-bold text-[#243247]">
                    كلمة المرور
                  </label>
                  <div className="relative">
                    <LockKeyhole
                      size={17}
                      aria-hidden="true"
                      className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-[#1565C0]"
                    />
                    <input
                      id="password"
                      dir="ltr"
                      type={isPasswordVisible ? 'text' : 'password'}
                      name="password"
                      autoComplete={isRegister ? 'new-password' : 'current-password'}
                      minLength={8}
                      placeholder="ثمانية أحرف على الأقل"
                      required
                      className="h-12 w-full rounded-xl border border-[#C9D7E8] bg-[#F4F7FB] px-11 text-left text-sm text-[#243247] outline-none transition placeholder:text-left placeholder:text-[#243247]/45 focus:border-[#1565C0] focus:bg-white focus:ring-4 focus:ring-[#1565C0]/10"
                    />
                    <button
                      type="button"
                      aria-label={isPasswordVisible ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                      aria-pressed={isPasswordVisible}
                      onClick={() => setIsPasswordVisible((visible) => !visible)}
                      className="absolute left-2 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-lg text-[#243247]/60 transition hover:bg-[#EAF2FF] hover:text-[#0B2D5C] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0]"
                    >
                      {isPasswordVisible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="mt-1 inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#1565C0] px-4 text-sm font-extrabold text-white shadow-sm transition hover:bg-[#0B2D5C] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1565C0] disabled:cursor-wait disabled:opacity-75"
                >
                  {isSubmitting && <Loader2 size={17} className="animate-spin" aria-hidden="true" />}
                  {isSubmitting ? 'جارٍ التحقق...' : isRegister ? 'إنشاء الحساب' : 'تسجيل الدخول'}
                </button>
              </form>

              {status && (
                <div role="status" className="mt-4 flex items-start gap-2.5 rounded-xl border border-[#1565C0]/20 bg-[#EAF2FF] px-3.5 py-3 text-xs leading-6 text-[#0B2D5C]">
                  <Info size={16} className="mt-0.5 shrink-0 text-[#1565C0]" aria-hidden="true" />
                  <p>{status}</p>
                </div>
              )}

              <div className="mt-4 flex flex-col items-center justify-between gap-3 text-center sm:flex-row sm:text-right">
                {!isRegister ? (
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    className="rounded-md text-xs font-bold text-[#1565C0] underline-offset-4 transition hover:text-[#0B2D5C] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0]"
                  >
                    هل نسيت كلمة السر؟
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => changeMode('login')}
                    className="rounded-md text-xs font-bold text-[#243247]/70 transition hover:text-[#1565C0] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0]"
                  >
                    لديك حساب بالفعل؟ <span className="text-[#1565C0]">تسجيل الدخول</span>
                  </button>
                )}
                <p className="inline-flex items-center gap-1.5 text-[10px] leading-5 text-[#243247]/55">
                  <Info size={13} aria-hidden="true" />
                  واجهة معاينة؛ لا تُرسل بياناتك الحقيقية.
                </p>
              </div>

              <button
                type="button"
                onClick={onOpenDemo}
                className="mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-[#C9D7E8] bg-white px-4 text-sm font-bold text-[#0B2D5C] transition hover:border-[#1565C0]/50 hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1565C0]"
              >
                <BookOpen size={17} aria-hidden="true" />
                استكشاف المنصة كزائر
              </button>
            </div>
          </div>

          <aside className="relative hidden flex-col justify-between overflow-hidden bg-[#0B2D5C] p-10 text-white lg:flex xl:p-12">
            <div aria-hidden="true" className="pointer-events-none absolute -left-24 -top-24 size-80 rounded-full bg-[#1565C0]/35 blur-[80px]" />
            <div aria-hidden="true" className="pointer-events-none absolute -bottom-36 -right-24 size-96 rounded-full border-[50px] border-white/[0.05]" />

            <div className="relative z-10 flex items-center gap-3">
              <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-white p-1.5 shadow-sm">
                <img
                  src="/usthb-logo.png"
                  alt="شعار جامعة العلوم والتكنولوجيا هواري بومدين"
                  width="100"
                  height="99"
                  className="size-full object-contain"
                />
              </span>
              <div>
                <p dir="ltr" className="text-base font-extrabold tracking-tight">RAG-USTHB</p>
                <p className="mt-1 text-[11px] text-white/65">جامعة العلوم والتكنولوجيا هواري بومدين</p>
              </div>
            </div>

            <div className="relative z-10 my-12">
              <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.07] px-3 py-1.5 text-[11px] font-bold text-white/85">
                <GraduationCap size={15} aria-hidden="true" />
                مساحة دراسية لطلاب الجامعة
              </span>
              <h2 className="mt-5 max-w-lg text-3xl font-extrabold leading-[1.55] xl:text-4xl">
                اجعل وقت المراجعة أكثر تركيزاً ووضوحاً.
              </h2>
              <p className="mt-4 max-w-md text-sm leading-7 text-white/70">
                اكتشف محتوى المقررات، راجع المفاهيم الأساسية، وتنقّل بين إجابات مدعومة بمراجع دراسية.
              </p>
            </div>

            <div className="relative z-10 rounded-2xl border border-white/15 bg-white/[0.07] p-4">
              <p className="text-xs font-extrabold text-white/90">مصادر أكاديمية في مكان واحد</p>
              <div className="mt-4 flex flex-col gap-3">
                <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2.5">
                  <FileText size={16} className="shrink-0 text-white/80" aria-hidden="true" />
                  <span className="text-xs text-white/75">محاضرات ومناهج رسمية</span>
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2.5">
                  <BookOpen size={16} className="shrink-0 text-white/80" aria-hidden="true" />
                  <span className="text-xs text-white/75">مراجعة منظمة حسب المادة</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <footer className="relative mt-5 text-center text-[10px] leading-5 text-[#243247]/50 lg:mt-0">
        <span className="inline-flex items-center gap-1.5">
          <GraduationCap size={13} aria-hidden="true" />
          تعليم جامعي، بلغة أقرب إليك
        </span>
      </footer>
    </main>
  )
}
