"""Tests for dice and damage rules."""

import pytest

from engine.rules import Dice, SEVERITY_DAMAGE, damage_for


class TestDiceSeeded:
    def test_same_seed_same_sequence(self):
        d1 = Dice(seed=42)
        d2 = Dice(seed=42)
        seq1 = [d1.roll(100) for _ in range(10)]
        seq2 = [d2.roll(100) for _ in range(10)]
        assert seq1 == seq2

    def test_different_seeds_different_sequences(self):
        d1 = Dice(seed=1)
        d2 = Dice(seed=2)
        seq1 = [d1.roll(100) for _ in range(10)]
        seq2 = [d2.roll(100) for _ in range(10)]
        assert seq1 != seq2

    def test_roll_range(self):
        d = Dice(seed=0)
        for _ in range(100):
            r = d.roll(6)
            assert 1 <= r <= 6

    def test_roll_die_parsing(self):
        d = Dice(seed=99)
        for _ in range(50):
            r = d.roll_die("2d4")
            assert 2 <= r <= 8

    def test_roll_die_single(self):
        d = Dice(seed=7)
        for _ in range(50):
            r = d.roll_die("d6")
            assert 1 <= r <= 6

    def test_roll_die_invalid(self):
        d = Dice()
        with pytest.raises(ValueError):
            d.roll_die("not_dice")


class TestDamageFor:
    def test_minor_range(self):
        d = Dice(seed=1)
        for _ in range(50):
            assert 1 <= damage_for("minor", d) <= 4

    def test_major_range(self):
        d = Dice(seed=1)
        for _ in range(50):
            assert 1 <= damage_for("major", d) <= 8

    def test_critical_range(self):
        d = Dice(seed=1)
        for _ in range(50):
            assert 2 <= damage_for("critical", d) <= 20

    def test_unknown_severity_defaults(self):
        d = Dice(seed=1)
        result = damage_for("unknown", d)
        assert 1 <= result <= 4
