"""Static documentation and prompt-call auditing; never imports audited code."""
import ast
import fnmatch
import os
from pathlib import Path
import re

NONINTERACTIVE = (
    'non-interactive', 'non interactive', 'not interactive', 'no prompts',
    'no user input', 'without user input', 'does not prompt', "doesn't prompt",
    'never prompts', 'without prompting', 'no interaction required',
    'no confirmation prompt', 'no manual intervention', 'does not ask',
    'never asks', 'runs unattended', 'unattended', 'CI-friendly', 'CI friendly',
    'suitable for CI', 'works in CI',
)
INTERACTIVE = (
    'interactive mode', 'interactive prompt', 'interactive use',
    'interactive confirmation', 'confirmation prompt', 'prompts for confirmation',
    'asks for confirmation', 'asks the user', 'prompts the user',
    'prompt for confirmation', 'ask the user',
)
NEGATION = re.compile(r"\b(?:no|not|never|without|doesn't|don't|isn't|does not)\b", re.I)


def phrase_pattern(phrases):
    return re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=len, reverse=True)) + r')(?!\w)', re.I)


def extract_claims(text, path='README.md'):
    """Return phrase occurrences with locations, excluding Markdown fences."""
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if fence:
            lines.append('\n' if line.endswith('\n') else '')
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not line[match.end():].strip():
                fence = None
        elif match:
            fence = match[1]
            lines.append('\n' if line.endswith('\n') else '')
        else:
            lines.append(line)
    prose = ''.join(lines)
    result = []
    for sentence in re.finditer(r'[^.!?]+(?:[.!?]|$)', prose):
        value = sentence[0]
        masked = list(value)
        for match in phrase_pattern(NONINTERACTIVE).finditer(value):
            result.append({'family': 'noninteractive', 'path': path,
                           'line': prose.count('\n', 0, sentence.start() + match.start()) + 1,
                           'phrase': match[0]})
            masked[match.start():match.end()] = ' ' * len(match[0])
        if not NEGATION.search(value):
            for match in phrase_pattern(INTERACTIVE).finditer(''.join(masked)):
                result.append({'family': 'interactive', 'path': path,
                               'line': prose.count('\n', 0, sentence.start() + match.start()) + 1,
                               'phrase': match[0]})
    return result


def extract_evidence(source, path):
    tree = ast.parse(source, filename=path)
    getpass_names = set()
    questionary_names = set()
    questionary_functions = set()
    toolkit_names = set()
    toolkit_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'questionary':
                    questionary_names.add(alias.asname or alias.name)
                if alias.name == 'prompt_toolkit' or alias.name.startswith('prompt_toolkit.'):
                    toolkit_names.add(alias.asname or alias.name.split('.')[0])
                    toolkit_imported = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == 'getpass':
                getpass_names.update(a.asname or a.name for a in node.names if a.name == 'getpass')
            if node.module == 'questionary':
                questionary_functions.update(a.asname or a.name for a in node.names)
            if node.module and (node.module == 'prompt_toolkit' or node.module.startswith('prompt_toolkit.')):
                toolkit_imported = True
                toolkit_names.update(a.asname or a.name for a in node.names if a.name == 'shortcuts')
                toolkit_names.update(a.asname or a.name for a in node.names if a.name == 'prompt')
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        kind = None
        if isinstance(func, ast.Name):
            if func.id == 'input':
                kind = 'input'
            elif func.id in getpass_names:
                kind = 'getpass'
            elif func.id in questionary_functions:
                kind = 'questionary'
            elif toolkit_imported and (func.id == 'prompt' or func.id in toolkit_names and func.id != 'shortcuts'):
                kind = 'prompt_toolkit'
        elif isinstance(func, ast.Attribute):
            if func.attr in ('prompt', 'confirm', 'getpass'):
                kind = func.attr
            elif func.attr == 'input' and isinstance(func.value, ast.Name) and func.value.id == 'builtins':
                kind = 'input'
            elif isinstance(func.value, ast.Name) and func.value.id in questionary_names:
                kind = 'questionary'
        if kind:
            result[(path, node.lineno, kind)] = {'path': path, 'line': node.lineno, 'kind': kind}
    return sorted(result.values(), key=lambda e: (e['path'], e['line'], e['kind']))


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('audit path must be a directory')
    claims, production, testonly, errors = [], [], [], []
    source_count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink() and not any(fnmatch.fnmatch((Path(directory) / d).relative_to(root).as_posix(), p) for p in ignore))
        for name in sorted(files):
            file = Path(directory) / name
            relative = file.relative_to(root)
            path = relative.as_posix()
            if file.is_symlink() or name == '.env' or name.startswith('.env.') or any(fnmatch.fnmatch(path, p) for p in ignore):
                continue
            is_doc = path == 'README.md' or (relative.parts[0] == 'docs' and file.suffix == '.md')
            if is_doc:
                claims.extend(extract_claims(file.read_text(encoding='utf-8'), path))
            if file.suffix != '.py' or any(p in ('docs', 'examples') for p in relative.parts[:-1]):
                continue
            test = any(p in ('tests', 'fixtures') for p in relative.parts[:-1]) or name.startswith('test_') or name.endswith('_test.py')
            if not test:
                source_count += 1
            try:
                evidence = extract_evidence(file.read_text(encoding='utf-8-sig'), path)
            except (SyntaxError, UnicodeError) as exc:
                errors.append({'path': path, 'message': str(exc)})
                continue
            (testonly if test else production).extend(evidence)
    findings, verified = [], []
    for family in ('noninteractive', 'interactive'):
        family_claims = [c for c in claims if c['family'] == family]
        if not family_claims:
            continue
        evidence = production
        severity, suffix = 'HIGH', ''
        if not source_count:
            evidence = [{'kind': 'no-source'}]
        elif not production and testonly:
            severity, suffix, evidence = 'MEDIUM', '-test-only', testonly
        elif (family == 'noninteractive' and not production) or (family == 'interactive' and production):
            verified.append({'family': family, 'claims': family_claims, 'evidence': production})
            continue
        findings.append({'rule': 'documented-' + family + '-claim-false' + suffix,
                         'severity': severity, 'claims': family_claims, 'evidence': evidence})
    return {'findings': findings, 'verified_claims': verified, 'claims': claims,
            'production_evidence': production, 'test_only_evidence': testonly, 'errors': errors}
