#!/bin/bash
# =============================================================================
# nBogne Demo Runner
# =============================================================================
# Starts the adapter and dashboard for demo/testing.
#
# Usage:
#   ./scripts/run_demo.sh              # Start both adapter and UI
#   ./scripts/run_demo.sh adapter      # Start only adapter
#   ./scripts/run_demo.sh ui           # Start only UI
#   ./scripts/run_demo.sh mock         # Start mock mediator + adapter + UI
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

case "${1:-all}" in
    adapter)
        echo -e "${GREEN}Starting nBogne Adapter...${NC}"
        python -m scripts.run_adapter --config config/local.yaml
        ;;
    
    ui)
        echo -e "${BLUE}Starting nBogne Dashboard...${NC}"
        echo "Open http://localhost:8501 in your browser"
        streamlit run ui/dashboard.py
        ;;
    
    mock)
        echo -e "${GREEN}Starting Mock Mediator...${NC}"
        python -m scripts.mock_mediator --port 9000 &
        MOCK_PID=$!
        
        sleep 1
        
        echo -e "${GREEN}Starting nBogne Adapter...${NC}"
        python -m scripts.run_adapter --config config/local.yaml &
        ADAPTER_PID=$!
        
        sleep 2
        
        echo -e "${BLUE}Starting nBogne Dashboard...${NC}"
        streamlit run ui/dashboard.py &
        UI_PID=$!
        
        echo ""
        echo "=============================================="
        echo "  nBogne Demo Running"
        echo "=============================================="
        echo "  Dashboard:     http://localhost:8501"
        echo "  Adapter:       http://localhost:8081"
        echo "  Mock Mediator: http://localhost:9000"
        echo "=============================================="
        echo "  Press Ctrl+C to stop all services"
        echo ""
        
        trap "kill $MOCK_PID $ADAPTER_PID $UI_PID 2>/dev/null" EXIT
        wait
        ;;
    
    all|*)
        echo -e "${GREEN}Starting nBogne Adapter...${NC}"
        python -m scripts.run_adapter --config config/local.yaml &
        ADAPTER_PID=$!
        
        sleep 2
        
        echo -e "${BLUE}Starting nBogne Dashboard...${NC}"
        streamlit run ui/dashboard.py &
        UI_PID=$!
        
        echo ""
        echo "=============================================="
        echo "  nBogne Running"
        echo "=============================================="
        echo "  Dashboard: http://localhost:8501"
        echo "  Adapter:   http://localhost:8081"
        echo "=============================================="
        echo "  Press Ctrl+C to stop"
        echo ""
        
        trap "kill $ADAPTER_PID $UI_PID 2>/dev/null" EXIT
        wait
        ;;
esac
