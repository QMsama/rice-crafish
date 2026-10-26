"""TN施肥响应、背景、投饵经验项与出口负荷。

RCC沿用田面TN代理沟渠出口浓度；负荷按系统出口水量乘浓度计算。
"""
import math
from datetime import date
import numpy as np

ALPHA = {"RM": 0.17910631036786312, "RCC": 0.18862475682454152}
KDECAY = {"RM": 0.32084970234924104, "RCC": 0.436}
BACKGROUND = 0.38139121394675596
GAMMA = 1.0217016137162531
FEED_KG_DAY = 3.25
PROTEIN = 0.32
SYSTEM_HA = 0.31
FEED_CONC = GAMMA * FEED_KG_DAY * PROTEIN / 6.25 / SYSTEM_HA

COEF = {
    "basal": dict(a0=-21.469, aN=0.841, apH=3.074, aSOM=0.0),
    "tillering": dict(a0=-101.2, aN=0.54, apH=22.184, aSOM=-11.093),
}


def c0_from_grid(N_kg_ha, ph, som, event):
    c = COEF[event["stage"]]
    raw = c["a0"] + c["aN"] * (N_kg_ha * event["frac"]) + c["apH"] * ph + c["aSOM"] * som
    return np.maximum(0.0, raw)



def regional_concentration(treatment, day, size, events, peaks):
    concentration = np.full(size, BACKGROUND)
    if treatment == 'RCC':
        concentration = concentration + FEED_CONC
    active = [j for j, event in enumerate(events[treatment]) if day >= event['response']]
    if active:
        j = active[-1]
        elapsed = (day-events[treatment][j]['response']).days
        concentration = concentration + peaks[treatment, j]*math.exp(-KDECAY[treatment]*elapsed)
    return concentration


def point_concentration(treatment, day, events, parameters):
    active = sorted([e for e in events if e['treatment'] == treatment and e['response_date'] <= day],
                    key=lambda e:e['response_date'])
    background = parameters['background_feed_parameters']['background_mg_L']
    feed = 0.0
    if treatment == 'RCC':
        feed = (parameters['background_feed_parameters']['gamma']*parameters['feed_kg_day']
                *parameters['protein_fraction']/6.25/parameters['system_area_ha'])
    fertilizer = 0.0
    if active:
        event = active[-1]
        c = COEF[event['stage']]
        raw = (c['a0']+c['aN']*float(event['N_kg_ha'])+c['apH']*float(event['pH'])
               +c['aSOM']*float(event['SOM_percent_assumed']))
        peak = parameters['peak_parameters'][treatment]
        elapsed = (date.fromisoformat(day)-date.fromisoformat(event['response_date'])).days
        fertilizer = peak['alpha']*max(0.0, raw)*math.exp(-peak['k']*elapsed)
    # 点位基准累加顺序：背景→投饵→施肥。
    total = background+feed
    total += fertilizer
    return {'fertilizer_mg_L':fertilizer, 'background_mg_L':background,
            'feed_mg_L':feed, 'total_mg_L':total}


def outlet_load_kg(outlet_m3, concentration_mg_L):
    return outlet_m3*concentration_mg_L*.001
