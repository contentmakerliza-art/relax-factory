"""One read-only model check of scoped project memory. No media/bot actions."""
import json,os,pwd,subprocess
from pathlib import Path
import project_memory


def main():
    user=pwd.getpwnam('relax-codex');folder=Path('/var/lib/relax-codex/workspace/project-memory-check-20261121')
    folder.mkdir(mode=0o700,exist_ok=False);os.chown(folder,user.pw_uid,user.pw_gid)
    memories=[project_memory.context('Little Paris Jazz Cafe',request='снег и пар'),
              project_memory.context('Exhale to Sleep',request='звук фон'),
              project_memory.context('Quiet Pines Cabin',stage='preview_qc',request='снег мелкие снежинки')]
    payload=[{k:m[k] for k in ['channel','active_rules','capabilities','examples']} for m in memories]
    (folder/'context-snapshot.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    names=['paris_needs_generated_snow','exhale_requires_snow','cabin_requires_native_window_check',
           'automated_pass_is_owner_approval','arbitrary_corrections_are_fully_automatic','snow_size_already_relaxed']
    schema=dict(type='object',additionalProperties=False,properties={k:{'type':'boolean'} for k in names},required=names)
    (folder/'schema.json').write_text(json.dumps(schema))
    prompt=('Do not use tools or read files. This is a read-only integration test, not a production task. '
        'Using only the supplied active project memory, answer the six boolean questions named in the schema. '
        'A conditional future relaxation is not active unless an explicit active rule says so. '
        'Current scoped memory follows:\n'+json.dumps(payload,ensure_ascii=False))
    output=folder/'result.json'
    command=['systemd-run','--unit=relax-project-memory-live-check','--collect','--wait','--pipe',
        '-p','User=relax-codex','-p','WorkingDirectory='+str(folder),'-p','MemoryMax=384M',
        '-p','CPUQuota=25%','-p','RuntimeMaxSec=150','--setenv=HOME=/var/lib/relax-codex',
        '--setenv=CODEX_HOME=/var/lib/relax-codex/.codex',
        '/opt/relax-codex/release-0.171.0/bin/codex','exec','--ephemeral','--skip-git-repo-check',
        '--sandbox','read-only','--output-schema',str(folder/'schema.json'),'-o',str(output),'-']
    result=subprocess.run(command,input=prompt,text=True,capture_output=True,timeout=180)
    if result.returncode:raise RuntimeError('Read-only memory check failed')
    answer=json.loads(output.read_text())
    expected=dict(zip(names,[False,False,True,False,False,False]))
    if answer!=expected:raise ValueError('Model did not follow scoped memory: '+json.dumps(answer))
    report=dict(passed=True,answer=answer,model_calls=1,media_actions=0,owner_approvals_changed=False)
    (project_memory.MEMORY/'live-check.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
