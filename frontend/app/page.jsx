'use client'

import { useState } from 'react'
import { Home as HomeIcon, Menu, X } from 'lucide-react'
import { RagAuth } from './rag-auth'
import { RagChatFeed } from './rag-chat-feed'
import { RagLanding } from './rag-home'
import { RagComposer } from './rag-composer'
import { RagDocumentDialog } from './rag-document-dialog'
import { RagSidebar } from './rag-sidebar'

import {
  subjects,
  initialDocuments,
  initialConversations,
  initialMessagesByConversation,
} from './mock-data'

function createId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function Home() {
  const [currentView, setCurrentView] = useState('home')
  const [authMode, setAuthMode] = useState('login')
  const [input, setInput] = useState('')
  const [documents, setDocuments] = useState(initialDocuments)
  const [conversations, setConversations] = useState(initialConversations)
  const [activeConversationId, setActiveConversationId] = useState('binary-search')
  const [messagesByConversation, setMessagesByConversation] = useState(initialMessagesByConversation)
  const [selectedDocument, setSelectedDocument] = useState(null)
  const [uploadNotice, setUploadNotice] = useState('')
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false)

  const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId) ?? conversations[0]
  const activeSubject = subjects.find((subject) => subject.id === activeConversation?.subjectId) ?? subjects[0]
  const activeMessages = messagesByConversation[activeConversation?.id] ?? []

  function handleViewNavigation(view, mode = 'login') {
    if (view === 'auth') setAuthMode(mode)
    setCurrentView(view)
  }

function handleSelectSubject(subjectId) {
    const existingConversation = conversations.find((conversation) => conversation.subjectId === subjectId)

    if (existingConversation) {
      setActiveConversationId(existingConversation.id)
    } else {
      const subject = subjects.find((item) => item.id === subjectId)
      const id = createId('conversation')
      const newConversation = {
        id,
        title: `New Chat · ${subject.nameEn}`,
        updatedAt: 'Just now',
        subjectId,
      }

      setConversations((current) => [newConversation, ...current])
      setMessagesByConversation((current) => ({ ...current, [id]: [] }))
      setActiveConversationId(id)
    }

    setIsMobileSidebarOpen(false)
  }

  function handleSelectConversation(conversationId) {
    setActiveConversationId(conversationId)
    setIsMobileSidebarOpen(false)
  }

  function handleQuestionSubmit(event) {
    event.preventDefault()
    const text = input.trim()

    if (!text || !activeConversation) return

    const userMessageId = createId('user')
    const assistantMessageId = createId('notice')
    const userMessage = { id: userMessageId, role: 'user', text }
// TODO: [Backend Integration] Replace this local mock notice with actual RAG API call (e.g., fetch('/api/chat', ...))
    const assistantNotice = {
      id: assistantMessageId,
      role: 'assistant',
      kind: 'notice',
      text: 'Your query has been added to local preview mode. The retrieval engine is currently offline, so no new response or citation was generated.',
    }

    setMessagesByConversation((current) => ({
      ...current,
      [activeConversation.id]: [...(current[activeConversation.id] ?? []), userMessage, assistantNotice],
    }))
    setConversations((current) => current.map((conversation) => (
      conversation.id === activeConversation.id
        ? {
            ...conversation,
            title: conversation.title.startsWith('New Chat') ? text.slice(0, 42) : conversation.title,
            updatedAt: 'Just now',
            updatedAtValue: Date.now(),
          }
        : conversation
    )))
    setInput('')
  }

  function handleFilesSelected(files) {
    const allowedExtensions = new Set(['pdf', 'doc', 'docx', 'txt', 'md'])
    const maxFileSize = 10 * 1024 * 1024
    const accepted = []
    const errors = []

    files.forEach((file, index) => {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? ''

      if (!allowedExtensions.has(extension)) {
        errors.push(`${file.name}: نوع الملف غير مدعوم`)
        return
      }

      if (file.size > maxFileSize) {
        errors.push(`${file.name}: الحد الأقصى للحجم 10 MB`)
        return
      }

      accepted.push({
        id: createId(`upload-${index}`),
        subjectId: activeSubject?.id ?? subjects[0].id,
        updatedAtValue: Date.now(),
        name: file.name,
        fileType: extension.toUpperCase(),
        sizeLabel: formatFileSize(file.size),
        description: 'مرفق محلي للمعاينة الحالية فقط.',
        source: 'upload',
        extension,
        file,
      })
    })

    if (accepted.length > 0) {
      setDocuments((current) => [...accepted, ...current])
    }

    const acceptedMessage = accepted.length > 0
      ? `تمت إضافة ${accepted.length} ملف/ملفات إلى هذه الجلسة فقط؛ لم يتم رفعها إلى خادم.`
      : ''
    setUploadNotice([acceptedMessage, ...errors].filter(Boolean).join(' · '))
  }

  async function handleOpenDocument(document) {
    setIsMobileSidebarOpen(false)

    if (document.source !== 'upload' || !document.file) {
      setSelectedDocument(document)
      return
    }

    if (document.extension === 'pdf') {
      setSelectedDocument({ ...document, previewUrl: URL.createObjectURL(document.file) })
      return
    }

    if (document.extension === 'txt' || document.extension === 'md') {
      try {
        const previewText = await document.file.text()
        setSelectedDocument({
          ...document,
          previewText: previewText.slice(0, 24000),
          previewTruncated: previewText.length > 24000,
        })
      } catch {
        setSelectedDocument({ ...document, previewText: '', previewError: true })
      }
      return
    }

    setSelectedDocument(document)
  }

  if (currentView === 'home') {
    return <RagLanding onNavigate={handleViewNavigation} />
  }

  if (currentView === 'auth') {
    return (
      <RagAuth
        initialMode={authMode}
        onNavigate={handleViewNavigation}
        onOpenDemo={() => setCurrentView('chat')}
      />
    )
  }

  return (
    <main dir="ltr" className="flex h-dvh min-h-dvh overflow-hidden bg-[#F4F7FB] text-[#243247]">
      <RagSidebar
        subjects={subjects}
        conversations={conversations}
        documents={documents}
        activeSubjectId={activeSubject?.id}
        activeConversationId={activeConversation?.id}
        onSelectSubject={handleSelectSubject}
        onSelectConversation={handleSelectConversation}
        onOpenDocument={handleOpenDocument}
        isMobileOpen={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
      />

      <section aria-labelledby="chat-heading" className="flex h-dvh min-w-0 flex-1 flex-col overflow-hidden bg-[#F4F7FB] lg:ml-[272px]">
        <header className="flex h-[70px] shrink-0 items-center justify-between gap-3 border-b border-[#C9D7E8] bg-[#FFFFFF] px-3 sm:px-5">
          <button
            type="button"
            aria-label="Open sidebar menu"
            aria-controls="study-sidebar"
            aria-expanded={isMobileSidebarOpen}
            onClick={() => setIsMobileSidebarOpen(true)}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl text-[#0B2D5C] transition hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0] lg:hidden"
          >
            <Menu size={20} aria-hidden="true" />
          </button>

          <div className="min-w-0 flex-1 text-center">
            <h1 id="chat-heading" className="truncate text-sm font-bold text-[#0B2D5C]">
              {activeSubject.nameEn}
            </h1>
            <p className="mt-0.5 truncate text-[11px] text-[#243247]/65">
              Academic Chat Session
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden rounded-full border border-[#C9D7E8] bg-[#EAF2FF] px-2.5 py-1 text-[10px] font-semibold text-[#0B2D5C] sm:inline-flex">
              MVP Edition
            </span>
            <button
              type="button"
              aria-label="Back to landing page"
              title="Back to landing page"
              onClick={() => setCurrentView('home')}
              className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-[#C9D7E8] bg-white px-2.5 text-[11px] font-semibold text-[#0B2D5C] transition hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1565C0]"
            >
              <HomeIcon size={15} aria-hidden="true" />
              <span className="hidden md:inline">Home</span>
            </button>
            <img
              src="/profile-avatar.png"
              alt="Student user avatar"
              className="size-9 rounded-full border-2 border-[#C9D7E8] bg-[#EAF2FF] object-cover"
            />
          </div>
        </header>

        <div className="min-h-0 flex-1">
          <RagChatFeed
            conversationId={activeConversation?.id}
            messages={activeMessages}
            documents={documents}
            subject={activeSubject}
            onOpenDocument={handleOpenDocument}
          />
        </div>

        <footer className="shrink-0 border-t border-[#C9D7E8] bg-[#FFFFFF] px-3 py-3 sm:px-5 sm:py-4">
          <div className="mx-auto w-full max-w-3xl">
            <p role="status" className="mb-2 text-center text-[10px] leading-5 text-[#243247]/70">
              هذه معاينة تفاعلية؛ لا تُرسل الأسئلة إلى محرك ذكاء اصطناعي أو قاعدة بيانات.
            </p>
            {uploadNotice && (
              <div role="status" className="mb-2 flex items-start justify-between gap-3 rounded-xl border border-[#C9D7E8] bg-[#F4F7FB] px-3 py-2 text-[11px] leading-5 text-[#243247]">
                <span dir="rtl">{uploadNotice}</span>
                <button
                  type="button"
                  aria-label="إغلاق إشعار الملفات"
                  onClick={() => setUploadNotice('')}
                  className="shrink-0 rounded-md p-1 text-[#0B2D5C] hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0]"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </div>
            )}
            <RagComposer
              value={input}
              onChange={setInput}
              onSubmit={handleQuestionSubmit}
              onFilesSelected={handleFilesSelected}
            />
            <p dir="rtl" className="mt-2 text-center text-[10px] text-[#243247]/55">
              Enter للإرسال · Shift + Enter لسطر جديد
            </p>
          </div>
        </footer>
      </section>

      <RagDocumentDialog document={selectedDocument} onClose={() => setSelectedDocument(null)} />
    </main>
  )
}
