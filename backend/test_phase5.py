import asyncio
import os
import sys

# Ensure sys.path considers backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app

print("Initializing test client...")
client = TestClient(app)
print("Test client initialized.")

def test_routes_exist():
    print("Testing /api/v1/repos ...")
    response = client.get("/api/v1/repos")
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")

    print("\nTesting /api/v1/graph/stats ...")
    response = client.get("/api/v1/graph/stats")
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")

def test_query():
    print("\nTesting direct RAG query ...")
    response = client.post("/api/v1/query", json={
        "query": "How does graph stats work?",
        "top_k": 3
    })
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Answer:\n{data.get('answer')}")
        print(f"Sources: {len(data.get('sources', []))}")
    else:
        print(f"Body: {response.text}")

def test_agent():
    print("\nTesting agent query ...")
    response = client.post("/api/v1/agent_query", json={
        "query": "Find the database connection logic",
        "top_k": 3
    })
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Answer:\n{data.get('answer')}")
    else:
        print(f"Body: {response.text}")

if __name__ == "__main__":
    print("Starting tests...")
    test_routes_exist()
    test_query()
    test_agent()
    print("Tests complete.")
