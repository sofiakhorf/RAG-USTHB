'use client'

/**
 * The chatbot — `/chat`.
 *
 * Route-guarded by `RequireAuth`, so a signed-out student is redirected to
 * `/login` (carrying this path) no matter how the URL was reached: typed
 * directly, reloaded, or replayed.
 *
 * Everything on this page is live backend data. The previous version rendered a
 * mock subject tree with sample questions; that is gone, along with the PDF
 * upload controls, the document dialog and the preview badges. What remains is
 * the product: ask a question, get the retrieved passages, keep the thread.
 */

import { useEffect, useState } from 'react'
import { LogOut, Menu, UserRound } from 'lucide-react'
import { RagChatFeed } from '../rag-chat-feed'
import { RagComposer } from '../rag-composer'
import { RagSidebar } from '../rag-sidebar'
import { RequireAuth, useAuth } from '../auth-provider'
import { useChatManager } from '../useChatManager'
import { useAppNavigation } from '../useAppNavigation'
import { useLang } from '../rag-lang-provider'
import { ROUTES } from '@/lib/routes'

function ChatScreen() {
  const { t } = useLang()
  const navigate = useAppNavigation()
  const { user, logout } = useAuth()

  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false)
  const [draft, setDraft] = useState('')
  // Confirmation is a plain in-page dialog rather than `window.confirm`: the
  // native one is not translatable, cannot be styled for dark mode, and blocks
  // the event loop behind it.
  const [pendingDeleteId, setPendingDeleteId] = useState(null)

  const {
    sessions,
    activeSessionId,
    messages,
    isLoadingSessions,
    isLoadingMessages,
    isSending,
    sessionsError,
    messagesError,
    sendError,
    loadSessions,
    openSession,
    resetThread,
    createConversation,
    removeConversation,
    sendMessage,
    retrySend,
  } = useChatManager()

  // Sign-out tears the provider down while a composer draft may still be
  // mounted; drop it so nothing leaks into the next student's session.
  useEffect(() => {
    return () => setDraft('')
  }, [])

  async function handleLogout() {
    try {
      await logout()
    } finally {
      // Always leave, even if the logout request failed: the guard would send
      // the student back here otherwise, on a stale local view.
      navigate('home')
    }
  }

  async function confirmDelete() {
    const sessionId = pendingDeleteId
    setPendingDeleteId(null)
    if (sessionId) await removeConversation(sessionId)
  }

  return (
    <main className="flex h-dvh min-h-dvh overflow-hidden bg-background text-foreground">
      <RagSidebar
        conversations={sessions}
        activeConversationId={activeSessionId}
        onSelectConversation={openSession}
        onNewConversation={() => {
          resetThread()
          setDraft('')
        }}
        onDeleteConversation={setPendingDeleteId}
        isLoading={isLoadingSessions}
        error={sessionsError}
        onRetry={loadSessions}
        isMobileOpen={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
        user={user}
        onOpenProfile={() => navigate('profile')}
        onLogout={handleLogout}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-[76px] items-center gap-2 border-b border-border bg-card px-4">
          <button
            type="button"
            aria-label={t.chat.menuButton}
            onClick={() => setIsMobileSidebarOpen(true)}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring lg:hidden"
          >
            <Menu size={19} aria-hidden="true" />
          </button>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-bold text-deep-blue">
              {activeSessionId
                ? sessions.find((item) => item.id === activeSessionId)?.title || t.sidebar.untitled
                : t.chat.emptyTitle}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {user?.fullName} · {user?.departmentLabel ?? user?.department}
            </p>
          </div>

          <button
            type="button"
            onClick={() => navigate('profile')}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-link/35 bg-secondary/60 px-3 text-xs font-bold text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            <UserRound size={15} aria-hidden="true" />
            <span className="hidden sm:inline">{t.chat.profileButton}</span>
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border px-3 text-xs font-bold text-foreground transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            <LogOut size={15} aria-hidden="true" />
            <span className="hidden sm:inline">{t.chat.logoutButton}</span>
          </button>
        </header>

        <div className="min-h-0 flex-1">
          <RagChatFeed
            conversationId={activeSessionId}
            messages={messages}
            isLoadingMessages={isLoadingMessages}
            isSending={isSending}
            sendError={sendError}
            onRetry={retrySend}
          />
        </div>

        <footer className="border-t border-border bg-card px-4 pb-[calc(env(safe-area-inset-bottom)+12px)] pt-3">
          {/* A conversation that failed to open is still the active one; asking
              into it would 404 again, so the composer is held until the list
              decides where the question should go. */}
          <RagComposer
            value={draft}
            onChange={setDraft}
            onSubmit={async () => {
              const sent = await sendMessage(draft)
              if (sent) setDraft('')
            }}
            isSending={isSending}
            disabled={isLoadingMessages}
            error={messagesError ? t.chat.errorNetwork : null}
          />
        </footer>
      </section>

      {pendingDeleteId && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-conversation-title"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 px-4"
          onClick={() => setPendingDeleteId(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 shadow-[0_28px_90px_-40px_rgba(0,0,0,0.6)]"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-conversation-title" className="text-sm font-bold text-foreground">
              {t.chat.deleteConversation}
            </h2>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">{t.chat.deleteConfirm}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPendingDeleteId(null)}
                className="inline-flex min-h-10 items-center justify-center rounded-xl border border-border px-4 text-xs font-bold text-foreground transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              >
                {t.common.cancel}
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="inline-flex min-h-10 items-center justify-center rounded-xl bg-destructive px-4 text-xs font-bold text-destructive-foreground transition hover:bg-destructive/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                {t.common.delete}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Skip link target: lets a keyboard user jump past the sidebar straight
          to the question box. */}
      <a href="#chat-composer" className="sr-only">
        {t.chat.composerLabel}
      </a>
    </main>
  )
}

/** `/chat` */
export default function ChatPage() {
  return (
    <RequireAuth>
      <ChatScreen />
    </RequireAuth>
  )
}
