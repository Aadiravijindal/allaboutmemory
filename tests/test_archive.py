"""Tests for the archive: whole conversations stored under the same
governance as facts, and the scoped context each AI actually receives."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memoryvault import Vault, Policy, MemoryUnit, Provenance
from memoryvault.schema import Conversation, Message, MemoryStatus
from memoryvault.policy_guard import PolicyGuard
from memoryvault.governance import apply_legal_hold
from memoryvault.context import ContextAssembler
from memoryvault.connectors import default_registry
from memoryvault.rescue import RescueTool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POL = os.path.join(ROOT, "policies", "default.yaml")
FIX = os.path.join(ROOT, "fixtures")


def vault(**kw):
    return Vault(os.path.join(tempfile.mkdtemp(), "v.db"),
                 policy=Policy.load(POL), **kw)


def chat(**kw):
    base = dict(
        external_id="c-1", source_system="chatgpt_enterprise",
        title="Acme renewal", namespace="sales", employee="Sarah Chen",
        employee_email="sarah@acme.com", department="sales",
        subjects=["customer:acme"],
        messages=[Message("user", "Acme is moving up from Pro.").to_dict(),
                  Message("assistant", "Which plan?").to_dict(),
                  Message("user", "Enterprise, this cycle.").to_dict()])
    base.update(kw)
    return Conversation(**base)


def rescued():
    v = vault(policy_guard=PolicyGuard())
    RescueTool(v, default_registry(FIX)).run(
        ["salesforce_agentforce", "chatgpt_enterprise", "intercom_fin",
         "email_ingest"])
    return v


# ---- storing whole chats -------------------------------------------------
def test_conversation_stored_whole():
    v = vault()
    c = v.add_conversation(chat())
    got = v.get_conversation(c.id)
    assert got.message_count == 3
    assert "Enterprise, this cycle." in got.transcript()
    assert got.tokens_estimate > 0


def test_conversation_sealed_in_the_chain():
    v = vault()
    v.add_conversation(chat())
    assert v.verify_chain() is True
    actions = [e["action"] for e in v.events_since(0)]
    assert "conversation_stored" in actions


def test_reingest_updates_instead_of_duplicating():
    v = vault()
    first = v.add_conversation(chat())
    again = v.add_conversation(chat(title="Acme renewal (updated)"))
    assert again.id == first.id                     # stable id
    assert v.conversation_counts()["active"] == 1   # not two rows
    assert v.get_conversation(first.id).title.endswith("(updated)")


def test_deleted_chat_is_not_resurrected_by_reingest():
    v = vault()
    c = v.add_conversation(chat())
    v.delete_conversation(c.id, actor="dpo")
    v.add_conversation(chat())
    assert v.get_conversation(c.id).status == MemoryStatus.DELETED.value


# ---- governance reaches the transcripts ---------------------------------
def test_pii_in_a_message_is_caught():
    v = vault(redact_pii=True)
    c = v.add_conversation(chat(messages=[
        Message("user", "his card is 4111 1111 1111 1111").to_dict()]))
    got = v.get_conversation(c.id)
    assert "credit_card" in got.pii_types
    assert got.redacted is True
    assert "4111" not in got.transcript()
    assert "pii" in got.flags


def test_chat_gets_a_sensitivity_level():
    v = vault()
    secret = v.add_conversation(chat(external_id="c-2", messages=[
        Message("user", "the admin password is hunter2").to_dict()]))
    assert secret.classification == "restricted"
    ordinary = v.add_conversation(chat(external_id="c-3"))
    assert ordinary.classification in ("internal", "confidential")


def test_company_rules_are_checked_against_what_was_said():
    v = vault(policy_guard=PolicyGuard())
    c = v.add_conversation(chat(external_id="c-4", messages=[
        Message("user", "I promised them a full refund of $1,200").to_dict()]))
    assert any(f.startswith("policy:") for f in c.flags)


def test_zero_retention_keeps_the_shape_not_the_words():
    v = vault(zero_retention=True)
    c = v.add_conversation(chat())
    got = v.get_conversation(c.id)
    assert got.message_count == 3            # we know a 3-turn chat happened
    assert "Enterprise" not in got.transcript()
    assert got.redacted is True


def test_legal_hold_covers_chats_and_blocks_deletion():
    v = vault()
    v.add_conversation(chat())
    v.add(MemoryUnit(content="Acme is on Enterprise", subject="customer:acme",
                     attribute="plan", value="Enterprise", trust=0.9))
    res = apply_legal_hold(v, "customer:acme", actor="legal", on=True)
    assert res["conversations_held"] == 1
    conv = v.conversations_for_subject("customer:acme")[0]
    blocked = v.delete_conversation(conv.id, actor="someone")
    assert blocked["blocked"] is True


def test_erasing_a_person_reaches_their_transcripts():
    v = vault()
    v.add_conversation(chat())
    v.add(MemoryUnit(content="Acme is on Enterprise", subject="customer:acme",
                     attribute="plan", value="Enterprise", trust=0.9))
    receipt = v.erase_subject("customer:acme", actor="dpo")
    assert len(receipt["conversation_ids"]) == 1
    assert len(receipt["memory_ids"]) == 1
    conv = v.get_conversation(receipt["conversation_ids"][0])
    assert conv.status == MemoryStatus.DELETED.value
    assert "Enterprise" not in conv.transcript()


def test_retention_expires_old_transcripts_but_not_held_ones():
    v = vault()
    old = v.add_conversation(chat(external_id="old", started_at="2020-01-01T00:00:00+00:00",
                                  retention_days=30))
    held = v.add_conversation(chat(external_id="held", started_at="2020-01-01T00:00:00+00:00",
                                   retention_days=30, legal_hold=True))
    assert v.expire_conversations() == 1
    assert v.get_conversation(old.id).status == MemoryStatus.EXPIRED.value
    assert v.get_conversation(held.id).status == MemoryStatus.ACTIVE.value


# ---- facts and chats point at each other -------------------------------
def test_fact_and_chat_are_linked_both_ways():
    v = rescued()
    fact = [m for m in v.all_memories()
            if "evening calls" in m.content][0]
    conv = v.conversation_for_memory(fact.id)
    assert conv is not None and conv.external_id == "sf-8841"
    back = v.facts_from_conversation(conv.id)
    assert fact.id in [m.id for m in back]


def test_transcript_search_respects_walls():
    v = rescued()
    assert v.search_conversations(query="refund", agent="owner")
    # a sales agent cannot see support transcripts
    assert v.search_conversations(query="refund", agent="sales_agent") == []


def test_rescue_reports_and_stores_transcripts():
    v = vault(policy_guard=PolicyGuard())
    rep = RescueTool(v, default_registry(FIX)).run(
        ["salesforce_agentforce", "chatgpt_enterprise"])
    assert rep["total_conversations_recovered"] >= 4
    assert v.conversation_counts()["active"] >= 4


# ---- one memory, each AI its own slice ---------------------------------
def test_each_agent_gets_only_its_slice():
    v = rescued()
    ca = ContextAssembler(v)
    sales = ca.assemble("sales_agent", query="acme")
    support = ca.assemble("support_agent", query="acme")
    hr = ca.assemble("hr_agent", query="acme")
    assert sales["facts"] and support["facts"]
    assert hr["facts"] == [] and hr["conversations"] == []
    assert sales["walls"] == ["sales", "general"]
    # the slices are genuinely different
    assert {f["id"] for f in sales["facts"]} != {f["id"] for f in support["facts"]}


def test_context_hides_material_above_the_clearance():
    v = vault()
    v.add(MemoryUnit(content="admin password is hunter2", subject="customer:acme",
                     attribute="secret", value="x", namespace="general", trust=0.9))
    v.add(MemoryUnit(content="Acme prefers evening calls", subject="customer:acme",
                     attribute="call_time", value="evening", namespace="general",
                     trust=0.9))
    low = ContextAssembler(v).assemble("admin", clearance="internal")
    assert all("hunter2" not in f["content"] for f in low["facts"])
    assert low["excluded"].get("too_sensitive", 0) >= 1
    high = ContextAssembler(v).assemble("admin", clearance="restricted")
    assert any("hunter2" in f["content"] for f in high["facts"])


def test_context_stays_inside_its_token_budget():
    v = rescued()
    ca = ContextAssembler(v)
    roomy = ca.assemble("owner", query="acme", token_budget=4000,
                        max_conversations=0)
    tight = ca.assemble("owner", query="acme", token_budget=15,
                        max_conversations=0)
    assert tight["tokens_estimate"] <= 15
    assert len(tight["facts"]) < len(roomy["facts"])   # the budget really bites
    assert tight["excluded"].get("budget", 0) >= 1


def test_context_caps_the_number_of_facts():
    v = rescued()
    b = ContextAssembler(v).assemble("owner", query="acme", max_facts=2,
                                     max_conversations=0)
    assert len(b["facts"]) == 2
    assert b["excluded"].get("budget", 0) >= 1


def test_context_includes_a_relevant_excerpt_not_the_whole_chat():
    v = rescued()
    b = ContextAssembler(v).assemble("owner", query="refund",
                                     max_conversations=1)
    assert b["conversations"]
    exc = b["conversations"][0]["excerpt"]
    full = v.get_conversation(b["conversations"][0]["id"]).transcript()
    assert exc and len(exc) < len(full)


def test_context_reads_are_recorded():
    v = rescued()
    before = len(v.retrievals(limit=500))
    ContextAssembler(v).assemble("sales_agent", query="acme")
    after = v.retrievals(limit=500)
    assert len(after) > before
    assert any(r["context"] == "context_assembly" for r in after)


def test_blocked_view_shows_what_an_agent_cannot_see():
    v = rescued()
    out = ContextAssembler(v).what_an_agent_cannot_see("hr_agent")
    assert out["blocked_facts"] > 0
    assert "sales" in out["blocked_namespaces"]


# ---- who did what -------------------------------------------------------
def test_employee_activity_attributes_facts_and_chats():
    v = rescued()
    people = v.employee_activity()
    by_name = {p["employee"]: p for p in people}
    assert "Sarah Chen" in by_name
    sarah = by_name["Sarah Chen"]
    assert sarah["facts"] > 0 and sarah["conversations"] > 0
    assert sarah["messages"] > 0
    assert sarah["department"] == "sales"
    assert "salesforce_agentforce" in sarah["sources"]
    # the person who tried the poisoned email shows flagged/held activity
    mark = by_name.get("Mark Ellis")
    assert mark and (mark["flagged"] + mark["held_for_review"]) > 0


def test_employee_activity_can_filter_to_one_person():
    v = rescued()
    only = v.employee_activity("Dana Ruiz")
    assert [p["employee"] for p in only] == ["Dana Ruiz"]
