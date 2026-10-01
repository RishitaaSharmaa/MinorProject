"""Replay state events through the indexed watcher and score it against ground truth.

The replay drives ``AssumptionWatcher`` exactly as production would: recorded
assumptions are registered as their decisions are made, events are then applied
in time order, and each event rechecks only the assumptions indexed under its
``(entity, field)`` pair.

Two numbers are reported side by side:

* ``evaluations`` - condition evaluations the indexed watcher actually made;
* ``full recheck`` - condition evaluations a naive implementation would make by
  walking every registered assumption for every event.

Detection quality is scored against ``ground_truth_violations``: a prediction is
one ``(event_id, decision_id)`` pair the watcher flagged, and the metrics are
precision, recall, and F1 over those pairs.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from app.services.evaluator import UnsupportedConditionError
from app.services.watcher import AssumptionWatcher

from scripts.replay_io import (
    DEFAULT_DATA_DIR,
    GroundTruthViolation,
    RecordedAssumption,
    load_decision_dates,
    load_ground_truth,
    load_recorded_assumptions,
    load_state_events,
)

ViolationPair = tuple[str, str]

#: How many false-positive and false-negative pairs the report lists inline.
EXAMPLE_LIMIT = 10


@dataclass(frozen=True)
class DetectionScore:
    """Pair-level detection quality for one slice of the replay."""

    predicted: int
    expected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class FieldScore:
    """Detection quality restricted to the events touching one state field."""

    field: str
    score: DetectionScore


@dataclass(frozen=True)
class ReplayMetrics:
    """Complete result of one replay run."""

    events_processed: int
    assumptions_registered: int
    unsupported_conditions: int
    evaluations: int
    full_recheck_evaluations: int
    recoveries: int
    unknown_evaluations: int
    score: DetectionScore
    by_field: tuple[FieldScore, ...]
    false_positives: tuple[ViolationPair, ...]
    false_negatives: tuple[ViolationPair, ...]

    @property
    def evaluation_reduction(self) -> float:
        """Fraction of condition evaluations the index avoided."""
        if not self.full_recheck_evaluations:
            return 0.0
        return 1.0 - (self.evaluations / self.full_recheck_evaluations)


def score_pairs(predicted: set[ViolationPair], expected: set[ViolationPair]) -> DetectionScore:
    """Score predicted violation pairs against answer-key violation pairs."""
    true_positives = len(predicted & expected)
    false_positives = len(predicted - expected)
    false_negatives = len(expected - predicted)
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return DetectionScore(
        predicted=len(predicted),
        expected=len(expected),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def replay(
    data_dir: Path = DEFAULT_DATA_DIR,
    watcher: AssumptionWatcher | None = None,
) -> ReplayMetrics:
    """Replay every state event in time order and score the watcher's detections."""
    engine = watcher if watcher is not None else AssumptionWatcher()
    assumptions = load_recorded_assumptions(data_dir, load_decision_dates(data_dir))
    events = load_state_events(data_dir)
    ground_truth = load_ground_truth(data_dir)
    fields_by_event = {event.event_id: event.field for event in events}

    pending = 0
    unsupported = 0
    full_recheck = 0
    recoveries = 0
    unknown = 0

    for event in events:
        pending, skipped = _register_due_assumptions(engine, assumptions, pending, event.event_time)
        unsupported += skipped
        full_recheck += engine.active_assumption_count()
        outcome = engine.process_event(event)
        recoveries += len(outcome.recoveries)
        unknown += len(outcome.unknown)
    registered = pending

    predicted = {
        (record.event_id, record.decision_id)
        for record in engine.violations()
        if record.event_id is not None
    }
    expected = _ground_truth_pairs(ground_truth)
    score = score_pairs(predicted, expected)

    return ReplayMetrics(
        events_processed=len(events),
        assumptions_registered=registered,
        unsupported_conditions=unsupported,
        evaluations=engine.evaluations,
        full_recheck_evaluations=full_recheck,
        recoveries=recoveries,
        unknown_evaluations=unknown,
        score=score,
        by_field=_score_by_field(predicted, expected, fields_by_event),
        false_positives=tuple(sorted(predicted - expected))[:EXAMPLE_LIMIT],
        false_negatives=tuple(sorted(expected - predicted))[:EXAMPLE_LIMIT],
    )


def _register_due_assumptions(
    watcher: AssumptionWatcher,
    assumptions: list[RecordedAssumption],
    pointer: int,
    event_time,
) -> tuple[int, int]:
    """Register assumptions recorded strictly before an event's timestamp.

    Returns the advanced pointer and how many assumptions were skipped because
    their condition could not be mapped onto the checkable vocabulary.
    """
    index = pointer
    skipped = 0
    while index < len(assumptions) and event_time is not None and assumptions[index].recorded_at < event_time:
        assumption = assumptions[index]
        try:
            watcher.watch(
                assumption.assumption_id,
                assumption.decision_id,
                assumption.condition,
                created_at=assumption.recorded_at,
            )
        except UnsupportedConditionError as error:
            skipped += 1
            print(f"WARNING {assumption.assumption_id}: {error}", file=sys.stderr)
        index += 1
    return index, skipped


def _ground_truth_pairs(violations: list[GroundTruthViolation]) -> set[ViolationPair]:
    """Collapse answer-key rows into the scored event/decision pairs."""
    return {(violation.event_id, violation.decision_id) for violation in violations}


def _score_by_field(
    predicted: set[ViolationPair],
    expected: set[ViolationPair],
    fields_by_event: dict[str | None, str],
) -> tuple[FieldScore, ...]:
    """Score detections separately for each touched state field."""
    fields = sorted({fields_by_event.get(pair[0], "?") for pair in predicted | expected})
    scores = []
    for field in fields:
        predicted_field = {pair for pair in predicted if fields_by_event.get(pair[0], "?") == field}
        expected_field = {pair for pair in expected if fields_by_event.get(pair[0], "?") == field}
        scores.append(FieldScore(field=field, score=score_pairs(predicted_field, expected_field)))
    return tuple(scores)


def _format_score(label: str, score: DetectionScore) -> str:
    """Render one detection score as a fixed-width report row."""
    return (
        f"{label:<22} {score.precision:>9.3f} {score.recall:>9.3f} {score.f1:>9.3f}"
        f" {score.true_positives:>6} {score.false_positives:>6} {score.false_negatives:>6}"
    )


def print_report(metrics: ReplayMetrics) -> None:
    """Print the replay cost comparison and the detection metrics."""
    print("Replay cost")
    print(f"  events processed           {metrics.events_processed}")
    print(f"  assumptions registered     {metrics.assumptions_registered}")
    print(f"  unsupported conditions     {metrics.unsupported_conditions}")
    print(f"  indexed evaluations        {metrics.evaluations}")
    print(f"  recheck-everything         {metrics.full_recheck_evaluations}")
    print(f"  evaluations avoided        {metrics.evaluation_reduction:>9.1%}")
    print(f"  recoveries reversed        {metrics.recoveries}")
    print(f"  unknown evaluations        {metrics.unknown_evaluations}")

    print("\nDetection against ground_truth_violations")
    print(f"{'slice':<22} {'precision':>9} {'recall':>9} {'f1':>9} {'tp':>6} {'fp':>6} {'fn':>6}")
    print("-" * 74)
    print(_format_score("ALL EVENTS", metrics.score))
    for field_score in metrics.by_field:
        print(_format_score(field_score.field, field_score.score))

    print(f"\npredicted pairs {metrics.score.predicted}, ground-truth pairs {metrics.score.expected}")
    if metrics.false_positives:
        print("false positives (event, decision):")
        for event_id, decision_id in metrics.false_positives:
            print(f"  {event_id} {decision_id}")
    if metrics.false_negatives:
        print("false negatives (event, decision):")
        for event_id, decision_id in metrics.false_negatives:
            print(f"  {event_id} {decision_id}")


def main() -> None:
    """Parse options, replay the dataset, and print the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    metrics = replay(args.data_dir)
    print(f"Replayed from {args.data_dir}")
    print_report(metrics)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Replay failed: {error}", file=sys.stderr)
        raise
