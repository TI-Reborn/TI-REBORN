"""Run the whole legacy suite and separate environment gaps from real failures.

The repository deliberately does not commit local research inputs: most of
evidence/ (native probe JSON, client file inventories), the installed game
client, and optional tools (pefile, unicorn, Flask, Blender). Tests that need
them error out on machines without them, which used to bury real regressions
in hundreds of unrelated errors (3077 tests: 188 failures, 297 errors on
2026-10-25 in a clean cloud checkout).

This runner classifies every failing test:
- environment: the exception (or one it was raised from) is a missing
  gitignored repository input, a path outside the repository (client files),
  or a missing optional module;
- known: listed in tools/full_tests_known.json with a category and a note
  (retired gold economy, feature not merged, needs owner decision...). A known
  entry that no longer fails is reported so the list cannot rot;
- real: everything else, including assertion failures.

Usage: python tools/run_full_tests.py [--pattern test_*.py] [--json out.json]
Exit status is 1 only when real failures exist. It never touches hosting.
"""
from collections import Counter
from pathlib import Path
import argparse
import io
import json
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_MODULES = {'pefile', 'unicorn', 'capstone', 'flask', 'waitress', 'bpy', 'PIL', 'numpy', 'werkzeug'}


def ignored(path):
    """True for an input the repository does not ship.

    That is a path outside the repository (installed client, home folders),
    a gitignored path, or a path below a directory that is absent from this
    checkout (local-only asset folders). A wrong path into an existing
    directory stays a real failure.
    """
    try:
        relative = Path(path).resolve().relative_to(ROOT)
    except ValueError:
        return True
    except OSError:
        return False
    if subprocess.run(['git', 'check-ignore', '-q', str(relative)], cwd=ROOT).returncode == 0:
        return True
    return not (ROOT/relative).parent.is_dir()


def chain(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error)); yield error
        error = error.__cause__ or error.__context__


def _from_text(text):
    """Loader failures (unittest._FailedTest) carry the original error as text."""
    import re
    for name in re.findall(r"No module named '([^']+)'", text):
        if name.split('.')[0] in OPTIONAL_MODULES:return 'module:' + name.split('.')[0]
    for name in re.findall(r"No such file or directory: '([^']+)'", text):
        if re.match(r'^[A-Za-z]:[\\/]', name):return 'file:windows-client'
        if ignored(name):
            try:return 'file:' + Path(name).resolve().relative_to(ROOT).parts[0]
            except ValueError:return 'file:outside-repository'
    return None


def environment_reason(error):
    for item in chain(error):
        if isinstance(item, OSError) and isinstance(item.filename, str) and re.match(r'^[A-Za-z]:[\\/]', item.filename):
            return 'file:windows-client'
        if isinstance(item, ImportError) and not isinstance(item, ModuleNotFoundError):
            reason = _from_text(str(item))
            if reason:return reason
        if isinstance(item, ModuleNotFoundError) and (item.name or '').split('.')[0] in OPTIONAL_MODULES:
            return 'module:' + item.name.split('.')[0]
        if isinstance(item, FileNotFoundError) and item.filename and ignored(item.filename):
            name = str(item.filename)
            try:
                return 'file:' + str(Path(name).resolve().relative_to(ROOT).parts[0])
            except ValueError:
                return 'file:outside-repository'
    return None


KNOWN = ROOT/'tools/full_tests_known.json'


def known_entries():
    data = json.loads(KNOWN.read_text(encoding='utf-8')) if KNOWN.exists() else {'entries': []}
    for entry in data['entries']:
        if not {'test', 'category', 'note'} <= set(entry):raise ValueError('Invalid known-failure entry')
    return data['entries']


class ClassifyingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.environment, self.known, self.real = [], [], []
        self.entries = known_entries()

    def _record(self, test, err, kind):
        reason = environment_reason(err[1])
        entry = dict(test=test.id(), kind=kind, error=type(err[1]).__name__,
                     message=str(err[1]).splitlines()[0][:200] if str(err[1]) else '')
        match = next((k for k in self.entries if entry['test'].startswith(k['test'])), None)
        if reason:
            entry['reason'] = reason; self.environment.append(entry)
        elif match is not None:
            entry['category'] = match['category']; self.known.append(entry)
        else:
            self.real.append(entry)

    def addError(self, test, err):
        super().addError(test, err); self._record(test, err, 'error')

    def addFailure(self, test, err):
        super().addFailure(test, err); self._record(test, err, 'failure')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(subtest, err, 'failure' if issubclass(err[0], test.failureException) else 'error')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--json', type=Path)
    parser.add_argument('modules', nargs='*', help='Run only these test modules (default: discover all)')
    args = parser.parse_args(argv)
    sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
    suite = (unittest.defaultTestLoader.loadTestsFromNames(args.modules) if args.modules else
             unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern=args.pattern, top_level_dir=str(ROOT/'tests')))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, resultclass=ClassifyingResult, verbosity=0).run(suite)
    reasons = Counter(e['reason'] for e in result.environment)
    by_module = Counter(e['test'].split('.')[0] for e in result.real)
    failing = [e['test'] for e in (*result.known, *result.environment, *result.real)]
    stale = [k['test'] for k in result.entries if not any(t.startswith(k['test']) for t in failing)]
    summary = dict(ran=result.testsRun, skipped=len(result.skipped),
                   environment=len(result.environment), environment_reasons=dict(reasons.most_common()),
                   known=len(result.known), known_categories=dict(Counter(e['category'] for e in result.known).most_common()),
                   known_now_passing=stale,
                   real=len(result.real), real_by_module=dict(by_module.most_common()))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.json:
        args.json.write_text(json.dumps(dict(summary=summary, real=result.real, known=result.known, environment=result.environment),
                                        ensure_ascii=False, indent=1))
    return 1 if result.real else 0


if __name__ == '__main__':
    raise SystemExit(main())
