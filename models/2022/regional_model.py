"""区域逐日水量、田面TN代理浓度和系统外排负荷计算。
按年度配置运行，输入检查、缓存和输出由本模块统一管理。
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import csv
import json
import math
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from water_balance import vol_per_m, manage, regional_ditch_step
from water_quality import (ALPHA, KDECAY, BACKGROUND, FEED_CONC,
                           c0_from_grid, regional_concentration)
from osgeo import gdal, osr
import numpy as np

gdal.UseExceptions()

ROOT = Path(r"E:\#岑俊毅\2.论文\2.稻虾综合种养")
BASE = ROOT / "模型/2026.9.3/模型背景数据"
POINTRUN = ROOT / ".codex-work/qgis_point_2022/et_recompute_runs/20261022_213821"
HERE = ROOT / ".codex-work/regional_reproduction"

START = date(2022, 6, 5)
END = date(2022, 9, 23)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]

# --- 点位参数（来自 2026-10-22 运行）---

EVENTS = {
    "RM": [
        dict(date=date(2022, 6, 18), response=date(2022, 6, 19), stage="tillering", frac=0.6),
        dict(date=date(2022, 7, 6), response=date(2022, 7, 7), stage="tillering", frac=0.4),
    ],
    "RCC": [
        dict(date=date(2022, 6, 13), response=date(2022, 6, 14), stage="basal", frac=0.6),
        dict(date=date(2022, 6, 25), response=date(2022, 6, 26), stage="tillering", frac=0.4),
    ],
}

# --- 区域几何（Rice_2021 模板）---
PIXEL_HA = 4.554342663494959
A_TOTAL = PIXEL_HA * 10000.0
RCC_PADDY_FRAC = 2245.0 / 3100.0
RCC_DITCH_FRAC = 855.0 / 3100.0
DITCH_L_PER_HA = 285.0 / 0.31
DITCH_L = DITCH_L_PER_HA * PIXEL_HA
DITCH_B, DITCH_A = 0.9, 1.1667
DITCH_H0_MM, DITCH_HMAX_MM = 800.0, 900.0
INFIL_MM = 2.0
STORM_DRAIN = False  # 区域沿用点位规则，不额外加暴雨阈值




V_INIT = DITCH_L * vol_per_m(DITCH_H0_MM)
V_MAX = DITCH_L * vol_per_m(DITCH_HMAX_MM)


def warp_to_mask(path: Path, gt, cols, rows, proj, src_nodata=None):
    kwargs = dict(
        format="MEM",
        outputBounds=[gt[0], gt[3] + gt[5] * rows, gt[0] + gt[1] * cols, gt[3]],
        width=cols,
        height=rows,
        dstSRS=proj,
        resampleAlg=gdal.GRA_Bilinear,
        dstNodata=float("nan"),
    )
    if src_nodata is not None:
        kwargs["srcNodata"] = src_nodata
    ds = gdal.Warp("", str(path), **kwargs)
    if ds is None:
        raise RuntimeError(f"warp failed: {path}")
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    ds = None
    return arr


def read_thresholds(days):
    """读取基准逐日阈值；年份配置可覆盖指定日期。"""
    p = POINTRUN / "daily_full_precision.csv"
    table = {}
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = date.fromisoformat(r["日期"])
            table[(r["处理"], d.month, d.day)] = (
                float(r["灌水下限_mm"]),
                float(r["目标水深_mm"]),
                float(r["蓄水上限_mm"]),
                int(r["晒田期"]) == 1,
            )
    for t in ("RM", "RCC"):
        keys = sorted(k for k in table if k[0] == t)
        base = table[keys[0]]
        for d in days:
            table.setdefault((t, d.month, d.day), base)
    return table






def build_cache(mask_ds, mask, valid_idx, days, cache_path: Path):
    if cache_path.exists():
        z = np.load(cache_path)
        return z["rain"], z["et"]
    gt = mask_ds.GetGeoTransform()
    cols, rows = mask_ds.RasterXSize, mask_ds.RasterYSize
    proj = mask_ds.GetProjection()
    n = valid_idx.size
    rain = np.zeros((len(days), n), dtype=np.float32)
    et = np.zeros((len(days), n), dtype=np.float32)
    t0 = time.time()
    for i, d in enumerate(days):
        doy = d.timetuple().tm_yday
        rp = BASE / f"rain daily tiff/{YEAR}/PRE_{YEAR}_Day_{doy:03d}.tif"
        ep = BASE / f"蒸散发/ET_{YEAR}_daily_tiff/ET_{YEAR}{doy:03d}.tif"
        ra = warp_to_mask(rp, gt, cols, rows, proj, src_nodata=-9999.0).ravel()[valid_idx]
        ea = warp_to_mask(ep, gt, cols, rows, proj, src_nodata=0.0).ravel()[valid_idx]
        rain[i] = np.nan_to_num(ra, nan=0.0)
        et[i] = np.nan_to_num(ea, nan=0.0) / 1000.0
        if i % 10 == 0:
            print(f"  cache {i + 1}/{len(days)} {d} rain_mean={rain[i].mean():.2f} et_mean={et[i].mean():.2f} {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(cache_path, rain=rain, et=et)
    return rain, et


def calculate(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--c0", choices=["grid", "fixed"], default="grid")
    ap.add_argument("--no-rain-drain", action="store_true", help="两个处理都关闭无雨日退水")
    ap.add_argument("--rm-no-drain", action="store_true", help="仅 RM 关闭无雨日退水（RCC 保持正常）")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个像元（冒烟测试）")
    ap.add_argument("--rebuild-cache", action="store_true")
    ap.add_argument("--ditch-h0", type=float, default=800.0, help="沟渠初始水深 mm（敏感性）")
    ap.add_argument("--ditch-cap", type=float, default=0.0, help="沟渠管理水位 mm；>0 时超过即主动外排")
    ap.add_argument("--ditch-manage", type=float, default=0.0, help="常规沟水位 mm；雨日可蓄至上限，无雨日排回该水位")
    ap.add_argument("--rm-daily-cap", type=float, default=0.0, help="RM 单日最大外排 mm；>0 时限制暴雨排水")
    ap.add_argument("--rm-bund", type=float, default=0.0, help="RM 田埂溢流高程 mm；>0 时雨日按该高程溢流而非管理上限")
    ap.add_argument("--year", type=int, default=2022)
    ap.add_argument("--start", default="2022-06-05")
    ap.add_argument("--days", type=int, default=111)
    ap.add_argument("--rcc-events", default="", help="RCC 施肥日，逗号分隔")
    ap.add_argument("--rcc-calendar", action="store_true", help="按图 2-4：RCC 晒田 7/3-7/4，7/5-7/14 用 10/30/100")
    ap.add_argument("--rm-calendar", action="store_true", help="按图 2-4：RM 晒田 7/3-7/4，6/29-7/2 用 30/50/100")
    ap.add_argument("--cache-file", required=True)
    args = ap.parse_args(argv)
    global V_INIT, DAYS, YEAR, START, END
    YEAR = args.year
    global EVENTS
    EVENTS = {k: [dict(date=date(YEAR, e["date"].month, e["date"].day),
                      response=date(YEAR, e["response"].month, e["response"].day),
                      stage=e["stage"], frac=e["frac"]) for e in v] for k, v in EVENTS.items()}
    if args.rcc_events:
        _ds = [date.fromisoformat(x.strip()) for x in args.rcc_events.split(",")]
        EVENTS["RCC"] = [dict(date=d, response=d + timedelta(days=1), stage="tillering", frac=f)
                         for d, f in zip(_ds, (0.6, 0.4))]
    START = date.fromisoformat(args.start)
    END = START + timedelta(days=args.days - 1)
    DAYS = [START + timedelta(days=i) for i in range(args.days)]
    V_INIT = DITCH_L * vol_per_m(args.ditch_h0)
    if args.ditch_cap > 0:
        global V_MAX
        V_MAX = DITCH_L * vol_per_m(args.ditch_cap)
        V_INIT = V_MAX

    stamp = time.strftime("%Y%m%d_%H%M%S")
    tag = args.tag or f"c0{args.c0}" + ("_nodrain" if args.no_rain_drain else "") + ("_rmnodrain" if args.rm_no_drain else "")
    run = HERE / f"run_{stamp}_{tag}_{uuid.uuid4().hex[:6]}"
    run.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_file)
    cache.parent.mkdir(parents=True, exist_ok=True)

    mask_ds = gdal.Open(str(BASE / "rice_crayfish/Rice_2021.tif"))
    mask = mask_ds.GetRasterBand(1).ReadAsArray()
    gt = mask_ds.GetGeoTransform()
    cols, rows = mask_ds.RasterXSize, mask_ds.RasterYSize
    proj = mask_ds.GetProjection()
    valid = (mask == 1) | (mask == 3)
    valid_idx = np.flatnonzero(valid)
    if args.limit:
        valid_idx = valid_idx[: args.limit]
    is_rm = mask.ravel()[valid_idx] == 1
    is_rcc = mask.ravel()[valid_idx] == 3
    n = valid_idx.size
    print(f"valid pixels: {n} (RM {is_rm.sum()}, RCC {is_rcc.sum()})")

    if args.rebuild_cache and cache.exists():
        raise ValueError("请使用新的缓存路径；已有缓存保留。")
    rain, et = build_cache(mask_ds, mask, np.flatnonzero(valid), DAYS, cache)
    if args.limit:
        rain, et = rain[:, : args.limit], et[:, : args.limit]

    # 静态栅格
    nfer = warp_to_mask(BASE / "nitrogen_fertilizer_use/Nfer-2018", gt, cols, rows, proj).ravel()[valid_idx]
    ph = warp_to_mask(BASE / "soil/Environmental Date_pH.tif", gt, cols, rows, proj, src_nodata=3.4e38).ravel()[valid_idx]
    som = warp_to_mask(BASE / "soil/Environmental Data_SOM.tif", gt, cols, rows, proj, src_nodata=1.79e308).ravel()[valid_idx]
    nfer = np.nan_to_num(nfer, nan=np.nanmedian(nfer)) * 10.0
    ph = np.where((ph > 3) & (ph < 11), ph, np.nanmedian(ph[(ph > 3) & (ph < 11)]))
    som = np.where((som > 0.05) & (som < 20), som, np.nanmedian(som[(som > 0.05) & (som < 20)]))
    print(f"Nfer kg/ha p5={np.percentile(nfer, 5):.1f} p50={np.percentile(nfer, 50):.1f} p95={np.percentile(nfer, 95):.1f}")

    # C0
    c0 = {}
    for t in ("RM", "RCC"):
        for j, ev in enumerate(EVENTS[t]):
            key = (t, j)
            if args.c0 == "grid":
                c0[key] = ALPHA[t] * c0_from_grid(nfer, ph, som, ev)
            else:
                # 固定为点位像元值（用中位数近似点位）
                c0[key] = np.full(n, ALPHA[t] * float(np.median(c0_from_grid(nfer, ph, som, ev))))

    thresholds = read_thresholds(DAYS)
    if args.rcc_calendar:
        for _k in list(thresholds):
            if _k[0] != "RCC":
                continue
            _m, _d = _k[1], _k[2]
            if (_m, _d) in ((7, 3), (7, 4)):
                thresholds[_k] = (0.0, 0.0, 0.0, True)
            elif _m == 7 and _d <= 14:
                thresholds[_k] = (10.0, 30.0, 100.0, False)
    if args.rm_calendar:
        for _k in list(thresholds):
            if _k[0] != "RM":
                continue
            _m, _d = _k[1], _k[2]
            if (_m, _d) in ((6, 29), (6, 30), (7, 1), (7, 2)):
                thresholds[_k] = (30.0, 50.0, 100.0, False)
            elif (_m, _d) in ((7, 3), (7, 4)):
                thresholds[_k] = (0.0, 0.0, 0.0, True)

    h_rm = np.zeros(n, dtype=np.float64)
    h_rcc = np.zeros(n, dtype=np.float64)
    v_d = np.zeros(n, dtype=np.float64)
    v_d[is_rcc] = V_INIT
    load_rm = np.zeros(n, dtype=np.float64)
    load_rcc = np.zeros(n, dtype=np.float64)
    drain_rm_tot = np.zeros(n, dtype=np.float64)
    outlet_rcc_tot = np.zeros(n, dtype=np.float64)

    def conc(t, d):
        return regional_concentration(t, d, n, EVENTS, c0)

    t0 = time.time()
    ledger = []
    for i, d in enumerate(DAYS):
        P = rain[i]
        E = et[i]
        loss = E + INFIL_MM
        # --- RM ---
        lo, tg, cap, dry = thresholds[("RM", d.month, d.day)]
        w = np.maximum(0.0, h_rm + P - loss)
        rm_cap = max(cap, args.rm_bund) if args.rm_bund > 0 else cap
        if (args.no_rain_drain or args.rm_no_drain) and (not dry) and tg > 0:
            # 对照：无雨日不主动退水，只在雨日超上限时排水
            low = w < lo
            w = np.where(low, tg, w)
            capm = (P > 0) & (w > rm_cap)
            dr = np.where(capm, w - rm_cap, 0.0)
            w = np.where(capm, rm_cap, w)
            irr = np.where(low, tg - (np.maximum(0.0, h_rm + P - loss)), 0.0)
        elif args.rm_bund > 0 and (not dry) and tg > 0:
            low = w < lo
            w = np.where(low, tg, w)
            capm = (P > 0) & (w > rm_cap)
            dr = np.where(capm, w - rm_cap, 0.0)
            w = np.where(capm, rm_cap, w)
        else:
            w, dr, irr = manage(w, P, lo, tg, cap, dry)
        h_rm = np.where(is_rm, w, h_rm)
        dr = np.where(is_rm, dr, 0.0)
        if args.rm_daily_cap > 0 and not dry:
            dr = np.minimum(dr, args.rm_daily_cap)
        drain_rm_tot += dr
        rm_inc = 0.01 * dr * conc("RM", d)
        load_rm += rm_inc
        rm_drain_day = (dr / 1000.0 * A_TOTAL).sum()

        # --- RCC 田面 ---
        lo, tg, cap, dry = thresholds[("RCC", d.month, d.day)]
        w = np.maximum(0.0, h_rcc + P - loss)
        if args.no_rain_drain and (not dry) and tg > 0:
            low = w < lo
            w = np.where(low, tg, w)
            capm = (P > 0) & (w > cap)
            dr = np.where(capm, w - cap, 0.0)
            w = np.where(capm, cap, w)
        else:
            w, dr, irr = manage(w, P, lo, tg, cap, dry)
        h_rcc = np.where(is_rcc, w, h_rcc)
        dr = np.where(is_rcc, dr, 0.0)

        # --- 沟渠 ---
        v_d, outlet = regional_ditch_step(
            v_d, P, loss, dr, is_rcc, DITCH_L, A_TOTAL, V_MAX, args.ditch_manage)
        outlet_rcc_tot += outlet
        rcc_inc = 10.0 * outlet * conc("RCC", d) / A_TOTAL
        load_rcc += rcc_inc
        ledger.append(dict(
            date=d.isoformat(),
            rm_drain_m3=float(rm_drain_day),
            rm_load_kg=float((rm_inc * PIXEL_HA).sum()),
            rcc_out_m3=float(outlet.sum()),
            rcc_load_kg=float((rcc_inc * PIXEL_HA).sum()),
        ))

        if i % 15 == 0:
            print(f"  {d} RM_load={load_rm[is_rm].mean():.3f} RCC_load={load_rcc[is_rcc].mean():.3f} "
                  f"RM_drain={drain_rm_tot[is_rm].mean():.1f}mm {time.time() - t0:.0f}s", flush=True)

    # --- 汇总 ---
    with open(run / "逐日区域账本.csv", "w", encoding="utf-8-sig", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=list(ledger[0]))
        wcsv.writeheader()
        wcsv.writerows(ledger)
    area_ha = PIXEL_HA
    res = {}
    for name, load, sel in (("RM", load_rm, is_rm), ("RCC", load_rcc, is_rcc)):
        v = load[sel]
        res[name] = dict(
            pixels=int(sel.sum()),
            area_ha=float(sel.sum() * area_ha),
            mean_kg_ha=float(v.mean()),
            median_kg_ha=float(np.median(v)),
            p5=float(np.percentile(v, 5)),
            p95=float(np.percentile(v, 95)),
            max_kg_ha=float(v.max()),
            total_kg=float((v * area_ha).sum()),
            total_t=float((v * area_ha).sum() / 1000.0),
            zero_frac=float((v == 0).mean()),
        )
        if name == "RM":
            res[name]["mean_drain_mm"] = float(drain_rm_tot[sel].mean())
        else:
            res[name]["mean_outlet_m3_per_pixel"] = float(outlet_rcc_tot[sel].mean())
            res[name]["mean_outlet_mm"] = float(outlet_rcc_tot[sel].mean() / A_TOTAL * 1000)
    res["meta"] = dict(
        start=str(START), end=str(END), days=len(DAYS), c0=args.c0,
        no_rain_drain=args.no_rain_drain, rm_no_drain=args.rm_no_drain, pixel_ha=PIXEL_HA,
        ditch_L_m=DITCH_L, V_init=V_INIT, V_max=V_MAX, feed_conc_mg_L=FEED_CONC,
        alpha=ALPHA, k=KDECAY, background=BACKGROUND,
    )

    res["meta"]["arguments"] = vars(args)
    res["meta"]["events"] = {t: [{k: str(v) if isinstance(v, date) else v for k,v in e.items()} for e in evs] for t,evs in EVENTS.items()}

    # 点位像元校验
    lon, lat = 112.6166, 30.3833
    src = osr.SpatialReference(wkt=proj)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(dst, src)
    x, y = ct.TransformPoint(lon, lat)[:2]
    col = int((x - gt[0]) / gt[1])
    row = int((y - gt[3]) / gt[5])
    pid = np.flatnonzero(valid_idx == row * cols + col)
    if pid.size:
        k = pid[0]
        res["point_pixel"] = dict(
            row=row, col=col, class_=int(mask[row, col]),
            load_rm_kg_ha=float(load_rm[k]), load_rcc_kg_ha=float(load_rcc[k]),
            N_kg_ha=float(nfer[k]), pH=float(ph[k]), SOM=float(som[k]),
        )
        print("point pixel:", res["point_pixel"])
    else:
        res["point_pixel"] = None

    with open(run / "summary.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    # 导出栅格
    for name, load, sel in (("RM", load_rm, is_rm), ("RCC", load_rcc, is_rcc)):
        full = np.full(mask.shape, -9999.0, dtype=np.float32)
        full.ravel()[valid_idx[sel]] = load[sel]
        out = run / f"TN_Load_{name}_{YEAR}_{tag}.tif"
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(str(out), cols, rows, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-9999.0)
        b.WriteArray(full)
        b.ComputeStatistics(False)
        ds = None
        mass = np.full(mask.shape, -9999.0, dtype=np.float32)
        mass.ravel()[valid_idx[sel]] = load[sel] * PIXEL_HA
        out2 = run / f"TN_TotalMass_{name}_{YEAR}_{tag}.tif"
        ds = drv.Create(str(out2), cols, rows, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-9999.0)
        b.WriteArray(mass)
        b.ComputeStatistics(False)
        ds = None
        print("wrote", out.name, out2.name)

    # 水量输出（mm）
    for name, vol, sel in (("RM", drain_rm_tot, is_rm), ("RCC", outlet_rcc_tot / A_TOTAL * 1000.0, is_rcc)):
        full = np.full(mask.shape, -9999.0, dtype=np.float32)
        full.ravel()[valid_idx[sel]] = vol[sel]
        out3 = run / f"TN_Drain_{name}_{YEAR}_{tag}.tif"
        ds = drv.Create(str(out3), cols, rows, 1, gdal.GDT_Float32, ["COMPRESS=LZW"])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-9999.0)
        b.WriteArray(full)
        b.ComputeStatistics(False)
        ds = None
        print("wrote", out3.name)


    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("RUN", run)
    return run




from osgeo import gdal
from pathlib import Path
import csv,hashlib,importlib.util,json,sys,uuid
from datetime import date,timedelta
sys.dont_write_bytecode=True
PACKAGE=Path(__file__).resolve().parent

def project_root():
    for p in PACKAGE.parents:
        if (p/'模型/2026.9.3/模型背景数据').is_dir():return p
    raise FileNotFoundError('请将核心计算代码放在包含模型/2026.9.3/模型背景数据的项目内。')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def run(preset='paper_2022',root=None):
    from osgeo import gdal
    import numpy as np
    root=Path(root) if root else project_root()
    config_path=PACKAGE/'configs'/f'{preset}.json'
    config=json.loads(config_path.read_text(encoding='utf-8'))
    for key in ['year','start','days']:
        flag='--'+key
        if flag not in config['arguments'] or config['arguments'][config['arguments'].index(flag)+1]!=str(config[key]):
            raise ValueError('配置头部与arguments不一致：'+key)
    if '--rm-daily-cap' in config['arguments']:
        raise ValueError('此选项尚待水量闭合核验；复现配置不使用该选项。')
    if '--limit' in config['arguments']:
        raise ValueError('本入口按完整区域复现；局部运行需独立定义土壤缺失值填补域。')
    base=root/'模型/2026.9.3/模型背景数据'
    workspace=root/'.codex-work/four_core_runs/regional';workspace.mkdir(parents=True,exist_ok=True)
    inputs=[base/'nitrogen_fertilizer_use/Nfer-2018.hdr',base/'rice_crayfish/Rice_2021.tif',base/'nitrogen_fertilizer_use/Nfer-2018',base/'soil/Environmental Date_pH.tif',base/'soil/Environmental Data_SOM.tif',PACKAGE/'inputs/daily_full_precision.csv']
    start=date.fromisoformat(config['start']);dates=[start+timedelta(days=i) for i in range(config['days'])]
    for d in dates:
        doy=d.timetuple().tm_yday;y=d.year
        inputs += [base/f'rain daily tiff/{y}/PRE_{y}_Day_{doy:03d}.tif',base/f'蒸散发/ET_{y}_daily_tiff/ET_{y}{doy:03d}.tif']
    missing=[str(p) for p in inputs if not p.exists()]
    if missing:raise FileNotFoundError('\n'.join(missing))
    records=[{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for p in inputs]
    signature={'dates':[str(d) for d in dates],'inputs':records,'engine_sha256':digest(PACKAGE/'regional_model.py'),'modules':{n:digest(PACKAGE/n) for n in ['water_balance.py','water_quality.py']}}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:20]
    cache=workspace/'cache'/f'{config["year"]}_{key}.npz';cache.parent.mkdir(exist_ok=True)
    mask_ds=gdal.Open(str(base/'rice_crayfish/Rice_2021.tif'));mask=mask_ds.ReadAsArray();gt=mask_ds.GetGeoTransform()
    if abs(abs(gt[1]*gt[5]-gt[2]*gt[4])/10000-4.554342663494959)>1e-8:
        raise ValueError('当前核验版本使用固定像元面积；更换模板需要同步修改几何参数。')
    shape=(len(dates),int(((mask==1)|(mask==3)).sum()))
    if cache.exists():
        with np.load(cache) as z:
            if z['rain'].shape!=shape or z['et'].shape!=shape:raise ValueError('缓存维度不符合日期与掩膜。')
    cache.with_suffix('.json').write_text(json.dumps(signature,ensure_ascii=False,indent=2),encoding='utf-8')
    module_name='regional_model_'+uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location(module_name,PACKAGE/'regional_model.py')
    model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    model.ROOT=root;model.BASE=base;model.POINTRUN=PACKAGE/'inputs';model.HERE=workspace
    args=config['arguments']+['--tag',config['id'],'--cache-file',str(cache)]
    output=model.calculate(args)
    # 日期分组只用于重现既有统计口径，不代表逐像元物候识别。
    with (output/'逐日区域账本.csv').open(encoding='utf-8-sig') as f:ledger=list(csv.DictReader(f))
    groups={k:{'RM_kg':0.,'RCC_kg':0.} for k in ['06月','07月01日至08月15日','08月16日以后']}
    for r in ledger:
        md=r['date'][5:];k='06月' if md<'07-01' else ('07月01日至08月15日' if md<='08-15' else '08月16日以后')
        groups[k]['RM_kg']+=float(r['rm_load_kg']);groups[k]['RCC_kg']+=float(r['rcc_load_kg'])
    with (output/'日期分段负荷.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['日期组','RM_t','RCC_t','RM_pct','RCC_pct'])
        totals={t:sum(g[t+'_kg'] for g in groups.values()) for t in ['RM','RCC']}
        for k,g in groups.items():w.writerow([k,g['RM_kg']/1000,g['RCC_kg']/1000,100*g['RM_kg']/totals['RM'],100*g['RCC_kg']/totals['RCC']])
    actual=json.loads((output/'summary.json').read_text(encoding='utf-8'))
    checks={t:{k:{'expected':v,'actual':actual[t][k],'difference':actual[t][k]-v} for k,v in config['expected'][t].items()} for t in ['RM','RCC']}
    numeric_pass=all(abs(x['difference'])<1e-6 for t in checks.values() for x in t.values())
    verification={'preset':preset,'reference_run':config['reference_run'],'summary_checks':checks,'summary_reproduced':numeric_pass,'interpretation':'复现一致性；不代表模型实测有效性。'}
    (output/'复现核验.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'运行清单.json').write_text(json.dumps({'config':config,'config_sha256':digest(config_path),'input_signature':signature,'cache':str(cache),'engine_sha256':digest(PACKAGE/'regional_model.py'),'modules':{n:digest(PACKAGE/n) for n in ['water_balance.py','water_quality.py']}},ensure_ascii=False,indent=2),encoding='utf-8')
    for p in [PACKAGE/n for n in ['regional_model.py','water_balance.py','water_quality.py']]+[config_path]:
        (output/p.name).write_bytes(p.read_bytes())
    (workspace/f'latest_{preset}.json').write_text(json.dumps({'run':str(output)},ensure_ascii=False,indent=2),encoding='utf-8')
    print('复现一致性:',numeric_pass,'输出:',output)
    return output

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--preset',default='paper_2022');p.add_argument('--root')
    a=p.parse_args();run(a.preset,a.root)
