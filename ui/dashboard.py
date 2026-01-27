#!/usr/bin/env python3
"""
nBogne Dashboard - UI for managing health data transmission.

Environment Variables:
    OPENMRS_URL     - OpenMRS FHIR endpoint (default: http://localhost:8080/openmrs/ws/fhir2/R4)
    ADAPTER_URL     - nBogne Adapter endpoint (default: http://localhost:8081)
    FACILITY_NAME   - Display name for this facility (default: Health Facility)

Run with:
    streamlit run ui/dashboard.py

    # Or with custom URLs:
    OPENMRS_URL=http://openmrs:8080/openmrs/ws/fhir2/R4 ADAPTER_URL=http://adapter:8081 streamlit run ui/dashboard.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import requests
import json
from datetime import datetime

# =============================================================================
# CONFIGURATION - Edit these or use environment variables
# =============================================================================
DEFAULT_OPENMRS_URL = os.environ.get("OPENMRS_URL", "http://localhost:8080/openmrs/ws/fhir2/R4")
DEFAULT_ADAPTER_URL = os.environ.get("ADAPTER_URL", "http://localhost:8081")
DEFAULT_FACILITY_NAME = os.environ.get("FACILITY_NAME", "Health Facility")

# Page config
st.set_page_config(
    page_title=f"nBogne - {DEFAULT_FACILITY_NAME}",
    page_icon="🏥",
    layout="wide"
)

# Session state defaults
if "openmrs_url" not in st.session_state:
    st.session_state.openmrs_url = DEFAULT_OPENMRS_URL
if "adapter_url" not in st.session_state:
    st.session_state.adapter_url = DEFAULT_ADAPTER_URL


def check_connection(url: str, timeout: int = 3) -> bool:
    """Check if a service is reachable."""
    try:
        requests.get(url, timeout=timeout)
        return True
    except:
        return False


def fetch_patient_from_openmrs(patient_id: str) -> dict | None:
    """Fetch patient data from OpenMRS FHIR endpoint."""
    url = f"{st.session_state.openmrs_url}/Patient/{patient_id}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        st.error(f"Failed to fetch patient: {e}")
        return None


def search_patients(query: str) -> list:
    """Search patients in OpenMRS."""
    url = f"{st.session_state.openmrs_url}/Patient?name={query}&_count=10"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            bundle = response.json()
            return bundle.get("entry", [])
        return []
    except:
        return []


def send_to_adapter(payload: dict, destination: str, priority: int = 0) -> dict | None:
    """Send FHIR bundle to nBogne adapter."""
    url = f"{st.session_state.adapter_url}/fhir"
    
    # Wrap in bundle if not already
    if payload.get("resourceType") != "Bundle":
        bundle = {
            "resourceType": "Bundle",
            "type": "message",
            "timestamp": datetime.utcnow().isoformat(),
            "entry": [{"resource": payload}]
        }
    else:
        bundle = payload
    
    headers = {
        "Content-Type": "application/json",
        "X-Destination": destination,
        "X-Priority": str(priority)
    }
    
    try:
        response = requests.post(url, json=bundle, headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        st.error(f"Failed to send: {e}")
        return None


def get_adapter_stats() -> dict | None:
    """Get queue statistics from adapter."""
    url = f"{st.session_state.adapter_url}/stats"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None


def get_adapter_health() -> dict | None:
    """Get health status from adapter."""
    url = f"{st.session_state.adapter_url}/health"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None


# =============================================================================
# UI Layout
# =============================================================================

st.title("🏥 nBogne Dashboard")
st.caption("Health data transmission over unreliable networks")

# Sidebar - Configuration
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.session_state.openmrs_url = st.text_input(
        "OpenMRS FHIR URL",
        value=st.session_state.openmrs_url
    )
    
    st.session_state.adapter_url = st.text_input(
        "nBogne Adapter URL", 
        value=st.session_state.adapter_url
    )
    
    st.divider()
    
    # Connection status
    st.subheader("Status")
    
    openmrs_ok = check_connection(st.session_state.openmrs_url.rsplit('/ws/', 1)[0])
    adapter_ok = check_connection(f"{st.session_state.adapter_url}/health")
    
    col1, col2 = st.columns(2)
    with col1:
        if openmrs_ok:
            st.success("OpenMRS ✓")
        else:
            st.error("OpenMRS ✗")
    
    with col2:
        if adapter_ok:
            st.success("Adapter ✓")
        else:
            st.error("Adapter ✗")


# Main content - Tabs
tab1, tab2, tab3 = st.tabs(["📤 Send Data", "📊 Queue Status", "📋 Manual Entry"])


# =============================================================================
# Tab 1: Send Data from OpenMRS
# =============================================================================
with tab1:
    st.header("Send Patient Data")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        search_query = st.text_input("Search patient (name or ID)")
        
        if search_query:
            if len(search_query) > 2:
                patients = search_patients(search_query)
                
                if patients:
                    st.write(f"Found {len(patients)} patient(s):")
                    
                    for entry in patients:
                        patient = entry.get("resource", {})
                        patient_id = patient.get("id", "Unknown")
                        names = patient.get("name", [{}])
                        name = names[0] if names else {}
                        display_name = f"{' '.join(name.get('given', []))} {name.get('family', '')}".strip()
                        gender = patient.get("gender", "unknown")
                        birth = patient.get("birthDate", "unknown")
                        
                        with st.expander(f"**{display_name or 'Unknown'}** ({patient_id})"):
                            st.write(f"**Gender:** {gender}")
                            st.write(f"**Birth Date:** {birth}")
                            st.json(patient)
                            
                            dest = st.selectbox(
                                "Destination",
                                ["CENTRAL", "FAC-001", "FAC-002", "REGIONAL"],
                                key=f"dest_{patient_id}"
                            )
                            
                            priority = st.slider(
                                "Priority",
                                0, 10, 0,
                                key=f"pri_{patient_id}"
                            )
                            
                            if st.button(f"Send {patient_id}", key=f"send_{patient_id}"):
                                with st.spinner("Sending..."):
                                    result = send_to_adapter(patient, dest, priority)
                                    if result and result.get("status") == "queued":
                                        st.success(f"Queued! Message ID: {result.get('message_id', '')[:8]}...")
                                    else:
                                        st.error("Failed to queue")
                else:
                    st.info("No patients found")
            else:
                st.caption("Type at least 3 characters to search")
    
    with col2:
        st.subheader("Quick Send")
        
        patient_id = st.text_input("Patient ID (direct)")
        destination = st.selectbox("Destination", ["CENTRAL", "FAC-001", "FAC-002", "REGIONAL"])
        priority = st.slider("Priority (0=normal, 10=urgent)", 0, 10, 0)
        
        if st.button("Fetch & Send", type="primary", disabled=not patient_id):
            with st.spinner("Fetching from OpenMRS..."):
                patient = fetch_patient_from_openmrs(patient_id)
                
                if patient:
                    st.json(patient)
                    
                    with st.spinner("Sending to adapter..."):
                        result = send_to_adapter(patient, destination, priority)
                        
                        if result and result.get("status") == "queued":
                            st.success(f"✓ Queued successfully!")
                            st.write(f"Message ID: `{result.get('message_id')}`")
                            st.write(f"Queue ID: `{result.get('queue_id')}`")
                        else:
                            st.error("Failed to send")
                else:
                    st.error(f"Patient {patient_id} not found")


# =============================================================================
# Tab 2: Queue Status
# =============================================================================
with tab2:
    st.header("Queue Status")
    
    if st.button("🔄 Refresh"):
        st.rerun()
    
    stats = get_adapter_stats()
    health = get_adapter_health()
    
    if stats:
        queue_stats = stats.get("queue", {})
        by_status = queue_stats.get("by_status", {})
        
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total", queue_stats.get("total", 0))
        
        with col2:
            pending = by_status.get("pending", 0) + by_status.get("sending", 0)
            st.metric("Pending", pending)
        
        with col3:
            st.metric("Sent", by_status.get("acked", 0))
        
        with col4:
            failed = by_status.get("failed", 0) + by_status.get("dead", 0)
            st.metric("Failed", failed)
        
        st.divider()
        
        # Status breakdown
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("By Status")
            if by_status:
                for status, count in by_status.items():
                    icon = {
                        "pending": "🟡",
                        "sending": "🔵",
                        "acked": "🟢",
                        "failed": "🔴",
                        "dead": "⚫"
                    }.get(status, "⚪")
                    st.write(f"{icon} **{status}**: {count}")
            else:
                st.info("Queue is empty")
        
        with col2:
            st.subheader("Health")
            if health:
                status = health.get("status", "unknown")
                if status == "healthy":
                    st.success(f"System Status: {status.upper()}")
                else:
                    st.error(f"System Status: {status.upper()}")
                
                issues = health.get("issues", [])
                if issues:
                    st.warning("Issues:")
                    for issue in issues:
                        st.write(f"- {issue}")
            else:
                st.warning("Could not fetch health status")
        
        # Receiver stats
        st.divider()
        st.subheader("Receiver Statistics")
        
        received = stats.get("received", {})
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Received", received.get("received", 0))
        with col2:
            st.metric("Queued", received.get("queued", 0))
        with col3:
            st.metric("Errors", received.get("errors", 0))
    
    else:
        st.warning("Could not connect to adapter. Is it running?")
        st.code(f"python -m scripts.run_adapter --config config/local.yaml")


# =============================================================================
# Tab 3: Manual Entry
# =============================================================================
with tab3:
    st.header("Manual FHIR Entry")
    st.caption("Send custom FHIR resources directly")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        default_bundle = """{
  "resourceType": "Bundle",
  "type": "message",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "example-patient",
        "name": [
          {
            "family": "Doe",
            "given": ["John"]
          }
        ],
        "gender": "male",
        "birthDate": "1990-01-15"
      }
    }
  ]
}"""
        
        fhir_json = st.text_area(
            "FHIR JSON",
            value=default_bundle,
            height=400
        )
    
    with col2:
        st.subheader("Settings")
        
        destination = st.selectbox(
            "Destination",
            ["CENTRAL", "FAC-001", "FAC-002", "REGIONAL"],
            key="manual_dest"
        )
        
        priority = st.slider(
            "Priority",
            0, 10, 0,
            key="manual_priority"
        )
        
        st.divider()
        
        if st.button("📤 Send", type="primary"):
            try:
                payload = json.loads(fhir_json)
                
                with st.spinner("Sending..."):
                    result = send_to_adapter(payload, destination, priority)
                    
                    if result and result.get("status") == "queued":
                        st.success("✓ Queued!")
                        st.json(result)
                    else:
                        st.error("Failed to queue")
                        if result:
                            st.json(result)
            
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")


# Footer
st.divider()
st.caption("nBogne — Health data transmission over unreliable networks")
