# Copyright (c) 2025 Spencer Williams
# Licensed under the MIT License. See LICENSE file in the project root.

"""Azure Document Intelligence provider for PDF content extraction."""

import base64
import logging
import os

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeOutputOption
from azure.core.credentials import AzureKeyCredential

from paper_orator.providers.base import DocumentExtractor, PageContent
from paper_orator.utils import clean_table_cell, is_text_in_table

logger = logging.getLogger(__name__)


class AzureDocumentExtractor(DocumentExtractor):
    """Extracts text, tables, and figures from PDFs using Azure Document Intelligence."""

    def __init__(self, config: dict):
        """Initialize with Azure Document Intelligence credentials.

        Args:
            config: Dict with keys 'endpoint' and 'key'.
        """
        self.endpoint = config["endpoint"]
        self.key = config["key"]

    def extract(self, pdf_path: str, output_dir: str) -> PageContent:
        client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.key),
        )
        with open(pdf_path, "rb") as f:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=f,
                output=[AnalyzeOutputOption.FIGURES],
            )
            result = poller.result()

        operation_id = poller.details["operation_id"]

        # --- Process tables ---
        table_contents = []
        if result.tables:
            for table_idx, table in enumerate(result.tables):
                num_cols = max(cell.column_index for cell in table.cells) + 1
                num_rows = max(cell.row_index for cell in table.cells) + 1
                table_content = [["" for _ in range(num_cols)] for _ in range(num_rows)]
                for cell in table.cells:
                    table_content[cell.row_index][cell.column_index] = cell.content

                table_md = ""
                for row in range(num_rows):
                    table_md += "| " + " | ".join(
                        clean_table_cell(table_content[row][col]) for col in range(num_cols)
                    ) + " |\n"

                table_path = os.path.join(output_dir, f"table_{table_idx}.txt")
                with open(table_path, "w") as f:
                    f.write(f"Table Content:\n{table_md}")

                page_idx = table.bounding_regions[0].page_number - 1
                polygon = table.bounding_regions[0].polygon
                table_contents.append([page_idx, False, polygon, f"[Table {table_idx}]:\n{table_md}"])

        # --- Process figures ---
        figure_contents = []
        result_figures = result.figures or []
        for figure_idx, figure in enumerate(result_figures):
            if not figure.id:
                logger.warning(f"Figure {figure_idx} has no ID, skipping extraction")
                continue

            response = client.get_analyze_result_figure(
                model_id=result.model_id,
                result_id=operation_id,
                figure_id=figure.id,
            )
            image_bytes = b"".join(response)

            figure_path = os.path.join(output_dir, f"figure_{figure_idx}.png")
            with open(figure_path, "wb") as writer:
                writer.write(image_bytes)

            image_data = base64.b64encode(image_bytes).decode("utf-8")
            page_idx = figure.bounding_regions[0].page_number - 1
            polygon = figure.bounding_regions[0].polygon

            figure_content = {
                "type": "image",
                "index": figure_idx,
                "data": image_data,
                "path": figure_path,
            }
            figure_contents.append([page_idx, False, polygon, figure_content])

        # --- Assemble page content ---
        page_lines: PageContent = []
        for page_idx, page in enumerate(result.pages):
            new_page_lines: list = []
            for line in page.lines:
                skip_line = False

                # Check if line is within a table
                for table in table_contents:
                    if table[0] == page_idx and is_text_in_table(line.polygon, table[2]):
                        if not table[1]:
                            table[1] = True
                            new_page_lines.append(table[3])
                        skip_line = True
                        break

                # Check if line is within a figure
                if not skip_line:
                    for figure in figure_contents:
                        if figure[0] == page_idx and is_text_in_table(line.polygon, figure[2]):
                            if not figure[1]:
                                figure[1] = True
                                new_page_lines.append(figure[3])
                            skip_line = True
                            break

                if not skip_line:
                    new_page_lines.append(line.content)

            # Append any tables/figures not already placed on this page
            for table in table_contents:
                if table[0] == page_idx and not table[1]:
                    new_page_lines.append(table[3])
            for figure in figure_contents:
                if figure[0] == page_idx and not figure[1]:
                    new_page_lines.append(figure[3])

            page_lines.append(new_page_lines)

        return page_lines
