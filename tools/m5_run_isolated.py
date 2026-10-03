#!/usr/bin/env python3
"""Run the unchanged M5 interface with reference/ZIP reads denied in this process.

Fixtures must have been built by a separate process. This process cannot prepare
fixtures or evaluate them. Optional replay checks compare fresh runs and an
already-corrected projection; no expected IC output is an input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install_guard() -> tuple[set[str], list[str]]:
    """An audit hook cannot be removed by the solver; filenames are resolved first."""
    reads: set[str] = set()
    denied: list[str] = []

    def guard(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes)):
            return
        raw = args[0].decode() if isinstance(args[0], bytes) else args[0]
        path = Path(raw).resolve()
        # No ZIP, reference directory, scorer or evaluator code can be opened.
        if ('golden' in path.parts or 'evaluation' in path.parts
                or path.suffix == '.zip' or path.name in {'score.py', 'm5_evaluate.py'}):
            denied.append(str(path))
            raise PermissionError(f'Isolated M5 denies reference/evaluator/archive access: {path}')
        mode = args[1]
        if mode is None or 'r' in str(mode) or '+' in str(mode):
            reads.add(str(path))

    sys.addaudithook(guard)
    return reads, denied


def run(args) -> dict:
    if args.out.exists():
        raise FileExistsError('Isolated-run output directory must be new')
    args.out.mkdir(parents=True)
    reads, denied = install_guard()
    probe = args.out / 'golden' / 'ic.jsonl'
    try:
        probe.open('rb')
    except PermissionError:
        pass
    else:
        raise AssertionError('Reference-read guard is inactive')
    probe_denials = len(denied)
    from kalmora.ic.__main__ import main
    from kalmora.ic.model import digest
    command = ['--phase', str(args.phase.resolve()), '--upstream', str(args.upstream.resolve()),
               '--backend-commit', args.backend_commit]
    code = main(command + ['--out', str(args.out / 'first'), '--write-projection'])
    first = args.out / 'first'
    audit = json.loads((first / 'audit.json').read_text())
    report = {'schema_version': 1, 'integration_mode': audit['metadata']['integration_mode'],
              'real_flow_verified': False, 'real_flow_gate': '#159', 'first_exit_code': code,
              'backend_base_commit': args.backend_commit, 'python': sys.version.split()[0],
              'upstream_sha256': sha(args.upstream), 'ic_sha256': sha(first / 'ic.jsonl'),
              'guard_probe_passed': True, 'recorded_sha256': audit['metadata']['recorded_sha256'],
              'source_erp_preserved': audit['metadata']['source_erp_preserved']}
    if args.check_replay:
        second = args.out / 'repeat'
        second_code = main(command + ['--out', str(second)])
        payload = json.loads(args.upstream.read_text())
        payload['prior_projection'] = str((first / 'projected_journal.jsonl').resolve())
        replay_input = args.out / 'replay-upstream.json'
        replay_input.write_text(json.dumps(payload, ensure_ascii=False) + '\n')
        replay = args.out / 'replay'
        replay_code = main(['--phase', str(args.phase.resolve()), '--upstream', str(replay_input),
                           '--backend-commit', args.backend_commit, '--out', str(replay)])
        replay_audit = json.loads((replay / 'audit.json').read_text())
        replay_rows = [json.loads(line) for line in (replay / 'ic.jsonl').read_text().splitlines() if line]
        checks = {
            'fresh_output_identical': sha(first / 'ic.jsonl') == sha(second / 'ic.jsonl'),
            'replay_emits_no_adjustments': all(not row['adjustment'] for row in replay_rows),
            'replay_projection_unchanged': audit['metadata']['corrected_sha256'] == replay_audit['metadata']['corrected_sha256'],
            'replay_preserves_original': report['recorded_sha256'] == replay_audit['metadata']['recorded_sha256'],
            'same_exit_codes': code == second_code == replay_code,
        }
        report['replay_checks'] = checks
        if not all(checks.values()):
            raise AssertionError(f'Replay check failed: {checks}')
        report['fresh_output_sha256'] = [sha(first / 'ic.jsonl'), sha(second / 'ic.jsonl')]
        report['replay_projection_sha256'] = replay_audit['metadata']['corrected_sha256']
    report['guard_read_paths'] = sorted(reads)
    report['guard_read_paths_sha256'] = digest(sorted(reads))
    report['guard_solver_denials'] = denied[probe_denials:]
    if report['guard_solver_denials']:
        raise AssertionError('Solver attempted to read forbidden reference data')
    (args.out / 'isolation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--backend-commit', required=True)
    parser.add_argument('--check-replay', action='store_true')
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({k: v for k, v in report.items() if k != 'guard_read_paths'}, sort_keys=True))
    raise SystemExit(report['first_exit_code'])
