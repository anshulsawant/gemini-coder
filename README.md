# Gemini Coder

## Description

This project provides a way to interact with the Gemini API to generate and modify code and documentation within a software project. It runs as a background Flask server providing a REST API, and includes a Gradio-based web UI for interaction.

## Table of Contents

* [Requirements](#requirements)
* [Installation](#installation)
* [Usage](#usage)
    * [Starting the Server](#starting-the-server)
    * [Using the Gradio UI](#using-the-gradio-ui)
    * [Interacting with the API](#interacting-with-the-api)
        * [Setting the Project Root](#setting-the-project-root)
        * [Generating Content](#generating-content)
        * [Modifying Content (Multi-Step)](#modifying-content-multi-step)
        * [Syncing Files](#syncing-files)
        * [Chatting with the LLM](#chatting-with-the-llm)
        * [File Operations](#file-operations)
* [Configuration](#configuration)
* [Contributing](#contributing)
* [License](#license)

## Requirements

* Python 3.9+
* pip
* A Google Cloud account and API key for the Gemini API.
* A configured command-line editor (e.g., Vim, Emacs, Nano, VS Code `code` command).

## Installation

1.  Clone this repository:

    ```bash
    git clone [https://github.com/anshulsawant/gemini-coder](https://github.com/anshulsawant/gemini-coder) # Replace with your repo URL
    cd gemini-coder
    ```
2.  Create a virtual environment (recommended):

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Linux/macOS
    # venv\Scripts\activate   # On Windows
    ```
3.  Install the dependencies:

    ```bash
    pip install -r requirements.txt
    ```
4.  Set the `GOOGLE_API_KEY` environment variable:

    ```bash
    export GOOGLE_API_KEY="YOUR_API_KEY"  # On Linux/macOS
    # set GOOGLE_API_KEY=YOUR_API_KEY     # On Windows (Command Prompt)
    # $env:GOOGLE_API_KEY="YOUR_API_KEY"  # On Windows (PowerShell)
    ```

    (Replace `YOUR_API_KEY` with your actual Gemini API key.)
5.  (Optional) Set the `EDITOR` environment variable if your preferred editor isn't found automatically (defaults: `$VISUAL`, then `emacs`):

    ```bash
    export EDITOR="code --wait" # Example for VS Code (use --wait flag)
    ```

## Usage

### Starting the Server

1.  Start the Flask server:

    ```bash
    python server.py
    ```

    The server will start running at `http://0.0.0.0:5000`. Note that the project root is **not** set via the command line anymore; it must be set via the UI or API.

### Using the Gradio UI

Once the server is running, interact with the application via the Gradio web interface:

1.  Open your web browser and go to `http://localhost:5000`.
2.  **Set Project Root:** Enter the absolute path to your project directory in the "Project Root Directory" field and click "Set Project Root & Load Files". This is required before other actions work.
3.  The UI provides:

    * **Chat Interface**: Chat with the LLM. History is maintained per project root.
    * **File Explorer**: Select files from the dropdown (refreshed after setting root) to view their content. Use "Refresh File List" if needed.
    * **Generate File**: Enter a filename (relative to project root) and instructions, then click "Generate File". The server will generate the file, save it, and attempt to open it in your configured editor.
    * **Modify File**:
        1.  Select a file to modify from the dropdown.
        2.  Provide modification instructions.
        3.  Click "Request Modification (Show Diff)".
        4.  The server generates the changes, creates a diff, and attempts to open the diff file in your editor.
        5.  **Review the diff in your editor.**
        6.  Back in the Gradio UI, click "✅ Confirm & Apply Changes" to save the modifications to the original file, or "❌ Cancel Changes" to discard them.

### Interacting with the API

The application provides a REST API. Use tools like `curl` or Postman. **Remember to set the project root first via `/set_project_root` for subsequent requests in your session.**

#### Setting the Project Root

**Required before most other API calls.** Send a POST request to `/set_project_root`:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "project_root": "/path/to/your/project"
}' \
http://localhost:5000/set_project_root
```project_root`: The absolute path to the project directory.

#### Generating Content

To generate a new file, send a POST request to `/generate`:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filename": "new_feature/logic.py",
    "instructions": "Create a Python class named Calculator with add and subtract methods."
}' \
http://localhost:5000/generate
```filename`: The relative path (from project root) of the file to create.  
`instructions`: Instructions for generating the file's content.  
(Optional) `"relevant_files": ["path/to/context.py"]`: List of relative paths for context (currently basic implementation).

The server generates the file, saves it, and tries to open it in the editor configured via `$EDITOR`.

#### Modifying Content (Multi-Step)

Modifying is a two-step process via the API:

**Step 1: Request Modification & Diff**

Send a POST request to `/modify`:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filepath": "src/my_file.py",
    "instructions": "Add a docstring to the main function."
}' \
http://localhost:5000/modify
```filepath`: The relative path to the file to modify.  
`instructions`: Instructions for modifying the file.

The server generates the modified content temporarily, creates a diff file, and attempts to open the diff in your editor. The response indicates success and includes the filepath.

**Step 2: Confirm or Cancel**

To apply the changes shown in the diff, send a POST request to `/confirm_modify`:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filepath": "src/my_file.py"
}' \
http://localhost:5000/confirm_modify

This writes the temporarily stored modified content to the actual file.

To discard the changes, send a POST request to /cancel_modify:

curl -X POST -H "Content-Type: application/json" \
-d '{
    "filepath": "src/my_file.py"
}' \
http://localhost:5000/cancel_modify

This removes the temporarily stored modification.

Syncing Files
To get an LLM-generated summary of the project, send a POST request to /sync:

curl -X POST http://localhost:5000/sync

(No request body needed currently).

The server reads relevant project files (up to limits), sends them to the LLM, and returns a summary.

Chatting with the LLM
To send a message and get a response, maintaining conversation history for the current project root, send a POST request to /chat:

curl -X POST -H "Content-Type: application/json" \
-d '{"message": "Explain the purpose of the main function in src/my_file.py"}' \
http://localhost:5000/chat
```message`: The message you want to send.

#### File Operations

**Get File List:**

```bash
curl http://localhost:5000/get_files

Returns a JSON list of relative file paths within the project root.

Get File Content:

curl http://localhost:5000/get_file_content?filepath=src/my_file.py

Returns JSON containing the content of the specified relative file path.

Upload File: (Example using curl)

curl -X POST -F "file=@/path/to/local/file_to_upload.txt" http://localhost:5000/upload_file

Uploads a file to the uploaded_files directory within the project root.

Configuration
GOOGLE_API_KEY (Required): Your Google Gemini API key (environment variable).

EDITOR / VISUAL (Optional): Command to launch your preferred text editor (environment variable). Ensure it works from your terminal. For GUI editors like VS Code or Sublime, you might need a specific command-line flag (e.g., code --wait, subl -w) to make the server wait until you close the file/diff.

GEMINI_CODER_SERVER_URL (Optional): URL for the backend server if the Gradio UI needs to connect to a different address (defaults to http://localhost:5000).

[TODO] Context Caching
The Gemini API supports caching. Implementing client-side caching in server.py could improve performance and reduce costs for repeated requests. See the Gemini Caching documentation.

Contributing
Contributions are welcome! Please open an issue or submit a pull request.

License
(Choose and add a license, e.g., MIT, Apache 2.0
