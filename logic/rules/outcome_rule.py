"""
<<interface>> OutcomeRule: every routing rule must be able to give an outcome().
This is the Strategy pattern (Week 11): LogicManager uses the rules through
this one method and doesn't need to know which rule it is.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class OutcomeRule(ABC):
    """INTERFACE for one routing rule: a contract saying every rule must be able to
    give an outcome(). It can't be created itself; each rule class implements it.

    POLYMORPHISM: LogicManager.route() calls outcome() on every rule in the same way,
    without knowing which subclass it is. LSP: any subclass can stand in for another
    because they all keep the same contract -- return the outcome text when the rule
    applies, or None to pass the decision on to the next rule.
    OCP: a new rule is a new subclass added to the list, LogicManager is not edited."""

    @abstractmethod
    def outcome(self, record: dict, facts: dict) -> str | None:
        """record = the AI-scored check; facts = LogicManager.evaluate(record).
        Return the outcome text, or None if this rule doesn't apply."""
