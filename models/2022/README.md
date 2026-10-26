# 2022 稻虾TN模型

当前配置：`paper_2022`。参数及参考数值见`configs/paper_2022.json`，输入要求见[INPUTS](docs/INPUTS.md)。

在本目录执行：

```powershell
& 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat' .\run_model.py --preset paper_2022 --root 'E:\#岑俊毅\2.论文\2.稻虾综合种养'
```

QGIS入口为`qgis_entry.py`；输出和缓存写入数据项目的`.codex-work/regional_reproduction/`。

2022关键源区工具：[source_area_2022](source_area_2022/)。

版本记录见[CHANGELOG](CHANGELOG.md)。点位研究源码、历史运行和核验材料集中在[年度归档](../../archive/models/2022/)；归档文档按其原始版本的路径语境保存。
