"""
Banker's Algorithm Engine
=========================
Implements the classic Banker's deadlock-avoidance algorithm adapted for
hospital resource safety analysis during pandemic patient admission.

Terminology mapping:
  processes  -> patients
  resources  -> hospital resources (ICU beds, oxygen, etc.)
  allocation -> currently allocated resources per patient
  max_demand -> maximum resources a patient might need
  available  -> currently free resource units
"""

from __future__ import annotations

from typing import Any, Optional


def compute_deficit(need: list[int], work: list[int]) -> list[int]:
    """deficit[j] = max(0, Need[j] - Work[j]) for component-wise comparison."""
    return [max(0, need[j] - work[j]) for j in range(len(need))]


def need_le_work(need: list[int], work: list[int]) -> bool:
    """Component-wise: Need[i] <= Work."""
    return all(need[j] <= work[j] for j in range(len(need)))


class BankersEngine:
    """
    Manages resource allocation state and determines system safety
    using Dijkstra's Banker's Algorithm.
    """

    def __init__(self, total_resources: list[int], resource_names: list[str]) -> None:
        if len(total_resources) != len(resource_names):
            raise ValueError("total_resources and resource_names must have the same length")

        self.resource_names: list[str] = list(resource_names)
        self.total: list[int] = list(total_resources)
        self.available: list[int] = list(total_resources)

        self._allocation: dict[str, list[int]] = {}
        self._max_demand: dict[str, list[int]] = {}
        self._n_resources: int = len(total_resources)

    @property
    def num_resources(self) -> int:
        return self._n_resources

    @property
    def num_patients(self) -> int:
        return len(self._allocation)

    @property
    def patient_ids(self) -> list[str]:
        return list(self._allocation.keys())

    def add_patient(self, patient_id: str, allocation: list[int], max_demand: list[int]) -> None:
        if patient_id in self._allocation:
            raise ValueError(f"Patient '{patient_id}' already registered.")
        if len(allocation) != self._n_resources or len(max_demand) != self._n_resources:
            raise ValueError("Allocation/max_demand vector length mismatch.")
        for i in range(self._n_resources):
            if allocation[i] < 0 or max_demand[i] < 0:
                raise ValueError(
                    f"Patient '{patient_id}': negative value at resource index {i}."
                )
            if allocation[i] > max_demand[i]:
                raise ValueError(
                    f"Patient '{patient_id}': allocation[{i}]={allocation[i]} "
                    f"exceeds max_demand[{i}]={max_demand[i]}."
                )
            if allocation[i] > self.available[i]:
                raise ValueError(
                    f"Patient '{patient_id}': allocation[{i}]={allocation[i]} "
                    f"exceeds available[{i}]={self.available[i]}."
                )

        self._allocation[patient_id] = list(allocation)
        self._max_demand[patient_id] = list(max_demand)
        for i in range(self._n_resources):
            self.available[i] -= allocation[i]

    def remove_patient(self, patient_id: str) -> None:
        if patient_id not in self._allocation:
            raise KeyError(f"Patient '{patient_id}' not found.")
        for i in range(self._n_resources):
            self.available[i] += self._allocation[patient_id][i]
        del self._allocation[patient_id]
        del self._max_demand[patient_id]

    def allocated_totals(self) -> list[int]:
        """A_total[j] = sum_i Allocation[i][j]."""
        return [
            sum(self._allocation[pid][j] for pid in self._allocation)
            for j in range(self._n_resources)
        ]

    def set_total_resources(self, new_total: list[int]) -> None:
        """
        Update capacity C without changing existing allocations.

        Requires new_total[j] >= A_total[j] for every j. Available becomes
        C - A_total. Callers must overflow/release patients before shrinking
        capacity below current allocation; this method never destroys holdings.
        """
        if len(new_total) != self._n_resources:
            raise ValueError("new_total length must match the number of resources.")
        allocated = self.allocated_totals()
        for j in range(self._n_resources):
            if new_total[j] < 0:
                raise ValueError(f"new_total[{j}]={new_total[j]} is negative.")
            if new_total[j] < allocated[j]:
                raise ValueError(
                    f"Resource '{self.resource_names[j]}': cannot set total={new_total[j]} "
                    f"below allocated={allocated[j]}. Overflow or discharge patients first."
                )
        self.total = list(new_total)
        for j in range(self._n_resources):
            self.available[j] = self.total[j] - allocated[j]
        self.validate_invariants()

    def reset(self) -> None:
        self._allocation.clear()
        self._max_demand.clear()
        self.available = list(self.total)

    def need_matrix(self) -> dict[str, list[int]]:
        """Need[i] = Max[i] - Allocation[i] for every patient."""
        return {
            pid: [
                self._max_demand[pid][j] - self._allocation[pid][j]
                for j in range(self._n_resources)
            ]
            for pid in self._allocation
        }

    def validate_invariants(self) -> None:
        """
        Verify Banker's bookkeeping invariants.

        Total[j] = Available[j] + sum(Allocation[i][j])
        0 <= Allocation[i][j] <= Max[i][j]
        Need[i][j] >= 0
        Available[j] >= 0
        """
        for j in range(self._n_resources):
            if self.available[j] < 0:
                raise ValueError(
                    f"Resource '{self.resource_names[j]}': available={self.available[j]} < 0"
                )
            allocated_sum = sum(self._allocation[pid][j] for pid in self._allocation)
            if self.available[j] + allocated_sum != self.total[j]:
                raise ValueError(
                    f"Resource '{self.resource_names[j]}': "
                    f"available({self.available[j]}) + allocated({allocated_sum}) "
                    f"!= total({self.total[j]})"
                )

        for pid in self._allocation:
            for j in range(self._n_resources):
                alloc = self._allocation[pid][j]
                max_d = self._max_demand[pid][j]
                if alloc > max_d:
                    raise ValueError(
                        f"Patient '{pid}': allocation[{j}]={alloc} > max[{j}]={max_d}"
                    )
                if max_d - alloc < 0:
                    raise ValueError(
                        f"Patient '{pid}': negative need at resource index {j}"
                    )

    def is_safe(self) -> tuple[bool, list[str], Optional[str]]:
        safe, sequence, blocking, _, _ = self._run_safety_algorithm(record_trace=False)
        return safe, sequence, blocking

    def is_safe_with_trace(
        self,
    ) -> tuple[bool, list[str], Optional[str], list[dict[str, Any]], Optional[dict[str, Any]]]:
        """Returns (safe, sequence, blocking_resource, steps, post_mortem)."""
        return self._run_safety_algorithm(record_trace=True)

    def build_unsafe_post_mortem(
        self,
        patient_ids: list[str],
        need: list[list[int]],
        work: list[int],
        finish: list[bool],
        completed_sequence: list[str],
    ) -> dict[str, Any]:
        """
        Diagnostic summary when the safety algorithm deadlocks.

        deficit[i][j] = max(0, Need[i][j] - Work[j]) is a diagnostic measure only.
        Most constraining resource: argmax_j sum_{i unfinished} deficit[i][j].
        """
        remaining = [patient_ids[i] for i in range(len(patient_ids)) if not finish[i]]
        deficits: dict[str, list[int]] = {}
        explanations: list[str] = []

        resource_deficit_sum = [0] * self._n_resources
        for i, pid in enumerate(patient_ids):
            if finish[i]:
                continue
            d = compute_deficit(need[i], work)
            deficits[pid] = d
            for j in range(self._n_resources):
                resource_deficit_sum[j] += d[j]
            blocking_resources = [
                self.resource_names[j]
                for j in range(self._n_resources)
                if d[j] > 0
            ]
            if blocking_resources:
                parts = ", ".join(
                    f"{self.resource_names[j]} (need {need[i][j]}, work {work[j]})"
                    for j in range(self._n_resources)
                    if d[j] > 0
                )
                explanations.append(
                    f"Process {pid} cannot currently complete: deficit on {parts}."
                )

        most_constraining_index = (
            resource_deficit_sum.index(max(resource_deficit_sum))
            if any(resource_deficit_sum)
            else None
        )
        most_constraining = (
            self.resource_names[most_constraining_index]
            if most_constraining_index is not None
            else None
        )

        return {
            "completed_processes": list(completed_sequence),
            "remaining_processes": remaining,
            "final_work": list(work),
            "need_by_process": {
                patient_ids[i]: list(need[i])
                for i in range(len(patient_ids))
                if not finish[i]
            },
            "deficits_by_process": deficits,
            "resource_deficit_sum": {
                self.resource_names[j]: resource_deficit_sum[j]
                for j in range(self._n_resources)
            },
            "most_constraining_resource": most_constraining,
            "most_constraining_rule": (
                "Resource j maximizing sum of per-process deficits "
                "sum_i max(0, Need_i[j] - Work[j]) over unfinished processes. "
                "This is a diagnostic heuristic, not a unique causal bottleneck."
            ),
            "explanations": explanations,
        }

    def _run_safety_algorithm(
        self,
        record_trace: bool,
    ) -> tuple[bool, list[str], Optional[str], list[dict[str, Any]], Optional[dict[str, Any]]]:
        patient_ids = list(self._allocation.keys())
        n = len(patient_ids)

        work: list[int] = list(self.available)
        finish: list[bool] = [False] * n
        safe_sequence: list[str] = []
        steps: list[dict[str, Any]] = []
        post_mortem: Optional[dict[str, Any]] = None

        need: list[list[int]] = [
            [
                self._max_demand[pid][j] - self._allocation[pid][j]
                for j in range(self._n_resources)
            ]
            for pid in patient_ids
        ]

        step_num = 0
        if record_trace:
            steps.append({
                "step": step_num,
                "action": "initialize",
                "work_before": list(work),
                "work": list(work),
                "available": list(self.available),
                "finish": list(finish),
                "message": "Initialize Work = Available; Finish[i] = False for all patients.",
            })

        while len(safe_sequence) < n:
            found = False
            for i, pid in enumerate(patient_ids):
                if finish[i]:
                    continue

                work_before = list(work)
                alloc = list(self._allocation[pid])
                can_complete = need_le_work(need[i], work)

                if record_trace:
                    step_num += 1
                    work_after = (
                        [work_before[j] + alloc[j] for j in range(self._n_resources)]
                        if can_complete
                        else list(work_before)
                    )
                    steps.append({
                        "step": step_num,
                        "action": "check",
                        "patient": pid,
                        "need": list(need[i]),
                        "allocation": alloc,
                        "work_before": work_before,
                        "work_after": work_after,
                        "need_le_work": can_complete,
                        "finish": list(finish),
                        "safe_sequence_so_far": list(safe_sequence),
                        "message": (
                            f"Process {pid}: Need = {need[i]}, Work = {work_before}. "
                            f"Need <= Work: {'TRUE' if can_complete else 'FALSE'}"
                        ),
                    })

                if can_complete:
                    for j in range(self._n_resources):
                        work[j] += alloc[j]
                    finish[i] = True
                    safe_sequence.append(pid)
                    found = True
                    break

            if not found:
                post_mortem = self.build_unsafe_post_mortem(
                    patient_ids, need, work, finish, safe_sequence
                )
                blocking_resource = post_mortem["most_constraining_resource"]

                if record_trace:
                    step_num += 1
                    steps.append({
                        "step": step_num,
                        "action": "unsafe",
                        "work_before": list(work),
                        "work": list(work),
                        "finish": list(finish),
                        "blocking_resource": blocking_resource,
                        "post_mortem": post_mortem,
                        "message": (
                            "No unfinished process satisfies Need <= Work. State is UNSAFE."
                        ),
                    })

                return False, [], blocking_resource, steps, post_mortem

        if record_trace:
            step_num += 1
            steps.append({
                "step": step_num,
                "action": "safe",
                "work": list(work),
                "finish": [True] * n,
                "safe_sequence": list(safe_sequence),
                "message": f"All processes completed. Safe sequence: {' -> '.join(safe_sequence)}",
            })

        return True, safe_sequence, None, steps, None

    def snapshot(self) -> dict:
        return {
            "resource_names": self.resource_names,
            "total": list(self.total),
            "available": list(self.available),
            "work": list(self.available),
            "num_patients": self.num_patients,
            "allocation": {pid: list(v) for pid, v in self._allocation.items()},
            "max_demand": {pid: list(v) for pid, v in self._max_demand.items()},
            "need": self.need_matrix(),
        }

    def utilization(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for i, name in enumerate(self.resource_names):
            allocated = self.total[i] - self.available[i]
            result[name] = allocated / self.total[i] if self.total[i] > 0 else 0.0
        return result
