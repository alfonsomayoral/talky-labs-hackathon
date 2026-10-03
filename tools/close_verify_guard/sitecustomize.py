"""Verification-only I/O guard, inherited by child Python processes.

Put this directory on PYTHONPATH and set KALMORA_SOURCE_PHASE explicitly.
This guard covers the Python I/O/network used by the deterministic workflow;
it is not a sandbox for hostile native code.
"""
import os
from pathlib import Path
import sys


def guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise PermissionError("verification denies network/provider access")
    if event != "open" or not isinstance(args[0], (str, bytes)):
        return
    path = Path(os.fsdecode(args[0]))
    if "golden" in path.parts or path.name.startswith("trial_balance_"):
        raise PermissionError("reference data is inaccessible to the solving process")
    mode, flags = args[1:3]
    writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
               or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR)))
    if writing and path.resolve().is_relative_to(Path(os.environ["KALMORA_SOURCE_PHASE"]).resolve()):
        raise PermissionError("original phase is read only")


sys.addaudithook(guard)
