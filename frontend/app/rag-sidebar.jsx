'use client'

/**
 * The chat sidebar.
 *
 * Rewritten from the mock version it replaced: the subject tree, the attached
 * file list and the four-way advanced sort are gone, because none of them
 * described anything real - there are no "subjects" in the data model, only
 * conversations owned by the signed-in student. What is left is the one thing
 * the product actually needs: a searchable, sortable list of *this* student's
 * conversations, which the backend already scopes to them.
 */

import { useMemo, useState } from 'react'
import { BookOpen, History, Loader2, LogOut, Plus, RotateCw, Search, Trash2, UserRound, X } from 'lucide-react'
import { RagLangToggle, useLang } from './rag-lang-provider'
import { RagThemeToggle } from './rag-theme-provider'
import { interpolate } from '@/lib/i18n'
import { formatRelativeTime } from '@/services/utils'

function Note({ children, tone = 'neutral' }) {
  const toneClass =
    tone === 'error'
      ? 'border-destructive/30 bg-destructive/10 text-foreground'
      : 'border-sidebar-border bg-sidebar-accent/40 text-sidebar-foreground/70'

  return (
    <p className={`rounded-xl border px-3 py-3 text-center text-xs leading-6 ${toneClass}`}>
      {children}
    </p>
  )
}

export function RagSidebar({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  isLoading,
  error,
  onRetry,
  isMobileOpen,
  onCloseMobile,
  user,
  onOpenProfile,
  onLogout,
}) {
  const { t, locale, isRtl } = useLang()
  const [searchQuery, setSearchQuery] = useState('')
  const [sortDirection, setSortDirection] = useState('desc')

  const normalizedQuery = searchQuery.trim().toLocaleLowerCase()

  /** Conversations sorted newest-first by default, which is how they are returned. */
  const visibleConversations = useMemo(() => {
    const matched = normalizedQuery
      ? conversations.filter((conversation) =>
          (conversation.title ?? '').toLocaleLowerCase().includes(normalizedQuery),
        )
      : conversations

    if (sortDirection === 'asc') return [...matched].reverse()
    return matched
  }, [conversations, normalizedQuery, sortDirection])

  function handleSelect(conversationId) {
    if (isMobileOpen) onCloseMobile()
    onSelectConversation(conversationId)
  }

  function handleNewConversation() {
    if (isMobileOpen) onCloseMobile()
    onNewConversation()
  }

  return (
    <>
      {isMobileOpen && (
        <button
          type="button"
          aria-label={t.sidebar.closeOverlay}
          className="fixed inset-0 z-40 bg-sidebar/55 lg:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        id="study-sidebar"
        aria-label={t.sidebar.asideLabel}
        className={`fixed inset-y-0 start-0 z-50 ${isMobileOpen ? 'flex' : 'hidden'} w-[min(88vw,304px)] flex-col border-e border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform duration-200 lg:flex lg:w-[304px] ${
          isMobileOpen ? 'translate-x-0' : isRtl ? 'translate-x-full' : '-translate-x-full'
        } lg:translate-x-0`}
      >
        <div className="flex min-h-[76px] items-center gap-3 border-b border-sidebar-border px-4 py-3">
          <div aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
            <BookOpen size={23} strokeWidth={1.8} />
          </div>
          <div className="min-w-0 flex-1">
            <p dir="ltr" className="truncate text-left text-sm font-bold tracking-wide text-sidebar-foreground">RAG-USTHB</p>
            <p className="mt-0.5 truncate text-[11px] text-sidebar-foreground/70">{t.sidebar.brandTagline}</p>
          </div>
          <RagLangToggle variant="sidebar" showLabel={false} />
          <RagThemeToggle variant="sidebar" />
          <button
            type="button"
            aria-label={t.sidebar.closeMenu}
            onClick={onCloseMobile}
            className="rounded-lg p-2 text-sidebar-foreground transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring lg:hidden"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="border-b border-sidebar-border p-3">
          <button
            type="button"
            onClick={handleNewConversation}
            className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground shadow-sm transition hover:bg-sidebar-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring"
          >
            <Plus size={16} aria-hidden="true" />
            {t.sidebar.newConversation}
          </button>

          <label className="relative mt-2.5 block">
            <span className="sr-only">{t.sidebar.searchLabel}</span>
            <Search
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-link"
            />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t.sidebar.searchPlaceholder}
              className="h-10 w-full rounded-xl border border-border bg-background ps-9 pe-3 text-xs text-foreground outline-none transition placeholder:text-muted-foreground focus:border-link focus:ring-2 focus:ring-link/15"
            />
          </label>

          <button
            type="button"
            onClick={() => setSortDirection((current) => (current === 'desc' ? 'asc' : 'desc'))}
            className="mt-2 flex min-h-9 w-full items-center justify-between rounded-lg px-2 text-xs font-semibold text-sidebar-foreground/80 transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
          >
            {sortDirection === 'desc' ? t.sidebar.sortNewest : t.sidebar.sortOldest}
            <span aria-hidden="true" className="text-[10px] text-sidebar-foreground/60">⇅</span>
          </button>
        </div>

        <div className="app-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4">
          <div className="mb-3 flex items-center justify-between gap-2 px-1">
            <h2 className="text-[11px] font-bold text-sidebar-foreground/75">{t.sidebar.conversationsTitle}</h2>
            <span className="rounded-full bg-sidebar-accent px-2 py-1 text-[10px] font-semibold text-sidebar-foreground/80">
              {interpolate(t.sidebar.conversationCount, { count: conversations.length })}
            </span>
          </div>

          {isLoading ? (
            <div role="status" className="flex items-center justify-center gap-2 rounded-xl border border-sidebar-border bg-sidebar-accent/30 px-3 py-4 text-xs text-sidebar-foreground/70">
              <Loader2 size={14} className="animate-spin text-sidebar-primary" aria-hidden="true" />
              {t.sidebar.loading}
            </div>
          ) : error ? (
            <div className="flex flex-col gap-2">
              <Note tone="error">{t.sidebar.error}</Note>
              <button
                type="button"
                onClick={onRetry}
                className="flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-sidebar-border bg-sidebar-accent px-3 text-[11px] font-bold text-sidebar-foreground transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
              >
                <RotateCw size={13} aria-hidden="true" />
                {t.sidebar.retry}
              </button>
            </div>
          ) : visibleConversations.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {visibleConversations.map((conversation) => {
                const isActive = conversation.id === activeConversationId

                return (
                  <li key={conversation.id} className="group">
                    <div
                      className={`flex items-center gap-1 rounded-xl transition ${
                        isActive ? 'bg-sidebar-primary text-sidebar-primary-foreground' : 'hover:bg-sidebar-accent'
                      }`}
                    >
                      <button
                        type="button"
                        aria-current={isActive ? 'page' : undefined}
                        onClick={() => handleSelect(conversation.id)}
                        className="flex min-h-11 min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-start focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] font-medium">
                            {conversation.title || t.sidebar.untitled}
                          </span>
                          <span className={`mt-0.5 flex items-center gap-1.5 text-[10px] ${isActive ? 'text-sidebar-primary-foreground/70' : 'text-sidebar-foreground/60'}`}>
                            <History size={11} aria-hidden="true" />
                            {formatRelativeTime(conversation.updatedAtValue, locale)}
                            {conversation.messageCount > 0 && (
                              <> · {interpolate(t.sidebar.messageCount, { count: conversation.messageCount })}</>
                            )}
                          </span>
                        </span>
                      </button>

                      <button
                        type="button"
                        aria-label={t.chat.deleteConversation}
                        title={t.chat.deleteConversation}
                        onClick={() => onDeleteConversation(conversation.id)}
                        className={`flex size-8 shrink-0 items-center justify-center rounded-lg transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring ${
                          isActive
                            ? 'text-sidebar-primary-foreground/80 hover:bg-black/15'
                            : 'text-sidebar-foreground/60 opacity-0 hover:bg-destructive/15 hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100'
                        }`}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : (
            <Note>{t.sidebar.emptyConversations}</Note>
          )}
        </div>

        <div className="border-t border-sidebar-border p-3">
          <button
            type="button"
            onClick={() => {
              if (isMobileOpen) onCloseMobile()
              onOpenProfile()
            }}
            aria-label={t.nav.profile}
            className="flex min-h-11 w-full items-center gap-2.5 rounded-xl px-2.5 text-start transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
          >
            {/* An icon, not initials: the spec rules out avatars, and a plain
                glyph keeps that promise without inventing identity data the
                backend never sends. */}
            <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
              <UserRound size={17} strokeWidth={1.8} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12px] font-semibold text-sidebar-foreground">
                {user?.fullName}
              </span>
              <span dir="ltr" className="mt-0.5 block truncate text-left text-[10px] text-sidebar-foreground/65">
                {user?.email}
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={onLogout}
            className="mt-1 flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 text-[11px] font-semibold text-sidebar-foreground/80 transition hover:bg-sidebar-accent hover:text-destructive focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
          >
            <LogOut size={15} aria-hidden="true" />
            {t.nav.logout}
          </button>

          <p className="mt-2 border-t border-sidebar-border/70 px-1 pt-2 text-center text-[10px] leading-5 text-sidebar-foreground/60">
            {t.sidebar.footer}
            <span dir="ltr" className="mt-0.5 block">USTHB · Algiers</span>
          </p>
        </div>
      </aside>
    </>
  )
}
