"""点位水量、TN与出口负荷计算及同日观测核验。"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from datetime import date
import argparse
import csv
import json
import math
import uuid

from water_balance import point_field_step, point_ditch_step
from water_quality import point_concentration, outlet_load_kg

PACKAGE = Path(__file__).resolve().parent
DEFAULT_YEAR = 2022


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scores(pairs):
    """同日配对RMSE与偏差；每组观测及其数据用途单独报告。"""
    if not pairs:
        return {'n': 0}
    return {'n':len(pairs),
            'rmse':math.sqrt(sum((sim-obs)**2 for sim,obs in pairs)/len(pairs)),
            'bias':sum(sim-obs for sim,obs in pairs)/len(pairs)}


def project_root():
    for parent in PACKAGE.parents:
        if (parent/'模型/2026.9.3/模型背景数据').is_dir():
            return parent
    raise FileNotFoundError('请用--root指定数据项目。')


def run(inputs=None, parameters=None, events=None, root=None, year=DEFAULT_YEAR,
        tn_observations=None, water_observations=None):
    root = Path(root).resolve() if root else project_root()
    local_data = root/'模型/2026.9.3/面上推广/核心计算代码'
    def input_file(supplied, relative):
        if supplied:
            return Path(supplied)
        packaged = PACKAGE/relative
        return packaged if packaged.is_file() else local_data/relative
    input_path = input_file(inputs,f'inputs/point_{year}.csv')
    parameter_path = input_file(parameters,f'configs/point_{year}.json')
    event_path = input_file(events,f'inputs/point_{year}_events.csv')
    if not all(p.is_file() for p in (input_path,parameter_path,event_path)):
        raise FileNotFoundError(f'请提供{year}年点位逐日输入、参数和施肥事件表：--inputs、--parameters、--events。')
    daily = read_rows(input_path)
    config = json.loads(parameter_path.read_text(encoding='utf-8-sig'))
    event_rows = read_rows(event_path)
    # 当前点位计算对应试验田几何；年度或站点改变需明确提供几何参数。
    geometry = config.get('geometry')
    if geometry is None:
        raise ValueError('参数文件需包含geometry：RM面积、RCC田面/沟渠面积及沟渠几何。')
    positive = ('RM_area_m2','RCC_field_area_m2','RCC_ditch_area_m2','ditch_length_m','ditch_b','ditch_a','ditch_max_depth_mm')
    nonnegative = ('ditch_initial_depth_mm','infiltration_mm_day')
    if any(not math.isfinite(geometry[k]) or geometry[k] <= 0 for k in positive):
        raise ValueError('面积与沟渠几何参数须为有限正数。')
    if any(not math.isfinite(geometry[k]) or geometry[k] < 0 for k in nonnegative):
        raise ValueError('初始水位及下渗须为有限非负数。')
    if geometry['ditch_initial_depth_mm'] > geometry['ditch_max_depth_mm']:
        raise ValueError('沟渠初始水位应不超过最高水位。')
    system_area = (geometry['RCC_field_area_m2']+geometry['RCC_ditch_area_m2'])/10000
    if not math.isclose(system_area,config['system_area_ha'],rel_tol=0,abs_tol=1e-12):
        raise ValueError('geometry的RCC系统面积须与投饵参数system_area_ha一致。')
    dates = sorted({r['日期'] for r in daily})
    if not dates or any(date.fromisoformat(d).year != year for d in dates):
        raise ValueError('点位输入日期需与--year一致。')
    if any(date.fromisoformat(e['date']).year != year or date.fromisoformat(e['response_date']).year != year for e in event_rows):
        raise ValueError('施肥事件日期需与--year一致。')
    event_keys = [(e['treatment'],e['date']) for e in event_rows]
    if len(set(event_keys)) != len(event_keys):
        raise ValueError('同处理同日施肥事件应合并为一条。')
    if any(t not in ('RM','RCC') for t,_ in event_keys):
        raise ValueError('施肥事件处理应为RM或RCC。')
    if any(e['response_date'] < e['date'] for e in event_rows):
        raise ValueError('施肥响应日期应在施肥日期当天或之后。')
    missing_treatments = {'RM','RCC'}-{t for t,_ in event_keys}
    if missing_treatments-set(config.get('zero_fertilizer_treatments',[])):
        raise ValueError('需提供两处理施肥事件；零施肥处理须在zero_fertilizer_treatments中注明。')
    if len(daily) != 2*len(dates) or len({(r['处理'],r['日期']) for r in daily}) != len(daily):
        raise ValueError('每个日期需各有一条RM和RCC输入，且键唯一。')
    if any((date.fromisoformat(b)-date.fromisoformat(a)).days != 1 for a,b in zip(dates,dates[1:])):
        raise ValueError('逐日水量输入日期必须连续。')
    if {r['处理'] for r in daily} != {'RM','RCC'}:
        raise ValueError('处理应为RM和RCC。')
    by_key = {(r['处理'],r['日期']):r for r in daily}
    field = {}
    water_rows = []
    for treatment in ('RM','RCC'):
        previous = 0.0
        for day in dates:
            row = by_key[treatment,day]
            rain, et = float(row['降雨_mm']), float(row['蒸散发ET_mm'])
            if min(rain,et) < 0:
                raise ValueError('降雨和ET须非负。')
            thresholds = [float(row[k]) for k in ['灌水下限_mm','目标水深_mm','蓄水上限_mm']]
            result = point_field_step(previous, rain, et, *thresholds, int(row['晒田期']) == 1,
                                      infiltration=geometry['infiltration_mm_day'])
            if abs(result['closure_mm']) > 1e-9:
                raise ArithmeticError('田面水量闭合失败。')
            previous = result['water']
            field[treatment,day] = result
            water_rows.append({'treatment':treatment,'date':day,**result})
    length,b,a = (geometry[k] for k in ('ditch_length_m','ditch_b','ditch_a'))
    h0 = geometry['ditch_initial_depth_mm']/1000
    volume = length*(b*h0+a*h0*h0)
    ledger, tn_rows = [], []
    totals = {'RM':0.0,'RCC':0.0}
    for day in dates:
        rm, rc = by_key['RM',day], by_key['RCC',day]
        if (float(rm['降雨_mm']),float(rm['蒸散发ET_mm'])) != (float(rc['降雨_mm']),float(rc['蒸散发ET_mm'])):
            raise ValueError('同点位RM/RCC使用相同降雨与ET。')
        concentrations = {}
        for treatment in ('RM','RCC'):
            component = point_concentration(treatment,day,event_rows,config)
            concentrations[treatment] = component['total_mg_L']
            tn_rows.append({'treatment':treatment,'date':day,**component})
        volume,outlet,closure = point_ditch_step(volume,float(rm['降雨_mm']),float(rm['蒸散发ET_mm']),field['RCC',day]['drain'],geometry)
        if abs(closure) > 1e-9:
            raise ArithmeticError('沟渠水量闭合失败。')
        rm_outlet = field['RM',day]['drain']*(geometry['RM_area_m2']/1000)
        rm_mass = outlet_load_kg(rm_outlet,concentrations['RM'])
        rc_mass = outlet_load_kg(outlet,concentrations['RCC'])
        totals['RM'] += rm_mass
        totals['RCC'] += rc_mass
        ledger.append({'date':day,'RM_outlet_m3':rm_outlet,'RCC_outlet_m3':outlet,
                       'ditch_volume_m3':volume,'closure_m3':closure,'RM_load_kg':rm_mass,'RCC_load_kg':rc_mass})
    metrics, pairs = {}, []
    if tn_observations:
        # 按原记录数据用途分组；率定日期额外标记，避免同数据重用被当作独立验证。
        grouped = {}
        for row in read_rows(tn_observations):
            treatment,day = row['treatment'],row['date']
            if treatment not in ('RM','RCC'):
                raise ValueError('观测处理应为RM或RCC。')
            peak_dates = config['peak_parameters'][treatment]['training_dates']
            bg_dates = config['background_feed_parameters']['training_dates'][treatment]
            calibrated = day in set(peak_dates+bg_dates)
            eligible = row.get('included_in_metrics','True').lower() == 'true'
            role = 'calibration' if calibrated else ('evaluation' if eligible else 'excluded')
            source_role = row.get('model_role','unspecified') or 'unspecified'
            sim = point_concentration(treatment,day,event_rows,config)['total_mg_L']
            obs = float(row['value'])
            pairs.append({'variable':'TN_mg_L','treatment':treatment,'date':day,'observed':obs,
                          'simulated':sim,'role':role,'source_role':source_role,'included_in_metrics':eligible})
            if eligible:
                grouped.setdefault((treatment,role,source_role,day),[]).append((sim,obs))
        by_group = {}
        for (treatment,role,source_role,day), values in grouped.items():
            by_group.setdefault(treatment+'_'+role+'_'+source_role,[]).append((values[0][0],sum(o for _,o in values)/len(values)))
        metrics['TN_mg_L'] = {k:scores(v) for k,v in by_group.items()}
    if water_observations:
        water_pairs = {'RM':[],'RCC':[]}
        for row in read_rows(water_observations):
            day = date(*map(int,row['日期'].replace('/','-').split('-'))).isoformat()
            for treatment in ('RM','RCC'):
                value = row.get('实测_'+treatment+'_水位_mm','')
                if value and (treatment,day) in field:
                    sim,obs = field[treatment,day]['water'],float(value)
                    water_pairs[treatment].append((sim,obs))
                    pairs.append({'variable':'water_mm','treatment':treatment,'date':day,
                                  'observed':obs,'simulated':sim,'role':'agreement','source_role':'','included_in_metrics':True})
        metrics['water_mm'] = {k:scores(v) for k,v in water_pairs.items()}
    output = root/'.codex-work/four_core_runs/point'/uuid.uuid4().hex
    output.mkdir(parents=True)
    write_rows(output/'water.csv',water_rows)
    write_rows(output/'TN.csv',tn_rows)
    write_rows(output/'outlet_load.csv',ledger)
    write_rows(output/'observation_pairs.csv',pairs)
    summary = {'year':year,'start':dates[0],'end':dates[-1],'days':len(dates),
               'RM':{'total_kg':totals['RM'],'kg_ha':totals['RM']/(geometry['RM_area_m2']/10000)},
               'RCC':{'total_kg':totals['RCC'],'kg_ha':totals['RCC']/((geometry['RCC_field_area_m2']+geometry['RCC_ditch_area_m2'])/10000)},
               'metrics':metrics,'pairing':'same-date mean for replicate TN observations',
               'concentration':'field TN represents RCC ditch outlet TN',
               'geometry':geometry,
               'inputs':{'daily':str(input_path),
                         'parameters':str(parameter_path),
                         'events':str(event_path),
                         'tn_observations':str(tn_observations) if tn_observations else None,
                         'water_observations':str(water_observations) if water_observations else None}}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),**summary},ensure_ascii=False,indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root','inputs','parameters','events','tn-observations','water-observations'):
        parser.add_argument('--'+name)
    parser.add_argument('--year',type=int,default=DEFAULT_YEAR)
    args = parser.parse_args()
    run(**vars(args))
