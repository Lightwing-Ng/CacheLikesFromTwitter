"""Tests for pointer-backed prompt bookmarks and browser controls."""

# Code version: v1.0.0-codex.1

from pathlib import Path

import pytest

from app.core.prompt_store import PromptStore
from app.core.resource_persistence import GEMINI_HISTORY_SCHEMA, PROMPT_SCHEMA, write_parquet_rows_atomic
from app.web.app import create_app


def _history_row(
    conversation_id: str,
    message_key: str,
    content_text: str,
    *,
    role: str = "user",
    last_seen_at: str = "2026-08-20T06:00:00Z",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "platform": "chatgpt",
        "conversation_id": conversation_id,
        "conversation_url": f"https://chatgpt.com/c/{conversation_id}",
        "conversation_title": "Prompt demo",
        "message_key": message_key,
        "turn_index": 0,
        "message_index": 0,
        "role": role,
        "author_label": "You" if role == "user" else "ChatGPT",
        "content_text": content_text,
        "content_html": "",
        "content_sha256": "hash",
        "source_links": [],
        "model_label": "",
        "first_seen_at": last_seen_at,
        "last_seen_at": last_seen_at,
    }


def _write_history(root: Path, content_text: str) -> None:
    write_parquet_rows_atomic(
        root / "llm" / "chatgpt" / "history.parquet",
        [_history_row("demo", "demo:user:0", content_text)],
        GEMINI_HISTORY_SCHEMA,
    )


def test_prompt_store_deduplicates_pointers_and_resolves_updated_text(tmp_path: Path) -> None:
    _write_history(tmp_path, "First prompt")
    store = PromptStore(tmp_path)

    saved, created = store.add_pointer(
        source="chatgpt",
        conversation_id="demo",
        message_key="demo:user:0",
    )
    duplicate, duplicate_created = store.add_pointer(
        source="chatgpt",
        conversation_id="demo",
        message_key="demo:user:0",
    )

    assert created is True
    assert duplicate_created is False
    assert saved.stable_id == duplicate.stable_id
    assert saved.content_text == "First prompt"
    assert saved.remarks == ()
    assert store.catalog_path == tmp_path / "prompt" / "prompts.parquet"

    import pyarrow.parquet as parquet

    table = parquet.read_table(store.catalog_path)
    assert table.num_rows == 1
    assert "content_text" not in table.column_names

    _write_history(tmp_path, "Updated prompt")
    refreshed = PromptStore(tmp_path).query().items[0]
    assert refreshed.content_text == "Updated prompt"


def test_prompts_mode_renders_add_and_copy_controls(tmp_path: Path) -> None:
    _write_history(tmp_path, "Create a concise local summary.")
    app = create_app(tmp_path)
    client = app.test_client()

    response = client.post(
        "/api/browser/prompts",
        json={
            "source": "chatgpt",
            "conversation_id": "demo",
            "message_key": "demo:user:0",
        },
    )
    assert response.status_code == 200
    assert response.get_json()["created"] is True
    assert client.post(
        "/api/browser/prompts",
        json={
            "source": "chatgpt",
            "conversation_id": "demo",
            "message_key": "demo:user:0",
        },
    ).get_json()["created"] is False

    prompt_body = client.get("/browser?view=prompts").get_data(as_text=True)
    text_body = client.get(
        "/browser?view=text&source=chatgpt&session_view=1&session=chatgpt:demo"
    ).get_data(as_text=True)

    assert 'id="browser_view_prompts"' in prompt_body
    assert 'data-option-count="3"' in prompt_body
    assert "Saved prompts" in prompt_body
    assert 'class="browser-prompt-col-added">Saved</th>' not in prompt_body
    assert 'class="browser-prompt-col-source">Source</th>' in prompt_body
    assert 'class="browser-prompt-col-remarks">Remarks</th>' in prompt_body
    assert 'browser-prompts-primary-metric' in prompt_body
    assert 'data-prompt-copy' in prompt_body
    assert 'data-prompt-remark-add' not in prompt_body
    assert 'data-prompt-remark-options' in prompt_body
    assert 'list="browser_prompt_remark_options"' in prompt_body
    assert 'aria-autocomplete="list"' in prompt_body
    assert 'enterkeyhint="done"' in prompt_body
    assert 'data-prompt-remark-select' not in prompt_body
    assert 'data-prompt-text="Create a concise local summary."' in prompt_body
    assert 'data-prompt-add' in text_body
    assert client.get("/static/images/text.bubble.fill.svg").status_code == 200
    assert client.get("/static/images/text.bubble.badge.clock.fill.svg").status_code == 200
    assert 'aria-label="Added as prompt"' in text_body


def test_prompt_remarks_are_persisted_and_exposed_as_shared_options(tmp_path: Path) -> None:
    _write_history(tmp_path, "Remarkable prompt")
    app = create_app(tmp_path)
    client = app.test_client()

    saved_response = client.post(
        "/api/browser/prompts",
        json={
            "source": "chatgpt",
            "conversation_id": "demo",
            "message_key": "demo:user:0",
        },
    )
    prompt_id = saved_response.get_json()["item"]["id"]

    added_response = client.post(
        f"/api/browser/prompts/{prompt_id}/remarks",
        json={"remark": "  favorite  "},
    )
    assert added_response.status_code == 200
    assert added_response.get_json()["created"] is True
    assert added_response.get_json()["item"]["remarks"] == ["favorite"]
    assert added_response.get_json()["remark_options"] == ["favorite"]

    duplicate_response = client.post(
        f"/api/browser/prompts/{prompt_id}/remarks",
        json={"remark": "FAVORITE"},
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.get_json()["created"] is False

    prompt_body = client.get("/browser?view=prompts").get_data(as_text=True)
    assert 'data-prompt-remark="favorite"' in prompt_body
    assert '<datalist id="browser_prompt_remark_options" data-prompt-remark-options>' in prompt_body
    assert '<option value="favorite">favorite</option>' in prompt_body
    assert "favorite" in prompt_body

    removed_response = client.delete(
        f"/api/browser/prompts/{prompt_id}/remarks",
        json={"remark": "favorite"},
    )
    assert removed_response.status_code == 200
    assert removed_response.get_json()["item"]["remarks"] == []
    assert removed_response.get_json()["remark_options"] == []

    reloaded = PromptStore(tmp_path)
    assert reloaded.query().items[0].remarks == ()


def test_prompt_collection_is_limited_to_user_messages(tmp_path: Path) -> None:
    write_parquet_rows_atomic(
        tmp_path / "llm" / "chatgpt" / "history.parquet",
        [
            _history_row("demo", "demo:user:0", "User prompt", role="user"),
            _history_row("demo", "demo:assistant:1", "Assistant response", role="assistant"),
        ],
        GEMINI_HISTORY_SCHEMA,
    )
    store = PromptStore(tmp_path)

    with pytest.raises(ValueError, match="Only user messages"):
        store.add_pointer(
            source="chatgpt",
            conversation_id="demo",
            message_key="demo:assistant:1",
        )

    app = create_app(tmp_path)
    client = app.test_client()
    response = client.post(
        "/api/browser/prompts",
        json={
            "source": "chatgpt",
            "conversation_id": "demo",
            "message_key": "demo:assistant:1",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Only user messages can be saved as prompts."

    write_parquet_rows_atomic(
        store.catalog_path,
        [
            {
                "schema_version": 1,
                "source": "chatgpt",
                "conversation_id": "demo",
                "message_key": "demo:assistant:1",
                "added_at": "2026-08-20T06:00:00Z",
            }
        ],
        PROMPT_SCHEMA,
    )
    assert PromptStore(tmp_path).query().items == ()

    text_body = client.get(
        "/browser?view=text&source=chatgpt&session_view=1&session=chatgpt:demo"
    ).get_data(as_text=True)
    assert text_body.count('class="browser-prompt-add-button') == 1
    assert 'Assistant response' in text_body
