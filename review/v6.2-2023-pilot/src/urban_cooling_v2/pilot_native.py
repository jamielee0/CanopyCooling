"""Native-cell input builder for the amended, limited v6.2 pilot.

No thermal interpolation. Exclusive 100km MGRS cores and UTM-zone ownership
exclude seam-straddling footprints; exact center duplicates are a hard error.
Continuous context uses GDAL area-average aggregation. Canopy must have complete
stable 2019-2025 source coverage, up to a 1e-6 floating-point coverage tolerance.
"""
from pathlib import Path
from collections import defaultdict
import re
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import reproject,Resampling,transform_bounds
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds,Window
from scipy.ndimage import distance_transform_edt
from shapely.geometry import shape,mapping
from shapely.ops import transform as geom_transform
from shapely import make_valid
from pyproj import Transformer
from affine import Affine
from .pooled_city_pass import emitted_energy,CONTEXT

PATTERN=re.compile(r'(?P<stem>ECOv(?P<collection>\d+)_L2T_LSTE_(?P<orbit>\d+)_(?P<scene>\d+)_(?P<tile>\w+)_(?P<instant>\d+T\d+)_(?P<build>\d+)_(?P<revision>\d+))_LST.tif$')

def read_scaled(path,window=None):
    with rasterio.open(path) as d:
        a=d.read(1,window=window,masked=True).astype(float).filled(np.nan)
        # Rasterio/GDAL exposes TIFF scale metadata; do not apply packed-swath
        # factors to the already-physical Collection 2 float COGs.
        a=a*d.scales[0]+d.offsets[0]
    return a

def average_to_grid(a,transform,crs,shape_out,transform_out,crs_out):
    dest=np.full(shape_out,np.nan,np.float32)
    reproject(np.asarray(a,np.float32),dest,src_transform=transform,src_crs=crs,
              src_nodata=np.nan,dst_transform=transform_out,dst_crs=crs_out,
              dst_nodata=np.nan,resampling=Resampling.average,num_threads=2)
    return dest

def shifted(a,dx,dy):
    out=np.full_like(a,np.nan)
    ys=slice(max(0,dy),min(a.shape[0],a.shape[0]+dy));xs=slice(max(0,dx),min(a.shape[1],a.shape[1]+dx))
    out[ys,xs]=a[slice(max(0,-dy),min(a.shape[0],a.shape[0]-dy)),slice(max(0,-dx),min(a.shape[1],a.shape[1]-dx))]
    return out

def native_owner(x,y,half,core,zone,crs):
    l,b,r,t=core
    keep=(x-half>=l)&(x+half<=r)&(y-half>=b)&(y+half<=t)
    togeo=Transformer.from_crs(crs,4326,always_xy=True)
    west=-180+6*(zone-1);east=west+6
    for dx,dy in [(-half,-half),(-half,half),(half,-half),(half,half)]:
        lon,_=togeo.transform(x+dx,y+dy);keep&=(lon>=west)&(lon<east)
    return keep

class ContextGrid:
    def __init__(self, paths, building_raster=None):
        self.sources={};self.cache={};self.provenance=[]
        annual=[];grid=None
        for p in paths['canopy_annual']:
            with rasterio.open(p) as d:
                spec=(d.shape,d.transform,d.crs)
                if grid is not None and spec!=grid:raise ValueError('Annual canopy grids differ')
                grid=spec;annual.append(d.read(1,masked=True).astype(np.float32).filled(np.nan))
        if len(annual)!=7:raise ValueError('Seven annual Science TCC layers required')
        annual=np.stack(annual);valid=np.isfinite(annual).all(axis=0)&(annual>=0).all(axis=0)&(annual<=100).all(axis=0)
        # Avoid all-NaN warnings without assigning scientific meaning to masked values.
        filled=np.where(np.isfinite(annual),annual,0)
        stable=valid&((filled.max(axis=0)-filled.min(axis=0))<=15)
        canopy=np.where(stable,np.median(filled,axis=0)/100,np.nan)
        self.sources['canopy_fraction']=(canopy,grid[1],grid[2])
        self.sources['stable_coverage']=(stable.astype(np.float32),grid[1],grid[2])
        del annual,filled
        for name in ['impervious_fraction','elevation']:
            with rasterio.open(paths[name]) as d:
                if name=='impervious_fraction':
                    # This inherited raster uses nodata=0, also a legitimate
                    # impervious value. Use its companion NLCD validity mask.
                    a=d.read(1).astype(np.float32)
                    with rasterio.open(paths['impervious_validity']) as lc:
                        if (lc.crs,lc.transform,lc.shape)!=(d.crs,d.transform,d.shape):raise ValueError('Impervious validity grid mismatch')
                        valid=(lc.read(1)!=0)&(a>=0)&(a<=100)
                    a=np.where(valid,a/100,np.nan)
                else:a=d.read(1,masked=True).astype(np.float32).filled(np.nan)*d.scales[0]+d.offsets[0]
                self.sources[name]=(a,d.transform,d.crs)
        with rasterio.open(paths['land_cover']) as d:
            lc=d.read(1,masked=True).filled(0);valid=lc!=0
            self.sources['low_vegetation_fraction']=(np.where(valid,np.isin(lc,[52,71,81,82]).astype(float),np.nan),d.transform,d.crs)
            self.sources['bare_fraction']=(np.where(valid,(lc==31).astype(float),np.nan),d.transform,d.crs)
            if not (lc==11).any():raise ValueError('No water cells for distance context')
            if d.crs.is_geographic:raise ValueError('Distance grid must be projected in metres')
            distance=distance_transform_edt(lc!=11,sampling=(abs(d.transform.e),abs(d.transform.a)))
            self.sources['distance_to_water']=(np.where(valid,distance,np.nan),d.transform,d.crs)
        if building_raster is not None:
            self.sources['building_fraction']=building_raster
        else:
            with rasterio.open(paths['building_fraction']) as d:
                self.sources['building_fraction']=(read_scaled(paths['building_fraction']),d.transform,d.crs)
    def at(self,shape_out,transform_out,crs_out):
        key=(shape_out,tuple(transform_out),str(crs_out))
        if key not in self.cache:
            out={k:average_to_grid(a,t,c,shape_out,transform_out,crs_out) for k,(a,t,c) in self.sources.items()}
            out['canopy_fraction'][out['stable_coverage']<1-1e-6]=np.nan
            self.cache[key]=out
        return self.cache[key]


def discover(raw,orbits,emissivity_root):
    groups={}
    for p in Path(raw).glob('*_LST.tif'):
        m=PATTERN.fullmatch(p.name)
        if not m or int(m['orbit']) not in orbits:continue
        row=m.groupdict();row['LST']=str(p)
        key=(int(row['orbit']),int(row['scene']),row['tile'])
        priority=(int(row['build']),int(row['revision']))
        if key not in groups or priority>groups[key][0]:groups[key]=(priority,row)
    result=[]
    for _,row in groups.values():
        for name in ['QC','cloud','water']:
            row[name]=str(Path(raw)/(row['stem']+'_'+name+'.tif'))
        row['EmisWB']=str(Path(emissivity_root)/(row['stem']+'_EmisWB.tif'))
        missing=[k for k in ['LST','QC','cloud','water','EmisWB'] if not Path(row[k]).is_file()]
        if missing:raise FileNotFoundError(row['stem']+' missing '+','.join(missing))
        result.append(row)
    if set(orbits)-{int(r['orbit']) for r in result}:raise ValueError('An entire selected pass is missing')
    return result


def build_pass(bundles,domain,city,city_epsg,contexts, *, shifts=((0,0),)):
    domain=make_valid(shape(domain));frames={shift:[] for shift in shifts};audit=[]
    bytile=defaultdict(list)
    for b in bundles:bytile[b['tile']].append(b)
    for tile,scenes in sorted(bytile.items()):
        scenes=sorted(scenes,key=lambda x:(x['instant'],int(x['scene'])))
        with rasterio.open(scenes[0]['LST']) as ds:
            if not (np.isclose(ds.transform.a,70) and np.isclose(ds.transform.e,-70) and ds.transform.b==0 and ds.transform.d==0):raise ValueError('Expected native north-up 70m grid')
            g=make_valid(geom_transform(Transformer.from_crs(4326,ds.crs,always_xy=True).transform,domain))
            left=max(ds.bounds.left,g.bounds[0]);bottom=max(ds.bounds.bottom,g.bounds[1]);right=min(ds.bounds.right,g.bounds[2]);top=min(ds.bounds.top,g.bounds[3])
            if left>=right or bottom>=top:continue
            win=from_bounds(left,bottom,right,top,ds.transform)
            c0=max(0,int(np.floor(win.col_off)));r0=max(0,int(np.floor(win.row_off)));c1=min(ds.width,int(np.ceil(win.col_off+win.width)));r1=min(ds.height,int(np.ceil(win.row_off+win.height)))
            win=Window(c0,r0,c1-c0,r1-r0);tr=ds.window_transform(win);crs=ds.crs;shape_out=(r1-r0,c1-c0)
            reference=(ds.crs,ds.transform,ds.shape)
            core=(round(ds.bounds.left/1e5)*1e5,round(ds.bounds.bottom/1e5)*1e5,round(ds.bounds.left/1e5)*1e5+1e5,round(ds.bounds.bottom/1e5)*1e5+1e5)
        rr,cc=np.indices(shape_out);xs=tr.c+(cc+.5)*70;ys=tr.f-(rr+.5)*70
        inside=geometry_mask([mapping(g)],out_shape=shape_out,transform=tr,invert=True,all_touched=False)
        owner=native_owner(xs,ys,35,core,int(tile[:2]),crs)
        outT=np.full(shape_out,np.nan);outE=outT.copy();anybad=np.zeros(shape_out,bool);nvalid=0
        for scene in scenes:
            arrays={}
            for name in ['LST','QC','cloud','water','EmisWB']:
                with rasterio.open(scene[name]) as d:
                    if (d.crs,d.transform,d.shape)!=reference:raise ValueError('Paired layers/scenes must have exactly the same native grid')
                arrays[name]=read_scaled(scene[name],win)
            qc=arrays['QC'];qc_ok=np.isfinite(qc)&((np.nan_to_num(qc,nan=3).astype(np.uint32)&3)<=1)
            good=qc_ok&(arrays['cloud']==0)&(arrays['water']==0)&np.isfinite(arrays['LST'])&(arrays['LST']>0)&np.isfinite(arrays['EmisWB'])&(arrays['EmisWB']>0)&(arrays['EmisWB']<=1)
            anybad|=(np.isfinite(arrays['cloud'])&(arrays['cloud']!=0))|(np.isfinite(arrays['water'])&(arrays['water']!=0))
            outT[good]=arrays['LST'][good];outE[good]=arrays['EmisWB'][good];nvalid+=int((good&inside).sum())
        valid=inside&owner&~anybad&np.isfinite(outT)&np.isfinite(outE)
        ctx=contexts.at(shape_out,tr,crs)
        cx,cy=Transformer.from_crs(crs,city_epsg,always_xy=True).transform(xs,ys)
        bx=np.floor(cx/1000).astype(int);by=np.floor(cy/1000).astype(int)
        for dx,dy in shifts:
            selected={name:(a if (dx,dy)==(0,0) else shifted(a,dx,dy)) for name,a in ctx.items() if name in ['canopy_fraction',*CONTEXT]}
            mask=valid.copy()
            for a in selected.values():mask&=np.isfinite(a)
            data={k:v[mask] for k,v in selected.items()}
            data.update(LST_K=outT[mask],emissivity=outE[mask],x=cx[mask],y=cy[mask],tile=tile,native_crs=str(crs),native_x=xs[mask],native_y=ys[mask])
            data['block']=[f'{a}_{b}' for a,b in zip(bx[mask],by[mask])]
            data['block_2km']=[f'{a//2}_{b//2}' for a,b in zip(bx[mask],by[mask])]
            data['cell_id']=[f'{tile}:{a}:{b}' for a,b in zip((rr+r0)[mask],(cc+c0)[mask])]
            data['M_W_m2']=emitted_energy(data['LST_K'],data['emissivity'])
            frames[(dx,dy)].append(pd.DataFrame(data))
        audit.append({'city':city,'tile':tile,'scenes':len(scenes),'raw_scene_valid_cells_in_domain':nvalid,'native_centers_in_domain':int(inside.sum()),'overlap_or_seam_cells_excluded':int((inside&~owner).sum()),'unique_QA_valid_before_context':int(valid.sum()),'paired_complete_primary':len(frames[(0,0)][-1]),'native_area_m2':4900,'ownership':'whole_footprint_inside_canonical_core_and_UTM_band'})
    result={k:pd.concat(v,ignore_index=True) for k,v in frames.items()}
    for f in result.values():
        if f.cell_id.duplicated().any() or f[['native_crs','native_x','native_y']].duplicated().any():raise ValueError('Duplicate native ground cells remain')
    return result,audit
