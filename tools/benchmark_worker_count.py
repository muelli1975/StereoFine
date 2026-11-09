"""Compare bounded worker counts with persistent EXIF and mixed-size public inputs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from PIL import Image

from stereofine import metadata
from tools import benchmark_cpu_batch as bench
from tools.benchmark_windows_cpu import host_info
from tools.benchmark_windows_exif import PersistentExifTool


def child(root, output, mode, cancel):
    start = perf_counter()
    with PersistentExifTool() as exif:
        opened = perf_counter()
        with patch.object(metadata.subprocess, 'run', exif.run):
            result = bench.run(root, output, mode, cancel=cancel)
        closed = perf_counter()
    result['seconds'] += opened-start+perf_counter()-closed
    return result


def invoke(root, output, mode, cancel=False):
    cmd = [sys.executable, '-m', 'tools.benchmark_worker_count', '--child', str(root), str(output), mode]
    if cancel:
        cmd.append('--cancel')
    run = subprocess.run(cmd, text=True, capture_output=True, timeout=240,
                         env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))
    if run.returncode:
        print(run.stdout,run.stderr,flush=True)
        run.check_returncode()
    return json.loads(run.stdout.splitlines()[-1])


def enlarge_fixture(root, dimensions):
    source = next(s for s in bench.make_sources(root) if s.base_name == 'CrusadeP')
    path = source.left_path
    with Image.open(path) as image:
        width, height = image.width//2, image.height
        enlarged = Image.new('RGB', (2*5472,3648))
        for x in (0,1):
            eye = image.crop((x*width,0,(x+1)*width,height))
            enlarged.paste(eye.resize((5472,3648),Image.Resampling.LANCZOS),(x*5472,0))
        exif = image.getexif().tobytes()
    enlarged.save(path,exif=exif)
    dimensions['CrusadeP']['size'] = [5472,3648]
    dimensions['CrusadeP']['derived'] = 'Each public eye resampled independently to stress master-size rendering'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child',nargs=3)
    parser.add_argument('--cancel',action='store_true')
    args = parser.parse_args()
    if args.child:
        root,output,mode = args.child
        print(json.dumps(child(Path(root),Path(output),mode,args.cancel)))
        return
    host = host_info()
    print('HOST',json.dumps(host),flush=True)
    modes = ('serial-default','parallel-4cv','workers3-2cv','workers3-4cv',
             'workers4-1cv','workers4-2cv','workers4-4cv')
    if host['logical_cpus'] >= 8:
        modes += ('parallel-8cv','workers3-8cv')
    observations = {mode:[] for mode in modes}
    with TemporaryDirectory(prefix='sf14-workers-') as tmp:
        root,output = Path(tmp)/'inputs',Path(tmp)/'output'
        dimensions = bench.prepare(root)
        enlarge_fixture(root,dimensions)
        sources = bench.make_sources(root)
        reference = None
        for i, order in enumerate((modes,tuple(reversed(modes))),1):
            for mode in order:
                for source in sources:
                    source.sidecar_path.unlink(missing_ok=True)
                result = invoke(root,output,mode)
                if reference is None:
                    reference = result['signature']
                assert result['signature'] == reference, mode
                assert all(x==[False,False] for x in result['cache'])
                observations[mode].append({k:result[k] for k in ('seconds','peak_mib','cv_threads','stages')})
                print('WORKERS',i,mode,round(result['seconds'],3),round(result['peak_mib'],1),flush=True)
                shutil.rmtree(output)
        results = {mode:dict(seconds=round(median(r['seconds'] for r in rows),3),
                             peak_mib=round(max(r['peak_mib'] for r in rows),1),cv_threads=rows[0]['cv_threads'])
                   for mode,rows in observations.items()}
        fastest = min((mode for mode in modes if bench.MODES[mode][0]>=3),key=lambda mode:results[mode]['seconds'])
        for source in sources:
            source.sidecar_path.unlink(missing_ok=True)
        cancel = invoke(root,output,fastest,cancel=True)
        shutil.rmtree(output)
        restart = invoke(root,output,fastest)
        assert restart['signature'] == reference
    Path('sf14-worker-count-results.json').write_text(json.dumps(dict(host=host,dimensions=dimensions,
        observations=observations,summary=results,cancel=cancel),indent=2),encoding='utf-8')
    print('SUMMARY',json.dumps(results),flush=True)


if __name__ == '__main__':
    main()
