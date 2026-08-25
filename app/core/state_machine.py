from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class ProjectPhase(str, Enum):
    INITIALIZED = "INITIALIZED"
    PROBLEM_FRAMED = "PROBLEM_FRAMED"
    DATA_PROFILED = "DATA_PROFILED"
    METHOD_SELECTED = "METHOD_SELECTED"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    TECHNICAL_REVIEW = "TECHNICAL_REVIEW"
    BUSINESS_REVIEW = "BUSINESS_REVIEW"
    VALIDATED = "VALIDATED"
    DOCUMENTATION = "DOCUMENTATION"
    COMPLETE = "COMPLETE"


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class ProjectStateMachine:
    """Deterministic State Machine managing analytical project lifecycles."""

    MAX_AUTOMATED_REVISIONS: int = 3

    VALID_TRANSITIONS: Dict[ProjectPhase, Set[ProjectPhase]] = {
        ProjectPhase.INITIALIZED: {ProjectPhase.PROBLEM_FRAMED, ProjectPhase.DATA_PROFILED},
        ProjectPhase.PROBLEM_FRAMED: {ProjectPhase.DATA_PROFILED, ProjectPhase.METHOD_SELECTED},
        ProjectPhase.DATA_PROFILED: {ProjectPhase.METHOD_SELECTED, ProjectPhase.PROBLEM_FRAMED},
        ProjectPhase.METHOD_SELECTED: {ProjectPhase.ANALYSIS_COMPLETE, ProjectPhase.DATA_PROFILED},
        ProjectPhase.ANALYSIS_COMPLETE: {ProjectPhase.TECHNICAL_REVIEW, ProjectPhase.METHOD_SELECTED},
        ProjectPhase.TECHNICAL_REVIEW: {
            ProjectPhase.BUSINESS_REVIEW,
            ProjectPhase.ANALYSIS_COMPLETE,
            ProjectPhase.METHOD_SELECTED,
        },
        ProjectPhase.BUSINESS_REVIEW: {
            ProjectPhase.VALIDATED,
            ProjectPhase.ANALYSIS_COMPLETE,
            ProjectPhase.METHOD_SELECTED,
        },
        ProjectPhase.VALIDATED: {ProjectPhase.DOCUMENTATION, ProjectPhase.COMPLETE},
        ProjectPhase.DOCUMENTATION: {ProjectPhase.COMPLETE},
        ProjectPhase.COMPLETE: set(),  # Terminal state
    }

    @classmethod
    def can_transition(cls, current_phase: ProjectPhase, target_phase: ProjectPhase) -> bool:
        """Check if transition is mathematically valid."""
        return target_phase in cls.VALID_TRANSITIONS.get(current_phase, set())

    @classmethod
    def transition(
        cls,
        current_phase: ProjectPhase,
        target_phase: ProjectPhase,
        iteration_count: int = 0,
        has_critical_critic_issues: bool = False,
    ) -> Tuple[ProjectPhase, ProjectStatus, int]:
        """
        Executes a deterministic state transition and evaluates quality gates.
        
        Returns:
            Tuple of (new_phase, new_status, new_iteration_count)
        """
        if not cls.can_transition(current_phase, target_phase):
            raise StateTransitionError(
                f"Illegal state transition requested from {current_phase.value} to {target_phase.value}."
            )

        # Gating rule: Cannot mark COMPLETE with unresolved critical issues
        if target_phase == ProjectPhase.COMPLETE and has_critical_critic_issues:
            raise StateTransitionError(
                "Cannot mark project as COMPLETE with unresolved CRITICAL critic issues."
            )

        # Loop counter increment if regressing to an earlier analytical state for revision
        is_revision = target_phase in {ProjectPhase.ANALYSIS_COMPLETE, ProjectPhase.METHOD_SELECTED} and current_phase in {
            ProjectPhase.TECHNICAL_REVIEW,
            ProjectPhase.BUSINESS_REVIEW,
        }

        new_iteration_count = iteration_count + (1 if is_revision else 0)

        # Check automated loop ceiling
        if is_revision and new_iteration_count > cls.MAX_AUTOMATED_REVISIONS:
            return current_phase, ProjectStatus.HUMAN_REVIEW_REQUIRED, new_iteration_count

        new_status = ProjectStatus.ACTIVE
        if target_phase == ProjectPhase.COMPLETE:
            new_status = ProjectStatus.COMPLETED
        elif is_revision:
            new_status = ProjectStatus.REVISION_REQUIRED

        return target_phase, new_status, new_iteration_count
