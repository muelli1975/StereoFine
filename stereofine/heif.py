"""Reuse TransCora's isolated HEIF reader; no codec is loaded into the GUI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageCms

from .image_color import sdr_rgb
from .resources import source_root, tool_path


def reader_command() -> list[str]:
    binary = tool_path('heif') / ('StereoFine-HEIF.exe' if sys.platform == 'win32' else 'StereoFine-HEIF')
    if binary.is_file():
        return [str(binary)]
    if not getattr(sys, 'frozen', False):
        return [sys.executable, str(source_root() / 'native/heif/read_heif.py')]
    raise ValueError('HEIF-Leser fehlt. StereoFine vollständig entpacken.')


def decode_heif(path: Path) -> tuple[list[np.ndarray], dict]:
    from .inputs import InputError
    try:
        with tempfile.TemporaryDirectory(prefix='stereofine-heif-') as tmp:
            command = reader_command() + [str(path.resolve()), '--decode-to', tmp]
            environment = os.environ.copy()
            # Avoid lending the GUI's frozen native-library search path to an
            # independently packaged reader with its own replaceable libraries.
            if sys.platform.startswith('linux'):
                original = environment.get('LD_LIBRARY_PATH_ORIG')
                if original is None: environment.pop('LD_LIBRARY_PATH', None)
                else: environment['LD_LIBRARY_PATH'] = original
            result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            if result.returncode:
                raise ValueError(result.stderr.strip() or 'HEIF reader failed.')
            report = json.loads(result.stdout)
            count = 2 if report.get('stereo') else 1
            descriptions = report['images']
            entities = report.get('entities', [])
            if (report.get('schema') != 1 or len(descriptions) != count
                    or (count == 2 and (len(entities) != 2 or
                        any(type(x) is not int or x < 1 for x in entities) or entities[0] == entities[1]))):
                raise ValueError('Inconsistent HEIF stereo description.')
            images = []
            for index, description in enumerate(descriptions):
                with Image.open(Path(tmp) / f'{index}.png') as image:
                    image.load()
                    if list(image.size) != description['size']:
                        raise ValueError('Inconsistent HEIF image dimensions.')
                    images.append(sdr_rgb(image))
            if count == 2 and images[0].shape != images[1].shape:
                raise ValueError('HEIF half-images have different dimensions.')
            return images, report
    except (OSError, ValueError, KeyError, TypeError, ImageCms.PyCMSError, subprocess.SubprocessError) as exc:
        raise InputError(f'HEIF-Datei konnte nicht geladen werden: {path}: {exc}') from exc
