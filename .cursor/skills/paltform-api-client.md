
---
name: Platform API client methods
description: Write or improve client methods that talk to platform API
---

# Write or improve client methods that talk to platform API

## When to use

When asked to create new methods or modify functionality in `src/platform/*.py` 


## Background information

- We use a client in `src/platform/client.py` which wraps a `httpx.Client`. 
- Methods are namespaced into separate modules/classes (e.g., `src/platform/files.py`)
- All methods are sync for now. 
- Methods simply make requests to the platform API and return JSON. No validation is performed. No Pydantic models. This is deliberately lean. 
- Typically, each method in each class in `src/platform/*.py` wraps a single HTTP route. 
- You can write helper functions that make the client easier to use (e.g. convenience functions for filtering, searching, parallelization, etc.)

## How to create/modify a function 

### 1. Fetch the openAPI spec

First, download the openAPI spec using:

```bash
curl https://api.dev.deeporigin.io/docs.json > openapi.json
```

### 2. Identify route to work on

Read or parse the JSON file to identify the route to work. Identify payload and response schemas. 

### 3. Read the token

Platform API routes require a token. Obtain using:

```bash
cat ~/.deeporigin/api_tokens.json | jq -r '.dev'  
```

### 4. Use an example cURL example if provided


## Tips and tricks

- Make sure to use `deeporigin` as the orgKey