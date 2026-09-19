"""MappingAgent: propose source-column -> target-field mappings with confidence.

Scoring is deterministic by default so the demo is reproducible. Signals:

  1. name similarity   - source column vs the target field's alias vocabulary
  2. type compatibility - inferred column type vs the declared target type
  3. value evidence     - e.g. "these look like 10-digit mobile numbers"
  4. discriminative damping - an alias claimed by SEVERAL target fields carries
     less information, so every score derived from it is damped. This is what
     makes "Contact No" land at ~0.73/0.70 instead of a false 0.98.

An LLM, when configured, may adjust a score by at most MAX_LLM_ADJUSTMENT. It
never picks a target the deterministic layer has not considered, and it never
overrides the autonomy thresholds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from ..config import get_target_schema, settings
from ..utils.text import slugify

# A candidate below this raw name similarity is not a mapping at all - the
# column simply has no home in the target schema (e.g. "Remarks", "location").
NAME_SIMILARITY_FLOOR = 0.72
MIN_CONFIDENCE_FLOOR = 0.45
EXACT_MATCH_SCORE = 0.97
SHARED_ALIAS_DAMPING = 0.35

#: Which inferred column types are plausible for each declared target type.
TYPE_COMPATIBILITY: dict[str, set[str]] = {
    "string": {"string", "identifier_or_text", "enum", "integer", "unknown"},
    "email": {"email", "string", "identifier_or_text", "unknown"},
    "phone": {"phone", "integer", "identifier_or_text", "string", "unknown"},
    "date": {"date", "unknown"},
    "enum": {"enum", "string", "identifier_or_text", "unknown"},
}


@dataclass
class Candidate:
    target_field: str
    confidence: float
    reason: str
    method: str = "deterministic_alias"
    matched_alias: str | None = None
    name_similarity: float = 0.0
    type_compatible: bool = True
    ai_assisted: bool = False
    signals: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(self.confidence, 3)
        d["name_similarity"] = round(self.name_similarity, 3)
        return d


@dataclass
class MappingProposal:
    source_field: str
    target_field: str | None
    confidence: float
    margin: float
    method: str
    reason: str
    ai_assisted: bool
    candidates: list[dict]
    sample_values: list[str]
    auto_apply: bool
    escalate: bool
    escalation_reason: str | None = None


def _alias_vocabulary() -> dict[str, list[str]]:
    schema = get_target_schema()
    vocab: dict[str, list[str]] = {}
    for name, spec in schema["fields"].items():
        aliases = {slugify(name)} | {slugify(a) for a in spec.get("aliases", [])}
        vocab[name] = sorted(aliases)
    return vocab


def _shared_alias_counts(vocab: dict[str, list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for aliases in vocab.values():
        for alias in aliases:
            counts[alias] = counts.get(alias, 0) + 1
    return counts


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
        # Full token containment ("dept" inside "dept name") is strong evidence.
        containment = 1.0 if (ta <= tb or tb <= ta) else jaccard
        ratio = max(ratio, 0.5 * ratio + 0.5 * containment)
    return ratio


def _value_signal(target_field: str, target_type: str, profile: dict) -> tuple[float, str | None]:
    """Small, explainable nudges based on what the values actually look like."""
    signals = profile.get("signals", {})
    if target_type == "phone":
        mobile = signals.get("mobile_like", 0.0)
        extension = signals.get("extension_like", 0.0)
        if target_field == "mobile_phone":
            if mobile >= 0.8:
                return 0.03, "sample values are 10-digit numbers starting 6-9 (mobile range)"
            if extension >= 0.8:
                return -0.03, "sample values look like short desk extensions"
        if target_field == "work_phone":
            if extension >= 0.8:
                return 0.03, "sample values look like short desk extensions"
            if mobile >= 0.8:
                return -0.03, "sample values look like personal mobile numbers"
    if target_type == "email" and signals.get("email_like", 0.0) >= 0.9:
        return 0.02, "values contain @ and look like addresses"
    if target_type == "date" and signals.get("date_like", 0.0) >= 0.9:
        return 0.02, "values parse as dates"
    if target_field == "employee_id" and profile.get("unique_ratio", 0) >= 0.95:
        return 0.02, "values are unique across the file (identifier-like)"
    return 0.0, None


def score_candidates(source_field: str, profile: dict) -> list[Candidate]:
    schema = get_target_schema()
    vocab = _alias_vocabulary()
    shared = _shared_alias_counts(vocab)
    source_key = profile.get("key") or slugify(source_field)
    inferred_type = profile.get("semantic_type", "unknown")

    candidates: list[Candidate] = []
    for target_field, aliases in vocab.items():
        spec = schema["fields"][target_field]
        target_type = spec.get("type", "string")

        best_alias, best_sim = None, 0.0
        for alias in aliases:
            sim = _similarity(source_key, alias)
            if sim > best_sim:
                best_alias, best_sim = alias, sim
        if best_sim < NAME_SIMILARITY_FLOOR:
            continue

        reasons: list[str] = []
        if best_sim >= 0.999:
            confidence = EXACT_MATCH_SCORE
            reasons.append(f"column name matches the known alias '{best_alias}'")
        else:
            confidence = best_sim * 0.9
            reasons.append(
                f"column name is {best_sim:.0%} similar to the alias '{best_alias}'"
            )

        compatible = inferred_type in TYPE_COMPATIBILITY.get(target_type, {inferred_type})
        if not compatible:
            confidence *= 0.5
            reasons.append(
                f"inferred column type '{inferred_type}' does not fit target type '{target_type}'"
            )

        delta, note = _value_signal(target_field, target_type, profile)
        if delta:
            confidence += delta
            reasons.append(note or "")

        alias_claimants = shared.get(best_alias, 1)
        if alias_claimants > 1 and best_sim >= 0.9:
            damping = 1 / (1 + SHARED_ALIAS_DAMPING * (alias_claimants - 1))
            confidence *= damping
            reasons.append(
                f"the term '{best_alias}' is a valid alias for {alias_claimants} different "
                "target fields, so the column name alone is not decisive"
            )

        candidates.append(
            Candidate(
                target_field=target_field,
                confidence=max(0.0, min(0.99, confidence)),
                reason="; ".join(r for r in reasons if r),
                matched_alias=best_alias,
                name_similarity=best_sim,
                type_compatible=compatible,
                signals={"inferred_type": inferred_type, "target_type": target_type},
            )
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def _apply_llm(source_field: str, profile: dict, candidates: list[Candidate]) -> bool:
    """Let the LLM nudge (never replace) the deterministic scores."""
    from .llm import MAX_LLM_ADJUSTMENT, llm_client

    if not llm_client.enabled or not candidates:
        return False
    names = [c.target_field for c in candidates[:5]]
    suggestion = llm_client.suggest_mapping(source_field, profile, names)
    if not suggestion or not suggestion.get("target_field"):
        return False

    target = suggestion["target_field"]
    strength = (suggestion["confidence"] - 0.5) * 2  # -1 .. 1
    for cand in candidates:
        if cand.target_field == target:
            cand.confidence = max(
                0.0, min(0.99, cand.confidence + MAX_LLM_ADJUSTMENT * strength)
            )
            cand.ai_assisted = True
            cand.method = "llm_assisted_semantic"
            if suggestion.get("reason"):
                cand.reason += f"; LLM: {suggestion['reason']}"
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return True


def propose_mapping(source_field: str, profile: dict, use_llm: bool = True) -> MappingProposal:
    schema = get_target_schema()
    candidates = score_candidates(source_field, profile)
    ai_assisted = _apply_llm(source_field, profile, candidates) if use_llm else False

    samples = [str(s) for s in profile.get("samples", [])[:5]]

    if not candidates or candidates[0].confidence < MIN_CONFIDENCE_FLOOR:
        return MappingProposal(
            source_field=source_field,
            target_field=None,
            confidence=candidates[0].confidence if candidates else 0.0,
            margin=0.0,
            method="no_match",
            reason=(
                f"No target field in the '{schema['entity']}' schema resembles "
                f"'{source_field}'. The column will be carried in the audit trail "
                "but not migrated."
            ),
            ai_assisted=ai_assisted,
            candidates=[c.as_dict() for c in candidates[:3]],
            sample_values=samples,
            auto_apply=False,
            escalate=False,
        )

    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    margin = best.confidence - (runner_up.confidence if runner_up else 0.0)
    spec = schema["fields"][best.target_field]
    critical = bool(spec.get("critical") or spec.get("required"))

    auto_apply = False
    escalate = False
    escalation_reason = None

    if best.confidence >= settings.high_confidence_threshold:
        if margin >= 0.10:
            auto_apply = True
        else:
            escalate = True
            escalation_reason = (
                f"Two target fields score almost identically "
                f"({best.target_field} {best.confidence:.0%} vs "
                f"{runner_up.target_field} {runner_up.confidence:.0%}). High confidence in "
                "'a phone-like field' is not the same as certainty about WHICH field."
            )
    elif best.confidence >= settings.medium_confidence_threshold:
        if margin >= settings.min_confidence_margin and not critical and best.type_compatible:
            auto_apply = True
        else:
            escalate = True
            if margin < settings.min_confidence_margin and runner_up:
                escalation_reason = (
                    f"'{source_field}' could reasonably map to {best.target_field} "
                    f"({best.confidence:.0%}) or {runner_up.target_field} "
                    f"({runner_up.confidence:.0%}). The gap ({margin:.0%}) is below the "
                    f"{settings.min_confidence_margin:.0%} margin required to decide alone."
                )
            elif critical:
                escalation_reason = (
                    f"'{best.target_field}' is a mandatory field in the target schema, so a "
                    f"medium-confidence mapping ({best.confidence:.0%}) is not applied without "
                    "confirmation."
                )
            else:
                escalation_reason = (
                    f"Mapping confidence {best.confidence:.0%} with an incompatible inferred "
                    "type."
                )
    else:
        escalate = True
        escalation_reason = (
            f"Best candidate {best.target_field} scores only {best.confidence:.0%}, below the "
            f"{settings.medium_confidence_threshold:.0%} autonomy floor."
        )

    return MappingProposal(
        source_field=source_field,
        target_field=best.target_field,
        confidence=best.confidence,
        margin=margin,
        method=best.method,
        reason=best.reason,
        ai_assisted=best.ai_assisted,
        candidates=[c.as_dict() for c in candidates[:4]],
        sample_values=samples,
        auto_apply=auto_apply,
        escalate=escalate,
        escalation_reason=escalation_reason,
    )


def resolve_collisions(proposals: list[MappingProposal]) -> list[MappingProposal]:
    """Enforce at most one source column per target field, per file.

    Highest confidence wins; the loser falls back to its next candidate above
    the floor, otherwise it becomes unmapped. Prevents two columns silently
    overwriting each other in the target payload.
    """
    taken: dict[str, MappingProposal] = {}
    ordered = sorted(proposals, key=lambda p: p.confidence, reverse=True)
    for proposal in ordered:
        if not proposal.target_field:
            continue
        winner = taken.get(proposal.target_field)
        if winner is None:
            taken[proposal.target_field] = proposal
            continue
        alternatives = [
            c
            for c in proposal.candidates
            if c["target_field"] not in taken
            and c["confidence"] >= MIN_CONFIDENCE_FLOOR
            and c["name_similarity"] >= NAME_SIMILARITY_FLOOR
        ]
        loser_note = (
            f"'{winner.source_field}' is a stronger match for "
            f"{proposal.target_field} ({winner.confidence:.0%} vs "
            f"{proposal.confidence:.0%})"
        )
        if alternatives:
            alt = alternatives[0]
            proposal.target_field = alt["target_field"]
            proposal.confidence = alt["confidence"]
            proposal.reason = f"{alt['reason']}; {loser_note}"
            proposal.auto_apply = False
            proposal.escalate = True
            proposal.escalation_reason = (
                f"Two source columns competed for '{winner.target_field}'. "
                f"{loser_note}, so '{proposal.source_field}' needs a human decision."
            )
            taken[proposal.target_field] = proposal
        else:
            proposal.target_field = None
            proposal.auto_apply = False
            proposal.escalate = False
            proposal.method = "collision_unmapped"
            proposal.reason = f"{loser_note}; no alternative target field available"
    return proposals
