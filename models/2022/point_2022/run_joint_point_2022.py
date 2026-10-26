"""2022点位α、k联合校准。QGIS打开此文件运行；参数集中在文件顶部。"""
from pathlib import Path
from datetime import date, datetime, timedelta
from collections import defaultdict
import copy
import csv
import hashlib
import json
import math
import os
import runpy
import shutil
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
os.environ['MPLCONFIGDIR']=str(HERE/'cache/matplotlib')

# 用户参数区。背景栅格和点位继续使用同目录run_point_2022.py的用户参数。
PROJECT_ROOT=Path(r'E:/#岑俊毅/2.论文/2.稻虾综合种养')
OBSERVATION_FILE='模型/2026.9.3/原始数据/2022年大田实验数据/2022年大田实验数据提取.xlsx'
OBSERVATION_SHEET='田面水TN浓度变化'
OUTPUT_DIRECTORY=PROJECT_ROOT/'模型/2026.9.3/2022点位验证'
CALIBRATION_DAYS=7  # 首次施肥后第1—7天；仅使用日期依据为“刻度”的观测
HOLDOUT_DAYS=7      # 第二次施肥后第1—7天；参数固定后检查
FERTILIZER_DATES={'RM':['2022-06-18','2022-07-06'], 'RCC':['2022-06-14','2022-06-27']}
K_BOUNDS={'basal':(.213,.436),'tillering':(.231,.512),'panicle':(.263,.670)}
# 同一处理两次事件共用α、k；k约束取各事件阶段范围的交集。
# α为非负经验幅度系数，不解释为肥料入水比例；背景/投饵模块另行研究。


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit_alpha_k(points, lower, upper):
    """剖面最小二乘：每个k解析求非负α，再在文献区间内搜索k。"""
    if len(points)<3 or len({p[1] for p in points})<3 or not 0<lower<upper:
        raise ValueError('联合校准需要至少3个不同日期，且k区间有效')
    if any(not all(math.isfinite(v) for v in p) or p[0]<=0 or p[1]<0 or p[2]<0 for p in points):
        raise ValueError('C0、时间或观测值无效')
    if not any(p[2]>0 for p in points):
        raise ValueError('全零观测不能识别衰减系数')
    def profile(k):
        x=[c0*math.exp(-k*t) for c0,t,y in points]
        alpha=max(0.,sum(v*p[2] for v,p in zip(x,points))/sum(v*v for v in x))
        return alpha,sum((alpha*v-p[2])**2 for v,p in zip(x,points))
    grid=[lower+(upper-lower)*i/2000 for i in range(2001)]
    losses=[profile(k)[1] for k in grid]
    # 精化每个局部极小值邻域，并显式比较区间端点。
    candidates=[lower,upper]
    for i in range(1,2000):
        if losses[i]<=losses[i-1] and losses[i]<=losses[i+1]:
            lo,hi=grid[i-1],grid[i+1]
            for _ in range(70):
                a,b=lo+(hi-lo)/3,hi-(hi-lo)/3
                if profile(a)[1]<profile(b)[1]: hi=b
                else: lo=a
            candidates.append((lo+hi)/2)
    k=min(candidates,key=lambda v:profile(v)[1])
    alpha,sse=profile(k)
    return alpha,k,sse


def fit_treatment(events, paired, treatment):
    own=sorted((e for e in events if e['treatment']==treatment),key=lambda e:e['date'])
    first=own[0]
    start=date.fromisoformat(first['response_date'])
    stop=min(start+timedelta(days=CALIBRATION_DAYS-1),date.fromisoformat(own[1]['date'])-timedelta(days=1))
    groups=defaultdict(list)
    for r in paired:
        if r['treatment']==treatment and r['included_in_metrics']=='True' and start<=date.fromisoformat(r['date'])<=stop:
            groups[r['date']].append(float(r['value']))
    keys=sorted(groups)
    pts=[(float(first['C0_mg_L']),(date.fromisoformat(d)-start).days,sum(groups[d])/len(groups[d])) for d in keys]
    lower=max(K_BOUNDS[e['stage']][0] for e in own)
    upper=min(K_BOUNDS[e['stage']][1] for e in own)
    alpha,k,sse=fit_alpha_k(pts,lower,upper)
    return dict(treatment=treatment,alpha=alpha,k=k,k_lower=lower,k_upper=upper,
                at_bound=min(abs(k-lower),abs(k-upper))<1e-7,n_dates=len(keys),
                training_dates=keys,training_sse=sse,first_C0_raw=float(first['C0_mg_L']),
                first_C0_calibrated=alpha*float(first['C0_mg_L']),
                stage_scope='same treatment alpha/k transferred to second event; k in stage-range intersection')


def make_metrics(base, pairs, parameters, events):
    rows=[]
    for treatment in ('RM','RCC'):
        own=sorted((e for e in events if e['treatment']==treatment),key=lambda e:e['date'])
        second=date.fromisoformat(own[1]['response_date'])
        for scope in ('首次事件率定','第二次事件前7天留出','全部评价日期（含率定）'):
            selected=[r for r in pairs if r['treatment']==treatment and r['included_in_metrics']=='True']
            if scope=='首次事件率定': selected=[r for r in selected if r['date'] in parameters[treatment]['training_dates']]
            if scope=='第二次事件前7天留出': selected=[r for r in selected if 0<=(date.fromisoformat(r['date'])-second).days<HOLDOUT_DAYS]
            days=sorted({r['date'] for r in selected})
            observed=[sum(float(r['value']) for r in selected if r['date']==d)/sum(r['date']==d for r in selected) for d in days]
            for label,key in [('文献参数','baseline_TN_mg_L'),('联合校准','joint_TN_mg_L')]:
                pred=[float(next(r[key] for r in selected if r['date']==d)) for d in days]
                rows.append(dict(treatment=treatment,scope=scope,model=label,**base['metrics'](observed,pred)))
    return rows


def export_book(path, parameters, scores, pairs, daily, events, archive, baseline_archive):
    from openpyxl import Workbook
    book=Workbook(); book.remove(book.active)
    def table(name,rows):
        sheet=book.create_sheet(name)
        if not rows:return
        sheet.append(list(rows[0]))
        for row in rows:
            sheet.append(list(row.values()))
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width=min(65,max(12,max(len(str(c.value or ''))*1.6 for c in column)))
            for cell in column[1:]:
                if isinstance(cell.value,(int,float)):cell.number_format='0.00'
    table('参数',[{'处理':p['treatment'],'α':p['alpha'],'k_每天':p['k'],'k下限':p['k_lower'],'k上限':p['k_upper'],
                  '达到边界':'是' if p['at_bound'] else '否','率定日期数':p['n_dates'],
                  '率定日期':'、'.join(p['training_dates']),'首次原C0_mg_L':p['first_C0_raw'],
                  '首次校准C0_mg_L':p['first_C0_calibrated']} for p in parameters.values()])
    table('误差对照',[{'处理':r['treatment'],'评价范围':r['scope'],'模型':r['model'],'日期数':r['n'],
                      'RMSE_mg_L':r['RMSE_mg_L'],'MAE_mg_L':r['MAE_mg_L'],'NSE':r['NSE']} for r in scores])
    table('观测对照',[{'处理':r['treatment'],'日期':r['date'],'观测TN_mg_L':float(r['value']),
                      '文献参数TN_mg_L':r['baseline_TN_mg_L'],'联合校准TN_mg_L':r['joint_TN_mg_L'],
                      '参与指标':'是' if r['included_in_metrics']=='True' else '否','数据用途':r['role_in_trial'],
                      '源日期依据':r.get('source_date_note',''),'源表行号':int(r['source_row']),
                      '筛选原因':r['evaluation_status']} for r in pairs])
    table('逐日模拟',daily)
    table('施肥与峰值',[{'处理':e['treatment'],'施肥日期':e['date'],'C0对应日期':e['response_date'],
                        '阶段':e['stage'],'事件施氮量_kgN_ha':float(e['N_kg_ha']),
                        '原C0_mg_L':float(e['C0_mg_L']),'校准C0_mg_L':float(e['C0_mg_L'])*parameters[e['treatment']]['alpha']} for e in events])
    table('说明',[{'项目':'方法','内容':'固定栅格C0关系；α非负，k在阶段范围交集中最小化浓度平方误差。每处理两次事件共用参数。'},
                  {'项目':'评价边界','内容':'首次事件用于率定；第二次事件前7天为同点事件留出。全时段指标含率定数据。'},
                  {'项目':'日期依据','内容':'插值日期观测用于图示，不计入正式指标。RM第二次施肥按7月6日。'},
                  {'项目':'输入口径','内容':'Nfer-2018年度土地施氮强度代理2022稻季；SOM按百分数假设。α不解释为入水比例。'},
                  {'项目':'完整记录','内容':str(archive)},{'项目':'栅格与气象提取记录','内容':str(baseline_archive)},
                  {'项目':'精度','内容':'表格显示两位小数，计算及JSON保存完整精度。'}])
    book.save(path)


def plot(path,parameters,pairs,daily,events,scores):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    from matplotlib import rc_context
    import matplotlib.dates as mdates
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc').get_name()
    with rc_context({'font.family':font,'axes.unicode_minus':False,'font.size':10}):
        fig=Figure(figsize=(15,8),constrained_layout=True); FigureCanvasAgg(fig)
        axes=fig.subplots(2,3,squeeze=False)
        for row,treatment in enumerate(('RM','RCC')):
            own=sorted((e for e in events if e['treatment']==treatment),key=lambda e:e['date'])
            for col,ax in enumerate(axes[row]):
                e=own[0 if col<2 else 1]
                start=date.fromisoformat(e['response_date']); end=start+timedelta(days=6)
                records=[r for r in daily if r['处理']==treatment and start<=date.fromisoformat(r['日期'])<=end]
                key='文献参数TN_mg_L' if col==0 else '联合校准TN_mg_L'
                ax.plot([date.fromisoformat(r['日期']) for r in records],[r[key] for r in records],color='#8c8c8c' if col==0 else '#237b96',lw=2,label='文献参数' if col==0 else '联合校准参数')
                obs=[r for r in pairs if r['treatment']==treatment and start<=date.fromisoformat(r['date'])<=end]
                for accepted,marker,label,color in [(True,'o','明确日期观测','#222222'),(False,'x','日期/顺序待核观测','#c78b37')]:
                    points=[r for r in obs if (r['included_in_metrics']=='True')==accepted]
                    ax.scatter([date.fromisoformat(r['date']) for r in points],[float(r['value']) for r in points],marker=marker,s=35,color=color,label=label,zorder=3)
                ax.set_title(treatment+'｜'+['首次事件：文献参数','首次事件：联合校准','第二次事件：参数迁移'][col],loc='left',fontsize=11)
                ax.set_ylabel('TN（mg/L）'); ax.set_ylim(bottom=0)
                if col>0:
                    maximum=max([float(r['value']) for r in pairs if r['treatment']==treatment]+[float(e2['C0_mg_L'])*parameters[treatment]['alpha'] for e2 in own])
                    ax.set_ylim(0,maximum*1.25)
                ax.set_xlim(start-timedelta(hours=0),end)
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=2)); ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
                ax.grid(alpha=.18)
                scope='首次事件率定' if col<2 else '第二次事件前7天留出'
                score=next(r for r in scores if r['treatment']==treatment and r['scope']==scope and r['model']==('文献参数' if col==0 else '联合校准'))
                note=f"n={score['n']}；RMSE={score['RMSE_mg_L']:.2f}" if score['n'] else '明确日期观测n=0；指标留空'
                ax.text(.98,.96,note,transform=ax.transAxes,ha='right',va='top',fontsize=9)
                if row==0 and col==1:ax.legend(loc='upper right',bbox_to_anchor=(1,.84),fontsize=8,frameon=False)
        fig.suptitle('2022年田面水TN：首次事件校准与第二次事件检验',fontsize=16)
        fig.supxlabel('左列保留原模型量级；中、右列在同一处理内共用纵轴。橙色叉号仅供图示。',fontsize=10)
        fig.savefig(path,dpi=180)


def main():
    base=runpy.run_path(str(HERE/'run_point_2022.py'),run_name='point_model_library')
    config=base['build_config'](); config.update(project_root=str(PROJECT_ROOT),observations=OBSERVATION_FILE,
                                                observation_sheet=OBSERVATION_SHEET,calibrate_k=False)
    for treatment,dates in FERTILIZER_DATES.items():
        own=sorted((e for e in config['events'] if e['treatment']==treatment),key=lambda e:e['date'])
        if len(own)!=len(dates):raise ValueError('施肥日期数与事件数不一致')
        for e,d in zip(own,dates):e.update(date=d,response_lag_days=1)
    if config['event_rule']!='latest_event':raise ValueError('此校准版本使用latest_event规则')
    # 使用已有校验规则检查用户输出路径。
    check=copy.deepcopy(config); check['output_directory']=str(OUTPUT_DIRECTORY)
    base['check_config'](check,PROJECT_ROOT)
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    archive=HERE/'joint_runs'/run_id; archive.mkdir(parents=True)
    config['output_directory']=str(HERE/'joint_baselines')
    config_path=archive/'baseline_config.json'
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    base_public=base['main'](config_path=config_path,load_layers=False)
    baseline_archive=HERE/'run_records'/base_public.name
    events=read(baseline_archive/'event_parameters.csv')
    pairs=read(baseline_archive/'observation_pairs.csv')
    parameters={t:fit_treatment(events,pairs,t) for t in ('RM','RCC')}
    joint_events=copy.deepcopy(events)
    for e in joint_events:
        p=parameters[e['treatment']]; e.update(C0_mg_L=float(e['C0_mg_L'])*p['alpha'],k_day=p['k'])
    daily=[]; lookup={}
    for r in read(baseline_archive/'daily_simulation.csv'):
        value,status=base['predict'](date.fromisoformat(r['date']),r['treatment'],joint_events,config['event_rule'],config['initial_tn_mg_L'])
        item={'处理':r['treatment'],'日期':r['date'],'文献参数TN_mg_L':float(r['TN_mg_L']),'联合校准TN_mg_L':value}
        daily.append(item); lookup[r['treatment'],r['date']]=item
    for r in pairs:
        d=lookup.get((r['treatment'],r['date']))
        r.update(baseline_TN_mg_L=d['文献参数TN_mg_L'] if d else None,joint_TN_mg_L=d['联合校准TN_mg_L'] if d else None,
                 role_in_trial='首次事件率定' if r['date'] in parameters[r['treatment']]['training_dates'] and r['included_in_metrics']=='True' else '未参与率定')
    scores=make_metrics(base,pairs,parameters,events)
    for name,data in [('observation_pairs',pairs),('daily_comparison',daily),('metrics',scores),('event_parameters',events)]:
        base['write_csv'](archive/(name+'.csv'),data)
    trial=dict(parameters=parameters,calibration_days=CALIBRATION_DAYS,holdout_days=HOLDOUT_DAYS,
               k_bounds=K_BOUNDS,baseline_archive=str(baseline_archive),method='nonnegative alpha profile least squares; concentration-space equal date weights')
    (archive/'joint_calibration.json').write_text(json.dumps(trial,ensure_ascii=False,indent=2),encoding='utf-8')
    for filename in ('observation_source.xlsx','observations_input.csv','nitrogen_input.csv'):
        shutil.copy2(baseline_archive/filename,archive/filename)
    # 源码与参数随本次运行归档，便于回看实际执行版本。
    source_dir=archive/'source'; source_dir.mkdir()
    for name in ('run_joint_point_2022.py','run_point_2022.py','observation_input.py','result_report.py','bounded_k.py'):
        shutil.copy2(HERE/name,source_dir/name)
    public=OUTPUT_DIRECTORY/('2022联合校准_'+run_id); public.mkdir(parents=True)
    export_book(public/'2022联合校准结果.xlsx',parameters,scores,pairs,daily,events,archive,baseline_archive)
    plot(public/'TN联合校准对照.png',parameters,pairs,daily,events,scores)
    manifest=dict(public_output=str(public),baseline_archive=str(baseline_archive),
                  source_sha256={p.name:digest(p) for p in source_dir.iterdir()},
                  output_sha256={p.name:digest(p) for p in public.iterdir()},
                  observation_sha256=digest(archive/'observation_source.xlsx'))
    (archive/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('联合参数：'+json.dumps(parameters,ensure_ascii=False,indent=2))
    print('结果目录：'+str(public)); print('完整记录：'+str(archive))
    return public


if __name__ in ('__main__','__console__'):
    main()
