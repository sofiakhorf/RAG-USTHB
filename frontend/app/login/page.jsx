'use client'

import { RagLogin } from '../rag-auth'
import { RedirectIfAuthenticated } from '../auth-provider'

/**
 * Sign-in page — `/login`.
 *
 * Wrapped in `RedirectIfAuthenticated` so a student who is already signed in
 * cannot end up staring at a sign-in form they no longer need.
 */
export default function LoginPage() {
  return (
    <RedirectIfAuthenticated>
      <RagLogin />
    </RedirectIfAuthenticated>
  )
}
