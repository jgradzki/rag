import { useEffect, useState } from 'react'
import { deleteDocument, getHealth, listDocuments, uploadDocuments } from './api'
import type { DocumentInfo, Health } from './api'
import { Chat } from './components/Chat'
import { DocumentPanel } from './components/DocumentPanel'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setDocuments(await listDocuments())
  }

  useEffect(() => {
    async function load() {
      const [healthInfo, docs] = await Promise.all([getHealth(), listDocuments()])
      setHealth(healthInfo)
      setDocuments(docs)
    }
    load().catch(() =>
      setError('Cannot reach the backend. Is it running on http://localhost:8000?'),
    )
  }, [])

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="app">
      <header>
        <h1>RAG demo</h1>
        {health && (
          <span className="muted">
            LLM: {health.llm} · Embeddings: {health.embedding_model.split('/').pop()}
          </span>
        )}
      </header>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      <div className="layout">
        <DocumentPanel
          documents={documents}
          onUpload={(files) => run(() => uploadDocuments(files))}
          onDelete={(docId) => run(() => deleteDocument(docId))}
        />
        <Chat />
      </div>
    </div>
  )
}
