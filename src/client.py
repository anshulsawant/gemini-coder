import os
import subprocess
import tempfile
from flask import Flask, request, jsonify, session
import google.generativeai as genai
import sys
import traceback
import logging
from typing import Optional, Dict, Any, List
from flask_cors import CORS  # Import CORS
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration (These could be moved to a separate config file)
DEFAULT_EDITOR = "emacs"  # Fallback editor
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))  # Or set in environment
MODEL_NAME = "gemini-pro"  # Or "gemini-pro-vision" if you need vision
MAX_GENERATE_RETRIES = 3
FILE_UPLOAD_DIR = "uploaded_files"  # Directory to store uploaded files
SESSION_TIMEOUT = 30 * 60  # 30 minutes in seconds

# Global variable for project root -  Now stored in session
# project_root = None  # No longer needed as a global

# Session management (using a simple in-memory dictionary for now) - REMOVED
# sessions: Dict[str, Dict[str, Any]] = {}
app.secret_key = os.urandom(24)  #  Use os.urandom()

def get_editor() -> str:
    """
    Gets the configured editor from environment variables.
    Defaults to DEFAULT_EDITOR if none is set.
    """
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", DEFAULT_EDITOR))
    if not editor:
        logging.warning("No editor found in environment variables, using default.")
        return DEFAULT_EDITOR
    return editor

def read_file(filepath: str) -> str:
    """
    Reads the content of a file.

    Args:
        filepath (str): The path to the file.

    Returns:
        str: The content of the file, or an empty string on error.
    """
    try:
        with open(filepath, "r") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Error reading file {filepath}: {e}")
        return ""

def write_file(filepath: str, content: str) -> None:
    """
    Writes content to a file.

    Args:
        filepath (str): The path to the file.
        content (str): The content to write.
    """
    try:
        with open(filepath, "w") as f:
            f.write(content)
    except Exception as e:
        logging.error(f"Error writing to file {filepath}: {e}")
        raise

def generate_content(prompt: str, file_paths: Optional[List[str]] = None, model_name: str = MODEL_NAME) -> Optional[str]:
    """
    Generates content using the Gemini API, optionally with file input.

    Args:
        prompt (str): The prompt to send to the Gemini API.
        file_paths (Optional[List[str]]): A list of file paths to include as file input.
        model_name (str): The name of the Gemini model to use.

    Returns:
        Optional[str]: The generated content, or None on failure.
    """
    model = genai.GenerativeModel(model_name)
    parts = [prompt]

    if file_paths:
        for file_path in file_paths:
            try:
                with open(file_path, "rb") as f:
                    part = {"mime_type": "text/plain", "data": f.read()}  # Adjust mime_type as needed
                    parts.append(part)
            except Exception as e:
                logging.error(f"Error reading file {file_path}: {e}")
                return None

    retries = 0;
    while retries < MAX_GENERATE_RETRIES:
        try:
            response = model.generate_content(parts)
            if response.text:
                return response.text
            else:
                logging.warning(f"Empty response from Gemini API. Retry {retries+1}/{MAX_GENERATE_RETRIES}")
                retries += 1
        except Exception as e:
            logging.error(f"Error generating content: {e}. Retry {retries+1}/{MAX_GENERATE_RETRIES}")
            retries += 1

    logging.error(f"Failed to generate content after {MAX_GENERATE_RETRIES} retries.")
    return None

def open_in_editor(filepath: str) -> None:
    """
    Opens a file in the configured editor.

    Args:
        filepath (str): The path to the file.
    """
    editor = get_editor()
    try:
        subprocess.run([editor, filepath], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error opening {filepath} in {editor}: {e}")
        raise
    except FileNotFoundError:
        logging.error(f"Editor not found: {editor}")
        raise

def create_diff_file(original_content: str, modified_content: str) -> str:
    """
    Creates a diff file between the original and modified content.

    Args:
        original_content (str): The original content.
        modified_content (str): The modified content.

    Returns:
        str: The path to the diff file, or an empty string on error.
    """
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as original_file, \
             tempfile.NamedTemporaryFile(mode="w", delete=False) as modified_file, \
             tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False) as diff_file:

            original_file.write(original_content)
            modified_file.write(modified_content)

            subprocess.run(
                ["diff", "-u", original_file.name, modified_file.name, "-L", "Original", "-L", "Modified"],
                stdout=diff_file,
                check=True,
            )
        return diff_file.name
    except Exception as e:
        logging.error(f"Error creating diff file: {e}")
        return ""

def get_project_files(root_path: str) -> List[str]:
    """
    Gets all Python and Markdown files from the project root, returning a list of file paths.

    Args:
        root_path (str): The root path of the project.

    Returns:
        List[str]: A list of file paths.
    """
    project_files = []
    for root, _, files in os.walk(root_path):
        for file in files:
            if file.endswith(".py") or file.endswith(".md"):
                filepath = os.path.join(root, file)
                project_files.append(filepath)
    return project_files

def construct_prompt(instruction_file_content: str,  request_data: Dict[str, Any], relevant_files: Optional[List[str]] = None) -> str:
    """
    Constructs the prompt for the Gemini API based on the request and project context.

    Args:
        instruction_file_content (str): Content of the .llm_instructions file.
        request_data (Dict[str, Any]): The request data from the API endpoint.
        relevant_files (Optional[List[str]]): List of file paths to include.

    Returns:
        str: The constructed prompt.
    """
    prompt = f"Instructions from .llm_instructions:\n{instruction_file_content}\n\n"

    if relevant_files:
        prompt += "Relevant project files:\n"
        for file_path in relevant_files:
            filename = os.path.basename(file_path)
            prompt += f"\n--- {filename} ---\n"  # Include filename in prompt
            #  The actual file content is passed via the 'parts' argument in generate_content
    prompt += f"\nRequest: {request_data}\n\n"
    prompt += "Generate the requested content. Be concise and accurate. If generating code, ensure it is runnable and follows best practices."
    return prompt

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'py', 'md', 'txt'}

def load_session_data(project_root: str) -> Dict[str, Any]:
    """Loads session data from .llm_session file in the project root.

    Args:
        project_root: The project root directory.

    Returns:
        A dictionary containing the loaded session data, or an empty dictionary if the file doesn't exist or errors occur.
    """
    session_file_path = os.path.join(project_root, ".llm_session")
    try:
        if os.path.exists(session_file_path):
            with open(session_file_path, "r") as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logging.error(f"Error loading session data: {e}")
        return {}

def save_session_data(project_root: str, session_data: Dict[str, Any]) -> None:
    """Saves session data to .llm_session file in the project root.

    Args:
        project_root: The project root directory.
        session_data: A dictionary containing the session data to save.
    """
    session_file_path = os.path.join(project_root, ".llm_session")
    try:
        with open(session_file_path, "w") as f:
            json.dump(session_data, f, indent=4)  # Pretty printing for readability
    except Exception as e:
        logging.error(f"Error saving session data: {e}")



@app.before_request
def before_request():
    """
    This function is called before every request.
    """
    session.setdefault('session_id', os.urandom(16).hex())
    session['last_access'] = time.time()



@app.after_request
def after_request(response):
    """
    Saves session data after each request.
    """
    project_root = session.get('project_root')
    if project_root:
        session_data = {
            'conversation_history': session.get('conversation_history', []),
            'project_root': project_root
        }
        save_session_data(project_root, session_data)
    return response

@app.route('/upload_file', methods=['POST'])
def handle_upload_file():
    """Handles file uploads."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = os.path.join(FILE_UPLOAD_DIR, file.filename)
        # Ensure the upload directory exists
        os.makedirs(FILE_UPLOAD_DIR, exist_ok=True)
        file.save(filename)
        return jsonify({'filename': filename}), 200
    return jsonify({'error': 'File type not allowed'}), 400



@app.route("/generate", methods=["POST"])
def handle_generate():
    """
    Handles the /generate endpoint for generating new content.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request data"}), 400
        project_root = session.get('project_root')
        if not project_root:
            return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = read_file(instruction_file_path)

        #  Use file paths from the request data.
        file_paths = data.get("file_paths", []) # Get list of file paths
        #  Include instructions from the user.
        instructions = data.get("instructions", "")
        prompt = construct_prompt(instruction_file_content, data, file_paths)
        prompt += f"\nInstructions: {instructions}" # Append the user instructions
        generated_content = generate_content(prompt, file_paths)

        if not generated_content:
            return jsonify({"error": "Failed to generate content"}), 500

        filename = data.get("filename")
        if not filename:
            return jsonify({"error": "Filename is required"}), 400
        filepath = os.path.join(project_root, filename)
        write_file(filepath, generated_content)
        open_in_editor(filepath)
        return jsonify({"result": "Content generated and opened in editor", "filename": filename}), 200

    except Exception as e:
        error_message = f"Error in /generate: {e}"
        logging.error(error_message)
        traceback.print_exc()  # Print detailed traceback
        return jsonify({"error": error_message}), 500


@app.route("/modify", methods=["POST"])
def handle_modify():
    """
    Handles the /modify endpoint for modifying existing content.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request data"}), 400
        project_root = session.get('project_root')
        if not project_root:
            return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = read_file(instruction_file_path)

        filepath = data.get("filepath")
        if not filepath:
            return jsonify({"error": "Filepath is required"}), 400

        original_content = read_file(os.path.join(project_root, filepath))

        # Use file paths.
        file_paths = [os.path.join(project_root, filepath)]  #  path of file to modify
        #  Include instructions from the user.
        instructions = data.get("instructions", "")
        prompt = construct_prompt(instruction_file_content, data, file_paths)
        prompt += f"\nInstructions: {instructions}" # Append the user instructions
        modified_content = generate_content(prompt, file_paths)

        if not modified_content:
            return jsonify({"error": "Failed to modify content"}), 500

        diff_file_path = create_diff_file(original_content, modified_content)
        if not diff_file_path:
            return jsonify({"error": "Failed to create diff"}), 500

        #  Return the diff and the modified content
        return jsonify({"result": "Diff created", "diff_file_path": diff_file_path, "modified_content": modified_content, "original_content": original_content, "filepath": filepath}), 200

    except Exception as e:
        error_message = f"Error in /modify: {e}"
        logging.error(error_message)
        traceback.print_exc()
        return jsonify({"error": error_message}), 500


@app.route("/sync", methods=["POST"])
def handle_sync():
    """
    Handles the /sync endpoint for syncing project files. This version uses file paths.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request data"}), 400
        project_root = session.get('project_root')
        if not project_root:
            return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = read_file(instruction_file_path)

        # Get all relevant file paths.
        project_files = get_project_files(project_root)
        file_paths = list(project_files)

        prompt = f"Instructions from .llm_instructions:\n{instruction_file_content}\n\n"
        prompt += "\nProvide a summary of the project, its purpose, and any potential issues or suggestions."

        summary = generate_content(prompt, file_paths)
        if not summary:
            return jsonify({"error": "Failed to get project summary"}), 500

        return jsonify({"result": "Project synced", "summary": summary}), 200

    except Exception as e:
        error_message = f"Error in /sync: {e}"
        logging.error(error_message)
        traceback.print_exc()
        return jsonify({"error": error_message}), 500

@app.route("/new", methods=["POST"])
def handle_new():
    """
    Handles the /new command to set the project root and start a new session.
    """
    data = request.get_json()
    if not data or "project_root" not in data:
        return jsonify({"error": "Missing project_root in request"}), 400
    project_root = data["project_root"]
    if not os.path.isdir(project_root):
        return jsonify({"error": f"Invalid project root: {project_root}"}), 400

    #  Initialize a new session.  We'll store the project root here.
    session['project_root'] = project_root
    session['conversation_history'] = []  #  start a new conversation history.

    # Save initial session data
    save_session_data(project_root, {'conversation_history': [] , 'project_root': project_root}) # save also project root

    logging.info(f"Project root set to: {project_root}")
    return jsonify({"result": "New session started", "project_root": project_root}), 200

@app.route("/restore", methods=["POST"])
def handle_restore():
    """
    Handles the /restore command to resume an existing session (load project root).
    """
    data = request.get_json()
    if not data or "project_root" not in data:
        return jsonify({"error": "Missing project_root in request"}), 400
    project_root = data["project_root"]
    if not os.path.isdir(project_root):
        return jsonify({"error": f"Invalid project root: {project_root}"}), 400

    # Load conversation history from file
    loaded_session_data = load_session_data(project_root)
    if not loaded_session_data:
        return jsonify({"error": f"No session data found at {project_root}/.llm_session"}), 404

    session['project_root'] = loaded_session_data.get('project_root')
    session['conversation_history'] = loaded_session_data.get('conversation_history', [])

    logging.info(f"Session restored with project root: {project_root}")
    return jsonify({"result": "Session restored", "project_root": project_root}), 200



@app.route("/get_files", methods=["GET"])
def handle_get_files():
    """
    Returns the list of files in the project.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

    try:
        files = get_project_files(project_root)
        return jsonify({"files": files}), 200
    except Exception as e:
        error_message = f"Error getting project files: {e}"
        logging.error(error_message)
        traceback.print_exc()
        return jsonify({"error": error_message}), 500

@app.route("/get_file_content", methods=["GET"])
def handle_get_file_content():
    """
    Returns the content of a specific file.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

    filepath = request.args.get("filepath")
    if not filepath:
        return jsonify({"error": "Filepath is required"}), 400
    full_filepath = os.path.join(project_root, filepath)
    try:
        content = read_file(full_filepath)
        return jsonify({"content": content}), 200
    except Exception as e:
        error_message = f"Error getting file content: {e}"
        logging.error(error_message)
        traceback.print_exc()
        return jsonify({"error": error_message}), 500

@app.route("/chat", methods=["POST"])
def handle_chat():
    """
    Handles chat requests, sending user input to Gemini and returning the response.
    """
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Missing message in request"}), 400

        #  Get the project root from the session.
        project_root = session.get('project_root')
        if not project_root:
            return jsonify({"error": "Project root not set. Use /new or /restore."}), 400

        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = read_file(instruction_file_path)

        #  Get conversation history from session
        conversation_history = session.get('conversation_history', [])

        message = data["message"]
        prompt = construct_prompt(instruction_file_content, {"message": message}, []) # files are handled in generate_content
        if conversation_history:
            prompt = "Context:" + "\n".join(conversation_history) + "\n" + prompt
        response_text = generate_content(prompt)

        if not response_text:
            return jsonify({"error": "Failed to get response from LLM"}), 500

        #  Update conversation history.
        conversation_history.append(f"User: {message}")
        conversation_history.append(f"LLM: {response_text}")
        session['conversation_history'] = conversation_history # save

        # Save conversation history to file - IMPORTANT
        save_session_data(project_root, {'conversation_history': conversation_history, 'project_root': project_root}) #save project root

        return jsonify({"response": response_text}), 200

    except Exception as e:
        error_message = f"Error in /chat: {e}"
        logging.error(error_message)
        traceback.print_exc()
        return jsonify({"error": error_message}), 500

def main(root_path: str):
    """
    Main function to start the Flask app.

    Args:
        root_path: The project root.
    """
    # global project_root # Removed global project_root
    # project_root = root_path  # Set the project root.  Now set with /new
    # if not os.path.isdir(root_path): #  Check in /new instead.
    #     logging.error(f"Invalid project root: {root_path}")
    #     sys.exit(1)

    # Check for the GOOGLE_API_KEY
    if not os.environ.get("GOOGLE_API_KEY"):
        logging.error(
            "GOOGLE_API_KEY environment variable not set.  The application cannot run without it."
        )
        sys.exit(1)

    # Create the file upload directory if it doesn't exist
    os.makedirs(FILE_UPLOAD_DIR, exist_ok=True)
    # logging.info(f"Starting app with project root: {root_path}") # Now logged in /new
    app.run(host="0.0.0.0", port=5000, debug=False)  # Change debug to False for production



if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python app.py <project_root>")
        sys.exit(1)
    project_root = sys.argv[1]  #  Still get initial project root from command line.
    main(project_root)
