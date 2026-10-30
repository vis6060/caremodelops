# Claude Developer Platform: Milestone 1

This opt-in extension uses public Synthea cases only. Historical ChartGround
benchmarks describe deterministic architectures, not Claude performance.

## Windows PowerShell setup

Install the extension dependencies, then run the offline mock demo:

```powershell
python -m pip install -r requirements-developer-platform.txt
python scripts/developer_platform_demo.py --case-id cg-syn-012 --question "What medication conflicts are present?" --provider mock
python -m pytest -v
```

For an explicitly requested live run, configure ANTHROPIC_API_KEY and
ANTHROPIC_MODEL in the repository root .env using .env.example as a reference.
The demo, direct workflow and Claude client all load this file automatically using
python-dotenv. Its location is resolved from the configuration module's __file__,
independent of the working directory. Process variables take precedence
(override=False), and an explicit --model overrides ANTHROPIC_MODEL.

```powershell
python scripts/developer_platform_demo.py --case-id cg-syn-012 --question "What medication conflicts are present?" --provider claude
```

No live requests are made by default or in unit tests. Live requests may incur
charges. The root .env is ignored by Git; .env.example contains placeholders only.
Pytest collection is scoped to tests/ so standalone credential-check scripts are
not imported as tests. The CLI prints a compact response; full bounded tool
outputs remain in the local run log.
The adapter follows the [official Python SDK](https://platform.claude.com/docs/en/api/sdks/python).

## Execution boundary

Only cg-syn-NNN directories under the fixed public case root are accepted. Paths,
linked files/directories, foreign patient/case rows, and restricted source markers
are rejected. Synthea identity must match the canonical patient. A validated
temporary snapshot feeds the existing store and tool registry. The CLI accepts
no custom data root. Trusted synthetic files must not be replaced with private
records: filesystem checks cannot certify data origin.

Plans are explicit. The existing planner is extended with an unconditional conflict
check. High-severity conflicts escalate; cg-syn-012's stopped/continued lisinopril
sources are both cited. The original planner is unchanged. Conflict-focused prompts
contain complete relevant contradiction records and conflict details, without unrelated
chart history. Required conflict sources are never shortened or dropped; if their
complete context exceeds 32000 characters, generation is blocked before an API call.
Other evidence is limited to 12 records and 800 characters per record, questions to
2000 characters, and JSON prompts to 32000 characters. General tool lists contain at
most six entries each. Notes and tool results are untrusted. Detected instruction
overrides block generation; pattern matching cannot detect every injection.

## Response and verification

The model returns JSON claims, per-claim citations, missing information and a
suggested action. Citations must occur in the supplied evidence list. Invalid IDs
are excluded and trigger abstention. Existing deterministic support checks and
action policy run afterward with local LLM calls disabled. Lexical support is not
clinical verification: a would-be answer remains uncertain pending clinical review.
Model failures return structured uncertainty; known high-severity conflicts still
escalate. This prototype does not provide medical advice.

## Usage and logs

Detailed bounded records are stored under the ignored results/claude_runs/ folder.
They include selected public evidence, plans, outputs, claims, action and usage.
SDK exception details and headers are never logged; key values are redacted.
Do not enter private records or secrets into questions. Keep SDK HTTP debugging off.

Live metadata contains the reported model, request ID, timestamp, latency, stop
reason and input/output/cache tokens. Missing usage remains null, including mock
token counts. Costs are not estimated. Organization, partner and pricing attribution
fields are nullable placeholders. The SDK is imported only for explicit live mode.
No live Claude performance was measured for this milestone.

## Bounded live generation correction

The former request used a fixed 1800-token ceiling. ANTHROPIC_MAX_TOKENS now
defaults to 4096 (allowed range 256-8192). A max_tokens stop triggers at most one
retry with twice the configured budget, capped at 8192, plus a brevity instruction.
SDK transport retries remain disabled; other failures are not retried.

The installed SDK 2.3.0 supports output_config.format with type json_schema.
The request uses ordinary ChartGround citation-ID fields, without native citation
blocks, and asks for two short answer sentences and at most three claims. Claim
count and citation membership are also validated locally. output_config.effort is
low; no explicit adaptive-thinking budget is enabled. See Anthropic's official
[structured output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
and [effort](https://platform.claude.com/docs/en/build-with-claude/effort) conventions.

usage.attempts records each request separately, including API success versus
generation status, actual tokens, request/model IDs, stop reason and latency.
Top-level usage metadata describes the last attempt; total_input_tokens and
total_output_tokens sum reported consumption only. Missing usage remains unknown.
An API response with max_tokens is recorded as consumed but truncated, not as
usable clinical generation. Application status and error describe validation;
answer_source distinguishes claude from deterministic_fallback.

A valid Claude answer is retained verbatim, while the local safety policy still
forces escalation for high-severity conflicts. Missing either contradictory
citation triggers a labeled fallback. Lexical checks remain nonclinical checks.

### One live verification (requires explicit approval; not run by this correction)

With your private root .env already configured, run these PowerShell commands only
when ready to authorize a paid request (up to two attempts if the first truncates):

```powershell
conda activate chartground-claude
$env:ANTHROPIC_MAX_TOKENS = "4096"
python scripts/developer_platform_demo.py --case-id cg-syn-012 --question "What medication conflicts are present?" --provider claude --model claude-sonnet-5-5
```

Check status=success, error=null, answer_source=claude, action=escalate, both
lisinopril evidence IDs, populated actual usage/model/request metadata, and
stop_reason=end_turn. No successful live result is claimed from offline tests.
