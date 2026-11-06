"""Immutable Research selection backlink; no Candidate store or market reader."""
from execution.validation import identifier, integer, require
from .review import expected
from .strategy import StrategyRules


def validate_binding(binding, draft):
    require(type(binding) is dict and set(binding) == {"selection", "protection"}, "INVALID_CANDIDATE_BINDING")
    value = binding["selection"]
    require(type(value) is dict and set(value) == {"candidate_id", "candidate_revision", "pending_id",
            "pending_revision", "pending_digest"}, "INVALID_CANDIDATE_SELECTION")
    identifier(value["candidate_id"])
    identifier(value["pending_id"])
    integer(value["candidate_revision"], positive=True)
    expected(value["pending_revision"], value["pending_digest"])
    require((draft.command.space_id, draft.source) in {
        ("AGENT_SPACE", "AGENT_PROPOSAL"), ("USER_SPACE", "MANUAL")}, "INVALID_CANDIDATE_SPACE")
    if binding["protection"] is not None:
        rules = StrategyRules(**binding["protection"])
        rules.validate()
        require(rules.direction == (1 if draft.command.action == "Buy" else -1), "STRATEGY_DIRECTION_MISMATCH")
        require(draft.command.strategy_id is not None and draft.command.revision == 1, "STRATEGY_LINEAGE_REQUIRED")
    return binding
