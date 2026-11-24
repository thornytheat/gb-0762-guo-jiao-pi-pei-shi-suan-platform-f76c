from datetime import datetime, timezone

from app.modules.batches.seal import canonical, sha
from app.modules.batches.storage import read as archived
from app.modules.formula.contract import normalize
from . import store
from .verify import release


def _pack(record, calibration):
    stages = record['stages']
    stock, blend = stages['stock'], stages['blend']
    can_trial = blend['status'] == 'FEASIBLE' and stock['balanced'] and stock['shortage_g'] == 0
    pack = {'batch_id': record['batch_id'], 'integrity_sha256': sha(canonical(record)),
            'can_trial': can_trial, 'stock_lines': len(stock['rows']),
            'isolation_lines': len(stages['assay']['isolated']), 'record': record}
    if can_trial:
        plan = normalize(record['parameters']['plan'])
        lots = {row['lot']: row for row in stages['assay']['lots']}
        pack['release'] = {**release(plan, blend['allocation'], lots, calibration), 'basis': calibration}
    else:
        pack['release'] = {'decision': 'BLOCKED', 'pending': [], 'groups': [], 'basis': calibration}
    return pack


def _calibration(record, root):
    return record['parameters'].get('calibration', []) + store.supplements(root, record['batch_id'])


def current(root, identifier):
    record = archived(root, identifier)
    frozen = store.issued(root, record['batch_id'])
    if frozen:
        return frozen
    return {**_pack(record, _calibration(record, root)), 'issued': False}


def _applicable(entry, trial_day, accepted, sessions, assigned):
    if (entry['device'], entry['measured_on']) in sessions:
        return 'DUPLICATE_SESSION'
    if entry['measured_on'] > trial_day:
        return 'AFTER_TRIAL_DAY'
    if assigned & set(entry['lots']):
        return 'LOT_SESSION_CONFLICT'
    if not accepted & set(entry['lots']):
        return 'NO_ACCEPTED_LOT'
    return None


def sign(root, identifier, late):
    record = archived(root, identifier)
    batch_id = record['batch_id']
    frozen = store.issued(root, batch_id)
    if frozen:
        return {'outcome': 'EXISTS', 'pack': frozen, 'applied': [],
                'ignored': [{'entry': entry, 'reason': 'ALREADY_ISSUED'} for entry in late]}
    known = _calibration(record, root)
    sessions = {(entry['device'], entry['measured_on']) for entry in known}
    assigned = {lot for entry in known for lot in entry['lots']}
    accepted = {row['lot'] for row in record['stages']['assay']['lots']}
    trial_day = normalize(record['parameters']['plan'])['as_of']
    applied, ignored = [], []
    for entry in late:
        reason = _applicable(entry, trial_day, accepted, sessions, assigned)
        if reason:
            ignored.append({'entry': entry, 'reason': reason})
            continue
        applied.append(entry)
        sessions.add((entry['device'], entry['measured_on']))
        assigned |= set(entry['lots'])
    if applied:
        known = record['parameters'].get('calibration', []) + store.append_supplements(root, batch_id, applied)
    pack = _pack(record, known)
    if pack['release']['decision'] != 'ISSUABLE':
        return {'outcome': 'HELD', 'pack': {**pack, 'issued': False}, 'applied': applied, 'ignored': ignored}
    certificate = {**pack, 'issued': True, 'issued_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    certificate['certificate_id'] = sha(canonical([batch_id, certificate['issued_at'], pack['integrity_sha256']]))
    frozen, created = store.freeze(root, batch_id, certificate)
    return {'outcome': 'ISSUED' if created else 'EXISTS', 'pack': frozen, 'applied': applied, 'ignored': ignored}
