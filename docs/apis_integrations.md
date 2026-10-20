# APIs & External Integrations Setup Document

## 1. Integration Inventory

The Healthcare Agent Orchestration System integrates two major API service suites:
1. **ASI:One LLM API**: Provides LLM reasoning, multi-agent task planning, and tool hand-back management.
2. **Google Workspace APIs**: Enables external operations across Gmail, Google Calendar, Google Sheets, and Google Drive.

---

## 2. ASI:One LLM API Configuration

### Account & Key Setup:
1. Register an account at `asi1.ai`.
2. Navigate to the Developer Dashboard and generate an API key.
3. Set the base endpoint URL for chat completions.

### Key API Payload Parameters:
* **`planner_mode`** (`boolean`): Set to `true` to enable Fetch.ai agent discovery and task decomposition.
* **`x-session-id`** (`header string`): Unique UUIDv4 string generated per user session. Retains multi-turn plan state during Human-in-the-Loop (HITL) tool call pauses.
* **`agents`** (`array of strings`): Array of specialist agent addresses. Directs ASI:One to orchestrate these specific agents.
* **`tools`** (`array of objects`): Function definitions for risky actions (e.g., email outreach). Triggers a tool call pause (`finish_reason: "tool_calls"`) for user confirmation.

---

## 3. Google Workspace Service Account Setup

To enable automated email delivery, calendar scheduling, and Google Sheets sync without user pop-up prompts, use a Google Cloud Service Account.

### Step 1: Enable Cloud APIs
In the Google Cloud Console, enable the following APIs for your project:
- Gmail API
- Google Calendar API
- Google Drive API
- Google Sheets API

### Step 2: Service Account Key Creation
1. Go to IAM & Admin > Service Accounts.
2. Create a service account named `healthcare-workspace-agent`.
3. Generate a JSON key file and store it securely in your local environment.

### Step 3: Required OAuth 2.0 Scopes
Enable the following scopes in your service account initialization script:
- Gmail Send & Compose (`gmail.send`, `gmail.compose`)
- Calendar Events (`calendar.events`)
- Google Spreadsheets (`spreadsheets`)
- Google Drive Files (`drive.file`)

---

## 4. Environment Variables Configuration

In your `.env` file, configure the following keys:
- `ASI_ONE_API_KEY`: API key for ASI:One LLM Planner endpoint
- `GOOGLE_SERVICE_ACCOUNT_FILE`: Path to Google Service Account JSON file
- `AGENT1_ADDRESS` to `AGENT6_ADDRESS`: Cryptographic addresses for each specialist agent (`agent1q...`)

---

## 5. Integration Verification Checklist

1. **ASI:One Connectivity**: Verify API key authentication and ensure planner mode returns streamed task decomposition events.
2. **Google Workspace Connectivity**: Verify JSON key authorization, test spreadsheet reads/writes via `gspread`, and verify email sending permissions.
