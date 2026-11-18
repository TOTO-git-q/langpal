"""Bounded same-origin transport for the SQLite study workspace.

Bodies are read on the event loop; every database write and the ZIP restore run in
a worker thread so a large PDF or archive never blocks other requests.
"""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.datastructures import UploadFile
from ..security import same_origin
from ..services import study_storage as store

router = APIRouter(prefix='/study-storage', tags=['study-storage'], dependencies=[Depends(same_origin)])


async def bounded_body(request, limit):
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) < 0: raise ValueError()
            if int(length) > limit: raise HTTPException(413, 'Request exceeds storage limit')
        except ValueError:
            raise HTTPException(400, 'Invalid content length')
    result = bytearray()
    async for chunk in request.stream():
        if len(result) + len(chunk) > limit:
            raise HTTPException(413, 'Request exceeds storage limit')
        result.extend(chunk)
    return bytes(result)


async def body_json(request):
    try:
        body = json.loads(await bounded_body(request, store.MAX_JSON))
        if not isinstance(body, dict): raise ValueError()
        store.encode(body)
        if 'importOnly' in body and type(body['importOnly']) is not bool: raise ValueError()
        return body
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, 'Expected a JSON object')


@router.get('/capabilities')
def capabilities():
    return {'version': 1, 'writable': True}


@router.get('/documents')
def documents():
    return {'documents': store.list_documents()}


@router.get('/document')
def document(id: str):
    return store.get_document(id)


@router.get('/document/file')
def document_file(id: str):
    return Response(store.get_file(id), media_type='application/pdf', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/document')
async def save_document(request: Request):
    # Bound the entire body BEFORE Starlette parses or spools multipart files.
    request._body = await bounded_body(request, store.MAX_PDF + store.MAX_JSON + 65536)
    async with request.form(max_files=1, max_fields=3, max_part_size=store.MAX_JSON) as form:
        try:
            metadata = json.loads(form.get('metadata', ''))
            expected = int(form.get('revision', '0'))
            flag = form.get('importOnly', 'false')
            if flag not in ('true', 'false'): raise ValueError()
            file = form.get('file')
            if file is not None and not isinstance(file, UploadFile): raise ValueError()
            blob = await file.read(store.MAX_PDF+1) if file else None
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422, 'Invalid document multipart fields')
    return await asyncio.to_thread(store.save_document, metadata, blob, expected, flag == 'true')


@router.delete('/document')
def delete_document(id: str, revision: int):
    """Delete an imported document, its PDF and all of its annotations."""
    return store.delete_document(id, revision)


@router.get('/annotations')
def annotations(documentId: str):
    return {'annotations': store.list_annotations(documentId)}


@router.put('/annotation')
async def save_annotation(request: Request):
    body = await body_json(request)
    return await asyncio.to_thread(store.save_annotation, body.get('documentId'), body.get('annotation'),
                                   body.get('revision', 0), body.get('importOnly', False))


@router.delete('/annotation')
def delete_annotation(documentId: str, id: str, revision: int):
    return store.delete_annotation(documentId, id, revision)


@router.get('/listening-notes')
def listening_notes():
    return store.get_state('listening-notes', 'global')


@router.put('/listening-notes')
async def save_listening_notes(request: Request):
    body = await body_json(request)
    return await asyncio.to_thread(store.save_state, 'listening-notes', 'global', body.get('text'),
                                   body.get('revision', 0), body.get('importOnly', False))


@router.get('/listening-draft')
def listening_draft(id: str):
    return store.get_state('listening-draft', id)


@router.put('/listening-draft')
async def save_listening_draft(request: Request):
    body = await body_json(request)
    return await asyncio.to_thread(store.save_state, 'listening-draft', body.get('id'), body.get('draft'),
                                   body.get('revision', 0), body.get('importOnly', False))


@router.delete('/listening-draft')
def delete_listening_draft(id: str):
    return store.delete_state('listening-draft', id)


@router.get('/export')
def export():
    return Response(store.export_archive(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="langpal-study.zip"', 'Cache-Control': 'no-store'})


@router.post('/restore')
async def restore(request: Request):
    return await asyncio.to_thread(store.restore_archive, await bounded_body(request, store.MAX_ARCHIVE))
