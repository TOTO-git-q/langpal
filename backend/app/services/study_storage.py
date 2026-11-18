"""Canonical SQLite study workspace. Every write is a compare-and-swap transaction.

Legacy import and restore insert missing records only. A deleted annotation stays as
a tombstone so an older archive or browser import cannot bring it back; deleting a
whole document removes it and its annotations outright. No filesystem paths are accepted.
"""
from contextlib import closing
import hashlib
import io
import json
import math
import zipfile

from fastapi import HTTPException
from ..db import get_conn

MAX_JSON = 2 * 1024 * 1024
MAX_PDF = 35 * 1024 * 1024
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_RECORDS = 10000


def fail(message, code=422):
    raise HTTPException(code, message)


def ident(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or '\x00' in value:
        fail('Invalid study record ID')
    return value


def encode(value, limit=MAX_JSON):
    try:
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True)
        if len(result.encode('utf-8')) > limit:
            fail('Study record is too large', 413)
        return result
    except (TypeError, ValueError, RecursionError, UnicodeError):
        fail('Invalid JSON record')


def revision(value):
    if type(value) is not int or value < 0:
        fail('revision must be a nonnegative integer')
    return value


def document_data(metadata, file=None):
    if not isinstance(metadata, dict):
        fail('Document metadata must be an object')
    ident(metadata.get('id'))
    if file is not None and (len(file) > MAX_PDF or not file.startswith(b'%PDF-')):
        fail('A PDF up to 35 MiB is required', 413 if len(file) > MAX_PDF else 422)
    return encode(metadata)


def note_data(note):
    if not isinstance(note, dict):
        fail('Annotation must be an object')
    note = {k: v for k, v in note.items() if k not in ('revision', 'imported', 'conflict', 'deleted')}
    ident(note.get('id'))
    if not isinstance(note.get('text', ''), str) or len(note.get('text', '')) > 20000:
        fail('Annotation text must be at most 20000 characters')
    if 'page' in note and (type(note['page']) is not int or note['page'] < 1):
        fail('Invalid annotation page')
    return encode(note, 128 * 1024)


def state_data(kind, value):
    if kind == 'listening-notes':
        if not isinstance(value, str) or len(value) > 20000:
            fail('Listening notes must be at most 20000 characters')
    elif kind == 'listening-draft':
        if not isinstance(value, dict):
            fail('Draft must be an object')
        if type(value.get('phase', 0)) is not int or not 0 <= value.get('phase', 0) <= 4:
            fail('Draft phase must be 0 through 4')
        time = value.get('time', 0)
        if type(time) not in (int, float) or not math.isfinite(time) or time < 0:
            fail('Invalid draft time')
        if not isinstance(value.get('answers', []), (list, dict)):
            fail('Invalid draft answers')
    else:
        fail('Invalid study state kind')
    return encode(value, 128 * 1024)


def doc_result(row):
    return dict(metadata=json.loads(row['metadata_json']), revision=row['revision'], hasFile=bool(row['has_file']))


def get_document(id):
    ident(id)
    with closing(get_conn()) as conn:
        row = conn.execute('SELECT metadata_json,revision,file IS NOT NULL AS has_file FROM study_documents WHERE id=?', (id,)).fetchone()
    if row is None:
        fail('Document not found', 404)
    return doc_result(row)


def list_documents():
    with closing(get_conn()) as conn:
        return [doc_result(row) for row in conn.execute('SELECT metadata_json,revision,file IS NOT NULL AS has_file FROM study_documents ORDER BY rowid DESC')]


def get_file(id):
    ident(id)
    with closing(get_conn()) as conn:
        row = conn.execute('SELECT file FROM study_documents WHERE id=?', (id,)).fetchone()
    if row is None or row['file'] is None:
        fail('PDF not found', 404)
    return row['file']


def save_document(metadata, file=None, expected=0, import_only=False):
    payload = document_data(metadata, file)
    revision(expected)
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT *,file IS NOT NULL AS has_file FROM study_documents WHERE id=?', (metadata['id'],)).fetchone()
        if row is not None and import_only:
            return {**doc_result(row), 'imported': False, 'conflict': payload != row['metadata_json'] or (file is not None and file != row['file'])}
        if expected != (row['revision'] if row else 0):
            fail('Document changed in another window; reload before saving', 409)
        new_revision = expected + 1
        if row is None:
            conn.execute('INSERT INTO study_documents VALUES (?,?,?,?)', (metadata['id'], payload, file, new_revision))
        else:
            conn.execute('UPDATE study_documents SET metadata_json=?,file=COALESCE(?,file),revision=? WHERE id=?', (payload, file, new_revision, metadata['id']))
        return dict(metadata=metadata, revision=new_revision, hasFile=file is not None or bool(row and row['has_file']), imported=bool(import_only), conflict=False)


def delete_document(id, expected):
    """Hard-delete a document, its PDF and every annotation row (tombstones included).

    A document still attached to an Agent conversation is refused rather than orphaned.
    Restoring an older archive afterwards would bring the document back; that is an
    explicit user action, so it is allowed.
    """
    ident(id); revision(expected)
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision FROM study_documents WHERE id=?', (id,)).fetchone()
        if row is None:
            fail('Document not found', 404)
        if expected != row['revision']:
            fail('Document changed in another window; reload before deleting', 409)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_attachments'").fetchone() and \
                conn.execute('SELECT 1 FROM workspace_attachments WHERE document_id=? LIMIT 1', (id,)).fetchone():
            fail('这份资料还附在助手对话里，请先删除那段对话', 409)
        notes = conn.execute('DELETE FROM study_annotations WHERE document_id=?', (id,)).rowcount
        conn.execute('DELETE FROM study_documents WHERE id=?', (id,))
        return {'id': id, 'deleted': True, 'annotations': notes}


def annotation_result(row):
    return {**json.loads(row['payload_json']), 'revision': row['revision'], **({'deleted': True} if row['deleted'] else {})}


def list_annotations(document_id):
    ident(document_id)
    with closing(get_conn()) as conn:
        return [annotation_result(row) for row in conn.execute('SELECT * FROM study_annotations WHERE document_id=? AND deleted=0 ORDER BY rowid', (document_id,))]


def save_annotation(document_id, note, expected=0, import_only=False):
    ident(document_id)
    payload = note_data(note)
    revision(expected)
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM study_documents WHERE id=?', (document_id,)).fetchone() is None:
            fail('Document not found', 404)
        row = conn.execute('SELECT * FROM study_annotations WHERE document_id=? AND id=?', (document_id, note['id'])).fetchone()
        if row is not None and import_only:
            return {**annotation_result(row), 'imported': False, 'conflict': bool(row['deleted']) or payload != row['payload_json']}
        if expected != (row['revision'] if row else 0):
            fail('Annotation changed in another window; reload before saving', 409)
        conn.execute('INSERT INTO study_annotations VALUES (?,?,?,?,0) ON CONFLICT(document_id,id) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision,deleted=0', (document_id, note['id'], payload, expected+1))
        return {**json.loads(payload), 'revision': expected+1, 'imported': bool(import_only), 'conflict': False}


def delete_annotation(document_id, id, expected):
    ident(document_id); ident(id); revision(expected)
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision FROM study_annotations WHERE document_id=? AND id=?', (document_id, id)).fetchone()
        if row is None:
            fail('Annotation not found', 404)
        if expected != row['revision']:
            fail('Annotation changed in another window; reload before deleting', 409)
        conn.execute('UPDATE study_annotations SET deleted=1,revision=revision+1 WHERE document_id=? AND id=?', (document_id, id))
        return {'id': id, 'deleted': True, 'revision': expected+1}


def state_result(kind, id, payload, rev):
    return {'text': payload, 'revision': rev} if kind == 'listening-notes' else {'id': id, 'draft': payload, 'revision': rev}


def get_state(kind, id):
    ident(id)
    with closing(get_conn()) as conn:
        row = conn.execute('SELECT * FROM study_state WHERE kind=? AND id=?', (kind, id)).fetchone()
    return state_result(kind, id, json.loads(row['payload_json']) if row else ('' if kind == 'listening-notes' else None), row['revision'] if row else 0)


def save_state(kind, id, value, expected=0, import_only=False):
    ident(id); revision(expected)
    payload = state_data(kind, value)
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM study_state WHERE kind=? AND id=?', (kind, id)).fetchone()
        if row is not None and import_only:
            return {**state_result(kind, id, json.loads(row['payload_json']), row['revision']), 'imported': False, 'conflict': payload != row['payload_json']}
        if expected != (row['revision'] if row else 0):
            fail('Notes changed in another window; reload before saving', 409)
        conn.execute('INSERT INTO study_state VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision', (kind, id, payload, expected+1))
        return {**state_result(kind, id, value, expected+1), 'imported': bool(import_only), 'conflict': False}


def delete_state(kind, id):
    ident(id)
    with closing(get_conn()) as conn, conn:
        removed = conn.execute('DELETE FROM study_state WHERE kind=? AND id=?', (kind, id)).rowcount
    if not removed:
        fail('Draft not found', 404)
    return {'id': id, 'deleted': True}


def export_archive():
    manifest = {'format': 'langpal-study', 'version': 1, 'documents': [], 'annotations': [], 'state': []}
    files = {}
    total = 0
    with closing(get_conn()) as conn:
        conn.execute('BEGIN')
        for row in conn.execute('SELECT * FROM study_documents'):
            data = dict(row)
            blob = data.pop('file')
            if blob is not None:
                digest = hashlib.sha256(blob).hexdigest()
                name = 'pdf/' + digest + '.pdf'
                data['file'] = {'name': name, 'sha256': digest}
                if name not in files:
                    total += len(blob)
                    if total > MAX_ARCHIVE:
                        fail('Study archive exceeds 128 MiB limit', 413)
                    files[name] = blob
            manifest['documents'].append(data)
        manifest['annotations'] = [dict(row) for row in conn.execute('SELECT * FROM study_annotations')]
        manifest['state'] = [dict(row) for row in conn.execute('SELECT * FROM study_state')]
    if sum(len(manifest[key]) for key in ('documents', 'annotations', 'state')) > MAX_RECORDS:
        fail('Study archive exceeds record limit', 413)
    raw = encode(manifest, MAX_ARCHIVE).encode('utf-8')
    if total + len(raw) > MAX_ARCHIVE:
        fail('Study archive exceeds 128 MiB limit', 413)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', raw)
        for name, blob in files.items():
            archive.writestr(name, blob)
    result = output.getvalue()
    if len(result) > MAX_ARCHIVE:
        fail('Study archive exceeds 128 MiB limit', 413)
    return result


def restore_archive(raw):
    """Validate fully before one transaction. Never extract paths or replace records."""
    if len(raw) > MAX_ARCHIVE:
        fail('Archive exceeds 128 MiB limit', 413)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) > MAX_RECORDS+1 or len(set(names)) != len(names) or sum(e.file_size for e in entries) > MAX_ARCHIVE:
                fail('Archive exceeds limits or has duplicate members', 413)
            if 'manifest.json' not in names:
                fail('Archive manifest missing')
            manifest = json.loads(archive.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != 'langpal-study' or manifest.get('version') != 1:
                fail('Unsupported study archive')
            if any(not isinstance(manifest.get(k), list) for k in ('documents', 'annotations', 'state')):
                fail('Invalid archive records')
            if sum(len(manifest[k]) for k in ('documents', 'annotations', 'state')) > MAX_RECORDS:
                fail('Archive record limit exceeded', 413)
            allowed = {'manifest.json'}
            documents, annotations, states = [], [], []
            keys = set()
            for item in manifest['documents']:
                metadata = json.loads(item['metadata_json'])
                if item['id'] != metadata['id']:
                    fail('Document ID mismatch')
                blob = None
                if item.get('file'):
                    digest = item['file']['sha256']
                    name = 'pdf/' + digest + '.pdf'
                    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or item['file']['name'] != name:
                        fail('Invalid PDF archive name')
                    allowed.add(name)
                    if archive.getinfo(name).file_size > MAX_PDF:
                        fail('PDF exceeds 35 MiB limit', 413)
                    blob = archive.read(name)
                    if hashlib.sha256(blob).hexdigest() != digest:
                        fail('PDF checksum mismatch')
                payload = document_data(metadata, blob)
                key = ('doc', item['id'])
                if key in keys: fail('Duplicate document ID')
                keys.add(key)
                documents.append((item['id'], payload, blob))
            for item in manifest['annotations']:
                ident(item['document_id']); ident(item['id'])
                note = json.loads(item['payload_json'])
                payload = note_data(note)
                if note['id'] != item['id'] or type(item['deleted']) is not int or item['deleted'] not in (0, 1):
                    fail('Invalid annotation identity or tombstone')
                key = ('note', item['document_id'], item['id'])
                if key in keys: fail('Duplicate annotation ID')
                keys.add(key)
                annotations.append((item['document_id'], item['id'], payload, item['deleted']))
            for item in manifest['state']:
                ident(item['id'])
                if item['kind'] == 'listening-notes' and item['id'] != 'global':
                    fail('Invalid listening note key')
                payload = state_data(item['kind'], json.loads(item['payload_json']))
                key = ('state', item['kind'], item['id'])
                if key in keys: fail('Duplicate state ID')
                keys.add(key)
                states.append((item['kind'], item['id'], payload))
            if set(names) != allowed:
                fail('Unexpected archive member')
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError, RuntimeError, RecursionError, NotImplementedError):
        fail('Invalid study archive')
    counts = {'imported': 0, 'skipped': 0, 'conflicts': 0}
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        for id, payload, blob in documents:
            row = conn.execute('SELECT metadata_json,file FROM study_documents WHERE id=?', (id,)).fetchone()
            if row is None:
                conn.execute('INSERT INTO study_documents VALUES (?,?,?,1)', (id, payload, blob)); counts['imported'] += 1
            else:
                counts['skipped'] += 1; counts['conflicts'] += int(row['metadata_json'] != payload or row['file'] != blob)
        for doc, id, payload, deleted in annotations:
            if conn.execute('SELECT 1 FROM study_documents WHERE id=?', (doc,)).fetchone() is None:
                fail('Archive annotation has no document')
            row = conn.execute('SELECT payload_json,deleted FROM study_annotations WHERE document_id=? AND id=?', (doc, id)).fetchone()
            if row is None:
                conn.execute('INSERT INTO study_annotations VALUES (?,?,?,1,?)', (doc, id, payload, deleted)); counts['imported'] += 1
            else:
                counts['skipped'] += 1; counts['conflicts'] += int(row['payload_json'] != payload or row['deleted'] != deleted)
        for kind, id, payload in states:
            row = conn.execute('SELECT payload_json FROM study_state WHERE kind=? AND id=?', (kind, id)).fetchone()
            if row is None:
                conn.execute('INSERT INTO study_state VALUES (?,?,?,1)', (kind, id, payload)); counts['imported'] += 1
            else:
                counts['skipped'] += 1; counts['conflicts'] += int(row['payload_json'] != payload)
    return counts
