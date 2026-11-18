# Official DSH transport (2026-11-10)

- SDK: `deepseek-harness-sdk==0.2.1rc2`, runtime `deepseek-harness-runtime-bin==0.2.1rc2` (Windows x64). Versions are enforced before production calls.
- Official source: https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.2.1-rc.2
- Transport: `DeepSeekHarness`, provider `deepseek-official`, standalone `sdk-minimal` profile, fixed `https://api.deepseek.com/anthropic` base. The runtime sends Messages requests to `/anthropic/v1/messages`, not the former Chat Completions endpoint.
- Existing DeepSeek settings supply key/model. No account migration, credential file, OAuth plugin, or use of Claude/Codex/ChatGPT tokens. The model is not silently substituted. Compatibility of the existing model with the official Messages endpoint requires a live test.
- **现状（2026-11-12）：DSH 只给课程管家用**（services/workspace_agent_deepseek.py 调 providers/dsh.py 的 `complete()`）。主聊天、杂活、听力里的 DeepSeek 走 providers/deepseek.py 的直连 HTTP（流式、内存多轮历史 + 首次从库里补种），registry 里不再有 DSHProvider。Claude remains its own SDK; Custom API remains its explicitly configured REST provider; ChatGPT SIWC remains separate.
- Every invocation has a temporary working directory and DSH home, no persisted SDK sessions. The key only enters the SDK's supported in-memory api_key option and child environment. Inherited application secrets, proxy settings and runtime hooks are blanked in the child environment.
- The pinned minimal profile omits local instructions, managed credentials, Web tools, external plugin discovery and subagents. Invocation patches disable every shipped model-visible tool (file/image, working directory, persistent shell), terminal/subprocess/attachment services, automatic compaction, session-log upload and plugin inventory upload. This is tool isolation, not an OS security sandbox.
- Agent inspect/read_skill are sanitized request snapshots included in the model input, not executable model tools. Its output remains a strictly checked proposal; only existing confirmation/apply/undo code may change app state.
- SDK `run` is synchronous. It is moved off the event loop, with a 90-second timer closing that invocation's runtime; cancellation closes the owned runtime and waits for cleanup. No shared service process is terminated. Raw SDK diagnostics are not exposed.
- Health/configured are passive local SDK/config checks, not verified connectivity.

## Verification

`python -m unittest discover -s tests -p test_workspace_agent_deepseek.py -v`: offline contracts (snapshot/proposal validation, response bounds, malformed/nonfinite data, environment scrubbing, cancellation/timeout; plus a check that chat DeepSeek is the direct HTTP provider, not DSH).

`python -m unittest discover -s tests -p test_dsh_runtime_offline.py -v`: real bundled dsh initialization + complete turn against a loopback Messages SSE fixture passed. One captured request, no `tools` field, no session-log/inventory payload fields, successful `completed` response, temporary-home cleanup verified. Uses only a synthetic placeholder key and synthetic text. No live provider request or production DB write is performed by these tests.

Windows sandbox execution denied deletion of some runtime-created temporary files (WinError 41); running the same authorized isolated test with ordinary user permissions passed. SDK 0.2.1rc2 emits ResourceWarning for its stdout/stderr pipe wrappers during teardown despite reaping the process; this is upstream SDK behavior, not a retained runtime process.

Live provider results and full app regression are recorded separately by the coordinating task. No app service was restarted here.
