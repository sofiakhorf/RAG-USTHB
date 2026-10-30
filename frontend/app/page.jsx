'use client'

import { RagLanding } from './rag-home'
import { useAppNavigation } from './useAppNavigation'

/** Landing page — `/` */
export default function HomePage() {
  const navigate = useAppNavigation()

  return <RagLanding onNavigate={navigate} />
}
