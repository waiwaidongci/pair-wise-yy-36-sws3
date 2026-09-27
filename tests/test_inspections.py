import tempfile, unittest
from pathlib import Path
from src import rules
from src.domain import ConflictError, PermissionDenied, ValidationError
from src.repository import Repository
from src.service import Service
class InspectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
        item=self.service.create_item({"title":"inspection item","description":"inspection handover","severity":"watch","quantity":5,"threshold":10,"external_ref":"INSP-1"},"creator","operator")
        current=item
        for target,role in (("assessing","compliance_officer"),("remediation","operator"),("inspection","compliance_officer")):
            current=self.service.transition(current["id"],target,current["version"],"mover",role)
        self.item=current
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def _register(self):
        return self.service.register_inspection(self.item["id"],{"inspection_date":"2026-09-27","handler":"承办人甲"},"officer","compliance_officer")
    def test_register_complete_then_director_closes(self):
        with self.assertRaises(ConflictError): self.service.transition(self.item["id"],"closed",self.item["version"],"chief","director")
        detail=self.service.get_item(self.item["id"],"director")
        self.assertIn("尚无现场检查记录",detail["close_blockers"])
        inspection=self._register(); self.assertEqual(inspection["status"],"pending")
        with self.assertRaises(ConflictError): self._register()
        detail=self.service.get_item(self.item["id"],"director")
        self.assertIn("最近检查未完成",detail["close_blockers"])
        done=self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"passed"},"officer","compliance_officer")
        self.assertEqual(done["status"],"completed"); self.assertEqual(done["conclusion"],"passed")
        detail=self.service.get_item(self.item["id"],"director")
        self.assertEqual(detail["close_blockers"],[]); self.assertEqual(detail["latest_inspection"]["id"],inspection["id"])
        closed=self.service.transition(self.item["id"],"closed",detail["version"],"chief","director")
        self.assertEqual(closed["status"],"closed")
    def test_defer_needs_recheck_and_reason_then_new_pending_allowed(self):
        inspection=self._register()
        with self.assertRaises(ValidationError): self.service.defer_inspection(self.item["id"],inspection["id"],{"recheck_date":"2026-09-20","reason":"设备故障"},"officer","compliance_officer")
        with self.assertRaises(ValidationError): self.service.defer_inspection(self.item["id"],inspection["id"],{"recheck_date":"2026-10-05","reason":" "},"officer","compliance_officer")
        deferred=self.service.defer_inspection(self.item["id"],inspection["id"],{"recheck_date":"2026-10-05","reason":"暴雨无法进场"},"officer","compliance_officer")
        self.assertEqual(deferred["status"],"deferred"); self.assertEqual(deferred["recheck_date"],"2026-10-05")
        detail=self.service.get_item(self.item["id"],"director")
        self.assertIn("最近检查已暂缓，等待复检",detail["close_blockers"])
        followup=self._register(); self.assertEqual(followup["status"],"pending")
        self.service.complete_inspection(self.item["id"],followup["id"],{"conclusion":"passed"},"officer","compliance_officer")
        self.assertEqual(self.service.get_item(self.item["id"],"director")["close_blockers"],[])
    def test_exceedance_returns_to_remediation_and_recalculates(self):
        inspection=self._register()
        with self.assertRaises(ValidationError): self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"exceedance_found","new_quantity":3},"officer","compliance_officer")
        with self.assertRaises(ValidationError): self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"exceedance_found"},"officer","compliance_officer")
        done=self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"exceedance_found","new_quantity":30},"officer","compliance_officer")
        self.assertEqual(done["conclusion"],"exceedance_found"); self.assertEqual(done["new_quantity"],30.0)
        item=self.service.get_item(self.item["id"],"viewer")
        self.assertEqual(item["status"],"remediation"); self.assertEqual(item["quantity"],30.0)
        self.assertEqual(item["priority"],rules.priority_score("watch",30,10))
        self.assertEqual(item["deadline_hours"],rules.response_deadline_hours("watch",30,10))
        with self.assertRaises(ConflictError): self._register()
    def test_role_guards(self):
        with self.assertRaises(PermissionDenied): self.service.register_inspection(self.item["id"],{"inspection_date":"2026-09-27","handler":"x"},"op","operator")
        inspection=self._register()
        with self.assertRaises(PermissionDenied): self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"passed"},"chief","director")
        with self.assertRaises(PermissionDenied): self.service.defer_inspection(self.item["id"],inspection["id"],{"recheck_date":"2026-10-01","reason":"r"},"guest","viewer")
    def test_complete_twice_conflicts_and_audit_chain_holds(self):
        inspection=self._register()
        self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"passed"},"officer","compliance_officer")
        with self.assertRaises(ConflictError): self.service.complete_inspection(self.item["id"],inspection["id"],{"conclusion":"passed"},"officer","compliance_officer")
        with self.assertRaises(ConflictError): self.service.defer_inspection(self.item["id"],inspection["id"],{"recheck_date":"2026-10-01","reason":"r"},"officer","compliance_officer")
        actions=[e["action"] for e in self.service.audit("director",self.item["id"])]
        self.assertIn("inspection_register",actions); self.assertIn("inspection_complete",actions)
        self.assertTrue(self.repo.verify_audit_chain())
if __name__=="__main__": unittest.main()
