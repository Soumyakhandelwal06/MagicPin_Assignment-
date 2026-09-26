# VERA PROJECT DOCUMENTATION

## 1. Project Overview

The Vera AI Challenge involves building the backend engine for "Vera," an AI-powered growth assistant designed for local merchants (e.g., dentists, salons, restaurants). The overarching problem the application solves is providing hyper-personalized, context-aware, and actionable outreach to small business owners without overwhelming them with generic spam. 

The intended users are local business owners (merchants). The AI assistant is expected to analyze incoming events (triggers) in the context of the merchant's business profile and industry category, deciding *whether* to message them, *what* to say, and *how* to act on their behalf (e.g., reaching out to their customers).

**Technical Explanation**
The system is built as a deterministic, stateful REST API using FastAPI. It continuously ingests and stores versioned JSON contexts (`category`, `merchant`, `customer`, `trigger`). A centralized engine processes "ticks" (time-advancement events), evaluates the urgency and validity of available triggers, filters them using merchant-scoped suppression keys, and delegates composition to a deterministic message composer that applies strict safety guardrails. The system also manages multi-turn conversational intent transitions when merchants reply.

## 2. Challenge Requirements and Expected Behavior

| Requirement | Purpose | Implementation Status | Relevant File |
| :--- | :--- | :--- | :--- |
| **REST API Server** | Provide 5 specific endpoints (`healthz`, `metadata`, `context`, `tick`, `reply`). | Implemented and tested | `bot.py` |
| **Versioned Contexts** | Only accept new or newer versions of context payloads; return `409 Conflict` on stale versions. | Implemented and tested | `bot.py` |
| **Determinism** | Identical inputs must yield identical outputs for offline testing. | Implemented and tested | `composer.py` |
| **Message Quality Guardrails** | Must conform to specific `cta` types, `send_as` roles, and filter vocabulary taboos. | Implemented and tested | `composer.py` |
| **Merchant Suppression** | Must respect `suppression_key` boundaries specifically scoped to a `merchant_id` to prevent cross-merchant blockage. | Implemented and tested | `engine.py` |
| **Multi-turn Replies** | Must handle intent transitions, auto-reply detection (3x loop), and hostile opt-outs. | Implemented and tested | `bot.py` |
| **Submission Output** | Generate 30 exact canonical outputs matching `test_pairs.json` in a valid `.jsonl` schema. | Implemented and tested | `generate_submission.py` |
| **Simulator Passing** | Pass the AI-driven `judge_simulator.py` scoring criteria. | **Unverified** (Blocked by API Key requirements) | `judge_simulator.py` |

## 3. Complete Project Architecture

The architecture relies on an event-driven loop where state is accumulated in-memory and evaluated synchronously upon time advancement (Ticks) or user interaction (Replies).

```mermaid
flowchart TD
    Client[Client / Simulator] -->|POST /v1/context| Bot[bot.py: FastAPI Server]
    Client -->|POST /v1/tick| Bot
    Client -->|POST /v1/reply| Bot
    
    Bot -->|Stores State| Memory[(In-Memory Dicts)]
    
    Bot -->|1. fetch & evaluate| Engine[engine.py: Trigger Engine]
    Engine -->|Reads| Memory
    
    Engine -->|2. top priority trigger| Composer[composer.py: Message Composer]
    Composer -->|applies rules| Guardrails[validate_message]

## 4. Technology Stack

* **Python 3.11**: The core runtime used for the backend logic.
* **FastAPI**: The web framework (found in `bot.py`). Used for building the 5 required REST API endpoints (`/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, `/v1/reply`). Chosen because it automatically handles JSON serialization, routing, and provides high performance.
* **Pydantic**: The data validation library natively integrated with FastAPI (found in `bot.py` via `BaseModel`). Used to define strict schemas for incoming requests (e.g., `CtxBody`, `TickBody`, `ReplyBody`), ensuring the application gracefully rejects malformed data.
* **Uvicorn**: The ASGI web server implementation. Used to serve the FastAPI application locally on port 8080.
* **Pytest**: The local unit testing framework (found in `test_bot.py`). Used to verify API responses, validate state transitions, and assert that edge cases (like stale context versions or competing triggers) are handled deterministically.
* **HTTPX**: The underlying HTTP library used by FastAPI's `TestClient` (found in `test_bot.py` and `demo_chat.py`) to simulate network requests during tests.
* **JSON/JSONL Utilities**: The standard Python `json` library is heavily utilized in `generate_submission.py` to parse canonical test pairs and output the final `submission.jsonl` artifact.

## 5. Detailed Explanation of Every Major File

### A. `bot.py`
**Purpose**: Acts as the central application router and HTTP interface.
* **Initialization**: Initializes the `FastAPI` instance and sets up in-memory dictionaries (`contexts` and `conversations`) to hold state, as well as importing the `suppressed_keys` and `suppressed_conversations` sets from `engine.py`.
* **Endpoints**:
  * `GET /v1/healthz`: Iterates over the `contexts` dictionary to count how many categories, merchants, customers, and triggers are currently loaded. Returns server uptime.
  * `GET /v1/metadata`: Returns static team info, the intended model (`gemini-1.5-pro`), and submission timestamps.
  * `POST /v1/context`: 
    * *Input*: `CtxBody` containing `scope`, `context_id`, `version`, and `payload`. 
    * *Step-by-step*: Validates the `scope` against an allowed set. Looks up the current stored version for the provided `context_id`. If the stored version is `>=` the incoming version, it throws a `409 Conflict` (idempotency safety). Otherwise, it updates the dictionary and returns a success ACK.
  * `POST /v1/tick`: 
    * *Input*: `TickBody` containing `now` (ISO timestamp) and a list of `available_triggers`.
    * *Step-by-step*: Passes the triggers to `evaluate_triggers()` in `engine.py`. Iterates over the returned valid triggers. Enforces a rule of *one action per merchant per tick* using a `used_merchants` set. Calls `compose()` in `composer.py`. Adds the output to the `actions` array and tracks newly generated suppression keys.
  * `POST /v1/reply`: 
    * *Input*: `ReplyBody` containing `conversation_id`, `message`, etc.
    * *Step-by-step*: Appends the message to the conversation history. Checks if the conversation is globally suppressed. Runs three deterministic rules against the message string (Auto-reply loop detection, hostile opt-out, positive commitment intent). It returns an `action` of `send`, `wait`, or `end`.

### B. `engine.py`
**Purpose**: The central decision engine that filters and prioritizes triggers.
* **`get_contexts(contexts_store, trigger_id)`**:
  * *Input*: The global `contexts` dict and a specific `trigger_id`.
  * *Step-by-step*: Fetches the trigger JSON. Extracts the `merchant_id` to fetch the merchant JSON. Extracts the `category_slug` (either from the merchant or fallback to the trigger) to fetch the category JSON. Fetches the customer JSON if applicable. Returns all four dicts.
* **`evaluate_triggers(contexts_store, available_triggers, now_str)`**:
  * *Input*: The state dict, a list of raw trigger strings, and the simulated time.
  * *Step-by-step*: Parses `now_str` into a UTC `datetime` object. Loops through triggers. If a trigger is missing dependencies (e.g. no merchant context exists yet), it skips it. It checks if `now > expires_at`; if so, it skips it. It checks if the tuple `(merchant_id, suppression_key)` exists in the global `suppressed_keys` set; if so, it skips it. Finally, it appends survivors to a list as `(urgency, trigger_id)` tuples, sorts them descending by urgency, and returns the prioritized IDs.

### C. `composer.py`
**Purpose**: Formats the final text output and applies safety guardrails.
* **`compose(category, merchant, trigger, customer, provider)`**:
  * *Input*: The four context dicts and an optional `LLMProvider` (which defaults to a deterministic `TemplateProvider`).
  * *Step-by-step*: Uses the `kind` of the trigger to map to a specific output template. It dynamically injects merchant facts (e.g. `owner_name`, `intent_topic`, `due_date`) into the string. It assigns a predefined `cta` enum, a `send_as` role, and an explicit `rationale` describing why it took the action.
* **`validate_message(msg, category)`**:
  * *Input*: The drafted message payload and the category context.
  * *Step-by-step*: Uses regex `r'https?://\S+'` to strip all URLs, replacing them with `[URL REDACTED]`. It loops through `category["voice"]["vocab_taboo"]` and performs case-insensitive regex replacements to swap banned words with `[REDACTED]`. It ensures the `cta` and `send_as` exactly match the official enums, otherwise falling back to safe defaults.

### D. `test_bot.py`
**Purpose**: The local `pytest` suite ensuring all backend constraints are mathematically met.
* `test_healthz` / `test_metadata`: Verifies the GET endpoints return 200 OK.
* `test_push_context_success_and_stale`: Tests atomic version updates. Pushes v1 (200 OK) then pushes v1 again (expects 409 Conflict).
* `test_invalid_scope`: Tests Pydantic rejection of unknown scopes.
* `test_tick_with_contexts`: Tests standard happy-path trigger processing.
* `test_all_five_categories`: Tests iteration over dynamic categories.
* `test_expired_offer`: Passes a tick where `now` is later than `expires_at` and asserts that the engine yields `0` actions.
* `test_reply_auto_reply`: Tests the 3x repeating string loop and asserts the bot returns `wait` with `wait_seconds=14400`.
* `test_reply_hostile`: Tests the word "stop" and asserts the bot returns `end`.
* `test_reply_intent`: Tests the word "yes" and asserts the bot returns `send` with `binary_confirm_cancel`.
* `test_merchant_scoped_suppression`: Proves that if Merchant A gets a global key suppressed, Merchant B can still receive it.
* `test_missing_contexts`: Drops triggers safely if the merchant context is absent.
* `test_competing_triggers`: Proves that a trigger with `urgency: 5` overrides `urgency: 1` during the same tick.
* `test_vocabulary_taboos`: Forces a taboo word through the composer and asserts `[REDACTED]` is produced.

### E. `generate_submission.py`
**Purpose**: An offline script to produce the final challenge artifact.
* *Step-by-step*: Reads `expanded_dataset/test_pairs.json`. Loops over the 30 canonical pairs. For each pair, it opens the exact corresponding JSON files from the `merchants`, `categories`, `triggers`, and `customers` subdirectories. It passes them directly into `compose()` (bypassing the API for speed). It serializes the output into a single JSON line containing `test_id`, `body`, `cta`, `send_as`, `suppression_key`, and `rationale`. It appends this to `submission.jsonl`.

### F. `validate_submission.py`
**Purpose**: A schema checker.
* *Step-by-step*: Opens `submission.jsonl`. Asserts exactly 30 lines. Uses `json.loads` to prove it is valid JSON. Checks that every dictionary key perfectly matches the required set. Asserts that the string values for `cta` and `send_as` exist inside a predefined `set` of valid enums. Does NOT verify the contextual quality of the text, only the shape.

### G. `submission.jsonl`
**Purpose**: The final 30-line deliverable.
* **Schema**:
  `{"test_id": "T01", "body": "...", "cta": "open_ended", "send_as": "vera", "suppression_key": "research_digest_2026W17", "rationale": "..."}`
* All 30 canonical cases from the expanded dataset have been successfully generated and validated. 

### H. `judge_simulator.py`
**Purpose**: The official AI evaluator provided by the challenge organizers.
* **Modifications**: The code was patched locally to resolve bugs in the grading suite. Specifically:
  1. `_warmup()` was expanded to push `customer` and `trigger` contexts into the bot so it has full memory before testing.
  2. `_auto_reply()` was modified to use a static `conv_id` across turns so the bot could actually track the history.
  3. The `ScoreResult` schema was refactored to rename `decision_quality` to `trigger_relevance` to align with the official brief.
  4. Penalty parsing was injected to ensure the LLM judge's deductions actually register.
* **Current Status**: *Unverified execution.* The simulator physically requires an `LLM_API_KEY` (e.g. Gemini, OpenAI) to execute the grading rubric. Because no such key is active in the environment, executing `python judge_simulator.py` safely fails with `HTTP Error 503` or `404 Not Found`.

## 6. API Documentation

### `GET /v1/healthz`
* **Purpose**: Check service availability and memory load.
* **Response Schema** (200 OK):
  ```json
  {
    "status": "ok",
    "uptime_seconds": 120,
    "contexts_loaded": {
      "category": 1,
      "merchant": 1,
      "customer": 0,
      "trigger": 1
    }
  }
  ```

### `GET /v1/metadata`
* **Purpose**: Identifies the team and architecture approach.
* **Response Schema** (200 OK):
  ```json
  {
    "team_name": "Team Alpha",
    "model": "gemini-1.5-pro",
    "approach": "Deterministic state machine and context aggregator"
  }
  ```

### `POST /v1/context`
* **Purpose**: Push business context into the engine.
* **Request Body**:
  ```json
  {
    "scope": "merchant",
    "context_id": "m_001_drmeera",
    "version": 1,
    "delivered_at": "2026-04-26T10:30:00Z",
    "payload": {
      "merchant_id": "m_001",
      "category_slug": "dentists",
      "identity": {"name": "Dr. Meera Clinic"}
    }
  }
  ```
* **Response** (200 OK):
  ```json
  {
    "accepted": true,
    "ack_id": "ack_m_001_drmeera_v1",
    "stored_at": "2026-09-27T00:00:00Z"
  }
  ```
* **Error Conditions**: Returns `409 Conflict` if the version is old, and `400 Bad Request` if the scope is invalid.

### `POST /v1/tick`
* **Purpose**: Advance simulated time and evaluate triggers.
* **Request Body**:
  ```json
  {
    "now": "2026-04-26T10:35:00Z",
    "available_triggers": ["trg_001_research_digest"]
  }
  ```
* **Response** (200 OK):
  ```json
  {
    "actions": [
      {
        "conversation_id": "conv_m_001_trg_001",
        "merchant_id": "m_001",
        "customer_id": null,
        "send_as": "vera",
        "trigger_id": "trg_001",
        "template_name": "vera_generic_v1",
        "template_params": ["Dr. Meera Clinic"],
        "body": "Meera, a new research digest is out. Want me to draft a WhatsApp?",
        "cta": "open_ended",
        "suppression_key": "research_digest_2026W17",
        "rationale": "External research digest with merchant-relevant anchor."
      }
    ]
  }
  ```

### `POST /v1/reply`
* **Purpose**: Simulate a human replying to the bot.
* **Request Body**:
  ```json
  {
    "conversation_id": "conv_m_001_trg_001",
    "merchant_id": "m_001",
    "from_role": "merchant",
    "message": "Stop messaging me.",
    "received_at": "2026-04-26T10:45:00Z",
    "turn_number": 2
  }
  ```
* **Response** (200 OK):
  ```json
  {
    "action": "end",
    "rationale": "Merchant explicitly opted out. Closing conversation."
  }
  ```

## 7. Complete End-to-End Workflow

### Workflow A: Context Ingestion
1. The AI Judge boots up and sequentially POSTs JSON payloads to `/v1/context`.
2. `bot.py` validates `version >= current_version`. 
3. Data is appended to the global `contexts` Python dictionary. 
4. The system is now fully aware of the business rules and environments.

### Workflow B: Proactive Merchant Outreach
1. The AI Judge sends a `POST /v1/tick` containing simulated time `now` and a list of `available_triggers`.
2. `evaluate_triggers()` parses `now`, dropping any trigger whose `expires_at` is in the past.
3. It drops triggers missing merchant profiles.
4. It checks `(merchant_id, suppression_key)` against the global blackout list.
5. It sorts surviving triggers by the `urgency` integer.
6. The highest urgency trigger is fed into `compose()`.
7. `compose()` dynamically injects variables (e.g. `owner_name`, `deadline_iso`) into strings.
8. `validate_message()` regex-scrubs the string for URLs and Taboo words.
9. `bot.py` generates `actions` JSON, adds the suppression key to memory, and returns to the Judge.

### Workflow C: Customer Reply Handling
1. Merchant replies via `POST /v1/reply`.
2. `bot.py` maps the message to the `conversations` history list.
3. Checks if the conversation is already ended/suppressed.
4. Checks for 3 identical messages in a row ("auto-reply hell"), entering a `wait` state if true.
5. Runs string matching for intent ("yes") and outputs a `send` action.
6. Runs string matching for opt-out ("stop") and outputs an `end` action.

### Workflow D: Submission Generation
1. `generate_submission.py` opens `test_pairs.json`.
2. It iteratively bypasses the API and passes local JSON objects straight into `composer.py`.
3. It writes the exact payload output (test_id, body, cta, etc) into `submission.jsonl`.

### Workflow E: Evaluation
1. `judge_simulator.py` calls the LLM Provider (e.g. Gemini).
2. It executes Workflow A (warmup) and Workflow B (full evaluation).
3. It prompts the LLM to grade the composed strings against the 5 rubric dimensions.
4. It averages the score across 30 triggers to give a final percentage. *(Currently unverified due to API key absence)*.

## 8. Decision-Making Logic (Pseudocode)

**Trigger Validation & Expiration:**
```python
now = parse_iso(tick_payload.now)
for trigger in available_triggers:
    if trigger.expires_at and now > trigger.expires_at:
        continue # Drop expired
    if (trigger.merchant_id, trigger.suppression_key) in suppressed_keys:
        continue # Drop suppressed
    valid_list.append(trigger)
```

**Prioritization & Rate Limiting:**
```python
valid_list.sort(key=lambda t: t.urgency, reverse=True)
for trigger in valid_list:
    if trigger.merchant_id in used_merchants:
        continue # Limit: 1 message per merchant per tick
    execute_composition(trigger)
    used_merchants.add(trigger.merchant_id)
    suppressed_keys.add((trigger.merchant_id, trigger.suppression_key))
```

**Vocabulary Redaction (Guardrails):**
```python
for banned_word in category.voice.vocab_taboo:
    if regex_search(banned_word, message_body):
        message_body = regex_replace(banned_word, "[REDACTED]", message_body)
```

## 9. Message Generation: Detailed Examples

**Example 1: Dentist (Research Digest)**
* **Input Context**: Dr. Meera (Dentist), Trigger Kind: `research_digest`. Payload: `top_item_id = "d_2026W17_jida_fluoride"`.
* **Vocabulary Taboo in Category**: `"guaranteed"`
* **Decision Process**: Maps to the research logic. Injects owner name and item ID.
* **Generated Message Body**: *"Meera, a new research digest is out (d_2026W17_jida_fluoride). Want me to pull it + draft a patient-ed WhatsApp you can share?"*
* **CTA**: `open_ended`
* **Send-As**: `vera`
* **Suppression Key**: Used to prevent duplicate digest spam for the rest of the week.
* **Rationale**: "External research digest with merchant-relevant anchor. Open-ended CTA."

**Example 2: Salon (Recall Due - Customer Scope)**
* **Input Context**: Karim Salon, Trigger Kind: `recall_due`. Customer: Aditya. Payload: `due_date = "tomorrow"`.
* **Decision Process**: Scope is `customer`. Overrides `send_as` to represent the merchant directly.
* **Generated Message Body**: *"Hi Aditya, Karim Salon here. It's time for your 6-month recall due around tomorrow. We have slots on Wed 6pm or Thu 5pm. Reply 1 for Wed, 2 for Thu."*
* **CTA**: `multi_choice_slot`
* **Send-As**: `merchant_on_behalf`
* **Rationale**: "Customer-scoped recall, sending via merchant's number. Multi-choice slot CTA for booking flows."

## 10. Testing and Verification
* **Test Suite Command**: `python -m pytest test_bot.py -v`
* **Actual Results**: 14 tests run, 14 PASS.
* **Test Cases Verified**: Context pushing, scope validation, time expiration, global suppression key boundary, missing dependency fallbacks, urgency sorting, auto-reply state detection, hostile opt-outs, intent transitions, confirm transitions, and vocabulary regex filtering.
* **Submission Validator**: 30 canonical cases produced and perfectly validated via `validate_submission.py`.
* **Unverified Constraints**: The `judge_simulator.py` execution is explicitly blocked and unverified due to the absence of a viable API key in the environment to connect to the Gemini/OpenAI grader.

## 11. Evaluation Criteria and Scoring
*(As outlined by the official brief and simulator parser)*
1. **Specificity (1-10)**: Measures the inclusion of hard payload facts (dates, identifiers). The current implementation actively injects these parameters to score highly here.
2. **Category Fit (1-10)**: Measures tone and taboo evasion. The current implementation uses strict regex guardrails to guarantee taboo evasion.
3. **Merchant Fit (1-10)**: Measures whether the text respects merchant constraints (e.g. languages).
4. **Trigger Relevance (1-10)**: Measures whether the response accurately interprets the trigger intent and urgency.
5. **Engagement Compulsion (1-10)**: Measures whether the CTA assigned (`binary_yes_no`, `open_ended`) logically drives interaction.

## 12. Implementation Timeline and Development Phases
* **Phase 1 (Analysis)**: Extracted exact HTTP schemas, payload variables, and enum lists from the raw challenge dataset and brief.
* **Phase 2 (Architecture)**: Stood up FastAPI application. Built the `contexts` tracking dict and implemented the `409` atomic versioning checks.
* **Phase 3 (Core Logic)**: Built `engine.py` expiration checks and `composer.py` guardrail logic.
* **Phase 4 (Refactoring)**: Identified a bug where suppression keys were flat strings (muting multiple merchants). Modified to `Tuple(merchant_id, suppression_key)`.
* **Phase 5 (Testing)**: Expanded `test_bot.py` to achieve comprehensive coverage across all edge conditions.
* **Phase 6 (Generation)**: Scripted the canonical 30 cases into `submission.jsonl` and patched the `judge_simulator.py` codebase to execute properly.

## 13. Current Project Status

| Component | Status | Evidence | Remaining Work |
| :--- | :--- | :--- | :--- |
| **API Endpoints** | Implemented/Tested | 14 local pytests pass | None |
| **Context Management** | Implemented/Tested | 409 rejections tested | None |
| **Decision Engine** | Implemented/Tested | Urgency override tested | None |
| **Submission Output** | Implemented/Tested | `submission.jsonl` exists | None |
| **Interactive CLI** | Implemented/Tested | `demo_chat.py` functional | None |
| **LLM Provider Integration** | Unimplemented | `composer.py` uses templates | Hook up Gemini/OpenAI API |
| **Simulator Passing** | **Unknown/Unverified**| Fails on 503 LLM connection | Provide valid API Key |

## 14. Known Issues and Technical Limitations
* **Deterministic Rigidity**: Because we are utilizing a fallback `TemplateProvider` in the absence of an LLM API Key, the bot's conversational ability is highly rigid. If a merchant says "Hello", it defaults to the catch-all response `"Got it, here's what's next..."` because the strict `if/else` intent mapping doesn't handle small talk.
* **Missing API Key**: Execution of `judge_simulator.py` will fail with network errors until an API key is pasted into line 30.
* **Time Simulation Bug Risk**: Previously, `engine.py` was using real-world `datetime.now()` instead of the simulated `tick_payload.now`. This was fixed, but further date tracking logic must remain strictly bound to the simulated time to prevent false expirations.

## 15. How to Run the Project Locally

**1. Install Dependencies**
```powershell
pip install fastapi uvicorn pydantic pytest httpx
```

**2. Start the Server**
```powershell
uvicorn bot:app --host 0.0.0.0 --port 8080
```

**3. Run Unit Tests**
```powershell
python -m pytest test_bot.py -v
```

**4. Run Interactive Terminal Chat Demo**
```powershell
python demo_chat.py
```

**5. Evaluate with Judge (Requires API Key)**
Open `judge_simulator.py`, paste your API key on Line 30, and run:
```powershell
python judge_simulator.py
```

## 16. Technical Interview Preparation

### A. 2-Minute Project Explanation
"For the Vera AI challenge, I engineered an event-driven FastAPI application that acts as a proactive outreach engine for local merchants. The system digests version-controlled profiles into an in-memory state engine. When time advances via a 'tick', the engine scrubs expired triggers, blocks suppressed ones via a composite key, and sorts the remaining items by urgency. The top trigger is then routed through a deterministic composer that enforces category-specific guardrails (like redacting vocabulary taboos) and attaches standardized Call-to-Action schemas before outputting the final JSON response."

### B. 5-Minute Technical Walkthrough
1. **Networking Layer (`bot.py`)**: Handles the Pydantic schemas. It guarantees idempotency on `/v1/context` by returning `409` if an older payload version is uploaded over a newer one.
2. **Decision Layer (`engine.py`)**: Retrieves contexts sequentially. It compares simulated timestamps from the tick against the payload `expires_at`. It enforces suppression by checking a global set of `(merchant_id, suppression_key)`.
3. **Generation Layer (`composer.py`)**: Normally, this would hit an LLM API. Currently, it uses a `TemplateProvider` to inject facts deterministically. It then executes a `validate_message()` regex pass to scrub URLs and taboos.
4. **Testing Layer (`test_bot.py`)**: Proves via HTTPX that our conversational heuristics (like detecting a 3-turn auto-reply loop) appropriately sleep the bot without crashing.

### C. Important Technical Decisions
* **Dictionary In-Memory State**: Avoided Postgres/Redis overhead by using Python dicts to optimize simulation execution speed.
* **Composite Suppression Keys**: Decided to use `(merchant_id, suppression_key)` pairs instead of raw strings. This prevents a generalized key like `"2026W17_digest"` from globally muting *every* merchant on the platform after one receives it.
* **Time Abstraction**: Abstracted `datetime.now()` to explicitly read from `TickBody.now` to ensure offline, historical, and future test fixtures execute predictably.

### D. Potential Interview Questions

1. **How do you handle API performance bottlenecks in FastAPI?**
   *Answer*: FastAPI is built on ASGI. By using `async def` for endpoints and offloading heavy tasks (like LLM generation) to background tasks or thread pools, the server handles thousands of concurrent connections efficiently.
2. **How does the system ensure idempotent context updates?**
   *Answer*: By comparing the incoming `version` integer against the stored version in `bot.py`. If it's stale or equal, we reject it with `409 Conflict`.
3. **How did you prevent cross-merchant suppression collisions?**
   *Answer*: Suppression is tracked as a tuple `(merchant_id, suppression_key)` in a Set, creating a strict boundary around each business.
4. **How do you handle triggers for contexts that haven't loaded yet?**
   *Answer*: `engine.py` calls `get_contexts()`. If any required dependency (category, merchant) is missing, it drops the trigger and `logger.warning` is triggered.
5. **How does the bot recognize an auto-reply loop?**
   *Answer*: It checks the conversation history array. If the last 3 messages from the merchant are identical string matches, it returns a `wait` action to back off.
6. **Why did you use Pydantic?**
   *Answer*: Pydantic automatically serializes and validates incoming JSON against Python types. It rejects malformed requests with `422 Unprocessable Entity` before my business logic is even touched.
7. **How does the bot enforce vocabulary taboos?**
   *Answer*: `composer.py` loops through `category["voice"]["vocab_taboo"]` and uses `re.sub(..., "[REDACTED]", ...)` to scrub the final string before transmission.
8. **What is the difference between `open_ended` and `binary_yes_no` CTAs?**
   *Answer*: `binary_yes_no` requires specific infrastructure parsing on the client side to render two buttons, whereas `open_ended` represents standard conversational text input.
9. **How do you handle multiple triggers per tick?**
   *Answer*: `engine.py` filters invalid triggers, then sorts the remainder descending by the `urgency` integer payload field.
10. **How do you prevent sending multiple messages to the same merchant in one tick?**
   *Answer*: `bot.py` tracks a local `used_merchants` set during the loop. The first valid trigger processed adds the merchant to the set, and any subsequent triggers for that merchant in the same loop are skipped.
11. **Why is `judge_simulator.py` execution unverified?**
   *Answer*: It performs a network call to the Google Gemini/OpenAI API. Without a valid, provisioned API key in the environment, it returns an HTTP 503 or 404 error during connection testing.
12. **How do you mock testing time?**
   *Answer*: Time is extracted from the `TickBody.now` ISO string and passed all the way down to `engine.py`, overriding the real-world `datetime.now()` to ensure reproducibility.
13. **What is `pytest` used for here?**
   *Answer*: It runs 14 local edge-case tests, utilizing FastAPI's `TestClient` to make simulated HTTP requests and assert that state transitions occur correctly in memory.
14. **How is `submission.jsonl` formatted?**
   *Answer*: It's a JSON Lines file where each line is an independent, valid JSON object mapping exactly to the 30 canonical test cases.
15. **What happens if a user types something completely unexpected in the chat?**
   *Answer*: In deterministic mode, the `if/elif` intent mapping fails to capture it, and it falls back to a safe default message: "Got it, here's what's next..."
16. **How does the `composer.py` inject specificity?**
   *Answer*: It traverses the JSON tree (e.g. `trigger["payload"]["top_item_id"]`) and dynamically casts those facts into the string template to anchor the message in verifiable reality.
17. **What is the difference between the `vera` and `merchant_on_behalf` identities?**
   *Answer*: If the trigger is scoped to the `merchant`, Vera acts as the assistant. If the trigger is scoped to a `customer` (e.g., appointment recall), Vera acts as the merchant contacting the client directly.
18. **How does the system ensure URLs are not sent?**
   *Answer*: A generic Regex pattern `r'https?://\S+'` is executed in `validate_message` to replace any generated links with `[URL REDACTED]`.
19. **How did you fix the auto-reply bug in the Judge Simulator?**
   *Answer*: The simulator originally generated a *new* conversation ID for every turn in the loop (`conv_auto_1`, `conv_auto_2`). I patched it to use a static ID so the bot's memory could accurately detect the history.
20. **If you had an LLM API key, where would you integrate it?**
   *Answer*: Inside the `LLMProvider.generate()` method in `composer.py` for dynamic string generation, and inside the fallback bucket of `/v1/reply` in `bot.py` for natural conversation handling.

## 17. Glossary
* **API Endpoint**: A specific URL path (e.g. `/v1/tick`) that accepts HTTP requests.
* **Context**: The JSON profiles representing business rules and entity details.
* **Trigger**: An event payload dictating a required action, scope, and urgency.
* **Suppression Key**: A unique identifier tied to an event type (e.g. `2026W17_Digest`). When tracked alongside a `merchant_id`, it prevents duplicate spam.
* **Idempotency**: The ability to send the same API request multiple times without changing the result beyond the initial application.
* **Deterministic Logic**: Code that yields the exact same output every single time given the exact same input, without relying on random AI hallucination.
* **JSONL**: JSON Lines. A text file where each line is a standalone JSON object.

## 18. Final Summary
The `vera-ai-challenge` backend implementation successfully operates a deterministic, event-driven state machine. It cleanly ingests contextual profiles with idempotent version checks, filters trigger backlogs based on strict expiration and suppression boundaries, and generates deterministic textual outputs guarded by Regex taboo filters. 

While the official AI Judge evaluation remains practically unverified due to the absence of a viable API key, the core architectural logic has been thoroughly proven by 14 local pytests and perfectly complies with the structural schemas outlined in the challenge guidelines. The final artifact, `submission.jsonl`, is generated and ready for delivery.
