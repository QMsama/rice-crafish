"""Run the three 2022 TN source-area stages with one Python interpreter."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Project data root containing 模型/.')
    parser.add_argument('--county-boundary', type=Path, help='County shapefile; relative paths are resolved below --root.')
    parser.add_argument('--study-boundary', type=Path, help='Study-boundary shapefile; relative paths are resolved below --root.')
    parser.add_argument('--font', type=Path, help='Optional font file; Microsoft YaHei is used when installed.')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        parser.error('--root must be a directory')

    def data_path(value):
        return (value if value.is_absolute() else root / value).resolve()

    regional = root / '模型/2026.9.3/面上推广'
    raster_inputs = [regional / f'TN_{kind}_{system}_2022.tif'
                     for system in ('RM', 'RCC') for kind in ('Load', 'TotalMass')]
    county = data_path(args.county_boundary) if args.county_boundary else next(
        (root / '模型/2026.6.27/毕业论文/制图').rglob('县.shp'), None)
    study = data_path(args.study_boundary) if args.study_boundary else (
        root / '模型/2026.9.3/模型背景数据/江汉平原矢量/江平原t.shp')
    required = raster_inputs + [study]
    if county is None:
        parser.error('County boundary not found; provide --county-boundary.')
    required.append(county)
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        parser.error('Missing input files: ' + '; '.join(missing))

    package = Path(__file__).resolve().parent
    output_parent = root / '.codex-work/source_area_runs'
    output_parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    run = output_parent / f'{stamp}_{uuid.uuid4().hex[:12]}'
    run.mkdir(exist_ok=False)
    for subdir in ('load_area_figure', 'source_area_map', 'source_area_map/agent_county'):
        (run / subdir).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({'TN_PROJECT_ROOT':str(root),'TN_SOURCE_AREA_RUN':str(run),
                'TN_COUNTY_BOUNDARY':str(county.resolve()),'TN_STUDY_BOUNDARY':str(study.resolve()),
                'PYTHONDONTWRITEBYTECODE':'1','PYTHONIOENCODING':'utf-8'})
    if args.font:
        env['TN_SOURCE_AREA_FONT'] = str(data_path(args.font))
    else:
        env.pop('TN_SOURCE_AREA_FONT', None)

    manifest = {'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),
                'project_root':str(root),'run_directory':str(run),
                'python_executable':sys.executable,
                'inputs':[{'path':str(p.resolve()),'sha256':sha256(p)} for p in required], 'steps':[]}
    manifest_path = run / 'run_manifest.json'

    def save_manifest():
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

    save_manifest()
    print('RUN_DIRECTORY=' + str(run),flush=True)
    for name in ('load_area_curve.py','county_statistics.py','source_area_map.py'):
        script = package / name
        step = {'script':name,'script_sha256':sha256(script),'python_executable':sys.executable}
        print('RUN_STAGE=' + name,flush=True)
        completed = subprocess.run([sys.executable,'-B',str(script)],cwd=run,env=env)
        step['returncode'] = completed.returncode
        manifest['steps'].append(step)
        if completed.returncode:
            manifest['status'] = 'failed'
            manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
            save_manifest()
            return completed.returncode
        save_manifest()
    manifest['status'] = 'completed'
    manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save_manifest()
    print('COMPLETED_RUN_DIRECTORY=' + str(run),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
