'use client'

import { useMemo, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  FileText,
  History,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { RagThemeToggle } from './rag-theme-provider'

function EmptyState({ children }) {
  return (
    <p className="rounded-xl border border-dashed border-sidebar-border bg-sidebar-accent/40 px-3 py-3 text-center text-xs leading-6 text-sidebar-foreground/70">
      {children}
    </p>
  )
}

function SortField({ id, label, value, options, onChange }) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1.5 text-[11px] font-semibold text-sidebar-foreground/80">
      {label}
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-sidebar-border bg-sidebar px-2 text-xs text-sidebar-foreground outline-none transition focus:border-sidebar-ring focus:ring-2 focus:ring-sidebar-ring/20"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  )
}

export function RagSidebar({
  subjects,
  conversations,
  documents,
  activeSubjectId,
  activeConversationId,
  onSelectSubject,
  onSelectConversation,
  onOpenDocument,
  isMobileOpen,
  onCloseMobile,
}) {
  const [searchQuery, setSearchQuery] = useState('')
  const [isSortOpen, setIsSortOpen] = useState(false)
  const [subjectSort, setSubjectSort] = useState('activity')
  const [conversationSort, setConversationSort] = useState('recent')
  const [documentSort, setDocumentSort] = useState('recent')
  const [sortDirection, setSortDirection] = useState('desc')
  const [expandedSubjects, setExpandedSubjects] = useState(() => new Set(activeSubjectId ? [activeSubjectId] : []))
  const [expandedGroups, setExpandedGroups] = useState(() => ({
    [`${activeSubjectId}:conversations`]: true,
    [`${activeSubjectId}:documents`]: false,
  }))

  const normalizedQuery = searchQuery.trim().toLocaleLowerCase()
  const direction = sortDirection === 'asc' ? 1 : -1
  const orderedSubjects = useMemo(() => {
    return subjects
      .map((subject) => {
        const subjectConversations = conversations.filter((conversation) => conversation.subjectId === subject.id)
        const subjectDocuments = documents.filter((document) => document.subjectId === subject.id)
        const subjectMatches = !normalizedQuery
          || `${subject.nameAr} ${subject.nameEn} ${subject.code}`.toLocaleLowerCase().includes(normalizedQuery)
        const visibleConversations = !normalizedQuery || subjectMatches
          ? subjectConversations
          : subjectConversations.filter((conversation) => conversation.title.toLocaleLowerCase().includes(normalizedQuery))
        const visibleDocuments = !normalizedQuery || subjectMatches
          ? subjectDocuments
          : subjectDocuments.filter((document) => `${document.name} ${document.description ?? ''}`.toLocaleLowerCase().includes(normalizedQuery))
        const latestActivity = Math.max(
          ...subjectConversations.map((conversation) => conversation.updatedAtValue ?? 0),
          ...subjectDocuments.map((document) => document.updatedAtValue ?? 0),
          0,
        )

        return {
          ...subject,
          visibleConversations,
          visibleDocuments,
          hasMatch: subjectMatches || visibleConversations.length > 0 || visibleDocuments.length > 0,
          latestActivity,
        }
      })
      .filter((subject) => subject.hasMatch)
      .sort((left, right) => {
        if (subjectSort === 'name') return left.nameAr.localeCompare(right.nameAr, 'ar') * direction
        if (subjectSort === 'code') return left.code.localeCompare(right.code, 'ar') * direction
        return (left.latestActivity - right.latestActivity) * direction
      })
  }, [conversations, documents, direction, normalizedQuery, subjectSort, subjects])

  function toggleSubject(subjectId) {
    setExpandedSubjects((current) => {
      const next = new Set(current)
      if (next.has(subjectId)) next.delete(subjectId)
      else next.add(subjectId)
      return next
    })
  }

  function toggleGroup(subjectId, group) {
    const key = `${subjectId}:${group}`
    setExpandedGroups((current) => ({ ...current, [key]: !current[key] }))
  }

  function sortConversations(items) {
    return [...items].sort((left, right) => (
      conversationSort === 'title'
        ? left.title.localeCompare(right.title, 'ar') * direction
        : ((left.updatedAtValue ?? 0) - (right.updatedAtValue ?? 0)) * direction
    ))
  }

  function sortDocuments(items) {
    return [...items].sort((left, right) => (
      documentSort === 'name'
        ? left.name.localeCompare(right.name, 'ar') * direction
        : ((left.updatedAtValue ?? 0) - (right.updatedAtValue ?? 0)) * direction
    ))
  }

  function handleSelectSubject(subjectId) {
    onSelectSubject(subjectId)
    setExpandedSubjects((current) => new Set(current).add(subjectId))
    setExpandedGroups((current) => ({ ...current, [`${subjectId}:conversations`]: true }))
  }

  function handleSelectConversation(conversationId, subjectId) {
    toggleMobileClose()
    onSelectConversation(conversationId)
    setExpandedSubjects((current) => new Set(current).add(subjectId))
  }

  function toggleMobileClose() {
    if (isMobileOpen) onCloseMobile()
  }

  return (
    <>
      {isMobileOpen && (
        <button
          type="button"
          aria-label="إغلاق القائمة الجانبية"
          className="fixed inset-0 z-40 bg-sidebar/55 lg:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        id="study-sidebar"
        dir="rtl"
        aria-label="قائمة المواد والمحادثات والملفات"
        className={`fixed inset-y-0 left-0 z-50 ${isMobileOpen ? 'flex' : 'hidden'} w-[min(88vw,304px)] flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform duration-200 lg:flex lg:w-[304px] ${isMobileOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}
      >
        <div className="flex min-h-[76px] items-center gap-3 border-b border-sidebar-border px-4 py-3">
          <div aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
            <BookOpen size={23} strokeWidth={1.8} />
          </div>
          <div className="min-w-0 flex-1">
            <p dir="ltr" className="truncate text-left text-sm font-bold tracking-wide text-sidebar-foreground">RAG-USTHB</p>
            <p className="mt-0.5 truncate text-[11px] text-sidebar-foreground/70">مساعدك الدراسي الذكي</p>
          </div>
          <RagThemeToggle variant="sidebar" />
          <button
            type="button"
            aria-label="إغلاق القائمة"
            onClick={onCloseMobile}
            className="rounded-lg p-2 text-sidebar-foreground transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring lg:hidden"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="border-b border-sidebar-border p-3">
          <label className="relative block">
            <span className="sr-only">ابحث في المواد والمحادثات والملفات</span>
            <Search
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-link"
            />
            <input
              type="search"
              dir="rtl"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="ابحث في موادك وملفاتك..."
              className="h-10 w-full rounded-xl border border-border bg-background pr-10 pl-3 text-xs text-foreground outline-none transition placeholder:text-muted-foreground focus:border-link focus:ring-2 focus:ring-link/15"
            />
          </label>
          <button
            type="button"
            aria-expanded={isSortOpen}
            aria-controls="advanced-sort-controls"
            onClick={() => setIsSortOpen((open) => !open)}
            className="mt-2 flex min-h-9 w-full items-center justify-between rounded-lg px-2 text-xs font-semibold text-sidebar-foreground/80 transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
          >
            <span className="inline-flex items-center gap-2">
              <SlidersHorizontal size={15} aria-hidden="true" />
              الفرز المتقدم
            </span>
            <ChevronDown size={15} className={`transition-transform ${isSortOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
          {isSortOpen && (
            <div id="advanced-sort-controls" className="mt-2 grid gap-2 rounded-xl border border-sidebar-border bg-sidebar-accent/35 p-3">
              <SortField
                id="sort-subjects"
                label="ترتيب المواد"
                value={subjectSort}
                onChange={setSubjectSort}
                options={[
                  { value: 'activity', label: 'حسب النشاط الأخير' },
                  { value: 'name', label: 'حسب اسم المادة' },
                  { value: 'code', label: 'حسب رمز المادة' },
                ]}
              />
              <SortField
                id="sort-conversations"
                label="ترتيب المحادثات"
                value={conversationSort}
                onChange={setConversationSort}
                options={[
                  { value: 'recent', label: 'الأحدث أولاً' },
                  { value: 'title', label: 'حسب العنوان' },
                ]}
              />
              <SortField
                id="sort-documents"
                label="ترتيب الملفات"
                value={documentSort}
                onChange={setDocumentSort}
                options={[
                  { value: 'recent', label: 'الأحدث أولاً' },
                  { value: 'name', label: 'حسب اسم الملف' },
                ]}
              />
              <SortField
                id="sort-direction"
                label="اتجاه الترتيب"
                value={sortDirection}
                onChange={setSortDirection}
                options={[
                  { value: 'desc', label: 'تنازلي' },
                  { value: 'asc', label: 'تصاعدي' },
                ]}
              />
            </div>
          )}
        </div>

        <div className="app-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4">
          <div className="mb-3 flex items-center justify-between gap-2 px-1">
            <h2 className="text-[11px] font-bold text-sidebar-foreground/75">المواد الدراسية</h2>
            <span className="rounded-full bg-sidebar-accent px-2 py-1 text-[10px] font-semibold text-sidebar-foreground/80">
              {orderedSubjects.length} مواد
            </span>
          </div>

          {orderedSubjects.length > 0 ? (
            <ul className="flex flex-col gap-2.5">
              {orderedSubjects.map((subject) => {
                const isActive = subject.id === activeSubjectId
                const isSubjectExpanded = expandedSubjects.has(subject.id)
                const conversationsGroupKey = `${subject.id}:conversations`
                const documentsGroupKey = `${subject.id}:documents`
                const areConversationsExpanded = expandedGroups[conversationsGroupKey] ?? false
                const areDocumentsExpanded = expandedGroups[documentsGroupKey] ?? false
                const subjectConversations = sortConversations(subject.visibleConversations)
                const subjectDocuments = sortDocuments(subject.visibleDocuments)

                return (
                  <li key={subject.id} className={`overflow-hidden rounded-2xl border ${isActive ? 'border-sidebar-ring/70 bg-sidebar-accent/45' : 'border-sidebar-border bg-sidebar-accent/20'}`}>
                    <div className="flex items-center gap-1.5 p-2">
                      <button
                        type="button"
                        aria-pressed={isActive}
                        onClick={() => handleSelectSubject(subject.id)}
                        className="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 rounded-xl px-1.5 text-right transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                      >
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-[10px] font-bold text-sidebar-primary-foreground">
                          {subject.code}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-semibold text-sidebar-foreground">{subject.nameAr}</span>
                          <span dir="ltr" className="mt-0.5 block truncate text-left text-[10px] text-sidebar-foreground/65">{subject.nameEn}</span>
                        </span>
                      </button>
                      <button
                        type="button"
                        aria-label={`${isSubjectExpanded ? 'إخفاء' : 'إظهار'} محادثات وملفات ${subject.nameAr}`}
                        aria-expanded={isSubjectExpanded}
                        aria-controls={`subject-content-${subject.id}`}
                        onClick={() => toggleSubject(subject.id)}
                        className="flex size-9 shrink-0 items-center justify-center rounded-lg text-sidebar-foreground/75 transition hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                      >
                        <ChevronDown size={16} className={`transition-transform ${isSubjectExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                      </button>
                    </div>

                    {isSubjectExpanded && (
                      <div id={`subject-content-${subject.id}`} className="border-t border-sidebar-border/80 px-2 pb-2">
                        <section className="pt-2">
                          <button
                            type="button"
                            aria-expanded={areConversationsExpanded}
                            aria-controls={`conversations-${subject.id}`}
                            onClick={() => toggleGroup(subject.id, 'conversations')}
                            className="flex min-h-9 w-full items-center justify-between gap-2 rounded-lg px-2 text-[11px] font-semibold text-sidebar-foreground/85 transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                          >
                            <span className="inline-flex items-center gap-2"><History size={14} aria-hidden="true" />المحادثات السابقة</span>
                            <span className="inline-flex items-center gap-2 text-[10px] text-sidebar-foreground/65">
                              {subjectConversations.length}
                              <ChevronDown size={13} className={`transition-transform ${areConversationsExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                            </span>
                          </button>
                          {areConversationsExpanded && (
                            <ul id={`conversations-${subject.id}`} className="mt-1 flex flex-col gap-1">
                              {subjectConversations.length > 0 ? subjectConversations.map((conversation) => {
                                const isConversationActive = conversation.id === activeConversationId

                                return (
                                  <li key={conversation.id}>
                                    <button
                                      type="button"
                                      aria-current={isConversationActive ? 'page' : undefined}
                                      onClick={() => handleSelectConversation(conversation.id, subject.id)}
                                      className={`w-full rounded-lg px-2.5 py-2 text-right transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring ${isConversationActive ? 'bg-sidebar-primary text-sidebar-primary-foreground' : 'text-sidebar-foreground/85 hover:bg-sidebar-accent'}`}
                                    >
                                      <span className="block truncate text-[11px] font-medium">{conversation.title}</span>
                                      <span className={`mt-1 flex items-center gap-1.5 text-[10px] ${isConversationActive ? 'text-sidebar-primary-foreground/70' : 'text-sidebar-foreground/60'}`}>
                                        <History size={11} aria-hidden="true" />
                                        {conversation.updatedAt}
                                      </span>
                                    </button>
                                  </li>
                                )
                              }) : <li><EmptyState>لا توجد محادثات مطابقة للبحث.</EmptyState></li>}
                            </ul>
                          )}
                        </section>

                        <section className="mt-1 border-t border-sidebar-border/70 pt-2">
                          <button
                            type="button"
                            aria-expanded={areDocumentsExpanded}
                            aria-controls={`documents-${subject.id}`}
                            onClick={() => toggleGroup(subject.id, 'documents')}
                            className="flex min-h-9 w-full items-center justify-between gap-2 rounded-lg px-2 text-[11px] font-semibold text-sidebar-foreground/85 transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                          >
                            <span className="inline-flex items-center gap-2"><FileText size={14} aria-hidden="true" />الملفات المرفقة</span>
                            <span className="inline-flex items-center gap-2 text-[10px] text-sidebar-foreground/65">
                              {subjectDocuments.length}
                              <ChevronDown size={13} className={`transition-transform ${areDocumentsExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                            </span>
                          </button>
                          {areDocumentsExpanded && (
                            <ul id={`documents-${subject.id}`} className="mt-1 flex flex-col gap-1">
                              {subjectDocuments.length > 0 ? subjectDocuments.map((document) => (
                                <li key={document.id}>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      toggleMobileClose()
                                      onOpenDocument(document)
                                    }}
                                    className="flex min-h-10 w-full items-center gap-2 rounded-lg px-2.5 py-2 text-right text-sidebar-foreground/85 transition hover:bg-sidebar-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-sidebar-ring"
                                  >
                                    <FileText size={13} className="shrink-0 text-sidebar-primary" aria-hidden="true" />
                                    <span className="min-w-0 flex-1">
                                      <span dir="ltr" className="block truncate text-left text-[11px] font-medium">{document.name}</span>
                                      <span className="mt-0.5 block text-[10px] text-sidebar-foreground/60">{document.fileType} · {document.sizeLabel}</span>
                                    </span>
                                  </button>
                                </li>
                              )) : <li><EmptyState>لا توجد ملفات مطابقة للبحث.</EmptyState></li>}
                            </ul>
                          )}
                        </section>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          ) : (
            <EmptyState>لا توجد مواد أو عناصر تطابق عبارة البحث.</EmptyState>
          )}
        </div>

        <div className="border-t border-sidebar-border px-4 py-3 text-center text-[10px] leading-5 text-sidebar-foreground/70">
          جامعة العلوم والتكنولوجيا هواري بومدين
          <span dir="ltr" className="mt-0.5 block">USTHB · Algiers</span>
        </div>
      </aside>
    </>
  )
}
