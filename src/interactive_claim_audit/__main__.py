"""Command line entry point."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description='Offline static audit of documented interactivity claims.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true', dest='as_json')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB')
    parser.add_argument('--fail-on', choices=['MEDIUM', 'HIGH'], default='MEDIUM')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.path, args.ignore)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings'])
    result['status'] = 'FAIL' if failed else 'PASS'
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(result['status'])
        for finding in result['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            for item in finding['evidence']:
                print('  ' + item.get('path', '') + ':' + str(item.get('line', '')) + ' ' + item['kind'])
        if args.verbose:
            for claim in result['verified_claims']:
                print('verified: ' + claim['family'])
            for error in result['errors']:
                print('parse warning: ' + error['path'] + ': ' + error['message'])
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
