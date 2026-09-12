"""Crossed session-isolation tests (contract S2/S3).

Phase 1 moved state ownership into per-session services. These tests prove that
two sessions never share a presentation, history, checkpoint, confirmation, or
memory, and that a replacement in one session cannot affect another.
"""
