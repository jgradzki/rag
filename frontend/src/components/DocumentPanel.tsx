import { useRef, useState } from 'react'
import type { DocumentInfo } from '../api'

const ACCEPTED = '.pdf,.txt,.md'

interface Props {
  documents: DocumentInfo[]
  onUpload: (files: File[]) => Promise<void>
  onDelete: (docId: string) => Promise<void>
}

export function DocumentPanel({ documents, onUpload, onDelete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  // One request at a time: a second upload or a double-clicked delete would race the first.
  const [busy, setBusy] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  async function run(label: string, action: () => Promise<void>) {
    if (busy) return
    setBusy(label)
    try {
      await action()
    } finally {
      setBusy(null)
    }
  }

  function upload(files: File[]) {
    if (files.length === 0) return
    run('Indexing…', async () => {
      await onUpload(files)
      if (inputRef.current) inputRef.current.value = ''
    })
  }

  return (
    <aside className="documents" aria-busy={busy !== null}>
      <h2>Documents</h2>

      <button
        type="button"
        className={`dropzone${dragging ? ' dragging' : ''}`}
        disabled={busy !== null}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          upload(Array.from(e.dataTransfer.files))
        }}
      >
        {busy ?? 'Drop PDF, TXT or MD files here, or click to choose'}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        multiple
        hidden
        onChange={(e) => upload(Array.from(e.target.files ?? []))}
      />

      {documents.length === 0 ? (
        <p className="muted">No documents indexed yet.</p>
      ) : (
        <ul className="doc-list">
          {documents.map((doc) => (
            <li key={doc.doc_id}>
              <div className="doc-name" title={doc.name}>
                {doc.name}
              </div>
              <span className="muted">{doc.chunks} chunks</span>
              <button
                className="icon-button"
                aria-label={`Remove ${doc.name}`}
                title="Remove from index"
                disabled={busy !== null}
                onClick={() => run('Removing…', () => onDelete(doc.doc_id))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
