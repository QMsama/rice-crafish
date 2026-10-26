"""命令行与QGIS共用的区域模型入口；运行产物保存在项目.codex-work。"""
from osgeo import gdal
from pathlib import Path
import csv,hashlib,importlib.util,json,sys,uuid
from datetime import date,timedelta
sys.dont_write_bytecode=True
PACKAGE=Path(__file__).resolve().parent

def project_root():
    for p in PACKAGE.parents:
        if (p/'模型/2026.9.3/模型背景数据').is_dir():return p
    raise FileNotFoundError('请将核心计算代码放在包含模型/2026.9.3/模型背景数据的项目内。')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def run(preset='paper_2022',root=None):
    from osgeo import gdal
    import numpy as np
    root=Path(root) if root else project_root()
    config_path=PACKAGE/'configs'/f'{preset}.json'
    config=json.loads(config_path.read_text(encoding='utf-8'))
    for key in ['year','start','days']:
        flag='--'+key
        if flag not in config['arguments'] or config['arguments'][config['arguments'].index(flag)+1]!=str(config[key]):
            raise ValueError('配置头部与arguments不一致：'+key)
    if '--rm-daily-cap' in config['arguments']:
        raise ValueError('此选项尚待水量闭合核验；复现配置不使用该选项。')
    if '--limit' in config['arguments']:
        raise ValueError('本入口按完整区域复现；局部运行需独立定义土壤缺失值填补域。')
    base=root/'模型/2026.9.3/模型背景数据'
    workspace=root/'.codex-work/regional_reproduction';workspace.mkdir(parents=True,exist_ok=True)
    inputs=[base/'rice_crayfish/Rice_2021.tif',base/'nitrogen_fertilizer_use/Nfer-2018',base/'soil/Environmental Date_pH.tif',base/'soil/Environmental Data_SOM.tif',PACKAGE/'inputs/daily_full_precision.csv']
    start=date.fromisoformat(config['start']);dates=[start+timedelta(days=i) for i in range(config['days'])]
    for d in dates:
        doy=d.timetuple().tm_yday;y=d.year
        inputs += [base/f'rain daily tiff/{y}/PRE_{y}_Day_{doy:03d}.tif',base/f'蒸散发/ET_{y}_daily_tiff/ET_{y}{doy:03d}.tif']
    missing=[str(p) for p in inputs if not p.exists()]
    if missing:raise FileNotFoundError('\n'.join(missing))
    records=[{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for p in inputs]
    signature={'dates':[str(d) for d in dates],'inputs':records,'engine_sha256':digest(PACKAGE/'regional_model.py')}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:20]
    cache=workspace/'cache'/f'{config["year"]}_{key}.npz';cache.parent.mkdir(exist_ok=True)
    mask_ds=gdal.Open(str(inputs[0]));mask=mask_ds.ReadAsArray();gt=mask_ds.GetGeoTransform()
    if abs(abs(gt[1]*gt[5]-gt[2]*gt[4])/10000-4.554342663494959)>1e-8:
        raise ValueError('当前核验版本使用固定像元面积；更换模板需要同步修改几何参数。')
    shape=(len(dates),int(((mask==1)|(mask==3)).sum()))
    if cache.exists():
        with np.load(cache) as z:
            if z['rain'].shape!=shape or z['et'].shape!=shape:raise ValueError('缓存维度不符合日期与掩膜。')
    cache.with_suffix('.json').write_text(json.dumps(signature,ensure_ascii=False,indent=2),encoding='utf-8')
    module_name='regional_model_'+uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location(module_name,PACKAGE/'regional_model.py')
    model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    model.ROOT=root;model.BASE=base;model.POINTRUN=PACKAGE/'inputs';model.HERE=workspace
    args=config['arguments']+['--tag',config['id'],'--cache-file',str(cache)]
    output=model.main(args)
    # 日期分组只用于重现既有统计口径，不代表逐像元物候识别。
    with (output/'逐日区域账本.csv').open(encoding='utf-8-sig') as f:ledger=list(csv.DictReader(f))
    groups={k:{'RM_kg':0.,'RCC_kg':0.} for k in ['06月','07月01日至08月15日','08月16日以后']}
    for r in ledger:
        md=r['date'][5:];k='06月' if md<'07-01' else ('07月01日至08月15日' if md<='08-15' else '08月16日以后')
        groups[k]['RM_kg']+=float(r['rm_load_kg']);groups[k]['RCC_kg']+=float(r['rcc_load_kg'])
    with (output/'日期分段负荷.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['日期组','RM_t','RCC_t','RM_pct','RCC_pct'])
        totals={t:sum(g[t+'_kg'] for g in groups.values()) for t in ['RM','RCC']}
        for k,g in groups.items():w.writerow([k,g['RM_kg']/1000,g['RCC_kg']/1000,100*g['RM_kg']/totals['RM'],100*g['RCC_kg']/totals['RCC']])
    actual=json.loads((output/'summary.json').read_text(encoding='utf-8'))
    checks={t:{k:{'expected':v,'actual':actual[t][k],'difference':actual[t][k]-v} for k,v in config['expected'][t].items()} for t in ['RM','RCC']}
    numeric_pass=all(abs(x['difference'])<1e-6 for t in checks.values() for x in t.values())
    verification={'preset':preset,'reference_run':config['reference_run'],'summary_checks':checks,'summary_reproduced':numeric_pass,'interpretation':'复现一致性；不代表模型实测有效性。'}
    (output/'复现核验.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'运行清单.json').write_text(json.dumps({'config':config,'config_sha256':digest(config_path),'input_signature':signature,'cache':str(cache),'engine_sha256':digest(PACKAGE/'regional_model.py')},ensure_ascii=False,indent=2),encoding='utf-8')
    for p in [PACKAGE/'regional_model.py',PACKAGE/'run_model.py',config_path]:
        (output/p.name).write_bytes(p.read_bytes())
    (workspace/f'latest_{preset}.json').write_text(json.dumps({'run':str(output)},ensure_ascii=False,indent=2),encoding='utf-8')
    print('复现一致性:',numeric_pass,'输出:',output)
    return output

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--preset',default='paper_2022');p.add_argument('--root')
    a=p.parse_args();run(a.preset,a.root)
