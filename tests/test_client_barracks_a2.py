"""Responsive barracks placement retains bounded native control geometry."""
import unittest

from deploy.client_barracks_a2 import bag_cells, bag_viewport, equipment_slots, layout


class BarracksLayoutTests(unittest.TestCase):
    def test_scrollbar_does_not_clip_the_fourth_backpack_column(self):
        for width in (330, 430):
            viewport = bag_viewport(width)
            right = max(cell.x+cell.width for cell in bag_cells(width))
            self.assertLessEqual(right, viewport.x+viewport.width-16)
            self.assertLessEqual(viewport.x+viewport.width, width)

    def test_reference_armour_is_a_vertical_column_beside_weapons(self):
        slots = equipment_slots(430)
        self.assertEqual([(r.x, r.y, r.width, r.height) for r in slots[:3]],
                         [(18, 50, 110, 76), (18, 136, 110, 76),
                          (18, 222, 110, 76)])
        self.assertEqual([(r.x, r.y) for r in slots[3:]],
                         [(142, 50), (142, 136), (142, 222)])

    def test_full_hd_uses_the_reference_content_canvas(self):
        plan = layout(1728, 768)
        self.assertEqual(tuple(vars(plan['equipment']).values()), (50, 118, 430, 558))
        self.assertEqual(plan['model'].width, 600)
        self.assertEqual(plan['tabs'].height, 56)

    def test_right_column_spans_the_full_content_height(self):
        for size in ((1728, 768), (1344, 544)):
            plan = layout(*size)
            self.assertEqual(plan['right'].y, plan['equipment'].y)
            self.assertEqual(plan['right'].y+plan['right'].height,
                             plan['equipment'].y+plan['equipment'].height)

    def test_reference_bag_has_twelve_bounded_cells_in_four_columns(self):
        cells = bag_cells(430)
        self.assertEqual(len(cells), 12)
        self.assertEqual(len({r.x for r in cells}), 4)
        self.assertEqual(len({r.y for r in cells}), 3)
        self.assertTrue(all(r.height == 56 and r.x+r.width <= 412
                            for r in cells))

    def test_compact_equipment_and_backpack_fit_the_short_canvas(self):
        self.assertLessEqual(max(r.y+r.height for r in equipment_slots(330)),228)
        self.assertLessEqual(max(r.y+r.height for r in bag_cells(330)),394)

    def test_full_hd_has_separate_equipment_model_and_right_column(self):
        plan=layout(1728,768)
        self.assertIsNotNone(plan)
        left=plan['equipment'];model=plan['model'];right=plan['right']
        self.assertLessEqual(left.x+left.width,model.x)
        self.assertLessEqual(model.x+model.width,right.x)
        self.assertLessEqual(right.x+right.width,1728)

    def test_compact_layout_fits_effective_full_hd_125_percent(self):
        plan=layout(1344,544)
        self.assertIsNotNone(plan)
        for rect in plan.values():
            self.assertGreater(rect.width,0)
            self.assertGreater(rect.height,0)
            self.assertGreaterEqual(rect.x,0)
            self.assertGreaterEqual(rect.y,0)
            self.assertLessEqual(rect.x+rect.width,1344)
            self.assertLessEqual(rect.y+rect.height,544)

    def test_small_canvas_keeps_the_existing_native_layout(self):
        self.assertIsNone(layout(800,448))

    def test_tabs_sit_under_the_soldier_inside_the_centre_stage(self):
        for size in ((1728, 768), (1344, 544), (1516, 640), (2368, 1120)):
            plan = layout(*size)
            tabs, model = plan['tabs'], plan['model']
            self.assertGreaterEqual(tabs.y, model.y+model.height, size)
            self.assertGreaterEqual(tabs.x, plan['equipment'].x+plan['equipment'].width, size)
            self.assertLessEqual(tabs.x+tabs.width, plan['right'].x, size)


if __name__=='__main__':
    unittest.main()
