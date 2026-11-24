import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.modules.batches.seal import canonical

IDENTIFIER = re.compile(r'[a-f0-9]{64}')


def _directory(root, kind):
    path = Path(root) / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load(root, kind, identifier, fallback):
    if not IDENTIFIER.fullmatch(identifier):
        return fallback
    try:
        return json.loads((Path(root) / kind / f'{identifier}.json').read_bytes())
    except FileNotFoundError:
        return fallback


def supplements(root, identifier):
    return _load(root, 'supplements', identifier, [])


def issued(root, identifier):
    return _load(root, 'certificates', identifier, None)


def append_supplements(root, identifier, entries):
    directory = _directory(root, 'supplements')
    merged = supplements(root, identifier) + entries
    with NamedTemporaryFile(dir=directory, delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(canonical(merged))
            file.flush()
            os.fsync(file.fileno())
            os.replace(temp, directory / f'{identifier}.json')
        finally:
            temp.unlink(missing_ok=True)
    return merged


def freeze(root, identifier, certificate):
    directory = _directory(root, 'certificates')
    with NamedTemporaryFile(dir=directory, delete=False) as file:
        temp = Path(file.name)
        try:
            file.write(canonical(certificate))
            file.flush()
            os.fsync(file.fileno())
            try:
                os.link(temp, directory / f'{identifier}.json')
            except FileExistsError:
                return issued(root, identifier), False
            return certificate, True
        finally:
            temp.unlink(missing_ok=True)
