# Home Operator

**Alexa+ can read your manual. Home Operator walks you through the fix.**

Home Operator is an Alexa+ add-on, built as an [MCP](https://modelcontextprotocol.io) server, that gives hands-free help with the appliances in your home: which parts they take, what maintenance is due, and (coming soon) step-by-step repairs that keep your place.

Built for the [Build, Ship, Shape: Amazon Developer Hackathon](https://amazonappdev2026.devpost.com/) (Alexa+ track).

> **Status:** All eight tools run on Amazon Bedrock AgentCore Runtime behind a Cognito authorizer, and a Bedrock model chooses which one to call. The demo household is **five real appliances**, their repair steps, error codes and maintenance intervals taken from the manufacturers' own manuals via Amazon Bedrock and then checked by a person against the pages: the **LG WM9500HKA** washer, the **LG WSEP4727F** wall oven, the **Whirlpool GSS30C6EY** refrigerator, the **Bosch SHE53T55UC** dishwasher and the **Carrier 58STA** gas furnace. Nothing in the household is invented.

The recall check is real too. The Bosch dishwasher's model is named in CPSC's 2017 BSH recall for a power cord that can overheat, which Home Operator finds by querying the live CPSC API — no staged data.

The tools run on **Amazon Bedrock AgentCore Runtime**, behind an **Amazon Cognito** authorizer, and a **Bedrock** model chooses which one to call. See [Architecture](#architecture).

## Tools

| Tool | Someone says | Returns |
|---|---|---|
| `get_appliance` | "What filter does the furnace take?" | Model, warranty status, replacement parts, last service. If nothing matches, the list of known appliances. |
| `get_maintenance_due` | "Anything I should take care of?" | Overdue and upcoming tasks across the home |
| `diagnose_symptom` | "The dishwasher won't drain." | Likely causes in order, each with the repair available and when it was last done |
| `start_repair` | "Walk me through cleaning the filter." | Step 1, the tools needed, a safety note, and the total number of steps |
| `navigate_repair` | "Next." "Go back." "Say that again." "It's unplugged." | The next, previous or current step. Takes the `repair` id and `step_number` from the previous reply, so no state is held on the server |
| `log_service` | "I replaced the fridge water filter." | Records it with today's date and returns when it is next due |
| `add_appliance` | "I just got a Bosch dryer, model DLE3400W." | Registers it with a standard maintenance schedule for its type and queues a recall check. Ignores a model already registered |
| `prepare_pro_brief` | "It still won't drain, I need someone." | A summary for a repair professional: model, age, warranty, the problem and what was already tried today. If the model is recalled, it says to call the manufacturer first, because recall repairs are free |

Finishing the final step of a repair logs the service automatically, which is what clears it from the overdue list.

**Safety gates.** Steps that involve power will not advance on "next". The dishwasher and furnace repairs both open with a gate: the walkthrough waits until the person says "done", "it's off" or "unplugged" before moving on. Nobody gets talked into reaching inside a live appliance because they said "next" out of habit.

**Safety recalls.** `uv run home-operator-check-recalls` checks every appliance against the US Consumer Product Safety Commission's public recall data (free, no key needed) and saves matches to `data/recalls.json`. Recall notices list models as "model number beginning with", so a recall naming `SHE33T` matches a dishwasher whose full model is `SHE33T52UC`. The brand must also appear in the notice. Short brands like "GE" match only as whole words. The check runs ahead of time, not during a tool call, because it takes seconds and tools must answer in under 500 ms. Open recalls then appear in `get_appliance` and are spoken first in `get_maintenance_due`, ahead of routine maintenance. Recalls usually cover a model *and* a range of serial numbers or build dates, which a model number alone can't settle, so Home Operator says the model "is named in a recall, so it may be affected" and asks the person to check the serial number against the notice. It never claims a specific unit is recalled.

**Where your place is kept: in the conversation, not the server.** `start_repair` returns a `repair` id and a `step_number`, and `navigate_repair` takes both back. The server remembers nothing between calls.

That is not a shortcut, it is a fix. Progress used to live in the server's memory, which worked on one laptop and broke the moment the tools ran on AgentCore Runtime, where consecutive calls can land on different copies of the container — one that never saw the repair start. Carrying the place in the call removes the problem instead of coordinating state, and it matches how a voice assistant calls tools: one shot, no memory. Whether a safety gate has been cleared is implied by the step number, so walking back to a power-off step asks again, which is the behaviour you would want anyway.

**No model runs inside a tool.** A tool call is a dictionary lookup and some date arithmetic: about **2 ms** of computation. The model sits in front of the tools, never inside them, so it cannot invent a repair step — every step it can reach came from a page of a manual a person checked.

## Architecture

Two lanes, and only one of them runs while someone is talking.

```
  "my washer won't drain"
        |
        v
  +-----------------------------------------------+
  | AGENT            Strands Agents SDK           |   decides WHICH tool
  |                  Bedrock, Amazon Nova 2 Lite  |   src/home_operator/agent.py
  +----------------------+------------------------+
                         |  Authorization: Bearer <JWT>
                         |  POST .../runtimes/{arn}/invocations
                         v
  +-----------------------------------------------+
  | AMAZON COGNITO       client_credentials       |   no users, no passwords:
  |                      scope tools.invoke       |   the agent proves it is the agent
  +----------------------+------------------------+
                         |  CUSTOM_JWT authorizer validates the token
                         v
  +-----------------------------------------------+
  | AGENTCORE RUNTIME    protocol MCP             |   decides WHAT IS TRUE
  |   0.0.0.0:8000/mcp   stateless streamable     |   the eight tools, ~2 ms each
  |   the eight tools    HTTP, JSON responses     |   no model in the path
  +-----------------------------------------------+
```

**The model decides which tool to call; the tools decide what is true.** Repair
steps, intervals and part numbers are served verbatim from JSON that a person
checked against the manufacturer's manual, page by page. The model has no other
source of appliance facts, so it cannot invent a repair step.

The slow lane runs days earlier, offline: a manual PDF goes to S3, Bedrock reads
it, a person reviews every entry against the page, and the result is merged into
the home record. The CPSC recall check runs there too. See
[How a manual becomes data](#how-a-manual-becomes-data).

### What it costs in time

| | |
|---|---|
| A tool's own work | **~2 ms** |
| Round trip from a laptop to `us-east-1` | **~370 ms** median |
| First handshake of a session (AgentCore waking a runtime) | **~5 s** |

The tools are fast; the network is not. Worth stating plainly rather than quoting
the 2 ms on its own.

## Deploy it

The MCP server runs on AgentCore Runtime behind a Cognito authorizer. Both are
reproducible from scratch in an empty AWS account.

**1. Cognito, machine to machine.** No users are created and no password exists
anywhere in this flow: the agent authenticates as itself with a client id and
secret, which is what `client_credentials` is for.

```bash
REGION=us-east-1
POOL_ID=$(aws cognito-idp create-user-pool --pool-name home-operator \
  --region $REGION --query 'UserPool.Id' --output text)

# The hosted domain is what provides the /oauth2/token endpoint.
aws cognito-idp create-user-pool-domain --user-pool-id $POOL_ID \
  --domain home-operator-$(aws sts get-caller-identity --query Account --output text) \
  --region $REGION

# client_credentials needs a custom scope, so a resource server has to exist.
aws cognito-idp create-resource-server --user-pool-id $POOL_ID \
  --identifier home-operator --name "Home Operator tools" \
  --scopes ScopeName=tools.invoke,ScopeDescription="Call Home Operator MCP tools" \
  --region $REGION

aws cognito-idp create-user-pool-client --user-pool-id $POOL_ID \
  --client-name home-operator-agent --generate-secret \
  --allowed-o-auth-flows client_credentials \
  --allowed-o-auth-scopes "home-operator/tools.invoke" \
  --allowed-o-auth-flows-user-pool-client --region $REGION
```

Copy `.env.example` to `.env` and fill in the pool id, client id, client secret,
token URL and scope. `.env` is gitignored; the secret never belongs in the repo.

**2. Deploy the MCP server.**

```bash
npm install -g @aws/agentcore

agentcore create --project-name homeoperator --no-agent
cd homeoperator
agentcore add agent --name HomeOperatorMCP --type byo --language Python \
  --build CodeZip --protocol MCP \
  --code-location ../src --entrypoint home_operator/mcp_entry.py \
  --authorizer-type CUSTOM_JWT \
  --discovery-url "https://cognito-idp.$REGION.amazonaws.com/$POOL_ID/.well-known/openid-configuration" \
  --allowed-clients "$CLIENT_ID" \
  --request-header-allowlist Authorization \
  --idle-timeout 3600
agentcore deploy -y
```

`CodeZip` means the code is zipped and built by AWS, so **no Docker and no ARM64
image are needed**. Put the runtime ARN it prints into `.env` as
`AGENTCORE_RUNTIME_ARN`, and the invocation URL as `AGENTCORE_MCP_URL`:

```
https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<percent-encoded ARN>/invocations?qualifier=DEFAULT
```

**3. Talk to it.**

```bash
uv run home-operator-agent "my washer won't drain"
```

### Two things that are easy to get wrong

**Use `allowedClients`, not `allowedAudience`.** A Cognito *access* token carries
no `aud` claim, so an audience check rejects every request with an unhelpful 401.

**Turn off the MCP SDK's DNS-rebinding protection in the AgentCore entry point,
and only there.** AgentCore forwards requests with its own internal hostname, and
the SDK rejects hostnames it does not recognise with a bare `421 Misdirected
Request` — the client error says nothing about why. Inside the runtime the check
protects nothing: the container is not routable and the only way in is through
AgentCore, which has already validated the JWT. `server.py` keeps the protection
for local runs. Both are logged in [FRICTION.md](FRICTION.md).

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

Try the washer, whose data comes from LG's real manual:

1. "My washer is showing OE" — explains the error code, names LG's first check (the drain hose), then offers the drain pump filter fix
2. "Yes, walk me through it" — eight steps from LG's manual, page 40, with the source shown on screen
3. "Next" — refused: step 1 is a safety gate
4. "It's unplugged" — the gate clears
5. "Hold on, someone's at the door" — it holds your place
6. "Anything I should take care of?" — includes LG's five-year hose replacement, from page 12

Or the original sample dishwasher:

1. "Why won't my dishwasher drain?"
2. "Walk me through cleaning the filter"
3. "Next" — refused, because step 1 is a safety gate
4. "Done" — the gate clears and it moves to step 2
5. "Next", then "Say that again" — it holds your place at step 3
6. Ask something off-script mid-repair — it says it is still holding your place
7. Keep going to the end; the service logs itself
8. "It still won't drain, I need someone" — a brief for a repair pro, including what you already tried
9. "Anything I should take care of?" — the dishwasher is gone from the overdue list
10. "I just got a Bosch dryer, model DLE3400W" — added, with a maintenance schedule

**Voice.** The simulator speaks as **Ruth, an Amazon Polly generative voice**, through the server's `/speak` endpoint. Each line is synthesised once and cached in `media/cache/`, so repeats play instantly (about 16 ms versus 1.2 s for a first request) and cost nothing. Requests are capped at 600 characters. If the server can't reach AWS, `/speak` returns 503 and the simulator falls back to the browser's speech synthesis — so the project runs fully for anyone without an AWS account. The fallback voice is chosen from the dropdown under the input, which prefers premium system voices.

The simulator's earlier browser-only voice works as follows. Pick a voice from the dropdown under the input — quality varies a lot between machines, and the joke voices macOS ships are filtered out. Replies are written to be spoken rather than read: dates become "about seven months ago" instead of "219 days ago", counts are spelled out, and each sentence is spoken separately so there is a natural pause between them. For the final demo video, Amazon Polly generative voices (`Ruth`, `Danielle`, `Matthew`) sound markedly better; a three-minute script is about 2,500 characters, well inside the free tier.

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

## How a manual becomes data

Amazon Bedrock reads the PDF; a person checks the result against the manual before any of it is used. Both versions are kept in `src/home_operator/data/extracted/`:

| File | What it is |
|---|---|
| `<MODEL>.raw.json` | Exactly what Amazon Nova returned from the manual |
| `<MODEL>.json` | The reviewed version, with every correction logged under `source.review.changes`, each citing the manual page and quoting it |

Manuals over 4.5 MB go through Amazon S3:

```bash
uv run home-operator-extract manuals/<manual>.pdf --brand Whirlpool --model GSS30C6EY \
  --category refrigerator --s3-bucket <your-bucket>
```

```bash
uv run home-operator-extract manuals/<manual>.pdf --brand LG --model WM9500HKA --category "washing machine"
# review WM9500HKA.raw.json against the manual, save the corrected copy as WM9500HKA.json, then:
uv run python -m home_operator.merge
```

What review found across three manuals: the model copied all four procedures and the error-code table accurately, but where the manual was vague it **invented maintenance intervals** ("every 30 days" where LG says "periodically"), even when told not to, and on one run it **dropped two sub-steps** that a later step depends on. On the Bosch manual it invented "clean the filter system every 1825 days" where the manual gives conditions rather than a frequency, and omitted a WARNING about sharp debris. On the Whirlpool manual — scanned, with no text layer, so pages had to be read as images — it **omitted a CAUTION: IRRITANT warning** entirely, and cited pages from the manual's French half rather than the English one. Twenty-one corrections in total, each tied to a page and a quotation. Manufacturer PDFs are not in this repository; download them from the manufacturer's support site.

## AWS services used

| Service | What it does here | How |
|---|---|---|
| **Amazon Polly** (generative engine, voice Ruth) | Speaks every reply in the simulator, and narrates the demo video | `src/home_operator/voice.py` calls `synthesize_speech` through boto3; `/speak` in `server.py` serves the MP3 |
| **Amazon Bedrock** (Amazon Nova 2 Lite, Converse API) | Reads a manufacturer's PDF manual once, ahead of time, and extracts parts, maintenance intervals, error codes, symptoms and step-by-step repairs | `src/home_operator/extract.py`; run `uv run home-operator-extract manual.pdf --brand LG --model WM9500HKA --category "washing machine"`. Output is validated against a strict schema and reviewed by a person before use |
| **Amazon S3** | Holds manuals too large to send inline (over 4.5 MB); Bedrock reads them straight from the bucket | `upload_manual()` in `extract.py`, then a `s3Location` document block. The bucket is private |
| **Amazon Bedrock AgentCore Runtime** | Hosts the MCP server itself, so the tools run on AWS rather than a laptop | `src/home_operator/mcp_entry.py` is the entry point; `homeoperator/` is the AgentCore CDK project. Protocol `MCP`, `CodeZip` build, so no container image is needed |
| **Amazon Cognito** | Authenticates the agent to the MCP server, machine to machine | A user pool with a resource server and a `client_credentials` app client. `src/home_operator/auth.py` exchanges the client id and secret for a JWT and caches it. AgentCore validates it with a `CUSTOM_JWT` authorizer before proxying anything |
| **Strands Agents SDK** + **Bedrock** (Nova 2 Lite) | The agent that decides which tool to call | `src/home_operator/agent.py`. `MCPClient` points at the AgentCore endpoint with the bearer token; the model chooses the tool and speaks the reply |

To use the AWS features locally:

```bash
aws login                              # short-lived credentials; no access keys stored
aws configure set region us-east-1
uv run home-operator
```

The Python SDK needs the `[crt]` extra (`boto3[crt]`, already in `pyproject.toml`) to read `aws login` credentials. Without AWS access everything still runs, using the browser voice.

## Project layout

```
src/home_operator/
  server.py              MCP server and the eight tool definitions
  store.py               lookup, maintenance math, diagnosis, repair steps, briefs
  recalls.py             CPSC recall check (runs ahead of time, not per request)
  voice.py               Amazon Polly speech with an on-disk cache
  extract.py             Amazon Bedrock: PDF manual -> validated repair data
  merge.py               puts a reviewed extraction into the home data
  mcp_entry.py           entry point used when the server runs on AgentCore Runtime
  auth.py                Cognito machine-to-machine token, cached
  mcp_client.py          MCP session against the AgentCore endpoint
  agent.py               Strands + Bedrock agent that picks the tools
  data/extracted/        raw and reviewed extractions, with the review log
  data/sample_home.json  sample appliances, symptoms and repair procedures
demo.py                  runs the full story against a running server
homeoperator/            AgentCore CDK project (created by `agentcore create`)
tests/                   211 tests, with real CPSC recall records as fixtures
FRICTION.md              developer friction log for the hackathon feedback
```

## License

[MIT](LICENSE)
