"""One normalized cyclic master drives both owner previews and long renders."""
VERSION='2026-11-21-normalized-cyclic-master-v1'
FPS=24
CROSSFADE=.75


def install_verified_master(folder, staged, manifest):
    """Replace a visual hardlink atomically, never mutate the approved MP4 inode."""
    import hashlib,shutil
    if manifest.get('loop_builder_version')!=VERSION or manifest.get('publication_loop_mode')!='repeat':
        raise ValueError('Unsupported cyclic publication recipe')
    if hashlib.sha256(staged.read_bytes()).hexdigest()!=manifest['loop_master_sha256']:
        raise ValueError('Cyclic master checksum differs')
    visual=folder/'visual';visual.mkdir(exist_ok=True)
    if any(p.name!='approved-master.mp4' for p in visual.iterdir()):
        raise ValueError('Unexpected visual source; preserve it for inspection')
    target=visual/'approved-master.mp4'
    if target.exists():
        old=hashlib.sha256(target.read_bytes()).hexdigest()
        if old==manifest['loop_master_sha256']:return
        if old!=manifest['preview_sha256']:raise ValueError('Previous visual differs from approved preview')
        history=folder/'codex-recipe-history';history.mkdir(exist_ok=True)
        backup=history/'approved-master-before-cyclic-recipe.mp4'
        if not backup.exists():shutil.copy2(target,backup)
    temp=visual/'cyclic-master.tmp';shutil.copy2(staged,temp);temp.replace(target)


def expected_loop_frames(source_frames):
    if not 192 <= source_frames <= 245:
        raise ValueError('Need eight to ten seconds of source video')
    return source_frames-round(CROSSFADE*FPS)


def safe_camera_fit(measurement):
    if not measurement:return True
    values=measurement[1]
    return (max(x[0] for x in values)/min(x[0] for x in values)<=1.08
            and max(abs(x[1]) for x in values)<=180*.04
            and max(abs(x[2]) for x in values)<=320*.04)
