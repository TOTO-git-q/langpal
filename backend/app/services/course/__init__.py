"""Public course kernel surface for backend consumers."""
from .content import (
    Teaching, SETTINGS_PREFIX, presets, resolve, language_settings, save_language_settings,
    validate_profile, point_key,
)
from . import builder, content, generate, ledger, lesson, lessons, planner, state


def brief(conn, language, now):
    progress = planner.overview(conn, language, now)
    if not progress['active']:
        return ''
    prefix = '【他的课程】' + progress['course']['title'] + '：'
    running = lesson.current(conn, now)
    if running and not running['ended'] and running['language'] == language:
        return prefix + f'正在上《{running["title"]}》。'
    counts = progress['counts']
    line = prefix + f'学会 {counts["known"]}/{counts["points"]}'
    if progress['next']:
        line += f'，下一课是《{progress["next"]["title"]}》'
    return line + '。'
