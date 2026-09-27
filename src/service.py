from __future__ import annotations

from typing import Any, Dict, Optional

from .domain import (ConflictError, ValidationError, ensure_role,
                     normalize_conclusion, normalize_severity, require_date,
                     require_number, require_text)
from .repository import Repository
from .rules import (AUDIT_ROLES, CREATE_ROLES, ENTITY, INSPECT_ROLES,
                    RECHECK_CONCLUSIONS, RECORD_ROLES, TITLE, VIEW_ROLES,
                    closure_blockers, completion_blockers, escalation_required,
                    has_pending_inspection, inspection_status_for,
                    needs_recheck_info, priority_score,
                    response_deadline_hours, rollback_target,
                    role_for_transition, validate_transition)


class Service:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _view(self, role: str) -> None:
        ensure_role(role, VIEW_ROLES)

    def create_item(self, payload: Dict[str, Any], actor: str, role: str) -> Dict[str, Any]:
        ensure_role(role, CREATE_ROLES)
        actor = require_text(actor, "actor", 100)
        title = require_text(payload.get("title"), "title", 200)
        description = require_text(payload.get("description"), "description")
        severity = normalize_severity(payload.get("severity"))
        quantity = require_number(payload.get("quantity", 0), "quantity")
        threshold = require_number(payload.get("threshold", 1), "threshold", 0.000001)
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        item = self.repository.create_item(title, description, severity, quantity,
                                           threshold, external_ref, actor)
        self.repository.append_audit("create", ENTITY, item["id"], actor, {
            "title": title, "severity": severity, "quantity": quantity,
            "priority": priority_score(severity, quantity, threshold),
        })
        return self.enrich(item)

    def add_record(self, item_id: int, payload: Dict[str, Any], actor: str,
                   role: str) -> Dict[str, Any]:
        ensure_role(role, RECORD_ROLES)
        actor = require_text(actor, "actor", 100)
        kind = require_text(payload.get("kind"), "kind", 100)
        detail = require_text(payload.get("detail"), "detail")
        status = payload.get("status", "open")
        if status not in ("open", "closed"):
            raise ValueError("status必须是open或closed")
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        record = self.repository.add_record(item_id, kind, detail, status,
                                            external_ref, actor)
        self.repository.append_audit("record", ENTITY, item_id, actor, {
            "record_id": record["id"], "kind": kind, "status": status,
        })
        return record

    def register_inspection(self, item_id: int, payload: Dict[str, Any], actor: str,
                            role: str) -> Dict[str, Any]:
        ensure_role(role, INSPECT_ROLES)
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        if item["status"] != "inspection":
            raise ConflictError("事件未处于复查状态，不能登记检查")
        if has_pending_inspection(self.repository.latest_inspection(item_id)):
            raise ConflictError("该事件已有一笔待办检查，请先完成复检")
        inspection_date = require_date(payload.get("inspection_date"), "inspection_date")
        inspector = require_text(payload.get("inspector"), "inspector", 100)
        conclusion = normalize_conclusion(payload.get("conclusion"))
        recheck_date = defer_reason = latest_quantity = None
        if needs_recheck_info(conclusion):
            recheck_date = require_date(payload.get("recheck_date"), "recheck_date")
            defer_reason = require_text(payload.get("defer_reason"), "defer_reason")
        if rollback_target(conclusion) is not None:
            latest_quantity = require_number(payload.get("latest_quantity"), "latest_quantity")
        inspection = self.repository.add_inspection(
            item_id, inspection_date, inspector, conclusion,
            inspection_status_for(conclusion), recheck_date, defer_reason,
            latest_quantity, actor)
        self.repository.append_audit("inspection", ENTITY, item_id, actor, {
            "inspection_id": inspection["id"], "conclusion": conclusion,
            "inspector": inspector, "status": inspection["status"],
        })
        self._maybe_rollback(item, conclusion, latest_quantity, actor)
        return inspection

    def complete_inspection(self, item_id: int, inspection_id: int,
                            payload: Dict[str, Any], actor: str, role: str) -> Dict[str, Any]:
        ensure_role(role, INSPECT_ROLES)
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        if item["status"] != "inspection":
            raise ConflictError("事件未处于复查状态，不能复检")
        conclusion = normalize_conclusion(payload.get("conclusion"))
        if conclusion not in RECHECK_CONCLUSIONS:
            raise ValidationError("复检结论只能是passed或exceeded")
        latest_quantity = None
        if rollback_target(conclusion) is not None:
            latest_quantity = require_number(payload.get("latest_quantity"), "latest_quantity")
        inspection = self.repository.complete_inspection(
            item_id, inspection_id, conclusion, latest_quantity, actor)
        self.repository.append_audit("recheck", ENTITY, item_id, actor, {
            "inspection_id": inspection["id"], "conclusion": conclusion,
        })
        self._maybe_rollback(item, conclusion, latest_quantity, actor)
        return inspection

    def _maybe_rollback(self, item: Dict[str, Any], conclusion: str,
                        latest_quantity: Optional[float], actor: str) -> None:
        target = rollback_target(conclusion)
        if target is None:
            return
        self.repository.rollback_item(item["id"], target, latest_quantity, actor)
        self.repository.append_audit("transition", ENTITY, item["id"], actor, {
            "from": item["status"], "to": target,
            "reason": "检查发现新的超标问题，退回整改",
            "latest_quantity": latest_quantity,
        })

    def transition(self, item_id: int, target: str, expected_version: int,
                   actor: str, role: str) -> Dict[str, Any]:
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        validate_transition(item["status"], target)
        ensure_role(role, role_for_transition(target))
        if not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version必须是正整数")
        blockers = completion_blockers(target, self.repository.open_record_count(item_id),
                                       self.repository.latest_inspection(item_id))
        if blockers:
            raise ConflictError("；".join(blockers))
        updated = self.repository.transition_item(item_id, target, expected_version, actor)
        self.repository.append_audit("transition", ENTITY, item_id, actor, {
            "from": item["status"], "to": target,
            "escalation_required": escalation_required(
                item["severity"], item["quantity"], item["threshold"]),
        })
        return self.enrich(updated)

    def get_item(self, item_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        item = self.enrich(self.repository.get_item(item_id))
        latest = self.repository.latest_inspection(item_id)
        item["latest_inspection"] = latest
        item["closure_blockers"] = closure_blockers(
            self.repository.open_record_count(item_id), latest)
        return item

    def list_items(self, role: str, status: Optional[str] = None) -> list:
        self._view(role)
        return [self.enrich(item) for item in self.repository.list_items(status)]

    def list_records(self, item_id: int, role: str) -> list:
        self._view(role)
        return self.repository.list_records(item_id)

    def list_inspections(self, item_id: int, role: str) -> list:
        self._view(role)
        return self.repository.list_inspections(item_id)

    def audit(self, role: str, item_id: Optional[int] = None) -> list:
        ensure_role(role, AUDIT_ROLES)
        return self.repository.list_audit(item_id)

    @staticmethod
    def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(item)
        result["priority"] = priority_score(
            item["severity"], item["quantity"], item["threshold"])
        result["deadline_hours"] = response_deadline_hours(
            item["severity"], item["quantity"], item["threshold"])
        result["escalation_required"] = escalation_required(
            item["severity"], item["quantity"], item["threshold"])
        return result
