export type SessionConfig = {
  session_id?: string
  cookies?: string
  authorization?: string
  thinking_mode: 'instant' | 'extended' | 'pro'
  model_name: string
  transport_mode?: 'authenticated' | 'anon'
  allow_anon_fallback?: boolean
}

export type ChatSummary = {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  image?: boolean
}

export type VerificationState = {
  history_verification?: 'not_checked' | 'passed' | 'failed'
  title_verification?: 'not_checked' | 'passed' | 'failed'
  sidebar_visible?: boolean | null
  missing_browser_stage?: string | null
  notes?: string | null
  remote_conversation_exists?: boolean
}

export type TransportDiagnostics = {
  selected_transport_mode?: string
  effective_transport_mode?: string
  endpoint_family?: string | null
  remote_conversation_id?: string | null
  remote_parent_message_id?: string | null
  fallback_occurred?: boolean
  history_verification?: string
  [key: string]: unknown
}

export type ChatDetail = ChatSummary & {
  messages: ChatMessage[]
  session_id?: string | null
  thinking_mode: string
  model_name: string
  transport_mode: string
  allow_anon_fallback?: boolean
  verification: VerificationState
  last_transport_diagnostics: TransportDiagnostics
}

export type DebugTransportPayload = {
  chat_id: string
  transport_mode: string
  allow_anon_fallback: boolean
  verification: VerificationState
  last_transport_diagnostics: TransportDiagnostics
  session_status: Record<string, unknown>
  debug_summary: {
    session_status: Record<string, unknown>
    last_request_summary: Record<string, unknown>
    last_response_summary: Record<string, unknown>
    request_diagnostics: TransportDiagnostics
  }
  transport_audit: Record<string, unknown>
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:6969'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`${response.status}: ${text || `Request failed with ${response.status}`}`)
  }

  return response.json() as Promise<T>
}

export function listChats() {
  return request<ChatSummary[]>('/chats')
}

export function getChat(chatId: string) {
  return request<ChatDetail>(`/chats/${chatId}`)
}

export function createChat(payload: { title?: string } & SessionConfig) {
  return request<ChatDetail>('/chats', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendMessage(chatId: string, payload: { message: string; image?: string | null }) {
  return request<ChatDetail>(`/chats/${chatId}/messages`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function renameChat(chatId: string, title: string) {
  return request<ChatDetail>(`/chats/${chatId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export function deleteChat(chatId: string) {
  return request<{ status: string }>(`/chats/${chatId}`, {
    method: 'DELETE',
  })
}

export function getDebugTransport(chatId: string) {
  return request<DebugTransportPayload>(`/debug/transports/${chatId}`)
}

export function updateChatVerification(
  chatId: string,
  payload: {
    history_verification?: 'not_checked' | 'passed' | 'failed'
    sidebar_visible?: boolean | null
    title_verification?: 'not_checked' | 'passed' | 'failed'
    missing_browser_stage?: string | null
    notes?: string | null
  },
) {
  return request<ChatDetail>(`/chats/${chatId}/verification`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function streamMessage(
  chatId: string,
  payload: { message: string; image?: string | null },
  onEvent: (event: { type: string; content?: string; chat?: ChatDetail; error?: string; message?: ChatMessage }) => void,
) {
  const response = await fetch(`${API_BASE}/chats/${chatId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok || !response.body) {
    const text = await response.text()
    throw new Error(`${response.status}: ${text || `Request failed with ${response.status}`}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''

    for (const part of parts) {
      const line = part
        .split('\n')
        .find((entry) => entry.startsWith('data:'))
      if (!line) continue
      const payload = JSON.parse(line.slice(5).trim())
      onEvent(payload)
      if (payload.type === 'error') {
        throw new Error(payload.error || 'Streaming request failed')
      }
      if (payload.type === 'done') {
        return payload.chat as ChatDetail
      }
    }
  }

  throw new Error('Streaming response ended without a completion event')
}
