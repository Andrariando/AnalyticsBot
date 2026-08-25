import pytest
from app.tools.file_tools import FileIngestionService, FileSecurityError
from app.core.state_machine import ProjectStateMachine, ProjectPhase, ProjectStatus, StateTransitionError


def test_filename_sanitization():
    unsafe_name = "../../sensitive/data.csv"
    clean = FileIngestionService.sanitize_filename(unsafe_name)
    assert ".." not in clean
    assert clean == "data.csv"

    special_chars = "my data file (v1) #2.xlsx"
    clean_special = FileIngestionService.sanitize_filename(special_chars)
    assert clean_special == "my_data_file__v1___2.xlsx"


def test_project_workspace_isolation():
    p1_dir = FileIngestionService.initialize_project_workspace("project_alpha")
    p2_dir = FileIngestionService.initialize_project_workspace("project_beta")

    assert p1_dir != p2_dir
    assert p1_dir.exists()
    assert p2_dir.exists()
    assert (p1_dir / "raw").exists()
    assert (p2_dir / "raw").exists()


def test_state_machine_valid_flow():
    # Valid step-by-step progress
    phase, status, iters = ProjectStateMachine.transition(
        current_phase=ProjectPhase.INITIALIZED,
        target_phase=ProjectPhase.PROBLEM_FRAMED,
    )
    assert phase == ProjectPhase.PROBLEM_FRAMED
    assert status == ProjectStatus.ACTIVE

    phase, status, iters = ProjectStateMachine.transition(
        current_phase=ProjectPhase.PROBLEM_FRAMED,
        target_phase=ProjectPhase.DATA_PROFILED,
    )
    assert phase == ProjectPhase.DATA_PROFILED

    phase, status, iters = ProjectStateMachine.transition(
        current_phase=ProjectPhase.DATA_PROFILED,
        target_phase=ProjectPhase.METHOD_SELECTED,
    )
    assert phase == ProjectPhase.METHOD_SELECTED


def test_state_machine_blocks_illegal_transition():
    # Cannot jump from INITIALIZED directly to COMPLETE
    with pytest.raises(StateTransitionError, match="Illegal state transition"):
        ProjectStateMachine.transition(
            current_phase=ProjectPhase.INITIALIZED,
            target_phase=ProjectPhase.COMPLETE,
        )


def test_state_machine_blocks_completion_with_critical_issues():
    # Cannot mark COMPLETE if critical review issues are unresolved
    with pytest.raises(StateTransitionError, match="CRITICAL"):
        ProjectStateMachine.transition(
            current_phase=ProjectPhase.DOCUMENTATION,
            target_phase=ProjectPhase.COMPLETE,
            has_critical_critic_issues=True,
        )


def test_state_machine_revision_cycle_limit():
    # Simulate 4 revisions from technical review back to analysis
    current = ProjectPhase.TECHNICAL_REVIEW
    iters = 0
    for _ in range(3):
        target, status, iters = ProjectStateMachine.transition(
            current_phase=current,
            target_phase=ProjectPhase.ANALYSIS_COMPLETE,
            iteration_count=iters,
        )
        assert status == ProjectStatus.REVISION_REQUIRED

    # 4th revision must trigger HUMAN_REVIEW_REQUIRED
    target, status, iters = ProjectStateMachine.transition(
        current_phase=current,
        target_phase=ProjectPhase.ANALYSIS_COMPLETE,
        iteration_count=iters,
    )
    assert status == ProjectStatus.HUMAN_REVIEW_REQUIRED
