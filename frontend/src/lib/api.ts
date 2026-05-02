export type SessionConfig = {
  session_id?: string
  cookies?: string
  authorization?: string
  thinking_mode: 'instant' | 'extended' | 'pro'
  model_name: string
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

export type ChatDetail = ChatSummary & {
  messages: ChatMessage[]
  session_id?: string | null
  thinking_mode: string
  model_name: string
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
