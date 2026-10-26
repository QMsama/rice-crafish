# 输入数据与运行产物

区域入口通过 `--root` 指定数据项目根目录，并使用其中的 `模型/2026.9.3/模型背景数据`。仓库内 `inputs/daily_full_precision.csv` 是 RM/RCC 管理阈值表，包含222行、6列。

| 输入 | 数据项目内路径 | 用途/单位 |
|---|---|---|
| 种植掩膜 | `rice_crayfish/Rice_2021.tif` | 类1为RM，类3为RCC；2021代理掩膜 |
| 施氮 | `nitrogen_fertilizer_use/Nfer-2018` 与 `Nfer-2018.hdr` | ENVI数据及必需头文件；模型乘10换算kg N/ha；建议同时保留aux.xml |
| pH | `soil/Environmental Date_pH.tif` | pH |
| SOM | `soil/Environmental Data_SOM.tif` | 按当前回归式的SOM口径 |
| 逐日降雨 | `rain daily tiff/年份/PRE_年份_Day_年积日.tif` | mm/d |
| 逐日ET | `蒸散发/ET_年份_daily_tiff/ET_年份年积日.tif` | 输入值除1000为mm/d |

像元面积为4.554342663494959 ha，当前入口检查模板像元面积。逐日P/ET双线性对齐种植模板；固定下渗2 mm/d。相应年份的气象数据和静态代理数据共同定义情景。

运行结果位于数据项目 `.codex-work/regional_reproduction/run_时间_配置_编号/`。每次保存6个GeoTIFF、逐日区域账本、summary、日期分组负荷、输入/代码/配置哈希和复现核验；可复用缓存位于同级cache。固定日期分组为6月、7月1日至8月15日、8月16日以后。

区域TN采用施肥事件经验浓度曲线，RM直接计算田面外排；RCC田面退水入沟为内部转移，系统出口采用沟渠外排及田面TN代理浓度。参考结果用于计算复现核对；模型实测评价需配套观测、边界及相同管理规则。
