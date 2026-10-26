# 稻虾TN模型 · 2024

分支 `model/2024`，登记版本 `2024.20261026`。当前区域配置为 `current_2024`，模拟时段2024-06-01—2024-09-23，共115天。

## 功能与版本

区域核心完成逐日降雨/ET输入、RM田面灌排、RCC田面—沟渠水量转移、施肥事件TN浓度和系统出口TN负荷。配套功能包括2024逐日气象、施肥事件和管理日历覆盖，以及历史情景运行索引。

RM普通无雨日保留田面积水；雨日采用max(阶段上限,120 mm)。RCC沟渠初始水深/外排上限为800/900 mm。

2024 RCC两次施肥为6月18日/7月6日，响应日分别顺延一天，两次采用tillering公式。RM晒田7月3日至4日，6月29日至7月2日阈值30/50/100 mm。RCC 7月1日至2日阈值10/30/100 mm，7月3日至4日晒田，7月5日至14日阈值10/30/100 mm。

| RM均值 kg/ha | RCC均值 kg/ha | RM总量 t | RCC总量 t |
|---:|---:|---:|---:|
| 5.532285108 | 6.780012542 | 3150.397315 | 2295.909139 |

原运行ID、参数和参考数值见 `configs/current_2024.json`。模型功能和历史节点见 [CHANGELOG.md](CHANGELOG.md) 与 [history](history/)。2022点位率定指标、区域情景输出和2024情景结果各有适用的数据与管理规则。

## 运行区域模型

先准备 [输入数据](docs/INPUTS.md)，在本分支根目录执行：

```powershell
& 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat' .\run_model.py --preset current_2024 --root 'E:\#岑俊毅\2.论文\2.稻虾综合种养'
```

`--root` 指向含“模型/2026.9.3/模型背景数据”的数据项目。QGIS Python控制台可使用下面的方式；将代码目录放在该数据项目内，便于入口向上查找数据根：

```python
import runpy
runpy.run_path(r'本分支完整路径/qgis_entry.py', run_name='__main__')
```

QGIS入口默认运行 `current_2024`，完成后加载6个结果栅格。每次运行、缓存与清单保存到数据项目的 `.codex-work/regional_reproduction/`。

## 追溯

`SOURCE_MANIFEST.json`记录本地来源相对路径、源SHA-256及发布SHA-256。`VERSION.json`记录年份、默认配置和基准运行。2026年5月仓库历史代码可从[归档分支](https://github.com/QMsama/rice-crafish/tree/archive/legacy-20261026)查看；年份导航位于[main](https://github.com/QMsama/rice-crafish/tree/main)。后续同年份修改在本分支创建新的代码提交，并在CHANGELOG记录功能、参数、验证和结果变化。
