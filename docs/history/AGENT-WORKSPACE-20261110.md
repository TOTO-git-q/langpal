# Agent workspace: architecture and verification (2026-11-10)

## User flow

The workspace opens as a conversation, not a settings form. Attachments appear inside the rounded composer. Advanced management retains courses, worldbooks, sources and tools; raw configuration is collapsed. A provider must be selected explicitly. The selected provider receives only the current request, the three most recent successful turns, selected material and the necessary sanitized configuration/working guidance.

Configuration changes are proposals. They require an explicit Apply action; a successful model response is not a configuration write. The change history reads authoritative server state before offering Apply or Undo. Unavailable or expired proposals remain visible but cannot execute.

## Model boundary

- Claude: one-shot official Agent SDK client using the existing CLI identity. No copied credentials, conversation resume, host tools or model-controlled mutations. Empty working directory and explicit empty settings/skills/plugins/MCP reduce ambient context; this is not a guarantee against managed CLI policies. Structured output and image inputs are validated.
- DeepSeek: bounded HTTP tool loop to the official API. Only two read-only, precomputed snapshots (`inspect` and `read_skill`) exist. No shell, browser, arbitrary URLs, plugins, redirects or fallback. Current adapter is text-only.
- The previous Codex runtime has been removed from this Agent path. Other application providers are not silently selected.
- GPT and other services are not implemented by merely choosing a Claude model name. They need their own authorized API configuration and thin protocol adapter. A GPT subscription is not an API credential or API credit.

Provider availability metadata does not prove authentication or network success. Claude installation is detected with authentication marked unverified until a request succeeds. DeepSeek reports configuration availability without exposing credential values. A failed provider never triggers another provider.

## Durable local state

SQLite owns conversations, message status, attachment relations, image bytes and proposals. Existing study documents remain canonical for document metadata/text. Agent attachments do not appear in the reading shelf. The existing study export is not a complete Agent conversation/image/proposal backup; a database backup is required for complete recovery.

Proposal records contain stable resource descriptors, before/after values, status and absolute expiry. Apply/Undo reconstruct resources after process restart, recheck conflicts and references, and update resources and proposal state atomically. Chat changes capture both room settings and pinned session. Previews do not commit changes. Browser-only preferences remain browser-scoped.

## Verification

- Real Claude SDK request with synthetic image and temporary database succeeded: image description, reading-style proposal, Apply, persisted readback and Undo. No real user content or production database was involved.
- Real HTTP + Chrome + temporary SQLite passed manual Preview, browser refresh, Apply, service-process restart, new-browser state recovery and Undo at 1280px and 390px.
- Earlier real HTTP tests verified document/image upload, persisted file bytes, selection and conversation recovery with a model test double.
- Offline tests: 11 durable-proposal cases, 10 workbench cases, 6 settings-chain cases, 15 conversation cases, 6 dispatcher cases, 6 Claude adapter cases, 16 DeepSeek adapter cases and 3 material-context cases. Final backend suites used a non-loopback network guard. Browser suites include global styling, attachment previews, explicit provider gating, authoritative proposal state and speech-recognition lifecycle doubles.

## Remaining limits

A real DeepSeek official-API test with synthetic content succeeded (two HTTP 200 responses): bounded snapshot reads, proposal, temporary SQLite Apply/readback/Undo. An earlier restricted check could not open SQLite and misclassified that error as missing configuration; capabilities now distinguish unreadable, missing, invalid and configured states. Other OpenAI-compatible services still need adapters/configuration. Browser speech recognition is user-started and consent-based; actual microphone capture was not tested. Scanned PDF OCR and DOCX are not supported. Unsent drafts are retained within the current page, not across a full refresh. Model inference quality is not guaranteed by structural validation. Production service startup and database migration were not performed by this verification work.
