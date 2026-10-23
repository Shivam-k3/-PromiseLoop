import { Loader2, RefreshCw, Server, Wifi } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"
import type { McpReadResult, McpStatus } from "@/types"

export function McpPanel() {
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const [readResult, setReadResult] = useState<McpReadResult | null>(null)
  const [readError, setReadError] = useState<string | null>(null)

  const applyProbe = useCallback(async () => {
    try {
      setStatus(await api.mcpStatus())
      setError(null)
    } catch (cause) {
      setStatus(null)
      setError(cause instanceof Error ? cause.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [])

  const connect = useCallback(async () => {
    setLoading(true)
    await applyProbe()
  }, [applyProbe])

  useEffect(() => {
    let cancelled = false
    api
      .mcpStatus()
      .then((next) => {
        if (cancelled) return
        setStatus(next)
        setError(null)
      })
      .catch((cause) => {
        if (cancelled) return
        setStatus(null)
        setError(cause instanceof Error ? cause.message : "Unknown error")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const read = async () => {
    setReading(true)
    setReadError(null)
    try {
      setReadResult(await api.mcpRead())
    } catch (cause) {
      setReadError(cause instanceof Error ? cause.message : "Unknown error")
    } finally {
      setReading(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Server className="size-4" /> MCP connection
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            initialize + tools/list over Streamable HTTP
          </p>
        </div>
        <Badge variant={loading ? "muted" : status ? "success" : "destructive"}>
          {loading ? "checking" : status ? "connected" : "offline"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {status ? (
          <div className="space-y-3 text-xs">
            <div className="space-y-1.5">
              <p className="break-all font-mono text-muted-foreground">{status.endpoint}</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline">protocol {status.protocol_version}</Badge>
                <Badge variant="outline">{status.server_name}</Badge>
                <Badge variant={status.chat_transport === "http" ? "success" : "warning"}>
                  chat: {status.chat_transport}
                </Badge>
              </div>
            </div>

            <div>
              <p className="text-muted-foreground">
                Tools discovered ({status.tools.length})
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {status.tools.map((tool) => (
                  <Badge key={tool.name} variant="muted" title={tool.description}>
                    {tool.name}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={connect} disabled={loading}>
                <RefreshCw className={loading ? "size-3 animate-spin" : "size-3"} />
                Re-check
              </Button>
              <Button size="sm" variant="secondary" onClick={read} disabled={reading}>
                {reading ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Wifi className="size-3" />
                )}
                Read commitments
              </Button>
            </div>

            {readResult && (
              <div className="rounded-lg border bg-muted/40 p-2">
                <p className="font-medium">tools/call: {readResult.tool}</p>
                <p className="text-muted-foreground">
                  Returned {readResult.result.count} commitment
                  {readResult.result.count === 1 ? "" : "s"} over HTTP.
                </p>
                {readResult.result.commitments.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {readResult.result.commitments.slice(0, 3).map((item) => (
                      <li key={item.id}>• {item.title}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {readError && <p className="text-destructive">{readError}</p>}

            <p className="text-[11px] text-muted-foreground">
              Commitment workflow: use the assistant below. It stages the draft first and
              only calls <code className="rounded bg-muted px-1">create_commitment</code>{" "}
              after you press <strong>Save it</strong>.
              {status.chat_transport !== "http" && (
                <> Set MCP_TRANSPORT=http to route that write through this HTTP server.</>
              )}
            </p>
          </div>
        ) : (
          <div className="space-y-2 text-xs">
            <p className="text-destructive">
              {error ?? "Streamable HTTP MCP server is not reachable."}
            </p>
            <p className="text-muted-foreground">
              Start it with{" "}
              <code className="rounded bg-muted px-1">
                python -m app.mcp_server.server --http --port 8001
              </code>
              .
            </p>
            <Button size="sm" variant="outline" onClick={connect} disabled={loading}>
              <RefreshCw className={loading ? "size-3 animate-spin" : "size-3"} /> Try again
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
