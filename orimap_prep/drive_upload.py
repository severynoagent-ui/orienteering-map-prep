from __future__ import annotations
from pathlib import Path
import json, os, sys
from .util import run

GOOGLE_PY = Path(os.environ.get('ORIMAP_GOOGLE_PY', sys.executable))
GAPI_ENV = os.environ.get('ORIMAP_GOOGLE_API')
GAPI = Path(GAPI_ENV) if GAPI_ENV else None
GSETUP_ENV = os.environ.get('ORIMAP_GOOGLE_SETUP')
GSETUP = Path(GSETUP_ENV) if GSETUP_ENV else None
FOLDER_MIME = 'application/vnd.google-apps.folder'

class DriveUploadError(RuntimeError):
    pass

def _cmd(args, *, check=True):
    if not GAPI or not GAPI.exists():
        raise DriveUploadError('Google Drive upload requires ORIMAP_GOOGLE_API pointing to a compatible Google Drive CLI/helper script')
    if not GOOGLE_PY.exists():
        raise DriveUploadError(f'Python executable not found: {GOOGLE_PY}')
    return run([str(GOOGLE_PY), str(GAPI)] + list(args), check=check)

def _json_cmd(args):
    res = _cmd(args)
    try:
        return json.loads(res.stdout)
    except Exception as e:
        raise DriveUploadError(f'Cannot parse google_api JSON for {args}: {e}\nSTDOUT={res.stdout[:1000]}\nSTDERR={res.stderr[:1000]}')

def check_auth():
    if GSETUP and GSETUP.exists():
        res = run([str(GOOGLE_PY), str(GSETUP), '--check'], check=False)
        if res.returncode != 0 or 'AUTHENTICATED' not in (res.stdout + res.stderr):
            raise DriveUploadError(f'Google auth is not valid. stdout={res.stdout[:500]} stderr={res.stderr[:500]}')
        return res.stdout.strip()
    if not GAPI or not GAPI.exists():
        raise DriveUploadError('Google Drive upload requires ORIMAP_GOOGLE_API')
    return 'AUTH_CHECK_SKIPPED'

def _q(s: str) -> str:
    return s.replace("'", "\\'")

def find_folder(name: str, parent_id: str | None = None):
    q = f"name='{_q(name)}' and mimeType='{FOLDER_MIME}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    items = _json_cmd(['drive','search',q,'--raw-query','--max','10'])
    return items[0] if items else None

def ensure_folder(name: str, parent_id: str | None = None):
    existing = find_folder(name, parent_id)
    if existing:
        return existing
    args=['drive','create-folder',name]
    if parent_id:
        args += ['--parent', parent_id]
    return _json_cmd(args)

def upload_file(path: Path, parent_id: str, name: str | None = None):
    args=['drive','upload',str(path),'--parent',parent_id]
    if name:
        args += ['--name', name]
    return _json_cmd(args)

def create_folder(name: str, parent_id: str | None = None):
    args=['drive','create-folder',name]
    if parent_id:
        args += ['--parent', parent_id]
    return _json_cmd(args)

def upload_project_tree(project_root: Path, zip_path: Path, root_folder_name='OB podklady', job_folder_name: str | None = None, logger=None):
    """Upload project tree and ZIP to Google Drive.

    Creates/uses root_folder_name in My Drive, then ALWAYS creates a new child
    job folder. Local directory structure is mirrored recursively. Returns
    folder/file metadata for manifest/reporting.
    """
    check_auth()
    if not project_root.exists():
        raise DriveUploadError(f'Project root missing: {project_root}')
    if not zip_path.exists():
        raise DriveUploadError(f'ZIP missing: {zip_path}')
    job_name = job_folder_name or project_root.name
    if logger: logger.log(f'[Drive] Zajišťuji složku {root_folder_name}/{job_name}')
    root = ensure_folder(root_folder_name)
    job = create_folder(job_name, root['id'])
    folder_cache = {project_root: job}
    uploaded=[]

    def ensure_remote_dir(local_dir: Path):
        if local_dir in folder_cache:
            return folder_cache[local_dir]
        parent = ensure_remote_dir(local_dir.parent)
        meta = ensure_folder(local_dir.name, parent['id'])
        folder_cache[local_dir] = meta
        return meta

    # Upload project files, excluding tmp and local aux lock junk. Include .aux.xml because GDAL stats can be useful.
    files = [p for p in sorted(project_root.rglob('*')) if p.is_file() and '/tmp/' not in str(p)]
    for p in files:
        remote_parent = ensure_remote_dir(p.parent)
        if logger: logger.log(f'[Drive] Upload {p.relative_to(project_root)}')
        meta = upload_file(p, remote_parent['id'])
        uploaded.append({'local_path':str(p),'relative_path':str(p.relative_to(project_root)),'drive_id':meta.get('id'),'name':meta.get('name'),'webViewLink':meta.get('webViewLink')})
    if logger: logger.log(f'[Drive] Upload ZIP {zip_path.name}')
    zip_meta = upload_file(zip_path, job['id'])
    uploaded.append({'local_path':str(zip_path),'relative_path':zip_path.name,'drive_id':zip_meta.get('id'),'name':zip_meta.get('name'),'webViewLink':zip_meta.get('webViewLink')})
    return {
        'root_folder': {'id':root.get('id'),'name':root.get('name'),'webViewLink':root.get('webViewLink')},
        'job_folder': {'id':job.get('id'),'name':job.get('name'),'webViewLink':job.get('webViewLink')},
        'uploaded_files': uploaded,
    }
