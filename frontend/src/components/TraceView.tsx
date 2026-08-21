import { useEffect, useState } from 'react'
import { api, type EventInfo, type Session } from '../api'

function payloadSummary(e: EventInfo): string {
  const p = e.payload
  switch (e.type) {
    case 'run_started':
      return `${p.provider ?? ''} · ${p.model ?? ''}`
    case 'assistant_message': {
      const text = typeof p.text === 'string' ? p.text : ''
      const calls = Array.isArray(p.tool_calls)
        ? (p.tool_calls as { name: string }[]).map((t) => t.name).join(', ')
        : ''
      return [text, calls && `tools: ${calls}`].filter(Boolean).join(' — ')
    }
    case 'tool_call_started':
      return `${p.name}(${JSON.stringify(p.arguments ?? {})})`
    case 'tool_result':
      return `${p.name}${p.is_error ? ' (error)' : ''}: ${typeof p.content === 'string' ? p.content : ''}`
    case 'artifact_created':
      return `${p.filename} (v${p.version})`
    case 'subagent_started':
      return typeof p.task === 'string' ? p.task : ''
    case 'subagent_finished':
      return p.ok ? 'finished' : 'failed'
    case 'run_finished':
      if (p.cancelled) return 'cancelled'
      if (p.failed) return 'failed'
      return 'done'
    case 'error':
      return typeof p.message === 'string' ? p.message : ''
    default:
      return JSON.stringify(p)
  }
}

function clip(text: string, limit = 400): string {
  return text.length > limit ? text.slice(0, limit) + '…' : text
}

export function TraceView({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  // A stack of session ids so subagent traces can be opened and navigated back.
  const [stack, setStack] = useState<string[]>([sessionId])
  const [events, setEvents] = useState<EventInfo[]>([])
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState<string | null>(null)

  const currentId = stack[stack.length - 1]

  useEffect(() => {
    setEvents([])
    setSession(null)
    setError(null)
    Promise.all([api.getSession(currentId), api.listEvents(currentId)])
      .then(([s, evts]) => {
        setSession(s)
        setEvents(evts)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [currentId])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal trace-modal" onClick={(e) => e.stopPropagation()}>
        <div className="trace-header">
          <h2>
            Trace{session?.kind === 'subagent' ? ' (subagent)' : ''}
            {session ? ` — ${session.title}` : ''}
          </h2>
          <div>
            {stack.length > 1 && (
              <button onClick={() => setStack((s) => s.slice(0, -1))}>← Back</button>
            )}
            <button onClick={onClose}>Close</button>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        {!error && events.length === 0 && <p>No events yet.</p>}
        <div className="trace-events">
          {events.map((e) => (
            <div key={e.id} className={`trace-event trace-event-${e.type}`}>
              <span className="trace-event-type">{e.type}</span>
              <span className="trace-event-summary">{clip(payloadSummary(e))}</span>
              {e.type === 'subagent_started' && typeof e.payload.session_id === 'string' && (
                <button
                  className="trace-open-subagent"
                  onClick={() => setStack((s) => [...s, e.payload.session_id as string])}
                >
                  Open subagent trace
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
