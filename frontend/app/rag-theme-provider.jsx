'use client'

import { createContext, useContext, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/utils'

const RagThemeContext = createContext(null)

export function RagThemeProvider({ children, initialTheme = 'light' }) {
  const [theme, setTheme] = useState(initialTheme)

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme)
    document.documentElement.classList.toggle('dark', nextTheme === 'dark')

    const secure = window.location.protocol === 'https:' ? '; Secure' : ''
    document.cookie = `rag-theme=${nextTheme}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`
  }

  return (
    <RagThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </RagThemeContext.Provider>
  )
}

export function RagThemeToggle({ variant = 'default', className }) {
  const context = useContext(RagThemeContext)

  if (!context) return null

  const { theme, toggleTheme } = context
  const isDark = theme === 'dark'
  const label = isDark ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'
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
          : 'border-border bg-card text-foreground hover:bg-secondary',
        className,
      )}
    >
      <Icon size={17} aria-hidden="true" />
    </button>
  )
}
