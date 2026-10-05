"""Shared, target-agnostic benchmark library: streaming client, stats, storage, provenance.

Used by every suite: `engine/` (direct to one inference server) and `system/`
(end-to-end through the router). Nothing here starts or knows about a specific server.
"""
