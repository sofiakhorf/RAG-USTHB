'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Languages } from 'lucide-react'
import {
  DEFAULT_LANGUAGE,
  getDictionary,
  isSupportedLanguage,
  LANG_COOKIE,
  LOCALE_BY_LANGUAGE,
  SUPPORTED_LANGUAGES,
} from '@/lib/i18n'

const RagLangContext = createContext(null)

function writeLangCookie(language) {
  if (typeof document === 'undefined') return
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${LANG_COOKIE}=${language}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`
}

/**
 * Provides the active language, its dictionary and the document direction.
 *
 * `initialLang` comes from the server layout (which reads the cookie), so the
 * server-rendered markup and the first client render agree and nothing flashes
 * in the wrong direction. Switching language updates the `<html>` attributes,
 * persists the cookie and re-renders every consumer.
 */
/** Mirror the active language onto `<html lang dir>`. */
function applyDocumentLang(language) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.lang = language
  root.dir = language === 'ar' ? 'rtl' : 'ltr'
}

export function RagLangProvider({ children, initialLang = DEFAULT_LANGUAGE }) {
  const [lang, setLangState] = useState(() => (
    isSupportedLanguage(initialLang) ? initialLang : DEFAULT_LANGUAGE
  ))

  const setLang = useCallback((next) => {
    setLangState(isSupportedLanguage(next) ? next : DEFAULT_LANGUAGE)
  }, [])

  const toggleLang = useCallback(() => {
    setLangState((current) => (current === 'en' ? 'ar' : 'en'))
  }, [])

  // Persist and mirror on mount and after every change, whichever setter ran.
  useEffect(() => {
    applyDocumentLang(lang)
    writeLangCookie(lang)
  }, [lang])

  const value = useMemo(() => {
    const isRtl = lang === 'ar'
    return {
      lang,
      /** Active translation dictionary. */
      t: getDictionary(lang),
      isRtl,
      /** CSS logical start edge, so callers can place icons without hard-coding sides. */
      start: isRtl ? 'right' : 'left',
      end: isRtl ? 'left' : 'right',
      setLang,
      toggleLang,
      locale: LOCALE_BY_LANGUAGE[lang],
      languages: SUPPORTED_LANGUAGES,
    }
  }, [lang, setLang, toggleLang])

  return <RagLangContext.Provider value={value}>{children}</RagLangContext.Provider>
}

export function useLang() {
  const context = useContext(RagLangContext)
  if (!context) {
    throw new Error('useLang() must be used inside <RagLangProvider>.')
  }
  return context
}

/**
 * Language switch button. Renders the *other* language's name so the control
 * always advertises what pressing it will do.
 */
export function RagLangToggle({ variant = 'default', showLabel = true, className }) {
  const { t, lang, toggleLang } = useLang()
  const nextLanguage = lang === 'en' ? 'ar' : 'en'
  const isSidebar = variant === 'sidebar'

  return (
    <button
      type="button"
      lang={nextLanguage}
      onClick={toggleLang}
      aria-label={`${t.common.language}: ${t.nav.langLabel}`}
      title={t.nav.langLabel}
      className={[
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border transition',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        showLabel ? 'min-h-10 px-3 text-xs font-bold' : 'size-10',
        isSidebar
          ? 'border-sidebar-border bg-sidebar-accent text-sidebar-foreground hover:bg-sidebar-accent/70'
          : 'border-border bg-card text-deep-blue hover:bg-secondary',
        className ?? '',
      ].join(' ')}
    >
      <Languages size={showLabel ? 15 : 17} aria-hidden="true" />
      {showLabel && t.nav.langToggle}
    </button>
  )
}
