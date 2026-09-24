## Inspiration

The dishwasher stops draining on a weeknight. The manual is in a drawer, or it
is a ninety-page PDF on a phone you do not want to touch with wet hands, and the
answer is on page 40.

Alexa+ can already read you that manual. It cannot stand next to you and keep
your place while you work, wait until you have actually switched the power off,
or tell you that your model is named in a safety recall. That gap is the whole
project: **Alexa+ can read your manual. Home Operator walks you through the fix.**

## What it does

Home Operator knows the five appliances in one home and talks you through them.

- **"My washer is showing OE."** It names the fault from LG's own troubleshooting
  table, most likely cause first, and offers the fix.
- **"Walk me through it."** Eight steps, one at a time. The first is a safety
  gate: it will not move on until you say the washer is off and unplugged.
- **"Hold on, someone's at the door."** Your place is kept. Come back and it is
  still on step four.
- **"Anything I should take care of?"** Overdue maintenance worked out from a
  real service history — and it says which jobs are yours and which belong to a
  technician, because the manuals are explicit about the difference.
- **"It still won't drain, I need someone."** A brief to read to a repair
  professional: model, age, warranty, the fault, and what you already tried.

Before any of that, when it matters: *"Your dishwasher's model is named in a
safety recall, so it may be affected. The power cord can overheat and catch
fire."* That recall is real, found by querying the US Consumer Product Safety
Commission's live API.

## How I built it

**Two lanes, and only one runs while you are talking.**

The slow lane runs days earlier, offline. A manual PDF goes to **Amazon S3**,
**Amazon Bedrock** (Nova 2 Lite) reads the whole thing — ten pages for the
furnace, ninety-two for the dishwasher — and returns structured steps, intervals
and symptoms — and then I check every entry against the page
myself. **Forty-six corrections are logged across five appliances**, each citing
a page number and quoting what the manual actually says. Raw and reviewed files
sit side by side in the repo, so the difference is auditable.

The fast lane is what runs while someone is standing at a machine. An
**MCP server** with eight tools is deployed on **Amazon Bedrock AgentCore
Runtime**, behind an **Amazon Cognito** authorizer using machine-to-machine
credentials — no users, no passwords, the agent proves it is the agent. A
**Strands Agents** agent on Bedrock decides which tool to call. **Amazon Polly**
speaks the replies in a generative voice.

The rule the whole design turns on: **the model decides which tool to call; the
tools decide what is true.** Repair steps are served verbatim from data a human
verified against a manual page. The model has no other source of appliance
facts, so it cannot invent a repair step.

The Alexa+ add-on toolkit is a partner-only preview — Amazon staff confirmed
this twice in the hackathon forum — so the front end is a simulated Alexa+
experience, which the rules explicitly permit. It is labelled as a stand-in on
screen. Everything behind it is real and running on AWS.

## Challenges I ran into

**The model kept talking past its tools, and no prompt stopped it.** Three times,
with instructions in both the system prompt and the tool descriptions:

1. Asked *"want me to walk you through it?"*, the person said **"yes please"** —
   and the model turned that into the call that clears a **power-off safety
   gate**, sending them to open a drain filter on a washer that might still have
   been plugged in and full of water.
2. On another turn it called **no tool at all** and recited *"Now open the drain
   pump filter cover"* from its own knowledge. A repair instruction, spoken
   aloud, that came from no manual.
3. Told by a tool that the washer still had to be unplugged, it said to open the
   filter cover anyway — contradicting the result it had just received.

All three are now impossible in code, not discouraged in a prompt. A gate clears
only on the person's own words about the machine, checked on the server: *"it's
unplugged"* opens it, *"yes"* does not. Thirty tests pin that behaviour.

**Moving to AgentCore broke the walkthrough in a way that taught me something.**
Progress lived in the server's memory, which works on one laptop but not on a
runtime where the next call can land on a different copy of the container. So
the place now travels in the tool call itself, which is both more robust and
closer to how a voice assistant really calls tools: one shot, no memory.

**And a 421 that only CloudWatch could explain.** Every call to the deployed
server failed with an opaque error. The cause was the MCP SDK's DNS-rebinding
protection rejecting AgentCore's internal proxy hostname — documented nowhere.

## What I learned

**A prompt is not a control.** Anything that matters for safety has to be
enforced where it cannot be talked out of, and tested. Every failure above was
found by using the thing, not by reading the code.

**Reviewing a model's output is real work, and reviewers make mistakes too.**
Nova invented intervals wherever a manual was vague — "every 30 days" where LG
says "periodically". But when I audited my own review, I found I had claimed
steps were kept verbatim when I had rewritten them, and had "improved" a
procedure's step order until I checked the page and found the extraction was
right and I was wrong. Both are logged in the repo.

**AWS gives you the pieces; the judgement is yours.** Bedrock, AgentCore,
Cognito and Strands all did exactly what they promise. Deciding that a gas
furnace's heat exchanger is a technician's job and not a homeowner's, and that a
recall means "may be affected" rather than "is recalled", is not something a
service can do for you.

## What's next

Account linking with OAuth 2.1 so each household's own data is reached with
their own identity, interruption that cuts in mid-word rather than mid-sentence,
and — the day the Alexa+ toolkit opens up — running this where it was always
meant to run.
