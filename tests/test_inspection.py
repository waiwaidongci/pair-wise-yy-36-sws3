import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, PermissionDenied, ValidationError
from src.repository import Repository
from src.service import Service
class InspectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
        self.item=self.service.create_item({"title":"inspection item","description":"inspection handoff","severity":"exceedance","quantity":5,"threshold":10,"external_ref":"INSP-1"},"creator","operator")
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def _reach_inspection(self):
        current=self.item
        for target,role in (("assessing","compliance_officer"),("remediation","operator"),("inspection","compliance_officer")):
            current=self.service.transition(current["id"],target,current["version"],"reviewer",role)
        return current
    def _defer(self,item_id):
        return self.service.register_inspection(item_id,{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"deferred","recheck_date":"2026-10-01","defer_reason":"停产待复检"},"officer","compliance_officer")
    def test_register_requires_inspection_state(self):
        with self.assertRaises(ConflictError): self.service.register_inspection(self.item["id"],{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"passed"},"officer","compliance_officer")
    def test_register_role_guard(self):
        current=self._reach_inspection()
        with self.assertRaises(PermissionDenied): self.service.register_inspection(current["id"],{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"passed"},"op","operator")
    def test_deferred_requires_recheck_date_and_reason(self):
        current=self._reach_inspection()
        with self.assertRaises(ValidationError): self.service.register_inspection(current["id"],{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"deferred","defer_reason":"停产待复检"},"officer","compliance_officer")
        with self.assertRaises(ValidationError): self.service.register_inspection(current["id"],{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"deferred","recheck_date":"2026-10-01"},"officer","compliance_officer")
        with self.assertRaises(ValidationError): self.service.register_inspection(current["id"],{"inspection_date":"09/27","inspector":"张工","conclusion":"passed"},"officer","compliance_officer")
    def test_close_blocked_without_any_inspection(self):
        current=self._reach_inspection()
        detail=self.service.get_item(current["id"],"director")
        self.assertIn("尚未登记现场检查",detail["closure_blockers"])
        with self.assertRaises(ConflictError): self.service.transition(current["id"],"closed",current["version"],"boss","director")
    def test_single_pending_and_close_blocked_until_recheck_done(self):
        current=self._reach_inspection()
        insp=self._defer(current["id"]); self.assertEqual(insp["status"],"pending")
        with self.assertRaises(ConflictError): self.service.register_inspection(current["id"],{"inspection_date":"2026-09-28","inspector":"李工","conclusion":"passed"},"officer","compliance_officer")
        detail=self.service.get_item(current["id"],"director")
        self.assertTrue(any("检查" in b for b in detail["closure_blockers"]))
        with self.assertRaises(ConflictError) as ctx: self.service.transition(current["id"],"closed",current["version"],"boss","director")
        self.assertIn("检查",str(ctx.exception))
        with self.assertRaises(ValidationError): self.service.complete_inspection(current["id"],insp["id"],{"conclusion":"deferred"},"officer","compliance_officer")
        done=self.service.complete_inspection(current["id"],insp["id"],{"conclusion":"passed"},"officer","compliance_officer")
        self.assertEqual(done["status"],"completed")
        with self.assertRaises(ConflictError): self.service.complete_inspection(current["id"],insp["id"],{"conclusion":"passed"},"officer","compliance_officer")
        closed=self.service.transition(current["id"],"closed",current["version"],"boss","director")
        self.assertEqual(closed["status"],"closed"); self.assertTrue(self.repo.verify_audit_chain())
    def test_exceeded_rolls_back_and_recalculates(self):
        current=self._reach_inspection()
        before=self.service.get_item(current["id"],"viewer")
        insp=self.service.register_inspection(current["id"],{"inspection_date":"2026-09-27","inspector":"张工","conclusion":"exceeded","latest_quantity":30},"officer","compliance_officer")
        self.assertEqual(insp["status"],"completed")
        after=self.service.get_item(current["id"],"viewer")
        self.assertEqual(after["status"],"remediation"); self.assertEqual(after["quantity"],30.0)
        self.assertGreater(after["priority"],before["priority"]); self.assertLess(after["deadline_hours"],before["deadline_hours"])
        self.assertEqual(after["version"],before["version"]+1)
        with self.assertRaises(ConflictError): self.service.register_inspection(current["id"],{"inspection_date":"2026-09-28","inspector":"李工","conclusion":"passed"},"officer","compliance_officer")
        self.assertTrue(self.repo.verify_audit_chain())
    def test_recheck_exceeded_rolls_back(self):
        current=self._reach_inspection()
        insp=self._defer(current["id"])
        self.service.complete_inspection(current["id"],insp["id"],{"conclusion":"exceeded","latest_quantity":25},"officer","compliance_officer")
        after=self.service.get_item(current["id"],"viewer")
        self.assertEqual(after["status"],"remediation"); self.assertEqual(after["quantity"],25.0)
if __name__=="__main__": unittest.main()
