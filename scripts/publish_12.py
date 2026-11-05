"""Publish only the verified new 1.2 release; never replace a previous release."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from release_checksums import ARCHIVES


def gh(*args, check=True):
    return subprocess.run(['gh', *args], text=True, capture_output=True, check=check)


def main():
    repository=os.environ['GITHUB_REPOSITORY']
    commit=os.environ['GITHUB_SHA']
    assert repository=='muelli1975/StereoFine'
    assert gh('api',f'repos/{repository}/git/ref/heads/main','--jq','.object.sha').stdout.strip()==commit
    folder=Path('release')
    names=set(ARCHIVES)|{'SHA256SUMS.txt','BUILD_CHECKS.json'}
    names.update(name+'.sha256' for name in ARCHIVES)
    for name in names:
        assert (folder/name).is_file(),name
    view=gh('release','view','v1.2','--repo',repository,'--json','isDraft,targetCommitish',check=False)
    if view.returncode==0:
        assert json.loads(view.stdout)['isDraft'], 'A published 1.2 release already exists; do not overwrite it.'
        gh('release','edit','v1.2','--repo',repository,'--target',commit,
           '--title','StereoFine 1.2','--notes-file','RELEASE_NOTES_1.2.md')
    else:
        gh('release','create','v1.2','--repo',repository,'--draft','--target',commit,
           '--title','StereoFine 1.2','--notes-file','RELEASE_NOTES_1.2.md')
    gh('release','upload','v1.2','--repo',repository,'--clobber',
       *[str(folder/name) for name in sorted(names)])
    actual=json.loads(gh('release','view','v1.2','--repo',repository,'--json','assets').stdout)
    assert {asset['name'] for asset in actual['assets']}==names
    with tempfile.TemporaryDirectory() as td:
        gh('release','download','v1.2','--repo',repository,'--dir',td)
        for name in names:
            with (folder/name).open('rb') as a, (Path(td)/name).open('rb') as b:
                assert hashlib.file_digest(a,'sha256').digest()==hashlib.file_digest(b,'sha256').digest(),name
    assert gh('api',f'repos/{repository}/git/ref/heads/main','--jq','.object.sha').stdout.strip()==commit
    gh('release','edit','v1.2','--repo',repository,'--draft=false','--latest')
    print('Published StereoFine 1.2 after verifying all uploaded asset bytes.')


if __name__=='__main__':main()
