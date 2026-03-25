export type RecentDocumentSource = 'chat' | 'sop' | 'library';

export interface RecentQuestionItem {
  question: string;
  askedAt: string;
}

export interface RecentDocumentItem {
  docId: string;
  fileName: string;
  departmentId: string | null;
  categoryId: string | null;
  viewedAt: string;
  source: RecentDocumentSource;
}

const RECENT_QUESTIONS_KEY = 'portal_recent_questions';
const RECENT_DOCUMENTS_KEY = 'portal_recent_documents';
const MAX_RECENT_ITEMS = 6;

function readStorage<T>(key: string): T[] {
  if (typeof window === 'undefined') {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeStorage<T>(key: string, items: T[]) {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(items));
}

export function loadRecentQuestions(): RecentQuestionItem[] {
  return readStorage<RecentQuestionItem>(RECENT_QUESTIONS_KEY);
}

export function rememberQuestion(question: string) {
  const normalized = question.trim();
  if (!normalized) {
    return;
  }
  const nextItems = [
    { question: normalized, askedAt: new Date().toISOString() },
    ...loadRecentQuestions().filter((item) => item.question !== normalized),
  ].slice(0, MAX_RECENT_ITEMS);
  writeStorage(RECENT_QUESTIONS_KEY, nextItems);
}

export function loadRecentDocuments(): RecentDocumentItem[] {
  return readStorage<RecentDocumentItem>(RECENT_DOCUMENTS_KEY);
}

export function rememberDocument(item: Omit<RecentDocumentItem, 'viewedAt'>) {
  const nextItems = [
    { ...item, viewedAt: new Date().toISOString() },
    ...loadRecentDocuments().filter((existing) => existing.docId !== item.docId),
  ].slice(0, MAX_RECENT_ITEMS);
  writeStorage(RECENT_DOCUMENTS_KEY, nextItems);
}
