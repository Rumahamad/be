from copy import deepcopy
from unittest import TestCase
from app.engines.payment_verification.email_authentication import authenticate

BANK = 'alerts@hdfcbank.bank.in'
FORWARDER = 'owner@gmail.com'
MAILBOX = 'bnc@gmail.com'
AUTH = ('mx.google.com; dkim=fail header.i=@hdfcbank.bank.in; '
        'arc=pass (i=2 spf=pass spfdomain=comm.hdfcbank.bank.in '
        'dkim=pass dkdomain=hdfcbank.bank.in dmarc=pass fromdomain=hdfcbank.bank.in); '
        'spf=pass smtp.mailfrom="owner+caf_=bnc=gmail.com@gmail.com"; dmarc=fail header.from=hdfcbank.bank.in')


class ArcAuthenticationTests(TestCase):
    def setUp(self):
        self.headers = {'From': BANK, 'Authentication-Results': AUTH,
                        'X-Forwarded-For': f'{FORWARDER} {MAILBOX}',
                        'X-Forwarded-To': MAILBOX,
                        'ARC-Seal': 'i=3; d=google.com; cv=pass; b=opaque',
                        'Message-ID': '<bank-message@example>'}

    def result(self, extra=None):
        headers = [{'name': k, 'value': v} for k, v in self.headers.items()]
        return authenticate({'payload': {'headers': headers + (extra or [])}}, BANK, FORWARDER, MAILBOX)

    def test_valid_gmail_attested_bank_chain(self):
        r = self.result()
        self.assertTrue(r['verified'])
        self.assertEqual(r['method'], 'GMAIL_ARC')
        self.assertTrue(r['forwarding_path_verified'])

    def test_visible_sender_alone_fails(self):
        self.headers['Authentication-Results'] = 'mx.google.com; spf=pass smtp.mailfrom=owner@gmail.com'
        self.assertFalse(self.result()['verified'])

    def test_reject_invalid_chain_wrong_domain_route_and_sealer(self):
        original = deepcopy(self.headers)
        changes = [('Authentication-Results', AUTH.replace('arc=pass', 'arc=fail')),
                   ('Authentication-Results', AUTH.replace('dkdomain=hdfcbank.bank.in', 'dkdomain=evil.example')),
                   ('Authentication-Results', AUTH.replace('fromdomain=hdfcbank.bank.in', 'fromdomain=bank.in')),
                   ('X-Forwarded-For', f'attacker@gmail.com {MAILBOX}'),
                   ('X-Forwarded-To', 'wrong@gmail.com'),
                   ('Authentication-Results', AUTH.replace('owner+caf_', 'attacker+caf_')),
                   ('Authentication-Results', AUTH.replace('spf=pass smtp', 'spf=fail smtp')),
                   ('ARC-Seal', 'i=3; d=evil.example; cv=pass'),
                   ('ARC-Seal', 'i=2; d=google.com; cv=pass')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.headers = {**original, key: value}
                self.assertFalse(self.result()['verified'])

    def test_older_injected_result_cannot_override_failure(self):
        self.headers['Authentication-Results'] = 'mx.google.com; arc=fail'
        self.assertFalse(self.result([{'name': 'Authentication-Results', 'value': AUTH}])['verified'])

    def test_duplicate_from_rejected(self):
        self.assertFalse(self.result([{'name': 'From', 'value': BANK}])['verified'])

    def test_direct_authentication_supports_header_i(self):
        del self.headers['X-Forwarded-For'], self.headers['X-Forwarded-To']
        self.headers['Authentication-Results'] = ('mx.google.com; '
            'spf=pass smtp.mailfrom="sender@comm.hdfcbank.bank.in"; '
            'dkim=pass header.i=@hdfcbank.bank.in; dmarc=pass header.from=hdfcbank.bank.in')
        self.assertTrue(self.result()['verified'])
