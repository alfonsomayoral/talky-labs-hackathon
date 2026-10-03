"""Application layer: use cases and the ports they depend on.

Transport-free. HTTP (and later MCP or the CLI) call the same use cases; storage is
reached only through the ports in ``ports.py``.
"""
