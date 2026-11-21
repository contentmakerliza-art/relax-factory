import os,sys,tempfile,subprocess,unittest
from pathlib import Path
SCRIPT=Path(__file__).parents[1]/'autoupdate.sh'
class AutoUpdateTests(unittest.TestCase):
 def exercise(self,paths,blocked=False):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'deploy').mkdir();(root/'data').mkdir();bin=root/'bin';bin.mkdir()
   lease=root/'media.lock';lease.touch();script=root/'deploy/autoupdate.sh'
   text=SCRIPT.read_text().replace('DATA=/var/lib/relax-factory','DATA='+str(root/'data')).replace('/tmp/relax-factory-update.lock',str(root/'update.lock')).replace('/opt/relax-codex/cabin-backlog/media-check.lock',str(lease))
   script.write_text(text)
   commands={
    'git':"import os,sys\na=sys.argv[1:]\nif a[:2]==['rev-parse','HEAD']:print('old')\nelif a[:2]==['rev-parse','origin/main']:print('new')\nelif a[:2]==['rev-parse','--short']:print('new')\nelif a and a[0]=='diff':print(os.environ['UPDATE_TEST_PATHS'])\nelif a and a[0]=='merge':open(os.environ['UPDATE_TEST_LOG'],'a').write('merge\\n')\n",
    'docker':"import os\nopen(os.environ['UPDATE_TEST_LOG'],'a').write('docker\\n')\n",
    'flock':"import os,sys\nsys.exit(1 if sys.argv[-1]=='8' and os.environ['UPDATE_TEST_BLOCKED']=='1' else 0)\n",
    'nproc':"print(2)\n",'awk':"print(4)\n",'date':"print('2026-11-21T00:00:00Z')\n"}
   for name,body in commands.items():
    p=bin/name;p.write_text('#!'+sys.executable+'\n'+body);p.chmod(0o755)
   log=root/'calls';env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],UPDATE_TEST_PATHS='\n'.join(paths),UPDATE_TEST_LOG=str(log),UPDATE_TEST_BLOCKED='1' if blocked else '0')
   p=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
   return log.read_text().splitlines() if log.exists() else []
 def test_passports_do_not_restart_factory(self):self.assertEqual(self.exercise(['docs/quiet-pines-cabin-passport.md']),['merge'])
 def test_updater_only_change_does_not_restart_factory(self):self.assertEqual(self.exercise(['deploy/autoupdate.sh']),['merge'])
 def test_application_change_rebuilds_once(self):self.assertEqual(self.exercise(['app.py']),['merge','docker'])
 def test_active_preview_prevents_runtime_update(self):self.assertEqual(self.exercise(['render/engine.py'],blocked=True),[])
if __name__=='__main__':unittest.main()
