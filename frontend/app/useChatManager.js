'use client'

/**
 * Chat state for `/chat`, backed by the Django conversation API.
 *
 * Everything here is real: the conversation list comes from
 * `GET /api/chat/sessions/`, opening one fetches its transcript, and asking a
 * question POSTs it and stores the RAG answer with its citations. Nothing is
 * held only in the browser - a reload, or logging out and back in, restores the
 * same history, because the server owns it.
 *
 * Optimistic question
 * -------------------
 * The student's question appears the instant they press Send; the server's copy
 * replaces it when the response lands. That removes a visible round trip while
 * keeping the server authoritative - if the request fails, the optimistic copy
 * is rolled back so the transcript never shows a question that was not saved.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as chatService from '@/services/chatService'

export function useChatManager() {
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])

  const [isLoadingSessions, setIsLoadingSessions] = useState(true)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [isSending, setIsSending] = useState(false)

  const [sessionsError, setSessionsError] = useState(false)
  const [messagesError, setMessagesError] = useState(null)
  const [sendError, setSendError] = useState(null)

  // The question currently in flight, so a retry resends the same text.
  const pendingQuestionRef = useRef(null)
  // Guards against setState after the student logs out (which unmounts this).
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  /* -------------------------------------------------------------- loading */

  const loadSessions = useCallback(async () => {
    setIsLoadingSessions(true)
    setSessionsError(false)

    try {
      const list = await chatService.listSessions()
      if (mountedRef.current) setSessions(list)
      return list
    } catch {
      if (mountedRef.current) setSessionsError(true)
      return []
    } finally {
      if (mountedRef.current) setIsLoadingSessions(false)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  const openSession = useCallback(async (sessionId) => {
    if (!sessionId) {
      setActiveSessionId(null)
      setMessages([])
      setMessagesError(null)
      setSendError(null)
      return
    }

    setActiveSessionId(sessionId)
    setIsLoadingMessages(true)
    setMessagesError(null)
    setSendError(null)

    try {
      const { messages: transcript } = await chatService.getSession(sessionId)
      if (!mountedRef.current) return
      setMessages(transcript)
    } catch (error) {
      if (!mountedRef.current) return
      // A 404 here means the conversation is not this student's (or no longer
      // exists); either way the list is refreshed so the sidebar stops
      // offering something that cannot be opened.
      setMessagesError(error)
      setMessages([])
      loadSessions()
    } finally {
      if (mountedRef.current) setIsLoadingMessages(false)
    }
  }, [loadSessions])

  /** Collapse a thread back to the empty state without touching the server. */
  const resetThread = useCallback(() => {
    setActiveSessionId(null)
    setMessages([])
    setMessagesError(null)
    setSendError(null)
  }, [])

  /* ------------------------------------------------------------ mutations */

  const createConversation = useCallback(async () => {
    setSessionsError(false)

    try {
      const session = await chatService.createSession()
      if (!mountedRef.current) return session

      setSessions((current) => [session, ...current])
      setActiveSessionId(session.id)
      setMessages([])
      setMessagesError(null)
      setSendError(null)
      return session
    } catch (error) {
      if (mountedRef.current) {
        setSessionsError(true)
        setMessagesError(error)
      }
      return null
    }
  }, [])

  const removeConversation = useCallback(
    async (sessionId) => {
      setSessionsError(false)

      try {
        await chatService.removeSession(sessionId)
      } catch {
        // A 404 means it was already gone (deleted in another tab, or not
        // ours); treat it as removed locally rather than raising an error the
        // student cannot act on.
        if (!mountedRef.current) return true
      }

      if (!mountedRef.current) return true

      setSessions((current) => current.filter((item) => item.id !== sessionId))

      if (activeSessionId === sessionId) resetThread()

      return true
    },
    [activeSessionId, resetThread],
  )

  /* --------------------------------------------------------------- asking */

  const sendMessage = useCallback(
    async (text) => {
      const question = String(text ?? '').trim()
      if (!question || isSending) return false

      setIsSending(true)
      setSendError(null)
      pendingQuestionRef.current = question

      try {
        // Asking from the empty state has no conversation yet; create one so
        // the question is never orphaned outside a thread.
        let sessionId = activeSessionId

        if (!sessionId) {
          const created = await chatService.createSession()
          if (!created) return false

          sessionId = created.id
          if (mountedRef.current) {
            setSessions((current) => [created, ...current])
            setActiveSessionId(created.id)
          }
        }

        const optimisticId = `optimistic-${Date.now()}`
        if (mountedRef.current) {
          setMessages((current) => [
            ...current,
            { id: optimisticId, role: 'user', content: question, sources: [] },
          ])
        }

        const result = await chatService.sendMessage(sessionId, question)
        if (!mountedRef.current) return true

        setMessages((current) => [
          // Drop the optimistic copy; the server's message carries a real id
          // and the real timestamp.
          ...current.filter((message) => message.id !== optimisticId),
          result.questionMessage,
          result.answerMessage,
        ].filter(Boolean))

        // Mirror the backend's title promotion (it names an untitled thread
        // after its first question) and bubble the thread to the top of the
        // sidebar, without a second round trip.
        setSessions((current) => {
          const next = current.map((item) =>
            item.id === sessionId
              ? {
                  ...item,
                  title: item.title && item.title !== 'New conversation'
                    ? item.title
                    : question.slice(0, 255),
                  messageCount: (item.messageCount ?? 0) + 2,
                }
              : item,
          )
          const active = next.find((item) => item.id === sessionId)
          return active ? [active, ...next.filter((item) => item.id !== sessionId)] : next
        })

        return true
      } catch (error) {
        if (!mountedRef.current) return false

        // Roll the optimistic copy back: the server did not save it, so the
        // transcript must not claim it did.
        setMessages((current) =>
          current.filter((message) => !String(message.id).startsWith('optimistic-')),
        )
        setSendError(error)
        return false
      } finally {
        pendingQuestionRef.current = null
        if (mountedRef.current) setIsSending(false)
      }
    },
    [activeSessionId, isSending],
  )

  const retrySend = useCallback(() => {
    const question = pendingQuestionRef.current
    if (!question) return Promise.resolve(false)
    // Clear first so `sendMessage` is not blocked by the guard below, which
    // still sees `isSending` as false only because the request has settled.
    return sendMessage(question)
  }, [sendMessage])

  return {
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
  }
}
