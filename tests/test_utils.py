"""Tests for document processing utilities."""

from paper_orator.utils import clean_table_cell, is_text_in_table

TABLE = [0, 0, 10, 0, 10, 10, 0, 10]


def test_text_inside_table():
    assert is_text_in_table([1, 1, 5, 1, 5, 2, 1, 2], TABLE)


def test_text_outside_table():
    assert not is_text_in_table([11, 1, 15, 1, 15, 2, 11, 2], TABLE)


def test_text_partially_outside_table():
    assert not is_text_in_table([5, 5, 12, 5, 12, 6, 5, 6], TABLE)


def test_invalid_polygon_lengths():
    assert not is_text_in_table([1, 2, 3], TABLE)
    assert not is_text_in_table([1, 1, 5, 1, 5, 2, 1, 2], [0, 0])


def test_clean_table_cell():
    cleaned = clean_table_cell("  **Bold**\nvalue :selected: | x ")
    assert cleaned.split() == ["Bold", "value", "x"]
    assert clean_table_cell(":unselected:") == ""
