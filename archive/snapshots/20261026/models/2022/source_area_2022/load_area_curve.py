from pathlib import Path
import csv
import hashlib
import json
import os

ROOT = Path(os.environ['TN_PROJECT_ROOT']).resolve()
RUN_ROOT = Path(os.environ['TN_SOURCE_AREA_RUN']).resolve()
WORK = RUN_ROOT / 'load_area_figure'
WORK.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = str(WORK / 'mpl-config')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
from osgeo import gdal, osr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter, MultipleLocator
from matplotlib.patches import Patch

gdal.UseExceptions()
font_path = Path(os.environ.get('TN_SOURCE_AREA_FONT', 'C:/Windows/Fonts/msyh.ttc'))
if font_path.is_file():
    font_manager.fontManager.addfont(str(font_path))
font_family = font_manager.FontProperties(fname=str(font_path)).get_name() if font_path.is_file() else 'DejaVu Sans'
plt.rcParams.update({
    'font.family': font_family, 'font.size': 13,
    'axes.unicode_minus': False, 'svg.fonttype': 'none',
    'axes.edgecolor': '#66717C', 'axes.labelcolor': '#25313B',
    'xtick.color': '#46535F', 'ytick.color': '#46535F',
    'text.color': '#25313B', 'axes.linewidth': 0.9,
    'pdf.fonttype': 42,
})

BASE = ROOT / '模型/2026.9.3/面上推广'
summary = {
    'period': ['2022-06-05', '2022-09-23'],
    'scope': '2022 fixed-management model scenario; each system uses its own valid planted area',
    'sorting': 'descending seasonal unit-area TN load',
    'classification': 'empirical local slope s=(mass/area)/(total_mass/total_area); s>2 critical; 1<s<=2 subcritical; s<=1 other',
    'systems': {},
}
series = {}

for key in ['RM', 'RCC']:
    paths = {kind: BASE / f'TN_{kind}_{key}_2022.tif' for kind in ['Load', 'TotalMass']}
    ld = gdal.Open(str(paths['Load']))
    md = gdal.Open(str(paths['TotalMass']))
    assert ld.GetGeoTransform() == md.GetGeoTransform()
    assert ld.GetProjection() == md.GetProjection()
    crs = osr.SpatialReference(wkt=ld.GetProjection())
    assert crs.IsProjected() and abs(crs.GetLinearUnits() - 1) < 1e-12
    gt = ld.GetGeoTransform()
    area = abs(gt[1] * gt[5] - gt[2] * gt[4]) / 10000
    lb, mb = ld.GetRasterBand(1), md.GetRasterBand(1)
    load, mass = lb.ReadAsArray(), mb.ReadAsArray()
    valid = np.isfinite(load) & (load != lb.GetNoDataValue())
    valid_mass = np.isfinite(mass) & (mass != mb.GetNoDataValue())
    assert np.array_equal(valid, valid_mass)
    load = load[valid].astype(np.float64)
    mass = mass[valid].astype(np.float64)
    assert np.all(load >= 0) and np.all(mass >= 0)
    assert np.allclose(mass, load * area, rtol=2e-7, atol=2e-5)
    order = np.argsort(-load, kind='stable')
    load, mass = load[order], mass[order]
    n, total_mass = len(load), float(mass.sum())
    total_area = n * area
    mean_load = total_mass / total_area
    x = np.arange(n + 1, dtype=float) / n * 100
    y = np.r_[0, np.cumsum(mass)] / total_mass * 100
    assert np.all(np.diff(x) > 0) and np.all(np.diff(y) >= 0)
    assert np.isclose(x[-1], 100) and np.isclose(y[-1], 100)
    slopes = mass / area / mean_load
    masks = {'critical': slopes > 2, 'subcritical': (slopes > 1) & (slopes <= 2), 'other': slopes <= 1}
    groups = {}
    for name, selected in masks.items():
        groups[name] = {
            'pixel_count': int(selected.sum()),
            'area_km2': float(selected.sum() * area / 100),
            'area_pct': float(selected.sum() / n * 100),
            'mass_t': float(mass[selected].sum() / 1000),
            'mass_pct': float(mass[selected].sum() / total_mass * 100),
        }
    assert sum(v['pixel_count'] for v in groups.values()) == n
    assert np.isclose(sum(v['mass_pct'] for v in groups.values()), 100)
    c2 = int(masks['critical'].sum())
    c1 = c2 + int(masks['subcritical'].sum())
    top = {str(p): float(np.interp(p, x, y)) for p in [5, 10, 20, 30, 50]}
    info = {
        'n': n, 'pixel_area_ha': area, 'area_km2': total_area / 100,
        'total_mass_t': total_mass / 1000, 'mean_load_kg_ha': mean_load,
        'slope_threshold_load_kg_ha': {'s1': mean_load, 's2': 2 * mean_load},
        'top_area_pct_mass_contribution': top,
        'groups': groups,
        'sources': {kind: {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for kind, p in paths.items()},
    }
    summary['systems'][key] = info
    series[key] = (x, y, c2, c1)
    with (WORK / f'{key}_curve.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['cumulative_area_pct', 'cumulative_TN_mass_pct'])
        for p in np.linspace(0, 100, 1001):
            writer.writerow([f'{p:.1f}', f'{np.interp(p, x, y):.10f}'])

fig, axes = plt.subplots(1, 2, figsize=(13.8, 8.3), sharex=True, sharey=True)
fig.subplots_adjust(left=0.078, right=0.974, top=0.795, bottom=0.295, wspace=0.18)
colors = {'RM': '#226FA0', 'RCC': '#CF7832'}
names = {'RM': '水稻单作', 'RCC': '稻虾共作'}

fig.text(0.078, 0.945, '2022年稻季TN负荷的面积贡献曲线', fontsize=23, fontweight='bold', va='top')
fig.text(0.078, 0.887, '各模式分别按单位面积TN负荷从高到低累计', fontsize=14, color='#5D6A75')

for p, (ax, key) in enumerate(zip(axes, ['RM', 'RCC'])):
    color = colors[key]
    x, y, c2, c1 = series[key]
    info = summary['systems'][key]
    ax.set_axisbelow(True)
    ax.grid(axis='both', color='#E8EDF0', linewidth=0.7)
    ax.spines[['top', 'right']].set_visible(False)
    ax.plot([0, 100], [0, 100], color='#9CA7AF', linewidth=1.2, linestyle=(0, (4, 4)), zorder=1)
    ax.axvspan(0, x[c2], color=color, alpha=0.18, lw=0, zorder=0)
    ax.axvspan(x[c2], x[c1], color=color, alpha=0.065, lw=0, zorder=0)
    # Every native-pixel cumulative point is retained in the plotted curve.
    ax.plot(x, y, color=color, lw=2.5, zorder=3)
    for boundary in [c2, c1]:
        ax.plot([x[boundary], x[boundary]], [0, y[boundary]], color=color, alpha=0.65, lw=0.9, linestyle=(0, (2, 3)), zorder=2)
        ax.scatter([x[boundary]], [y[boundary]], s=41, marker='s', facecolor='white', edgecolor=color, linewidth=1.5, zorder=5)
    y10 = info['top_area_pct_mass_contribution']['10']
    ax.plot([10, 10], [0, y10], color='#52616D', lw=0.9, linestyle=(0, (3, 3)), zorder=2)
    ax.scatter([10], [y10], s=57, color=color, edgecolor='white', linewidth=1.0, zorder=6)
    ax.annotate(f'最高10%面积\n贡献 {y10:.2f}% TN负荷', xy=(10, y10), xytext=(27, y10 + 17),
                fontsize=12.2, color=color, ha='left', va='center',
                arrowprops={'arrowstyle': '->', 'color': color, 'lw': 1.0,
                            'connectionstyle': 'arc3,rad=0.10'},
                bbox={'boxstyle': 'round,pad=0.3', 'fc': 'white', 'ec': 'none', 'alpha': 0.94})
    ax.text(0, 1.08, f'{chr(97+p)}  {key}  {names[key]}', transform=ax.transAxes, fontsize=17, fontweight='bold', color=color)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_locator(MultipleLocator(20))
    ax.yaxis.set_major_locator(MultipleLocator(20))
    ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.tick_params(labelsize=12, length=4, pad=7)
    ax.set_xlabel('累计种植面积占比', labelpad=12, fontsize=14)
    if p == 0:
        ax.set_ylabel('累计TN负荷贡献', labelpad=12, fontsize=14)
    crit, sub = info['groups']['critical'], info['groups']['subcritical']
    box = ax.get_position()
    fig.text(box.x0, 0.184, f'关键源区   {crit["area_pct"]:.2f}%面积 → {crit["mass_pct"]:.2f}%负荷', color=color, fontsize=12.3, fontweight='bold')
    fig.text(box.x0, 0.141, f'次关键源区   {sub["area_pct"]:.2f}%面积 → {sub["mass_pct"]:.2f}%负荷', color='#53616D', fontsize=12)

handles = [Patch(facecolor='#AAB7C2', alpha=0.58, edgecolor='none', label='关键源区  s > 2'),
           Patch(facecolor='#DCE3E8', edgecolor='none', label='次关键源区  1 < s ≤ 2'),
           plt.Line2D([0], [0], color='#9CA7AF', lw=1.2, linestyle=(0, (4, 4)), label='均匀贡献参照线')]
fig.legend(handles=handles, loc='center left', bbox_to_anchor=(0.075, 0.089), frameon=False, ncol=3, fontsize=11.5, columnspacing=2.2)
fig.text(0.078, 0.043, '分区依据：经验曲线局部斜率 s = 单位面积负荷 / 本模式面积加权平均负荷；各模式独立归一化。', fontsize=10.7, color='#697783')
fig.text(0.078, 0.014, '统计范围：2022-06-05至09-23模型情景；10%贡献由曲线插值，分区面积按完整有效像元计算。', fontsize=10.7, color='#697783')

png = WORK / '2022年TN负荷_面积贡献曲线.png'
svg = WORK / '2022年TN负荷_面积贡献曲线.svg'
fig.savefig(png, dpi=260, facecolor='white')
fig.savefig(svg, facecolor='white')
plt.close(fig)
(WORK / 'figure_data.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'figure': str(png), 'editable': str(svg), 'systems': {k: {'top10': v['top_area_pct_mass_contribution']['10'], 'groups': v['groups']} for k,v in summary['systems'].items()}}, ensure_ascii=False, indent=2))
