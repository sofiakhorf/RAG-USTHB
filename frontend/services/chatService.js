/**
 * Conversation + RAG API client.
 *
 * Mirrors the Django endpoints in `backend/chatbot/`. Every conversation is
 * owned by the signed-in student: the backend scopes every queryset by user, so
 * asking for someone else's id returns `404` rather than their messages.
 *
 * Normalisation happens here, at the network boundary, and nowhere else. The
 * API speaks snake_case (`updated_at`, `message_count`, `question_message`)
 * because that is what the Django serializers emit; the components speak
 * camelCase. Keeping the translation in one module means a component never has
 * to know which shape it is holding, and a new field is mapped in exactly one
 * place.
 *
 * Sources are stripped from the displayed answer: the backend still receives
 * and stores source metadata for provenance, but the UI never shows a "Sources"
 * section or citation references inside the answer text.
 */

import { api } from './apiClient'

export const CHAT_ENDPOINTS = {
  sessions: '/api/chat/sessions/',
  session: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/`,
  messages: (id) => `/api/chat/sessions/${encodeURIComponent(id)}/messages/`,
}

/**
 * Convert an ISO timestamp to the epoch milliseconds the UI sorts by.
 *
 * An unparseable date becomes `0` rather than `NaN`.
 */
function toEpoch(value) {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * Strip citation references [N] and reference IDs from LLM answer text.
 */
function stripCitations(text) {
  if (typeof text !== 'string') return text

  let result = text.replace(/\[\d+\]/g, '')
  result = result.replace(/ref\s+[0-9a-fA-F]{32,}/gi, '')
  result = result.replace(/reference\s+[0-9a-fA-F]{32,}/gi, '')

  return result.trim()
}

/**
 * Backend ChatSessionSerializer -> the sidebar's conversation shape.
 */
function normalizeSession(session) {
  if (!session) return null

  return {
    id: session.id,
    title: session.title ?? '',
    messageCount: session.message_count ?? 0,
    createdAt: session.created_at,
    updatedAt: session.updated_at,
    updatedAtValue: toEpoch(session.updated_at),
  }
}

/**
 * Backend ChatMessageSerializer -> one transcript entry.
 *
 * Sources are kept in the stored message for internal provenance.
 */
function normalizeMessage(message) {
  if (!message) return null

  return {
    id: message.id,
    role: message.role,
    content: message.content ?? '',
    sources: message.sources ?? [],
    contextChunks: message.context_chunks ?? [],
    createdAt: message.created_at,
    createdAtValue: toEpoch(message.created_at),
  }
}

/**
 * Rebuild the `kind` flag from a stored transcript entry.
 */
function kindOf(message) {
  return (message.sources?.length ?? 0) > 0
    ? 'extractive'
    : 'no_evidence'
}

/**
 * Every conversation belonging to the current student, most recent first.
 */
export async function listSessions() {
  const body = await api.get(CHAT_ENDPOINTS.sessions)

  return (Array.isArray(body) ? body : [])
    .map(normalizeSession)
    .filter(Boolean)
}

/**
 * Start a new, empty conversation.
 */
export async function createSession(title) {
  const body = await api.post(
    CHAT_ENDPOINTS.sessions,
    title ? { title } : {}
  )

  return normalizeSession(body)
}

/**
 * Fetch one conversation together with its transcript.
 */
export async function getSession(id) {
  const body = await api.get(CHAT_ENDPOINTS.session(id))

  return {
    session: normalizeSession(body?.session),
    messages: (body?.messages ?? [])
      .map(normalizeMessage)
      .filter(Boolean),
  }
}

/**
 * Delete one conversation. The backend cascades to its messages.
 */
export async function removeSession(id) {
  await api.delete(CHAT_ENDPOINTS.session(id))
}

/**
 * Ask a question in a conversation.
 *
 * @param {string} sessionId
 * @param {string} content The student's question.
 * @returns {Promise<{
 *   kind: 'extractive' | 'no_evidence',
 *   answer: string,
 *   sources: Array,
 *   questionMessage: object,
 *   answerMessage: object
 * }>}
 */
export async function sendMessage(sessionId, content) {
  const body = await api.post(
    CHAT_ENDPOINTS.messages(sessionId),
    { content }
  )

  const questionMessage = normalizeMessage(body?.question_message)
  const answerMessage = normalizeMessage(body?.answer_message)

  // The original content is preserved to allow Markdown rendering and citation processing.
  const cleanAnswer = body?.answer ?? ''

  return {
    // The live turn uses the kind returned by Django.
    kind: body?.kind ?? (
      answerMessage
        ? kindOf(answerMessage)
        : 'no_evidence'
    ),

    answer: cleanAnswer,

    // Sources are excluded from the display payload.
    // The backend still stores them for internal provenance.
    // Original source data remains available in the database.
    sources: [],

    questionMessage,
    answerMessage,
  }
}

export { kindOf, stripCitations }