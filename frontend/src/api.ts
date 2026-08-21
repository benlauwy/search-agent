export interface User {
  id: string
  email: string
  name: string
  picture: string
  provider: string
}

export interface Session {
  id: string
  title: string
  provider: string
  model: string
  kind: string
  created_at: string
  updated_at: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface Message {
  id: string
  idx: number
  role: 'user' | 'assistant' | 'tool'
  text: string
  reasoning: string[]
  tool_calls: ToolCall[]
  tool_call_id: string | null
  tool_name: string | null
  created_at: string
}

export interface FileInfo {
  id: string
  kind: 'upload' | 'artifact'
  filename: string
  mime: string
  size: number
  version: number
  created_at: string
}

export interface EventInfo {
  id: string
  run_id: string
  idx: number
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface AppSettings {
  values: Record<string, string>
  secret_keys: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, { credentials: 'same-origin', ...init })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      if (body.detail) detail = body.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  me: () => request<User>('/api/auth/me'),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (provider = '', model = '') =>
    request<Session>('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    }),
  deleteSession: (id: string) => request<{ ok: boolean }>(`/api/sessions/${id}`, { method: 'DELETE' }),
  getSession: (id: string) => request<Session>(`/api/sessions/${id}`),
  updateSession: (id: string, values: { provider?: string; model?: string }) =>
    request<Session>(`/api/sessions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }),
  listEvents: (id: string) => request<EventInfo[]>(`/api/sessions/${id}/events`),
  listMessages: (id: string) => request<Message[]>(`/api/sessions/${id}/messages`),
  sendMessage: (id: string, text: string) =>
    request<{ run_id: string }>(`/api/sessions/${id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),
  cancelRun: (id: string) => request<{ cancelled: boolean }>(`/api/sessions/${id}/cancel`, { method: 'POST' }),
  listFiles: (id: string) => request<FileInfo[]>(`/api/sessions/${id}/files`),
  uploadFile: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<FileInfo>(`/api/sessions/${id}/files`, { method: 'POST', body: form })
  },
  getSettings: () => request<AppSettings>('/api/settings'),
  updateSettings: (values: Record<string, string>) =>
    request<AppSettings>('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    }),
}
