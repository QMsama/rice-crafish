"""2022点位晒田期控水：停灌并排出当日剩余田面积水。"""
DRYING_PERIODS = {
    'RM': [('2022-06-29','2022-07-01')],
    'RCC': [('2022-07-04','2022-07-14')],
}

def stage_thresholds(treatment, day, original):
    """晒田后按管理表FSI拔节孕穗期标准：下限10、目标40、雨后上限150 mm。"""
    if treatment=='RM' and '2022-07-09'<=day<='2022-07-15':
        return (10.0,40.0,150.0)
    return original


def is_drying(treatment, day):
    return any(start <= day <= end for start,end in DRYING_PERIODS[treatment])


def manage(water, rain, lower, target, capacity, drying):
    """输入为扣除实际耗水后的水深；一步为1日。capacity沿用基准溢流阈值。"""
    if min(water,rain,lower,target,capacity)<0:
        raise ValueError('水量与阈值须非负')
    irrigation=drain=controlled=overflow=0.0
    if drying:
        assert target==0 and lower==0
        controlled=drain=water
        water=0.0
    elif target==0:
        overflow=drain=max(0.0,water-capacity)
        water-=drain
    else:
        if water<lower:irrigation,water=target-water,target
        if rain>0 and water>capacity:
            overflow=drain=water-capacity
            water=capacity
        elif rain==0 and water>target:
            controlled=drain=water-target
            water=target
    return {'water':water,'irrigation':irrigation,'drain':drain,
            'management_drain':controlled,'overflow':overflow}
