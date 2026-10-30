/**
 * Single source of truth for the frontend's page routes.
 *
 * The app used to switch screens with local `useState`; routing is now handled
 * by the Next.js App Router so every screen has a real URL that survives a
 * browser refresh and can be shared.
 */
export const ROUTES = {
  home: '/',
  login: '/login',
  register: '/register',
  chat: '/chat',
  profile: '/profile',
}

export const AUTH_PAGES = new Set(['login', 'register'])

/** Routes that require a signed-in student; anything else is public. */
export const PROTECTED_ROUTES = new Set(['chat', 'profile'])

export function routeFor(page) {
  return ROUTES[page] ?? ROUTES.home
}
