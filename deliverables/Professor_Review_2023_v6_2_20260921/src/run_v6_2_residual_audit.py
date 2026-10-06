#!/usr/bin/env python3
"""Report residual neighbor dependence without exposing fitted effects.

Adds prespecified 4km and 8km uncertainty stress checks; these do not change the
1km-intercept mean model, select passes, or replace the primary precision rule.
"""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from urban_cooling_v2.pooled_city_pass import fit_city_pass,public_precision
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path

def run(manifest):
 c=json.loads(manifest.read_text());root=Path(c['repository']);P=lambda name:guarded_output_path(root,'scientific',c['run_id']+'/'+name);S=lambda name:guarded_output_path(root,'sealed',c['run_id']+'/'+name)
 records=[];stress=[]
 for orbit in c['orbits']:
  d=pd.read_parquet(S(f'{orbit}_paired_native_cells_SEALED.parquet'))
  with np.load(S(f'{orbit}_paired_primary_SEALED.npz'),allow_pickle=True) as z:
   names=list(z['predictor_names']);lookup={b:i for i,b in enumerate(z['block_labels'])};bi=np.array([lookup[b] for b in d.block]);x=d[names].to_numpy();y=d[['LST_K','M_W_m2']].to_numpy();res=y-z['block_y_means'][bi]-(x-z['block_x_means'][bi])@z['coefficients']
  pair_parts=[]
  for tile,ids in d.groupby('tile').indices.items():
   q=d.iloc[ids];gx=np.rint((q.native_x-q.native_x.min())/70).astype(int).to_numpy();gy=np.rint((q.native_y-q.native_y.min())/70).astype(int).to_numpy();width=gx.max()+2
   keys=gy*width+gx;order=np.argsort(keys);sortedkeys=keys[order]
   for delta in [1,width]:
    target=keys+delta;idx=np.searchsorted(sortedkeys,target);inside=idx<len(order);found=np.zeros(len(idx),bool);found[inside]=sortedkeys[idx[inside]]==target[inside]
    i=np.flatnonzero(found);j=order[idx[found]];pair_parts.append(np.column_stack([ids[i],ids[j]]))
  pairs=np.vstack(pair_parts)
  for size in [1,2]:
   bx=np.floor(d.x.to_numpy()/(size*1000));by=np.floor(d.y.to_numpy()/(size*1000));cross=(bx[pairs[:,0]]!=bx[pairs[:,1]])|(by[pairs[:,0]]!=by[pairs[:,1]])
   chosen=pairs[cross]
   record={'city':c['city'],'orbit':orbit,'boundary_km':size,'cross_boundary_neighbor_pairs':len(chosen),'interpretation':'cardinal_neighbor_dependence_not_a_pvalue_or_effect_sign'}
   for k,outcome in enumerate(['LST_K','M_W_m2']):record[outcome+'_residual_cross_boundary_correlation']=float(np.corrcoef(res[chosen[:,0],k],res[chosen[:,1],k])[0,1]) if len(chosen)>1 else None
   records.append(record)
  for size in [4,8]:
   d['stress_group']=[f'{x}_{y}' for x,y in zip(np.floor(d.x/(size*1000)).astype(int),np.floor(d.y/(size*1000)).astype(int))]
   fit=fit_city_pass(d,cluster_column='stress_group',bootstrap_replicates=1000,seed=20260919)
   stress.append(public_precision(fit,city=c['city'],pass_id=f'{c["city"]}:{orbit}',variant=f'spatial_{size}km'))
   dest=S(f'{orbit}_spatial_{size}km_SEALED.npz');np.savez_compressed(dest,coefficients=fit.coefficients,bootstrap_coefficients=fit.bootstrap_coefficients);dest.chmod(0o600)
  pd.DataFrame(records).to_csv(P('residual_spatial_diagnostics.csv'),index=False);pd.DataFrame(stress).to_csv(P('spatial_stress_precision.csv'),index=False)
  print(json.dumps({'city':c['city'],'orbit':orbit,'completed':'residual_dependence_and_4km_8km_precision'}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);args=p.parse_args();run(args.manifest)
