// Thin client for the FastAPI backend (see backend/app/api/).

export interface DocumentInfo {
  doc_id: string
  name: string
  chunks: number
}

export interface Source {
  number: number
  source: string
  page: number | null
  score: number
  text: string
}

export interface Health {
  status: string
  llm: string
  embedding_model: string
}

export interface ChatHandlers {
  onSources: (sources: Source[]) => void
  onToken: (token: string) => void
  onError: (message: string) => void
}

// Mirrors the question length limit of ChatRequest in backend/app/api/schemas.py.
export const MAX_QUESTION_LENGTH = 4000

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors (422) are a list of {msg, loc, ...}.
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join('; ')
  return `${res.status} ${res.statusText}`
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json() as Promise<T>
}

export const getHealth = () => request<Health>('/api/health')

export const listDocuments = () => request<DocumentInfo[]>('/api/documents')

export function uploadDocuments(files: File[]) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return request<DocumentInfo[]>('/api/documents', { method: 'POST', body: form })
}

export const deleteDocument = (docId: string) =>
  request<{ deleted: string }>(`/api/documents/${docId}`, { method: 'DELETE' })

/**
 * Sends a question and reads the Server-Sent Events stream.
 * EventSource only supports GET, so the stream is parsed manually from fetch().
 */
export async function streamChat(question: string, handlers: ChatHandlers): Promise<void> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  if (!res.body) throw new Error('The response has no body')

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    // The server always ends with a "done" event; anything else is a broken connection.
    if (done) throw new Error('Connection closed before the answer finished')
    buffer += value

    // Events are separated by a blank line; the last part may be incomplete.
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const raw of events) {
      const { event, data } = parseEvent(raw)
      if (event === 'sources') handlers.onSources(data as Source[])
      else if (event === 'token') handlers.onToken(data as string)
      else if (event === 'error') handlers.onError(data as string)
      else if (event === 'done') return
    }
  }
}

function parseEvent(raw: string): { event: string; data: unknown } {
  let event = 'message'
  let data = ''
  for (const line of raw.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7)
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  return { event, data: data ? JSON.parse(data) : null }
}
