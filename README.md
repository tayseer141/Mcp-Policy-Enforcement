# 🛡️ MCP-Based Policy Enforcement for Secure Database Access

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)]() [![Docker](https://img.shields.io/badge/Docker-Supported-blue)]() [![MCP](https://img.shields.io/badge/Protocol-MCP-green)]() [![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-blue)]()

> Empowering Large Language Models (LLMs) to interact with enterprise databases through natural language, without compromising security, intent, or access controls.

## 📖 Overview

As Large Language Models (LLMs) become integrated into enterprise systems, they introduce a critical security gap: models are inherently unaware of organizational permissions and can trigger sensitive tools without authorization.

This project solves this by introducing a robust **MCP-Based Policy Enforcement System**. It acts as a secure, intelligent middleman between a user's natural language prompt and the database. By leveraging the Model Context Protocol (MCP), the LLM is granted access to system tools, but execution only occurs *after* a dedicated Policy Engine verifies the user's Role-Based Access Control (RBAC) permissions and validates their true intent.

## ✨ Key Features

* **🗣️ Natural Language Interface**: Users can execute complex database operations using plain text, requiring zero technical knowledge or SQL writing skills.
* **🔒 Strict RBAC Enforcement**: A dedicated Policy Engine intercepts every tool call to verify the user's role against organizational policies before execution.
* **🎯 Intent Alignment**: The system goes beyond technical permissions by verifying that the tool selected by the LLM accurately matches the user's original intent, preventing "hallucinated" or misinterpreted executions.
* **🛡️ Fail-Closed Security**: By default, any ambiguous request or missing permission results in an immediate block, returning a clear, user-friendly explanation rather than a generic error code.
* **💉 SQL Injection Prevention**: All database interactions are sanitized using abstractions and Parameterized Queries, completely preventing raw, LLM-generated SQL from hitting the database.

## 🏗️ Architecture

The system is built on a modular, Multi-Layer Architecture designed for clear separation of duties:

1.  **Interface Layer (LLM Handler)**: Manages communication with external LLMs (like OpenAI) to interpret user requests.
2.  **MCP Server**: Exposes available database tools and capabilities to the LLM using the Model Context Protocol.
3.  **Enforcement Layer (Policy Engine)**: The core security checkpoint that validates roles and permissions against the RBAC database.
4.  **Tools & Execution Layer**: Contains the business logic and standardized tools (e.g., `get_user_details`).
5.  **Data Layer (Database Adapter & DB)**: Manages secure PostgreSQL connections and holds both organizational data and RBAC tables.

## 🚀 Quickstart: Booting the Policy Engine

Ready to lock down your LLM database interactions? Getting the system up and running is designed to be frictionless, relying on lightweight containerization.

### 🛠️ Prerequisites

Before initiating the sequence, ensure your control station has the following installed:
* **Docker & Docker Compose**: The entire environment runs in isolated containers.
* **Python 3.10+**: Required if you plan to run the server locally outside of Docker to utilize the latest MCP libraries.
* **Git**: To pull the source code.

### 📦 Installation Sequence

**Step 1: Secure the Source Code**
Clone the repository to your local machine to begin.
```bash
git clone [https://github.com/tayseer141/Mcp-Policy-Enforcement.git](https://github.com/tayseer141/Mcp-Policy-Enforcement.git)
cd Mcp-Policy-Enforcement
```

**Step 2: Configure the Environment Variables**
The system needs to know how to connect to your database and LLM provider. Copy the example configuration file and add your secret keys.
```bash
cp .env.example .env
```
*(Open `.env` in your editor and configure your PostgreSQL credentials and LLM API keys).*

**Step 3: Ignite the Engine (Docker Build)**
Deploy the Multi-Layer Architecture. This single command spins up the MCP Server, the Policy Engine, and the testing database.
```bash
docker compose up --build -d
```
*Note: The `-d` flag runs the containers in detached mode. You can view the system logs anytime using `docker compose logs -f`.*

### 🧪 Running the Security Protocols (Tests)

Security is not left to chance. The system includes a robust suite of Unit and End-to-End (E2E) tests to ensure the RBAC engine correctly blocks unauthorized intent. 

To run the automated test scripts using `pytest` inside the testing container:
```bash
docker compose exec app pytest -v
```
Watch the console as the system successfully deflects simulated SQL injection attacks and unauthorized "Drop Table" requests! 

## 💻 Tech Stack

* **Core**: Python 3.10+ (utilizing AsyncIO for high-concurrency non-blocking operations).
* **Protocol**: Model Context Protocol (MCP).
* **Infrastructure**: Docker (containerized for cross-platform deployment on Linux, Windows, or Cloud).
* **Database**: PostgreSQL / SQLite.
