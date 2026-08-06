"""Backend adapters for premium job sources (strategy §6).

Phase 1 ships ``opencli`` — the browser-bridge backend that drives the
user's real Chrome via OpenCLI (LinkedIn/Indeed). Each backend module owns
its own probing (health without side effects), command running, and output
parsing so source modules stay thin dispatchers.
"""
