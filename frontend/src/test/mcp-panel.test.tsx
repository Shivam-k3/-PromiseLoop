import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { McpPanel } from "@/components/McpPanel"
import { api } from "@/lib/api"
import type { McpReadResult, McpStatus } from "@/types"

vi.mock("@/lib/api", () => ({
  api: {
    mcpStatus: vi.fn(),
    mcpRead: vi.fn(),
  },
}))

const status: McpStatus = {
  transport: "streamable-http",
  endpoint: "http://127.0.0.1:8001/mcp",
  connected: true,
  protocol_version: "2025-11-25",
  server_name: "promiseloop",
  chat_transport: "http",
  tools: [
    { name: "create_commitment", description: "Create" },
    { name: "list_commitments", description: "List" },
    { name: "update_commitment", description: "Update" },
    { name: "add_dependency", description: "Depend" },
    { name: "get_next_actions", description: "Next" },
    { name: "complete_commitment", description: "Complete" },
  ],
}

const readResult: McpReadResult = {
  tool: "list_commitments",
  protocol_version: "2025-11-25",
  server_name: "promiseloop",
  result: {
    count: 1,
    commitments: [{ id: "1", title: "Send the demo" }],
  },
}

afterEach(cleanup)

describe("McpPanel", () => {
  beforeEach(() => {
    vi.mocked(api.mcpStatus).mockReset()
    vi.mocked(api.mcpRead).mockReset()
  })

  it("shows the negotiated protocol, transport and discovered tools", async () => {
    vi.mocked(api.mcpStatus).mockResolvedValue(status)
    render(<McpPanel />)

    expect(await screen.findByText("connected")).toBeInTheDocument()
    expect(screen.getByText(/protocol 2025-11-25/)).toBeInTheDocument()
    expect(screen.getByText(/chat: http/)).toBeInTheDocument()
    expect(screen.getByText("list_commitments")).toBeInTheDocument()
    expect(screen.getByText("complete_commitment")).toBeInTheDocument()
  })

  it("runs a read-only tools/call and shows the result", async () => {
    vi.mocked(api.mcpStatus).mockResolvedValue(status)
    vi.mocked(api.mcpRead).mockResolvedValue(readResult)
    render(<McpPanel />)

    await screen.findByText("connected")
    await userEvent.click(screen.getByRole("button", { name: /read commitments/i }))

    expect(await screen.findByText(/tools\/call: list_commitments/)).toBeInTheDocument()
    expect(screen.getByText(/returned 1 commitment/i)).toBeInTheDocument()
    expect(screen.getByText(/send the demo/i)).toBeInTheDocument()
    expect(api.mcpRead).toHaveBeenCalledTimes(1)
  })

  it("shows a clear offline state when the HTTP probe fails", async () => {
    vi.mocked(api.mcpStatus).mockRejectedValue(
      new Error("Streamable HTTP MCP server unavailable"),
    )
    render(<McpPanel />)

    expect(await screen.findByText(/unavailable/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument()
  })
})
