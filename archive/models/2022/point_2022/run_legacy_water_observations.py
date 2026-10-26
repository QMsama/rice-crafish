"""使用旧版V4观测日期、水深，对照终稿管理规则。"""
from datetime import date
import json, shutil
import compare_original_water_rules as model
u = model.u
SOURCE = u.ROOT/'模型/2026.6.27/python计算/模型验证/V4/田面水.csv'
COPY = u.ROOT/'模型/2026.6.27/毕业论文/张怡杰论文数据/田面水.csv'
RESULT = u.ROOT/'模型/2026.6.27/python计算/模型验证/终稿/水量平衡验证/水量平衡.csv'

def main():
    raw = u.read(SOURCE)
    assert raw == u.read(COPY), '旧版观测副本内容不一致'
    historical = {r['日期']:r for r in u.read(RESULT)}
    rows, clean, seen = [], [], set()
    checked = 0
    for n,r in enumerate(raw,2):
        md = int(r['日期']); ds = date(2022,md//100,md%100).isoformat()
        assert ds not in seen
        seen.add(ds)
        clean.append({'日期':ds,'RM水深_mm':float(r['水稻mm']),'RCC水深_mm':float(r['稻虾mm'])})
        for t,col,oldcol in [('RM','水稻mm','实测_RM_水位_mm'),('RCC','稻虾mm','实测_RCC_稻田水位_mm')]:
            value = float(r[col]); assert value>=0
            assert abs(float(historical[ds][oldcol])-value)<1e-9, (ds,t)
            checked += 1
            rows.append({'处理':t,'参考日期':ds,'观测水深_mm':value,'日期依据':'沿用V4原表月日；年份2022取自终稿配置'})
    out,archive = model.main(rows,'2022旧版观测水位模拟_','旧版观测（V4）','观测日期沿用V4原表。')
    u.write(out/'旧版水位观测值.csv',clean,True)
    shutil.copy2(SOURCE,archive/'observations_source.csv')
    shutil.copy2(__file__,archive/'run_legacy_water_observations.py')
    p=archive/'manifest.json'; m=json.loads(p.read_text(encoding='utf-8'))
    m.update({'observation_source':str(SOURCE),'observation_sha256':u.sha(SOURCE),'dates':len(clean),
              'historical_observation_cells_verified':checked,'scope':'field water; V4 observation dates retained; original measurement log not verified',
              'outputs_sha256':{f.name:u.sha(f) for f in out.iterdir()}})
    p.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
    print('VERIFIED',len(clean),'dates;',checked,'historical observation cells match')

if __name__=='__main__': main()
