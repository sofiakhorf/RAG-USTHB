import './globals.css'
import { cookies, headers } from 'next/headers'
import { Inter, Noto_Sans_Arabic } from 'next/font/google'
import { RagLangProvider } from './rag-lang-provider'
import { RagThemeProvider } from './rag-theme-provider'
import { RagAuthProvider } from './auth-provider'
import { LANG_COOKIE, resolveInitialLanguage } from '@/lib/i18n'
import { THEME_COOKIE } from '@/lib/theme'

const arabicFont = Noto_Sans_Arabic({
  subsets: ['arabic', 'latin'],
  display: 'swap',
  variable: '--font-arabic',
})

const interFont = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-sans',
})

export const metadata = {
  title: 'RAG-USTHB | Smart Academic AI Assistant',
  description: 'An AI-powered academic platform for USTHB students to search lectures, exam archives, and official syllabi with multi-language support.',
}

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { color: '#F5F9FD', media: '(prefers-color-scheme: light)' },
    { color: '#081625', media: '(prefers-color-scheme: dark)' },
  ],
  colorScheme: 'light dark',
}

export default async function RootLayout({ children }) {
  const cookieStore = await cookies()
  const headerStore = await headers()

  // Both preferences are resolved on the server and written straight onto
  // <html>, so the very first paint already has the right theme, `lang` and
  // `dir` — no flash and no hydration mismatch.
  const initialTheme = cookieStore.get(THEME_COOKIE)?.value === 'dark' ? 'dark' : 'light'
  const initialLang = resolveInitialLanguage(
    cookieStore.get(LANG_COOKIE)?.value,
    headerStore.get('accept-language'),
  )
  const isRtl = initialLang === 'ar'

  return (
    <html
      lang={initialLang}
      dir={isRtl ? 'rtl' : 'ltr'}
      className={initialTheme === 'dark' ? 'dark' : undefined}
    >
      <body className={`${interFont.variable} ${arabicFont.variable} min-h-dvh bg-background text-foreground antialiased`}>
        <RagLangProvider initialLang={initialLang}>
          <RagThemeProvider initialTheme={initialTheme}>
            {/* Innermost, so the session screens can use the active language
                and theme. It performs one `GET /api/auth/me/` on mount, which
                is what every protected page's guard reads from. */}
            <RagAuthProvider>{children}</RagAuthProvider>
          </RagThemeProvider>
        </RagLangProvider>
      </body>
    </html>
  )
}
