# Devpost submission

Copy each section into the matching Devpost field. Nothing here is written for
this file: every claim is checkable in the repo.

---

## Track and mini challenges

- **Track:** Alexa+ (self-hosted MCP server)
- **Mini challenges:** AWS Builder, Open Source

---

## Elevator pitch

*(one line, under 200 characters)*

> Alexa+ can read your appliance manual. Home Operator walks you through the fix,
> step by step, hands free, from the manufacturer's own pages.

---

## What it does

Something in your house breaks. The manual is in a drawer, or a PDF on a phone
you do not want to touch with wet hands, and the answer is on page 40.

Home Operator is an Alexa+ add-on that knows the five appliances in one home and
talks you through them, out loud, and you can interrupt it at any time:

- **"My washer is showing OE."** It names the fault from the manufacturer's own
  troubleshooting table, in order of likelihood, and offers the fix.
- **"Walk me through it."** Eight steps, one at a time, waiting for you. The
  first step is a safety gate: it will not go on until you say the washer is
  off and unplugged.
- **"Tell me step four."** Refused while the washer is still plugged in: a
  safety step can't be skipped. Once it's off, jump to any step, go back, or
  say "repeat".
- **"What filter does the furnace take?"** Ask anything in the middle of a
  repair. Your place is kept.
- **"Anything I should take care of?"** Overdue maintenance worked out from a
  real service history, and it says which jobs are yours and which belong to a
  technician, because the manuals are explicit about the difference.
- **"It still won't drain, I need someone."** A brief to read to a repair
  professional: model, age, warranty, the fault, and what you already tried.
- **A photo of a new appliance's label.** Alexa+ already reads photos people
  upload; here a Nova model stands in for that step, and Home Operator's own
  `add_appliance` tool takes the hand-off: the model is registered with a
  maintenance schedule and checked against the government's recall database,
  live, in about two seconds.
- **"I replaced the fridge filter."** Logged with today's date and kept: what
  you do and add is stored in Amazon DynamoDB, so it is still there tomorrow.

And before any of that, if it matters: **"Your dishwasher's model is named in a
safety recall, so it may be affected. The power cord can overheat and catch
fire."** That is a real recall, found by querying the US Consumer Product Safety
Commission's live API, not staged for the demo.

## How it works

Two lanes, and only one runs while you are talking.

```
  "my washer won't drain"   (your voice, from the browser)
        |
        v
  AMAZON NOVA 2 SONIC  speech to speech, standing in for Alexa+
                       hears you, decides WHICH tool to call, speaks
        |
  RELAY                enforces what a prompt can only ask for
        |  Authorization: Bearer <JWT>
        v
  AMAZON COGNITO       client_credentials, no users and no passwords
        |
        v
  AGENTCORE RUNTIME    protocol MCP, CUSTOM_JWT authorizer
                       the eight tools decide WHAT IS TRUE, ~2 ms each
```

**The model decides which tool to call; the tools decide what is true.** Repair
steps, intervals and part numbers are served verbatim from JSON that a person
checked against the manufacturer's manual, page by page. The model has no other
source of appliance facts, so it cannot invent a repair step.

**A speech model speaks for itself, so the relay enforces the rules.** Tested
against the live model, Nova 2 Sonic did three things a prompt had told it not
to: it tried to clear the power-off gate when the person had only said "yes",
it started a repair, cleared the gate and advanced in one breath so the safety
warning was never spoken, and now and then it said its reasoning aloud. So the
relay passes the tools the words it actually heard, not the model's version;
allows one move through a repair per thing said; quotes each step from the
manual and checks what was spoken against it; and drops the audio of any
sentence that narrates a tool call before it is played. About two seconds from
the end of your sentence to the first word back, tool call included.

Every tool call is on screen as it happens, with what the model asked for next
to what was sent, so a viewer can see that the answers come from AgentCore and
not from the model.

**Measured, not just claimed.** In 43 spoken conversations with the live link,
the washer's power-off gate held every time someone said "next", "tell me step
four" or a bare "yes please" (30 of 30), and opened every time they said "okay,
it's unplugged" (10 of 10). The safety warning and every repair line were spoken
word for word in all 40 completed runs. The harness is `evals/voice_safety.py`.

**The slow lane runs days earlier, offline.** A manual PDF goes to Amazon S3,
Amazon Bedrock reads it and returns structured steps, intervals and symptoms,
and then a person checks every entry against the page. Every correction is
logged with the page number and a quote of what the manual actually says: **46
of them across five appliances.** Raw and reviewed files are kept side by side
in the repo, so the difference is auditable.

## What is real, and what stands in

The Alexa+ add-on toolkit is a partner-only preview - confirmed twice by Amazon
staff in the hackathon forum - so there is no way to run this on a real device.
The rules explicitly allow a simulated Alexa+ experience "built using any AI or
agentic tool of their choice", and that is what the browser front end is: an
Echo Show style screen, with Amazon Nova 2 Sonic standing in for Alexa+'s voice
and orchestrator. The screen says so. The original text simulator, with a
Strands agent on Nova 2 Lite, is kept alongside it.

Everything behind it is real: the voice is hosted on AWS and needs nobody's
login to run, the MCP server runs on AgentCore Runtime, the
Cognito authorizer validates every call, the appliances are real models, the
manual data is traceable to a page, and the recall came from the government's
own API.

The household is a demo household. The appliances are not the builder's own,
and the service history is seeded.

---

## Built with

`amazon-nova-sonic` `amazon-bedrock` `amazon-bedrock-agentcore` `strands-agents`
`amazon-cognito` `amazon-dynamodb` `amazon-ec2` `amazon-cloudfront` `aws-iam` `aws-systems-manager`
`amazon-polly` `amazon-s3` `model-context-protocol` `python` `starlette`
`uvicorn` `websockets` `javascript` `cpsc-api`

---

## Links

- **Try it:** https://d6zzi2o2me078.cloudfront.net/?code=9bad96-b7c7a5 (Chrome;
  allow the microphone, then talk. Tap ? for things to say.)
- **Repo:** https://github.com/Varshithagogineni/home-operator
- **Open source project:** https://github.com/Varshithagogineni/cpsc-recall-check
- **Video:** https://youtu.be/YnIsw8vN3vo

---

## Product feedback

*(The full log, with reproduction steps, is FRICTION.md in the repo: 14 entries
written as they happened, each with the task, steps, expected and actual result,
severity, workaround and suggestion.)*

Devpost asks five things of each tool: what it was used for, what worked, what
needs work, how onboarding went, and whether we would build with it again. Each
tool is answered on its own below; the longer write-ups after them are the
"needs work" items worth the most to the teams.

### Amazon Bedrock AgentCore Runtime (with the AgentCore CLI and CDK)

- **Used for:** hosting the MCP server, the eight tools the voice calls, behind
  a `CUSTOM_JWT` authorizer, built with `CodeZip`. Environment variables and an
  extra IAM policy give it the household table in DynamoDB.
- **Worked well:** a Python MCP server deployed with no Docker and no ARM image,
  redeployed in one command, and `agentcore deploy --diff` showed exactly which
  permission and setting would change before anything did.
- **Needs work:** a deployed server fails with a bare `421` (the MCP SDK's
  DNS-rebinding check rejects AgentCore's proxy host); AgentCore health-checks
  `/ping`, which no MCP SDK serves; every session close logs a `404`; and the
  documented MCP samples no longer run on the current SDK.
- **Onboarding:** the samples failing on a fresh install, then the 421, which
  only CloudWatch explained. Once past those, nothing else went wrong.
- **Again?** Yes. It is the most direct way we found to put an MCP server on AWS
  behind real authentication.

### Amazon Nova 2 Sonic

- **Used for:** the voice. It hears the person, decides which tool to call, and
  speaks, and can be interrupted. `src/home_operator/sonic.py`.
- **Worked well:** tool use across a full eight-step repair; about two seconds
  from the end of a sentence to the first word back, tool call included; natural
  interruption; speech-start and speech-end events that made the on-screen
  listening and thinking states easy; and, given the exact line, it spoke every
  repair step word for word (40 of 40 runs).
- **Needs work:** it chains tool calls in one turn (start a repair, clear its
  safety gate and advance, in one breath); it fills tool arguments with its own
  paraphrase of what the person said; and now and then it speaks its reasoning.
  Each needed code in a relay. Bidirectional streaming is not in boto3, and the
  Developer Preview SDK does not read `aws login` credentials.
- **Onboarding:** finding the separate preview SDK, and open re:Post reports that
  made tool use look riskier than it turned out to be.
- **Again?** Yes, with the relay. An option for at most one tool call per turn
  would remove most of it.

### Amazon Bedrock with Nova 2 Lite (document understanding, photo reading)

- **Used for:** reading each manufacturer's PDF once and extracting steps, error
  codes, intervals and parts (`extract.py`); and reading the brand and model off
  a photo of an appliance's rating label (`photo.py`).
- **Worked well:** it read a 92-page manual, and a 44-page one that is only
  scanned images, and copied every procedure accurately. It reads a rating
  label in about a second.
- **Needs work:** it invents figures where a manual is vague ("every 30 days"
  where LG says "periodically"), dropped two safety warnings, and cited the
  French half of a bilingual manual. The content filter once blocked its own
  output, reported only in English prose.
- **Onboarding:** a new account cannot call Bedrock for up to two hours, and the
  error does not say that waiting is the fix.
- **Again?** Yes, for extraction a person then checks. 46 corrections say it
  should never be trusted unreviewed for safety steps.

### Amazon Cognito

- **Used for:** machine-to-machine sign-in to the tools: `client_credentials`,
  no users and no passwords.
- **Worked well:** exactly the right shape for one service proving who it is.
- **Needs work:** `client_credentials` needs a custom scope, so a resource server
  must exist first; and a Cognito access token has no `aud` claim, so the
  natural `allowedAudience` check rejects every call. `allowedClients` works.
- **Onboarding:** quick once those two were known.
- **Again?** Yes.

### Amazon DynamoDB

- **Used for:** a household's changes (logged jobs, added appliances), one item
  per household, read on every call so every AgentCore copy agrees.
- **Worked well:** `list_append` updates, on-demand billing, and a one-resource
  CloudFormation template.
- **Needs work:** the boto3 resource API returns numbers as `Decimal`, which
  breaks date arithmetic until converted.
- **Onboarding:** minutes.
- **Again?** Yes.

### Amazon EC2, CloudFront, IAM, Systems Manager and CloudFormation

- **Used for:** hosting the voice app on a public HTTPS link (`deploy/hosted.yaml`).
- **Worked well:** an IAM role means the app never depends on anyone's login;
  CloudFront's managed policies carry WebSockets and cookies with no custom
  config; SSM Run Command ships updates with no SSH.
- **Needs work:** `aws login` sessions lapse after a few hours, and an app run
  from a laptop simply stops; nothing in the CLI says so up front.
- **Onboarding:** straightforward.
- **Again?** Yes.

### Strands Agents SDK and Amazon Polly

- **Used for:** the original text simulator: a Strands agent on Nova 2 Lite
  picking tools, Polly's generative voice Ruth speaking.
- **Worked well:** Strands' `MCPClient` talked to the AgentCore endpoint with a
  bearer token unchanged; Polly's generative voice was the best of the TTS
  voices we compared.
- **Needs work:** `MCPClient.call_tool_sync` paid an AgentCore session wake-up on
  every call: 3.6 to 8.3 seconds, against 0.3 to 0.45 with one held session.
- **Again?** Yes, with session reuse documented.

### Alexa+ add-on documentation and CLI

- **Used for:** designing the add-on. The documented model, an add-on as tools
  Alexa+ calls, is exactly why this is an MCP server.
- **Needs work:** `npm install -g @alexa-ai/cli` returns 404 on public npm, and
  the testing docs describe a simulator participants cannot use. Amazon staff
  confirmed in the forum that the toolkit is partner-only; that should be on the
  documentation page.
- **Onboarding:** not possible for a participant, which is why the front end is
  a simulator.
- **Again?** Yes, the day it opens. This is the first thing we would put on it.

### The one that matters most: a model will talk past its tools, and no prompt stops it

Amazon Nova 2 Lite, choosing MCP tools for a spoken repair walkthrough, did all
three of these. Each survived explicit instructions in the system prompt **and**
in the tool descriptions:

1. Asked "want me to walk you through it?", the person said **"yes please"**. The
   model turned that into `navigate_repair(action="done")` and cleared a
   power-off **safety gate**, moving to the step that opens a drain filter. The
   person had agreed to a repair, not confirmed a washer was unplugged.
2. On a later turn it called **no tool at all** and said *"Now open the drain
   pump filter cover"* from its own knowledge - a repair instruction, spoken
   aloud, that came from no manual.
3. Told by a tool that the washer still had to be unplugged
   (`awaiting_confirmation: true`), it said *"Now open the drain filter cover"*
   anyway, contradicting the result it had just received, in wording that is not
   in the LG manual.

In a voice product these are physical-safety failures, not formatting problems.
They are now prevented in code: a gate clears only on the person's own words
about the machine, checked server-side; agreeing to a repair is matched in the
backend and answered by calling the tool directly; and any turn touching a
repair tool is spoken from the tool's text rather than the model's. Thirty tests
pin it.

**What would have helped:** a supported way to constrain a turn to tool-grounded
output, so a model cannot answer a domain question without calling a tool. For
agents over MCP this is the common safety requirement, and every builder is
currently re-implementing it. Second, the Nova guidance should say plainly that
tool results are not authoritative to the model and that safety-critical state
must be enforced in the tool, not the prompt.

### AgentCore Runtime: an opaque 421 that took CloudWatch to diagnose

A correctly deployed MCP server returned `MCPError: Received error (421) from
runtime` on every call. The cause was only visible in CloudWatch: `Invalid Host
header: cell01.us-east-1.prod.arp.kepler-analytics.aws.dev`. The MCP SDK's
DNS-rebinding protection rejects AgentCore's internal proxy hostname, then
returns 421. The documented MCP hosting walkthrough never mentions it.

**Suggestion:** document it, or forward the client-facing host so the SDK's
default passes. Surfacing the container's response body in the client error
would have saved an hour.

Two smaller ones alongside it: AgentCore health-checks `/ping`, which no MCP SDK
serves, so clean deployments log 404s that look like faults; and ending a session
logs `Session termination failed: 404` every time, because `DELETE` appears
unimplemented.

### The AWS MCP samples do not run on the current SDK

Every code sample on "Deploy MCP servers in AgentCore Runtime" fails on a fresh
`pip install mcp`. `FastMCP` is now `MCPServer`, `streamablehttp_client` is
`streamable_http_client`, the client context manager yields two values rather
than three, and headers moved to an `http_client` you construct yourself. A
reader cannot tell whether the error is their mistake or documentation drift.
**Pin the SDK version in the docs, or update the samples.**

### Strands MCPClient pays a session wake-up on every call

Against a deployed AgentCore runtime, four identical `call_tool_sync` calls took
8289, 4572, 4641 and 3581 ms. The same endpoint with the MCP SDK's own client,
holding one session open, answers in **317-449 ms**. Roughly a cold session
every time, which is unusable for anything interactive. Worked around by holding
a session on a background event loop. **Document whether `MCPClient` reuses a
transport session, and expose the session so a caller can reuse it.**

### Bedrock document understanding: faithful on steps, inventive on numbers

Across four manuals Nova 2 Lite copied procedures accurately and **invented
figures wherever a manual was vague**: "clean the filter every 30 days" where LG
says "periodically", and "every 1825 days" where Bosch gives no interval at all.
It also dropped safety warnings (an irritant CAUTION, a sharp-debris WARNING),
and on a bilingual manual cited every page from the French half - correct
content, misleading citations, a fixed 22-page offset.

Two more: on a new AWS account Bedrock returns "account is not authorized" for
up to two hours with no indication that waiting is the fix; and the content
filter blocked the model's **own output** while it was reading a Whirlpool
manual, returning a plain-English message rather than a distinguishable stop
reason, so callers must pattern-match English to know whether to retry.

**Suggestion:** an explicit instruction in the document-understanding guidance to
return null rather than infer a missing interval would remove a whole class of
error. For multilingual documents, say which language section to cite.

### Amazon Nova 2 Sonic: first ruled out, then adopted

Speech-to-speech was the obvious fit for a hands-free product, and was first
ruled out on paper: `InvokeModelWithBidirectionalStream` is not in boto3 and
needs `aws-sdk-bedrock-runtime`, which AWS's own docs label Developer Preview;
and three tool-use defects were open on re:Post (`promptStart` rejected when
`toolConfiguration` is included, a hang when chaining tools, an infinite loop
with multiple tools).

Tested against the live model instead, none of the three reproduced across a
full eight-step repair. **What did go wrong is worth fixing in the model:** it
chains tool calls within one user turn (start a repair, clear its safety gate
and advance, in one breath), it fills tool arguments with its own paraphrase of
what the user said, and it occasionally speaks its reasoning aloud, tool names
included. Each needed code in a relay rather than a prompt. Two smaller
papercuts: the preview SDK does not read `aws login` credentials, so the relay
signs with boto3's credential chain; and a spoken error code arrives as letters
("u e"), which an index keyed on "UE" misses.

**Suggestion:** an option to allow at most one tool call per user turn, and a
documented way to mark a tool argument as "the user's verbatim words", would
remove most of the relay. See FRICTION.md for the details.

### Alexa+ add-on tooling

The documented setup step `npm install -g @alexa-ai/cli` returns **404 on public
npm**, with no mention of a private registry or access request. The testing
documentation describes a web simulator and says "you must deploy your add-on
before you can test it", neither of which a participant can do. Amazon staff
confirmed in the forum that the toolkit is partner-only. That answer is fine -
but it should be on the documentation page, not only in a forum thread, because
the docs read as though the path is open to anyone.

---

## Open Source mini challenge

- **GitHub username:** Varshithagogineni
- **Project repository:** https://github.com/Varshithagogineni/cpsc-recall-check
- **Contribution URL:** https://github.com/Varshithagogineni/cpsc-recall-check/commits/main

**What it is.** `cpsc-recall-check` is a small MIT-licensed Python library that
checks whether a product is named in a US Consumer Product Safety Commission
recall. No API key, no account, no dependencies, Python 3.10+.

**How it works.** The CPSC publishes every recall at `saferproducts.gov`, free
and open. Fetching them is easy; deciding whether one is about *your* dishwasher
is not, because recalls are written for people to read. A notice says "model
numbers beginning with SHE33T, SHE43R, SHE53T", names the brand somewhere in a
paragraph, and mentions unit counts, years and a phone number - all of which look
like model numbers to naive code. So the library matches **model prefixes**,
requires the **brand as a whole word** (without which "GE" matches "range",
"storage" and "damage"), and ignores any code shorter than five characters or
lacking both letters and digits.

**Why it matters.** There is deliberately no `is_recalled`. A recall names
*models*; whether one particular unit is included almost always depends on a
serial number only its owner can read off the label. The result is called
`may_be_affected` and carries the code the notice actually printed, so a caller
has to go out of their way to tell someone their working appliance is recalled.
Telling someone that when it may not be true is its own kind of harm, and a
library shape can prevent it. A test asserts `is_recalled` does not exist.

Twenty-one tests run against real CPSC records, including the 2017 BSH
dishwasher recall. It was extracted from Home Operator during the hackathon
window, where it answers the question worth asking before anyone opens up a
machine.
