"""Manual-backed display text must describe effects without changing items."""
from pathlib import Path
import unittest

from deploy.item_effect_descriptions import load_descriptions, extend_language

ROOT = Path(__file__).resolve().parents[1]


class ItemEffectDescriptionTests(unittest.TestCase):
    def test_trainers_state_original_experience_rates_and_one_hour(self):
        rows = load_descriptions(ROOT)['ru']
        for identity, percent in ((5003, 30), (5004, 50), (5005, 100)):
            self.assertEqual(rows[identity], (f'Получаемый опыт: +{percent}%',
                                             'Время действия: 1 час.'))

    def test_capacity_injection_is_distinct_from_medical_injection(self):
        rows = load_descriptions(ROOT)['ru']
        self.assertEqual(rows[5012], ('Максимальное здоровье: +10%',
                                     'Цена применения: 8 AP', 'Действует 10 ходов',
                                     'Восстанавливается 15 ходов'))
        self.assertNotIn(20, rows)  # Original Health Injection heals100.

    def test_vision_uses_original_sight_duration_and_cooldown(self):
        self.assertEqual(load_descriptions(ROOT)['ru'][35],
                         ('Дальность обзора: +1 клетка', 'Цена применения: 10 AP',
                          'Действует 10 ходов', 'Восстанавливается 15 ходов'))

    def test_rank_boosters_use_points_and_blockers_keep_original_durations(self):
        rows = load_descriptions(ROOT)['en']
        self.assertEqual(rows[5006][0], 'Rank points earned: +5')
        self.assertEqual(rows[5007][0], 'Rank points earned: +10')
        self.assertEqual(rows[5008][0], 'Rank points earned: +20')
        for identity, hours in ((5009, 1), (5010, 2), (5011, 8)):
            self.assertEqual(rows[identity], ('Blocks experience gain', f'Duration: {hours} h'))

    def test_localization_is_additive_and_preserves_existing_healing_string(self):
        raw = b'[language]\r\nc026=Heals %s hp\r\n'
        result = extend_language(raw, 'en', load_descriptions(ROOT)['en'])
        self.assertTrue(result.startswith(raw))
        self.assertIn(b'tio_item_effect_5012_0=Maximum health: +10%', result)
        self.assertEqual(extend_language(result, 'en', load_descriptions(ROOT)['en']), result)

    def test_foreign_existing_description_is_not_silently_overwritten(self):
        raw = b'[language]\r\ntio_item_effect_5012_0=Different\r\n'
        with self.assertRaises(ValueError):
            extend_language(raw, 'en', load_descriptions(ROOT)['en'])


if __name__ == '__main__':
    unittest.main()
