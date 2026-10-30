'use client'

/**
 * The conversation transcript.
 *
 * Renders three things and nothing else: the student's questions, the backend's
 * answers, and nothing else. There is no document preview here; a citation names
 * the document and page so the student can open the original themselves, which is
 * the whole point of an extractive answer.
 *
 * Localisation of answers
 * -----------------------
 * The backend labels every answer `extractive` or `no_evidence`. When there is
 * no evidence, the stored English sentence is *replaced* by the active
 * language's wording rather than shown, so an Arabic reader is never handed an
 * English sentence. An extractive answer is shown verbatim, because it is
 * quoted source text that must not be paraphrased.
 */

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { BookOpen, Bot, ChevronDown, FileText, Loader2, RotateCw, TriangleAlert } from 'lucide-react'
import { useLang } from './rag-lang-provider'
import { interpolate } from '@/lib/i18n'

/** One cited passage. Collapsed by default so a long answer stays readable. */
function SourceCard({ source, index }) {
  const { t } = useLang()
  const [isExpanded, setIsExpanded] = useState(false)

  const label = source.citation || source.document || ''
  const excerpt = (source.excerpt ?? '').trim()

  return (
    <li className="rounded-xl border border-border bg-card px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg bg-secondary text-[10px] font-extrabold text-deep-blue">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-bold text-foreground" dir="auto">
            {label}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
            {typeof source.score === 'number' && (
              <span>{interpolate(t.chat.sourceScore, { score: source.score.toFixed(2) })}</span>
            )}
            {source.page != null && (
              <span>{interpolate(t.chat.sourcePage, { page: source.page })}</span>
            )}
            {source.reference_id && (
              <span dir="ltr" className="font-mono">
                {source.reference_id}
              </span>
            )}
          </p>
        </div>
      </div>

      {excerpt && (
        <>
          <button
            type="button"
            onClick={() => setIsExpanded((open) => !open)}
            aria-expanded={isExpanded}
            className="mt-2 inline-flex items-center gap-1 rounded-md text-[10px] font-bold text-link transition hover:text-deep-blue focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            <ChevronDown
              size={12}
              aria-hidden="true"
              className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`}
            />
            {source.document}
          </button>
          {isExpanded && (
            <p className="mt-2 whitespace-pre-wrap rounded-lg bg-secondary/70 px-2.5 py-2 text-[11px] leading-6 text-foreground/85">
              {excerpt}
            </p>
          )}
        </>
      )}
    </li>
  )
}

function ThinkingRow() {
  const { t } = useLang()

  return (
    <div className="flex justify-start" role="status" aria-live="polite">
      <div className="flex min-w-0 gap-2.5">
        <span
          aria-hidden="true"
          className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-sidebar text-sidebar-foreground"
        >
          <Bot size={17} strokeWidth={1.8} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1.5 text-[10px] font-semibold text-muted-foreground">{t.chat.roleAssistant}</p>
          <div className="inline-flex items-center gap-2 rounded-2xl rounded-tl-md border border-border bg-card px-4 py-3 text-[12px] text-muted-foreground shadow-sm">
            <Loader2 size={14} className="animate-spin text-link" aria-hidden="true" />
            {t.chat.thinking}
          </div>
        </div>
      </div>
    </div>
  )
}

export function RagChatFeed({
  conversationId,
  messages,
  isLoadingMessages,
  isSending,
  sendError,
  onRetry,
}) {
  const { t } = useLang()
  const feedRef = useRef(null)

  useEffect(() => {
    const feed = feedRef.current
    if (!feed) return undefined

    let cancelled = false
    const scrollToLatest = () => {
      if (!cancelled) feed.scrollTop = feed.scrollHeight
    }
    const frame = requestAnimationFrame(scrollToLatest)
    document.fonts?.ready.then(scrollToLatest)

    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
    }
  }, [conversationId, messages.length, isSending, isLoadingMessages])

  return (
    <div
      ref={feedRef}
      role="log"
      aria-label={t.chat.feedLabel}
      aria-live="polite"
      aria-relevant="additions text"
      className="app-scroll h-full min-h-0 overflow-y-auto overscroll-contain px-3 py-5 sm:px-5 sm:py-7"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
        {isLoadingMessages ? (
          <div
            role="status"
            className="mx-auto mt-8 inline-flex items-center gap-2 rounded-full border border-bg-secondary px-3 py-1.5 text-[11px] text-muted-foreground"
          >
            <Loader2 size={14} className="animate-spin text-link" aria-hidden="true" />
            {t.chat.thinking}
          </div>
        ) : messages.length === 0 ? (
          <div className="mx-auto mt-8 flex max-w-md flex-col items-center rounded-2xl border border-dashed border-border bg-secondary/70 px-6 py-8 text-center">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-sidebar text-sidebar-foreground">
              <BookOpen size={22} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <h2 className="mt-4 text-base font-bold text-deep-blue">{t.chat.emptyTitle}</h2>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">{t.chat.emptyText}</p>
          </div>
        ) : (
          messages.map((message) => {
            const isUser = message.role === 'user'
            const sources = message.sources ?? []
            // A stored assistant message with no citations is the backend's
            // "no evidence" reply; re-render it in the active language.
            const hasNoEvidence = !isUser && sources.length === 0

            return (
              <article key={message.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`flex min-w-0 gap-2.5 ${
                    isUser ? 'max-w-[90%] sm:max-w-[82%]' : 'max-w-[96%] sm:max-w-[92%]'
                  }`}
                >
                  {!isUser && (
                    <span
                      aria-hidden="true"
                      className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-sidebar text-sidebar-foreground"
                    >
                      <Bot size={17} strokeWidth={1.8} />
                    </span>
                  )}

                  <div className={`min-w-0 ${isUser ? 'text-end' : 'flex-1'}`}>
                    <p
                      className={`mb-1.5 text-[10px] font-semibold text-muted-foreground ${
                        isUser ? 'text-end' : 'text-start'
                      }`}
                    >
                      {isUser ? t.chat.roleUser : t.chat.roleAssistant}
                    </p>

                    <div
                      className={`prose-rag break-words rounded-2xl px-4 py-3 shadow-sm ${
                        isUser
                          ? 'rounded-tr-md bg-primary text-primary-foreground'
                          : hasNoEvidence
                            ? 'rounded-tl-md border border-link/35 bg-secondary text-foreground'
                            : 'rounded-tl-md border border-border bg-card text-foreground'
                      }`}
                      dir="auto"
                    >
                      {hasNoEvidence ? (
                        t.chat.noEvidence
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      )}
                    </div>
                    {!isUser && sources.length > 0 && (
                      <ul className="mt-3 flex flex-col gap-2">
                        {sources.map((source, idx) => (
                          <SourceCard key={idx} source={source} index={idx + 1} />
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </article>
            )
          })
        )}

        {isSending && <ThinkingRow />}

        {sendError && !isSending && (
          <div
            role="alert"
            className="mx-auto flex w-full max-w-3xl flex-col gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="inline-flex min-w-0 items-start gap-2 text-xs leading-6 text-foreground">
              <TriangleAlert size={15} className="mt-1 shrink-0 text-destructive" aria-hidden="true" />
              <span className="min-w-0 break-words">
                {sendError.code === 'network' ? t.chat.errorNetwork : t.chat.errorMessage}
              </span>
            </span>
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[11px] font-bold text-deep-blue transition hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            >
              <RotateCw size={13} aria-hidden="true" />
              {t.chat.retry}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}