from unittest.mock import MagicMock
from app.services.ollama_service import OllamaService
from app.services.metadata_extractor import MetadataExtractor


def test_extract_engine_variant_from_filename_regex():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.extract_engine_variant(
        filename="15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf",
        sample_text="cylinder head torque...",
    ) == "4.2L"
    ollama.chat.assert_not_called()


def test_extract_engine_variant_handles_w12_pattern():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.extract_engine_variant(
        filename="13-ENGINE BLOCK W12.pdf",
        sample_text="...",
    ) == "W12"


def test_extract_engine_variant_falls_back_to_llm_when_filename_ambiguous():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"engine_variant": "4.2L"}'
    extractor = MetadataExtractor(ollama, model="gemma4:e4b")
    result = extractor.extract_engine_variant(
        filename="01-MAINTENANCE.pdf",
        sample_text="Drain the engine oil. Use 0W-30 for the 4.2L V8...",
    )
    assert result == "4.2L"
    ollama.chat.assert_called_once()


def test_extract_engine_variant_returns_none_when_llm_says_unknown():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"engine_variant": "unknown"}'
    extractor = MetadataExtractor(ollama, model="gemma4:e4b")
    assert extractor.extract_engine_variant(
        filename="GLOSSARY.pdf",
        sample_text="general definitions",
    ) is None


def test_extract_engine_variant_recovers_from_malformed_llm_output():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "well, it looks like 6.0L mostly"
    extractor = MetadataExtractor(ollama, model="m")
    # Permissive parse: scan the text for a known variant token.
    assert extractor.extract_engine_variant(
        filename="01-MAINTENANCE.pdf",
        sample_text="anything",
    ) == "6.0L"


def test_classify_table_type_uses_header_keywords():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.classify_table_type(
        section_title="TIGHTENING TORQUES",
        header=["Bolt", "Torque (Nm)"],
    ) == "torque"
    assert extractor.classify_table_type(
        section_title="FLUID CAPACITIES",
        header=["System", "Capacity (L)"],
    ) == "fluid"
    assert extractor.classify_table_type(
        section_title="DTC INDEX",
        header=["DTC", "Description"],
    ) == "dtc"
    assert extractor.classify_table_type(
        section_title="MISC",
        header=["A", "B"],
    ) is None
