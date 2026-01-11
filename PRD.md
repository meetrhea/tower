# Claude Code Phone Escalation Wrapper

## Problem & Goals

**Pain:** Claude Code runs autonomously in tmux sessions but gets blocked on decisions, errors, or permission prompts while I'm away from my desk. I have to constantly monitor terminal windows to catch these moments.

**Solution:** A wrapper that detects when Claude Code needs human input, calls me on the phone with a spoken summary, accepts my voice/DTMF response, and injects that decision back into the agent.

**Success Criteria:**
- When Claude hits a decision boundary, my phone rings within 30 seconds
- I hear a concise summary of what's happening and my options
- My response (keypad or voice) steers the agent without touching a keyboard
- The interaction is logged for future preference learning

---

## Users & Scenarios

**Primary User:** Senior engineer running 1-3 long-lived Claude Code sessions across projects

**Key Scenarios:**

| Scenario | Trigger Pattern | Expected Call |
|----------|-----------------|---------------|
| Test failure | `FAILED`, traceback, exit code != 0 | "Tests failed in project X. 3 failures in auth module. Press 1 to retry, 2 to skip, 3 for details" |
| Permission prompt | Claude's permission request text | "Claude wants to run `rm -rf node_modules`. Press 1 to allow, 2 to deny" |
| Stuck/confused | No output for 60s while in "thinking" state | "Claude seems stuck on database migration. Press 1 to continue, 2 to abort, 3 to give guidance" |
| Deployment decision | `deploy`, `push to prod`, migration keywords | "Ready to deploy to production. Press 1 to proceed, 2 to cancel" |

---

## Core Flow (v1)

```
┌─────────────────┐
│  tmux pane      │
│  (Claude Code)  │
└────────┬────────┘
         │ capture-pane every 2s
         ▼
┌─────────────────┐
│  Event Detector │──── no event ──▶ (loop)
│  (Python daemon)│
└────────┬────────┘
         │ event detected
         ▼
┌─────────────────┐
│  LLM Summarizer │
│  (Claude API)   │
└────────┬────────┘
         │ { speech_text, options[], claude_instruction_template }
         ▼
┌─────────────────┐
│  Twilio Call    │
│  Outbound Voice │
└────────┬────────┘
         │ speak summary, gather DTMF/voice
         ▼
┌─────────────────┐
│  Response       │
│  Handler        │
└────────┬────────┘
         │ map response to claude_instruction
         ▼
┌─────────────────┐
│  tmux send-keys │
│  back to pane   │
└─────────────────┘
```

---

## Functional Requirements

### Event Detection
- [ ] Poll tmux pane every 2 seconds via `tmux capture-pane -p -S -50`
- [ ] Strip ANSI escape codes
- [ ] Pattern match against configurable triggers:
  - Error patterns: `FAILED`, `Error:`, `Traceback`, non-zero exit
  - Permission patterns: Claude's "Do you want to" / "Allow?" prompts
  - Stall detection: no new output for 60s while process is running
- [ ] Debounce: don't re-trigger on same event within 5 minutes

### LLM Summarizer
- [ ] Prompt template that takes raw tmux output and produces:
  - `speech_text`: 2-3 sentences, speakable, no jargon
  - `options`: array of { dtmf_key, label, claude_instruction }
  - `context_snippet`: key lines for logging
- [ ] Use Claude API (claude-3-haiku for speed, upgrade later)
- [ ] Timeout: 10 seconds max

### Phone Integration (Twilio)
- [ ] Outbound call to configured phone number
- [ ] TwiML flow:
  1. `<Say>` the speech_text
  2. `<Gather>` for DTMF input (timeout 30s)
  3. Fallback: `<Record>` short voice memo for STT processing
- [ ] Webhook receives response, maps to action
- [ ] If no answer after 3 rings, log and continue (don't block agent)

### Response Handling
- [ ] Map DTMF digit to corresponding option's `claude_instruction`
- [ ] If voice memo: transcribe via Whisper, feed to LLM for intent extraction
- [ ] Send instruction to correct tmux pane via `tmux send-keys -t <pane>`
- [ ] Confirm action was sent (check pane output changed)

### Logging
- [ ] Store each interaction:
  ```json
  {
    "timestamp": "2024-01-15T10:30:00Z",
    "session": "claude-infra",
    "pane": "%3",
    "event_type": "test_failure",
    "raw_output": "...",
    "speech_text": "...",
    "options_offered": [...],
    "human_response": "1",
    "instruction_sent": "yes, retry the tests",
    "outcome": "tests_passed"
  }
  ```
- [ ] SQLite for v1, migrate to Supabase later

---

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Event → phone ring | < 30 seconds |
| Call duration | < 60 seconds typical |
| Uptime | Best effort (personal tool) |
| Concurrent sessions | 3 tmux panes |
| Cost | < $5/month Twilio for personal use |

---

## Tech Stack (v1)

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Daemon | Python 3.11 | Fast to write, good tmux/subprocess support |
| LLM | Claude API (Haiku) | Speed, cost, familiarity |
| Telephony | Twilio Voice | Best docs, quick setup, DTMF + recording |
| STT (v1.5) | Whisper (local or API) | Already have it running |
| Logging | SQLite | Zero config, portable |
| Hosting | Local Mac + ngrok for webhooks | Simplest for prototype |

---

## Two-Week Sprint Plan

### Week 1: Core Loop (No Phone Yet)

**Day 1-2: tmux Event Detection**
- [ ] Python script that monitors a target pane
- [ ] Event pattern matching (errors, prompts)
- [ ] CLI output: "Detected: test_failure at 10:30"

**Day 3-4: LLM Summarizer**
- [ ] Prompt engineering for concise spoken summaries
- [ ] API integration with Claude
- [ ] Test with real Claude Code output samples

**Day 5: Local Voice Loop**
- [ ] Replace phone with local TTS (pyttsx3 or say command)
- [ ] Keyboard input simulates DTMF
- [ ] Full loop: detect → summarize → speak → input → send-keys
- [ ] **Milestone: Working local prototype**

### Week 2: Phone Integration

**Day 6-7: Twilio Setup**
- [ ] Twilio account, phone number
- [ ] Basic outbound call that speaks static text
- [ ] ngrok tunnel for webhooks

**Day 8-9: Dynamic Calls**
- [ ] TwiML generation from summarizer output
- [ ] DTMF gathering and webhook handling
- [ ] Response → tmux send-keys

**Day 10: Polish & Demo**
- [ ] Error handling (call failures, timeouts)
- [ ] Logging to SQLite
- [ ] README with setup instructions
- [ ] **Milestone: End-to-end phone demo**

---

## Future Work (Post-v1)

- **Multi-channel walkie-talkie**: PTT interface for multiple tmux sessions
- **Preference learning**: Suggest common responses based on interaction history
- **Smart escalation**: Only call for high-severity events, auto-approve trivial ones
- **Mobile app**: Custom UI instead of phone call
- **Voice-first mode**: Continuous listening while working, interrupt Claude anytime

---

## Open Questions

1. **What events should NEVER auto-continue?** (e.g., production deploys, file deletions)
2. **Should the wrapper pause Claude while waiting for human response?**
3. **How to handle multiple rapid events?** (Queue? Batch into one call?)
4. **Phone number configuration**: Hardcode for v1, or config file?

---

## Appendix: Sample Prompts

### Event Classification Prompt
```
You are analyzing terminal output from an AI coding assistant (Claude Code).

Classify the current state:
- ERROR: The agent encountered a failure (test, build, runtime)
- PERMISSION: The agent is asking for human approval
- STUCK: The agent seems confused or hasn't progressed
- NORMAL: Nothing requires escalation

Output JSON: { "state": "...", "confidence": 0.0-1.0, "key_lines": [...] }

Terminal output:
---
{tmux_output}
---
```

### Summarizer Prompt
```
You are a voice assistant helping a developer monitor their AI coding agent.

Given this terminal output, create a brief phone message:
1. What happened (1 sentence, no jargon)
2. What are the options (2-3 choices)
3. For each option, what instruction to send back to the agent

Format as JSON:
{
  "speech": "Your tests failed in the auth module. Three tests are broken.",
  "options": [
    { "key": "1", "label": "retry tests", "instruction": "Run the tests again" },
    { "key": "2", "label": "skip and continue", "instruction": "Skip the failing tests and continue" },
    { "key": "3", "label": "show details", "instruction": "Show me the full error output" }
  ]
}

Terminal output:
---
{tmux_output}
---
```
