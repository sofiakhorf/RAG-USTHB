/**
 * Cookie that stores the chosen colour theme.
 *
 * Lives in a plain module (not in the `'use client'` theme provider) because
 * the root layout — a Server Component — reads it with `cookies()`. Values
 * exported from client modules become client references there, so the lookup
 * would silently miss.
 */
export const THEME_COOKIE = 'rag-theme'
