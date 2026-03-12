"""
FHIR Template Registry

The key insight: ~85-90% of a FHIR JSON record is predictable structure.
Templates capture that structure. We transmit only the variable values.

How it works:
1. During setup, templates are pre-shared between facility and server
2. A template = a FHIR resource with placeholders for variable values
3. On send: match record to template, extract values, return compact binary
4. On receive: look up template, fill in values, reconstruct full FHIR JSON
"""
import json
import struct
from typing import Any, Optional
from pathlib import Path


# Built-in templates for common FHIR resource patterns
# template_id 1-20 reserved for standard encounters
# template_id 0 = no template (fallback to full compression)

BUILTIN_TEMPLATES = {
    1: {
        "name": "basic_encounter",
        "resourceType": "Bundle",
        "description": "Basic outpatient encounter with vitals and diagnosis",
        "fields": [
            {"path": "patient_ref", "type": "string", "max_len": 36},
            {"path": "encounter_date", "type": "date"},
            {"path": "encounter_type", "type": "code", "codebook": "encounter_type"},
            {"path": "practitioner_ref", "type": "string", "max_len": 36},
            {"path": "systolic_bp", "type": "uint16"},
            {"path": "diastolic_bp", "type": "uint16"},
            {"path": "heart_rate", "type": "uint16"},
            {"path": "temperature", "type": "float16"},  # degrees C * 10
            {"path": "spo2", "type": "uint8"},
            {"path": "weight_kg", "type": "float16"},  # kg * 10
            {"path": "height_cm", "type": "uint16"},
            {"path": "diagnosis_1", "type": "code", "codebook": "icd10"},
            {"path": "diagnosis_2", "type": "code", "codebook": "icd10"},
            {"path": "diagnosis_3", "type": "code", "codebook": "icd10"},
            {"path": "medication_1", "type": "code", "codebook": "medication"},
            {"path": "medication_2", "type": "code", "codebook": "medication"},
            {"path": "note", "type": "text", "max_len": 200},
        ]
    },
    2: {
        "name": "lab_result",
        "resourceType": "Bundle",
        "description": "Lab result observation",
        "fields": [
            {"path": "patient_ref", "type": "string", "max_len": 36},
            {"path": "observation_date", "type": "date"},
            {"path": "lab_code", "type": "code", "codebook": "loinc"},
            {"path": "value", "type": "float32"},
            {"path": "unit", "type": "code", "codebook": "ucum"},
            {"path": "reference_low", "type": "float32"},
            {"path": "reference_high", "type": "float32"},
            {"path": "interpretation", "type": "code", "codebook": "interpretation"},
            {"path": "performer_ref", "type": "string", "max_len": 36},
        ]
    },
    3: {
        "name": "referral",
        "resourceType": "Bundle",
        "description": "Patient referral between facilities",
        "fields": [
            {"path": "patient_ref", "type": "string", "max_len": 36},
            {"path": "referral_date", "type": "date"},
            {"path": "from_facility", "type": "code", "codebook": "facility"},
            {"path": "to_facility", "type": "code", "codebook": "facility"},
            {"path": "priority", "type": "uint8"},  # 1=routine, 2=urgent, 3=emergency
            {"path": "reason_code", "type": "code", "codebook": "icd10"},
            {"path": "diagnosis_summary", "type": "text", "max_len": 200},
            {"path": "systolic_bp", "type": "uint16"},
            {"path": "diastolic_bp", "type": "uint16"},
            {"path": "heart_rate", "type": "uint16"},
            {"path": "temperature", "type": "float16"},
            {"path": "current_meds", "type": "text", "max_len": 100},
        ]
    },
    4: {
        "name": "immunization",
        "resourceType": "Immunization",
        "description": "Immunization record",
        "fields": [
            {"path": "patient_ref", "type": "string", "max_len": 36},
            {"path": "date", "type": "date"},
            {"path": "vaccine_code", "type": "code", "codebook": "cvx"},
            {"path": "dose_number", "type": "uint8"},
            {"path": "site", "type": "code", "codebook": "body_site"},
            {"path": "lot_number", "type": "string", "max_len": 20},
            {"path": "performer_ref", "type": "string", "max_len": 36},
        ]
    },
}


class TemplateRegistry:
    """Manages FHIR resource templates for compression."""

    def __init__(self, templates_path: Optional[Path] = None):
        self.templates = dict(BUILTIN_TEMPLATES)
        if templates_path and templates_path.exists():
            with open(templates_path) as f:
                custom = json.load(f)
                for tid_str, tpl in custom.items():
                    self.templates[int(tid_str)] = tpl

    def get_template(self, template_id: int) -> Optional[dict]:
        return self.templates.get(template_id)

    def match_fhir(self, fhir_json: dict) -> Optional[int]:
        """Try to match a FHIR resource to a template. Returns template_id or None."""
        resource_type = fhir_json.get("resourceType", "")

        if resource_type == "Bundle":
            entries = fhir_json.get("entry", [])
            resource_types = set()
            for entry in entries:
                r = entry.get("resource", {})
                resource_types.add(r.get("resourceType", ""))

            if "Encounter" in resource_types and "Observation" in resource_types:
                if "ServiceRequest" in resource_types:
                    return 3  # referral
                return 1  # basic encounter with vitals

            if "DiagnosticReport" in resource_types or (
                "Observation" in resource_types and "Encounter" not in resource_types
            ):
                return 2  # lab result

        if resource_type == "Immunization":
            return 4

        return None  # No template match — use fallback compression

    def extract_values(self, fhir_json: dict, template_id: int) -> dict:
        """Extract variable values from a FHIR resource using a template."""
        template = self.templates[template_id]
        values = {}

        if template_id == 1:
            values = self._extract_encounter(fhir_json)
        elif template_id == 2:
            values = self._extract_lab(fhir_json)
        elif template_id == 3:
            values = self._extract_referral(fhir_json)
        elif template_id == 4:
            values = self._extract_immunization(fhir_json)

        return values

    def reconstruct_fhir(self, values: dict, template_id: int) -> dict:
        """Reconstruct a full FHIR JSON resource from template + values."""
        if template_id == 1:
            return self._reconstruct_encounter(values)
        elif template_id == 2:
            return self._reconstruct_lab(values)
        elif template_id == 3:
            return self._reconstruct_referral(values)
        elif template_id == 4:
            return self._reconstruct_immunization(values)
        raise ValueError(f"Unknown template: {template_id}")

    # --- Extractors ---

    def _extract_encounter(self, bundle: dict) -> dict:
        v = {}
        for entry in bundle.get("entry", []):
            r = entry.get("resource", {})
            rt = r.get("resourceType")

            if rt == "Patient":
                v["patient_ref"] = r.get("id", "")

            elif rt == "Encounter":
                period = r.get("period", {})
                v["encounter_date"] = period.get("start", "")[:10]
                enc_type = r.get("type", [{}])
                if enc_type:
                    codings = enc_type[0].get("coding", [{}])
                    v["encounter_type"] = codings[0].get("code", "") if codings else ""
                v["practitioner_ref"] = ""
                participants = r.get("participant", [])
                if participants:
                    ref = participants[0].get("individual", {}).get("reference", "")
                    v["practitioner_ref"] = ref

            elif rt == "Observation":
                code = r.get("code", {}).get("coding", [{}])[0].get("code", "")
                val = r.get("valueQuantity", {}).get("value", 0)
                if code == "8480-6":
                    v["systolic_bp"] = int(val)
                elif code == "8462-4":
                    v["diastolic_bp"] = int(val)
                elif code == "8867-4":
                    v["heart_rate"] = int(val)
                elif code == "8310-5":
                    v["temperature"] = float(val)
                elif code == "2708-6" or code == "59408-5":
                    v["spo2"] = int(val)
                elif code == "29463-7":
                    v["weight_kg"] = float(val)
                elif code == "8302-2":
                    v["height_cm"] = int(val)

            elif rt == "Condition":
                code = r.get("code", {}).get("coding", [{}])[0].get("code", "")
                for i in range(1, 4):
                    key = f"diagnosis_{i}"
                    if key not in v:
                        v[key] = code
                        break

            elif rt == "MedicationRequest":
                med = r.get("medicationCodeableConcept", {}).get("coding", [{}])
                code = med[0].get("code", "") if med else ""
                for i in range(1, 3):
                    key = f"medication_{i}"
                    if key not in v:
                        v[key] = code
                        break

        # Defaults for missing values
        defaults = {
            "patient_ref": "", "encounter_date": "", "encounter_type": "",
            "practitioner_ref": "", "systolic_bp": 0, "diastolic_bp": 0,
            "heart_rate": 0, "temperature": 0.0, "spo2": 0, "weight_kg": 0.0,
            "height_cm": 0, "diagnosis_1": "", "diagnosis_2": "", "diagnosis_3": "",
            "medication_1": "", "medication_2": "", "note": "",
        }
        for k, default in defaults.items():
            v.setdefault(k, default)

        return v

    def _extract_lab(self, bundle: dict) -> dict:
        v = {"patient_ref": "", "observation_date": "", "lab_code": "",
             "value": 0.0, "unit": "", "reference_low": 0.0, "reference_high": 0.0,
             "interpretation": "", "performer_ref": ""}

        for entry in bundle.get("entry", []):
            r = entry.get("resource", {})
            rt = r.get("resourceType")
            if rt == "Patient":
                v["patient_ref"] = r.get("id", "")
            elif rt == "Observation":
                v["observation_date"] = r.get("effectiveDateTime", "")[:10]
                v["lab_code"] = r.get("code", {}).get("coding", [{}])[0].get("code", "")
                vq = r.get("valueQuantity", {})
                v["value"] = float(vq.get("value", 0))
                v["unit"] = vq.get("unit", "")
                ref_range = r.get("referenceRange", [{}])
                if ref_range:
                    v["reference_low"] = float(ref_range[0].get("low", {}).get("value", 0))
                    v["reference_high"] = float(ref_range[0].get("high", {}).get("value", 0))
                interp = r.get("interpretation", [{}])
                if interp:
                    v["interpretation"] = interp[0].get("coding", [{}])[0].get("code", "")
                perf = r.get("performer", [{}])
                if perf:
                    v["performer_ref"] = perf[0].get("reference", "")
        return v

    def _extract_referral(self, bundle: dict) -> dict:
        v = {"patient_ref": "", "referral_date": "", "from_facility": "",
             "to_facility": "", "priority": 1, "reason_code": "",
             "diagnosis_summary": "", "systolic_bp": 0, "diastolic_bp": 0,
             "heart_rate": 0, "temperature": 0.0, "current_meds": ""}
        for entry in bundle.get("entry", []):
            r = entry.get("resource", {})
            rt = r.get("resourceType")
            if rt == "Patient":
                v["patient_ref"] = r.get("id", "")
            elif rt == "ServiceRequest":
                v["referral_date"] = r.get("authoredOn", "")[:10]
                v["priority"] = {"routine": 1, "urgent": 2, "stat": 3}.get(r.get("priority", "routine"), 1)
                v["reason_code"] = r.get("reasonCode", [{}])[0].get("coding", [{}])[0].get("code", "") if r.get("reasonCode") else ""
            elif rt == "Observation":
                code = r.get("code", {}).get("coding", [{}])[0].get("code", "")
                val = r.get("valueQuantity", {}).get("value", 0)
                if code == "8480-6": v["systolic_bp"] = int(val)
                elif code == "8462-4": v["diastolic_bp"] = int(val)
                elif code == "8867-4": v["heart_rate"] = int(val)
                elif code == "8310-5": v["temperature"] = float(val)
        return v

    def _extract_immunization(self, resource: dict) -> dict:
        r = resource if resource.get("resourceType") == "Immunization" else {}
        return {
            "patient_ref": r.get("patient", {}).get("reference", ""),
            "date": r.get("occurrenceDateTime", "")[:10],
            "vaccine_code": r.get("vaccineCode", {}).get("coding", [{}])[0].get("code", ""),
            "dose_number": r.get("protocolApplied", [{}])[0].get("doseNumberPositiveInt", 1) if r.get("protocolApplied") else 1,
            "site": r.get("site", {}).get("coding", [{}])[0].get("code", "") if r.get("site") else "",
            "lot_number": r.get("lotNumber", ""),
            "performer_ref": r.get("performer", [{}])[0].get("actor", {}).get("reference", "") if r.get("performer") else "",
        }

    # --- Reconstructors ---

    def _reconstruct_encounter(self, v: dict) -> dict:
        entries = []
        entries.append({"resource": {"resourceType": "Patient", "id": v["patient_ref"]}})
        enc = {
            "resourceType": "Encounter", "status": "finished",
            "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": v["encounter_type"]}]}],
            "period": {"start": v["encounter_date"]},
            "participant": [{"individual": {"reference": v["practitioner_ref"]}}] if v["practitioner_ref"] else [],
        }
        entries.append({"resource": enc})

        vital_map = [
            ("8480-6", "systolic_bp", "mmHg", "Systolic blood pressure"),
            ("8462-4", "diastolic_bp", "mmHg", "Diastolic blood pressure"),
            ("8867-4", "heart_rate", "/min", "Heart rate"),
            ("8310-5", "temperature", "Cel", "Body temperature"),
            ("59408-5", "spo2", "%", "Oxygen saturation"),
            ("29463-7", "weight_kg", "kg", "Body weight"),
            ("8302-2", "height_cm", "cm", "Body height"),
        ]
        for loinc, key, unit, display in vital_map:
            val = v.get(key, 0)
            if val:
                entries.append({"resource": {
                    "resourceType": "Observation", "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
                    "valueQuantity": {"value": val, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
                    "effectiveDateTime": v["encounter_date"],
                }})

        for i in range(1, 4):
            dx = v.get(f"diagnosis_{i}", "")
            if dx:
                entries.append({"resource": {
                    "resourceType": "Condition", "clinicalStatus": {"coding": [{"code": "active"}]},
                    "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": dx}]},
                }})

        for i in range(1, 3):
            med = v.get(f"medication_{i}", "")
            if med:
                entries.append({"resource": {
                    "resourceType": "MedicationRequest", "status": "active", "intent": "order",
                    "medicationCodeableConcept": {"coding": [{"code": med}]},
                }})

        return {"resourceType": "Bundle", "type": "transaction", "entry": entries}

    def _reconstruct_lab(self, v: dict) -> dict:
        obs = {
            "resourceType": "Observation", "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": v["lab_code"]}]},
            "effectiveDateTime": v["observation_date"],
            "valueQuantity": {"value": v["value"], "unit": v["unit"]},
        }
        if v["reference_low"] or v["reference_high"]:
            obs["referenceRange"] = [{"low": {"value": v["reference_low"]}, "high": {"value": v["reference_high"]}}]
        if v["interpretation"]:
            obs["interpretation"] = [{"coding": [{"code": v["interpretation"]}]}]
        return {
            "resourceType": "Bundle", "type": "transaction",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": v["patient_ref"]}},
                {"resource": obs},
            ]
        }

    def _reconstruct_immunization(self, v: dict) -> dict:
        return {
            "resourceType": "Immunization", "status": "completed",
            "patient": {"reference": v["patient_ref"]},
            "occurrenceDateTime": v["date"],
            "vaccineCode": {"coding": [{"code": v["vaccine_code"]}]},
            "protocolApplied": [{"doseNumberPositiveInt": v["dose_number"]}],
            "site": {"coding": [{"code": v["site"]}]} if v["site"] else {},
            "lotNumber": v["lot_number"],
            "performer": [{"actor": {"reference": v["performer_ref"]}}] if v["performer_ref"] else [],
        }

    def _reconstruct_referral(self, v: dict) -> dict:
        entries = [
            {"resource": {"resourceType": "Patient", "id": v["patient_ref"]}},
            {"resource": {
                "resourceType": "ServiceRequest", "status": "active", "intent": "order",
                "authoredOn": v["referral_date"],
                "priority": {1: "routine", 2: "urgent", 3: "stat"}.get(v["priority"], "routine"),
                "reasonCode": [{"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": v["reason_code"]}]}] if v["reason_code"] else [],
            }},
        ]
        return {"resourceType": "Bundle", "type": "transaction", "entry": entries}
