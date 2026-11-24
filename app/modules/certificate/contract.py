from app.errors import TrialError
from app.modules.assay.units import day

FIELDS = {'device', 'measured_on', 'low_bp', 'high_bp', 'lots'}
MAX_ENTRIES = 16
MAX_BP = 9999


def _deviation(value):
    if type(value) is int:
        amount = value
    elif isinstance(value, str):
        try:
            amount = int(value.strip())
        except ValueError:
            raise TrialError('BAD_CALIBRATION') from None
    else:
        raise TrialError('BAD_CALIBRATION')
    if abs(amount) > MAX_BP:
        raise TrialError('BAD_CALIBRATION')
    return amount


def entries(raw):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ENTRIES:
        raise TrialError('BAD_CALIBRATION')
    normalized, sessions, assigned = [], set(), set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise TrialError('BAD_CALIBRATION')
        device = item['device']
        if not isinstance(device, str) or not device.strip():
            raise TrialError('BAD_CALIBRATION')
        device = device.strip()
        try:
            measured_on = day(item['measured_on'])
        except ValueError:
            raise TrialError('BAD_CALIBRATION') from None
        low, high = _deviation(item['low_bp']), _deviation(item['high_bp'])
        lots = item['lots']
        if low > high or not isinstance(lots, list) or not lots:
            raise TrialError('BAD_CALIBRATION')
        if any(not isinstance(lot, str) or not lot.strip() for lot in lots):
            raise TrialError('BAD_CALIBRATION')
        lots = sorted({lot.strip() for lot in lots})
        if (device, measured_on) in sessions or assigned & set(lots):
            raise TrialError('BAD_CALIBRATION')
        sessions.add((device, measured_on))
        assigned |= set(lots)
        normalized.append({'device': device, 'measured_on': measured_on,
                           'low_bp': low, 'high_bp': high, 'lots': lots})
    return normalized
