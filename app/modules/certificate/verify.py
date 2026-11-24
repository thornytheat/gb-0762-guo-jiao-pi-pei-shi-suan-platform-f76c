from app.modules.dry.weights import SCALE, as_grams, sag_display

CHECKS = ('dry', 'gel_low', 'gel_high')


def _worst(check, plan, dry0, moment0, groups):
    """每项检查都是各组共享偏差 δ 的线性函数，最劣角点按组独立取端点。

    同台同次的批次共用一个 δ（组内只取一个端点，绝不拆开），异台异场的 δ 各自独立。
    返回 (余量, 角点)；余量 < 0 表示该检查在偏差范围内可能越线。
    """
    corner = []
    if check == 'dry':
        margin = dry0 - plan['dry_min_u']
        for group in groups:
            deviation = group['high_bp']
            margin -= deviation * group['weight_g']
            corner.append((group, deviation))
    elif check == 'gel_low':
        margin = moment0 - dry0 * plan['gel_low_sag']
        for group in groups:
            coefficient = group['moment_gmsag'] - group['weight_g'] * plan['gel_low_sag']
            deviation = group['high_bp'] if coefficient > 0 else group['low_bp']
            margin -= deviation * coefficient
            corner.append((group, deviation))
    else:
        margin = dry0 * plan['gel_high_sag'] - moment0
        for group in groups:
            coefficient = group['weight_g'] * plan['gel_high_sag'] - group['moment_gmsag']
            deviation = group['high_bp'] if coefficient > 0 else group['low_bp']
            margin -= deviation * coefficient
            corner.append((group, deviation))
    return margin, corner


def _finding(check, corner, dry0, moment0):
    dry = dry0 - sum(deviation * group['weight_g'] for group, deviation in corner)
    moment = moment0 - sum(deviation * group['moment_gmsag'] for group, deviation in corner)
    return {'check': check, 'dry_g': as_grams(dry), 'gel_sag': sag_display(moment, dry),
            'corner': [{'device': group['device'], 'measured_on': group['measured_on'], 'deviation_bp': deviation}
                       for group, deviation in corner if group['low_bp'] != group['high_bp']]}


def release(plan, allocation, lots, calibration):
    items = {lot: (grams, lots[lot]['moisture_bp'], lots[lot]['gel_msag']) for lot, grams in allocation.items()}
    dry0 = sum(grams * (SCALE - moisture) for grams, moisture, _ in items.values())
    moment0 = sum(grams * (SCALE - moisture) * gel for grams, moisture, gel in items.values())
    groups = []
    for entry in calibration:
        members = [lot for lot in entry['lots'] if lot in allocation]
        if not members:
            continue
        groups.append({'device': entry['device'], 'measured_on': entry['measured_on'],
                       'low_bp': entry['low_bp'], 'high_bp': entry['high_bp'], 'lots': members,
                       'weight_g': sum(items[lot][0] for lot in members),
                       'moment_gmsag': sum(items[lot][0] * items[lot][2] for lot in members)})
    pending = []
    for check in CHECKS:
        margin, corner = _worst(check, plan, dry0, moment0, groups)
        if margin < 0:
            pending.append(_finding(check, corner, dry0, moment0))
    return {'decision': 'AWAIT_REMEASURE' if pending else 'ISSUABLE', 'pending': pending,
            'groups': [{key: group[key] for key in ('device', 'measured_on', 'low_bp', 'high_bp', 'lots')}
                       for group in groups]}
