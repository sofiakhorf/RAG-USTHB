'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/utils'
import { THEME_COOKIE } from '@/lib/theme'
import { useLang } from './rag-lang-provider'

const RagThemeContext = createContext(null)

function writeThemeCookie(theme) {
  if (typeof document === 'undefined') return
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${THEME_COOKIE}=${theme}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`
}

/**
 * Global light/dark mode.
 *
 * The server layout already rendered `<html class="dark">` from the cookie, so
 * there is no flash on load; this provider only owns the state afterwards and
 * keeps the class + cookie in sync for every page and component.
 */
export function RagThemeProvider({ children, initialTheme = 'light' }) {
  const [theme, setThemeState] = useState(initialTheme === 'dark' ? 'dark' : 'light')

  const setTheme = useCallback((next) => {
    setThemeState(next === 'dark' ? 'dark' : 'light')
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  // Persist and mirror on mount and after every change, whichever setter ran.
  // The server layout already rendered `<html class="dark">` from the cookie,
  // so this never causes a flash on load.
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    writeThemeCookie(theme)
  }, [theme])

  const value = useMemo(() => ({
    theme,
    isDark: theme === 'dark',
    setTheme,
    toggleTheme,
  }), [theme, setTheme, toggleTheme])

  return <RagThemeContext.Provider value={value}>{children}</RagThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(RagThemeContext)
  if (!context) {
    throw new Error('useTheme() must be used inside <RagThemeProvider>.')
  }
  return context
}

export function RagThemeToggle({ variant = 'default', className }) {
  const { isDark, toggleTheme } = useTheme()
  const { t } = useLang()
  const label = isDark ? t.nav.themeLight : t.nav.themeDark
  const Icon = isDark ? Sun : Moon

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={isDark}
      title={label}
      onClick={toggleTheme}
      className={cn(
        'inline-flex size-10 shrink-0 items-center justify-center rounded-xl border transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        variant === 'sidebar'
          ? 'border-sidebar-border bg-sidebar-accent text-sidebar-foreground hover:bg-sidebar-accent/70'
          : 'border-border bg-card text-deep-blue hover:bg-secondary',
        className,
      )}
    >
      <Icon size={17} aria-hidden="true" />
    </button>
  )
}
