"""田面与虾沟逐日水量计算；水深单位mm，体积单位m³。"""
import math
import numpy as np

DITCH_B, DITCH_A = 0.9, 1.1667

def vol_per_m(h_mm: float, b: float = DITCH_B, a: float = DITCH_A) -> float:
    h = h_mm / 1000.0
    return b * h + a * h * h


def manage(water, rain, lo, tg, cap, drying):
    """与 drying_control.manage 等价的逐像元版本。"""
    w = water.copy()
    drain = np.zeros_like(w)
    irr = np.zeros_like(w)
    if drying:
        drain = w.copy()
        w[:] = 0.0
        return w, drain, irr
    if tg == 0:
        over = np.maximum(0.0, w - cap)
        drain = over
        w = w - over
        return w, drain, irr
    low = w < lo
    irr[low] = tg - w[low]
    w[low] = tg
    rainmask = (rain > 0) & (w > cap)
    over = np.where(rainmask, w - cap, 0.0)
    w = np.where(rainmask, cap, w)
    norain = (~rainmask) & (rain == 0) & (w > tg)
    over2 = np.where(norain, w - tg, 0.0)
    w = np.where(norain, tg, w)
    drain = over + over2
    return w, drain, irr


def manage_point(water, rain, lower, target, capacity, drying):
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


def point_field_step(previous, rain, et, lower, target, capacity, drying, infiltration=2.0):
    actual_loss = min(previous + rain, et + infiltration)
    result = manage_point(previous + rain - actual_loss, rain, lower, target, capacity, drying)
    result['actual_loss_mm'] = actual_loss
    result['closure_mm'] = previous + rain + result['irrigation'] - actual_loss - result['drain'] - result['water']
    return result


def point_ditch_step(volume, rain, et, field_drain, geometry):
    """按点位几何计算虾沟；田面入沟属系统内部转移。"""
    length,b,a = (geometry[k] for k in ('ditch_length_m','ditch_b','ditch_a'))
    ditch_scale = geometry['RCC_ditch_area_m2']/1000
    field_scale = geometry['RCC_field_area_m2']/1000
    capacity = geometry['ditch_max_depth_mm']/1000
    depth = (-b + math.sqrt(b**2 + 4*a*volume/length)) / (2*a)
    surface = length * (b + 2*a*depth)
    available = volume + rain*ditch_scale + field_drain*field_scale
    loss = min(available, (et+geometry['infiltration_mm_day'])*surface/1000)
    outlet = max(0.0, available-loss-length*(b*capacity+a*capacity*capacity))
    remaining = available-loss-outlet
    return remaining, outlet, volume+rain*ditch_scale+field_drain*field_scale-loss-outlet-remaining


def regional_ditch_step(volume, rain, loss, field_drain, is_rcc,
                        length, total_area, maximum_volume, manage_mm=0.0):
    inflow = field_drain/1000.0 * ((2245.0/3100.0)*total_area)
    depth = np.zeros(len(volume))
    depth[is_rcc] = (-DITCH_B + np.sqrt(DITCH_B**2 + 4*DITCH_A*volume[is_rcc]/length)) / (2*DITCH_A)
    wet_area = length*(DITCH_B+2*DITCH_A*depth)
    available = volume + rain/1000.0*((855.0/3100.0)*total_area) + inflow
    loss_volume = np.minimum(loss/1000.0*wet_area, np.maximum(available, 0.0))
    water = np.maximum(0.0, available-loss_volume)
    water = np.where(is_rcc, water, 0.0)
    if manage_mm > 0:
        target = np.where(rain > 0, maximum_volume, length*vol_per_m(manage_mm))
        outlet = np.maximum(0.0, water-target)
        water = water-outlet
    else:
        outlet = np.maximum(0.0, water-maximum_volume)
        water = np.minimum(water, maximum_volume)
    return water, np.where(is_rcc, outlet, 0.0)
