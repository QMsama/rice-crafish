from pathlib import Path
import json
import os
import hashlib

ROOT = Path(os.environ['TN_PROJECT_ROOT']).resolve()
RUN_ROOT = Path(os.environ['TN_SOURCE_AREA_RUN']).resolve()
WORK = RUN_ROOT / 'source_area_map'
os.environ['MPLCONFIGDIR'] = str(WORK / 'mpl-config')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
from osgeo import gdal, ogr, osr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager, patheffects
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

gdal.UseExceptions()
ogr.UseExceptions()
font_path = Path(os.environ.get('TN_SOURCE_AREA_FONT', 'C:/Windows/Fonts/msyh.ttc'))
if font_path.is_file():
    font_manager.fontManager.addfont(str(font_path))
font_family = font_manager.FontProperties(fname=str(font_path)).get_name() if font_path.is_file() else 'DejaVu Sans'
plt.rcParams.update({'font.family': font_family, 'font.size': 12,
                     'axes.unicode_minus': False, 'svg.fonttype': 'none',
                     'text.color': '#25313B', 'axes.edgecolor': '#9CA8AF'})

BASE = ROOT / '模型/2026.9.3/面上推广'
curve = json.loads((WORK.parent / 'load_area_figure/figure_data.json').read_text(encoding='utf-8'))
county = json.loads((WORK / 'agent_county/county_source_statistics.json').read_text(encoding='utf-8'))
template = gdal.Open(str(BASE / 'TN_Load_RM_2022.tif'))
gt, proj = template.GetGeoTransform(), template.GetProjection()
rows, cols = template.RasterYSize, template.RasterXSize
pixel_ha = abs(gt[1] * gt[5] - gt[2] * gt[4]) / 10000
extent = (gt[0], gt[0] + cols * gt[1], gt[3] + rows * gt[5], gt[3])
native_crs = osr.SpatialReference(wkt=proj)
native_crs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
wgs84 = osr.SpatialReference()
wgs84.ImportFromEPSG(4326)
wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
to_map = osr.CoordinateTransformation(wgs84, native_crs)
to_wgs = osr.CoordinateTransformation(native_crs, wgs84)

study_path = Path(os.environ['TN_STUDY_BOUNDARY']) if os.environ.get('TN_STUDY_BOUNDARY') else ROOT / '模型/2026.9.3/模型背景数据/江汉平原矢量/江平原t.shp'
sd = ogr.Open(str(study_path))
sl = sd.GetLayer()
sf = sl.GetFeature(0)
study = sf.GetGeometryRef().Clone()
ssrs = sl.GetSpatialRef().Clone()
ssrs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
if not ssrs.IsSame(native_crs):
    study.Transform(osr.CoordinateTransformation(ssrs, native_crs))
if not study.IsValid():
    study = study.MakeValid()
xmin, xmax, ymin, ymax = study.GetEnvelope()
padding = 6000
limits = (xmin-padding, xmax+padding, ymin-padding, ymax+padding)

cd = ogr.Open(str(WORK / 'agent_county/selected_counties_projected.gpkg'))
cl = cd.GetLayerByName('counties')
assert cl.GetSpatialRef().IsSame(native_crs)
county_geoms = []
county_lookup = {}
for f in cl:
    geom = f.GetGeometryRef().Clone()
    if not geom.Intersects(study):
        continue
    clipped = geom.Intersection(study)
    if clipped.IsEmpty():
        continue
    attrs = f.items()
    county_geoms.append((attrs, clipped))
    county_lookup[attrs['county']] = clipped

def draw_boundary(ax, geom, color, lw, zorder):
    kind = ogr.GT_Flatten(geom.GetGeometryType())
    if kind in [ogr.wkbPolygon, ogr.wkbMultiPolygon]:
        draw_boundary(ax, geom.Boundary(), color, lw, zorder)
    elif kind in [ogr.wkbLineString, ogr.wkbLinearRing]:
        p = np.array(geom.GetPoints())
        if len(p):
            ax.plot(p[:, 0], p[:, 1], color=color, lw=lw, zorder=zorder)
    else:
        for i in range(geom.GetGeometryCount()):
            draw_boundary(ax, geom.GetGeometryRef(i), color, lw, zorder)

palette = ['#FFFFFF', '#D8DEE3', '#F2BD72', '#B72D32']
cmap = ListedColormap(palette)
cmap.set_bad((1, 1, 1, 0))
norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4)
systems = {}
for key in ['RM', 'RCC']:
    ld = gdal.Open(str(BASE / f'TN_Load_{key}_2022.tif'))
    md = gdal.Open(str(BASE / f'TN_TotalMass_{key}_2022.tif'))
    assert ld.GetGeoTransform() == gt and md.GetGeoTransform() == gt
    assert ld.GetProjection() == proj and md.GetProjection() == proj
    raw = ld.ReadAsArray()
    mass = md.ReadAsArray().astype(np.float64)
    valid = np.isfinite(raw) & (raw != ld.GetRasterBand(1).GetNoDataValue())
    assert np.allclose(mass[valid], raw[valid] * pixel_ha, atol=2e-5, rtol=2e-7)
    mean = float(mass[valid].sum() / (valid.sum() * pixel_ha))
    s = np.zeros(raw.shape, dtype=np.float64)
    s[valid] = mass[valid] / pixel_ha / mean
    classes = np.zeros(raw.shape, dtype=np.uint8)
    classes[valid] = 1
    classes[valid & (s > 1)] = 2
    classes[valid & (s > 2)] = 3
    expected = curve['systems'][key]['groups']
    for code, name in [(1, 'other'), (2, 'subcritical'), (3, 'critical')]:
        assert int((classes == code).sum()) == expected[name]['pixel_count']
    assert county['systems'][key]['critical_pixel_count'] == int((classes == 3).sum())
    out = WORK / f'TN_source_class_{key}_2022.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(out), cols, rows, 1, gdal.GDT_Byte,
                                            options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    ds.SetMetadata({'SYSTEM': key, 'PERIOD': '2022-06-05/2022-09-23',
                    'CLASS_1': 'other: s<=1', 'CLASS_2': 'subcritical: 1<s<=2',
                    'CLASS_3': 'critical: s>2', 'MEAN_LOAD_KG_HA': str(mean),
                    'CRITICAL_THRESHOLD_KG_HA': str(2*mean),
                    'SLOPE_DEFINITION': '(pixel_mass/pixel_area)/(system_mass/system_area)',
                    'NODATA': 'outside valid system planted area'})
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(0)
    b.SetDescription('TN source contribution class')
    ct = gdal.ColorTable()
    for i, rgba in enumerate([(255,255,255,0), (216,222,227,255), (242,189,114,255), (183,45,50,255)]):
        ct.SetColorEntry(i, rgba)
    b.SetRasterColorTable(ct)
    b.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    b.WriteArray(classes)
    ds.FlushCache()
    ds = None
    readback = gdal.Open(str(out))
    assert np.array_equal(readback.ReadAsArray(), classes)
    systems[key] = {'classes': classes, 'mean': mean, 'critical_threshold': 2*mean,
                    'path': str(out), 'critical_pixels': int((classes == 3).sum())}

fig = plt.figure(figsize=(15, 10.2), facecolor='white')
axes = [fig.add_axes([0.045, 0.38, 0.435, 0.48]),
        fig.add_axes([0.525, 0.38, 0.435, 0.48])]
fig.text(0.045, 0.968, '江汉平原稻季TN负荷关键源区分布', fontsize=24, fontweight='bold', va='top')
fig.text(0.045, 0.922, '2022年模型情景  |  依据原始像元负荷与县级边界定位', fontsize=14, color='#64717C')
label_names = ['松滋市', '枝江市', '监利市', '仙桃市', '洪湖市', '潜江市', '天门市', '公安县', '石首市', '江陵县']
# Label locations are internal points of the actual clipped county polygons.
label_offsets = {'松滋市': (0, -6000), '枝江市': (-3500, 2000), '公安县': (0, -3000),
                 '仙桃市': (0, 4500), '洪湖市': (2000, -4500), '潜江市': (0, 2500),
                 '江陵县': (0, 1000), '监利市': (0, -1000)}
title_colors = {'RM': '#226FA0', 'RCC': '#CF7832'}
display_names = {'RM': '水稻单作', 'RCC': '稻虾共作'}

for panel, (ax, key) in enumerate(zip(axes, ['RM', 'RCC'])):
    classes = systems[key]['classes']
    ax.imshow(np.ma.masked_equal(classes, 0), extent=extent, origin='upper', cmap=cmap,
              norm=norm, interpolation='nearest', zorder=2)
    for attrs, geom in county_geoms:
        draw_boundary(ax, geom, '#B0B8BD', 0.40, 3)
    draw_boundary(ax, study, '#46545E', 0.85, 4)
    top = county['systems'][key]['top5_by_critical_mass'][:3]
    top_names = {r['county'] for r in top}
    for name in label_names:
        if name not in county_lookup:
            continue
        p = county_lookup[name].PointOnSurface()
        dx, dy = label_offsets.get(name, (0, 0))
        is_top = name in top_names
        txt = ax.text(p.GetX()+dx, p.GetY()+dy, name,
                      fontsize=10.8 if is_top else 9.5,
                      color='#8C1C25' if is_top else '#58666F',
                      fontweight='bold' if is_top else 'normal', ha='center', va='center', zorder=8)
        txt.set_path_effects([patheffects.withStroke(linewidth=2.8, foreground='white', alpha=0.95)])
    # True-north direction at a position inside this projected map.
    nx, ny = xmax-14000, ymax-46000
    lon, lat, _ = to_wgs.TransformPoint(nx, ny)
    x2, y2, _ = to_map.TransformPoint(lon, lat+0.15)
    vec = np.array([x2-nx, y2-ny]); vec = vec / np.linalg.norm(vec) * 18000
    ax.annotate('', xy=(nx+vec[0], ny+vec[1]), xytext=(nx, ny),
                arrowprops={'arrowstyle': '-|>', 'color': '#364650', 'lw': 1.1}, zorder=9)
    ax.text(nx+vec[0], ny+vec[1]+4500, 'N', ha='center', va='bottom', fontsize=12, zorder=9)
    sx, sy, length = xmin+12000, ymin+9000, 50000
    ax.plot([sx, sx+length], [sy, sy], color='#354650', lw=2, zorder=9)
    for xx in [sx, sx+length/2, sx+length]:
        ax.plot([xx, xx], [sy-1800, sy+1800], color='#354650', lw=1, zorder=9)
    ax.text(sx, sy-4500, '0', ha='center', va='top', fontsize=9)
    ax.text(sx+length, sy-4500, '50 km', ha='center', va='top', fontsize=9)
    ax.set_xlim(limits[0], limits[1]); ax.set_ylim(limits[2], limits[3])
    ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    bx = ax.get_position()
    fig.text(bx.x0, 0.875, f'{chr(97+panel)}  {key}  {display_names[key]}', fontsize=18,
             fontweight='bold', color=title_colors[key])
    fig.text(bx.x0, 0.348, f'关键阈值：TN负荷 > {systems[key]["critical_threshold"]:.2f} kg/ha',
             fontsize=12, color='#8C1C25')
    fig.text(bx.x0, 0.312, '主要县市              关键区面积             占本模式关键区负荷', fontsize=11.2, color='#687580')
    for i, row in enumerate(top):
        yy = 0.277-i*0.033
        fig.text(bx.x0, yy, row['county'], fontsize=12, fontweight='bold', color='#354650')
        fig.text(bx.x0+0.130, yy, f'{row["critical_area_km2"]:.2f} km²', fontsize=12)
        fig.text(bx.x0+0.280, yy, f'{row["share_of_regional_critical_mass_pct"]:.2f}%', fontsize=12, color='#8C1C25')

legend = [Patch(facecolor=palette[3], label='关键源区  s > 2'),
          Patch(facecolor=palette[2], label='次关键源区  1 < s ≤ 2'),
          Patch(facecolor=palette[1], label='其他有效种植区  s ≤ 1')]
fig.legend(handles=legend, loc='center left', bbox_to_anchor=(0.038, 0.143),
           frameon=False, ncol=3, fontsize=12, columnspacing=2.0)
fig.text(0.045, 0.096, '识别单元：约213 m原始像元；各模式独立归一化。红色表示县内满足阈值的具体种植像元。',
         fontsize=11.2, color='#65737E')
fig.text(0.045, 0.064, '县市统计按像元中心点归属；“关键区负荷占比”的分母为本模式全域关键区TN输出总量。',
         fontsize=11.2, color='#65737E')
fig.text(0.045, 0.032, '范围：2022-06-05至09-23田块系统出口TN负荷；县级边界采用项目现有2024版资料作为位置参照。',
         fontsize=11.2, color='#65737E')
png = WORK / '江汉平原2022年TN关键源区分布.png'
svg = WORK / '江汉平原2022年TN关键源区分布.svg'
fig.savefig(png, dpi=250, facecolor='white')
fig.savefig(svg, facecolor='white')
plt.close(fig)
audit = {'map': str(png), 'editable_map': str(svg), 'native_grid': {'geotransform': gt, 'rows': rows, 'cols': cols, 'pixel_area_ha': pixel_ha},
         'outputs': {k: {n:v for n,v in val.items() if n!='classes'} for k,val in systems.items()},
         'county_coverage_pct': {k:county['systems'][k]['coverage_pct'] for k in ['RM', 'RCC']},
         'source_curve_sha256': hashlib.sha256((WORK.parent/'load_area_figure/figure_data.json').read_bytes()).hexdigest()}
(WORK/'map_verification.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2),encoding='utf-8')
print(json.dumps(audit,ensure_ascii=False,indent=2))
