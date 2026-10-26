"""按终稿V3的田面管理规则计算，并在相同气象输入下对照。"""
from pathlib import Path
from datetime import date, datetime
import ast, json, math, shutil
import run_water_level_2022 as u

HERE = Path(__file__).resolve().parent
SOURCE = u.ROOT / '模型/2026.6.27/python计算/模型验证/终稿/水量平衡验证/2026.4.23稻田水量平衡V3.py'
BASE = HERE / 'water_runs/20261018_212800_730850'
EVAPORATION = 2.0  # 补充蒸发假设，mm/day
SEEPAGE = 2.0     # 下渗假设，mm/day
START, END = '2022-06-05', '2022-09-23'

def main(observation_rows=None, output_prefix='2022原管理规则对照_', observation_label='观测（日期待核）', observation_note='图件观测日期待核。'):
    # 直接提取原文件的两段阈值条件，避免手工抄录日期和水深。
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    blocks = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.lineno in (124, 134):
            blocks[node.lineno] = node
    # 通过顶层分支的第一条赋值识别规则，不依赖固定行号。
    blocks = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.body and isinstance(node.body[0], ast.Assign):
            statement = ast.unparse(node.body[0])
            if '605 <= current_md' in ast.unparse(node.test):
                for t in ('rm', 'rcc'):
                    if statement.startswith(t + '_h_min,'):
                        blocks[t] = compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec')
    assert set(blocks) == {'rm', 'rcc'}
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive = HERE / 'original_water_runs' / stamp
    out = u.OUTPUT / (output_prefix + stamp)
    archive.mkdir(parents=True); out.mkdir()
    weather = u.read(BASE / 'point_weather.csv')
    baseline = {(r['处理'], r['日期']):float(r['模拟田面水深_mm']) for r in u.read(BASE / 'daily_full_precision.csv')}
    rows, lookup = [], {}
    for t in ('RM', 'RCC'):
        h = 0.0
        for r in weather:
            ds = r['date']
            if not START <= ds <= END: continue
            d = date.fromisoformat(ds)
            scope = {'current_md':d.month * 100 + d.day}
            exec(blocks[t.lower()], {}, scope)
            low, target, cap = (float(scope[t.lower() + suffix]) for suffix in ('_h_min','_h_target','_hd_max'))
            p, tr = float(r['rainfall_mm_day']), float(r['transpiration_mm_day'])
            initial = h
            loss = min(h+p, tr+EVAPORATION+SEEPAGE)
            h = max(0.0, h+p-loss)
            irrigation = drain = 0.0
            if target == 0:
                drain, h = h, 0.0
            else:
                if h < low: irrigation, h = target-h, target
                if p > 0 and h > cap: drain, h = h-cap, cap
                elif p == 0 and h > target: drain, h = h-target, target
            balance = initial+p+irrigation-loss-drain-h
            assert abs(balance) < 1e-9
            lookup[t, ds] = h
            rows.append({'处理':t,'日期':ds,'终稿规则水深_mm':h,'区域基准水深_mm':baseline[t,ds],
                         '降雨_mm':p,'蒸腾T_mm':tr,'补充蒸发假设_mm':EVAPORATION,'下渗假设_mm':SEEPAGE,
                         '实际合计耗水_mm':loss,'灌溉_mm':irrigation,'田面出流_mm':drain,
                         '灌水下限_mm':low,'目标水深_mm':target,'蓄水上限_mm':cap,'水量闭合差_mm':balance})
    pairs = []
    for r in (u.read(BASE/'observation_pairs.csv') if observation_rows is None else observation_rows):
        key = r['处理'],r['参考日期']
        if key not in lookup: continue
        pairs.append({'处理':key[0],'参考日期':key[1],'观测水深_mm':float(r['观测水深_mm']),
                      '终稿规则水深_mm':lookup[key],'区域基准水深_mm':baseline[key],'日期依据':r['日期依据']})
    metrics = []
    for t in ('RM','RCC'):
        for period, lo, hi in [('6—7月',START,'2022-07-31'),('8月以后','2022-08-01',END)]:
            groups = {}
            for r in pairs:
                if r['处理']==t and lo <= r['参考日期'] <= hi:
                    groups.setdefault(r['参考日期'],[]).append(r['观测水深_mm'])
            for name, model in [('终稿规则',lookup),('区域基准',baseline)]:
                error = [model[t,ds]-sum(v)/len(v) for ds,v in groups.items()]
                metrics.append({'处理':t,'时段':period,'规则':name,'日期数':len(error),
                                'RMSE_mm':math.sqrt(sum(x*x for x in error)/len(error))})
    u.write(out/'逐日水位与水量.csv',rows,True)
    u.write(out/'观测对照.csv',pairs,True)
    u.write(archive/'daily_full_precision.csv',rows)
    u.write(archive/'metrics.csv',metrics)
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    from matplotlib import rc_context
    import matplotlib.dates as mdates
    with rc_context({'font.family':FontProperties(fname='C:/Windows/Fonts/msyh.ttc').get_name(),'axes.unicode_minus':False}):
        fig=Figure(figsize=(12,7.5));FigureCanvasAgg(fig)
        axes=fig.subplots(2,1)
        fig.subplots_adjust(top=.88,bottom=.14,hspace=.36,left=.08,right=.98)
        for ax,t in zip(axes,('RM','RCC')):
            rs=[r for r in rows if r['处理']==t]; ps=[r for r in pairs if r['处理']==t]
            dates=[date.fromisoformat(r['日期']) for r in rs]
            ax.plot(dates,[r['区域基准水深_mm'] for r in rs],color='#999999',ls='--',label='区域基准规则')
            ax.plot(dates,[r['终稿规则水深_mm'] for r in rs],color='#147c91',lw=1.7,label='原终稿管理规则')
            ax.scatter([date.fromisoformat(r['参考日期']) for r in ps],[r['观测水深_mm'] for r in ps],color='#b17b3f',marker='x',s=24,label=observation_label)
            ax.set_title(t,loc='left');ax.set_ylabel('田面水深（mm）');ax.grid(alpha=.15)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'));ax.set_ylim(bottom=0)
        axes[0].legend(ncol=3,frameon=False,fontsize=9)
        fig.suptitle('2022年田面水深：原终稿管理规则对照',fontsize=16)
        fig.text(.5,.065,'共同输入：逐日降雨、蒸腾T；补充蒸发2 mm/d、下渗2 mm/d。'+observation_note,ha='center',fontsize=10)
        fig.text(.5,.03,'执行终稿V3灌排规则；RCC仅计算田面水深，田面出流进入虾沟。',ha='center',fontsize=10)
        fig.savefig(out/'水位规则对照.png',dpi=170)
    shutil.copy2(__file__,archive/Path(__file__).name)
    shutil.copy2(SOURCE,archive/'original_source.py')
    manifest={'source':str(SOURCE),'source_sha256':u.sha(SOURCE),'weather_sha256':u.sha(BASE/'point_weather.csv'),
              'output':str(out),'metrics':metrics,'initial_depth_mm':0,'supplemental_E_mm_day':EVAPORATION,
              'seepage_mm_day':SEEPAGE,'scope':'field water only; original management with shared forcing; approximate observation dates',
              'max_balance_error':max(abs(r['水量闭合差_mm']) for r in rows)}
    (archive/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    return out, archive

if __name__=='__main__': main()
