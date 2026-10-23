export type CommitmentStatus = "pending" | "in_progress" | "completed" | "cancelled"
export type Priority = "low" | "normal" | "high"
export type Precision = "exact" | "day" | "vague" | "none"

export interface Commitment {
  id: string
  title: string
  recipient: string | null
  details: string | null
  status: CommitmentStatus
  priority: Priority
  due_at: string | null
  due_local_date: string | null
  due_local_time: string | null
  deadline_precision: Precision
  timezone: string
  source: string
  original_text: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  depends_on_ids: string[]
  blocked_by: string[]
}

export interface NextAction {
  commitment: Commitment
  score: number
  reason: string
  blocked: boolean
}

export interface Dashboard {
  pending: Commitment[]
  overdue: Commitment[]
  completed: Commitment[]
  upcoming: Commitment[]
  blocked: Commitment[]
  counts: Record<string, number>
  next_actions: NextAction[]
  server_time: string
}

export interface ActivityEntry {
  id: string
  commitment_id: string
  action: string
  detail: Record<string, unknown>
  created_at: string
}

export interface CommitmentDraft {
  title: string
  recipient: string | null
  details: string | null
  due_at: string | null
  due_local_date: string | null
  due_local_time: string | null
  deadline_precision: Precision
  timezone: string
  priority: Priority
  source: string
  original_text: string | null
}

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export interface PendingConfirmation {
  kind: "create_commitment"
  question: string
  draft: CommitmentDraft
}

export interface ChatReply {
  reply: string
  confirmation: PendingConfirmation | null
  tools_used: string[]
}

export interface McpToolInfo {
  name: string
  description: string
}

export interface McpStatus {
  transport: "streamable-http"
  endpoint: string
  connected: boolean
  protocol_version: string
  server_name: string
  chat_transport: string
  tools: McpToolInfo[]
}

export interface McpReadResult {
  tool: string
  protocol_version: string
  server_name: string
  result: {
    count: number
    commitments: Pick<Commitment, "id" | "title">[]
  }
}

export interface CommitmentInput {
  title: string
  recipient?: string | null
  details?: string | null
  priority?: Priority
  due_at?: string | null
  due_local_date?: string | null
  due_local_time?: string | null
  deadline_precision?: Precision
  timezone?: string
  source?: string
  original_text?: string | null
}
