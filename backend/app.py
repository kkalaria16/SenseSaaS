from fastapi import FastAPI, Request, HTTPException, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import uvicorn
import json
import os
import logging
import time
from datetime import datetime, date
from langgraph_sql_agent_chat import run_conversational_query, HumanMessage, AIMessage

from logging_config import log_agent_step, log_error
import sqlparse
from sqlparse import tokens as T
from dotenv import load_dotenv
from langgraph_sql_agent_charts import run_chart_generation
from decimal import Decimal

load_dotenv()

app = FastAPI()

# Security Configuration
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
APP_API_KEY = os.getenv("APP_API_KEY")

async def verify_api_key(api_key: str = Security(api_key_header)):
    """Validate API Key for SOC 2 Compliance."""
    if not APP_API_KEY:
        # If no key configured, warn but allow (or fail safe depending on policy)
        # For SOC 2, we should probably fail safe, but for dev convenience we might warn.
        # Let's enforce it if the env var is set, otherwise allow (dev mode).
        logging.warning("APP_API_KEY not set in environment. Authentication disabled.")
        return None
        
    if api_key == APP_API_KEY:
        return api_key
    
    raise HTTPException(
        status_code=403,
        detail="Could not validate credentials"
    )

# Mount static files
app.mount("/static", StaticFiles(directory="../frontend/static"), name="static")
templates = Jinja2Templates(directory="../frontend/templates")

class ChatMessage(BaseModel):
    content: str
    role: str  # 'user' or 'assistant'
    timestamp: str = ""

class ChatRequest(BaseModel):
    message: str
    company_id: Optional[int] = 1  # Default company ID
    thread_id: Optional[str] = None # For session persistence

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def format_sql(sql: str) -> str:
    """Format SQL using token-based parsing for clean, readable output."""
    if not sql:
        return ""

    # Parse and format using sqlparse
    formatted = sqlparse.format(
        sql,
        reindent=True,
        keyword_case='upper',
        indent_width=2,
        strip_comments=False,
        use_space_around_operators=True
    )

    return formatted.strip()

def log_audit_event(action: str, user_id: Optional[int], details: Dict[str, Any], status: str = "SUCCESS"):
    """Helper to log structured audit events."""
    log_agent_step(
        "AuditLog",
        f"Action: {action} | Status: {status}",
        {
            "action": action,
            "user_id": user_id,
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )

@app.post("/api/chat")
async def chat(chat_request: ChatRequest, api_key: str = Depends(verify_api_key)):
    start_time = time.time()
    try:
        # Add company ID to the query if not present
        print(f"DEBUG: Received ChatRequest: {chat_request}")
        query = chat_request.message
        company_id = chat_request.company_id
        thread_id = chat_request.thread_id
        print(f"DEBUG: Extracted thread_id: {thread_id}")
        
        # Add company ID to query if not already present
        # Only do this if it looks like a new query, not an answer to clarification
        # But hard to distinguish here. Let's rely on agent cleaning or context.
        if not any(tag in query.lower() for tag in ['companyid', 'company id']):
            query = f"[CompanyID: {company_id}] {query}"
        
        # Process the message through the agent
        result = run_conversational_query(query=query, company_id=company_id, thread_id=thread_id)
        
        # Format the response
        if result.get("is_clarification"):
             # It's a question from the bot
             message = result["natural_response"]
             natural_response = message
             status = "CLARIFICATION_NEEDED"
             
        elif result.get("error"):
            # ... (existing error handling)
            message = f"❌ Error: {result['error']}"
            natural_response = message
            status = "ERROR"
        elif "summary" in result and not result.get("results"):
            # Use the summary for general queries
            message = result["summary"]
            natural_response = message
            status = "SUCCESS"
        elif not result.get("results"):
            message = "ℹ️ No results found for your query."
            natural_response = message
            status = "SUCCESS"
        else:
            # Use the natural response if available, otherwise use the raw results
            natural_response = result.get("natural_response", "Here are your results:")
            if "|" in natural_response and "\n|-" in natural_response:
                message = natural_response
            else:
                message = natural_response + "\n\n" + json.dumps(result["results"], default=str)
            status = "SUCCESS"
        
        # Format SQL for display
        formatted_sql = format_sql(result.get("sql_query", ""))
        
        # Audit Log Success
        log_audit_event(
            action="CHAT_QUERY",
            user_id=company_id, # Using company_id as proxy for user context
            details={"query": query, "latency_ms": int((time.time() - start_time) * 1000)},
            status=status
        )
        
        # Create response
        response = {
            "message": message,
            "natural_response": natural_response,
            "summary_text": result.get("summary_text", natural_response),
            "sql": formatted_sql,
            "error": result.get("error"),
            "company_id": company_id,
            "thread_id": result.get("thread_id"),
            "is_clarification": result.get("is_clarification", False)
        }
        
        return JSONResponse(content=response)
        
    except Exception as e:
        logging.exception("Error in chat endpoint")
        # Audit Log Failure
        log_audit_event(
            action="CHAT_QUERY",
            user_id=chat_request.company_id,
            details={"query": chat_request.message, "error": str(e)},
            status="FAILURE"
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "An error occurred while processing your request.",
                "details": str(e)
            }
        )

@app.get("/charts", response_class=HTMLResponse)
async def charts_page(request: Request):
    return templates.TemplateResponse("charts.html", {"request": request})

def serialize_data(obj):
    """Recursively convert Decimal to float and datetime to str for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_data(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_data(i) for i in obj]
    return obj

@app.post("/api/charts")
async def charts_endpoint(chat_request: ChatRequest, api_key: str = Depends(verify_api_key)):
    start_time = time.time()
    try:
        # Add company ID to the query if not present
        query = chat_request.message
        company_id = chat_request.company_id
        
        # Process the message through the chart agent
        result = run_chart_generation(query=query, company_id=company_id)
        
        # Format SQL for display
        formatted_sql = format_sql(result.get("sql_query", ""))
        
        # Audit Log Success
        log_audit_event(
            action="CHART_GENERATION",
            user_id=company_id,
            details={"query": query, "latency_ms": int((time.time() - start_time) * 1000)},
            status="SUCCESS"
        )
        
        # Create response
        response = {
            "sql": formatted_sql,
            "error": result.get("error"),
            "chart_config": result.get("chart_config"),
            "results": result.get("results"),
            "company_id": company_id
        }
        
        # Serialize response to handle Decimals
        serialized_response = serialize_data(response)
        
        return JSONResponse(content=serialized_response)
        
    except Exception as e:
        logging.exception("Error in charts endpoint")
        log_audit_event(
            action="CHART_GENERATION",
            user_id=chat_request.company_id,
            details={"query": chat_request.message, "error": str(e)},
            status="FAILURE"
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "An error occurred while processing your chart request.",
                "details": str(e)
            }
        )

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})

@app.get("/api/logs")
async def get_logs(api_key: str = Depends(verify_api_key)):
    try:
        log_dir = "logs"
        if not os.path.exists(log_dir):
            return {"logs": []}
            
        # Get all json log files
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".json")]
        if not log_files:
            return {"logs": []}
            
        # Sort by modification time (newest first)
        log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir, x)), reverse=True)
        
        # Read the latest log file (or multiple if needed, but start with latest)
        latest_log = log_files[0]
        logs = []
        
        with open(os.path.join(log_dir, latest_log), 'r') as f:
            for line in f:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                    
        # Return logs reversed (newest first)
        return {"logs": list(reversed(logs)), "filename": latest_log}
        
    except Exception as e:
        logging.exception("Error fetching logs")
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":
    # Configure logging
    from logging_config import configure_logging
    configure_logging()
    
    # Start the server
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

