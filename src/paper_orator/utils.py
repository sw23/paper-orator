# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Utility functions for document content processing."""

import re


def is_text_in_table(text_polygon: list, table_polygon: list) -> bool:
    """Check if a text polygon is contained within a table polygon.

    Each polygon is a list of 8 values representing 4 (x, y) coordinate pairs
    defining a quadrilateral bounding region.

    Args:
        text_polygon: 8-element list of coordinates for the text region.
        table_polygon: 8-element list of coordinates for the table region.

    Returns:
        True if all points of the text polygon fall within the table polygon.
    """
    if len(text_polygon) != 8 or len(table_polygon) != 8:
        return False
    for i in range(0, 8, 2):
        if (text_polygon[i] < table_polygon[0] or text_polygon[i] > table_polygon[4] or
                text_polygon[i + 1] < table_polygon[1] or text_polygon[i + 1] > table_polygon[5]):
            return False
    return True


def clean_table_cell(cell_content: str) -> str:
    """Clean table cell content by removing unwanted characters.

    Removes newlines, checkbox markers (:unselected:/:selected:), pipe
    characters, and markdown bold formatting. Strips leading/trailing whitespace.

    Args:
        cell_content: Raw cell content string.

    Returns:
        Cleaned cell content string.
    """
    cell_content = re.sub(r'(\n|:unselected:|:selected:|\|)', ' ', cell_content)
    cell_content = re.sub(r'\*?\*(.*?)\*\*?', r'\1', cell_content)
    cell_content = cell_content.strip()
    return cell_content
