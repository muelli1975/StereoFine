"""Measure reusable ExifTool against release metadata writes on public fixtures."""
from __future__ import annotations

import argparse
from pathlib import Path
from queue import Queue
from statistics import median
from subprocess import CompletedProcess, PIPE, Popen, STDOUT
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from unittest.mock import patch
import json
import shutil

from stereofine import metadata
from tools import benchmark_cpu_batch as bench
from tools.benchmark_windows_cpu import host_info, invoke

class PersistentExifTool:
    def __enter__(self):
        self.id = 0
        self.lines = Queue()
        self.process = Popen([str(metadata.find_exiftool_path()),'-stay_open','True','-@','-'],
                             stdin=PIPE, stdout=PIPE, stderr=STDOUT, encoding='utf-8', errors='replace')
        self.reader = Thread(target=self.read, daemon=True)
        self.reader.start()
        return self

    def read(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip('\r\n'))
        self.lines.put(None)

    def run(self, args, **kwargs):
        self.id += 1
        request = str(self.id)
        marker = 'stereofine-status-' + request + '='
        commands = [*args[1:],'-echo3',marker+'${status}','-execute'+request]
        if any('\r' in arg or '\n' in arg for arg in commands):
            raise ValueError('A newline requires the subprocess path')
        self.process.stdin.write('\n'.join(commands)+'\n')
        self.process.stdin.flush()
        output = []
        status = None
        while True:
            line = self.lines.get(timeout=15)
            if line is None:
                raise RuntimeError('ExifTool ended before replying')
            if line == '{ready'+request+'}':
                break
            if line.startswith(marker):
                status = int(line[len(marker):])
            else:
                output.append(line)
        if status is None:
            raise RuntimeError('ExifTool did not provide a status')
        return CompletedProcess(args,status,'\n'.join(output),'')

    def __exit__(self, *_exc):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('-stay_open\nFalse\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def child(root, output, reuse):
    if not reuse:
        return bench.run(root, output, 'parallel-4cv')
    start = perf_counter()
    with PersistentExifTool() as exif:
        opened = perf_counter()
        with patch.object(metadata.subprocess, 'run', exif.run):
            result = bench.run(root, output, 'parallel-4cv')
        closed = perf_counter()
    result['seconds'] += (opened-start)+(perf_counter()-closed)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', nargs=3)
    args = parser.parse_args()
    if args.child:
        root, output, mode = args.child
        print(json.dumps(child(Path(root), Path(output), mode == 'persistent')))
        return
    import os
    import subprocess
    import sys
    host = host_info()
    print('HOST', json.dumps(host), flush=True)
    observations = {'process': [], 'persistent': []}
    with TemporaryDirectory(prefix='sf14-exif-') as tmp:
        root = Path(tmp)/'inputs'
        output = Path(tmp)/'output'
        bench.prepare(root)
        seed = invoke(root, 'batch-child', 'parallel-4cv', output=output)
        shutil.rmtree(output)
        sidecars = {s.sidecar_path: s.sidecar_path.read_bytes() for s in bench.make_sources(root)}
        for order in (('process','persistent'),('persistent','process'),('process','persistent')):
            for mode in order:
                for path, data in sidecars.items():
                    path.write_bytes(data)
                command = [sys.executable, '-m', 'tools.benchmark_windows_exif', '--child',
                           str(root), str(output), mode]
                run = subprocess.run(command, capture_output=True, text=True, timeout=120,
                                     env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))
                if run.returncode:
                    print(run.stdout, run.stderr, flush=True)
                    run.check_returncode()
                result = json.loads(run.stdout.splitlines()[-1])
                assert result['signature'] == seed['signature'], mode
                assert all(flags == [True,True] for flags in result['cache'])
                shutil.rmtree(output)
                observations[mode].append({k:result[k] for k in ('seconds','stages','peak_mib')})
                print('EXIF', mode, round(result['seconds'],3), round(result['stages']['metadata'],3), flush=True)
        from PIL import Image
        template = Path(tmp)/'restart.jpg'
        invalid = Path(tmp)/'invalid.jpg'
        invalid.write_bytes(b'not an image')
        source = bench.make_sources(root)[0].metadata_source
        Image.new('RGB',(100,100)).save(template)
        with PersistentExifTool() as exif, patch.object(metadata.subprocess, 'run', exif.run):
            assert not metadata.copy_metadata_without_preview_or_orientation(source,invalid).success
            assert metadata.copy_metadata_without_preview_or_orientation(source,template).success
        with PersistentExifTool() as exif, patch.object(metadata.subprocess, 'run', exif.run):
            assert metadata.copy_metadata_without_preview_or_orientation(source,template).success
    summary = {mode: dict(total_s=round(median(r['seconds'] for r in runs),3),
                          metadata_s=round(median(r['stages']['metadata'] for r in runs),3))
               for mode,runs in observations.items()}
    Path('sf14-exif-results.json').write_text(json.dumps(dict(host=host, summary=summary, runs=observations),indent=2),
                                              encoding='utf-8')
    print('SUMMARY',json.dumps(summary),flush=True)


if __name__ == '__main__':
    main()
