"""Pure replay of lesson progress: each point needs one success."""
from .content import view
from .lessons import holders


def fold(events, outline, now):
    course = view(outline)
    points = {(unit.id, point.id): {'status': 'new'} for unit in course.units for point in unit.points}
    fingerprints = {(unit.id, point.id): point.key for unit in course.units for point in unit.points}
    for event in events:
        pair = event['unit_id'], event['point_id']
        if pair not in points or event['point_key'] != fingerprints[pair]:
            continue
        if event['result'] == 'success':
            points[pair]['status'] = 'known'
        elif event['result'] in ('miss', 'assisted') and points[pair]['status'] == 'new':
            points[pair]['status'] = 'learning'
    units = {}
    for unit in course.units:
        statuses = [points[unit.id, point.id]['status'] for point in unit.points]
        units[unit.id] = ('known' if statuses and all(status == 'known' for status in statuses)
                          else 'learning' if any(status != 'new' for status in statuses) else 'new')
    held = holders(outline)
    counted = [point for (unit_id, _), point in points.items() if unit_id not in held]
    return {'points': points, 'units': units,
            'counts': {'points': len(counted), 'known': sum(point['status'] == 'known' for point in counted)}}
