import type {
  ActivityEntry,
  ChatMessage,
  ChatReply,
  Commitment,
  CommitmentInput,
  Dashboard,
  McpReadResult,
  McpStatus,
} from "@/types"

const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")
const API_KEY = import.meta.env.VITE_API_KEY ?? ""

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(init.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError("Cannot reach the PromiseLoop API. Is the backend running?", 0)
  }

  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const body = await response.json()
      detail = body?.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function query(params: Record<string, string | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

export const api = {
  dashboard: (tz: string) => request<Dashboard>(`/api/dashboard${query({ tz })}`),

  listCommitments: (params: {
    status?: string
    period?: string
    recipient?: string
    search?: string
    tz?: string
  }) => request<Commitment[]>(`/api/commitments${query(params)}`),

  createCommitment: (input: CommitmentInput) =>
    request<Commitment>("/api/commitments", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  completeCommitment: (id: string) =>
    request<Commitment>(`/api/commitments/${id}/complete`, { method: "POST" }),

  addDependency: (id: string, dependsOnId: string) =>
    request<Commitment>(`/api/commitments/${id}/dependencies`, {
      method: "POST",
      body: JSON.stringify({ depends_on_id: dependsOnId }),
    }),

  activity: (id: string) => request<ActivityEntry[]>(`/api/commitments/${id}/activity`),

  chat: (messages: ChatMessage[], tz: string) =>
    request<ChatReply>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages, timezone: tz }),
    }),

  confirm: (draft: CommitmentInput) =>
    request<Commitment>("/api/chat/confirm", {
      method: "POST",
      body: JSON.stringify({ draft }),
    }),

  mcpStatus: () => request<McpStatus>("/api/mcp/status"),

  mcpRead: () => request<McpReadResult>("/api/mcp/read", { method: "POST" }),
}
