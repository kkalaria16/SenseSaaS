# Deployment Guide for SQL Agent Chat

## 1. Prerequisites

- **Docker Desktop** (or Docker Engine) installed on the host machine.
- **SQL Server** accessible from the host.
- **API Keys**: OpenAI API Key and a secure App API Key.

## 2. Configuration

Create a `.env` file in the root directory (same level as Dockerfile):

```env
OPENAI_API_KEY=your_openai_api_key
DB_SERVER=your_sql_server_address
DB_DATABASE=your_database_name
DB_UID=your_username
DB_PWD=your_password
APP_API_KEY=your_secure_app_key
```

## 3. Building the Docker Image

Run this command in the project root:

```powershell
docker build -t sql-agent-backend .
```

## 4. Running the Container

Run the container, exposing port 8000:

```powershell
docker run -d -p 8000:8000 --env-file .env --name sql-agent-container --restart always sql-agent-backend
```

---

## 5. IIS Deployment (Windows Server)

To expose this Docker container through IIS (e.g., to use standard ports 80/443 or manage via IIS), we use a **Reverse Proxy** setup.

### Step A: Install IIS Modules
You must install the following modules on your IIS server:
1.  **Application Request Routing (ARR) 3.0**
2.  **URL Rewrite 2.1**
    *   Download both from the Microsoft Web Platform Installer or official Microsoft downloads.

### Step B: Enable Proxy in ARR
1.  Open **IIS Manager**.
2.  Click on the **Server Node** (top level connection).
3.  Double-click **Application Request Routing Cache**.
4.  In the right "Actions" pane, click **Server Proxy Settings**.
5.  Check **Enable proxy**.
6.  Click **Apply**.

### Step C: Setup user interface site
1.  Create a folder for your site (e.g., `C:\inetpub\wwwroot\sql-agent`).
2.  Copy the `web.config` file from this project into that folder.
    *   *Note:* This `web.config` contains a URL Rewrite rule that forwards all traffic to `http://localhost:8000`.

### Step D: Create the Site
1.  In IIS Manager, right-click **Sites** > **Add Website**.
2.  **Site name:** `SQLAgentChat`
3.  **Physical path:** `C:\inetpub\wwwroot\sql-agent` (the folder where you put web.config).
4.  **Binding:** Configure your desired port (e.g., 80) and Host name.
5.  Click **OK**.

### Step E: Verify
1.  Ensure your Docker container is running (`docker ps`).
2.  Open a browser and navigate to `http://localhost/` (or your configured hostname).
3.  IIS will receive the request => Rewrite Rule => Proxies to Docker (port 8000) => Returns response.
