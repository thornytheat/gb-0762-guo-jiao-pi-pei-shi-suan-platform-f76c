import json
from concurrent.futures import ThreadPoolExecutor

from app.main import create_app

ASSAYS = ('lot,expires,stock,unit,moisture_pct,gel_sag\n'
          'L-A,2026-12-10,5000,g,10,150\n'
          'L-B,2026-12-11,5000,g,10,160\n')


def material(calibration=None, dry_min=8900, gel_low=155, gel_high=156):
    body = {'assays': ASSAYS,
            'plan': {'as_of': '2026-11-22', 'target_g': 10000, 'step_g': 2500,
                     'dry_min_g': dry_min, 'gel_low_sag': gel_low, 'gel_high_sag': gel_high}}
    if calibration is not None:
        body['calibration'] = calibration
    return body


def shared(deviation=50):
    return [{'device': 'MA-1', 'measured_on': '2026-11-20',
             'low_bp': -deviation, 'high_bp': deviation, 'lots': ['L-A', 'L-B']}]


def split(deviation=50):
    return [{'device': 'MA-1', 'measured_on': '2026-11-20',
             'low_bp': -deviation, 'high_bp': deviation, 'lots': ['L-A']},
            {'device': 'MA-1', 'measured_on': '2026-11-21',
             'low_bp': -deviation, 'high_bp': deviation, 'lots': ['L-B']}]


def archive(client, body):
    return client.post('/api/batches', json=body).json['batch_id']


def test_shared_deviation_is_not_split(client):
    """同台同次共用一个偏差：两批同向偏移时凝胶恒为 155，配方可签发。
    若把同场误差拆成两批各自独立取值，反而会误判越线误扣工单。"""
    batch = archive(client, material(calibration=shared()))
    release = client.get('/api/certificate/' + batch).json['release']
    assert release['decision'] == 'ISSUABLE' and release['pending'] == []
    assert len(release['groups']) == 1 and release['groups'][0]['lots'] == ['L-A', 'L-B']


def test_split_sessions_vary_independently(client):
    """同一仪器不同场次各有偏差：角点可取 L-A 偏干、L-B 偏湿，凝胶跌破下限。"""
    batch = archive(client, material(calibration=split()))
    release = client.get('/api/certificate/' + batch).json['release']
    assert release['decision'] == 'AWAIT_REMEASURE'
    (finding,) = release['pending']
    assert finding['check'] == 'gel_low' and finding['gel_sag'] == '154.972'
    assert [(c['measured_on'], c['deviation_bp']) for c in finding['corner']] == [('2026-11-20', -50), ('2026-11-21', 50)]


def test_borderline_dry_awaits_remeasure(client):
    batch = archive(client, material(calibration=shared(), dry_min=8951))
    release = client.get('/api/certificate/' + batch).json['release']
    assert release['decision'] == 'AWAIT_REMEASURE'
    (finding,) = release['pending']
    assert finding['check'] == 'dry' and finding['dry_g'] == '8950.0000'
    assert finding['corner'] == [{'device': 'MA-1', 'measured_on': '2026-11-20', 'deviation_bp': 50}]


def test_sign_and_retry_never_duplicates(client):
    batch = archive(client, material(calibration=shared()))
    first = client.post('/api/certificate/' + batch, json={})
    assert first.status_code == 201 and first.json['created']
    certificate = first.json['certificate']
    assert certificate['issued'] and certificate['release']['decision'] == 'ISSUABLE'
    retry = client.post('/api/certificate/' + batch, json={})
    assert retry.status_code == 200 and not retry.json['created']
    assert retry.json['certificate']['certificate_id'] == certificate['certificate_id']
    assert client.get('/api/certificate/' + batch).json['issued'] is True


def test_late_calibration_reverifies_unsigned_record(client):
    """迟到的校准单适用于测量当日：未签发的留档单按新偏差重新验方并转待复测。"""
    batch = archive(client, material(dry_min=8951))
    assert client.get('/api/certificate/' + batch).json['release']['decision'] == 'ISSUABLE'
    reply = client.post('/api/certificate/' + batch, json={'calibration': shared()})
    assert reply.status_code == 409 and reply.json['code'] == 'AWAIT_REMEASURE'
    assert reply.json['created'] is False and reply.json['certificate'] is None
    assert [entry['device'] for entry in reply.json['applied']] == ['MA-1']
    current = client.get('/api/certificate/' + batch).json
    assert current['issued'] is False and current['release']['decision'] == 'AWAIT_REMEASURE'
    assert current['release']['pending'][0]['check'] == 'dry'


def test_issued_certificate_keeps_original_basis(client):
    """已签单保留原判依据：迟到校准不再改判，重试仍返回原签发件。"""
    batch = archive(client, material())
    issued = client.post('/api/certificate/' + batch, json={}).json['certificate']
    reply = client.post('/api/certificate/' + batch, json={'calibration': shared()})
    assert reply.status_code == 200 and not reply.json['created']
    assert reply.json['ignored'][0]['reason'] == 'ALREADY_ISSUED'
    kept = reply.json['certificate']
    assert kept['certificate_id'] == issued['certificate_id']
    assert kept['release']['decision'] == 'ISSUABLE' and kept['release']['basis'] == []
    assert client.get('/api/certificate/' + batch).json['release']['basis'] == []


def test_late_calibration_must_apply_to_measurement_day(client):
    batch = archive_client = archive(client, material())
    future = [{'device': 'MA-1', 'measured_on': '2026-11-25', 'low_bp': -50, 'high_bp': 50, 'lots': ['L-A', 'L-B']}]
    stranger = [{'device': 'MA-9', 'measured_on': '2026-11-20', 'low_bp': -50, 'high_bp': 50, 'lots': ['ZZ-9']}]
    reply = client.post('/api/certificate/' + batch, json={'calibration': future + stranger})
    assert reply.status_code == 201
    assert [row['reason'] for row in reply.json['ignored']] == ['AFTER_TRIAL_DAY', 'NO_ACCEPTED_LOT']
    assert client.get('/api/certificate/' + batch).json['release']['basis'] == []


def test_blocked_record_cannot_be_signed(client):
    batch = archive(client, material(gel_low=195, gel_high=200))
    pack = client.get('/api/certificate/' + batch).json
    assert not pack['can_trial'] and pack['release']['decision'] == 'BLOCKED'
    reply = client.post('/api/certificate/' + batch, json={})
    assert reply.status_code == 409 and reply.json['code'] == 'NOT_ISSUABLE'


def test_bad_calibration_rejected_before_archiving(client):
    inverted = [{'device': 'MA-1', 'measured_on': '2026-11-20', 'low_bp': 50, 'high_bp': -50, 'lots': ['L-A']}]
    overlap = shared()[:1] + [{'device': 'MB-2', 'measured_on': '2026-11-20', 'low_bp': 0, 'high_bp': 10, 'lots': ['L-B', 'L-A']}]
    for calibration in (inverted, overlap, [{'device': 'MA-1'}], 'not-a-list'):
        reply = client.post('/api/batches', json=material(calibration=calibration))
        assert reply.status_code == 422 and reply.json['code'] == 'BAD_CALIBRATION'
    assert client.get('/api/batches').json['batches'] == []


def test_concurrent_sign_freezes_single_certificate(tmp_path):
    app = create_app(tmp_path / 'archive')
    batch = app.test_client().post('/api/batches', json=material(calibration=shared())).json['batch_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: app.test_client().post('/api/certificate/' + batch, json={}), range(7)))
    assert sum(reply.json['created'] for reply in results) == 1
    assert len({reply.json['certificate']['certificate_id'] for reply in results}) == 1
    assert len(list((tmp_path / 'archive' / 'certificates').iterdir())) == 1


def test_certificate_page_shows_decision_and_pending(client):
    batch = archive(client, material(calibration=shared(), dry_min=8951))
    page = client.get('/trial/certificate', query_string={'batch': batch})
    for text in ('待复测', '干物下限', 'MA-1', '2026-11-20', '申请签发'):
        assert text.encode() in page.data
    signed = archive(client, material(calibration=shared()))
    client.post('/api/certificate/' + signed, json={})
    page = client.get('/trial/certificate', query_string={'batch': signed})
    assert '可签发'.encode() in page.data and '已签发'.encode() in page.data


def test_unknown_batch_sign_is_404(client):
    reply = client.post('/api/certificate/' + '0' * 64, json={})
    assert reply.status_code == 404 and reply.json['code'] == 'BATCH_NOT_FOUND'
