#!/usr/bin/env python3
"""Create and build independent Passport firmware workspaces."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'FoloToy-AI-Passport-full.bin'


def workspace(name, root=ROOT):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', name):
        raise ValueError('Workspace name must be a lowercase slug (1–48 characters)')
    path = root / 'firmwares' / name
    if path.is_symlink():
        raise ValueError('Workspace directory must not be a symlink')
    return path


def metadata(name, root=ROOT):
    path = workspace(name, root)
    data = json.loads((path / 'firmware.json').read_text())
    if data.get('id') != name or data.get('board') != 'ai-passport' or data.get('kind') not in ('codex', 'blank'):
        raise ValueError('Invalid firmware workspace manifest')
    return path, data


def create(name, root=ROOT):
    path = workspace(name, root)
    if path.exists():
        raise ValueError(f'Workspace already exists: {name}')
    path.parent.mkdir(exist_ok=True)
    shutil.copytree(root / 'templates/firmware-blank', path)
    # ESP-IDF bootloader enumerates the project's bootloader_components directory.
    (path / 'bootloader_components').symlink_to('../../shared/boards/ai-passport/bootloader_components', target_is_directory=True)
    for filename in ('sdkconfig.defaults', 'partitions.csv'):
        shutil.copy2(root / 'shared/boards/ai-passport' / filename, path / filename)
    (path / 'firmware.json').write_text(json.dumps(dict(id=name, board='ai-passport', kind='blank'), indent=2)+'\n')
    (path / 'main/firmware_identity.h').write_text(f'#pragma once\n#define FIRMWARE_ID "{name}"\n')
    return path


def verified_image(name, root=ROOT):
    path, _ = metadata(name, root)
    image = path / 'build' / IMAGE
    receipt = json.loads((path / 'build/validated.json').read_text())
    if receipt.get('workspace') != name or receipt.get('sha256') != hashlib.sha256(image.read_bytes()).hexdigest():
        raise ValueError('Image does not match validation receipt; rebuild this workspace')
    return image


def build(name):
    path, data = metadata(name)
    output = path / 'build'
    output.mkdir(exist_ok=True)
    (output / 'validated.json').unlink(missing_ok=True)
    if data['kind'] == 'codex':
        command = 'source "$1"; cd "$2"; ./tools/validate.sh'
        subprocess.run(['/bin/bash', '-e', '-c', command, '--', str(ROOT/'scripts/env.sh'), str(path)], check=True)
    else:
        with tempfile.TemporaryDirectory(prefix='passport-firmware-') as tmp:
            command = '''source "$1"
cd "$2"
idf.py -B "$3" -D "SDKCONFIG=$3/sdkconfig" -D "SDKCONFIG_DEFAULTS=$2/sdkconfig.defaults" build
idf.py -B "$3" merge-bin -o "$3/FoloToy-AI-Passport-full.bin"
python3 "$4" "$3"
'''
            subprocess.run(['/bin/bash','-e','-c',command,'--',str(ROOT/'scripts/env.sh'),str(path),tmp,str(ROOT/'shared/boards/ai-passport/tools/verify_firmware.py')],check=True)
            shutil.copy2(Path(tmp)/IMAGE, output/IMAGE)
    receipt = dict(workspace=name, sha256=hashlib.sha256((output/IMAGE).read_bytes()).hexdigest())
    (output/'validated.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(f'Validated: {output/IMAGE}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    for command in ('new','build'):
        sub.add_parser(command).add_argument('name')
    args=parser.parse_args()
    try:
        if args.command=='list':
            for p in sorted((ROOT/'firmwares').glob('*/firmware.json')):
                _,data=metadata(p.parent.name)
                print(f"{data['id']}\t{data['kind']}\t{data['board']}")
        elif args.command=='new': print(create(args.name))
        else: build(args.name)
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,f'{error}\n')

if __name__=='__main__': main()
