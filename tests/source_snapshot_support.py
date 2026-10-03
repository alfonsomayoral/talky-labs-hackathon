"""Use the development snapshot reader supplied by the source foundation."""
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from kalmora.documents.router import DocumentRouter


def snapshot_router(phase):
    router_type = DocumentRouter
    # Allows testing a supplied, uncommitted reader without copying or editing it.
    override = os.environ.get("KALMORA_ROUTER_MODULE")
    if override:
        spec = importlib.util.spec_from_file_location("kalmora.documents.audit_snapshot_router", override)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        router_type = module.DocumentRouter
    if "use_preparsed" not in inspect.signature(router_type).parameters:
        raise RuntimeError("snapshot reader not integrated; set KALMORA_ROUTER_MODULE to the supplied router.py")
    normalized = Path(os.environ.get("KALMORA_NORMALIZED_SOURCES", phase.parent / "normalized_sources"))
    return router_type(phase, use_preparsed=True, normalized_dir=normalized)
