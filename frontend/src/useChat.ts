import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type FileInfo, type Message, type ToolCall } from './api'

export interface ToolActivity {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: string
  isError?: boolean
}

export interface Draft {
  reasoning: string
  text: string
}

let localIdCounter = 0
const localId = () => `local-${++localIdCounter}`

export function useChat(sessionId: string | null) {
  const [messages, setMessages] = useState<Message[]>([])
  const [files, setFiles] = useState<FileInfo[]>([])
  const [running, setRunning] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([])
  const [error, setError] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    const [msgs, fls] = await Promise.all([api.listMessages(sessionId), api.listFiles(sessionId)])
    setMessages(msgs)
    setFiles(fls)
  }, [sessionId])

  useEffect(() => {
    setMessages([])
    setFiles([])
    setDraft(null)
    setToolActivity([])
    setError(null)
    setRunning(false)
    if (!sessionId) return
    void refresh()

    const es = new EventSource(`/api/sessions/${sessionId}/stream`)
    esRef.current = es

    es.addEventListener('status', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      setRunning(Boolean(data.running))
    })
    es.addEventListener('run_started', () => {
      setRunning(true)
      setError(null)
      setToolActivity([])
    })
    es.addEventListener('reasoning_delta', (e) => {
      const { payload } = JSON.parse((e as MessageEvent).data)
      setDraft((d) => ({ reasoning: (d?.reasoning ?? '') + payload.text, text: d?.text ?? '' }))
    })
    es.addEventListener('text_delta', (e) => {
      const { payload } = JSON.parse((e as MessageEvent).data)
      setDraft((d) => ({ reasoning: d?.reasoning ?? '', text: (d?.text ?? '') + payload.text }))
    })
    es.addEventListener('assistant_message', (e) => {
      const { payload } = JSON.parse((e as MessageEvent).data)
      setDraft(null)
      setMessages((msgs) => [
        ...msgs,
        {
          id: localId(),
          idx: msgs.length,
          role: 'assistant',
          text: payload.text,
          reasoning: payload.reasoning ?? [],
          tool_calls: (payload.tool_calls ?? []) as ToolCall[],
          tool_call_id: null,
          tool_name: null,
          created_at: new Date().toISOString(),
        },
      ])
    })
    es.addEventListener('tool_call_started', (e) => {
      const { payload } = JSON.parse((e as MessageEvent).data)
      setToolActivity((acts) => [
        ...acts,
        { id: payload.id, name: payload.name, arguments: payload.arguments },
      ])
    })
    es.addEventListener('tool_result', (e) => {
      const { payload } = JSON.parse((e as MessageEvent).data)
      setToolActivity((acts) =>
        acts.map((a) =>
          a.id === payload.id ? { ...a, result: payload.content, isError: payload.is_error } : a,
        ),
      )
      setMessages((msgs) => [
        ...msgs,
        {
          id: localId(),
          idx: msgs.length,
          role: 'tool',
          text: payload.content,
          reasoning: [],
          tool_calls: [],
          tool_call_id: payload.id,
          tool_name: payload.name,
          created_at: new Date().toISOString(),
        },
      ])
    })
    es.addEventListener('artifact_created', () => {
      if (sessionId) void api.listFiles(sessionId).then(setFiles)
    })
    es.addEventListener('error', (e) => {
      const raw = (e as MessageEvent).data
      if (raw) {
        const { payload } = JSON.parse(raw)
        if (payload?.message) setError(payload.message)
      }
    })
    es.addEventListener('run_finished', () => {
      setRunning(false)
      setDraft(null)
      void refresh()
    })

    return () => {
      es.close()
      esRef.current = null
    }
  }, [sessionId, refresh])

  const send = useCallback(
    async (text: string) => {
      if (!sessionId) return
      setError(null)
      const pendingId = localId()
      setMessages((msgs) => [
        ...msgs,
        {
          id: pendingId,
          idx: msgs.length,
          role: 'user',
          text,
          reasoning: [],
          tool_calls: [],
          tool_call_id: null,
          tool_name: null,
          created_at: new Date().toISOString(),
        },
      ])
      setRunning(true)
      try {
        await api.sendMessage(sessionId, text)
      } catch (e) {
        setMessages((msgs) => msgs.filter((m) => m.id !== pendingId))
        setRunning(false)
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [sessionId],
  )

  const cancel = useCallback(async () => {
    if (sessionId) await api.cancelRun(sessionId)
  }, [sessionId])

  const upload = useCallback(
    async (file: File) => {
      if (!sessionId) return
      await api.uploadFile(sessionId, file)
      setFiles(await api.listFiles(sessionId))
    },
    [sessionId],
  )

  return { messages, files, running, draft, toolActivity, error, send, cancel, upload, refresh }
}
