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
- **Workaround:** Built and tested the MCP server locally with the official MCP Inspector (`@modelcontextprotocol/inspector`). Asked on the hackathon Discord and Devpost forum whether toolkit access is gated.
- **Suggestion:** If the CLI is limited to approved partners, say so on the setup page and link to the access request. If it's meant to be public, publish it to npm, or document the registry to configure.
