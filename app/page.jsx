'use client'

import { useState } from 'react'
import { Home as HomeIcon, Menu, X } from 'lucide-react'
import { RagAuth } from './rag-auth'
import { RagChatFeed } from './rag-chat-feed'
import { RagLanding } from './rag-home'
import { RagComposer } from './rag-composer'
import { RagDocumentDialog } from './rag-document-dialog'
import { RagSidebar } from './rag-sidebar'

const subjects = [
  { id: 'algorithms', code: 'L1', nameAr: 'الخوارزميات', nameEn: 'Algorithms' },
  { id: 'analysis', code: 'L1', nameAr: 'التحليل 1', nameEn: 'Analysis 1' },
  { id: 'algebra', code: 'L1', nameAr: 'الجبر 1', nameEn: 'Algebra 1' },
  { id: 'physics', code: 'L1', nameAr: 'الفيزياء 1', nameEn: 'Physics 1' },
]

const initialDocuments = [
  {
    id: 'ch3-notes',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-25T18:00:00+01:00'),
    name: 'Ch3_Notes.pdf',
    fileType: 'PDF',
    sizeLabel: '2.4 MB',
    description: 'ملاحظات المحاضرة حول التعقيد الخوارزمي وطرق البحث.',
    pages: [
      {
        title: 'البحث الثنائي',
        text: 'تعمل خوارزمية البحث الثنائي على مجال مرتب، وتقسمه إلى نصفين في كل خطوة حتى تجد العنصر أو تنتهي مساحة البحث.',
      },
      {
        title: 'التعقيد الزمني',
        text: 'عدد خطوات البحث يتناسب مع لوغاريتم عدد العناصر، لذلك يكون التعقيد الزمني O(log n).',
      },
    ],
  },
  {
    id: 'algorithms-l1',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-24T17:30:00+01:00'),
    name: 'Algorithms_L1.pdf',
    fileType: 'PDF',
    sizeLabel: '4.8 MB',
    description: 'دليل المقرر للسنة الأولى في الخوارزميات وهياكل البيانات.',
    pages: [
      {
        title: 'البحث الخطي',
        text: 'يفحص البحث الخطي العناصر بالتتابع حتى يعثر على القيمة المطلوبة. لا يشترط ترتيب البيانات، ويصل تعقيده في أسوأ الحالات إلى O(n).',
      },
      {
        title: 'اختيار الخوارزمية',
        text: 'يعتمد الاختيار بين البحث الخطي والثنائي على ترتيب البيانات وحجمها وكلفة تجهيزها.',
      },
    ],
  },
  {
    id: 'td02-exercises',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-22T12:00:00+01:00'),
    name: 'TD02_Exercises.pdf',
    fileType: 'PDF',
    sizeLabel: '1.1 MB',
    description: 'تمارين الأعمال الموجهة مع إرشادات مراجعة للأسبوع الثاني.',
    pages: [
      {
        title: 'تمارين الاستدعاء الذاتي',
        text: 'حلّل حالة التوقف، ثم اكتب العلاقة بين المسألة الأصلية والمسألة الأصغر قبل حساب التعقيد.',
      },
      {
        title: 'مراجعة الحل',
        text: 'تحقق من أن كل استدعاء يقترب من حالة التوقف وأن جميع الحالات الأساسية مغطاة.',
      },
    ],
  },
]

const initialConversations = [
  { id: 'binary-search', title: 'Binary search complexity', updatedAt: 'اليوم · 10:42', updatedAtValue: Date.parse('2026-10-26T10:42:00+01:00'), subjectId: 'algorithms' },
  { id: 'recursion', title: 'Recursion exercises', updatedAt: 'أمس · 18:18', updatedAtValue: Date.parse('2026-10-25T18:18:00+01:00'), subjectId: 'algorithms' },
  { id: 'sorting', title: 'Sorting algorithms review', updatedAt: '12 مارس · 14:05', updatedAtValue: Date.parse('2026-03-12T14:05:00+01:00'), subjectId: 'algorithms' },
]

const initialMessagesByConversation = {
  'binary-search': [
    { id: 'binary-user-1', role: 'user', text: 'ما هو التعقيد الزمني لخوارزمية البحث الثنائي؟' },
    {
      id: 'binary-assistant-1',
      role: 'assistant',
      text: 'التعقيد الزمني لخوارزمية البحث الثنائي هو O(log n)، لأنها تقلل مساحة البحث إلى النصف في كل خطوة. يجب أن تكون البيانات مرتبة مسبقاً حتى تعمل الخوارزمية بشكل صحيح.',
      sourceIds: ['ch3-notes'],
    },
    { id: 'binary-user-2', role: 'user', text: 'هل يمكنك توضيح الفرق بينها وبين البحث الخطي؟' },
    {
      id: 'binary-assistant-2',
      role: 'assistant',
      text: 'بالتأكيد. البحث الخطي يفحص العناصر واحداً تلو الآخر وتعقيده O(n)، بينما البحث الثنائي أسرع بكثير بتعقيد O(log n)، لكنه يتطلب مصفوفة مرتبة. عملياً، نختار البحث الثنائي عند توفر ترتيب مسبق وحجم بيانات كبير، ونستخدم البحث الخطي عندما تكون البيانات غير مرتبة أو عندما يكون عدد العناصر صغيراً.',
      sourceIds: ['algorithms-l1'],
    },
  ],
  recursion: [
    { id: 'recursion-user-1', role: 'user', text: 'ما المقصود بالاستدعاء الذاتي؟' },
    {
      id: 'recursion-assistant-1',
      role: 'assistant',
      text: 'الاستدعاء الذاتي هو أن تستدعي الدالة نفسها لحل نسخة أصغر من المشكلة. يحتاج الحل إلى حالة توقف واضحة، وإلى خطوة تقلّص المدخلات حتى يصل التنفيذ إليها.',
      sourceIds: ['td02-exercises'],
    },
  ],
  sorting: [
    { id: 'sorting-user-1', role: 'user', text: 'ما الفرق بين الفرز بالاختيار والفرز بالدمج؟' },
    {
      id: 'sorting-assistant-1',
      role: 'assistant',
      text: 'فرز الاختيار يختار أصغر عنصر من الجزء غير المرتب في كل دورة، ويعمل عادةً بتعقيد O(n²). أمّا الفرز بالدمج فيقسّم القائمة ثم يدمج الأجزاء المرتبة، ويعمل بتعقيد O(n log n) مع مساحة إضافية.',
      sourceIds: ['algorithms-l1'],
    },
  ],
}

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
        title: `محادثة جديدة · ${subject.nameEn}`,
        updatedAt: 'الآن',
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
    const assistantNotice = {
      id: assistantMessageId,
      role: 'assistant',
      kind: 'notice',
      text: 'تمت إضافة سؤالك إلى سجل المعاينة فقط. محرك الاسترجاع والإجابة غير متصل حالياً، لذلك لم يتم إنشاء إجابة أو مصدر جديد.',
    }

    setMessagesByConversation((current) => ({
      ...current,
      [activeConversation.id]: [...(current[activeConversation.id] ?? []), userMessage, assistantNotice],
    }))
    setConversations((current) => current.map((conversation) => (
      conversation.id === activeConversation.id
        ? {
            ...conversation,
            title: conversation.title.startsWith('محادثة جديدة') ? text.slice(0, 42) : conversation.title,
            updatedAt: 'الآن',
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
            aria-label="فتح القائمة الجانبية"
            aria-controls="study-sidebar"
            aria-expanded={isMobileSidebarOpen}
            onClick={() => setIsMobileSidebarOpen(true)}
            className="flex size-10 shrink-0 items-center justify-center rounded-xl text-[#0B2D5C] transition hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1565C0] lg:hidden"
          >
            <Menu size={20} aria-hidden="true" />
          </button>

          <div className="min-w-0 flex-1 text-center">
            <h1 id="chat-heading" dir="ltr" className="truncate text-sm font-bold text-[#0B2D5C]">
              {activeSubject.nameEn}
            </h1>
            <p dir="rtl" className="mt-0.5 truncate text-[11px] text-[#243247]/65">
              {activeSubject.nameAr} <span aria-hidden="true">·</span> جلسة معاينة
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden rounded-full border border-[#C9D7E8] bg-[#EAF2FF] px-2.5 py-1 text-[10px] font-semibold text-[#0B2D5C] sm:inline-flex">
              نسخة تجريبية
            </span>
            <button
              type="button"
              dir="rtl"
              aria-label="العودة إلى الصفحة الرئيسية"
              title="العودة إلى الصفحة الرئيسية"
              onClick={() => setCurrentView('home')}
              className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-[#C9D7E8] bg-white px-2.5 text-[11px] font-semibold text-[#0B2D5C] transition hover:bg-[#EAF2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1565C0]"
            >
              <HomeIcon size={15} aria-hidden="true" />
              <span className="hidden md:inline">الرئيسية</span>
            </button>
            <img
              src="/profile-avatar.png"
              alt="صورة حساب تجريبي"
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
