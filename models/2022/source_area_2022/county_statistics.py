from pathlib import Path
import csv
import json
import os
import hashlib

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
ROOT = Path(os.environ['TN_PROJECT_ROOT']).resolve()
RUN_ROOT = Path(os.environ['TN_SOURCE_AREA_RUN']).resolve()
WORK = RUN_ROOT / 'source_area_map/agent_county'
BASE = ROOT / '模型/2026.9.3/面上推广'
BOUNDARY = Path(os.environ['TN_COUNTY_BOUNDARY']) if os.environ.get('TN_COUNTY_BOUNDARY') else next((ROOT / '模型/2026.6.27/毕业论文/制图').rglob('县.shp'))
PRIOR = json.loads((RUN_ROOT / 'load_area_figure/figure_data.json').read_text(encoding='utf-8'))
ref = gdal.Open(str(BASE / 'TN_Load_RM_2022.tif'))
nx, ny, gt = ref.RasterXSize, ref.RasterYSize, ref.GetGeoTransform()
area_ha = abs(gt[1] * gt[5] - gt[2] * gt[4]) / 10000
target = osr.SpatialReference(wkt=ref.GetProjection())
target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
geo = osr.SpatialReference()
geo.ImportFromEPSG(4326)
geo.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
to_geo = osr.CoordinateTransformation(target, geo)
extent_xy = [(gt[0]+c*gt[1]+r*gt[2], gt[3]+c*gt[4]+r*gt[5]) for c,r in [(0,0),(nx,0),(nx,ny),(0,ny)]]
corner_ll = [to_geo.TransformPoint(x,y)[:2] for x,y in extent_xy]
ll_box = [min(v[0] for v in corner_ll)-0.02, min(v[1] for v in corner_ll)-0.02, max(v[0] for v in corner_ll)+0.02, max(v[1] for v in corner_ll)+0.02]
src = ogr.Open(str(BOUNDARY))
src_layer = src.GetLayer()
src_srs = src_layer.GetSpatialRef().Clone()
src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
src_layer.SetSpatialFilterRect(*ll_box)
project = osr.CoordinateTransformation(src_srs, target)
features = []
geometry_issues = []
for feature in src_layer:
    attrs = feature.items()
    geometry = feature.GetGeometryRef().Clone()
    if not geometry.IsValid():
        geometry_issues.append({'code': int(attrs['县代码']), 'county': attrs['县名'], 'action': 'MakeValid in working copy'})
        geometry = geometry.MakeValid()
    geometry.Transform(project)
    features.append((int(attrs['县代码']), attrs, geometry))
features.sort(key=lambda row:(row[0], str(row[1]['县名'])))
assert len(set(row[0] for row in features)) == len(features)

mem_vector = ogr.GetDriverByName('Memory').CreateDataSource('county')
layer = mem_vector.CreateLayer('county', target, geom_type=ogr.wkbMultiPolygon)
for name,typ in [('cid',ogr.OFTInteger),('code',ogr.OFTInteger64),('county',ogr.OFTString),('city',ogr.OFTString),('province',ogr.OFTString)]:
    field = ogr.FieldDefn(name,typ)
    if typ == ogr.OFTString:
        field.SetWidth(100)
    layer.CreateField(field)
county_info = []
for cid,(code,attrs,geom) in enumerate(features,1):
    record = ogr.Feature(layer.GetLayerDefn())
    row = {'cid':cid,'code':code,'county':attrs['县名'],'city':attrs['市名'],'province':attrs['省名']}
    county_info.append(row)
    for k,v in row.items():
        record.SetField(k,v)
    record.SetGeometry(ogr.ForceToMultiPolygon(geom.Clone()))
    layer.CreateFeature(record)

def memory_raster(dtype):
    ds = gdal.GetDriverByName('MEM').Create('',nx,ny,1,dtype)
    ds.SetGeoTransform(gt)
    ds.SetProjection(ref.GetProjection())
    ds.GetRasterBand(1).Fill(0)
    return ds

index_ds = memory_raster(gdal.GDT_Int32)
gdal.RasterizeLayer(index_ds,[1],layer,options=['ATTRIBUTE=cid'])
county_index = index_ds.ReadAsArray()
count_ds = memory_raster(gdal.GDT_UInt16)
gdal.RasterizeLayer(count_ds,[1],layer,burn_values=[1],options=['MERGE_ALG=ADD'])
membership_count = count_ds.ReadAsArray()
assert np.array_equal(county_index > 0, membership_count > 0)
gdal.GetDriverByName('GTiff').CreateCopy(str(WORK / 'county_index.tif'),index_ds,options=['COMPRESS=LZW'])
gpkg_path = WORK / 'selected_counties_projected.gpkg'
if not gpkg_path.exists():
    gpkg = ogr.GetDriverByName('GPKG').CreateDataSource(str(gpkg_path))
    gpkg.CopyLayer(layer,'counties')
    gpkg = None

summary = {
    'boundary_source':str(BOUNDARY),
    'boundary_sha256':hashlib.sha256(BOUNDARY.read_bytes()).hexdigest(),
    'boundary_fields': {'county':'县名','code':'县代码','city':'市名','province':'省名'},
    'candidate_county_count':len(features),
    'candidate_filter_wgs84':ll_box,
    'raster_dimensions':[nx,ny],
    'pixel_area_ha':area_ha,
    'raster_srs_wkt':ref.GetProjection(),
    'method':'Project county geometry to native raster CRS; default GDAL pixel-center rasterization. At overlaps ascending county-code order is burnt, so last (highest code) owns center. Classification uses per-pixel TotalMass/pixel area.',
    'geometry_issues':geometry_issues,
    'share_denominators':'All shares of regional critical area/mass use the entire respective system valid mask, including unassigned pixels. Within-county critical share uses assigned valid system area/mass in that county.',
    'systems':{},
    'county_lookup':county_info,
}
all_rows = []
geojson_features = []
for system in ['RM','RCC']:
    ds = gdal.Open(str(BASE / f'TN_TotalMass_{system}_2022.tif'))
    lds = gdal.Open(str(BASE / f'TN_Load_{system}_2022.tif'))
    assert ds.GetGeoTransform() == gt and ds.GetProjection() == ref.GetProjection()
    mass = ds.ReadAsArray().astype(np.float64)
    load = lds.ReadAsArray()
    valid = np.isfinite(mass) & (mass != ds.GetRasterBand(1).GetNoDataValue())
    load_valid = np.isfinite(load) & (load != lds.GetRasterBand(1).GetNoDataValue())
    assert np.array_equal(valid,load_valid)
    nvalid = int(valid.sum())
    total_mass_kg = float(mass[valid].sum())
    mean = total_mass_kg / (nvalid*area_ha)
    unit_load = mass / area_ha
    critical = valid & (unit_load > 2*mean)
    subcritical = valid & (unit_load > mean) & (unit_load <= 2*mean)
    ncritical = int(critical.sum())
    critical_mass_kg = float(mass[critical].sum())
    assert ncritical == PRIOR['systems'][system]['groups']['critical']['pixel_count']
    unassigned = valid & (county_index == 0)
    overlap = valid & (membership_count > 1)
    county_rows = []
    for meta in county_info:
        in_county = valid & (county_index == meta['cid'])
        n = int(in_county.sum())
        if not n:
            continue
        cmask = critical & in_county
        smask = subcritical & in_county
        nc = int(cmask.sum())
        ns = int(smask.sum())
        county_mass = float(mass[in_county].sum())
        cmass = float(mass[cmask].sum())
        row = {**meta,'system':system,'valid_pixel_count':n,'valid_area_km2':n*area_ha/100,'total_mass_t':county_mass/1000,'mean_load_kg_ha':county_mass/(n*area_ha),'critical_pixel_count':nc,'critical_area_km2':nc*area_ha/100,'critical_mass_t':cmass/1000,'share_of_regional_critical_area_pct':nc/ncritical*100,'share_of_regional_critical_mass_pct':cmass/critical_mass_kg*100,'within_county_critical_area_pct':nc/n*100,'within_county_critical_mass_pct':cmass/county_mass*100,'subcritical_pixel_count':ns,'subcritical_area_km2':ns*area_ha/100,'subcritical_mass_t':float(mass[smask].sum())/1000}
        if nc:
            rr,cc = np.where(cmask)
            x = gt[0]+(cc+.5)*gt[1]+(rr+.5)*gt[2]
            y = gt[3]+(cc+.5)*gt[4]+(rr+.5)*gt[5]
            cx,cy = float(x.mean()),float(y.mean())
            lon,lat,_ = to_geo.TransformPoint(cx,cy)
            row.update({'critical_centroid_lon':lon,'critical_centroid_lat':lat})
            geojson_features.append({'type':'Feature','properties':row.copy(),'geometry':{'type':'Point','coordinates':[lon,lat]}})
        county_rows.append(row)
    county_rows.sort(key=lambda row:row['critical_mass_t'],reverse=True)
    for rank,row in enumerate(county_rows,1):
        row['critical_mass_rank'] = rank
    cr,cc = np.where(critical)
    cx = gt[0]+(cc+.5)*gt[1]+(cr+.5)*gt[2]
    cy = gt[3]+(cc+.5)*gt[4]+(cr+.5)*gt[5]
    avg_lon,avg_lat,_ = to_geo.TransformPoint(float(cx.mean()),float(cy.mean()))
    missing_coordinates = []
    for r,c in zip(*np.where(unassigned)):
        x,y = gdal.ApplyGeoTransform(gt,float(c)+.5,float(r)+.5)
        lon,lat,_ = to_geo.TransformPoint(x,y)
        missing_coordinates.append({'row':int(r),'col':int(c),'lon':lon,'lat':lat,'load_kg_ha':float(unit_load[r,c]),'critical':bool(critical[r,c])})
    missing_file = WORK/f'{system}_unassigned_centers.csv'
    with missing_file.open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=['row','col','lon','lat','load_kg_ha','critical'])
        writer.writeheader()
        writer.writerows(missing_coordinates)
    sys_summary = {
        'valid_pixel_count':nvalid,'valid_area_km2':nvalid*area_ha/100,'total_mass_t':total_mass_kg/1000,
        'mean_load_kg_ha':mean,'critical_threshold_kg_ha':2*mean,
        'critical_pixel_count':ncritical,'critical_area_km2':ncritical*area_ha/100,'critical_mass_t':critical_mass_kg/1000,
        'assigned_pixel_count':int((valid & (county_index>0)).sum()),'coverage_pct':float((valid & (county_index>0)).sum()/nvalid*100),
        'unassigned_pixel_count':int(unassigned.sum()),'unassigned_area_km2':float(unassigned.sum()*area_ha/100),
        'unassigned_mass_t':float(mass[unassigned].sum()/1000),
        'unassigned_critical_pixel_count':int((critical & unassigned).sum()),
        'unassigned_critical_area_km2':float((critical & unassigned).sum()*area_ha/100),
        'unassigned_critical_mass_t':float(mass[critical & unassigned].sum()/1000),
        'overlap_pixel_count':int(overlap.sum()),'overlap_area_km2':float(overlap.sum()*area_ha/100),
        'overlap_critical_pixel_count':int((critical & overlap).sum()),
        'all_critical_center_mean_lon_lat':[avg_lon,avg_lat],
        'county_count_with_valid_pixels':len(county_rows),
        'top5_by_critical_mass':county_rows[:5],
        'top5_by_critical_area':sorted(county_rows,key=lambda row:row['critical_area_km2'],reverse=True)[:5],
        'counties':county_rows,
    }
    assert sum(row['valid_pixel_count'] for row in county_rows) + sys_summary['unassigned_pixel_count'] == nvalid
    assert sum(row['critical_pixel_count'] for row in county_rows) + sys_summary['unassigned_critical_pixel_count'] == ncritical
    assert abs(sum(row['critical_mass_t'] for row in county_rows)+sys_summary['unassigned_critical_mass_t']-critical_mass_kg/1000)<1e-8
    summary['systems'][system] = sys_summary
    all_rows.extend(county_rows)

fields = list(dict.fromkeys(k for row in all_rows for k in row))
with (WORK/'county_source_statistics.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer = csv.DictWriter(f,fieldnames=fields)
    writer.writeheader()
    writer.writerows(all_rows)
(WORK/'county_source_statistics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(WORK/'critical_county_centroids.geojson').write_text(json.dumps({'type':'FeatureCollection','features':geojson_features},ensure_ascii=False),encoding='utf-8')
for system,report in summary['systems'].items():
    print(system, 'coverage',report['coverage_pct'],'overlap',report['overlap_pixel_count'],'unassigned',report['unassigned_pixel_count'])
    for row in report['top5_by_critical_mass']:
        print(row['county'],row['city'],'area km2',round(row['critical_area_km2'],3),'mass t',round(row['critical_mass_t'],3),'regional critical mass %',round(row['share_of_regional_critical_mass_pct'],3),'within county area %',round(row['within_county_critical_area_pct'],3))
print('OUTPUT',WORK/'county_source_statistics.json')
