"""晒田停止补灌，积水经蒸散发和下渗消退；超蓄水上限才溢流。"""
from pathlib import Path
from datetime import datetime
import csv,json,shutil
import build_validation_delivery as delivery

HERE=Path(__file__).resolve().parent
RUN=HERE/'natural_drydown_runs'/datetime.now().strftime('%Y%m%d_%H%M%S')
RUN.mkdir(parents=True)
source=delivery.WATER
old=delivery.read(source)
rows=[]
for t in ('RM','RCC'):
    h=0.0; last_cap=None
    for original in [r for r in old if r['处理']==t]:
        r=dict(original)
        p=float(r['降雨_mm']);tr=float(r['蒸腾T_mm']);initial=h
        low,target,cap=(float(r[k]) for k in ('灌水下限_mm','目标水深_mm','蓄水上限_mm'))
        loss=min(h+p,tr+float(r['补充蒸发假设_mm'])+float(r['下渗假设_mm']))
        h=max(0,h+p-loss);irrig=drain=0.0
        if target==0:
            # 暂沿用前一有水阶段的蓄水上限，作为降雨溢流阈值。
            assert last_cap is not None
            cap=last_cap
            drain=max(0,h-cap);h-=drain
        else:
            last_cap=cap
            if h<low:irrig,h=target-h,target
            if p>0 and h>cap:drain,h=h-cap,cap
            elif p==0 and h>target:drain,h=h-target,target
        residual=initial+p+irrig-loss-drain-h
        assert abs(residual)<1e-9 and h>=0
        if target==0:assert irrig==0 and (drain==0 or abs(h-cap)<1e-9)
        for k,v in {'终稿规则水深_mm':h,'实际合计耗水_mm':loss,'灌溉_mm':irrig,'田面出流_mm':drain,'蓄水上限_mm':cap,'水量闭合差_mm':residual}.items():r[k]=v
        rows.append(r)
with (RUN/'daily_full_precision.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
delivery.WATER=RUN/'daily_full_precision.csv'
delivery.WORK=RUN
delivery.OUT=RUN/'final'
delivery.main()
p=RUN/'manifest.json';m=json.loads(p.read_text(encoding='utf-8'))
m['water_scope']='Natural drydown in zero-target periods; no irrigation; previous wet-stage capacity retained as provisional rainfall overflow threshold. Other wet-stage management unchanged.'
m['management_confirmation']='User confirmed natural drydown rather than immediate drainage on 2026-10-19.'
p.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
payload=json.loads((RUN/'payload.json').read_text(encoding='utf-8'));payload['manifest']=m
(RUN/'payload.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
shutil.copy2(__file__,RUN/Path(__file__).name)
(HERE/'natural_drydown_latest.json').write_text(json.dumps({'run':str(RUN)},ensure_ascii=False),encoding='utf-8')
print('JULY9',[(r['处理'],r['终稿规则水深_mm'],r['田面出流_mm']) for r in rows if r['日期']=='2022-07-09'])
