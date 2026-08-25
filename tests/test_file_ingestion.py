import pytest
from pathlib import Path
from app.tools.file_tools import FileIngestionService
from app.tools.profiling_tools import DatasetProfiler


@pytest.mark.asyncio
async def test_csv_ingestion_and_profiling(db_session, tmp_path):
    project_id = "proj_test_csv"
    csv_content = b"sku,dc,qty_demanded,qty_fulfilled,lead_time\nSKU01,RNO,100,90,5\nSKU02,CHI,50,50,7\nSKU03,ATL,0,0,4\nSKU04,DEN,200,180,10\n"

    # Ingest file
    file_record = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project_id,
        filename="test_demand.csv",
        content_bytes=csv_content,
    )

    assert file_record.filename == "test_demand.csv"
    assert file_record.file_type == "csv"
    assert file_record.row_count == 4
    assert file_record.column_count == 5

    # Run profiler
    raw_path = Path(file_record.raw_path)
    assert raw_path.exists()

    summary = DatasetProfiler.profile_tabular_file(
        file_path=raw_path,
        file_id=file_record.id,
        business_rules=[
            {
                "name": "Fulfilled should not exceed Demanded",
                "expression": "qty_fulfilled <= qty_demanded",
                "columns": ["qty_fulfilled", "qty_demanded"],
            }
        ],
    )

    assert summary.row_count == 4
    assert summary.column_count == 5
    assert summary.duplicate_rows_count == 0
    assert "sku" in summary.potential_grain
    assert len(summary.columns) == 5

    # Verify column profile
    sku_col = next(c for c in summary.columns if c.name == "sku")
    assert sku_col.null_count == 0
    assert sku_col.unique_count == 4

    qty_col = next(c for c in summary.columns if c.name == "qty_demanded")
    assert qty_col.numeric_stats is not None
    assert qty_col.numeric_stats["min"] == 0
    assert qty_col.numeric_stats["max"] == 200


@pytest.mark.asyncio
async def test_json_and_text_ingestion(db_session):
    project_id = "proj_test_docs"
    json_bytes = b'{"analysis": "inventory", "target_service_level": 0.95}'
    txt_bytes = b"Problem Statement:\nNorthline Mobility inventory optimization\n"

    json_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project_id,
        filename="config.json",
        content_bytes=json_bytes,
    )
    assert json_rec.file_type == "json"

    txt_rec = await FileIngestionService.save_and_ingest_file(
        db=db_session,
        project_id=project_id,
        filename="problem.txt",
        content_bytes=txt_bytes,
    )
    assert txt_rec.file_type == "txt"

    # Verify text extraction
    extracted = FileIngestionService.extract_document_text(Path(txt_rec.raw_path))
    assert "Northline Mobility" in extracted


@pytest.mark.asyncio
async def test_unsupported_file_extension(db_session):
    project_id = "proj_test_invalid"
    with pytest.raises(ValueError, match="Unsupported file extension"):
        await FileIngestionService.save_and_ingest_file(
            db=db_session,
            project_id=project_id,
            filename="malicious.exe",
            content_bytes=b"MZ...",
        )
