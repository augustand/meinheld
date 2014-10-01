from argparse import ArgumentParser
from os.path import join, abspath
from subprocess import Popen, call

import json
import sys
import re
import meinheld


RESULTS = ['OK', 'INFORMATIONAL', 'NON-STRICT',
        'UNIMPLEMENTED', 'UNCLEAN', 'FAILED']


# Environment Setup

def ensure_virtualenv():
    """A python2 instance will be installed to the current virtualenv, in
    order to run the Autobahn test client. So if there is none active, these
    tests should not proceed.
    """

    if not hasattr(sys, 'real_prefix'):
        raise Exception('Not inside a virtualenv')
    print('Running in a virtual environment')

def ensure_python2(python2):
    """As recommended by Autobahn, the test client should be run with a
    Python 2 interpreter. The interpreter is installed in the current
    virtualenv. The build to be tested by tox is also reinstalled using
    pip2, to make it available to python2 tests."""

    src = '''
import sys
try:
    sys.real_prefix
    sys.exit(0)
except AttributeError:
    sys.exit(1)
'''

    if call((python2, '-c', src)):
        print('Installing {} into virtualenv'.format(python2))
        call(('virtualenv', '-q', '-p', python2, sys.prefix))
    else:
        print(python2, 'found in virtualenv')

    zipfile = 'meinheld-{}.zip'.format(meinheld.__version__)
    zipfile = abspath(join(sys.prefix, '..', 'dist', zipfile))
    print('Installing', zipfile)
    call(('pip2', 'install', '-q', '--pre', '-U', zipfile))

def ensure_wstest():
    """Installs the test client."""

    try:
        call(('wstest', '-a'))
    except FileNotFoundError:
        print('Installing Autobahn test suite')
        call(('pip2', 'install', '-q', 'autobahntestsuite'))


# Server Setup

def setup_servers():
    """Starts servers within subprocesses."""

    print('Starting test servers')
    server27 = Popen(('python2', 'autobahn_test_server.py', '8002'))
    server34 = Popen(('python3', 'autobahn_test_server.py', '8003'))
    return server27, server34

def teardown_servers(servers):
    """Stops given servers by killing their subprocesses."""

    for server in servers:
        try:
            server.kill()
            server.wait()
        except AttributeError:
            pass
    print('Stopped test servers')


# Report Parsing

def read_report(client_conf, accept):
    """Reads the report generated by wstest."""

    with open(client_conf, 'r') as stream:
        report_dir = json.load(stream).get('outdir')

    with open(join(report_dir, 'index.json'), 'r') as stream:
        report = json.load(stream)

    passed = True
    for server_name, server in sorted(report.items()):
        print('Reading report for "{}"...'.format(server_name))
        cases = sorted(filter(lambda e: not acceptable(e[1], accept),
                server.items()), key=case_sorting_key)

        if len(cases) > 0:
            passed = False

        for key, case in cases:
            report_case(join(report_dir, case.get('reportfile')))
    return passed

def indented(n, *args):
    return '\n'.join(map(lambda ln: n * ' ' + ln,
            re.split('\r\n|\r|\n', ' '.join(args).strip())))

def level(value):
    try:
        return RESULTS.index(value)
    except ValueError:
        return len(RESULTS)

def acceptable(case, accept):
    """Verifies that a test case result is acceptable."""
    a = level(case.get('behavior')) <= accept[0]
    b = level(case.get('behaviorClose')) <= accept[1]
    return a and b

def case_sorting_key(e):
    """Sorting key for test case identifier."""
    return tuple(map(lambda n: int(n), e[0].split('.')))

def report_case(report_file):
    """Prints information about a test case."""

    with open(report_file, 'r') as stream:
        report = json.load(stream)

    msg = 'Case {id} {behavior}'.format(**report)
    if level(report.get('behaviorClose')) > 0:
        msg += ' ({} close)'.format(report.get('behaviorClose'))
    print(indented(2, msg))

    print(indented(4, 'Description:', report.get('description')))
    print(indented(4, 'Expectation:', report.get('expectation')))

    print(indented(4, 'Outcome:', report.get('result')))
    print(indented(4, 'Closing Behavior:', report.get('resultClose')))
    print()

    print(indented(4, 'Request:'))
    print(indented(6, report.get('httpRequest')))
    print(indented(4, 'Response:'))
    print(indented(6, report.get('httpResponse')))
    print()

    if report.get('wasOpenHandshakeTimeout'):
        print(indented(4, 'No response to opening handshake'))

    if not report.get('wasClean'):
        print(indented(4, 'The connection was not closed properly:'))
        print(indented(6, str(report.get('wasNotCleanReason'))))

    if report.get('closedByMe'):
        print(indented(4, 'Client initiated the closing handshake'))

    if report.get('localCloseCode') or report.get('localCloseReason'):
        print(indented(4, 'Client close: {code} - "{reason}"'.format(
                code=report.get('localCloseCode'),
                reason=report.get('localCloseReason'))))

    if report.get('reportCloseCode') or report.get('reportCloseReason'):
        print(indented(4, 'Server close: {code} - "{reason}"'.format(
                code=report.get('remoteCloseCode'),
                reason=report.get('remoteCloseReason'))))

    if report.get('wasCloseHandshakeTimeout'):
        print(indented(4, 'No response to closing handshake'))

    if report.get('wasServerConnectionDropTimeout'):
        print(indented(4, 'TCP connection not dropped by the server'))

    print()


# Entry Point

def runtests():
    """Runs the Autobahn Test Suite against Meinheld on both Python 2.7 and
    Python 3.4. The test suite itself should run on Python 2.7, and should
    collect results from all servers from a single run (to report correctly).
    This is why both servers are tested from a single environemnt.
    """

    parser = ArgumentParser(description=
            'Runs Autobahn test client against Meinheld servers.')

    parser.add_argument('-p2', '--python2', type=str, default='python2.7',
            help='The Python 2 instance in which the Autobahn test client '
            'will run')
    parser.add_argument('-r', '--accept-result', type=int, default=3,
            help='The maximum test case result to accept as non-failure')
    parser.add_argument('-c', '--accept-close-result', type=int, default=4,
            help='The maximum test case closing result to accept as '
            'non-failure')
    parser.add_argument('-s', '--settings', type=str,
            default='fuzzingclient.json', help='Settings for Autobahn\'s '
            'fuzzingclient mode.')

    args = parser.parse_args()

    ensure_virtualenv()
    ensure_python2(args.python2)
    ensure_wstest()

    servers = []
    try:
        servers = setup_servers()
        call(('wstest', '-m', 'fuzzingclient', '-s', args.settings))
    finally:
        teardown_servers(servers)

    accept = (args.accept_result, args.accept_close_result)
    sys.exit(0 if read_report(args.settings, accept) else 1)

if __name__ == '__main__':
    runtests()

