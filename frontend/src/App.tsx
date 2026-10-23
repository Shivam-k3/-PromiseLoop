import { Link2, Loader2, X } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { ChatPanel } from "@/components/ChatPanel"
import { Dashboard } from "@/components/Dashboard"
import { McpPanel } from "@/components/McpPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ApiError, api } from "@/lib/api"
import { browserTimezone } from "@/lib/format"
import type { ChatMessage, Commitment, Dashboard as DashboardData, PendingConfirmation } from "@/types"

export default function App() {
  const timezone = browserTimezone()
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [dependencyTarget, setDependencyTarget] = useState<Commitment | null>(null)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(null)
  const [sending, setSending] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setDashboard(await api.dashboard(timezone))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [timezone])

  useEffect(() => {
    void load()
  }, [load])

  const complete = async (id: string) => {
    setBusyId(id)
    try {
      await api.completeCommitment(id)
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown error")
    } finally {
      setBusyId(null)
    }
  }

  const linkDependency = async (dependsOnId: string) => {
    if (!dependencyTarget) return
    setBusyId(dependencyTarget.id)
    try {
      await api.addDependency(dependencyTarget.id, dependsOnId)
      setDependencyTarget(null)
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown error")
    } finally {
      setBusyId(null)
    }
  }

  const send = async (text: string) => {
    const outgoing: ChatMessage = { role: "user", content: text }
    const history = [...messages, outgoing]
    setMessages(history)
    setSending(true)
    setChatError(null)
    setConfirmation(null)
    try {
      const reply = await api.chat(history, timezone)
      setMessages((current) => [...current, { role: "assistant", content: reply.reply }])
      setConfirmation(reply.confirmation)
    } catch (cause) {
      setChatError(
        cause instanceof ApiError ? cause.message : "The assistant is unavailable right now.",
      )
    } finally {
      setSending(false)
    }
  }

  const confirmSave = async () => {
    if (!confirmation) return
    setSending(true)
    setChatError(null)
    try {
      const created = await api.confirm(confirmation.draft)
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: `Saved: "${created.title}"${created.recipient ? ` for ${created.recipient}` : ""}.`,
        },
      ])
      setConfirmation(null)
      await load()
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "Could not save the commitment.")
    } finally {
      setSending(false)
    }
  }

  const candidates = dashboard
    ? [
        ...dashboard.overdue,
        ...dashboard.upcoming,
        ...dashboard.pending,
      ].filter(
        (item) =>
          item.id !== dependencyTarget?.id &&
          item.status !== "completed" &&
          item.status !== "cancelled",
      )
    : []

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card/70 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
              ∞
            </span>
            <div>
              <h1 className="text-sm font-semibold leading-tight">PromiseLoop</h1>
              <p className="text-[11px] leading-tight text-muted-foreground">
                Remember every promise you make
              </p>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Badge variant="outline">{timezone}</Badge>
            <Badge variant={loading ? "muted" : "success"}>
              {loading ? "syncing" : "connected"}
            </Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-4">
          {dependencyTarget && (
            <Card className="border-primary/40">
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <CardTitle className="flex items-center gap-2">
                  <Link2 className="size-4" /> What must happen first?
                </CardTitle>
                <Button size="sm" variant="ghost" onClick={() => setDependencyTarget(null)}>
                  <X className="size-3" />
                </Button>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Pick the prerequisite for “{dependencyTarget.title}”.
                </p>
                {candidates.length === 0 ? (
                  <p className="mt-3 text-sm text-muted-foreground">
                    No other open commitments to depend on.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1.5">
                    {candidates.map((candidate) => (
                      <li key={candidate.id}>
                        <button
                          disabled={busyId === dependencyTarget.id}
                          onClick={() => linkDependency(candidate.id)}
                          className="w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-accent disabled:opacity-50 cursor-pointer"
                        >
                          {candidate.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          )}

          <Dashboard
            data={dashboard}
            loading={loading}
            error={error}
            busyId={busyId}
            onRetry={load}
            onComplete={complete}
            onAddDependency={(id) =>
              setDependencyTarget(
                [
                  ...(dashboard?.overdue ?? []),
                  ...(dashboard?.upcoming ?? []),
                  ...(dashboard?.pending ?? []),
                ].find((item) => item.id === id) ?? null,
              )
            }
          />
        </div>

        <div className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <McpPanel />
          <ChatPanel
            messages={messages}
            confirmation={confirmation}
            sending={sending}
            error={chatError}
            onSend={send}
            onConfirm={confirmSave}
            onDiscard={() => setConfirmation(null)}
          />
        </div>
      </main>

      {busyId && (
        <div className="pointer-events-none fixed bottom-4 right-4 flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-xs shadow-sm">
          <Loader2 className="size-3 animate-spin" /> Saving…
        </div>
      )}
    </div>
  )
}
