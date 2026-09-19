from rxlint.core.rulepack import load_pack, pack_hash, verify_quotes


def test_every_quote_is_verbatim_on_its_cited_page(pack):
    records = verify_quotes(pack)
    assert len(records) >= 70
    missing = [r for r in records if not r["found"]]
    assert missing == []


def test_every_rule_has_a_source_and_known_type(pack):
    from rxlint.core.engine import EVALUATORS

    for rule in pack.rules:
        assert rule.type in EVALUATORS, rule.id
        assert rule.source.ref == "PACK" or rule.source.ref in pack.sources, rule.id
        if rule.source.ref != "PACK":
            assert rule.source.quotes, f"{rule.id} cites an external source without a quote"


def test_pack_hash_is_stable_and_content_addressed(pack, tmp_path):
    import shutil
    from pathlib import Path

    copy = tmp_path / "pack"
    shutil.copytree(pack.root, copy)
    assert pack_hash(copy) == pack.sha256
    rule = copy / "rules" / "dose.yaml"
    rule.write_text(rule.read_text(encoding="utf-8").replace("[80, 90]", "[80, 95]", 1), encoding="utf-8")
    assert pack_hash(copy) != pack.sha256


def test_policies_are_declared(pack):
    for rule in pack.rules:
        for p in [rule.params.get("policy")] if rule.params.get("policy") else []:
            assert p in pack.policies
