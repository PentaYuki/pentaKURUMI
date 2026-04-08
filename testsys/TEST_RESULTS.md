# TestSys Report

Date: 2026-04-08
Command:

```bash
python3 -m unittest discover -s testsys -p "test_*.py" -v
```

## Summary

- Total tests: 11
- Passed: 11
- Failed: 0
- Result: OK

## Files Added

- testsys/test_toggle_intents.py
- testsys/test_pentamit_routing.py
- testsys/test_bonsai_cooldown.py
- testsys/test_penta_memory_hybrid.py

## Covered Functions

1. Pentami toggle intent parsing
- `check_toggle` parses: `on`, `off`, `on_thinking`, `off_thinking`, `clear`.

2. PentamiT routing behavior
- Thinking mode OFF: stream prefers Ollama fast path.
- Thinking mode ON: complex prompts can route to Bonsai stream.

3. Bonsai wake cooldown
- `can_wake_now` returns false during cooldown and true after cooldown.
- `_ensure_awake` does not start server while in cooldown.

4. PentaMemory hybrid logic
- `_save_vault` persists memory to JSON.
- `_retrieve_long_term_memories` filters by distance threshold.

## Raw Result (key lines)

- `Ran 11 tests in 0.066s`
- `OK`

## Notes

- Runtime emitted a non-blocking warning from `urllib3` about LibreSSL.
- This warning did not affect test outcomes.
