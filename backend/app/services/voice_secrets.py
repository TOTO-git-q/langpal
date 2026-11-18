"""Windows account-bound storage for speech API credentials."""
import base64
import os


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    if os.name != 'nt':
        raise ValueError('当前系统尚未配置语音密钥存储')
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.c_void_p)]

    storage = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.addressof(storage))
    target = Blob()
    operation = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    operation.argtypes = (ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('本机语音密钥存储不可用')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = (ctypes.c_void_p,)
        free.restype = ctypes.c_void_p
        free(target.data)


def seal(key: str) -> str:
    return 'dpapi:' + base64.b64encode(_dpapi(key.encode('utf-8'), True)).decode('ascii')


def open_secret(value: str) -> str:
    # Read legacy plaintext without rewriting user data during a settings preview.
    # The next explicit save seals the old key as well as newly entered keys.
    if not value.startswith('dpapi:'):
        return value
    try:
        return _dpapi(base64.b64decode(value[6:], validate=True), False).decode('utf-8')
    except Exception:
        raise ValueError('无法读取语音密钥，请重新填写') from None
