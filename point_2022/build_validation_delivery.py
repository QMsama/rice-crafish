"""附件格式的数据准备：田面水量、虾沟蓄水、TN浓度与出口负荷。"""
from pathlib import Path
import csv,json,math,hashlib
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'.codex-work/qgis_point_2022/delivery_20261019'
OUT=ROOT/'模型/2026.9.3/2022点位验证/点位验证'
WATER=ROOT/'.codex-work/qgis_point_2022/original_water_runs/20261019_134725/daily_full_precision.csv'
TN=ROOT/'.codex-work/qgis_point_2022/manual_runs/20261018_203016_799767'
TEMPLATE=ROOT/'模型/2026.6.27/毕业论文/验证终稿'
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
        for r in rows:w.writerow({k:format(v,'.2f') if isinstance(v,float) else v for k,v in r.items()})
def vol(h):return 285*(.9*h+1.1667*h*h)
def depth(v):return (-.9+math.sqrt(.9**2+4*1.1667*v/285))/(2*1.1667)
def main():
    WORK.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    assert not any(OUT.iterdir()), '目标目录已有文件，请先核查避免覆盖'
    w={(r['处理'],r['日期']):r for r in read(WATER)}
    tn={(r['处理'],r['日期']):float(r['合计TN_mg_L']) for r in read(TN/'daily_components.csv')}
    obs={}
    for r in read(TN/'observations.csv'):obs.setdefault((r['treatment'],r['date']),[]).append(float(r['value']))
    waterobs={r['日期']:r for r in read(ROOT/'模型/2026.9.3/2022点位验证/2022旧版观测水位模拟_20261019_134725/旧版水位观测值.csv')}
    headers=list(read(TEMPLATE/'水量平衡验证/水量平衡.csv')[0])
    th=list(read(TEMPLATE/'田面水TN验证/TN模拟对齐数据.csv')[0])
    waterrows=[];tnrows=[];payload=[];checks=[]
    v=vol(.8)
    for ds in sorted({d for t,d in w}):
        rm,rc=w['RM',ds],w['RCC',ds]
        p=float(rm['降雨_mm']);et=float(rm['蒸腾T_mm'])+2
        surface=285*(.9+2*1.1667*depth(v))
        inflow=float(rc['田面出流_mm'])*2245/1000
        available=v+p*855/1000+inflow
        actual=min(available,(et+2)*surface/1000)
        pre=available-actual;out=max(0,pre-vol(.9));vn=pre-out
        checks.append(v+p*855/1000+inflow-actual-out-vn);v=vn
        o=waterobs.get(ds,{})
        vals=[ds,p,et,float(rm['终稿规则水深_mm']),float(o['RM水深_mm']) if o else '',float(rm['灌溉_mm']),float(rm['田面出流_mm']),
              float(rc['终稿规则水深_mm']),float(o['RCC水深_mm']) if o else '',float(rc['灌溉_mm']),depth(v)*1000,0.0,out,out]
        waterrows.append(dict(zip(headers,vals)))
        getobs=lambda t:sum(obs[t,ds])/len(obs[t,ds]) if (t,ds) in obs else ''
        tv=[ds,int(ds[5:7]+ds[8:]),tn['RM',ds],tn['RCC',ds],getobs('RM'),getobs('RCC')]
        tnrows.append(dict(zip(th,tv)))
        payload.append([ds,float(rm['田面出流_mm']),None,tn['RM',ds],None,out,tn['RCC',ds],None])
    assert len(payload)==111 and max(map(abs,checks))<1e-9
    write(OUT/'水量平衡.csv',waterrows);write(OUT/'TN模拟对齐数据.csv',tnrows)
    manifest={'period':['2022-06-05','2022-09-23'],'days':len(payload),'E_assumption_mm_day':2,'seepage_mm_day':2,
              'RM_area_m2':1100,'RCC_area_m2':3100,'RCC_field_m2':2245,'ditch_initial_depth_mm':800,'ditch_max_depth_mm':900,
              'RCC_concentration_assumption':'field TN represents ditch outlet TN; no separate ditch nitrogen attenuation',
              'water_scope':'original final field rules; original ditch storage geometry; no direct field bypass',
              'TN_observations':'same-date values averaged for single-row template; full source archived',
              'max_ditch_balance_error_m3':max(map(abs,checks)),
              'RM_total_kg':sum(r[1]*1100/1000*r[3]*.001 for r in payload),
              'RCC_total_kg':sum(r[5]*r[6]*.001 for r in payload),
              'sources':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [WATER,TN/'daily_components.csv',TN/'observations.csv',TEMPLATE/'负荷/负荷V2.xlsx']}}
    (WORK/'payload.json').write_text(json.dumps({'rows':payload,'output':str(OUT),'template':str(TEMPLATE/'负荷/负荷V2.xlsx'),'manifest':manifest},ensure_ascii=False),encoding='utf-8')
    (WORK/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
