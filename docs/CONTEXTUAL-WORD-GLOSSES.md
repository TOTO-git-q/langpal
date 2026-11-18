# Contextual word glosses

Chat generation stays unchanged. Before the existing delivery pause of each text bubble,
`word_glosses.schedule` starts compact contextual glosses alongside the delivery
pauses. Every alphabetic clickable token is included (including function words).
There are at most 28 occurrences per model request and two glossary requests in
flight. The model returns a compact ID-to-meaning map, without repeating token
metadata. This uses the existing utility-provider selection, without switching models.

`bubble_done.tokens[].gloss` optionally carries results that are already ready.
The frontend requests `POST /api/explain/words` for remaining results, joining the
same server task. It does not wait for memory extraction or the end of all bubbles.
Old messages prepare their sentence on the first lookup, rather than automatically
sending the entire chat history to the model.

Request: `{ "language": "ja", "sentence": "昨日は本を読みました。" }`.
Sentence length is 1–6000 characters. Response: `{ "words": [...], "complete": true }`.
Each entry has `lemma`, `surface`, `reading`, `pos`, `occurrence` (zero based among
identical surface/lemma pairs), `meaning_zh`, `detail` (`brief`/`full`), and `cached`.
Unknown/invalid model IDs or empty meanings are omitted; missing entries fall back
to the clicked word only. Repeated occurrences are separate, including when
requesting a full word card using optional `/word.occurrence`.

The SQLite `explain_cache` table is retained without a migration. The existing
`kind='word'` constraint is respected; compact glosses use namespaced cache keys
`gloss:v1:<hash>`, detailed occurrence cards `detail:v2:<hash>`. Legacy word cards
and sentence parsing retain their keys. Compact glosses never occupy full-card keys.
Context keys include language, whitespace-normalized source text, lemma, surface,
and occurrence. Cached lookups and inserts each use one connection per batch.

The frontend keeps at most 128 sentence results and coalesces pending requests.
Warm word clicks render immediately; vocabulary saved-state queries never block
meaning display. Full usage/grammar requires the explicit expansion control.
Closing a popover cannot cancel a batch used by another word. Errors retain a
single-word fallback; failed batches may be retried.

Reading prepares only three visible sentence units while lookup is on, then the
sentence under the pointer. It uses source text without ruby pronunciation markup.
It neither prefetches an entire uploaded book nor warms during the exercise view.
The standalone reader loads the same shared module.

Validation: `tests/test_word_glosses.py` (real table constraints, real Japanese
tokenizer, controlled providers), `tests/test_word_glosses_ui.mjs` (headless Chrome),
and existing reader/furigana regression checks. Production timing and model output
are recorded separately from mocked UI timing in the release work directory.
