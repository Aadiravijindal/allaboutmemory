"""Tests for Connect-ANY-AI: webhook inbox, universal upload, custom REST."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault.anyai import (CustomConnectorStore, ingest_records,
                               parse_upload, UniversalRestConnector)
from memoryvault import Vault, Policy

POL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "policies", "default.yaml")


def fresh_vault():
    return Vault(os.path.join(tempfile.mkdtemp(), "v.db"), policy=Policy.load(POL))


def test_custom_store_add_list_token():
    st = CustomConnectorStore(tempfile.mkdtemp())
    tok = st.ingest_token("acme")
    assert tok.startswith("ing_")
    assert st.check_ingest_token("acme", tok) is True
    assert st.check_ingest_token("acme", "wrong") is False
    st.add("acme", "PDF Maker AI", "rest",
           {"base_url": "https://x", "auth_value": "secret123"})
    listed = st.list("acme")
    assert listed[0]["name"] == "pdf_maker_ai"
    # secrets never leaked back
    assert listed[0]["config"]["auth_value"] == "•••"


def test_custom_store_builds_connector():
    st = CustomConnectorStore(tempfile.mkdtemp())
    st.add("acme", "pdfai", "rest", {"base_url": "https://x",
                                     "extract_path": "/d"})
    conns = st.build("acme")
    assert len(conns) == 1
    assert isinstance(conns[0], UniversalRestConnector)


def test_webhook_ingest_stores_memory():
    v = fresh_vault()
    r = ingest_records(v, "acme", "pdfmaker_ai",
                       [{"content": "made a PDF report for the client",
                         "channel": "api"}])
    assert r["added"] == 1
    assert len(v.all_memories()) == 1


def test_untrusted_upload_quarantined():
    v = fresh_vault()
    # upload channel is untrusted -> quarantined (poison defense)
    r = ingest_records(v, "acme", "some_tool",
                       [{"content": "x", "channel": "upload", "trust": 0.2}])
    assert r["quarantined"] == 1


def test_parse_upload_json_and_csv():
    js = parse_upload("x.json", b'[{"content":"a"},{"content":"b"}]')
    assert len(js) == 2
    wrapped = parse_upload("x.json", b'{"records":[{"content":"a"}]}')
    assert len(wrapped) == 1
    csv = parse_upload("x.csv", b"content,subject\nhello,customer:acme\n")
    assert csv[0]["content"] == "hello"
