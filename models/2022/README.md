# 2022 稻虾氮素流失核心计算

| 文件 | 计算任务 |
| --- | --- |
| `water_balance.py` | 田面水量、灌排管理和虾沟蓄排水 |
| `water_quality.py` | 施肥响应、背景与投饵TN浓度及出口负荷 |
| `point_validation.py` | 点位逐日计算、同日观测核验和负荷汇总 |
| `regional_model.py` | 按年度配置读取空间输入，逐像元运行并输出栅格 |

水量模块和水质模块供点位、区域入口调用。运行配置放`configs/`，逐日输入及管理表放`inputs/`。

在本目录运行（数据项目路径可替换）：

```powershell
$dataRoot = 'E:\#岑俊毅\2.论文\2.稻虾综合种养'
$qgisPython = 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat'
& $qgisPython .\regional_model.py --preset paper_2022 --root $dataRoot
```

2022点位计算：

```powershell
& $qgisPython .\point_validation.py --root $dataRoot
```

点位逐日输入、参数与施肥事件从本地数据项目`模型/2026.9.3/面上推广/核心计算代码/inputs/`和`configs/`读取，也可用`--inputs`、`--parameters`、`--events`指定。

提供观测时增加`--tn-observations <TN观测.csv>`及`--water-observations <水位观测.csv>`。TN观测列为`treatment,date,value,included_in_metrics,model_role`；按原数据用途分组，同日重复观测取平均后计算RMSE和偏差，率定日期单独标记。水位观测列为`日期,实测_RM_水位_mm,实测_RCC_水位_mm`。观测文件在数据项目内保存，通过参数读取。

区域外部数据位于数据项目`模型/2026.9.3/模型背景数据/`：种养掩膜`rice_crayfish/Rice_2021.tif`；施氮量`nitrogen_fertilizer_use/Nfer-2018`及配套`.hdr`；pH、SOM分别为`soil/Environmental Date_pH.tif`、`soil/Environmental Data_SOM.tif`；逐日降雨`rain daily tiff/年份/PRE_年份_Day_年积日.tif`；ET为`蒸散发/ET_年份_daily_tiff/ET_年份年积日.tif`，区域ET按原方法除以1000换为mm/d。

水质计算沿用已率定TN经验模型。RCC负荷以沟渠系统出口水量乘田面TN代理浓度；田面入沟为内部转移。点位和区域各自沿用对应管理规则。区域结果复现核验用于检查计算一致性；观测核验由点位入口按提供数据计算。

点位输出`water.csv`、`TN.csv`、`outlet_load.csv`、`summary.json`；提供观测时输出`observation_pairs.csv`。区域输出逐日账本和TN排水、单位面积负荷、总质量栅格。输出与缓存统一位于数据项目`.codex-work/four_core_runs/`。QGIS控制台先执行`import sys; sys.dont_write_bytecode = True`，将本目录加入Python路径后调用`regional_model.run(preset, root)`。
