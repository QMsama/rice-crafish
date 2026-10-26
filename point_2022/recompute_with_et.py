"""用逐日ET重算2022点位水量、经验TN浓度和出口负荷。"""
from osgeo import gdal
from pathlib import Path
from datetime import date, datetime
import csv, json, math, hashlib, shutil, types
from drying_control import manage, is_drying

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FORMAL=ROOT/'模型/2026.9.3/提取数据/点位验证'
PREVIOUS=Path(json.loads((HERE/'drying_control_latest.json').read_text(encoding='utf-8'))['run'])
TN_POINTER=HERE/'active_tn_run.json'
TN_BASE=(Path(json.loads(TN_POINTER.read_text(encoding='utf-8'))['run'])
         if TN_POINTER.exists() else HERE/'manual_runs/20261018_203016_799767')
ET_BASE=ROOT/'模型/2026.9.3/模型背景数据/蒸散发'
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p, rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def same(a,b):assert abs(float(a)-float(b))<1e-9,(a,b)

def field(old, et=None):
    out=[]
    for t in ('RM','RCC'):
        h=0.
        for a in (x for x in old if x['处理']==t):
            r=dict(a);ds=a['日期'];p=float(a['降雨_mm']);initial=h
            potential=et[ds] if et is not None else float(a['蒸腾T_mm'])+2
            loss=min(h+p,potential+2)
            low,target,cap=(float(a[k]) for k in ('灌水下限_mm','目标水深_mm','蓄水上限_mm'))
            x=manage(h+p-loss,p,low,target,cap,is_drying(t,ds));h=x['water']
            residual=initial+p+x['irrigation']-loss-x['drain']-h
            same(residual,0)
            r.update({'终稿规则水深_mm':h,'实际合计耗水_mm':loss,'灌溉_mm':x['irrigation'],
                '田面出流_mm':x['drain'],'水量闭合差_mm':residual,'管理排水_mm':x['management_drain'],
                '溢流_mm':x['overflow'],'晒田期':int(is_drying(t,ds))})
            if et is not None:
                r['补充蒸发假设_mm']=0.;r['蒸散发ET_mm']=potential
                r['耗水输入说明']='ET栅格+下渗2；蒸腾T列仅保留作来源对照'
            out.append(r)
    return out

def main():
    gdal.UseExceptions()
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    run=HERE/'et_recompute_runs'/stamp;run.mkdir(parents=True)
    # 正式文件须与已核验基准吻合，保留用户独立手稿。
    accepted=[PREVIOUS/'final']
    current=HERE/'et_recompute_latest.json'
    if current.exists():
        last=Path(json.loads(current.read_text(encoding='utf-8'))['run'])
        if (last/'delivery_verification.json').exists():accepted.append(last/'final')
    for name in ('水量平衡.csv','TN模拟对齐数据.csv','负荷计算.xlsx'):
        assert any((folder/name).exists() and sha(FORMAL/name)==sha(folder/name) for folder in accepted),f'正式文件已更改，先核查: {name}'
    before={p.name:sha(p) for p in FORMAL.iterdir() if p.is_file() and not p.name.startswith('~$')}
    old=read(PREVIOUS/'daily_full_precision.csv')
    replay=field(old)
    for a,b in zip(old,replay):
        for k in a:
            if k not in ('处理','日期'):same(a[k],b[k])
    config=json.loads((HERE/'config.json').read_text(encoding='utf-8'))
    et_rows=read(ET_BASE/'ET_2022_point_20220605_20220923.csv')
    dates=sorted({r['日期'] for r in old});assert [r['date'] for r in et_rows]==dates
    et={};sources=[]
    for row in et_rows:
        p=Path(row['ET_file']);ds=gdal.Open(str(p));band=ds.GetRasterBand(1)
        col,rr=gdal.ApplyGeoTransform(gdal.InvGeoTransform(ds.GetGeoTransform()),config['longitude'],config['latitude'])
        raw=float(band.ReadAsArray(math.floor(col),math.floor(rr),1,1)[0,0])
        assert raw!=band.GetNoDataValue() and band.GetUnitType()=='mm day-1'
        value=raw*band.GetScale()+band.GetOffset();same(value,row['ET_mm_day'])
        assert math.isfinite(value) and value>=0
        et[row['date']]=value;sources.append({'date':row['date'],'path':str(p),'sha256':sha(p),'ET_mm_day':value})
    write(run/'ET逐日输入.csv',sources)
    rows=field(old,et);write(run/'daily_full_precision.csv',rows)
    # 从施肥栅格输入、各阶段C0回归式及现行参数重新执行浓度计算，不重新率定。
    tndir=run/'tn';tndir.mkdir()
    pars=json.loads((TN_BASE/'config.json').read_text(encoding='utf-8'))
    events=read(TN_BASE/'event_parameters.csv')
    for e in events:
        c=config['coefficients'][e['stage']]
        raw=c['a0']+c['aN']*float(e['N_kg_ha'])+c['apH']*float(e['pH'])+c['aSOM']*float(e['SOM_percent_assumed'])
        same(raw,e['C0_raw_mg_L']);e['C0_mg_L']=max(0.,raw)
    components=[];tn={}
    baseline_tn=read(TN_BASE/'daily_components.csv')
    for r in baseline_tn:
        t,ds=r['处理'],r['日期'];active=sorted([e for e in events if e['treatment']==t and e['response_date']<=ds],key=lambda e:e['response_date'])
        p=pars['peak_parameters'][t]
        fert=p['alpha']*active[-1]['C0_mg_L']*math.exp(-p['k']*(date.fromisoformat(ds)-date.fromisoformat(active[-1]['response_date'])).days) if active else 0.
        bg=pars['background_feed_parameters']['background_mg_L']
        feed=pars['feed_kg_day'] if t=='RCC' else 0.
        fn=feed*pars['protein_fraction']/6.25/pars['system_area_ha'];fc=pars['background_feed_parameters']['gamma']*fn
        row={'处理':t,'日期':ds,'施肥响应_mg_L':fert,'基础背景_mg_L':bg,'日投饵量_kg':feed,
             '日投饵氮_kgN_ha':fn,'投饵附加项_mg_L':fc,'合计TN_mg_L':fert+bg+fc}
        for k in r:
            if k not in ('处理','日期'):same(r[k],row[k])
        components.append(row);tn[t,ds]=row['合计TN_mg_L']
    write(tndir/'daily_components.csv',components);write(tndir/'event_parameters.csv',events)
    for name in ('observations.csv','config.json'):shutil.copy2(TN_BASE/name,tndir/name)
    if (TN_BASE/'calendar_provenance.json').exists():
        shutil.copy2(TN_BASE/'calendar_provenance.json',tndir/'calendar_provenance.json')
    # 沟渠沿用现有共用耗水驱动结构，ET作为沟渠耗水代理，另扣下渗2。
    code=(HERE/'build_validation_delivery.py').read_text(encoding='utf-8')
    code=code.replace("et=float(rm['蒸腾T_mm'])+2","et=float(rm['蒸散发ET_mm'])")
    code=code.replace("'E_assumption_mm_day':2","'ET_source':'2022 daily actual ET raster','additional_fixed_E_mm_day':0")
    module=types.ModuleType('et_delivery');module.__file__=str(HERE/'build_validation_delivery.py')
    exec(compile(code,module.__file__,'exec'),module.__dict__)
    module.WORK=run;module.OUT=run/'final';module.WATER=run/'daily_full_precision.csv';module.TN=tndir
    module.main()
    water=read(run/'final/水量平衡.csv')
    for a,b in zip(read(FORMAL/'水量平衡.csv'),water):
        for key in ('日期','降雨量_P_mm','实测_RM_水位_mm','实测_RCC_稻田水位_mm'):b[key]=a[key]
    write(run/'final/水量平衡.csv',water)
    assert sha(run/'final/TN模拟对齐数据.csv')==sha(FORMAL/'TN模拟对齐数据.csv')
    # 完整精度沟渠与出口账本。
    lookup={(r['处理'],r['日期']):r for r in rows};trace=[];v=module.vol(.8)
    payload=json.loads((run/'payload.json').read_text(encoding='utf-8'))
    for ds,loadrow in zip(dates,payload['rows']):
        rm=lookup['RM',ds];rc=lookup['RCC',ds];initial=v
        surface=285*(.9+2*1.1667*module.depth(v));rain=float(rm['降雨_mm'])*.855
        inflow=float(rc['田面出流_mm'])*2.245;loss=min(v+rain+inflow,(et[ds]+2)*surface/1000)
        outlet=max(0.,v+rain+inflow-loss-module.vol(.9));v+=rain+inflow-loss-outlet
        same(outlet,loadrow[5]);same(initial+rain+inflow-loss-outlet-v,0)
        trace.append({'日期':ds,'沟初蓄量_m3':initial,'沟降雨_m3':rain,'田面入沟_m3':inflow,
            '沟耗水_m3':loss,'沟末蓄量_m3':v,'沟末水深_mm':module.depth(v)*1000,'RCC外排_m3':outlet,
            'RM外排_m3':float(rm['田面出流_mm'])*1.1,'RM_TN_mg_L':tn['RM',ds],'RCC_TN_mg_L':tn['RCC',ds],
            'RM负荷_kg':loadrow[1]*1.1*tn['RM',ds]*.001,'RCC负荷_kg':outlet*tn['RCC',ds]*.001})
    write(run/'沟渠与负荷逐日账本.csv',trace)
    comparison=[]
    for a,b in zip(old,rows):
        comparison.append({'处理':b['处理'],'日期':b['日期'],'原ET_mm':float(a['蒸腾T_mm'])+2,'当前ET_mm':b['蒸散发ET_mm'],
            '原水深_mm':a['终稿规则水深_mm'],'当前水深_mm':b['终稿规则水深_mm'],
            '原灌溉_mm':a['灌溉_mm'],'当前灌溉_mm':b['灌溉_mm'],'原田面出流_mm':a['田面出流_mm'],'当前田面出流_mm':b['田面出流_mm']})
    write(run/'ET更新逐日对比.csv',comparison)
    m=payload['manifest'];m.update({'formal_before':before,'previous_run':str(PREVIOUS),
        'ET_sum_mm':sum(et.values()),'previous_ET_sum_mm':sum(float(r['蒸腾T_mm'])+2 for r in old if r['处理']=='RM'),
        'field_rows':len(rows),'TN_recomputed_rows':len(components),'TN_max_difference_mg_L':0,
        'ditch_ET_assumption':'same daily land ET used as ditch water-loss proxy under existing shared-driver structure; not independently validated open-water evaporation',
        'water_management':'unchanged thresholds and drainage rules; seepage 2 mm/day',
        'TN_parameters':'fixed current calibrated alpha,k,background,feed; recomputed C0 and daily concentrations',
        'ET_table':str(ET_BASE/'ET_2022_point_20220605_20220923.csv')})
    save(run/'manifest.json',m);payload['manifest']=m;save(run/'payload.json',payload)
    save(HERE/'et_recompute_latest.json',{'run':str(run)})
    for name in ('recompute_with_et.py','drying_control.py','build_validation_delivery.py'):shutil.copy2(HERE/name,run/name)
    print('ET_RECOMPUTED',str(run));print('LOAD_KG_HA',m['RM_total_kg']/.11,m['RCC_total_kg']/.31)

if __name__=='__main__':main()
