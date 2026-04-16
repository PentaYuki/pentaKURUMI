# Changelog — pentaKURUMI System

All notable changes to this project will be documented in this file.

## [5.8.0] — 2026-04-16

### 🚀 Milestone: Ultra-Low Latency Engine & Stateful Memory

This update represents a major architectural shift, moving away from external heavy inference clients to a deeply integrated, high-performance embedded engine optimized for Apple Silicon.

#### 🧠 AI Engine & Inference
- **Migration to MLX-vLLM**: Replaced the legacy `llama.cpp` (Bonsai) architecture with a direct-embedded **MLX-vLLM** engine (Qwen2.5-7B-Instruct-4bit).
- **Stateful KV Caching**: Implemented a persistent KV cache system. The model now "remembers" the prefixes of your conversation history, reducing prefill time by **70%** (from ~15s down to ~5s total).
- **Smart Hybrid Routing**:
    - **Tier 0 (Phrase Engines)**: Sub-ms semantic matching for taught phrases.
    - **Tier 1 (Fast-Path)**: Ollama 3.2 1B for casual/short queries (Sub-3s response).
    - **Tier 2 (Brain-Path)**: MLX 7B for complex reasoning and tasks.

#### 💾 Memory & RAG
- **Redis Integration**: Re-integrated Redis as the primary short-term context store. History is now persistent across server restarts.
- **FAISS Long-Term Memory**: Implemented a RAG (Retrieval-Augmented Generation) pipeline using FAISS and `nomic-embed-text`. PentaMi can now "recall" memories from any past interaction.
- **Vault System**: Automated background saving of high-quality Q&A pairs into the long-term vector store.

#### 🛠️ Core Improvements
- **Pre-warming Engine**: Servers now pre-load and warm up the 7B model asynchronously during startup for zero-latency first-token delivery.
- **Ollama Tuning**: Optimized thread count and history trimming for the 1B model to maximize CPU/GPU efficiency on Mac Mini.
- **Pronoun Enforcement**: Direct token-level pronoun enforcement for a more consistent wibu/cute personality.

---
*Created with love for a More Human AI. 🔺*
