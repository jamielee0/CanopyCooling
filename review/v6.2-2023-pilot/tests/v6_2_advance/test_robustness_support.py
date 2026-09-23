import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import pandas as pd
from v6_2_advance.run_robustness_completion import common_ids, restrict_ids


class FootprintTests(unittest.TestCase):
    def test_intersection_and_stable_order(self):
        a = pd.DataFrame({'cell_id':['c','b','a'], 'value':[30,20,10]})
        b = pd.DataFrame({'cell_id':['d','a','c'], 'value':[4,1,3]})
        ids = common_ids([a,b])
        self.assertEqual(ids, ['a','c'])
        self.assertEqual(restrict_ids(a,ids).value.tolist(), [10,30])
        self.assertEqual(restrict_ids(b,ids).value.tolist(), [1,3])
    def test_duplicate_cells_are_not_silently_deduplicated(self):
        with self.assertRaises(ValueError):
            common_ids([pd.DataFrame({'cell_id':['a','a']})])
    def test_empty_common_support_is_preserved(self):
        a = pd.DataFrame({'cell_id':['a'], 'value':[1]})
        b = pd.DataFrame({'cell_id':['b'], 'value':[2]})
        self.assertEqual(common_ids([a,b]), [])
        self.assertEqual(len(restrict_ids(a,[])), 0)


if __name__ == '__main__':
    unittest.main()
