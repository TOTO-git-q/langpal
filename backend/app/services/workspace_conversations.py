"""Durable local Agent conversations; canonical study documents hold attachment data."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
import json
import re
from uuid import uuid4
from threading import RLock

_active = set()
_lock = RLock()

from fastapi import HTTPException
from ..db import get_conn

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT_FILE = 1024 * 1024
MAX_TEXT = 60000
MAX_CONTEXT = 24000
_TYPES = {'.txt': 'text/plain', '.md': 'text/markdown', '.csv': 'text/csv', '.json': 'application/json', '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def now():
    return datetime.now(timezone.utc).isoformat()


def require_conversation(conn, conversation_id):
    row = conn.execute('SELECT * FROM workspace_conversations WHERE id=?', (conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Conversation not found')
    return dict(row)


def create_conversation(title='New conversation'):
    row = dict(id=str(uuid4()), title=title[:120], created_at=now(), updated_at=now())
    with closing(get_conn()) as conn, conn:
        conn.execute('INSERT INTO workspace_conversations VALUES (:id,:title,:created_at,:updated_at)', row)
    return row


def list_conversations():
    with closing(get_conn()) as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM workspace_conversations ORDER BY updated_at DESC,id LIMIT 100')]


def delete_conversation(conversation_id):
    with _lock, closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        require_conversation(conn, conversation_id)
        if any(cid == conversation_id for cid, _ in _active):
            raise HTTPException(409)
        documents = [row[0] for row in conn.execute('SELECT document_id FROM workspace_attachments WHERE conversation_id=?', (conversation_id,))]
        conn.execute('DELETE FROM workspace_attachment_images WHERE attachment_id IN (SELECT id FROM workspace_attachments WHERE conversation_id=?)', (conversation_id,))
        conn.execute('DELETE FROM workspace_attachments WHERE conversation_id=?', (conversation_id,))
        conn.execute('DELETE FROM workspace_messages WHERE conversation_id=?', (conversation_id,))
        conn.execute('DELETE FROM workspace_conversations WHERE id=?', (conversation_id,))
        for document_id in documents:
            if not conn.execute('SELECT 1 FROM workspace_attachments WHERE document_id=?', (document_id,)).fetchone():
                conn.execute('DELETE FROM study_annotations WHERE document_id=?', (document_id,))
                conn.execute('DELETE FROM study_documents WHERE id=?', (document_id,))
    return {'deleted': conversation_id}


def attachment_view(row):
    result = {key: row[key] for key in ('id', 'name', 'mime', 'size', 'provenance', 'text_chars', 'truncated', 'no_text', 'document_id')}
    for key in ('width', 'height'):
        if key in row.keys() and row[key] is not None: result[key] = row[key]
    return result


def detail(conversation_id):
    with _lock, closing(get_conn()) as conn, conn:
        recover_interrupted(conn, conversation_id)
        conversation = require_conversation(conn, conversation_id)
        messages = []
        for row in conn.execute('SELECT * FROM workspace_messages WHERE conversation_id=? ORDER BY rowid DESC LIMIT 200', (conversation_id,)):
            item = dict(row)
            item.pop('fingerprint')
            item['attachment_ids'] = json.loads(item.pop('attachment_ids_json'))
            result_json = item.pop('result_json')
            item['result'] = json.loads(result_json) if result_json else None
            messages.append(item)
        attachments = [attachment_view(row) for row in conn.execute('SELECT a.*,i.width,i.height FROM workspace_attachments a LEFT JOIN workspace_attachment_images i ON i.attachment_id=a.id WHERE a.conversation_id=? ORDER BY a.rowid', (conversation_id,))]
    return dict(conversation=conversation, messages=list(reversed(messages)), attachments=attachments)


def normalized_image(raw, mime):
    """Decode and re-encode, dropping metadata and rejecting animation/bombs."""
    formats = {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/webp': 'WEBP'}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != formats[mime] or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Image format mismatch or animation')
                if max(image.size) > 8192 or image.width * image.height > 16000000:
                    raise ValueError('Image dimensions exceed limits')
                image.load()
                image = ImageOps.exif_transpose(image)
                clean = Image.new('RGBA' if ('A' in image.getbands() or 'transparency' in image.info) and mime != 'image/jpeg' else 'RGB', image.size)
                clean.paste(image.convert(clean.mode))
                output = io.BytesIO()
                clean.save(output, format=formats[mime])
                data = output.getvalue()
                if len(data) > MAX_FILE: raise ValueError('Normalized image exceeds limit')
                return data, clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, KeyError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'Use a valid, non-animated PNG, JPEG, or WebP up to 8192 px / 16 MP') from None


def image_content(conversation_id, attachment_id):
    with closing(get_conn()) as conn:
        row = conn.execute('SELECT a.mime,i.data,i.sha256 FROM workspace_attachments a JOIN workspace_attachment_images i ON i.attachment_id=a.id WHERE a.conversation_id=? AND a.id=?', (conversation_id, attachment_id)).fetchone()
    if row is None: raise HTTPException(404, 'Image attachment not found in this conversation')
    if hashlib.sha256(row['data']).hexdigest() != row['sha256']:
        raise HTTPException(409, 'Image attachment integrity check failed')
    return row['data'], row['mime']


def upload(conversation_id, name, mime, raw, extracted_text='', extraction_truncated=False):
    if not isinstance(name, str) or not name or len(name) > 180 or name != name.strip() or re.search(r'[\\/:\x00-\x1f\x7f]', name) or name.startswith('.'):
        raise HTTPException(422, 'Invalid attachment filename')
    extension = '.' + name.rsplit('.', 1)[-1].lower()
    if extension not in _TYPES:
        raise HTTPException(422, 'Use TXT, MD, CSV, JSON, PDF, PNG, JPEG, or WebP')
    expected = _TYPES[extension]
    allowed = {expected, 'application/octet-stream', ''}
    if extension in ('.md', '.csv', '.json'): allowed.add('text/plain')
    if mime not in allowed:
        raise HTTPException(422, 'Attachment type does not match filename')
    if not raw or len(raw) > (MAX_FILE if extension == '.pdf' or expected.startswith('image/') else MAX_TEXT_FILE):
        raise HTTPException(413, 'Attachment is empty or exceeds size limit')
    if not isinstance(extracted_text, str) or len(extracted_text) > MAX_TEXT:
        raise HTTPException(413, 'Extracted text exceeds 60000 characters')
    image_data = None
    if expected.startswith('image/'):
        if extracted_text or extraction_truncated: raise HTTPException(422, 'Images do not accept extracted text')
        image_data, width, height = normalized_image(raw, expected)
        text, provenance, blob = '', 'server-image-validated', None
    elif extension == '.pdf':
        if not raw.startswith(b'%PDF-'): raise HTTPException(422, 'Invalid PDF signature')
        text, provenance, blob = extracted_text, 'browser-pdfjs-unverified', raw
    else:
        if extracted_text or extraction_truncated:
            raise HTTPException(422, 'Text files are decoded by the server')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeError:
            raise HTTPException(422, 'Text attachments must use UTF-8') from None
        if '\x00' in text: raise HTTPException(422, 'Binary content is not supported')
        if extension == '.json':
            try: json.loads(text)
            except (ValueError, RecursionError): raise HTTPException(422, 'Invalid JSON attachment') from None
        provenance, blob = 'server-utf8', None
    from . import workspace_agent as agent
    if agent._secret.search(text) or re.search(r'-----BEGIN .*PRIVATE KEY-----', text):
        raise HTTPException(422, 'Attachment appears to contain credentials; remove them before uploading')
    truncated = bool(extraction_truncated or len(text) > MAX_TEXT)
    text = text[:MAX_TEXT]
    attachment_id, document_id = str(uuid4()), 'agent-' + str(uuid4())
    metadata = dict(id=document_id, title=name, name=name, source='workspace-agent', text=text, type=extension[1:], attachment_sha256=hashlib.sha256(raw).hexdigest())
    if image_data is not None:
        metadata.update(width=width, height=height, normalized_sha256=hashlib.sha256(image_data).hexdigest())
    payload = encoded(metadata)
    row = dict(id=attachment_id, conversation_id=conversation_id, document_id=document_id, name=name, mime=expected, size=len(raw), provenance=provenance, text_chars=len(text), truncated=int(truncated), no_text=int(not text.strip() and image_data is None), document_digest=hashlib.sha256(payload.encode()).hexdigest(), created_at=now())
    with closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        require_conversation(conn, conversation_id)
        if conn.execute('SELECT COUNT(*) FROM workspace_attachments WHERE conversation_id=?', (conversation_id,)).fetchone()[0] >= 40:
            raise HTTPException(413, 'Conversation attachment limit reached')
        conn.execute('INSERT INTO study_documents VALUES (?,?,?,1)', (document_id, payload, blob))
        conn.execute('INSERT INTO workspace_attachments VALUES (:id,:conversation_id,:document_id,:name,:mime,:size,:provenance,:text_chars,:truncated,:no_text,:document_digest,:created_at)', row)
        if image_data is not None:
            conn.execute('INSERT INTO workspace_attachment_images VALUES (?,?,?,?,?)', (attachment_id, image_data, width, height, hashlib.sha256(image_data).hexdigest()))
            row.update(width=width, height=height)
    return attachment_view(row)


def recover_interrupted(conn, conversation_id):
    rows = conn.execute("SELECT request_id FROM workspace_messages WHERE conversation_id=? AND role='assistant' AND status='pending'", (conversation_id,)).fetchall()
    for row in rows:
        if (conversation_id, row['request_id']) not in _active:
            conn.execute("UPDATE workspace_messages SET status='failed',updated_at=? WHERE conversation_id=? AND request_id=?", (now(), conversation_id, row['request_id']))


def begin_turn(conversation_id, request_id, message, attachment_ids, preferences):
    fingerprint = hashlib.sha256(encoded([message, attachment_ids, preferences]).encode()).hexdigest()
    with _lock, closing(get_conn()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        require_conversation(conn, conversation_id)
        recover_interrupted(conn, conversation_id)
        existing = conn.execute("SELECT * FROM workspace_messages WHERE conversation_id=? AND request_id=? AND role='assistant'", (conversation_id, request_id)).fetchone()
        if existing:
            if existing['fingerprint'] != fingerprint: raise HTTPException(409, 'request_id already used for a different message')
            if existing['status'] == 'succeeded': return {'replay': json.loads(existing['result_json'])}
            raise HTTPException(409, 'Request is pending, failed, or was interrupted; use a new request_id to retry')
        if conn.execute("SELECT 1 FROM workspace_messages WHERE conversation_id=? AND status='pending' LIMIT 1", (conversation_id,)).fetchone():
            raise HTTPException(409, 'This conversation already has a pending message')
        contexts, budget = [], MAX_CONTEXT
        for attachment_id in attachment_ids:
            row = conn.execute('SELECT a.*,d.metadata_json,d.revision FROM workspace_attachments a JOIN study_documents d ON d.id=a.document_id WHERE a.id=? AND a.conversation_id=?', (attachment_id, conversation_id)).fetchone()
            if row is None: raise HTTPException(404, 'Attachment does not belong to this conversation')
            if row['revision'] != 1 or hashlib.sha256(row['metadata_json'].encode()).hexdigest() != row['document_digest']:
                raise HTTPException(409, 'Attached document changed; upload a new attachment')
            if row['mime'].startswith('image/'):
                image = conn.execute('SELECT * FROM workspace_attachment_images WHERE attachment_id=?', (attachment_id,)).fetchone()
                if image is None or hashlib.sha256(image['data']).hexdigest() != image['sha256']:
                    raise HTTPException(409, 'Image attachment integrity check failed')
                contexts.append(dict(id=row['id'], name=row['name'], kind='image', mime=row['mime'], image_data=image['data'], width=image['width'], height=image['height'], provenance=row['provenance'], truncated=False, no_text=False))
                continue
            text = json.loads(row['metadata_json']).get('text', '')
            excerpt = text[:min(budget, 12000)]
            budget -= len(excerpt)
            contexts.append(dict(id=row['id'], name=row['name'], text=excerpt, provenance=row['provenance'], truncated=bool(row['truncated'] or len(excerpt)<len(text)), no_text=bool(row['no_text'])))
        previous = []
        rows = conn.execute("SELECT u.content AS request,a.content AS reply FROM workspace_messages a JOIN workspace_messages u ON u.conversation_id=a.conversation_id AND u.request_id=a.request_id AND u.role='user' WHERE a.conversation_id=? AND a.role='assistant' AND a.status='succeeded' ORDER BY a.rowid DESC LIMIT 3", (conversation_id,)).fetchall()
        previous = [dict(row) for row in reversed(rows)]
        stamp = now()
        for role, content in [('user', message), ('assistant', '')]:
            conn.execute('INSERT INTO workspace_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)', (str(uuid4()), conversation_id, request_id, role, content, 'pending', encoded(attachment_ids), None, fingerprint, stamp, stamp))
        conn.execute('UPDATE workspace_conversations SET updated_at=? WHERE id=?', (stamp, conversation_id))
        conn.commit()
        _active.add((conversation_id, request_id))
    return dict(previous=previous, attachment_context=contexts)


def finish_turn(conversation_id, request_id, result):
    response = {**result, 'conversation_id': conversation_id, 'request_id': request_id}
    with closing(get_conn()) as conn, conn:
        conn.execute("UPDATE workspace_messages SET status='succeeded',content=?,result_json=?,updated_at=? WHERE conversation_id=? AND request_id=? AND role='assistant' AND status='pending'", (result.get('reply', ''), encoded(response), now(), conversation_id, request_id))
        conn.execute("UPDATE workspace_messages SET status='succeeded',updated_at=? WHERE conversation_id=? AND request_id=? AND role='user'", (now(), conversation_id, request_id))
    with _lock:
        _active.discard((conversation_id, request_id))
    return response


def fail_turn(conversation_id, request_id):
    # Never persist provider exceptions, which can contain credentials or URLs.
    with closing(get_conn()) as conn, conn:
        conn.execute("UPDATE workspace_messages SET status='failed',updated_at=? WHERE conversation_id=? AND request_id=? AND status='pending'", (now(), conversation_id, request_id))

    with _lock:
        _active.discard((conversation_id, request_id))
