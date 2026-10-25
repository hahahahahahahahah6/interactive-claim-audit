import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from interactive_claim_audit.audit import audit, extract_claims, extract_evidence, NONINTERACTIVE, INTERACTIVE
from interactive_claim_audit.__main__ import main

FIXTURES = Path(__file__).parent / 'fixtures'


class Claims(unittest.TestCase):
    def families(self, text):
        return {c['family'] for c in extract_claims(text)}

    def test_overlap(self):
        self.assertEqual(self.families('no confirmation prompt'), {'noninteractive'})

    def test_not_interactive(self):
        self.assertEqual(self.families('this tool is not interactive'), {'noninteractive'})

    def test_not_prompt_user(self):
        self.assertEqual(self.families('does not prompt the user'), {'noninteractive'})

    def test_bare_adjective(self):
        self.assertFalse(self.families('an interactive tool'))

    def test_bare_noun(self):
        self.assertFalse(self.families('prompt engineering'))

    def test_negation(self):
        self.assertFalse(self.families('does not run in interactive mode'))

    def test_fenced(self):
        self.assertFalse(self.families('```text\nruns unattended\n```'))

    def test_tilde_fenced(self):
        self.assertFalse(self.families('~~~~\ninteractive mode\n~~~~'))

    def test_inline(self):
        self.assertEqual(self.families('`interactive mode`'), {'interactive'})

    def test_sentence_scope(self):
        self.assertEqual(self.families('Not supported. Interactive mode.'), {'interactive'})

    def test_exact_phrases(self):
        self.assertFalse(self.families('prompts for user confirmation; runs fully unattendedly'))

    def test_boundary(self):
        self.assertFalse(self.families('xnon-interactive; interactive modes'))

    def test_line_number(self):
        self.assertEqual(extract_claims('```\nno prompts\n```\nno prompts')[0]['line'], 4)


class Evidence(unittest.TestCase):
    def check(self, code, count=1):
        self.assertEqual(len(extract_evidence(code, 'main.py')), count)

    def test_input(self): self.check('input()')
    def test_builtin(self): self.check('builtins.input()')
    def test_getpass_attribute(self): self.check('getpass.getpass()')
    def test_any_getpass_receiver(self): self.check('obj.getpass()')
    def test_getpass_bare_unimported(self): self.check('getpass()', 0)
    def test_getpass_import(self): self.check('from getpass import getpass\ngetpass()')
    def test_getpass_alias(self): self.check('from getpass import getpass as gp\ngp()')
    def test_prompt(self): self.check('obj.prompt()')
    def test_confirm(self): self.check('obj.confirm()')
    def test_questionary(self): self.check('import questionary\nquestionary.text()')
    def test_questionary_alias(self): self.check('import questionary as q\nq.text()')
    def test_questionary_from(self): self.check('from questionary import text as t\nt()')
    def test_questionary_unimported(self): self.check('questionary.text()', 0)
    def test_toolkit(self): self.check('from prompt_toolkit import prompt\nprompt()')
    def test_toolkit_alias(self): self.check('from prompt_toolkit import prompt as p\np()')
    def test_toolkit_module(self): self.check('import prompt_toolkit\nprompt()')
    def test_toolkit_shortcuts(self): self.check('from prompt_toolkit import shortcuts\nprompt()')
    def test_prompt_bare(self): self.check('prompt()', 0)
    def test_stdin(self): self.check('sys.stdin.readline()\nsys.stdin.read()\nsys.stdin.readlines()', 0)
    def test_print(self): self.check('print("hello")', 0)
    def test_option(self): self.check('click.option("--yes", prompt=True)', 0)
    def test_local_input(self): self.check('def input(): pass\ninput()')
    def test_dead_code(self): self.check('def unused():\n    input()')
    def test_dedupe(self): self.check('obj.prompt(); obj.prompt()')
    def test_separate_lines(self): self.check('input()\ninput()', 2)


class Audit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def test_no_claim(self):
        self.write('main.py', 'input()')
        self.assertFalse(audit(self.root)['findings'])

    def test_ignore(self):
        self.write('README.md', 'no prompts')
        self.write('main.py', 'pass')
        self.write('extra.py', 'input()')
        self.assertFalse(audit(self.root, ['extra.py'])['findings'])

    def test_both_families_no_source(self):
        self.write('README.md', 'runs unattended. Interactive mode.')
        findings = audit(self.root)['findings']
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f['severity'] == 'HIGH' and f['evidence'] == [{'kind': 'no-source'}] for f in findings))

    def test_both_families_test_only(self):
        self.write('README.md', 'runs unattended. Interactive mode.')
        self.write('main.py', 'pass')
        self.write('tests/test_x.py', 'input()')
        self.assertEqual(len(audit(self.root)['findings']), 2)

    def test_interactive_test_only(self):
        self.write('README.md', 'interactive mode')
        self.write('main.py', 'pass')
        self.write('fixtures/x.py', 'input()')
        self.assertEqual(audit(self.root)['findings'][0]['rule'], 'documented-interactive-claim-false-test-only')

    def test_all_evidence_one_finding(self):
        self.write('README.md', 'no prompts. runs unattended.')
        self.write('main.py', 'input()\nobj.confirm()')
        result = audit(self.root)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(len(result['findings'][0]['evidence']), 2)

    def test_docs_scope(self):
        self.write('other.md', 'no prompts')
        self.write('docs/nested/a.md', 'interactive mode')
        self.write('main.py', 'input()')
        self.assertEqual([v['family'] for v in audit(self.root)['verified_claims']], ['interactive'])

    def test_excluded_sources(self):
        self.write('README.md', 'no prompts')
        self.write('main.py', 'pass')
        for path in ('docs/x.py', 'examples/x.py'):
            self.write(path, 'input()')
        self.assertFalse(audit(self.root)['findings'])

    def test_test_filename(self):
        self.write('README.md', 'no prompts')
        self.write('main.py', 'pass')
        self.write('unit_test.py', 'input()')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')

    def test_symlink(self):
        self.write('README.md', 'no prompts')
        self.write('main.py', 'pass')
        (self.root / 'linked.py').symlink_to(FIXTURES / 'bad/noninteractive/main.py')
        (self.root / 'linked_dir').symlink_to(FIXTURES / 'bad/noninteractive', target_is_directory=True)
        self.assertFalse(audit(self.root)['findings'])

    def test_env_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            return original(path, *args, **kwargs)
        output = io.StringIO()
        with patch.object(Path, 'open', guarded), contextlib.redirect_stdout(output):
            self.assertEqual(main([str(FIXTURES / 'testonly'), '--json']), 2)
        self.assertNotIn('CLAIM_AUDIT_MARKER_ONLY_NOT_A_SECRET', output.getvalue())

    def test_parse_warning(self):
        self.write('main.py', 'def !')
        self.assertEqual(len(audit(self.root)['errors']), 1)

    def test_imports_are_per_file(self):
        self.write('README.md', 'no prompts')
        self.write('a.py', 'from getpass import getpass')
        self.write('b.py', 'getpass()')
        self.assertFalse(audit(self.root)['findings'])


class CLI(unittest.TestCase):
    def run_cli(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(args)
        return code, out.getvalue()

    def test_good_noninteractive(self):
        code, out = self.run_cli([str(FIXTURES / 'good/noninteractive'), '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['verified_claims'][0]['family'], 'noninteractive')

    def test_good_interactive(self):
        code, out = self.run_cli([str(FIXTURES / 'good/interactive'), '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['verified_claims'][0]['family'], 'interactive')

    def test_bad_noninteractive(self): self.bad('noninteractive')
    def test_bad_interactive(self): self.bad('interactive')
    def bad(self, family):
        code, out = self.run_cli([str(FIXTURES / ('bad/' + family)), '--json'])
        findings = json.loads(out)['findings']
        self.assertEqual(code, 2)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'documented-' + family + '-claim-false')
        self.assertEqual(findings[0]['severity'], 'HIGH')

    def test_medium(self):
        code, out = self.run_cli([str(FIXTURES / 'testonly'), '--json'])
        self.assertEqual(code, 2)
        findings = json.loads(out)['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'MEDIUM')
        self.assertEqual(findings[0]['rule'], 'documented-noninteractive-claim-false-test-only')

    def test_threshold(self):
        code, out = self.run_cli([str(FIXTURES / 'testonly'), '--fail-on', 'HIGH', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['findings'][0]['severity'], 'MEDIUM')

    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            _, out = self.run_cli(['--version'])
        self.assertEqual(cm.exception.code, 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            main(['--version'])
        self.assertEqual(output.getvalue().strip(), '0.1.0')

    def test_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(['--unknown'])
        self.assertEqual(cm.exception.code, 1)

    def test_invalid_path(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main(['/nonexistent/claim-audit-path'])
        self.assertEqual(cm.exception.code, 1)

    def test_verbose(self):
        code, out = self.run_cli([str(FIXTURES / 'good/interactive'), '--verbose'])
        self.assertEqual(code, 0)
        self.assertIn('verified: interactive', out)


# Each exact phrase is independently pinned, including capitalization.
def phrase_test(phrase, family):
    def test(self):
        self.assertEqual(self.families(phrase.upper()), {family})
    return test

for family, phrases in [('noninteractive', NONINTERACTIVE), ('interactive', INTERACTIVE)]:
    for index, phrase in enumerate(phrases):
        setattr(Claims, 'test_phrase_' + family + '_' + str(index), phrase_test(phrase, family))

if __name__ == '__main__':
    unittest.main()
