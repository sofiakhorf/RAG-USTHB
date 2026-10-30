'use client'

import { Paperclip, Send, TriangleAlert } from 'lucide-react'
import { useLang } from './rag-lang-provider'
import { interpolate } from '@/lib/i18n'

/**
 * The question box.
 *
 * Deliberately minimal: a text field and a Send button. The file-upload
 * controls that used to live here were removed when the product was narrowed to
 * "ask the indexed corpus a question" - ingestion happens on the backend, not
 * through the chat, so offering an upload here would imply the file could be
 * retrieved, which it cannot.
 */
export function RagComposer({
  value,
  onChange,
  onSubmit,
  isSending,
  disabled = false,
  error,
}) {
  const { t, isRtl } = useLang()
  const isBlank = value.trim().length === 0

  function handleKeyDown(event) {
    // Enter sends; Shift+Enter inserts a newline. `isComposing` (and the
    // legacy `keyCode` guard) stop this firing mid-IME, which matters for
    // Arabic input methods that compose before committing.
    if (
      event.key === 'Enter' &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing &&
      event.keyCode !== 229
    ) {
      event.preventDefault()
      if (!isBlank && !disabled) event.currentTarget.form.requestSubmit()
    }
  }

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        if (!isBlank && !disabled) onSubmit()
      }}
      className="mx-auto flex w-full max-w-3xl flex-col gap-2"
    >
      <div
        className={`flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm transition focus-within:ring-2 ${
          error
            ? 'border-destructive focus-within:border-destructive focus-within:ring-destructive/10'
            : 'border-border focus-within:border-link/40 focus-within:ring-link/10'
        }`}
      >
        <label htmlFor="chat-composer" className="sr-only">
          {t.chat.composerLabel}
        </label>
        <textarea
          id="chat-composer"
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t.chat.composerPlaceholder}
          disabled={disabled}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? 'chat-composer-error' : undefined}
          className="app-scroll max-h-40 min-h-11 w-full resize-none bg-transparent px-2.5 py-2.5 text-[13px] leading-6 text-foreground outline-none placeholder:text-foreground/50 disabled:opacity-60"
        />

        <button
          type="submit"
          aria-label={t.chat.sendLabel}
          title={t.chat.sendLabel}
          disabled={isBlank || isSending}
          className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm transition hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-45"
        >
          {isSending ? (
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
              className="size-4 animate-spin"
            >
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M22 12a10 10 0 0 0-10-10" strokeLinecap="round" />
            </svg>
          ) : (
            <Send size={16} className={isRtl ? 'rotate-180' : ''} aria-hidden="true" />
          )}
        </button>
      </div>

      {error ? (
        <p
          id="chat-composer-error"
          role="alert"
          className="flex items-start gap-1.5 text-[11px] font-semibold leading-5 text-destructive"
        >
          <TriangleAlert size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
      ) : (
        <p className="text-center text-[11px] leading-5 text-muted-foreground">
          {t.chat.composerHint}
        </p>
      )}
    </form>
  )
}
