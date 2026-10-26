"""在QGIS Python控制台编辑器中运行本文件。"""
from pathlib import Path
import importlib.util,sys
sys.dont_write_bytecode=True

# 可选：paper_2022、current_2024、legacy_2022。
PRESET='current_2024'

def execute(preset=PRESET):
    from qgis.core import QgsProject,QgsRasterLayer
    folder=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('regional_reproduction_entry',folder/'run_model.py')
    entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
    output=entry.run(preset)
    for path in sorted(output.glob('TN_*.tif')):
        layer=QgsRasterLayer(str(path),path.stem)
        if not layer.isValid():raise RuntimeError('QGIS无法读取：'+str(path))
        QgsProject.instance().addMapLayer(layer)
    print('六个结果栅格已加入当前QGIS项目；运行目录：',output)
    return output

if __name__ in ('__main__','__console__'):execute()
