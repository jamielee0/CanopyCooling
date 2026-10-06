import unittest,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(next(p/'src' for p in Path(__file__).resolve().parents if (p/'src/urban_cooling_v2').is_dir())))
import numpy as np,rasterio
from rasterio.transform import from_origin
from urban_cooling_v2.pilot_native import average_to_grid,shifted,native_owner,read_scaled
class NativeTests(unittest.TestCase):
 def test_area_average_known_grid(self):
  a=np.array([[0,1],[.2,.6]],np.float32)
  b=average_to_grid(a,from_origin(400000,3700000,35,35),'EPSG:32612',(1,1),from_origin(400000,3700000,70,70),'EPSG:32612')
  self.assertAlmostEqual(b[0,0],.45,places=6)
 def test_shift_no_wrap(self):
  a=np.arange(9,dtype=float).reshape(3,3);b=shifted(a,1,0)
  self.assertTrue(np.isnan(b[:,0]).all());np.testing.assert_equal(b[:,1:],a[:,:-1])
 def test_ownership_excludes_partial_core_overlap(self):
  x=np.array([399950,399980,400020,400050]);y=np.repeat(3650000,4)
  a=native_owner(x,y,35,(300000,3600000,400000,3700000),12,'EPSG:32612')
  b=native_owner(x,y,35,(400000,3600000,500000,3700000),12,'EPSG:32612')
  np.testing.assert_equal(a,[True,False,False,False]);np.testing.assert_equal(b,[False,False,False,True]);self.assertFalse((a&b).any())
 def test_scaling_and_fill(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'scaled.tif'
   with rasterio.open(p,'w',driver='GTiff',height=1,width=2,count=1,dtype='uint16',crs='EPSG:32612',transform=from_origin(400000,3700000,70,70),nodata=65535) as d:
    d.write(np.array([[250,65535]],np.uint16),1);d.scales=(.002,);d.offsets=(.49,)
   a=read_scaled(p);self.assertAlmostEqual(a[0,0],.99);self.assertTrue(np.isnan(a[0,1]))
class SceneTests(unittest.TestCase):
 def test_scene_choice_paired_masks_and_no_duplicate_cells(self):
  from urban_cooling_v2.pilot_native import build_pass,CONTEXT
  from pyproj import Transformer
  from shapely.geometry import box,mapping
  from shapely.ops import transform
  class Context:
   def at(self,shape,tr,crs):
    return {'canopy_fraction':np.full(shape,.2),**{k:np.zeros(shape) for k in CONTEXT}}
  with tempfile.TemporaryDirectory() as temp:
   bundles=[]
   for scene in [1,2]:
    row={'tile':'12SVB','instant':f'20230101T12000{scene}','scene':str(scene)}
    for name in ['LST','QC','cloud','water','EmisWB']:
     a=np.full((3,3),301.+scene if name=='LST' else .97 if name=='EmisWB' else 0.)
     if name=='cloud' and scene==1:a[1,1]=1
     p=Path(temp)/f'{scene}_{name}.tif'
     with rasterio.open(p,'w',driver='GTiff',height=3,width=3,count=1,dtype='float32',crs='EPSG:32612',transform=from_origin(400000,3650210,70,70)) as d:d.write(a.astype('float32'),1)
     row[name]=str(p)
    bundles.append(row)
   g=transform(Transformer.from_crs(32612,4326,always_xy=True).transform,box(399999,3649999,400211,3650211))
   frames,audit=build_pass(bundles,mapping(g),'test',32612,Context())
   f=frames[(0,0)];self.assertEqual(len(f),8);self.assertFalse(f.cell_id.duplicated().any());self.assertTrue((f.LST_K==303).all())
   self.assertTrue((f.emissivity>.96).all());self.assertEqual(audit[0]['scenes'],2)

if __name__=='__main__':unittest.main()
