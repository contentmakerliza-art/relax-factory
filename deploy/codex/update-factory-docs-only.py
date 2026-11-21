from pathlib import Path
import subprocess,fcntl
repo=Path('/opt/relax-factory')
def git(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout
with Path('/tmp/relax-factory-update.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if git('status','--porcelain').strip():raise ValueError('Preserve dirty factory checkout')
 git('fetch','origin','main')
 paths=git('diff','--name-only','HEAD..origin/main').splitlines()
 if any(not p.startswith('docs/') for p in paths):raise ValueError('Code changes present; no docs-only deployment')
 if paths:git('merge','--ff-only','origin/main')
 print('Documentation fast-forwarded without container restart:',git('rev-parse','HEAD').strip())
