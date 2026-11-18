"""Offline upload bounds and threadpool regression; no user database or API calls."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import HTTPException
from app.routers import chat

class FakeUpload:
    def __init__(self, data): self.data, self.read_sizes = data, []
    async def read(self, size=-1):
        self.read_sizes.append(size)
        return self.data if size < 0 else self.data[:size]

class ChatResourceTests(unittest.TestCase):
    def test_oversized_upload_is_bounded_and_not_written(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(chat, 'UPLOAD_DIR', Path(folder)), patch.object(chat, '_UPLOAD_MAX_BYTES', 16):
            upload = FakeUpload(b'x' * 100)
            with self.assertRaises(HTTPException) as error: asyncio.run(chat.upload_chat_image(upload))
            self.assertEqual(error.exception.status_code, 413)
            self.assertEqual(upload.read_sizes, [17])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_empty_invalid_and_valid_images(self):
        # PNG header sufficient for the project's existing magic/dimension contract.
        png = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (1).to_bytes(4,'big')*2 + b'\x08\x02\x00\x00\x00'
        with tempfile.TemporaryDirectory() as folder, patch.object(chat, 'UPLOAD_DIR', Path(folder)):
            for value, status in [(b'',400), (b'not an image',415)]:
                with self.assertRaises(HTTPException) as error: asyncio.run(chat.upload_chat_image(FakeUpload(value)))
                self.assertEqual(error.exception.status_code,status)
            with patch.object(chat, '_UPLOAD_MAX_BYTES', len(png)):
                result = asyncio.run(chat.upload_chat_image(FakeUpload(png)))
            self.assertEqual((result['width'], result['height']), (1,1))
            self.assertEqual((Path(folder)/Path(result['url']).name).read_bytes(),png)
            self.assertEqual(len(list(Path(folder).iterdir())),1)

if __name__ == '__main__': unittest.main()
