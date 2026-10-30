'use client'

import { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { routeFor } from '@/lib/routes'

/**
 * Maps the legacy `onNavigate(page)` contract used by the existing components
 * onto real Next.js routes.
 */
export function useAppNavigation() {
  const router = useRouter()

  return useCallback((page) => {
    router.push(routeFor(page))
  }, [router])
}
