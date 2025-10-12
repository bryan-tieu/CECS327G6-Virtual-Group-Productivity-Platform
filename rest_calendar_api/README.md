# Remote Communication
### Component: Calendar API (FastAPI)
The component demonstrate remote communication using a RESTful API built with FastAPI.

It simulates a minimal Calendar system where distributed components or clients can communicate and exchange data over HTTP

Clients can use tools like `curl` or `Invoke-RestMethod` to interact with the API, showcasing peer-to-peer style communication via standard web protocol


# Personal Notes
- pip install fastapi uvicorn
- uvicorn rest_calendar_api.main:app --reload --port 8000

# Copy this to your browser
http://127.0.0.1:8000/docs

Test all the Calls