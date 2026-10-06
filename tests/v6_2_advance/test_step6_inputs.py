import unittest
import numpy as np
import pandas as pd
from v6_2_advance.step6_inputs import (
 timestamp, brackets, interpolate, vpd_kpa, rain_hours, accumulate_rain, grib_ranges,
 window_plan, assert_nonthermal_columns, solar_geometry, WEIGHTS,
)

class Step6Tests(unittest.TestCase):
 def test_subsecond_brackets_and_timezone(self):
  lo,hi,w=brackets('2023-06-26T13:55:48.103-04:00')
  self.assertEqual(lo,pd.Timestamp('2023-06-26T17:00:00Z'));self.assertAlmostEqual(w,(55*60+48.103)/3600)
  self.assertEqual(brackets('2023-06-26T17:00:00Z')[2],0)
  with self.assertRaises(ValueError):timestamp('2023-06-26')
 def test_interpolation_and_missing_bracket(self):
  d=pd.DataFrame({'T':[300.,304.]},index=pd.to_datetime(['2023-01-01T00:00Z','2023-01-01T01:00Z']))
  self.assertEqual(interpolate('2023-01-01T00:15Z',d,['T']),{'T':301.})
  self.assertIsNone(interpolate('2023-01-01T01:15Z',d,['T']))
  with self.assertRaises(ValueError):interpolate('2023-01-01T00:15Z',pd.concat([d,d]),['T'])
 def test_vpd_kelvin_and_cell_average(self):
  # FAO saturation pressures at 20 C and 10 C are 2.33828127 and 1.22796262 kPa.
  self.assertAlmostEqual(float(vpd_kpa(293.15,283.15)),1.11031865,places=7)
  self.assertEqual(float(vpd_kpa(300,301)),0)
  with self.assertRaises(ValueError):vpd_kpa(-1,300)
  a=vpd_kpa([285,315],[280,300]).mean();b=float(vpd_kpa(300,290))
  self.assertGreater(abs(a-b),.05)
 def test_rain_window_has_no_future_or_double_count(self):
  t='2023-01-08T00:59:59Z';h=rain_hours(t,7)
  self.assertEqual(len(h),168);self.assertEqual(h[0],pd.Timestamp('2023-01-01T01:00Z'))
  self.assertLess(h[-1],timestamp(t));self.assertEqual(len(set(h)),168)
  with self.assertRaises(ValueError):rain_hours(t,2)
 def test_area_weighted_accumulation_known_answer(self):
  h=rain_hours('2023-01-02T00:00Z',1);a=np.tile([1.,3.],(24,1))
  q=accumulate_rain(a,h,h,[1,3]);self.assertEqual(q['total_mm'],60);self.assertEqual(q['complete_cell_fraction'],1)
 def test_missing_and_negative_rain_are_not_zero_filled(self):
  h=rain_hours('2023-01-02T00:00Z',1);a=np.ones((24,2));a[2,0]=-1
  q=accumulate_rain(a,h,h,[1,1]);self.assertIsNone(q['total_mm']);self.assertEqual(q['complete_cell_fraction'],.5)
  q=accumulate_rain(a[:-1],h[:-1],h,[1,1]);self.assertIsNone(q['total_mm']);self.assertEqual(q['available_hours'],23)
  with self.assertRaises(ValueError):accumulate_rain(np.ones((25,2)),h.append(h[:1]),h,[1,1])
 def test_range_selection_excludes_unrequested_fields(self):
  idx='1:0:d=2023062600:TMP:2 m above ground:anl:\n2:100:d=2023062600:DPT:2 m above ground:anl:\n3:250:d=2023062600:TMP:surface:anl:\n'
  self.assertEqual(grib_ranges(idx,{'t':('TMP','2 m above ground'),'d':('DPT','2 m above ground')}),{'t':(0,99),'d':(100,249)})
  with self.assertRaises(ValueError):grib_ranges(idx,{'u':('UGRD','10 m above ground')})
 def test_fixed_weights_and_no_city_pooling(self):
  p=pd.DataFrame([dict(city='phoenix',orbit=o,apparent_solar_hour=16 if w>0 else 10) for o,w in WEIGHTS.items()]+[dict(city='atlanta',orbit=1,apparent_solar_hour=10)])
  q=window_plan(p);self.assertEqual(q[q.city.eq('atlanta')].window_weight.iloc[0],0)
  p.loc[0,'apparent_solar_hour']=12
  with self.assertRaises(ValueError):window_plan(p)
 def test_output_access_columns(self):
  assert_nonthermal_columns(['city','orbit','acquisition_utc'])
  for col in ('LST_K','cooling_K_per_10pp','coefficients'):
   with self.assertRaises(ValueError):assert_nonthermal_columns([col])
 def test_solar_geometric_bounds(self):
  zen,az=solar_geometry(0,12,80);self.assertLess(zen,1)
  zen,az=solar_geometry(0,6,80);self.assertAlmostEqual(zen,90,places=5);self.assertAlmostEqual(az,90,delta=1)

if __name__=='__main__':unittest.main()
