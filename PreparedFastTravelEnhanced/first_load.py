"""Enable the file lookup optimization on the verified Enhanced executable."""

from ctypes import WinDLL, c_uint64, create_unicode_buffer, wintypes
from hashlib import file_digest, sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from zipfile import BadZipFile, ZipFile

from unrealsdk import logging


GAME_HASH = '57c5dc7b2636097a8aa9bd63749be91062941926bc04935310972cda02a9ef56'
DLL_NAME = 'first_load.dll'
library = None
installed = False


def executable():
    get_name = WinDLL('kernel32', use_last_error=True).GetModuleFileNameW
    get_name.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    get_name.restype = wintypes.DWORD
    path = create_unicode_buffer(32768)
    length = get_name(None, path, len(path))
    return Path(path.value) if 0 < length < len(path) else None


def binary_payload():
    module = Path(__file__)
    archive = next((parent for parent in module.parents if parent.suffix.lower() == '.sdkmod'), None)
    if archive is None:
        return module.with_name(DLL_NAME).read_bytes()
    with ZipFile(archive) as package:
        return package.read(f'{module.parent.name}/{DLL_NAME}')


def native_path():
    binary = binary_payload()
    directory = Path(gettempdir()) / 'FasterFastTravelEnhanced'
    directory.mkdir(exist_ok=True)
    target = directory / f'first-load-{sha256(binary).hexdigest()}.dll'
    if target.is_file() and target.read_bytes() == binary:
        return target
    with NamedTemporaryFile(dir=directory, delete=False) as draft:
        draft.write(binary)
    staging = Path(draft.name)
    try:
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)
    return target


def install():
    global library, installed
    if installed:
        return
    try:
        if library is None:
            game = executable()
            if game is None:
                return
            with game.open('rb') as program:
                if file_digest(program, 'sha256').hexdigest() != GAME_HASH:
                    return
            library = WinDLL(str(native_path()), winmode=0x00000800)
            library.first_load_install.argtypes = ()
            library.first_load_install.restype = wintypes.BOOL
            library.first_load_begin.argtypes = ()
            library.first_load_begin.restype = None
            library.first_load_end.argtypes = ()
            library.first_load_end.restype = c_uint64
            library.first_load_remove.argtypes = ()
            library.first_load_remove.restype = None
        installed = bool(library.first_load_install())
    except (OSError, AttributeError, BadZipFile, KeyError) as error:
        library = None
        logging.warning(f'Faster Fast Travel could not initialize its file lookup optimization. {error}')


def begin():
    if installed:
        library.first_load_begin()


def end():
    if installed:
        library.first_load_end()


def remove():
    global installed
    if installed:
        library.first_load_remove()
        installed = False
