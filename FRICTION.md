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
- **Suggestion:** The documentation gives no hint of this. "Set Up Your Development Environment" reads as a public quickstart: it lists `npm install -g @alexa-ai/cli`, a version check, and `alexa-ai configure`, with no preview banner, no eligibility note and no access request link. Three separate hackathon participants asked the same question on the forum within a day, which suggests the cost is widespread. Please add a preview notice at the top of every MCP Toolkit page naming who can get access and how, and make the 404 a documented, expected outcome rather than something each developer has to diagnose. Publishing a stub package to npm whose postinstall message explains the preview status would end the confusion outright.

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
