"""Course overview and next lesson from replayed progress."""
from . import content, ledger, lessons, state


def selected(conn, language):
    config = content.language_settings(conn, language)
    outline = content.resolve(config, language)
    return outline, config.mode == 'ambient' and outline is not None


def snapshot(conn, outline, now):
    folded = state.fold(ledger.read(conn, outline), outline, now)
    from . import lesson
    lesson.ensure(conn)
    attempted = conn.execute("""SELECT DISTINCT lesson_id FROM course_lessons WHERE language=? AND course_id=?
                               AND (json_extract(log_json, '$.sheet') IS NOT NULL
                                    OR json_extract(log_json, '$.result') IS NOT NULL)""",
                             (outline.language, outline.id))
    for row in attempted:
        if folded['units'].get(row[0]) == 'new':
            folded['units'][row[0]] = 'learning'
    return folded


def _next(outline, folded):
    held = lessons.holders(outline)
    for unit in content.view(outline).units:
        if unit.id in held:
            continue
        if folded['units'][unit.id] != 'known':
            return {'unit_id': unit.id, 'title': unit.title}
    return None


def next_lesson(conn, language, now):
    outline, active = selected(conn, language)
    return _next(outline, snapshot(conn, outline, now)) if active else None


def overview(conn, language, now):
    outline, active = selected(conn, language)
    result = {'active': active, 'course': {'id': outline.id, 'title': outline.title, 'language': outline.language}
              if outline else None, 'counts': dict(points=0, known=0),
              'units': [], 'next': None, 'lesson': None}
    from . import lesson
    running = lesson.current(conn, now)
    if running and not running['ended'] and running['language'] == language:
        result['lesson'] = {key: running[key] for key in ('id', 'lesson_id', 'title')}
    if outline is None:
        return result
    folded = snapshot(conn, outline, now)
    held = lessons.holders(outline)
    for unit in content.view(outline).units:
        if unit.id in held:
            continue
        result['units'].append({'id': unit.id, 'title': unit.title, 'can_do': unit.can_do,
                                'status': folded['units'][unit.id], 'points': [
                                    {'id': point.id, 'label': point.label,
                                     'status': folded['points'][unit.id, point.id]['status']}
                                    for point in unit.points]})
    if active:
        result.update(counts=folded['counts'], next=_next(outline, folded))
    return result
