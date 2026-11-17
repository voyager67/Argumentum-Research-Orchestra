from argumentum.agents import AGENTS, CAPABILITY_PACKS, CONTRACTS


def test_specialist_registry_is_unique():
    ids = [x.agent_id for x in AGENTS]
    assert len(ids) == len(set(ids))


def test_five_capability_packs_are_defined():
    assert len(CAPABILITY_PACKS) == 5


def test_every_agent_has_an_output_contract():
    assert {x.agent_id for x in AGENTS} == set(CONTRACTS)
