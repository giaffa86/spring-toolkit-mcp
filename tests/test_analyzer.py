from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.analyzer import analyze_project, generate_mockmvc_tests, generate_review


class AnalyzerTests(unittest.TestCase):
    def test_detects_spring_components_config_and_migration_risks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_demo_project(root)

            summary = analyze_project(root)

            self.assertEqual(summary["build"]["tool"], "maven")
            self.assertEqual(summary["component_counts"]["controller"], 1)
            self.assertEqual(summary["component_counts"]["service"], 1)
            self.assertEqual(summary["health"]["endpoint_count"], 1)
            self.assertEqual(summary["health"]["unsecured_endpoint_count"], 1)
            self.assertTrue(summary["health"]["uses_jpa"])

            config_entries = summary["configuration"][0]["entries"]
            secret = next(entry for entry in config_entries if entry["key"] == "spring.datasource.password")
            self.assertEqual(secret["value"], "<redacted>")
            self.assertTrue(secret["redacted"])

            warnings = summary["flyway"][0]["warnings"]
            warning_codes = {warning["code"] for warning in warnings}
            self.assertIn("drop_column", warning_codes)
            self.assertIn("create_index_non_concurrent", warning_codes)

    def test_review_json_contains_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_demo_project(root)

            result = generate_review(root, output="json")

            self.assertIsInstance(result, dict)
            categories = {finding["category"] for finding in result["findings"]}
            self.assertIn("security", categories)
            self.assertIn("database", categories)

    def test_mockmvc_generation_targets_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_demo_project(root)

            result = generate_mockmvc_tests(root, "PatientController")

            self.assertEqual(len(result["controllers"]), 1)
            skeleton = result["controllers"][0]["skeleton"]
            self.assertIn("@WebMvcTest(PatientController.class)", skeleton)
            self.assertIn('get("/api/patients")', skeleton)


def write_demo_project(root: Path) -> None:
    (root / "src/main/java/com/acme/patient").mkdir(parents=True)
    (root / "src/main/resources/db/migration").mkdir(parents=True)
    (root / "src/main/resources").mkdir(parents=True, exist_ok=True)

    (root / "pom.xml").write_text(
        """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId>
  <artifactId>patient-api</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )

    (root / "src/main/java/com/acme/patient/PatientController.java").write_text(
        """package com.acme.patient;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
class PatientController {
    @GetMapping("/patients")
    String list() {
        return "ok";
    }
}
""",
        encoding="utf-8",
    )

    (root / "src/main/java/com/acme/patient/PatientService.java").write_text(
        """package com.acme.patient;

import org.springframework.stereotype.Service;

@Service
class PatientService {}
""",
        encoding="utf-8",
    )

    (root / "src/main/resources/application.properties").write_text(
        "spring.datasource.url=jdbc:postgresql://localhost/patient\n"
        "spring.datasource.password=super-secret\n",
        encoding="utf-8",
    )

    (root / "src/main/resources/db/migration/V1__patient.sql").write_text(
        "CREATE INDEX idx_patient_name ON patient(name);\n"
        "ALTER TABLE patient DROP COLUMN old_code;\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
