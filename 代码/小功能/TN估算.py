from osgeo import gdal, osr
import numpy as np
import pandas as pd
import os
import datetime
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']  
plt.rcParams['axes.unicode_minus'] = False    

# ==========================================
# 1. 基础路径设置
# ==========================================
study_area_mask = r"D:\桌面文件\mode\rice_crayfish\Rice_2021.tif"
soil_som_tif = r"D:\桌面文件\mode\soil\Environmental Data_SOM.tif"
soil_ph_tif = r"D:\桌面文件\mode\soil\Environmental Date_pH.tif"
n_fer_tif = r"D:\桌面文件\mode\nitrogen_fertilizer_use\Nfer-2018"
VALIDATION_EXCEL = r"D:\#data\Python\模型验证\V5\田面水TN验证\验证数据.xlsx"

# ==========================================
# 2. 核心参数与【独立参数配置区】
# ==========================================
VALIDATION_POINT_LON = 112.6166
VALIDATION_POINT_LAT = 30.3833
START_DATE = 601
END_DATE = 922

# ------------------------------------------
# ⭐ 独立施肥日期与比例配置 (填 None 表示不施肥)
# ------------------------------------------
FERTILIZER_CONFIG = {
    "rice": {
        "base":      {"date": 605, "ratio": 0.7},
        "tillering": {"date": 618, "ratio": 0.2},
        "heading":   {"date": 707, "ratio": 0.1}
    },
    "cray": {
        "base":      {"date": None, "ratio": 0},  # 填 None 自动跳过该次施肥
        "tillering": {"date": 610,  "ratio": 1},
        "heading":   {"date": None, "ratio": 0.0}   # 填 None 自动跳过该次施肥
    }
}

# ------------------------------------------
# ✅ 独立衰减系数配置 (TN 一阶衰减系数)
# ------------------------------------------
TN_DECAY_K = {
    "rice": {
        "base": 0.250,
        "tillering": 0.4,
        "heading": 0.4
    },
    "cray": {
        "base": 0.215,       
        "tillering": 0.25,  
        "heading": 0.467     
    }
}

# ==========================================
# 3. 工具函数
# ==========================================
def read_and_align(target_path, ref_ds):
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"❌ 栅格不存在：{target_path}")
    gt = ref_ds.GetGeoTransform()
    cols, rows = ref_ds.RasterXSize, ref_ds.RasterYSize
    minX, maxY = gt[0], gt[3]
    maxX = minX + gt[1] * cols
    minY = maxY + gt[5] * rows 
    tmp_ds = gdal.Warp('', target_path, format='VRT',
                       outputBounds=[minX, minY, maxX, maxY],
                       width=cols, height=rows,
                       dstSRS=ref_ds.GetProjection(),
                       resampleAlg=gdal.GRA_Bilinear)
    return tmp_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)

def spatial_interpolate(array, valid_min, valid_max, fallback_val, search_dist=500):
    data = np.copy(array)
    invalid_mask = (data <= valid_min) | (data > valid_max) | np.isnan(data)
    if not np.any(invalid_mask): return data
    nodata_val = -9999.0
    data[invalid_mask] = nodata_val
    driver = gdal.GetDriverByName('MEM')
    temp_ds = driver.Create('', array.shape[1], array.shape[0], 1, gdal.GDT_Float32)
    band = temp_ds.GetRasterBand(1)
    band.WriteArray(data)
    band.SetNoDataValue(nodata_val)
    gdal.FillNodata(targetBand=band, maskBand=None, maxSearchDist=search_dist, smoothingIterations=0)
    filled_data = band.ReadAsArray()
    temp_ds = None 
    return np.where(filled_data == nodata_val, fallback_val, filled_data)

def wgs84_to_rowcol(ref_ds, lon, lat):
    gt = ref_ds.GetGeoTransform()
    raster_proj = osr.SpatialReference()
    raster_proj.ImportFromWkt(ref_ds.GetProjection())
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    if int(gdal.VersionInfo('VERSION_NUM')) >= 3000000:
        wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        raster_proj.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x, y, _ = osr.CoordinateTransformation(wgs84, raster_proj).TransformPoint(lon, lat)
    col = int((x - gt[0]) / gt[1])
    row = int((y - gt[3]) / gt[5])
    if row < 0 or row >= ref_ds.RasterYSize or col < 0 or col >= ref_ds.RasterXSize:
        raise ValueError(f"坐标超出范围：行{row}列{col}")
    return row, col

# ==========================================
# 4. 提取参数
# ==========================================
def extract_params():
    mask_ds = gdal.Open(study_area_mask)
    row, col = wgs84_to_rowcol(mask_ds, VALIDATION_POINT_LON, VALIDATION_POINT_LAT)
    
    som = spatial_interpolate(read_and_align(soil_som_tif, mask_ds), 0.0, 200.0, 2.0)
    ph = spatial_interpolate(read_and_align(soil_ph_tif, mask_ds), 0.0, 14.0, 7.0)
    
    n_fer_data = read_and_align(n_fer_tif, mask_ds) * 1
    n_fer_data = np.where((n_fer_data <= 0) | (n_fer_data > 10000) | np.isnan(n_fer_data), 0.0, n_fer_data)

    point_som = max(0.1, som[row, col])
    point_ph = max(4.0, min(10.0, ph[row, col]))
    point_n_fer = max(0.0, n_fer_data[row, col])
    
    mask_ds = None
    print(f"✅ 参数提取成功")
    print(f"  土壤：SOM={point_som:.2f}%, pH={point_ph:.2f}")
    print(f"  共用施肥量：N={point_n_fer:.2f} kg/ha")
    print(f"\n📅 独立施肥日期配置：")
    
    # ⭐ 打印更新后的配置格式
    print(f"  稻田：基肥{FERTILIZER_CONFIG['rice']['base']['date']} | 蘖肥{FERTILIZER_CONFIG['rice']['tillering']['date']} | 穗肥{FERTILIZER_CONFIG['rice']['heading']['date']}")
    print(f"  稻虾田：基肥{FERTILIZER_CONFIG['cray']['base']['date']} | 蘖肥{FERTILIZER_CONFIG['cray']['tillering']['date']} | 穗肥{FERTILIZER_CONFIG['cray']['heading']['date']}")
    return point_som, point_ph, point_n_fer

# ==========================================
# 5. 论文公式（仅保留 TN 计算）
# ==========================================
def calculate_tn_initial(fer_amount, ph, som, stage):
    # ⭐ 严格按文献公式计算，不做任何系数换算
    if stage == 'base':
        val = -21.469 + 0.841 * fer_amount + 3.074 * ph
    elif stage == 'tillering':
        val = -101.200 + 0.540 * fer_amount + 22.184 * ph - 11.093 * som
    elif stage == 'heading':
        val = -164.918 + 0.435 * fer_amount + 26.256 * ph
    else:
        val = 0.0
    return max(0.001, val)

def get_tn_k(mode, stage):
    return TN_DECAY_K.get(mode, {}).get(stage, 0.325)

# ==========================================
# 6. 逐日模拟（传入模式参数计算衰减）
# ==========================================
def daily_simulation(som, ph, n_fer):
    date_list = []
    current = datetime.datetime(2022, 6, 1)
    while current <= datetime.datetime(2022, 9, 22):
        date_list.append((int(current.strftime('%m%d')), current.strftime('%Y-%m-%d')))
        current += datetime.timedelta(days=1)
    
    c_tn_rice = 0.01
    rice_tn_stage = 'base'
    
    c_tn_cray = 1.5
    cray_tn_stage = 'base'
    
    results = []
    print("\n✅ 开始逐日模拟（纯 TN 模块）")
    
    for date_md, date_str in date_list:
        # --------------------------
        # ⭐ 1. 稻田独立施肥逻辑 (动态检测 None)
        # --------------------------
        for stage, config in FERTILIZER_CONFIG['rice'].items():
            if config['date'] is not None and date_md == config['date']:
                c_tn_rice += calculate_tn_initial(n_fer * config['ratio'], ph, som, stage)
                rice_tn_stage = stage
        
        # --------------------------
        # ⭐ 2. 稻虾田独立施肥逻辑 (动态检测 None)
        # --------------------------
        for stage, config in FERTILIZER_CONFIG['cray'].items():
            if config['date'] is not None and date_md == config['date']:
                c_tn_cray += calculate_tn_initial(n_fer * config['ratio'], ph, som, stage)
                cray_tn_stage = stage
        
        # --------------------------
        # 3. 独立衰减计算
        # --------------------------
        c_tn_rice *= np.exp(-get_tn_k('rice', rice_tn_stage))
        c_tn_cray *= np.exp(-get_tn_k('cray', cray_tn_stage))
        
        c_tn_rice = max(0.001, c_tn_rice)
        c_tn_cray = max(0.001, c_tn_cray)
        
        results.append({
            '标准日期': date_str,      
            '日期(mmdd)': date_md,     
            '单季稻TN(mg/L)': round(c_tn_rice, 4),
            '稻虾田TN(mg/L)': round(c_tn_cray, 4)
        })
    
    sim_df = pd.DataFrame(results)
    print(f"✅ 模拟完成，共{len(sim_df)}天数据")
    return sim_df

# ==========================================
# 7. 自动对齐验证数据并导出
# ==========================================
def align_and_export(sim_df):
    val_df = pd.read_excel(VALIDATION_EXCEL)
    
    sim_df['标准日期'] = pd.to_datetime(sim_df['标准日期'])
    
    val_rice = val_df.iloc[:, [0, 1]].dropna()
    val_rice.columns = ['验证日期_稻', '单季稻TN观测值(mg/L)']
    val_rice['验证日期_稻'] = pd.to_datetime(val_rice['验证日期_稻'])
    
    val_cray = val_df.iloc[:, [2, 3]].dropna()
    val_cray.columns = ['验证日期_虾', '稻虾田TN观测值(mg/L)']
    val_cray['验证日期_虾'] = pd.to_datetime(val_cray['验证日期_虾'])
    
    aligned_df = pd.merge(sim_df, val_rice, left_on="标准日期", right_on="验证日期_稻", how="left")
    aligned_df = pd.merge(aligned_df, val_cray, left_on="标准日期", right_on="验证日期_虾", how="left")
    
    aligned_df = aligned_df.drop(columns=['验证日期_稻', '验证日期_虾'])
    aligned_df = aligned_df.dropna(subset=['单季稻TN观测值(mg/L)', '稻虾田TN观测值(mg/L)'], how='all')
    
    print("\n📊 模型误差评估结果：")
    metrics_results = []
    target_cols = ['单季稻TN(mg/L)', '稻虾田TN(mg/L)']
    
    for sim_col in target_cols:
        obs_col = sim_col.replace('(mg/L)', '观测值(mg/L)')
        
        if sim_col in aligned_df.columns and obs_col in aligned_df.columns:
            obs = aligned_df[obs_col].values
            sim = aligned_df[sim_col].values
            
            valid = (~np.isnan(obs)) & (~np.isnan(sim)) & (obs != 0)
            if np.sum(valid) > 1:
                obs, sim = obs[valid], sim[valid]
                
                r_matrix = np.corrcoef(sim, obs)
                r2 = r_matrix[0, 1] ** 2 if r_matrix.shape == (2, 2) else np.nan
                
                slope, intercept = np.polyfit(sim, obs, 1)
                fit_y = slope * sim + intercept  
                df_val = len(obs) - 2                
                rmse = np.sqrt(np.sum((obs - fit_y) ** 2) / df_val) if df_val > 0 else np.nan
                
                re = np.mean(np.abs(obs - sim) / obs) * 100
                
                item_name = sim_col.split('(')[0]
                print(f"  ➤ [{item_name}] R² = {r2:.4f}, RMSE = {rmse:.4f}, 平均相对误差(RE) = {re:.2f}%")
                
                metrics_results.append({
                    '评价项': item_name,
                    'R²': round(r2, 4),
                    'RMSE': round(rmse, 4),
                    '平均相对误差RE(%)': round(re, 2)
                })
            else:
                print(f"  ⚠️ [{sim_col}] 有效数据不足，无法计算。")
        else:
            print(f"  ⚠️ 未在验证表中找到 {obs_col} 列，跳过 {sim_col.split('(')[0]} 的指标计算。")

    out_dir = r"D:\#data\Python\模型验证\V5\田面水TN验证"
    os.makedirs(out_dir, exist_ok=True)
    
    sim_output = os.path.join(out_dir, "TN浓度验证.csv")
    aligned_output = os.path.join(out_dir, "TN模拟对齐数据.csv")
    
    sim_df.to_csv(sim_output, index=False, encoding='utf-8-sig')
    aligned_df.to_csv(aligned_output, index=False, encoding='utf-8-sig')
    
    if metrics_results:
        metrics_df = pd.DataFrame(metrics_results)
        metrics_output = os.path.join(out_dir, "模型评价指标_R2_RMSE_RE.csv")
        metrics_df.to_csv(metrics_output, index=False, encoding='utf-8-sig')
    
    print(f"\n✅ 数据导出完成")
    print(f"  对齐数据已保存（共{len(aligned_df)}天匹配）")
    if metrics_results:
        print(f"  👉 评价指标表已保存至：模型评价指标_R2_RMSE_RE.csv")
        
    return aligned_df

# ==========================================
# 可视化绘图函数
# ==========================================
def plot_validation(sim_df, aligned_df):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    rice_valid = aligned_df.dropna(subset=['单季稻TN观测值(mg/L)'])
    cray_valid = aligned_df.dropna(subset=['稻虾田TN观测值(mg/L)'])

    axes[0, 0].plot(sim_df['标准日期'], sim_df['单季稻TN(mg/L)'], label='模拟值', c='#1f77b4')
    axes[0, 0].scatter(rice_valid['标准日期'], rice_valid['单季稻TN观测值(mg/L)'], label='观测值', c='red', marker='x')
    axes[0, 0].set_title('单季稻 TN 逐日拟合图')
    axes[0, 0].tick_params(axis='x', rotation=30)
    axes[0, 0].legend()

    axes[0, 1].plot(sim_df['标准日期'], sim_df['稻虾田TN(mg/L)'], label='模拟值', c='#2ca02c')
    axes[0, 1].scatter(cray_valid['标准日期'], cray_valid['稻虾田TN观测值(mg/L)'], label='观测值', c='red', marker='x')
    axes[0, 1].set_title('稻虾田 TN 逐日拟合图')
    axes[0, 1].tick_params(axis='x', rotation=30)
    axes[0, 1].legend()

    axes[1, 0].scatter(rice_valid['单季稻TN(mg/L)'], rice_valid['单季稻TN观测值(mg/L)'], c='#1f77b4')
    vmin_r = min(rice_valid['单季稻TN(mg/L)'].min(), rice_valid['单季稻TN观测值(mg/L)'].min())
    vmax_r = max(rice_valid['单季稻TN(mg/L)'].max(), rice_valid['单季稻TN观测值(mg/L)'].max())
    axes[1, 0].plot([vmin_r, vmax_r], [vmin_r, vmax_r], 'k--', label='1:1线')
    axes[1, 0].set(title='单季稻 TN 精度验证', xlabel='模拟值 (mg/L)', ylabel='观测值 (mg/L)')
    axes[1, 0].legend()

    axes[1, 1].scatter(cray_valid['稻虾田TN(mg/L)'], cray_valid['稻虾田TN观测值(mg/L)'], c='#2ca02c')
    vmin_c = min(cray_valid['稻虾田TN(mg/L)'].min(), cray_valid['稻虾田TN观测值(mg/L)'].min())
    vmax_c = max(cray_valid['稻虾田TN(mg/L)'].max(), cray_valid['稻虾田TN观测值(mg/L)'].max())
    axes[1, 1].plot([vmin_c, vmax_c], [vmin_c, vmax_c], 'k--', label='1:1线')
    axes[1, 1].set(title='稻虾田 TN 精度验证', xlabel='模拟值 (mg/L)', ylabel='观测值 (mg/L)')
    axes[1, 1].legend()

    plt.tight_layout()
    plt.show() 

# ==========================================
# 主函数
# ==========================================
def main():
    try:
        print("="*70)
        print("稻虾田/稻田氮模拟（纯TN版）")
        print("="*70)
        
        som, ph, n_fer = extract_params()
        sim_df = daily_simulation(som, ph, n_fer)
        
        aligned_df = align_and_export(sim_df)
        
        print("\n" + "="*70)
        print("✅ 所有流程完成！关闭弹出的图表窗口后程序将完全退出。")
        print("="*70)
        
        plot_validation(sim_df, aligned_df)

    except Exception as e:
        print(f"\n❌ 报错：{str(e)}")


main()