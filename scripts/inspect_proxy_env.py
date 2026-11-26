"""Read only proxy variables from native x64 Windows processes; never dump full env.

Usage: python inspect_proxy_env.py PID [PID ...]
Uses version-dependent PEB offsets. Failure means unknown, not absent variables.
"""
import ctypes as C
import json
import struct
import sys
import winreg
from ctypes import wintypes as W
from urllib.parse import urlsplit

KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')
k = C.WinDLL('kernel32', use_last_error=True)
nt = C.WinDLL('ntdll')
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k.ReadProcessMemory.restype = W.BOOL
k.CloseHandle.argtypes = [W.HANDLE]
k.IsWow64Process.argtypes = [W.HANDLE, C.POINTER(W.BOOL)]
k.IsWow64Process.restype = W.BOOL
nt.NtQueryInformationProcess.argtypes = [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]


class PBI(C.Structure):
    _fields_ = [('reserved', C.c_void_p), ('peb', C.c_void_p),
                ('reserved2', C.c_void_p * 2), ('pid', C.c_size_t), ('reserved3', C.c_void_p)]


def masked(key, value):
    if key.upper() == 'NO_PROXY':
        return value
    try:
        u = urlsplit(value)
        if u.username is not None or u.password is not None:
            return f'{u.scheme}://<redacted>@{u.hostname}:{u.port}'
        return value
    except ValueError:
        return '<unparseable proxy>'


def inspect(pid):
    result = {'pid': pid}
    h = k.OpenProcess(0x410, False, pid)
    if not h:
        return dict(result, error=f'OpenProcess: {C.get_last_error()}')
    try:
        if C.sizeof(C.c_void_p) != 8:
            raise ValueError('requires 64-bit Python')
        wow = W.BOOL()
        if not k.IsWow64Process(h, C.byref(wow)) or wow.value:
            raise ValueError('requires native x64 target')
        p = PBI()
        status = nt.NtQueryInformationProcess(h, 0, C.byref(p), C.sizeof(p), None)
        if status:
            raise ValueError(f'NtQueryInformationProcess: {status}')

        def read(address, size):
            buf = C.create_string_buffer(size)
            done = C.c_size_t()
            if not k.ReadProcessMemory(h, address, buf, size, C.byref(done)) or done.value != size:
                raise OSError(C.get_last_error(), 'ReadProcessMemory failed')
            return buf.raw

        params = struct.unpack('<Q', read(p.peb + 0x20, 8))[0]
        env = struct.unpack('<Q', read(params + 0x80, 8))[0]
        size = struct.unpack('<Q', read(params + 0x3f0, 8))[0]
        if not 0 < size < 4 * 1024 * 1024:
            raise ValueError('unexpected environment size; offsets may be unsupported')
        values = {}
        for item in read(env, size).decode('utf-16-le').split('\0'):
            key, sep, value = item.partition('=')
            if sep and key.upper() in KEYS:
                values[key.upper()] = value
        expected = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as reg:
            for key in KEYS:
                try:
                    expected[key] = winreg.QueryValueEx(reg, key)[0]
                except FileNotFoundError:
                    pass
        result['proxy_environment'] = {key: masked(key, value) for key, value in values.items()}
        result['matches_user_registry'] = {
            key: bool(expected.get(key)) and values.get(key) == expected[key] for key in KEYS
        }
        return result
    except Exception as e:
        return dict(result, error=str(e))
    finally:
        k.CloseHandle(h)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python inspect_proxy_env.py PID [PID ...]')
    print(json.dumps([inspect(int(pid)) for pid in sys.argv[1:]], ensure_ascii=True, indent=2))
