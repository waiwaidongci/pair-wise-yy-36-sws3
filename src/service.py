from __future__ import annotations

from typing import Any, Dict, Optional

from .domain import (ConflictError, ensure_role, normalize_severity,
                     require_date, require_number, require_text)
from .repository import Repository
from .rules import (AUDIT_ROLES, CREATE_ROLES, ENTITY, INSPECTION_RETURN_STATE,
                    INSPECTION_ROLES, INSPECTION_STAGE, RECORD_ROLES, TITLE,
                    VIEW_ROLES, completion_blockers, ensure_inspection_stage,
                    escalation_required, normalize_conclusion, priority_score,
                    response_deadline_hours, role_for_transition,
                    validate_deferral, validate_new_exceedance,
                    validate_transition)


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

    def register_inspection(self, item_id: int, payload: Dict[str, Any], actor: str,
                            role: str) -> Dict[str, Any]:
        ensure_role(role, INSPECTION_ROLES)
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        ensure_inspection_stage(item["status"])
        if self.repository.pending_inspection(item_id) is not None:
            raise ConflictError("已存在待办检查，请先完成或暂缓")
        inspection_date = require_date(payload.get("inspection_date"), "inspection_date")
        handler = require_text(payload.get("handler"), "handler", 100)
        inspection = self.repository.create_inspection(item_id, inspection_date,
                                                       handler, actor)
        self.repository.append_audit("inspection_register", ENTITY, item_id, actor, {
            "inspection_id": inspection["id"], "inspection_date": inspection_date,
            "handler": handler,
        })
        return inspection

    def complete_inspection(self, item_id: int, inspection_id: int,
                            payload: Dict[str, Any], actor: str,
                            role: str) -> Dict[str, Any]:
        ensure_role(role, INSPECTION_ROLES)
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        conclusion = normalize_conclusion(payload.get("conclusion"))
        new_quantity = None
        return_state = None
        if conclusion == "exceedance_found":
            new_quantity = require_number(payload.get("new_quantity"), "new_quantity",
                                          0.000001)
            validate_new_exceedance(new_quantity, item["threshold"])
            return_state = INSPECTION_RETURN_STATE
        inspection = self.repository.complete_inspection(
            item_id, inspection_id, conclusion, new_quantity, return_state)
        self.repository.append_audit("inspection_complete", ENTITY, item_id, actor, {
            "inspection_id": inspection["id"], "conclusion": conclusion,
            "new_quantity": new_quantity, "return_state": return_state,
        })
        return inspection

    def defer_inspection(self, item_id: int, inspection_id: int, payload: Dict[str, Any],
                         actor: str, role: str) -> Dict[str, Any]:
        ensure_role(role, INSPECTION_ROLES)
        actor = require_text(actor, "actor", 100)
        inspection = self.repository.get_inspection(item_id, inspection_id)
        recheck_date = require_date(payload.get("recheck_date"), "recheck_date")
        reason = require_text(payload.get("reason"), "reason")
        validate_deferral(inspection["inspection_date"], recheck_date)
        inspection = self.repository.defer_inspection(item_id, inspection_id,
                                                      recheck_date, reason)
        self.repository.append_audit("inspection_defer", ENTITY, item_id, actor, {
            "inspection_id": inspection["id"], "recheck_date": recheck_date,
            "reason": reason,
        })
        return inspection

    def get_item(self, item_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        item = self.repository.get_item(item_id)
        result = self.enrich(item)
        result["latest_inspection"] = self.repository.latest_inspection(item_id)
        result["close_blockers"] = self._close_blockers(item)
        return result

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

    def _close_blockers(self, item: Dict[str, Any]) -> list:
        if item["status"] != INSPECTION_STAGE:
            return []
        return completion_blockers("closed",
                                   self.repository.open_record_count(item["id"]),
                                   self.repository.latest_inspection(item["id"]))

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
