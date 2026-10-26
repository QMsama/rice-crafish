"""只修改季中晒田期管理，并重算水量及原有TN出口负荷链。"""
from pathlib import Path
from datetime import datetime
import csv,json,hashlib,shutil
import build_validation_delivery as delivery
from drying_control import manage,is_drying,DRYING_PERIODS,stage_thresholds

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=HERE/'natural_drydown_runs/20261019_152804'
FORMAL=ROOT/'模型/2026.9.3/提取数据/点位验证'

def normalized_rows(path):
    rows=delivery.read(path)
    for r in rows:
        for k,v in r.items():
            if k=='日期':
                r[k]=datetime.strptime(v,'%Y/%m/%d').strftime('%Y-%m-%d') if '/' in v else v
            elif v!='':r[k]=float(v)
    return rows


def calculate(old, enabled=True):
    rows=[]
    for treatment in ('RM','RCC'):
        water=0.
        for original in [r for r in old if r['处理']==treatment]:
            r=dict(original)
            initial=water
            rain=float(r['降雨_mm'])
            loss=min(water+rain,sum(float(r[k]) for k in
                ('蒸腾T_mm','补充蒸发假设_mm','下渗假设_mm')))
            low,target,cap=(float(r[k]) for k in ('灌水下限_mm','目标水深_mm','蓄水上限_mm'))
            if enabled:
                low,target,cap=stage_thresholds(treatment,r['日期'],(low,target,cap))
            drying=enabled and is_drying(treatment,r['日期'])
            result=manage(max(0,water+rain-loss),rain,low,target,cap,drying)
            water=result['water']
            residual=initial+rain+result['irrigation']-loss-result['drain']-water
            assert abs(residual)<1e-9
            r.update({'终稿规则水深_mm':water,'实际合计耗水_mm':loss,
                '灌水下限_mm':low,'目标水深_mm':target,'蓄水上限_mm':cap,
                '灌溉_mm':result['irrigation'],'田面出流_mm':result['drain'],
                '水量闭合差_mm':residual,'管理排水_mm':result['management_drain'],
                '溢流_mm':result['overflow'],'晒田期':int(drying)})
            rows.append(r)
    return rows


def write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    run=HERE/'drying_control_runs'/datetime.now().strftime('%Y%m%d_%H%M%S')
    run.mkdir(parents=True)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    # 新计算必须与当前正式基准一致，用户修改源文件时先停止核查。
    allowed=[BASE/'final/水量平衡.csv']
    latest=HERE/'drying_control_latest.json'
    if latest.exists():
        previous=Path(json.loads(latest.read_text(encoding='utf-8'))['run'])/'final/水量平衡.csv'
        if previous.exists():allowed.append(previous)
    assert any(normalized_rows(FORMAL/'水量平衡.csv')==normalized_rows(p) for p in allowed), '正式水量数据发生实质变化，需先核对'
    assert sha(FORMAL/'TN模拟对齐数据.csv')==sha(BASE/'final/TN模拟对齐数据.csv')
    before={p.name:sha(p) for p in FORMAL.iterdir() if p.is_file() and not p.name.startswith('~$')}
    old=delivery.read(BASE/'daily_full_precision.csv')
    replay=calculate(old,False)
    for a,b in zip(old,replay):
        for k in a:
            if k not in ('日期','处理'):
                assert abs(float(a[k])-float(b[k]))<1e-9,(k,a,b)
    rows=calculate(old)
    assert sum(r['晒田期'] for r in rows)==14
    comparison=[]
    for a,b in zip(old,rows):
        for k in ('降雨_mm','蒸腾T_mm','补充蒸发假设_mm','下渗假设_mm'):
            assert a[k]==b[k]
        thresholds=stage_thresholds(b['处理'],b['日期'],tuple(float(a[k]) for k in
            ('灌水下限_mm','目标水深_mm','蓄水上限_mm')))
        assert thresholds==tuple(float(b[k]) for k in ('灌水下限_mm','目标水深_mm','蓄水上限_mm'))
        comparison.append({'处理':b['处理'],'日期':b['日期'],'晒田期':b['晒田期'],
            '基准水深_mm':float(a['终稿规则水深_mm']),'当前水深_mm':b['终稿规则水深_mm'],
            '基准出流_mm':float(a['田面出流_mm']),'当前出流_mm':b['田面出流_mm'],
            '管理排水_mm':b['管理排水_mm'],'溢流_mm':b['溢流_mm']})
    write(run/'daily_full_precision.csv',rows)
    write(run/'逐日修改对照.csv',comparison)
    delivery.WATER=run/'daily_full_precision.csv';delivery.WORK=run;delivery.OUT=run/'final'
    delivery.main()
    # 保留用户现有日期和不涉及本次重算的列的文本格式。
    staged=delivery.read(delivery.OUT/'水量平衡.csv')
    for original,updated in zip(delivery.read(FORMAL/'水量平衡.csv'),staged):
        for key in ['日期','降雨量_P_mm','蒸散发_ET_mm','实测_RM_水位_mm','实测_RCC_稻田水位_mm']:
            updated[key]=original[key]
    write(delivery.OUT/'水量平衡.csv',staged)
    assert sha(delivery.OUT/'TN模拟对齐数据.csv')==before['TN模拟对齐数据.csv']
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    manifest.update({'water_scope':'RM July 9-15 wet-stage thresholds 10/40/150 mm; specified midseason drying periods.',
        'drying_periods':DRYING_PERIODS,'drying_target_mm':0,
        'drying_drain_rule':'D = available field depth after daily water loss; end depth = 0',
        'rule_basis':'User-confirmed RM stage calendar; management workbook FSI jointing-booting standard for July 9-15; thesis equation 5-5 for retained drying periods.',
        'RM_July9_15_rule':{'lower_mm':10,'target_mm':40,'maximum_mm':150,
            'source':'模型/2026.6.27/毕业论文/模型/文件/田面水水分管理.xlsx!Sheet1!E5',
            'stage_mapping':'post-drying jointing-booting; inferred from stage order, not dated phenology measurements'},
        'baseline':str(BASE),'formal_before':before,
        'baseline_replay_rows':len(replay),'drying_rows':14,
        'max_field_balance_error_mm':max(abs(r['水量闭合差_mm']) for r in rows)})
    (run/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    payload=json.loads((run/'payload.json').read_text(encoding='utf-8'))
    payload['manifest']=manifest
    (run/'payload.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    for name in ('recompute_drying_control.py','drying_control.py','test_drying_control.py','build_validation_delivery.py'):
        shutil.copy2(HERE/name,run/name)
    (HERE/'drying_control_latest.json').write_text(json.dumps({'run':str(run)},ensure_ascii=False),encoding='utf-8')
    print('STAGED_RUN',run)
    print('LOADS',manifest['RM_total_kg'],manifest['RCC_total_kg'])


if __name__=='__main__':main()
