import dataclasses
import sys
from unittest.mock import MagicMock

import pytest

import embedder as embedder_module
from config import settings as real_settings
from embedder import Embedder, VertexEmbedder, build_embedder


@pytest.fixture
def fake_vertex(monkeypatch):
    vertexai = MagicMock(name="vertexai")
    language_models = MagicMock(name="vertexai.language_models")

    language_models.TextEmbeddingInput = lambda text, task_type: {
        "text": text,
        "task_type": task_type,
    }

    model = MagicMock(name="TextEmbeddingModel")

    def get_embeddings(inputs, output_dimensionality=None):
        return [
            MagicMock(values=[float(i)] * (output_dimensionality or 768))
            for i, _ in enumerate(inputs)
        ]

    model.get_embeddings.side_effect = get_embeddings
    language_models.TextEmbeddingModel.from_pretrained.return_value = model

    monkeypatch.setitem(sys.modules, "vertexai", vertexai)
    monkeypatch.setitem(sys.modules, "vertexai.language_models", language_models)

    return vertexai, language_models, model


def test_init_uses_adc_and_pins_the_model(fake_vertex):
    vertexai, language_models, _ = fake_vertex

    emb = VertexEmbedder(project="pharos-505715", location="europe-west3")

    vertexai.init.assert_called_once_with(project="pharos-505715", location="europe-west3")
    language_models.TextEmbeddingModel.from_pretrained.assert_called_once_with(
        "text-embedding-005"
    )
    assert isinstance(emb, Embedder)
    assert emb.dimensionality == 768


def test_embed_documents_returns_768_dim_vectors(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder()

    vectors = emb.embed_documents(["chunk a", "chunk b", "chunk c"])

    assert len(vectors) == 3
    assert all(len(v) == 768 for v in vectors)
    model.get_embeddings.assert_called_once()
    assert model.get_embeddings.call_args.kwargs["output_dimensionality"] == 768


def test_embed_documents_batches_instead_of_one_call_per_chunk(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder()

    texts = [f"chunk {i}" for i in range(70)]
    vectors = emb.embed_documents(texts)

    assert len(vectors) == 70
    batch_sizes = [len(call.args[0]) for call in model.get_embeddings.call_args_list]
    assert batch_sizes == [32, 32, 6]


def test_embed_documents_of_a_single_batch_makes_one_call(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder()

    emb.embed_documents([f"chunk {i}" for i in range(VertexEmbedder.MAX_BATCH)])

    assert model.get_embeddings.call_count == 1


def test_empty_input_makes_no_api_call(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder()

    assert emb.embed_documents([]) == []
    model.get_embeddings.assert_not_called()


def test_query_and_document_use_different_task_types(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder()

    emb.embed_documents(["a passage"])
    emb.embed_query("a question")

    document_call, query_call = model.get_embeddings.call_args_list
    assert document_call.args[0][0]["task_type"] == "RETRIEVAL_DOCUMENT"
    assert query_call.args[0][0]["task_type"] == "RETRIEVAL_QUERY"


def test_embed_query_returns_a_flat_vector_not_a_list_of_vectors(fake_vertex):
    emb = VertexEmbedder()

    vector = emb.embed_query("CrashLoopBackOff, exit code 1")

    assert len(vector) == 768
    assert all(isinstance(x, float) for x in vector)


def test_custom_dimensionality_is_forwarded(fake_vertex):
    _, _, model = fake_vertex
    emb = VertexEmbedder(dimensionality=256)

    vectors = emb.embed_documents(["x"])

    assert len(vectors[0]) == 256
    assert model.get_embeddings.call_args.kwargs["output_dimensionality"] == 256


def test_build_embedder_selects_vertex_from_settings(fake_vertex):
    vertexai, _, _ = fake_vertex
    settings = dataclasses.replace(
        real_settings,
        embedder_backend="vertex",
        gcp_project="pharos-505715",
        vertex_location="europe-west3",
    )

    built = build_embedder(settings)

    assert isinstance(built, VertexEmbedder)
    vertexai.init.assert_called_once_with(project="pharos-505715", location="europe-west3")


def test_build_embedder_rejects_an_unknown_backend():
    settings = dataclasses.replace(real_settings, embedder_backend="wat")

    with pytest.raises(ValueError, match="wat"):
        build_embedder(settings)


def test_local_backend_is_still_selectable(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(embedder_module, "LocalEmbedder", lambda name: sentinel)
    settings = dataclasses.replace(real_settings, embedder_backend="local")

    assert build_embedder(settings) is sentinel