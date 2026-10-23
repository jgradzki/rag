import { memo, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { MAX_QUESTION_LENGTH, streamChat } from '../api'
import type { Source } from '../api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  error?: string
}

const EXAMPLES = [
  'What is chunk overlap for?',
  'How long did the Opportunity rover operate?',
  'What is hybrid search?',
]

// Answers can be steered by text injected into an uploaded document, so they must never
// load remote resources: an image URL could carry the question and the retrieved context
// to another server. Links open in a new tab, so following one keeps the conversation.
const MARKDOWN_COMPONENTS: Components = {
  img: ({ alt }) => <span className="muted">[image: {alt || 'no description'}]</span>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
}

// Follow new tokens only while the user is (nearly) at the bottom of the conversation.
const STICK_TO_BOTTOM_PX = 80

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const list = listRef.current
    if (list && stickToBottom.current) list.scrollTop = list.scrollHeight
  }, [messages])

  // Updates the last (assistant) message while the answer streams in.
  function updateLast(update: (msg: Message) => Message) {
    setMessages((prev) => [...prev.slice(0, -1), update(prev[prev.length - 1])])
  }

  async function ask(question: string) {
    question = question.trim()
    if (!question || streaming) return
    setInput('')
    setStreaming(true)
    stickToBottom.current = true
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '' },
    ])
    try {
      await streamChat(question, {
        onSources: (sources) => updateLast((m) => ({ ...m, sources })),
        onToken: (token) => updateLast((m) => ({ ...m, content: m.content + token })),
        onError: (error) => updateLast((m) => ({ ...m, error })),
      })
    } catch (e) {
      updateLast((m) => ({ ...m, error: (e as Error).message }))
    } finally {
      setStreaming(false)
    }
  }

  return (
    <main className="chat">
      <div
        className="messages"
        ref={listRef}
        aria-live="polite"
        aria-busy={streaming}
        onScroll={(e) => {
          const el = e.currentTarget
          stickToBottom.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < STICK_TO_BOTTOM_PX
        }}
      >
        {messages.length === 0 && (
          <div className="empty">
            <h2>Ask your documents</h2>
            <p className="muted">
              Relevant fragments are retrieved from the index and passed to the LLM, which answers
              with numbered citations.
            </p>
            <div className="examples">
              {EXAMPLES.map((q) => (
                <button key={q} onClick={() => ask(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageView key={i} msg={msg} pending={streaming && i === messages.length - 1} />
        ))}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          ask(input)
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about your documents…"
          aria-label="Question"
          maxLength={MAX_QUESTION_LENGTH}
          disabled={streaming}
        />
        <button type="submit" disabled={streaming || !input.trim()}>
          Send
        </button>
      </form>
    </main>
  )
}

// Memoized: while an answer streams, only that message re-renders (and re-parses its
// Markdown) - not every earlier answer in the conversation.
const MessageView = memo(function MessageView({
  msg,
  pending,
}: {
  msg: Message
  pending: boolean
}) {
  if (msg.role === 'user') {
    return (
      <div className="message user">
        <p>{msg.content}</p>
      </div>
    )
  }
  return (
    <div className="message assistant">
      {msg.content && <Markdown components={MARKDOWN_COMPONENTS}>{msg.content}</Markdown>}
      {!msg.content && !msg.error && (
        <p className="muted">{pending ? 'Thinking…' : '(empty answer)'}</p>
      )}
      {msg.error && <p className="error">{msg.error}</p>}
      {msg.sources && msg.sources.length > 0 && <Sources sources={msg.sources} />}
    </div>
  )
})

function Sources({ sources }: { sources: Source[] }) {
  return (
    <details className="sources">
      <summary>Sources ({sources.length})</summary>
      <ol>
        {sources.map((s) => (
          <li key={s.number}>
            <div className="source-head">
              <strong>[{s.number}]</strong> {s.source}
              {s.page != null && `, page ${s.page}`}
              <span className="muted"> · relevance {s.score.toFixed(2)}</span>
            </div>
            <blockquote>{s.text}</blockquote>
          </li>
        ))}
      </ol>
    </details>
  )
}
