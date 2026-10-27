'use client'

import { useEffect, useRef } from 'react'
import { BookOpen, Bot, FileText, Info, Maximize2 } from 'lucide-react'

export function RagChatFeed({ conversationId, messages, documents, subject, onOpenDocument }) {
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
  }, [conversationId, messages.length])

  return (
    <div
      ref={feedRef}
      role="log"
      aria-label="سجل المحادثة"
      aria-live="polite"
      aria-relevant="additions text"
      className="app-scroll h-full min-h-0 overflow-y-auto overscroll-contain px-3 py-5 sm:px-5 sm:py-7"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
        <div className="flex justify-center">
          <div className="flex items-center gap-2 rounded-full border border-border bg-secondary px-3 py-1.5 text-[10px] font-medium text-muted-foreground/75">
            <Info size={13} className="shrink-0 text-link" aria-hidden="true" />
            <span>محادثة تجريبية · الإجابات والمصادر أمثلة محلية</span>
          </div>
        </div>

        {messages.length === 0 ? (
          <div className="mx-auto mt-8 flex max-w-md flex-col items-center rounded-2xl border border-dashed border-border bg-secondary/70 px-6 py-8 text-center">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-sidebar text-sidebar-foreground">
              <BookOpen size={22} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <h2 className="mt-4 text-base font-bold text-deep-blue">
              ابدأ جلسة جديدة في {subject.nameAr}
            </h2>
            <p className="mt-2 text-xs leading-6 text-muted-foreground/75">
              اكتب سؤالاً حول المادة في الأسفل. هذه المعاينة لا تتصل حالياً بمحرك الاسترجاع أو بقاعدة بيانات للمحادثات.
            </p>
          </div>
        ) : (
          messages.map((message) => {
            const isUser = message.role === 'user'
            const sourceIds = message.sourceIds ?? (message.citation ? [message.citation] : [])
            const sources = sourceIds
              .map((sourceId) => documents.find((document) => document.id === sourceId || document.name === sourceId))
              .filter(Boolean)

            return (
              <article
                key={message.id}
                className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                <div className={`flex min-w-0 gap-2.5 ${isUser ? 'max-w-[90%] sm:max-w-[82%]' : 'max-w-[94%] sm:max-w-[88%]'}`}>
                  {!isUser && (
                    <span
                      aria-hidden="true"
                      className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-sidebar text-sidebar-foreground"
                    >
                      <Bot size={17} strokeWidth={1.8} />
                    </span>
                  )}

                  <div className={`min-w-0 ${isUser ? 'text-left' : 'flex-1'}`}>
                    <p className={`mb-1.5 text-[10px] font-semibold text-muted-foreground/60 ${isUser ? 'text-left' : 'text-right'}`}>
                      {isUser ? 'أنت' : message.kind === 'notice' ? 'تنبيه المعاينة' : 'مساعد RAG'}
                    </p>
                    <div
                      dir="rtl"
                      className={`rounded-2xl px-4 py-3 text-[13px] leading-7 shadow-sm ${
                        isUser
                          ? 'rounded-tr-md bg-primary text-primary-foreground'
                          : message.kind === 'notice'
                            ? 'rounded-tl-md border border-link/35 bg-secondary text-foreground'
                            : 'rounded-tl-md border border-border bg-card text-foreground'
                      }`}
                    >
                      {message.kind === 'notice' && (
                        <span className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold text-link">
                          <Info size={13} aria-hidden="true" />
                          لا توجد إجابة مولّدة
                        </span>
                      )}
                      <p className="whitespace-pre-wrap">{message.text}</p>
                    </div>

                    {sources.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {sources.map((source) => (
                          <button
                            key={source.id}
                            type="button"
                            onClick={() => onOpenDocument(source)}
                            aria-label={`فتح المصدر ${source.name}`}
                            className="flex w-[196px] max-w-full items-center gap-2 rounded-xl border border-border bg-card px-2.5 py-2 text-left transition hover:border-link hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                          >
                            <FileText size={14} className="shrink-0 text-link" aria-hidden="true" />
                            <span dir="ltr" className="w-32 shrink-0 truncate text-[11px] font-semibold text-foreground">
                              {source.name}
                            </span>
                            <Maximize2 size={13} className="shrink-0 text-deep-blue" aria-hidden="true" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </article>
            )
          })
        )}
      </div>
    </div>
  )
}

