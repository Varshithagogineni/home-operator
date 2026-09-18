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

**Safety gates.** Steps that involve power will not advance on "next". The dishwasher and furnace repairs both open with a gate: the walkthrough waits until the person says "done", "it's off" or "unplugged" before moving on. Nobody gets talked into reaching inside a live appliance because they said "next" out of habit.

**Where your place is kept.** Repair progress is stored per home (`home_id`, currently `"default"`), in memory. In production this is a DynamoDB item keyed by the Alexa+ customer id, so each household keeps its own place. Restarting the server clears it.

Both tools are read-only and return in milliseconds. Tool calls never call an LLM; Alexa+ does the reasoning, and this server supplies facts and state.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you if needed.
- Node.js 22.19+, only needed for MCP Inspector.

## Run it

```bash
uv sync
uv run home-operator
```

This serves two things:

| URL | What it is |
|---|---|
| `http://127.0.0.1:8000/mcp` | The MCP endpoint, Streamable HTTP, stateless, JSON responses |
| `http://127.0.0.1:8000/sim/` | A simulated Alexa+ experience for demos |

Set `PORT` or `HOST` to change the address.

## The simulator

Open `http://127.0.0.1:8000/sim/` and talk to it by typing, or click the suggested phrases. It plays the part of Alexa+: it works out which tool your words call, speaks the reply aloud, and shows the matching screen. A live panel lists every MCP call with its latency, so you can see that the answers come from the real server.

Try this sequence:

1. "Why won't my dishwasher drain?"
2. "Walk me through cleaning the filter"
3. "Next" — refused, because step 1 is a safety gate
4. "Done" — the gate clears and it moves to step 2
5. "Next", then "Say that again" — it holds your place at step 3
6. Keep going to the end; the service logs itself
7. "Anything I should take care of?" — the dishwasher is gone from the overdue list

**Voice.** The simulator speaks through the browser's speech synthesis. Pick a voice from the dropdown under the input — quality varies a lot between machines, and the joke voices macOS ships are filtered out. Replies are written to be spoken rather than read: dates become "about seven months ago" instead of "219 days ago", counts are spelled out, and each sentence is spoken separately so there is a natural pause between them. For the final demo video, Amazon Polly generative voices (`Ruth`, `Danielle`, `Matthew`) sound markedly better; a three-minute script is about 2,500 characters, well inside the free tier.

The assistant side is scripted, not an LLM. The hackathon rules allow a simulated Alexa+ experience, and everything behind it is a real MCP server.

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
