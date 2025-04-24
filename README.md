# Gemini Coder

## Description (Provide a brief description of your project)

This project provides a way to interact with the Gemini API to generate and modify code and documentation within a software project. It's designed to be used as a background server and provides an API and a Gradio-based user interface.

## Table of Contents

* [Requirements](#requirements)
* [Installation](#installation)
* [Usage](#usage)
    * [Starting the Server](#starting-the-server)
    * [Using the Gradio UI](#using-the-gradio-ui)
    * [Interacting with the API](#interacting-with-the-api)
        * [Setting the Project Root](#setting-the-project-root)
        * [Generating Content](#generating-content)
        * [Modifying Content](#modifying-content)
        * [Syncing Files](#syncing-files)
        * [Chatting with the LLM](#chatting-with-the-LLM)
* [Configuration](#configuration)
* [Contributing](#contributing)
* [License](#license)

## Requirements

* Python 3.9+
* pip
* A Google Cloud account and API key for the Gemini API.
* A configured editor (e.g., Vim, Emacs, VS Code).

## Installation

1.  Clone this repository:

    ```bash
    git clone https://github.com/anshulsawant/gemini-coder
    cd gemini-coder
    ```

2.  Create a virtual environment (recommended):

    ```bash
    python -m venv gc
    source gc/bin/activate  # gc\Scripts\activate  # On Windows
    ```

3.  Install the dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4.  Set the `GOOGLE_API_KEY` environment variable:

    ```bash
    export GOOGLE_API_KEY="YOUR_API_KEY"  # On Linux/macOS
    set GOOGLE_API_KEY=YOUR_API_KEY  # On Windows
    ```
    (Replace `YOUR_API_KEY` with your actual Gemini API key.)

## Usage

### Starting the Server

1.  Start the Flask server, providing the project root as a command-line argument:

    ```bash
    python -m server /path/to/your/project
    ```

    (Replace `/path/to/your/project` with the actual path to the project you want to work with. This should be the directory containing your source code, documentation, etc.)

    The server will start running at `http://0.0.0.0:5000`.

### Using the Gradio UI

Once the server is running, you can interact with the application using the Gradio web interface:

1.  Open your web browser and go to `http://localhost:5000`.
2.  The UI provides the following functionality:
    * **Chat Interface**: You can chat with the LLM by typing messages in the text box and clicking "Send". The conversation history will be displayed above the input box.
    * **File Explorer**: A list of project files is displayed on the right side.  Select a file from the dropdown to view its contents.
    * **Generate File**: Enter a desired filename and instructions in the provided text boxes, and click "Generate File".  The new file will be generated and opened in your configured editor.
    * **Modify File**: Select a file to modify from the dropdown, provide modification instructions, and click "Modify File". The diff will be opened in your configured editor.  After you save the changes in your editor, click "Apply Changes" in the Gradio UI to apply them to the original file.

### Interacting with the API

The application provides a REST API for interacting with the Gemini API. You can use tools like `curl`, Postman, or a web browser to send requests.

#### Setting the Project Root

The project root is typically set when starting the server from the command line.

#### Generating Content

To generate a new file, send a POST request to the `/generate` endpoint:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filename": "new_file.py",
    "instructions": "Create a function that adds two numbers."
}' \
[http://0.0.0.0:5000/generate](http://0.0.0.0:5000/generate)
```

* `filename`: The name of the file to create.
* `instructions`: Instructions for generating the file's content.

The server will generate the file and open it in your configured editor.

#### Modifying Content

To modify an existing file, send a POST request to the `/modify` endpoint:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filepath": "src/my_file.py",
    "instructions": "Add a comment at the beginning of the file saying \'This file is modified.\'"
}' \
[http://0.0.0.0:5000/modify](http://0.0.0.0:5000/modify)
```

* `filepath`: The path to the file to modify.
* `instructions`: Instructions for modifying the file's content.

The server will generate a diff of the changes and open it in your configured editor. After you save the changes in the editor, you need to send an apply changes request

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{
    "filepath": "src/my_file.py",
    "modified_content": "The modified content"
}' \
[http://0.0.0.0:5000/apply_changes](http://0.0.0.0:5000/apply_changes)
```

#### Syncing Files

To get a summary of the project, send a POST request to the `/sync` endpoint:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{}' [http://0.0.0.0:5000/sync](http://0.0.0.0:5000/sync)
```

The server will return a summary of the project based on the files in the project root.

#### Chatting with the LLM

To send a message to the LLM, send a POST request to the `/chat` endpoint:

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"message": "What is this project about?"}' [http://0.0.0.0:5000/chat](http://0.0.0.0:5000/chat)
```

* `message`: The message you want to send to the LLM.

### Configuration

The application's behavior can be configured using environment variables:

* `EDITOR`: The editor to use for opening files (e.g., `vim`, `emacs`, `code`). If not set, the application will try to use `$VISUAL` and defaults to `vim`.
* `GOOGLE_API_KEY`: Your Google Gemini API key. This is required for the application to function.

### [TODO] Context Caching

The Gemini API supports caching of responses to improve efficiency and reduce costs.  See the [Caching documentation](https://ai.google.dev/gemini-api/docs/caching?lang=python) for more information.  You may want to implement caching in your application.

