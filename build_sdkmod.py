"""Compile the Windows x64 helper and assemble the Willow1 SDK package."""

from argparse import ArgumentParser
from hashlib import file_digest
from pathlib import Path
from subprocess import check_output, run
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
MOD = 'PreparedFastTravelEnhanced'
FILES = ('__init__.py', 'area_exit.py', 'asset_cache.py', 'first_load.py', 'pyproject.toml', 'README.md')


def build(compiler):
    target = check_output([compiler, '-dumpmachine'], text=True).strip()
    if target != 'x86_64-w64-mingw32':
        raise SystemExit(f'Expected a Windows x64 MinGW-w64 GCC compiler. Found {target}.')

    output_dir = ROOT / 'dist'
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f'{MOD}.sdkmod'
    with TemporaryDirectory(dir=output_dir) as staging_dir:
        staging = Path(staging_dir)
        native = staging / 'first_load.dll'
        run([compiler, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O3', '-s', '-shared',
             '-o', str(native), str(ROOT / 'native' / 'first_load.c')], check=True)

        draft = staging / output.name
        with ZipFile(draft, 'w', ZIP_DEFLATED) as archive:
            for name in FILES:
                archive.write(ROOT / MOD / name, f'{MOD}/{name}')
            archive.write(native, f'{MOD}/{native.name}')
        with ZipFile(draft) as archive:
            corrupt = archive.testzip()
            if corrupt is not None:
                raise RuntimeError(f'Invalid archive entry {corrupt}')
        draft.replace(output)
    return output


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc', help='Windows x64 MinGW-w64 GCC executable')
    output = build(parser.parse_args().cc)
    with output.open('rb') as package:
        digest = file_digest(package, 'sha256').hexdigest()
    print(output)
    print(f'SHA-256 {digest}')


if __name__ == '__main__':
    main()
