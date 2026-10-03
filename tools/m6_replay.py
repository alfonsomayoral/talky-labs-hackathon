#!/usr/bin/env python3
"""Fresh-process replay with guarded Python I/O, imports and network.

This is an execution-boundary test for the Python solver, not a hostile-native-code
sandbox. All I/O mechanisms used by PhaseData, Path and the solver are guarded.
"""
import argparse
import builtins
import io
import json
import os
from pathlib import Path
import socket

from kalmora.close.__main__ import execute
from kalmora.close.contracts import file_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('phase', 'handoff', 'expected', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    phase = a.phase.resolve()
    denied, accessed = [], set()
    original_import = builtins.__import__

    def guard_path(path):
        if isinstance(path, int):
            return
        name = Path(os.fsdecode(path)).resolve()
        if 'golden' in name.parts or any(name.is_relative_to(phase / part) for part in ('inbox', 'bank')):
            denied.append(str(name))
            raise PermissionError('M6 replay denies golden and source-document access')
        accessed.add(str(name))

    def guarded(opener):
        def wrapped(path, *args, **kwargs):
            guard_path(path)
            return opener(path, *args, **kwargs)
        return wrapped

    def deny_network(*args, **kwargs):
        raise PermissionError('M6 replay denies network access')

    def guarded_import(name, *args, **kwargs):
        if 'kalmora.evaluation' in name or name in {'m6_fixture', 'm6_sources'}:
            raise PermissionError('M6 replay denies evaluator/fixture imports')
        return original_import(name, *args, **kwargs)

    builtins.open = guarded(builtins.open)
    io.open = guarded(io.open)
    os.open = guarded(os.open)
    builtins.__import__ = guarded_import
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    for path in (phase / 'golden/close.jsonl', phase / 'inbox/denial-probe.pdf'):
        try:
            path.read_bytes()
        except PermissionError:
            pass
        else:
            raise AssertionError('access guard failed')
    manifest = execute(phase, a.handoff, a.output, saved_facts_only=True)
    expected = json.loads((a.expected / 'freeze.json').read_text())
    compared = {}
    for name, expected_hash in expected['files'].items():
        actual = file_hash(a.output / name)
        if actual != expected_hash:
            raise AssertionError(f'replay mismatch: {name}')
        compared[name] = actual
    report = {'result': 'PASS', 'integration': manifest['integration'], 'files_equal': compared,
              'guard': 'builtins.open + io.open + os.open + imports + socket; fresh process',
              'denied_probe_paths': denied, 'solver_forbidden_accesses': len(denied) - 2,
              'unique_file_accesses': len(accessed), 'document_calls': 0, 'llm_calls': 0,
              'handoff_sha256': manifest['handoff_sha256'], 'python': manifest['python']}
    (a.output / 'replay_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
