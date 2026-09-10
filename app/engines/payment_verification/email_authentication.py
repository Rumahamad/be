"""Validate the receiving Gmail server's attestation, never visible sender alone."""
import re
from email.utils import parseaddr

AUTH_VERSION = 'gmail-arc-v2'


def aligned(domain: str, expected: str) -> bool:
    domain = domain.lower().rstrip('.')
    return bool(expected) and (domain == expected or domain.endswith('.' + expected))


def authenticate(message: dict, bank_sender: str, forwarder: str, mailbox: str) -> dict:
    values: dict[str, list[str]] = {}
    for header in message.get('payload', {}).get('headers', []):
        values.setdefault(header['name'].lower(), []).append(header['value'])
    bank_sender, forwarder, mailbox = (v.strip().lower() for v in (bank_sender, forwarder, mailbox))
    domain = bank_sender.rpartition('@')[2]
    # Gmail prepends its own result. Never search older Authentication-Results
    # headers for a passing claim, or trust raw ARC-Authentication-Results.
    auth = values.get('authentication-results', [''])[0].lower()
    senders = values.get('from', [])
    sender = parseaddr(senders[0])[1].lower() if len(senders) == 1 else ''
    result = dict(version=AUTH_VERSION, verified=False, method=None,
                  original_message_id=values.get('message-id', [''])[0][:500],
                  google_original_message_id=values.get('x-google-original-message-id', [''])[0][:500],
                  sender=sender, authenticated_domain=None, forwarding_path_verified=False,
                  arc_pass=False, spf_pass=False, dkim_pass=False, dmarc_pass=False,
                  authentication_results=auth[:8000], reason='EMAIL_AUTH_FAILED')
    if sender != bank_sender or not domain:
        result['reason'] = 'SENDER_MISMATCH'
        return result
    if not re.match(r'^\s*mx\.google\.com\s*;', auth):
        return result
    clauses = auth.split(';')[1:]
    forwarded = bool(values.get('x-forwarded-for') or values.get('x-forwarded-to'))
    if not forwarded:
        for mechanism, properties in [('spf', ('smtp.mailfrom',)), ('dkim', ('header.d', 'header.i')), ('dmarc', ('header.from',))]:
            for clause in clauses:
                if not re.match(rf'^\s*{mechanism}=pass\b', clause):
                    continue
                clause = re.sub(r'\([^)]*\)', '', clause)
                for prop in properties:
                    match = re.search(rf'\b{re.escape(prop)}="?([^\s;"<>]+)', clause)
                    if match and aligned(match[1].rsplit('@', 1)[-1], domain):
                        result[mechanism + '_pass'] = True
        if all(result[k] for k in ('spf_pass', 'dkim_pass', 'dmarc_pass')):
            result.update(verified=True, method='DIRECT', authenticated_domain=domain, reason=None)
        return result
    route = values.get('x-forwarded-for', [''])[0].lower().split()
    destination = parseaddr(values.get('x-forwarded-to', [''])[0])[1].lower()
    # Bind route headers to Gmail's authenticated forwarding envelope; route
    # headers alone can be supplied by a sender and are not proof of ownership.
    local, _, forward_domain = forwarder.partition('@')
    expected_envelope = f'{local}+caf_={mailbox.replace("@", "=")}@{forward_domain}'
    envelope_verified = False
    for clause in clauses:
        if re.match(r'^\s*spf=pass\b', clause):
            clean = re.sub(r'\([^)]*\)', '', clause)
            envelope = re.search(r'\bsmtp\.mailfrom="?([^\s;"<>]+)', clean)
            envelope_verified = envelope_verified or bool(envelope and envelope[1] == expected_envelope)
    result['forwarding_path_verified'] = bool(forwarder and mailbox and
        forward_domain == 'gmail.com' and envelope_verified and
        len(values.get('x-forwarded-for', [])) == 1 and
        len(values.get('x-forwarded-to', [])) == 1 and
        route == [forwarder, mailbox] and destination == mailbox)
    if not result['forwarding_path_verified']:
        result['reason'] = 'FORWARDING_PATH_MISMATCH'
        return result
    # Require the receiving Gmail seal as well as Gmail's validated ARC summary.
    seal = values.get('arc-seal', [''])[0].lower()
    tags = dict(re.findall(r'(?:^|;)\s*([a-z]+)=([^;\s]+)', seal))
    if tags.get('d') != 'google.com' or tags.get('cv') != 'pass':
        return result
    for clause in clauses:
        arc = re.fullmatch(r'\s*arc=pass\s*\(([^)]+)\)\s*', clause)
        if not arc:
            continue
        evidence = arc[1]
        index = re.search(r'\bi=(\d+)\b', evidence)
        if not index or not tags.get('i', '').isdigit() or int(tags['i']) != int(index[1]) + 1:
            continue
        result['arc_pass'] = True
        for mechanism, prop in [('spf', 'spfdomain'), ('dkim', 'dkdomain'), ('dmarc', 'fromdomain')]:
            result[mechanism + '_pass'] = any(aligned(d, domain) for d in re.findall(
                rf'\b{mechanism}=pass\s+{prop}=([a-z0-9.-]+)', evidence))
        if all(result[k] for k in ('spf_pass', 'dkim_pass', 'dmarc_pass')):
            result.update(verified=True, method='GMAIL_ARC', authenticated_domain=domain, reason=None)
        return result
    return result
