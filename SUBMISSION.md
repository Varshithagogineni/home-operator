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
`amazon-cognito` `amazon-ec2` `amazon-cloudfront` `aws-iam` `aws-systems-manager`
`amazon-polly` `amazon-s3` `model-context-protocol` `python` `starlette`
`uvicorn` `websockets` `javascript` `cpsc-api`

---

## Links

- **Try it:** https://d6zzi2o2me078.cloudfront.net/?code=9bad96-b7c7a5 (Chrome;
  allow the microphone, then talk. Tap ? for things to say.)
- **Repo:** https://github.com/Varshithagogineni/home-operator
- **Open source project:** https://github.com/Varshithagogineni/cpsc-recall-check
- **Video:** *(add before submitting)*

---

## Product feedback

*(The full log, with reproduction steps, is FRICTION.md in the repo: 14 entries
written as they happened, each with the task, steps, expected and actual result,
severity, workaround and suggestion.)*

### Which developer tools, APIs and SDKs did you use, and for what?

| Tool | What it does in Home Operator |
|---|---|
| **Amazon Bedrock AgentCore Runtime** + the AgentCore CLI and CDK | Hosts the MCP server: eight tools, protocol MCP, `CodeZip` build, `CUSTOM_JWT` authorizer. `homeoperator/` is the CDK project; `src/home_operator/mcp_entry.py` is the entry point |
| **Amazon Nova 2 Sonic** (Bedrock bidirectional streaming, `aws-sdk-bedrock-runtime`) | The voice: hears the person, decides which tool to call, speaks the answer, and can be interrupted. `src/home_operator/sonic.py` |
| **Amazon Bedrock**, Nova 2 Lite, Converse API document understanding | Read each manufacturer's PDF once and extracted repair steps, error codes, intervals and parts. `src/home_operator/extract.py` |
| **Amazon Cognito** | Machine-to-machine sign-in to the tools: a user pool, a resource server and a `client_credentials` app client. `src/home_operator/auth.py` |
| **Amazon S3** | Holds the manuals over Bedrock's 4.5 MB inline limit, read by Bedrock straight from the bucket |
| **Amazon EC2, Amazon CloudFront, AWS IAM, AWS Systems Manager, AWS CloudFormation** | Host the voice app on a public HTTPS link with its own IAM role, secrets in SSM Parameter Store, updates through SSM Run Command, all from one template. `deploy/hosted.yaml` |
| **Strands Agents SDK** with Nova 2 Lite | The agent behind the original text simulator, `src/home_operator/agent.py` |
| **Amazon Polly** (generative, voice Ruth) | Speaks the original text simulator's replies |
| **MCP Python SDK** 2.x | The server and its clients |
| **CPSC recalls API** (US government, public) | Finds safety recalls on the household's models, through the open-source `cpsc-recall-check` library |
| **Alexa+ add-on documentation and CLI** | Read, but not usable: the toolkit is partner-only (below) |

### What worked well?

- **AgentCore Runtime with `CodeZip`.** A Python MCP server deployed without
  Docker or an ARM image, behind a JWT authorizer, and redeployed in one
  command. Once the 421 below was solved, it has answered every call since.
- **Cognito `client_credentials`.** Exactly the right shape for one service
  proving who it is to another: no users and no passwords anywhere.
- **Nova 2 Sonic's tool use and latency.** Tool calls worked across a full
  eight-step repair, about two seconds from the end of a sentence to the first
  word back with the tool call included, and interrupting it feels natural. When
  a tool reply carried the exact line to say, it said the manual's steps word for
  word. Its speech-start and speech-end events made the listening and thinking
  states on screen easy to build.
- **Bedrock document understanding.** It read a 92-page manual, and a 44-page
  one that is only scanned images, and copied every procedure accurately.
- **IAM roles for hosting.** The voice app signs its own calls with credentials
  AWS keeps fresh, so the public link works without anyone being logged in.

### What needs work?

The sections below, most important first.

### How was your onboarding experience?

On the AWS side, good once past a few walls, each of which cost an hour or more
because nothing said what was wrong: a new account cannot call Bedrock for up to
two hours; `aws login` credentials need an undocumented extra in the Python SDK;
the AgentCore MCP samples no longer run on the current SDK; and a deployed server
fails with a bare 421. Nova 2 Sonic needs a separate Developer Preview SDK that
is not in boto3. On the Alexa+ side, onboarding was not possible: the documented
CLI is not on public npm and the toolkit is partner-only, which is why the front
end is a simulator. All of these are in FRICTION.md.

### Would you build with these devices and services again?

Yes. AgentCore, Bedrock and Nova 2 Sonic carried this project from a laptop to a
public link with a real voice, and each problem above had a workaround. The day
the Alexa+ add-on toolkit opens, this is the first thing I would put on it.

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
