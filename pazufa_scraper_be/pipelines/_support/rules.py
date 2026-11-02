from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pazufa_corelib.api_client.models import Autor

from pazufa_scraper_be.pardok import DrsDokument
from pazufa_scraper_be.pipelines._support.utils import DokumentContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


logger = logging.getLogger(__name__)


def get_change_urheber_transform_fn(urheber: str) -> Callable[[DokumentContainer], None]:
    """Get transform function that changes Autor/Urheber."""

    def _change_urheber_transform_fn(current: DokumentContainer) -> None:
        if not isinstance(current.pardok, DrsDokument):
            return

        current.pardok.urheber = [urheber]
        if len(current.pazufa) >= 1:
            current.pazufa[0].autoren = [Autor(organisation=urheber)]

    return _change_urheber_transform_fn


def get_change_abstract_transform_fn(abstract: str) -> Callable[[DokumentContainer], None]:
    """Get transform function that changes Abstract."""

    def _change_abstract_transform_fn(current: DokumentContainer) -> None:
        current.pardok.abstract = abstract

    return _change_abstract_transform_fn


@dataclass
class Rule:
    """Base rule that evaluates whether a DokumentContainer matches a condition."""

    name: str
    when: Callable[[DokumentContainer], bool]

    def __call__(self, dok_container: DokumentContainer) -> bool:
        """Evaluate the rule's condition against dok_container."""
        return self.when(dok_container)


@dataclass
class DropRule(Rule):
    """Rule that drops matching DokumentContainers from the pipeline."""


@dataclass
class TransformRule(Rule):
    """Rule that transforms a matching DokumentContainer."""

    transform_function: Callable[[DokumentContainer], None]


def _merge_function(current: DokumentContainer, target: DokumentContainer) -> DokumentContainer:
    abstract = ((target.pardok.abstract or "") + "\n\n" + (current.pardok.abstract or "")).strip()
    target.pardok.abstract = abstract or None
    return DokumentContainer(pardok=target.pardok, pazufa=target.pazufa + current.pazufa)


@dataclass
class _MergeRule(Rule):
    merge_into: Callable[[DokumentContainer, DokumentContainer], bool]
    merge_function: Callable[[DokumentContainer, DokumentContainer], DokumentContainer] = _merge_function


@dataclass
class ForwardMergeRule(_MergeRule):
    """Rule that merges the current container into a subsequent matching container."""


@dataclass
class BackwardMergeRule(_MergeRule):
    """Rule that merges the current container into a preceding matching container."""


def flush_pending_forward_rules(pending: list[tuple[DokumentContainer, ForwardMergeRule]], current: DokumentContainer) -> tuple[list, DokumentContainer]:
    """Apply any pending forward-merge rules that match the current container."""
    remaining = []
    for pending_item, pending_rule in pending:
        if pending_rule.merge_into(pending_item, current):
            current = pending_rule.merge_function(pending_item, current)

        else:
            remaining.append((pending_item, pending_rule))

    return remaining, current


# TODO(se-jaeger): refactor to reduce complexity
def apply_rules(pardok_pazufa_doks: list[DokumentContainer], rules: Sequence[Rule]) -> list[DokumentContainer]:  # noqa: C901, PLR0912
    """Apply the given rules to a list of DokumentContainers, returning the reduced list."""
    result: list[DokumentContainer] = []
    pending: list[tuple[DokumentContainer, ForwardMergeRule]] = []

    for index, item in enumerate(pardok_pazufa_doks):
        pending, current = flush_pending_forward_rules(pending=pending, current=item)

        append_item = True
        for rule in rules:
            if rule(current):
                match rule:
                    case ForwardMergeRule():
                        for target in pardok_pazufa_doks[index + 1 :]:
                            if rule.merge_into(current, target):
                                append_item = False
                                pending.append((current, rule))
                                break

                    case BackwardMergeRule():
                        for i in reversed(range(len(result))):
                            if rule.merge_into(current, result[i]):
                                append_item = False
                                result[i] = rule.merge_function(current, result[i])
                                break

                    case TransformRule():
                        rule.transform_function(current)

                    case DropRule():
                        append_item = False
                        break

        if append_item:
            result.append(current)

    if len(pending) > 0:
        msg = f"[{pardok_pazufa_doks[0].pardok.vorgang.id}]: Did not consume all pending items."
        logger.warning(msg)

    return result
