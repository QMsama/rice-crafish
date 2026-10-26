"""在文献区间内估计k；固定栅格C0，记录训练日期和留出事件。"""
from datetime import date, timedelta
from collections import defaultdict
import math


def fit_k(points, lower, upper):
    if not 0 < lower < upper:
        raise ValueError('k区间必须为正且下限小于上限')
    def loss(k):
        return sum((c0*math.exp(-k*t)-obs)**2 for c0,t,obs in points)
    # 先全区间网格定位，再在最佳格点邻域精化；显式比较两个边界。
    grid = [lower+(upper-lower)*i/1000 for i in range(1001)]
    i = min(range(len(grid)),key=lambda j:loss(grid[j]))
    lo, hi = grid[max(0,i-1)], grid[min(1000,i+1)]
    for _ in range(80):
        a, b = lo+(hi-lo)/3, hi-(hi-lo)/3
        if loss(a)<loss(b):
            hi=b
        else:
            lo=a
    return min((lower,upper,(lo+hi)/2),key=loss)


def calibrate(events, observations, bounds):
    samples, keys = defaultdict(list), []
    original = {e['stage']:e['k_day'] for e in events}
    for treatment in ('RM','RCC'):
        own = sorted((e for e in events if e['treatment']==treatment),key=lambda e:e['date'])
        event=own[0]
        start=date.fromisoformat(event['response_date'])
        stop=min(start+timedelta(days=6), date.fromisoformat(own[1]['date'])-timedelta(days=1)) if len(own)>1 else start+timedelta(days=6)
        groups=defaultdict(list)
        for r in observations:
            if r['treatment']==treatment and r['date_status']=='printed_tick' and r['date_exact']==r['date'] and r['value_status'] in ('validated_geometry','user_revised_workbook') and start<=date.fromisoformat(r['date'])<=stop:
                groups[r['date']].append(float(r['value']))
        for day, values in sorted(groups.items()):
            samples[event['stage']].append((event['C0_mg_L'],(date.fromisoformat(day)-start).days,sum(values)/len(values)))
            keys.append([treatment,day])
    parameters=[]
    for stage, old in original.items():
        pts=samples[stage]
        lo,hi=bounds[stage]
        enough=len(pts)>=2 and len({p[1] for p in pts})>=2
        k=fit_k(pts,lo,hi) if enough else old
        parameters.append(dict(stage=stage, literature_k=old, calibrated_k=k, lower=lo,upper=hi,
                               n_dates=len(pts), at_bound=abs(k-lo)<1e-8 or abs(k-hi)<1e-8,
                               status='bounded_fit' if enough else 'literature_retained_insufficient_data'))
        for e in events:
            if e['stage']==stage:
                e['k_day']=k
    return dict(parameters=parameters,training_keys=keys,original_k=original,
                method='unweighted concentration SSE on first-event days 1-7; same-day mean; fixed C0',
                interpretation='boundary optimum conditional on fixed C0; not an independently validated local decay constant')


def write_comparison(output,pairs,events,calibration,metrics,write_csv):
    results=[]
    for treatment in ('RM','RCC'):
        own=sorted((e for e in events if e['treatment']==treatment),key=lambda e:e['date'])
        for scope in ('全部评价日期（含率定）','首次事件率定日期','第二次事件前7天留出'):
            rows=[r for r in pairs if r['treatment']==treatment and r['included_in_metrics']]
            if scope=='首次事件率定日期':
                rows=[r for r in rows if r['calibration_role']=='用于k率定']
            elif scope=='第二次事件前7天留出':
                rows=[r for r in rows if len(own)>1 and 0<=(date.fromisoformat(r['date'])-date.fromisoformat(own[1]['response_date'])).days<=6]
            days=sorted({r['date'] for r in rows})
            observed=[sum(float(r['value']) for r in rows if r['date']==d)/sum(r['date']==d for r in rows) for d in days]
            after=[next(r['simulated_TN_mg_L'] for r in rows if r['date']==d) for d in days]
            before=[]
            for d in days:
                e=max((e for e in own if e['response_date']<=d),key=lambda e:e['response_date'])
                before.append(e['C0_mg_L']*math.exp(-calibration['original_k'][e['stage']]*(date.fromisoformat(d)-date.fromisoformat(e['response_date'])).days))
            for label,values in (('时间对齐后文献k',before),('区间率定k',after)):
                results.append(dict(treatment=treatment,scope=scope,parameter_set=label,**metrics(observed,values)))
    write_csv(output/'calibration_comparison.csv',results)
