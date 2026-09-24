# Friction log

Problems hit while building Home Operator, logged as they happen for the
hackathon's product feedback. Each entry follows the submission format.

## Template

```
### <short title>
- **Date:**
- **Tool / API:**
- **Task attempted:**
- **Steps taken:**
- **Expected:**
- **Actual:**
- **Severity:** Blocker / High / Medium / Low
- **Workaround:**
- **Suggestion:**
```

---

### Alexa AI CLI package is not on the public npm registry
- **Date:** 2026-09-15, re-checked 2026-09-17
- **Tool / API:** Alexa+ MCP Toolkit, `@alexa-ai/cli`
- **Task attempted:** Install the Alexa AI CLI to register and test an MCP add-on.
- **Steps taken:** Followed "Set Up Your Development Environment" in the Alexa+ add-on docs, which says to run `npm install -g @alexa-ai/cli` (Node.js 24+). Checked the package with `npm view @alexa-ai/cli version`.
- **Expected:** The package installs and `alexa-ai --version` prints a version.
- **Actual:** `npm error 404 Not Found - GET https://registry.npmjs.org/@alexa-ai%2fcli`. The docs don't mention a private registry, access request, or allowlist.
- **Severity:** Blocker for the documented add-on path.
- **Workaround:** Built and tested the MCP server locally with the official MCP Inspector (`@modelcontextprotocol/inspector`), then built a self-hosted simulated Alexa+ front end for the demo.
- **Resolved:** 2026-09-18 on the Devpost forum. Emerson Sklar (Amazon): *"No, there is no way for participants to get access to the toolkit or simulator. A self-built simulator or other front end for demoing are certainly options though!"* and *"The Alexa+ Add-on toolkit and web simulator is in preview with select partners, and is not available to participants in the hackathon."*
- **Root cause, confirmed 2026-09-21:** Another participant followed the official setup guide and got `AssumeRole AccessDenied` on a developer-tools IAM role in Amazon's own AWS account. The guide assumes a step that is easy to miss and impossible for outsiders: the developer's AWS account ID must first be shared with an Alexa Solutions Architect, who grants access to that role. The CLI is distributed behind that grant, which is why it returns 404 on public npm. Amazon then confirmed: *"Access to the Alexa+ developer tools will not be granted to hackathon participants, nor will setting that AWS account role... you are not expected to use those tools with your hackathon submission."* An Amazon staff member also redirected that participant to this forum thread, so the question was reaching others with the same problem.
- **Suggestion:** The documentation gives no hint of this. "Set Up Your Development Environment" reads as a public quickstart: it lists `npm install -g @alexa-ai/cli`, a version check, and `alexa-ai configure`, with no preview banner, no eligibility note and no access request link. Three separate hackathon participants asked the same question on the forum within a day, which suggests the cost is widespread. Please add a preview notice at the top of every MCP Toolkit page naming who can get access and how, and state the Solutions Architect step as a hard prerequisite in step one of the setup guide rather than an assumption. An opaque `AccessDenied` on a role the developer has never heard of should be a documented, expected outcome with a link to the access process — not something each developer has to diagnose on a forum. Publishing a stub package to npm whose postinstall message explains the preview status would end the confusion outright.

### Docs describe testing paths that participants cannot use
- **Date:** 2026-09-18
- **Tool / API:** Alexa+ MCP add-on docs, "Test add-ons" page
- **Task attempted:** Plan how to test and demo an add-on without a physical Echo device.
- **Steps taken:** Read the testing page, which describes a web simulator ("interact with your add-on through text, preview visual responses on simulated device screens") and optional routing to a physical device.
- **Expected:** That the documented simulator is the supported way to test, as the page implies.
- **Actual:** The web simulator is partner-only, so none of the documented end-to-end testing applies to hackathon participants. The page also says "You must deploy your add-on before you can test it", which is impossible without the gated CLI.
- **Severity:** High.
- **Workaround:** Validated tool schemas and calls with MCP Inspector, and built a self-hosted simulator that speaks replies and renders the cards.
- **Suggestion:** Mark clearly which testing paths need preview access and which don't. MCP Inspector works well for everyone and deserves a first-class place in the docs, ideally with an Alexa-specific checklist of what a good add-on response looks like.

### The Alexa+ track's "Agent Skills" resource points at developer tooling, not a submittable artifact
- **Date:** 2026-09-18
- **Tool / API:** Hackathon Resources page, Alexa+ track
- **Task attempted:** Work out what an "Agent Skill" is, since the rules offer it as an alternative to building an MCP server.
- **Steps taken:** Followed the only two Alexa+ track resources. "Build with Agent Skills" links to `apps.extensions.modelcontextprotocol.io/api/#build-with-agent-skills`.
- **Expected:** A definition of an Agent Skill as something you build and submit for the Alexa+ track, with its structure and how Alexa+ loads it.
- **Actual:** That page describes Agent Skills as helpers *for AI coding assistants* — tools that scaffold or migrate MCP Apps during development, installed through a plugin marketplace. It never explains an Agent Skill as a runtime capability Alexa+ would call. The Alexa+ add-on docs mention "the add-on Agent Skill (agentic onboarding experience)" without defining it either.
- **Severity:** Medium. It cost an hour, and anyone choosing the Agent Skill path over MCP has no specification to follow.
- **Workaround:** Built a self-hosted MCP server, which is unambiguous and well specified.
- **Suggestion:** Either define an Agent Skill for the Alexa+ track properly — file structure, how it is registered, how Alexa+ invokes it, with one worked example — or drop it from the rules and point people to MCP. Two links is also thin for a track worth $44,000; the Fire TV track gets seven sample repos and an e-book, while Alexa+ gets a protocol spec and a page about coding-assistant plugins.

### `aws login` credentials need an undocumented extra in the Python SDK
- **Date:** 2026-09-21
- **Tool / API:** AWS CLI `aws login`, boto3 / botocore 1.43.99
- **Task attempted:** Call Amazon Polly from the MCP server's Python code using the short-lived credentials created by `aws login`.
- **Steps taken:** Signed in with `aws login` (worked in the CLI), then `pip install boto3` and created a client.
- **Expected:** The SDK picks up the `aws login` session automatically. The launch announcement says the credentials "work across local development tools like the AWS CLI, AWS Tools for PowerShell and AWS SDKs."
- **Actual:** `MissingDependencyException: Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]"`.
- **Severity:** Low. The error message is excellent — it names the exact fix.
- **Workaround:** Installed `boto3[crt]` instead of `boto3`.
- **Suggestion:** Mention the `[crt]` extra in the `aws login` announcement and the "Login for AWS local development" guide, under "Using with the SDKs". A beginner following the announcement will hit this on their first SDK call.

### New AWS accounts can't call Bedrock for up to two hours
- **Date:** 2026-09-21
- **Tool / API:** Amazon Bedrock Converse API, Amazon Nova 2 Lite
- **Task attempted:** First Bedrock call, a one-sentence text prompt, from an account created for this hackathon.
- **Steps taken:** Created the account, redeemed the hackathon's $150 credits, signed in with `aws login`, called `converse` on `us.amazon.nova-2-lite-v1:0`. Amazon Polly calls from the same session worked immediately.
- **Expected:** A response, since Amazon's own models don't need a model-access request.
- **Actual:** `AccessDeniedException: Your account is currently being verified. Verification normally takes less than 2 hours.`
- **Severity:** Medium for a hackathon: many entrants will create a fresh AWS account for the credits and hit this on their first AI call.
- **Workaround:** Wrote and tested the extractor against a stand-in client while waiting.
- **Suggestion:** Mention the new-account verification window on the hackathon's AWS credits page and in Bedrock's getting-started guide, and show verification status in the Bedrock console so developers don't assume their permissions are wrong.

### Bedrock's content filter blocked its own output while reading an appliance manual
- **Date:** 2026-09-22
- **Tool / API:** Amazon Bedrock Converse, Amazon Nova 2 Lite
- **Task attempted:** Extract repair steps from a Whirlpool refrigerator manual (scanned, 44 pages, read from Amazon S3).
- **Steps taken:** Same call that had already worked on two LG manuals.
- **Expected:** Structured JSON, as before.
- **Actual:** The reply was the single line `- The generated text has been blocked by our content filters.` An identical retry a minute later succeeded, so the block is not deterministic. Appliance manuals quote child-entrapment and suffocation warnings, which is the likeliest trigger.
- **Severity:** Medium. A pipeline that trusted the reply would have stored that sentence as data.
- **Workaround:** The extractor validates every reply against a schema, saves unusable replies for inspection, and the run is simply repeated.
- **Suggestion:** Return a distinct error code for filtered output rather than plain text in the message body, so callers can retry programmatically instead of pattern-matching English. A `stopReason` of `content_filtered` on the response would be enough.

### Nova cites pages from the wrong language half of a bilingual manual
- **Date:** 2026-09-22
- **Tool / API:** Amazon Bedrock Converse, Amazon Nova 2 Lite, document input
- **Task attempted:** Ask for the page number where each procedure appears, in a manual that prints English then the same content in French.
- **Steps taken:** Prompted for "the page number printed on the manual page".
- **Expected:** Pages from the English half, since the request and output are English.
- **Actual:** Every citation pointed at the French half (page 37 instead of 15). The extracted steps were correct English translations of the French text, so the content was right and only the citations were misleading.
- **Severity:** Low, but it would have put wrong references on screen.
- **Workaround:** Checked one procedure by rendering pages as images, found the fixed 22-page offset, and re-cited all of them.
- **Suggestion:** Worth a note in the document-understanding guide: for multilingual documents, state the language section you want cited, since the model may ground itself in either.

### AgentCore Runtime returns 421 because the MCP SDK rejects its proxy's Host header
- **Date:** 2026-09-23
- **Tool / API:** Amazon Bedrock AgentCore Runtime (protocol MCP), MCP Python SDK 2.2.0
- **Task attempted:** Call a deployed MCP server through the AgentCore invocation endpoint.
- **Steps taken:** Deployed with `agentcore deploy` (CodeZip, `protocol: MCP`, `CUSTOM_JWT` authorizer against a Cognito pool). The container started cleanly and served `/mcp` locally. Connected with the SDK's `streamable_http_client` and a valid Cognito bearer token.
- **Expected:** `initialize` succeeds, since auth passed and the server is healthy.
- **Actual:** `MCPError: Received error (421) from runtime. Please check your CloudWatch logs for more information.` The client has no way to tell this apart from a server crash. CloudWatch showed the real cause: `Invalid Host header: cell01.us-east-1.prod.arp.kepler-analytics.aws.dev` — the SDK's DNS-rebinding protection rejecting AgentCore's internal proxy hostname, then returning 421 Misdirected Request.
- **Severity:** Blocker, and hard to diagnose: the documented MCP hosting walkthrough never mentions it.
- **Workaround:** Pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to `streamable_http_app` in the AgentCore entry point only. Inside the runtime the check protects nothing — the container is not routable and the only way in is through AgentCore, which has already validated the JWT — but the local entry point keeps it enabled.
- **Suggestion:** Either document this in "Deploy MCP servers in AgentCore Runtime", or have the runtime forward the client-facing host so the SDK's default passes. Surfacing the container's response body in the client error would have saved an hour of guessing.

### AgentCore health-checks /ping, which an MCP server does not serve
- **Date:** 2026-09-23
- **Tool / API:** Amazon Bedrock AgentCore Runtime (protocol MCP)
- **Task attempted:** Deploy an MCP server built with the official SDK, unmodified.
- **Steps taken:** Read CloudWatch logs after deployment.
- **Expected:** No unexplained requests, since the MCP protocol contract only describes `/mcp`.
- **Actual:** Repeated `GET /ping HTTP/1.1" 404 Not Found` alongside the `/mcp` traffic. The runtime still worked, so it is cosmetic, but it looks like a fault and no MCP SDK serves `/ping` by default.
- **Severity:** Low.
- **Workaround:** Added a `/ping` route returning `{"status": "ok"}` to the AgentCore entry point.
- **Suggestion:** State in the MCP protocol contract whether `/ping` is required, optional, or ignored, so implementers know whether to add it.

### AWS MCP examples use the v1 Python SDK API, which no longer exists in v2
- **Date:** 2026-09-23
- **Tool / API:** AgentCore MCP documentation, MCP Python SDK 2.2.0
- **Task attempted:** Follow the documented client and server examples with the current SDK.
- **Steps taken:** Copied the sample code from "Deploy MCP servers in AgentCore Runtime".
- **Expected:** The samples run against the current `mcp` package on PyPI.
- **Actual:** Three separate breaks: `from mcp.server.fastmcp import FastMCP` (v2 uses `MCPServer` from `mcp.server.mcpserver`), `streamablehttp_client` (renamed `streamable_http_client`), and the client context manager now yields two values rather than three, so the documented `as (read, write, _)` raises `ValueError: not enough values to unpack`. Headers also moved from a positional argument to an `http_client` you construct yourself.
- **Severity:** Medium — every sample on the page fails on a fresh `pip install mcp`.
- **Workaround:** Read the installed package's signatures with `inspect.signature` and port the samples.
- **Suggestion:** Pin the SDK version in the docs, or update the samples to v2. A reader cannot tell whether the error is their mistake or documentation drift.

### Strands MCPClient.call_tool_sync pays an AgentCore session wake-up on every call
- **Date:** 2026-09-23
- **Tool / API:** Strands Agents SDK 1.57.0 (`strands.tools.mcp.MCPClient`), Amazon Bedrock AgentCore Runtime
- **Task attempted:** Call one MCP tool repeatedly on a deployed AgentCore runtime, without a model in the loop, for a latency-sensitive path ("next", "back", "repeat" during a repair walkthrough).
- **Steps taken:** Built `MCPClient(url=..., headers={"Authorization": ...})`, called `start()`, then `call_tool_sync` four times in a row with the same arguments and timed each call.
- **Expected:** The first call pays AgentCore's session start-up, later calls reuse the session. A separate measurement with the MCP SDK's own `streamable_http_client`, holding one session open against the same endpoint with the same token, answers in **317-449 ms** (median 366 ms).
- **Actual:** 8289 ms, 4572 ms, 4641 ms, 3581 ms. Every call costs roughly what a cold session costs, about ten times the round trip of a reused session, which suggests the session is not being reused across calls.
- **Severity:** High for anything interactive. Four seconds to answer "next" is unusable when someone is standing at an appliance.
- **Workaround:** Hold an MCP session open on a background event loop and call `session.call_tool` directly for the latency-sensitive path, leaving the Strands client for the model's own tool use. That path now answers in 0.3-0.9 s end to end, including the agent-layer overhead. See `FastLane` in `src/home_operator/chat.py`.
- **Suggestion:** Document whether `MCPClient` is expected to reuse a transport session between `call_tool_sync` calls, and expose the underlying session so a caller can reuse it deliberately instead of building a second client. A note in the Strands MCP docs about remote servers with expensive session start-up would have saved the measurement.

### Ending an MCP session against AgentCore logs a 404 on every close
- **Date:** 2026-09-23
- **Tool / API:** Amazon Bedrock AgentCore Runtime (protocol MCP), MCP Python SDK 2.1.1
- **Task attempted:** Close an MCP client session cleanly.
- **Steps taken:** Exited the `streamable_http_client` context manager normally.
- **Expected:** Either a clean shutdown, or a documented note that session termination is not supported.
- **Actual:** `Session termination failed: 404` printed on every close. Nothing is broken, but the message appears in demo output and logs, and reads like a fault. The MCP spec's `DELETE` on the session endpoint appears unimplemented by the runtime.
- **Severity:** Low.
- **Workaround:** None needed; it is noise.
- **Suggestion:** Implement `DELETE` as a no-op returning 200, or state in the MCP protocol contract that termination is unsupported so clients can stop logging it as a failure.

### Amazon Nova 2 Sonic was evaluated for speech-to-speech and not adopted
- **Date:** 2026-09-23
- **Tool / API:** Amazon Nova 2 Sonic (`amazon.nova-2-sonic-v1:0`), `aws-sdk-bedrock-runtime` (Developer Preview), Amazon Polly
- **Task attempted:** Replace the Polly text-to-speech layer with a true speech-to-speech model that can also call the MCP tools.
- **Steps taken:** Confirmed the model is `ACTIVE` in the account with `SPEECH` input and `SPEECH`/`TEXT` output. Read the bidirectional streaming and tool configuration guides, and searched for current reports of tool use working end to end.
- **Expected:** A supported path to speech in, speech out, with tool calling.
- **Actual:** Adoption was blocked by four things together. `InvokeModelWithBidirectionalStream` is not in boto3 and needs `aws-sdk-bedrock-runtime[awscrt]`, which AWS's own documentation labels Developer Preview and says not to use for production workloads. Three tool-use defects are open on re:Post: `promptStart` rejected when `toolConfiguration` is included, a hang when chaining tools, and an infinite tool-calling loop with multiple tools. The available voices do not include Polly's generative "Ruth", which this project had already chosen after listening to samples. And because the model returns raw PCM, the SSML `<break>` pacing written into every spoken line would be discarded.
- **Severity:** Medium. Nothing is broken; the feature is simply not adoptable on a deadline.
- **Workaround:** Kept Polly generative Ruth for speech, with the browser's own speech recognition for input. The tools stay reachable by any model because they are plain MCP.
- **Suggestion:** The three re:Post tool-use reports are the blocker worth fixing first: speech-to-speech without reliable tool calling cannot drive an assistant that does anything. Publishing a known-issues list for Nova 2 Sonic tool use, and a supported non-preview client path, would make it adoptable.

### Nova 2 Lite speaks repair steps it was never given, including past a safety gate
- **Date:** 2026-09-24
- **Tool / API:** Amazon Bedrock, Amazon Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`), via Strands Agents with MCP tools
- **Task attempted:** Have the model choose tools for a spoken repair walkthrough, where every repair step must come from a manufacturer's manual and a safety gate must hold until the person confirms the appliance is switched off.
- **Steps taken:** System prompt states, in its own section, that every appliance fact must come from a tool, that a step must be said as written, and that a repair must not start until asked. The tool description for `start_repair` repeats the last point. Ran the same five-turn conversation after each change.
- **Expected:** The model routes to tools and quotes what they return.
- **Actual:** Three distinct failures, none fixed by instructions.
  1. Asked "want me to walk you through it?", the person said "yes please". The model called `navigate_repair` with `action: "done"` and cleared the power-off safety gate, moving to the step that opens a drain filter. The person had agreed to a repair, not confirmed that a washer was unplugged.
  2. On a later "yes please", the model called **no tool at all** and said "Now open the drain pump filter cover" from its own knowledge. That is a repair instruction, spoken aloud, that came from no manual.
  3. Told by the tool that the washer still had to be unplugged (`awaiting_confirmation: true`), the model said "Now open the drain filter cover" anyway - contradicting the tool result it had just received, in wording that is not in the LG manual.
- **Severity:** High. In a voice product these are physical-safety failures, not formatting problems.
- **Workaround:** Stopped relying on instructions for anything that matters. A safety gate now clears only on the person's own words about the machine, checked server-side, so `action: "done"` by itself does nothing. Agreeing to an offered repair is matched in the backend and answered by calling `start_repair` directly. Any turn that touches a repair tool is spoken from the tool's text rather than the model's, and a turn that calls no tool during a repair is discarded and the current step re-read. Thirty tests pin this.
- **Suggestion:** Two things would have helped a great deal. First, a supported way to constrain a turn to tool-grounded output, so a model cannot answer a domain question without calling a tool: for agents over MCP this is the common safety requirement, and every builder is currently re-implementing it. Second, the guidance for Nova 2 Lite should say plainly that tool results are not authoritative to the model and that safety-critical state must be enforced in the tool, not the prompt. We found this by testing; a smaller team might ship it.
