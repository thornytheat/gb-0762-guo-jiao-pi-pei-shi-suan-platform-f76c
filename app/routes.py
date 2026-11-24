from flask import Blueprint, current_app, jsonify, request

from .errors import TrialError
from .input import from_request
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate import service as certificate_service
from .modules.certificate.contract import entries as calibration_entries
from .pipeline import process

api = Blueprint('trial_api', __name__, url_prefix='/api')


def preview(stage):
    return process(from_request(), stage)[stage]


@api.post('/assay')
def assay():
    return preview('assay')


@api.post('/dry')
def dry():
    return preview('dry')


@api.post('/formula')
def formula():
    return preview('formula')


@api.post('/blend')
def blend():
    return preview('blend')


@api.post('/stock')
def stock():
    return preview('stock')


@api.post('/batches')
def batches():
    record, fresh = preserve(current_app.config['ARCHIVE'], from_request())
    return {'batch_id': record['batch_id'], 'created': fresh, 'record': record}, 201 if fresh else 200


@api.get('/batches')
def list_batches():
    return {'batches': history(current_app.config['ARCHIVE'])}


@api.get('/batches/<identifier>')
def batch(identifier):
    return read(current_app.config['ARCHIVE'], identifier)


@api.get('/certificate/<identifier>')
def certificate(identifier):
    return certificate_service.current(current_app.config['ARCHIVE'], identifier)


@api.post('/certificate/<identifier>')
def sign(identifier):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict) or set(body) - {'calibration'}:
        raise TrialError('UNKNOWN_REQUEST_FIELD', 400)
    result = certificate_service.sign(current_app.config['ARCHIVE'], identifier,
                                      calibration_entries(body.get('calibration')))
    outcome = result['outcome']
    payload = {'created': outcome == 'ISSUED', 'applied': result['applied'], 'ignored': result['ignored']}
    if outcome == 'HELD':
        decision = result['pack']['release']['decision']
        return {**payload, 'code': 'AWAIT_REMEASURE' if decision == 'AWAIT_REMEASURE' else 'NOT_ISSUABLE',
                'certificate': None, 'release': result['pack']['release']}, 409
    return {**payload, 'certificate': result['pack']}, 201 if outcome == 'ISSUED' else 200


@api.get('/export/<identifier>')
def export(identifier):
    response = jsonify(certificate(identifier))
    response.headers['Content-Disposition'] = f'attachment; filename="pectin-{identifier[:12]}.json"'
    return response
