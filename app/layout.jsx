import './globals.css'
import { cookies } from 'next/headers'
import { Noto_Sans_Arabic } from 'next/font/google'
import { RagThemeProvider } from './rag-theme-provider'

const arabicFont = Noto_Sans_Arabic({
  subsets: ['arabic', 'latin'],
  display: 'swap',
  variable: '--font-arabic',
})

export const metadata = {
  title: 'RAG-USTHB | مساعدك الأكاديمي الذكي',
  description: 'منصة عربية لطلاب جامعة العلوم والتكنولوجيا هواري بومدين، تساعد على البحث في المحاضرات وأرشيف الامتحانات والمناهج الرسمية.',
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

  return (
    <html lang="ar" dir="rtl" className={initialTheme === 'dark' ? 'dark' : undefined}>
      <body className={`${arabicFont.variable} min-h-dvh bg-background text-foreground antialiased`}>
        <RagThemeProvider initialTheme={initialTheme}>{children}</RagThemeProvider>
      </body>
    </html>
  )
}
