'use client'

import { RagRegister } from '../rag-auth'
import { RedirectIfAuthenticated } from '../auth-provider'

/**
 * Sign-up page — `/register`.
 *
 * Registration never signs the student in: on success the form navigates to
 * `/login`, which is why a signed-in visitor is bounced away from here too.
 */
export default function RegisterPage() {
  return (
    <RedirectIfAuthenticated>
      <RagRegister />
    </RedirectIfAuthenticated>
  )
}
