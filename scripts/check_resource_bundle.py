"""Compare committed and freshly compiled GResources without replacing either."""

from __future__ import annotations

import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def normalize_xml(data: bytes) -> str:
    root = ET.fromstring(data)
    for element in root.iter():
        # Discard indentation, but retain leaf text (including label whitespace).
        if len(element) and element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    return ET.canonicalize(ET.tostring(root, encoding='unicode'))


def read_bundle(path: Path) -> dict[str, bytes | str]:
    names = subprocess.check_output(['gresource', 'list', str(path)], text=True).splitlines()
    contents: dict[str, bytes | str] = {}
    for name in names:
        data = subprocess.check_output(['gresource', 'extract', str(path), name])
        contents[name] = normalize_xml(data) if name.endswith(('.ui', '.svg')) else data
    return contents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('committed', type=Path)
    parser.add_argument('compiled', type=Path)
    args = parser.parse_args()
    if not args.committed.is_file():
        print(f'Missing committed resource bundle: {args.committed}')
        return 1
    old, new = read_bundle(args.committed), read_bundle(args.compiled)
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    if changed:
        print(
            'Resource bundle is stale; run ./resources/compile_resources.sh and commit the bundle:'
        )
        print('\n'.join(changed))
        return 1
    print('Committed resource bundle matches its sources.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
