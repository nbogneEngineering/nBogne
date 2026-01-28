"""
nBogne Dashboard - Flask Application

Environment Variables:
    OPENMRS_URL     - OpenMRS FHIR endpoint (default: http://localhost:8080/openmrs/ws/fhir2/R4)
    ADAPTER_URL     - nBogne Adapter endpoint (default: http://localhost:8081)
    FACILITY_NAME   - Display name for this facility (default: Health Facility)
    FLASK_SECRET    - Secret key for sessions (default: dev-secret-change-me)

Run with:
    python -m ui.app
    
    # Or with gunicorn:
    gunicorn -w 2 -b 0.0.0.0:8501 ui.app:app
"""

import os
import json
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for

# =============================================================================
# CONFIGURATION
# =============================================================================
OPENMRS_URL = os.environ.get("OPENMRS_URL", "http://localhost:8080/openmrs/ws/fhir2/R4")
ADAPTER_URL = os.environ.get("ADAPTER_URL", "http://localhost:8081")
FACILITY_NAME = os.environ.get("FACILITY_NAME", "Health Facility")
SECRET_KEY = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

# =============================================================================
# APP SETUP
# =============================================================================
app = Flask(__name__)
app.secret_key = SECRET_KEY

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def check_openmrs_connection():
    """Check if OpenMRS is reachable."""
    try:
        resp = requests.get(f"{OPENMRS_URL}/Patient", params={"_count": 1}, timeout=5)
        return resp.status_code == 200
    except:
        return False

def check_adapter_connection():
    """Check if adapter is reachable."""
    try:
        resp = requests.get(f"{ADAPTER_URL}/health", timeout=5)
        return resp.status_code == 200
    except:
        return False

def get_adapter_stats():
    """Get queue statistics from adapter."""
    try:
        resp = requests.get(f"{ADAPTER_URL}/stats", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def search_patients(query):
    """Search patients in OpenMRS."""
    try:
        params = {"name": query, "_count": 20} if query else {"_count": 20}
        resp = requests.get(f"{OPENMRS_URL}/Patient", params=params, timeout=10)
        if resp.status_code == 200:
            bundle = resp.json()
            patients = []
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                patient = {
                    "id": resource.get("id"),
                    "name": format_patient_name(resource),
                    "gender": resource.get("gender", "unknown"),
                    "birthDate": resource.get("birthDate", ""),
                }
                patients.append(patient)
            return patients
    except Exception as e:
        print(f"Error searching patients: {e}")
    return []

def format_patient_name(resource):
    """Extract formatted name from FHIR Patient resource."""
    names = resource.get("name", [])
    if names:
        name = names[0]
        given = " ".join(name.get("given", []))
        family = name.get("family", "")
        return f"{given} {family}".strip() or "Unknown"
    return "Unknown"

def get_patient_data(patient_id):
    """Get full patient data from OpenMRS."""
    try:
        resp = requests.get(f"{OPENMRS_URL}/Patient/{patient_id}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def send_to_adapter(fhir_data, destination, priority=5):
    """Send FHIR data to the adapter."""
    try:
        headers = {
            "Content-Type": "application/fhir+json",
            "X-Destination": destination,
            "X-Priority": str(priority),
        }
        resp = requests.post(
            f"{ADAPTER_URL}/fhir",
            json=fhir_data,
            headers=headers,
            timeout=30
        )
        return resp.status_code, resp.json() if resp.status_code in [200, 201, 202] else resp.text
    except Exception as e:
        return 500, str(e)

# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def index():
    """Dashboard home page."""
    openmrs_ok = check_openmrs_connection()
    adapter_ok = check_adapter_connection()
    stats = get_adapter_stats() if adapter_ok else None
    
    return render_template("index.html",
        facility_name=FACILITY_NAME,
        openmrs_url=OPENMRS_URL,
        adapter_url=ADAPTER_URL,
        openmrs_ok=openmrs_ok,
        adapter_ok=adapter_ok,
        stats=stats
    )

@app.route("/patients")
def patients():
    """Patient search page."""
    query = request.args.get("q", "")
    patients = search_patients(query) if check_openmrs_connection() else []
    
    return render_template("patients.html",
        facility_name=FACILITY_NAME,
        query=query,
        patients=patients,
        openmrs_ok=check_openmrs_connection()
    )

@app.route("/send/<patient_id>", methods=["GET", "POST"])
def send_patient(patient_id):
    """Send patient data to adapter."""
    patient = get_patient_data(patient_id)
    
    if not patient:
        flash("Patient not found", "error")
        return redirect(url_for("patients"))
    
    if request.method == "POST":
        destination = request.form.get("destination", "CENTRAL")
        priority = int(request.form.get("priority", 5))
        
        status_code, response = send_to_adapter(patient, destination, priority)
        
        if status_code in [200, 201, 202]:
            flash(f"Patient data queued successfully. Message ID: {response.get('message_id', 'N/A')}", "success")
            return redirect(url_for("patients"))
        else:
            flash(f"Failed to send: {response}", "error")
    
    return render_template("send.html",
        facility_name=FACILITY_NAME,
        patient=patient,
        patient_name=format_patient_name(patient)
    )

@app.route("/manual", methods=["GET", "POST"])
def manual():
    """Manual FHIR entry page."""
    if request.method == "POST":
        destination = request.form.get("destination", "CENTRAL")
        priority = int(request.form.get("priority", 5))
        fhir_json = request.form.get("fhir_data", "")
        
        try:
            fhir_data = json.loads(fhir_json)
            status_code, response = send_to_adapter(fhir_data, destination, priority)
            
            if status_code in [200, 201, 202]:
                flash(f"Data queued successfully. Message ID: {response.get('message_id', 'N/A')}", "success")
            else:
                flash(f"Failed to send: {response}", "error")
        except json.JSONDecodeError:
            flash("Invalid JSON", "error")
    
    return render_template("manual.html", facility_name=FACILITY_NAME)

@app.route("/queue")
def queue():
    """Queue status page."""
    stats = get_adapter_stats() if check_adapter_connection() else None
    return render_template("queue.html",
        facility_name=FACILITY_NAME,
        adapter_ok=check_adapter_connection(),
        stats=stats
    )

@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Settings page."""
    global OPENMRS_URL, ADAPTER_URL
    
    if request.method == "POST":
        OPENMRS_URL = request.form.get("openmrs_url", OPENMRS_URL)
        ADAPTER_URL = request.form.get("adapter_url", ADAPTER_URL)
        flash("Settings updated", "success")
        return redirect(url_for("settings"))
    
    return render_template("settings.html",
        facility_name=FACILITY_NAME,
        openmrs_url=OPENMRS_URL,
        adapter_url=ADAPTER_URL,
        openmrs_ok=check_openmrs_connection(),
        adapter_ok=check_adapter_connection()
    )

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route("/api/status")
def api_status():
    """API endpoint for connection status."""
    return jsonify({
        "openmrs": check_openmrs_connection(),
        "adapter": check_adapter_connection(),
        "stats": get_adapter_stats()
    })

@app.route("/api/patients")
def api_patients():
    """API endpoint for patient search."""
    query = request.args.get("q", "")
    return jsonify(search_patients(query))

@app.route("/api/send", methods=["POST"])
def api_send():
    """API endpoint to send FHIR data."""
    data = request.get_json()
    destination = data.get("destination", "CENTRAL")
    priority = data.get("priority", 5)
    fhir_data = data.get("fhir_data")
    
    if not fhir_data:
        return jsonify({"error": "No FHIR data provided"}), 400
    
    status_code, response = send_to_adapter(fhir_data, destination, priority)
    return jsonify(response) if isinstance(response, dict) else jsonify({"message": response}), status_code

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8501))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
