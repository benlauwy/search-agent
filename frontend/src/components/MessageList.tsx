import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, ToolCall } from '../api'
import type { Draft } from '../useChat'

function Collapsible({ summary, children }: { summary: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="collapsible">
      <button className="collapsible-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} {summary}
      </button>
      {open && <div className="collapsible-body">{children}</div>}
    </div>
  )
}

function ToolCallBadges({ calls }: { calls: ToolCall[] }) {
  if (!calls.length) return null
  return (
    <div className="tool-badges">
      {calls.map((tc) => (
        <Collapsible key={tc.id} summary={`⚙ ${tc.name}`}>
          <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
        </Collapsible>
      ))}
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === 'user') {
    return <div className="msg msg-user">{msg.text}</div>
  }
  if (msg.role === 'tool') {
    return (
      <div className="msg msg-tool">
        <Collapsible summary={`⮑ ${msg.tool_name ?? 'tool'} result`}>
          <pre>{msg.text}</pre>
        </Collapsible>
      </div>
    )
  }
  return (
    <div className="msg msg-assistant">
      {msg.reasoning.length > 0 && (
        <Collapsible summary="Reasoning">
          <div className="reasoning-text">{msg.reasoning.join('\n\n')}</div>
        </Collapsible>
      )}
      {msg.text && (
        <div className="markdown">
          <Markdown remarkPlugins={[remarkGfm]}>{msg.text}</Markdown>
        </div>
      )}
      <ToolCallBadges calls={msg.tool_calls} />
    </div>
  )
}

export function MessageList({
  messages,
  draft,
  running,
  error,
}: {
  messages: Message[]
  draft: Draft | null
  running: boolean
  error: string | null
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, draft?.text, draft?.reasoning, error])

  return (
    <div className="message-list">
      {messages.length === 0 && !running && (
        <div className="empty-state">
          Ask anything. I can search the web, read your uploaded files, and write downloadable
          Markdown reports.
        </div>
      )}
      {messages.map((m) => (
        <MessageBubble key={m.id} msg={m} />
      ))}
      {draft && (
        <div className="msg msg-assistant msg-draft">
          {draft.reasoning && (
            <div className="reasoning-live">
              <span className="reasoning-label">Thinking…</span>
              <div className="reasoning-text">{draft.reasoning}</div>
            </div>
          )}
          {draft.text && (
            <div className="markdown">
              <Markdown remarkPlugins={[remarkGfm]}>{draft.text}</Markdown>
            </div>
          )}
        </div>
      )}
      {running && !draft && <div className="msg msg-assistant msg-draft">…</div>}
      {error && <div className="msg msg-error">{error}</div>}
      <div ref={bottomRef} />
    </div>
  )
}
