# interactive-claim-audit

Offline static audit of documented interactivity claims.

Version 0.1.0 · Python 3.9+ · MIT · standard library only at runtime.

Compare documentation promises about human interaction with named Python call sites. The auditor parses source without importing or executing the audited project, uses no network, skips symlinks, and skips `.env` and `.env.*` file contents.

## Usage

Install from a local checkout:

```sh
python3 -m pip install .
interactive-claim-audit /path/to/project
python3 -m interactive_claim_audit /path/to/project --json
interactive-claim-audit /path/to/project --verbose --ignore 'vendor/*'
interactive-claim-audit /path/to/project --fail-on HIGH
interactive-claim-audit --version
```

The path defaults to the current directory. `--ignore GLOB` is repeatable and matches relative paths. `--verbose` adds verified families and parse warnings to text output. `--json` emits a JSON object containing `status`, `findings`, `verified_claims`, `claims`, `production_evidence`, `test_only_evidence`, and `errors`.

Exit codes are 0 for PASS, 2 for findings meeting the selected threshold, and 1 for usage errors. The default threshold is MEDIUM; `--fail-on HIGH` leaves MEDIUM findings visible but permits exit 0.

## Rules

Documentation occurrences collapse into two families, `noninteractive` and `interactive`, evaluated independently. Each failing family produces one finding containing all applicable evidence items.

| Rule | Severity | Condition |
| --- | --- | --- |
| `documented-noninteractive-claim-false` | HIGH | The noninteractive family has production evidence. |
| `documented-noninteractive-claim-false-test-only` | MEDIUM | That family has evidence only in test or fixture sources. |
| `documented-interactive-claim-false` | HIGH | The interactive family lacks production evidence and has no test evidence. |
| `documented-interactive-claim-false-test-only` | MEDIUM | That family has evidence only in test or fixture sources. |

A claimed family with no production Python files produces one HIGH finding with `no-source` evidence, taking priority over the test-only rules. With production files present, the noninteractive family is verified when evidence is absent everywhere; the interactive family is verified when production evidence exists. Verified families appear in `verified_claims`. A tree with zero documentation claims passes regardless of its call sites.

## Claim vocabulary

Only root `README.md` and `docs/**/*.md` supply claims. Fenced code blocks are excluded; inline code spans count as prose. Matching is case-insensitive and limited to the exact phrases below; hyphen and space spellings are accepted only where explicitly listed.

```text
NONINTERACTIVE
non-interactive
non interactive
not interactive
no prompts
no user input
without user input
does not prompt
doesn't prompt
never prompts
without prompting
no interaction required
no confirmation prompt
no manual intervention
does not ask
never asks
runs unattended
unattended
CI-friendly
CI friendly
suitable for CI
works in CI

INTERACTIVE
interactive mode
interactive prompt
interactive use
interactive confirmation
confirmation prompt
prompts for confirmation
asks for confirmation
asks the user
prompts the user
prompt for confirmation
ask the user
```

Negation is asymmetric: a sentence containing `no`, `not`, `never`, `without`, `doesn't`, `don't`, `isn't`, or `does not` suppresses the interactive family. Matches in the noninteractive family still count, including its negated phrases. Overlap masking finds the noninteractive family first, masks its matched spans, and searches the remaining text for the interactive family. This prevents a substring from generating an extra family match.

The bare words “interactive” and “prompt” are not claims. Paraphrases outside the vocabulary are not inferred. Contradictory documentation can supply both families; each receives its own evaluation.

## Named evidence table

Evidence is collected from Python AST calls and deduplicated by relative file, line, and kind. Imports and aliases are tracked per file where indicated.

| Named call | Evidence treatment |
| --- | --- |
| `input(...)`, `builtins.input(...)` | Counts, including a locally shadowed `input`. |
| `.getpass(...)` | Counts on any receiver spelling. |
| Imported bare `getpass(...)` | Counts with `from getpass import getpass`, including aliases; a bare name without that import does not count. |
| `.prompt(...)` | Counts on any receiver, including Click, Questionary objects, and toolkit sessions. |
| `.confirm(...)` | Counts on any receiver. |
| `questionary.<name>(...)` or imported Questionary functions | Counts with tracked module or function imports and aliases. |
| Toolkit `prompt(...)` | Counts with a per-file `prompt_toolkit` import; imported `prompt` aliases and `shortcuts` imports are recognized. |

Production evidence excludes `tests/`, `fixtures/`, test filename patterns (`test_*.py`, `*_test.py`), `docs/`, and `examples/`. Test and fixture evidence is collected separately; docs and examples supply no source evidence. Symlinked files and directories are skipped. Parse and decoding failures are reported in `errors`; they are not proof that a file lacks relevant behavior.

## Differentiation

| Neighbour | Its question | This tool's distinction |
| --- | --- | --- |
| auth-claim-audit | Are credentials required? | Examines dependence on a human, including filename and yes/no questions. `getpass` overlaps explicitly: login evidence there, human-input evidence here. |
| error-claim-audit | Which failures occur? | Examines waiting for a person. |
| concurrency-claim-audit | What execution model is used? | Examines human interaction. |
| timeout-claim-audit | What time bounds apply? | Examines human blocking rather than elapsed-time guarantees. |
| Bandit / Ruff | What code issues exist? | Compares documentation promises with source evidence. |
| Click / Questionary / prompt_toolkit documentation | How are input primitives used? | Checks documentation against a project's source instead of teaching those APIs. |

## Honest limitations

This is a vocabulary-and-call-site check, not a behavioral proof. Exact-phrase claims miss paraphrases. Dead code counts: a call in an uncalled function is still evidence. Reachability, branches, flag defaults, runtime configuration, and whether a person actually sees a question are not inferred. A successful result does not prove every documented execution path behaves as intended.

Receiver types are not inferred: `.prompt`, `.confirm`, and `.getpass` calls on unrelated objects or test doubles can count. A locally defined `input` also counts. Import recognition is limited to the named evidence table; dynamic imports, indirect wrappers, and arbitrary alias assignments can escape detection.

Reading `sys.stdin.read`, `readline`, or `readlines`, including redirected or piped input, is not evidence. Printing and logging are not evidence. Argparse and Click option declarations are not evidence; in particular, `click.option(..., prompt=True)` is a documented gap because it is a declaration rather than a `.prompt(...)` call.

Curses, Urwid, and Textual interfaces are outside scope. Other libraries such as inquirer, PyInquirer, and bullet are outside scope unless their calls independently match a named pattern. Evidence found only in tests or fixtures receives MEDIUM under the rules above; it does not establish production behavior. Negation and overlap masking follow the lexical rules above rather than natural-language understanding.

## Development and packaging

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
# If isolated build dependencies are unavailable offline:
python3 -m build --no-isolation
```

The build produces a wheel and source distribution in `dist/`. The source distribution includes the test fixtures through `MANIFEST.in`.
