import './globals.css'
import { cookies } from 'next/headers'
import { Inter, Noto_Sans_Arabic } from 'next/font/google'
import { RagThemeProvider } from './rag-theme-provider'

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
  const initialTheme = cookieStore.get('rag-theme')?.value === 'dark' ? 'dark' : 'light'

  const currentLang = cookieStore.get('rag-lang')?.value || 'en'
  const isRtl = currentLang === 'ar'
  
  return (
  <html lang={currentLang} dir={isRtl ? 'rtl' : 'ltr'} className={initialTheme === 'dark' ? 'dark' : undefined}>
      <body className={`${interFont.variable} ${arabicFont.variable} min-h-dvh bg-background text-foreground antialiased font-sans`}>
        <RagThemeProvider initialTheme={initialTheme}>{children}</RagThemeProvider>
      </body>
    </html>
  )
}
