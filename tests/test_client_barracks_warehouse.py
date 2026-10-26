"""The A2 warehouse column gives the grid the full height of the column."""
import unittest

from deploy.client_barracks_warehouse import BAR, COLUMN_BOTTOM, COLUMN_TOP, counter_offset, plan


def resolve(value, height: int) -> int:
    """TABLE-local value for a page of the given (already clamped) height."""
    if isinstance(value, int):
        return value
    axis, divisor, offset = value
    assert axis == 'h'
    return height//divisor+offset


class WarehousePlanTests(unittest.TestCase):
    HEIGHTS = {554: 682, 430: 544}

    def boxes(self, right):
        height = self.HEIGHTS[right]
        return {name: tuple(resolve(v, height) for v in rect) for name, rect in plan(right).items()}, height-COLUMN_BOTTOM

    def test_grid_uses_the_whole_column_width(self):
        for right in (554, 430):
            boxes, _ = self.boxes(right)
            self.assertEqual(boxes['grid'][2], right)

    def test_grid_sits_between_the_top_bar_and_the_bottom_rows(self):
        for right in (554, 430):
            boxes, table = self.boxes(right)
            x, y, w, h = boxes['grid']
            self.assertGreaterEqual(y, BAR)
            counter_y = table-counter_offset()[1]
            self.assertLessEqual(y+h, counter_y)
            self.assertLessEqual(counter_y+16, boxes['footer'][1])

    def test_full_hd_grid_is_much_taller_than_the_previous_one(self):
        boxes, _ = self.boxes(554)
        # The previous A2 grid was 404x~430 beside a 144 px category column.
        self.assertGreater(boxes['grid'][2]*boxes['grid'][3], 404*430)

    def test_filter_list_drops_down_over_the_grid(self):
        for right in (554, 430):
            boxes, _ = self.boxes(right)
            fx, fy, fw, fh = boxes['filters']
            gx, gy, gw, gh = boxes['grid']
            self.assertEqual(fy, BAR+2)
            self.assertLess(fw, gw)
            self.assertLessEqual(fy+fh, gy+gh)

    def test_top_bar_controls_do_not_overlap(self):
        for right in (554, 430):
            boxes, _ = self.boxes(right)
            toggle, owners, tag = boxes['toggle'], boxes['owners'], boxes['tag_frame']
            self.assertLessEqual(toggle[0]+toggle[2], owners[0])
            self.assertLessEqual(owners[0]+owners[2], tag[0])
            self.assertEqual(tag[0]+tag[2], right)
            # 'Метка: Все меченые' is the longest native tag caption.
            self.assertGreaterEqual(tag[2], 110)

    def test_search_shares_the_counter_row_on_the_right(self):
        for right in (554, 430):
            boxes, table = self.boxes(right)
            caption, search, grid = boxes['search_caption'], boxes['search'], boxes['grid']
            self.assertEqual(search[0]+search[2], right)
            self.assertLessEqual(caption[0]+caption[2], search[0])
            self.assertGreaterEqual(search[1], grid[1]+grid[3])
            self.assertLessEqual(search[1]+search[3], boxes['footer'][1])
            # The counter text on the left ends well before the search caption.
            self.assertGreater(caption[0], counter_offset()[0]+110)

    def test_refresh_is_in_the_bottom_right_corner(self):
        for right in (554, 430):
            boxes, table = self.boxes(right)
            x, y, w, h = boxes['refresh']
            self.assertGreaterEqual(x+w, right-8)
            self.assertGreaterEqual(y+h, table-8)

    def test_column_starts_where_the_equipment_panel_starts(self):
        self.assertEqual(COLUMN_TOP, 112)


if __name__ == '__main__':
    unittest.main()
