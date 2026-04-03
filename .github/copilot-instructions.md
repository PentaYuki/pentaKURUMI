# Project Guidelines

## Architecture
- This workspace has three main parts:
  - `PentaAI_Mac/`: Python backend (FastAPI + WebSocket + hormone/NLP engines).
  - `PentaCommand/`: SwiftUI iOS client (voice capture, WebSocket, UI state machine).
  - `PentakuruV4/`: Optional Windows remote-control app (Python UI + Flask).
- Backend entry points:
  - `PentaAI_Mac/ai_server.py` for the main AI server (REST + `/ws/chat`).
  - `PentaAI_Mac/cli.py` for the web console.
- Keep module boundaries intact:
  - `PentaAI_Mac/core/` for parsing/intent/time/profile/action orchestration.
  - `PentaAI_Mac/engine/` for phrase matching, slots, response composition.
  - `PentaAI_Mac/hormone/` for emotion/hormone logic.
  - `PentaAI_Mac/memory/` and `PentaAI_Mac/penta_memory.py` for persistence/LLM memory.

## Build And Run
- Start backend API server:
  - `cd PentaAI_Mac && python ai_server.py` (default port `9090`)
- Start backend web console:
  - `cd PentaAI_Mac && python cli.py` (default port `8080`)
- Run iOS app:
  - `open PentaCommand.xcodeproj` then build from Xcode (physical device required for mic/speech).
- Run Windows controller (optional):
  - `cd PentakuruV4 && python pentaKuruV4.py`
- Tests:
  - There is no established automated test suite in this workspace yet. Prefer targeted validation by running changed components directly.

## Conventions
- Preserve existing Vietnamese-first user text and comments; add English only when needed for clarity.
- Prefer minimal, localized edits; do not refactor across `core/`, `engine/`, `hormone/`, and iOS files unless requested.
- Keep API contracts stable:
  - WebSocket payload shape for `/ws/chat`.
  - Token-protected REST behavior in `PentaAI_Mac/ai_server.py`.
- Follow existing fallback patterns (graceful degradation when optional systems are unavailable, e.g., Redis/TTS/emotion helpers).
- Be careful with persisted runtime data and secrets:
  - Do not commit local state/config artifacts (see `.gitignore`).

## Environment Pitfalls
- Ollama is expected for local LLM features (default `http://localhost:11434`).
- Default ports can conflict: `9090` (AI server), `8080` (console), `11434` (Ollama), optional `6379` (Redis).
- Embedding models may trigger large first-run downloads under `PentaAI_Mac/data/model_cache/`; use `tfidf` mode when low-resource setup is needed.
- Connectivity depends on matching config values across backend and client (notably auth token and Tailscale/IP settings).

## Reference Docs
- System overview and quick setup: `README.md`
- iOS app setup and operation: `PentaCommand/README.md`
- Windows controller details: `PentakuruV4/README.md`
- Valtec TTS details: `PentaAI_Mac/tts_engine/valtec/README.md`
