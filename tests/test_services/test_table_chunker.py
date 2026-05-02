# tests/test_services/test_table_chunker.py
from app.services.table_chunker import TableChunker


def test_chunk_tables_emits_one_whole_and_one_row_per_data_row():
    table_pages = [{
        "page_number": 7,
        "tables": [{
            "bbox": (50.0, 100.0, 400.0, 300.0),
            "header": ["Bolt", "Torque (Nm)"],
            "rows": [
                ["Bolt", "Torque (Nm)"],   # header row repeated as first data row
                ["Cylinder head", "129"],
                ["Valve cover", "10"],
            ],
        }],
    }]
    chunks = TableChunker().chunk_tables(table_pages, base_chunk_index=0, section_titles_by_page={7: "TORQUE SPECS"})

    kinds = [c["chunk_kind"] for c in chunks]
    assert kinds.count("table_whole") == 1
    assert kinds.count("table_row") == 2  # header row dropped

    whole = next(c for c in chunks if c["chunk_kind"] == "table_whole")
    assert whole["page_number"] == 7
    assert "Cylinder head" in whole["content"]
    assert "129" in whole["content"]
    assert whole["section_title"] == "TORQUE SPECS"

    rows = [c for c in chunks if c["chunk_kind"] == "table_row"]
    assert any("Cylinder head" in r["content"] and "129" in r["content"] for r in rows)
    assert all(r["table_id"] == whole["table_id"] for r in rows)


def test_chunk_tables_handles_missing_header_by_using_index_columns():
    table_pages = [{
        "page_number": 1,
        "tables": [{
            "bbox": (0, 0, 100, 100),
            "header": None,
            "rows": [
                ["a", "1"],
                ["b", "2"],
            ],
        }],
    }]
    chunks = TableChunker().chunk_tables(table_pages, base_chunk_index=10, section_titles_by_page={})

    rows = [c for c in chunks if c["chunk_kind"] == "table_row"]
    assert len(rows) == 2
    assert rows[0]["chunk_index"] >= 10
    # When header is unknown, fall back to col_1, col_2…
    assert "col_1" in rows[0]["content"]
    assert "col_2" in rows[0]["content"]


def test_chunk_tables_returns_table_bboxes_for_prose_exclusion():
    """The chunker also reports per-page table bboxes so prose chunking can skip them."""
    table_pages = [{
        "page_number": 4,
        "tables": [
            {"bbox": (10, 20, 30, 40), "header": ["x"], "rows": [["x"], ["a"]]},
            {"bbox": (50, 60, 70, 80), "header": ["y"], "rows": [["y"], ["b"]]},
        ],
    }]
    chunker = TableChunker()
    chunks = chunker.chunk_tables(table_pages, base_chunk_index=0, section_titles_by_page={})
    bboxes = chunker.bboxes_by_page(table_pages)

    assert bboxes[4] == [(10, 20, 30, 40), (50, 60, 70, 80)]
