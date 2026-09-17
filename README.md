# Home Operator

**Alexa+ can read your manual. Home Operator walks you through the fix.**

Home Operator is an Alexa+ add-on, built as an [MCP](https://modelcontextprotocol.io) server, that gives hands-free help with the appliances in your home: which parts they take, what maintenance is due, and (coming soon) step-by-step repairs that keep your place.

Built for the [Build, Ship, Shape: Amazon Developer Hackathon](https://amazonappdev2026.devpost.com/) (Alexa+ track).

> **Status: Week 1–3.** A local MCP server with six working tools on **sample data**. Appliance and repair state is kept in memory and resets when the server restarts; DynamoDB replaces it later. There's **no authentication yet** (OAuth 2.1 comes next), so only run it on `127.0.0.1`.

## Tools

| Tool | Someone says | Returns |
|---|---|---|
| `get_appliance` | "What filter does the furnace take?" | Model, warranty status, replacement parts, last service. If nothing matches, the list of known appliances. |
| `get_maintenance_due` | "Anything I should take care of?" | Overdue and upcoming tasks across the home |
| `diagnose_symptom` | "The dishwasher won't drain." | Likely causes in order, each with the repair available and when it was last done |
| `start_repair` | "Walk me through cleaning the filter." | Step 1, the tools needed, a safety note, and the total number of steps |
| `navigate_repair` | "Next." "Go back." "Say that again." | The next, previous or current step, holding your place between questions |
| `log_service` | "I replaced the fridge water filter." | Records it with today's date and returns when it is next due |

Finishing the final step of a repair logs the service automatically, which is what clears it from the overdue list.

Both tools are read-only and return in milliseconds. Tool calls never call an LLM; Alexa+ does the reasoning, and this server supplies facts and state.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you if needed.
- Node.js 22.19+, only needed for MCP Inspector.

## Run it

```bash
uv sync
uv run home-operator
```

The server listens at `http://127.0.0.1:8000/mcp` using Streamable HTTP in stateless mode with JSON responses. Set `PORT` or `HOST` to change the address.

## Test it

Unit tests:

```bash
uv run pytest
```

The whole demo story end to end, against a running server:

```bash
uv run python demo.py
```

It asks why the dishwasher won't drain, walks through the seven-step fix, interrupts and resumes, logs the service, then shows what else is due.

With the official [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector), using the visual UI:

```bash
npx @modelcontextprotocol/inspector
```

Choose transport **Streamable HTTP**, enter the URL `http://127.0.0.1:8000/mcp`, and connect.

Or from the command line:

```bash
npx @modelcontextprotocol/inspector --cli --server-url http://127.0.0.1:8000/mcp --transport http --method tools/call --tool-name get_appliance --tool-arg appliance=furnace
```

Alexa+ connects using an older protocol version (`2025-03-26`). To check that handshake directly:

```bash
curl -s -X POST http://127.0.0.1:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

## Project layout

```
src/home_operator/
  server.py              MCP server and the six tool definitions
  store.py               lookup, maintenance math, diagnosis and repair steps
  data/sample_home.json  sample appliances, symptoms and repair procedures
demo.py                  runs the full story against a running server
tests/                   test_store.py, test_repair.py
FRICTION.md              developer friction log for the hackathon feedback
```

## License

[MIT](LICENSE)
