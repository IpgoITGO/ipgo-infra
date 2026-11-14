"""합성 병합 조건만 검사. GitHub·병합·배포 없음."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import session

class MergeGuardTests(unittest.TestCase):
    def fixture(self):
        return {"headRefOid":"a"*40,"baseRefName":"dev","state":"OPEN","isDraft":False,
                "mergeable":"MERGEABLE","mergeStateStatus":"CLEAN","author":{"login":"fixture"},
                "reviewDecision":"","latestReviews":[],"threads":{"pageInfo":{"hasNextPage":False},"nodes":[]},
                "statusCheckRollup":[{"name":"test","status":"COMPLETED","conclusion":"SUCCESS"}]}

    def run_guard(self, directory, snapshot):
        source=directory/"snapshot.json";plan=directory/"plan.json"
        source.write_text(json.dumps(snapshot));plan.write_text(json.dumps({"sha":"a"*40,"author":"fixture","checks":["test"]}))
        return session.merge_guard(directory,source,plan)

    def test_pass_preserves_input_without_granting_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);result=self.run_guard(directory,self.fixture())
            self.assertEqual(result["state"],"MERGE_GUARD_PASSED")
            self.assertFalse(result["authorization_granted"])
            self.assertEqual(json.loads(Path(result["input"]["path"]).read_text())["snapshot"],self.fixture())

    def test_block_records_exact_reasons_and_original_before_return(self):
        cases=[("mergeStateStatus","UNKNOWN","MERGE_STATE"),("headRefOid","b"*40,"HEAD_CHANGED"),
               ("reviewDecision","REVIEW_REQUIRED","APPROVAL"),("statusCheckRollup",[],"CHECK_SET"),
               ("threads",{"pageInfo":{"hasNextPage":True},"nodes":[]},"INCOMPLETE_REVIEW_THREADS"),
               ("baseRefName","main","BASE_BRANCH"),("isDraft",True,"DRAFT"),
               ("latestReviews",[{"state":"CHANGES_REQUESTED"}],"CHANGES_REQUESTED"),
               ("threads",{"pageInfo":{"hasNextPage":False},"nodes":[{"isResolved":False}]},"UNRESOLVED_REVIEW"),
               ("statusCheckRollup",[{"name":"test","status":"COMPLETED","conclusion":"FAILURE"}],"CHECK_RESULT")]
        for field,value,code in cases:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);snapshot=self.fixture();snapshot[field]=value
                result=self.run_guard(directory,snapshot)
                self.assertEqual(result["state"],"BLOCKED")
                self.assertIn(code,[r["code"] for r in result["reasons"]])
                self.assertEqual(json.loads(Path(result["input"]["path"]).read_text())["snapshot"],snapshot)
                self.assertEqual(len(list(directory.glob("merge-guard-*-result.json"))),1)

    def test_later_success_never_overwrites_failed_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);snapshot=self.fixture();snapshot["mergeStateStatus"]="UNKNOWN"
            first=self.run_guard(directory,snapshot);original=Path(first["input"]["path"]).read_bytes()
            second=self.run_guard(directory,self.fixture())
            self.assertEqual(second["state"],"MERGE_GUARD_PASSED")
            self.assertEqual(Path(first["input"]["path"]).read_bytes(),original)
            self.assertEqual(len(list(directory.glob("merge-guard-*-result.json"))),2)

    def test_missing_author_cannot_pass_even_if_snapshot_author_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);snapshot=self.fixture();snapshot.pop("author")
            source=directory/"snapshot.json";source.write_text(json.dumps(snapshot))
            plan=directory/"plan.json";plan.write_text(json.dumps({"sha":"a"*40,"checks":["test"]}))
            result=session.merge_guard(directory,source,plan)
            self.assertEqual(result["state"],"BLOCKED")
            self.assertIn("INVALID_PLAN_AUTHOR",[r["code"] for r in result["reasons"]])

    def test_non_object_input_preserves_raw_and_returns_explicit_block_reason(self):
        for target in ("snapshot", "plan"):
            for value in ([], None, "bad"):
                with self.subTest(target=target, value=value), tempfile.TemporaryDirectory() as temp:
                    directory=Path(temp)
                    snapshot=self.fixture();plan={"sha":"a"*40,"author":"fixture","checks":["test"]}
                    if target=="snapshot":snapshot=value
                    else:plan=value
                    source=directory/"snapshot.json";source.write_text(json.dumps(snapshot))
                    path=directory/"plan.json";path.write_text(json.dumps(plan))
                    result=session.merge_guard(directory,source,path)
                    self.assertEqual(result["state"],"BLOCKED")
                    self.assertIn(target.upper()+"_TYPE",[r["code"] for r in result["reasons"]])
                    self.assertEqual(json.loads(Path(result["input"]["path"]).read_text())[target],value)
                    self.assertEqual(len(list(directory.glob("merge-guard-*-result.json"))),1)

    def test_null_or_malformed_ci_checks_are_explicitly_blocked(self):
        for value in (None, {}, [None], ["bad"]):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);snapshot=self.fixture();snapshot["statusCheckRollup"]=value
                result=self.run_guard(directory,snapshot)
                self.assertEqual(result["state"],"BLOCKED")
                self.assertIn("CHECKS_TYPE",[r["code"] for r in result["reasons"]])
                self.assertEqual(json.loads(Path(result["input"]["path"]).read_text())["snapshot"]["statusCheckRollup"],value)
                self.assertEqual(len(list(directory.glob("merge-guard-*-result.json"))),1)

if __name__=="__main__":
    unittest.main()
