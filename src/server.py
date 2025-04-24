import time
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
import uuid # For temporary storage keys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration (These could be moved to a separate config file)
DEFAULT_EDITOR = "emacs"  # Fallback editor
# Ensure API key is set in the environment before running
if "GOOGLE_API_KEY" not in os.environ:
    logging.error("GOOGLE_API_KEY environment variable not set. Exiting.")
    sys.exit(1)
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
MODEL_NAME = "gemini-pro"  # Or "gemini-pro-vision" if you need vision
MAX_GENERATE_RETRIES = 3
FILE_UPLOAD_DIR = "uploaded_files"  # Directory to store uploaded files (relative to project root for now)
SESSION_TIMEOUT = 30 * 60  # 30 minutes in seconds (currently informational)

# Secret key for Flask session
app.secret_key = os.urandom(24)

# --- Helper Functions ---

def get_editor() -> str:
    """
    Gets the configured editor from environment variables.
    Defaults to DEFAULT_EDITOR if none is set.
    """
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", DEFAULT_EDITOR))
    if not editor:
        logging.warning("No editor found in environment variables, using default: %s", DEFAULT_EDITOR)
        return DEFAULT_EDITOR
    return editor

def _get_safe_path(project_root: str, relative_path: str) -> Optional[str]:
    """
    Validates and resolves a relative path within the project root.

    Args:
        project_root (str): The absolute path to the project root.
        relative_path (str): The relative path provided by the user/request.

    Returns:
        Optional[str]: The absolute, validated path, or None if invalid/unsafe.
    """
    if not project_root or not relative_path:
        logging.warning("Attempted path operation with missing project_root or relative_path.")
        return None

    # Normalize paths to prevent issues with '..' etc.
    abs_project_root = os.path.abspath(project_root)
    requested_path = os.path.abspath(os.path.join(abs_project_root, relative_path))

    # Security check: Ensure the resolved path is still within the project root
    if not requested_path.startswith(abs_project_root):
        logging.error("Path traversal attempt detected: %s resolves outside project root %s",
                      relative_path, abs_project_root)
        return None

    return requested_path


def read_file(filepath: str) -> str:
    """
    Reads the content of a file. Raises IOError on failure.

    Args:
        filepath (str): The absolute path to the file.

    Returns:
        str: The content of the file.

    Raises:
        IOError: If the file cannot be read.
    """
    try:
        with open(filepath, "r", encoding='utf-8') as f: # Specify encoding
            return f.read()
    except Exception as e:
        logging.error(f"Error reading file {filepath}: {e}")
        raise IOError(f"Could not read file: {filepath}") from e

def write_file(filepath: str, content: str) -> None:
    """
    Writes content to a file. Ensures directory exists. Raises IOError on failure.

    Args:
        filepath (str): The absolute path to the file.
        content (str): The content to write.

    Raises:
        IOError: If the file cannot be written.
    """
    try:
        # Ensure the directory exists before writing
        dir_path = os.path.dirname(filepath)
        if dir_path: # Check if dirname is not empty (e.g., for root files)
             os.makedirs(dir_path, exist_ok=True)
        with open(filepath, "w", encoding='utf-8') as f: # Specify encoding
            f.write(content)
        logging.info("Successfully wrote to file: %s", filepath)
    except Exception as e:
        logging.error(f"Error writing to file {filepath}: {e}")
        raise IOError(f"Could not write to file: {filepath}") from e

def generate_content(prompt: str, file_paths: Optional[List[str]] = None, model_name: str = MODEL_NAME) -> Optional[str]:
    """
    Generates content using the Gemini API, optionally with file input.

    Args:
        prompt (str): The prompt to send to the Gemini API.
        file_paths (Optional[List[str]]): A list of absolute file paths to include as file input.
        model_name (str): The name of the Gemini model to use.

    Returns:
        Optional[str]: The generated content, or None on failure after retries.
    """
    model = genai.GenerativeModel(model_name)
    parts = [prompt]
    uploaded_files = [] # Keep track of uploaded files for potential cleanup

    if file_paths:
        # Note: The Gemini API currently prefers using the File API for larger/multiple files.
        # This implementation sends content directly, which might have size limits.
        # Consider switching to `genai.upload_file` for more robust handling.
        for file_path in file_paths:
            try:
                # Read file content as bytes for potential non-text data, though API expects text here
                with open(file_path, "rb") as f:
                    # Determine a basic mime type (can be enhanced)
                    mime_type = "text/plain" # Default
                    if file_path.endswith(".py"):
                        mime_type = "text/x-python"
                    elif file_path.endswith(".md"):
                        mime_type = "text/markdown"
                    # Add file content directly to the parts list
                    parts.append(f"\n--- Start File: {os.path.basename(file_path)} ---\n")
                    parts.append(f.read().decode('utf-8', errors='ignore')) # Decode assuming text
                    parts.append(f"\n--- End File: {os.path.basename(file_path)} ---\n")

            except Exception as e:
                logging.error(f"Error preparing file {file_path} for Gemini: {e}")
                # Decide if you want to continue without the file or fail
                # return None # Fail if any file fails

    retries = 0
    while retries < MAX_GENERATE_RETRIES:
        try:
            logging.info("Sending request to Gemini API...")
            # Ensure all parts are strings before sending
            string_parts = [str(p) for p in parts]
            response = model.generate_content(string_parts)

            # Check for valid response text
            if response.text:
                 logging.info("Received response from Gemini API.")
                 # Basic cleanup: Remove markdown code block fences if present
                 cleaned_text = response.text.strip()
                 if cleaned_text.startswith("```") and cleaned_text.endswith("```"):
                     lines = cleaned_text.split('\n')
                     if len(lines) > 1:
                         # Remove first line (e.g., ```python) and last line (```)
                         cleaned_text = '\n'.join(lines[1:-1])
                     else:
                         # Handle case where it's just ```
                         cleaned_text = ""

                 return cleaned_text
            else:
                # Log safety feedback if available
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                     logging.warning(f"Gemini API request blocked. Reason: {response.prompt_feedback.block_reason}")
                     return f"Error: Content generation blocked by API safety filters (Reason: {response.prompt_feedback.block_reason}). Please revise your prompt or instructions."
                elif hasattr(response, 'candidates') and response.candidates and response.candidates[0].finish_reason != 'STOP':
                     logging.warning(f"Gemini API generation finished unexpectedly. Reason: {response.candidates[0].finish_reason}")
                     # Optionally return a specific error message based on finish_reason
                     return f"Error: Content generation stopped unexpectedly (Reason: {response.candidates[0].finish_reason})."
                else:
                     logging.warning(f"Empty response from Gemini API (no text and no clear block reason). Retry {retries+1}/{MAX_GENERATE_RETRIES}")
                     retries += 1


        except Exception as e:
            logging.error(f"Error generating content: {e}. Retry {retries+1}/{MAX_GENERATE_RETRIES}")
            retries += 1
            time.sleep(1) # Wait a bit before retrying

    logging.error(f"Failed to generate content after {MAX_GENERATE_RETRIES} retries.")
    return None # Return None after exhausting retries

def open_in_editor(filepath: str) -> None:
    """
    Opens a file in the configured editor. Raises RuntimeError on failure.

    Args:
        filepath (str): The absolute path to the file.

    Raises:
        RuntimeError: If the editor cannot be run or the file opened.
    """
    editor = get_editor()
    try:
        logging.info(f"Attempting to open {filepath} in editor: {editor}")
        # Use Popen for potentially non-blocking operation, though wait might be needed
        # depending on editor behavior. run(check=True) is simpler if blocking is okay.
        process = subprocess.Popen([editor, filepath])
        # Optional: Wait for the editor process to finish if needed
        # process.wait()
        logging.info(f"Successfully launched editor for {filepath}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Editor '{editor}' returned an error for {filepath}: {e}")
        raise RuntimeError(f"Editor '{editor}' failed for file: {filepath}") from e
    except FileNotFoundError:
        logging.error(f"Editor command not found: {editor}. Check $EDITOR or $VISUAL environment variables.")
        raise RuntimeError(f"Editor not found: {editor}") from e
    except Exception as e:
        logging.error(f"Unexpected error opening {filepath} in {editor}: {e}")
        raise RuntimeError(f"Failed to open file in editor: {filepath}") from e


def create_diff_file(original_content: str, modified_content: str, original_label: str = "Original", modified_label: str = "Modified") -> Optional[str]:
    """
    Creates a temporary diff file between the original and modified content.

    Args:
        original_content (str): The original content.
        modified_content (str): The modified content.
        original_label (str): Label for the original file in the diff header.
        modified_label (str): Label for the modified file in the diff header.

    Returns:
        Optional[str]: The absolute path to the temporary diff file, or None on error.
                         The caller is responsible for deleting this file.
    """
    diff_file_path = None
    original_file = None
    modified_file = None
    try:
        # Create temporary files to hold the content
        with tempfile.NamedTemporaryFile(mode="w", encoding='utf-8', delete=False) as original_file, \
             tempfile.NamedTemporaryFile(mode="w", encoding='utf-8', delete=False) as modified_file:

            original_file.write(original_content)
            modified_file.write(modified_content)
            original_file_path = original_file.name
            modified_file_path = modified_file.name

        # Create a separate temporary file for the diff output
        with tempfile.NamedTemporaryFile(mode="w", encoding='utf-8', suffix=".diff", delete=False) as diff_file:
            diff_file_path = diff_file.name

        # Run the diff command
        # Use labels that are more informative if possible (e.g., include original filename)
        cmd = ["diff", "-u", original_file_path, modified_file_path, "-L", original_label, "-L", modified_label]
        logging.info(f"Running diff command: {' '.join(cmd)}")
        process = subprocess.run(
            cmd,
            stdout=open(diff_file_path, 'w', encoding='utf-8'), # Redirect stdout to diff file
            stderr=subprocess.PIPE, # Capture stderr
            check=False, # Don't raise error on non-zero exit (diff returns 1 if files differ)
            text=True, # Work with text streams
            encoding='utf-8'
        )

        # diff returns 0 if files are identical, 1 if different, >1 if error
        if process.returncode > 1:
            logging.error(f"Error creating diff file: {process.stderr}")
            # Clean up the potentially created diff file if diff command failed
            if diff_file_path and os.path.exists(diff_file_path):
                os.remove(diff_file_path)
            return None
        elif process.returncode == 0:
             logging.info("Original and modified content are identical. No diff generated.")
             # Optionally, you might want to delete the empty diff file or handle this case specifically
        else:
             logging.info(f"Diff file created successfully: {diff_file_path}")

        return diff_file_path

    except Exception as e:
        logging.error(f"Unexpected error creating diff file: {e}")
        # Ensure cleanup if diff file was created before the exception
        if diff_file_path and os.path.exists(diff_file_path):
            try:
                os.remove(diff_file_path)
            except OSError as cleanup_error:
                logging.error(f"Error cleaning up diff file {diff_file_path}: {cleanup_error}")
        return None
    finally:
        # Clean up the temporary original and modified files
        if original_file_path and os.path.exists(original_file_path):
            try:
                os.remove(original_file_path)
            except OSError as cleanup_error:
                 logging.error(f"Error cleaning up temp file {original_file_path}: {cleanup_error}")
        if modified_file_path and os.path.exists(modified_file_path):
            try:
                os.remove(modified_file_path)
            except OSError as cleanup_error:
                 logging.error(f"Error cleaning up temp file {modified_file_path}: {cleanup_error}")


def get_project_files(root_path: str, extensions: List[str] = ['.py', '.md', '.txt', '.json', '.yaml', '.yml', '.html', '.css', '.js']) -> List[str]:
    """
    Gets all files with specified extensions from the project root, returning relative paths.
    Excludes common virtual environment and Git directories.

    Args:
        root_path (str): The absolute root path of the project.
        extensions (List[str]): List of file extensions to include (e.g., ['.py', '.md']).

    Returns:
        List[str]: A list of relative file paths from the project root.
    """
    project_files = []
    abs_root_path = os.path.abspath(root_path)
    # Common directories to exclude
    exclude_dirs = {'.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules', '.idea', '.vscode'}

    for root, dirs, files in os.walk(abs_root_path, topdown=True):
        # Modify dirs in-place to prevent walking into excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in files:
            # Check if the file has one of the desired extensions
            if any(file.lower().endswith(ext) for ext in extensions):
                abs_filepath = os.path.join(root, file)
                # Calculate relative path from the project root
                relative_filepath = os.path.relpath(abs_filepath, abs_root_path)
                project_files.append(relative_filepath)

    return sorted(project_files) # Sort for consistency


def construct_prompt(instruction_file_content: str, request_data: Dict[str, Any], relevant_files_content: Optional[Dict[str, str]] = None) -> str:
    """
    Constructs the prompt for the Gemini API based on the request and project context.

    Args:
        instruction_file_content (str): Content of the .llm_instructions file (or general instructions).
        request_data (Dict[str, Any]): The request data from the API endpoint (e.g., user instructions).
        relevant_files_content (Optional[Dict[str, str]]): Dictionary mapping relative file paths to their content.

    Returns:
        str: The constructed prompt.
    """
    prompt_lines = []

    # General instructions (if provided)
    if instruction_file_content:
        prompt_lines.append("--- General Instructions ---")
        prompt_lines.append(instruction_file_content)
        prompt_lines.append("--- End General Instructions ---\n")

    # Relevant file context (if provided)
    if relevant_files_content:
        prompt_lines.append("--- Relevant Project Files Context ---")
        for rel_path, content in relevant_files_content.items():
            prompt_lines.append(f"\n-- File: {rel_path} --\n")
            prompt_lines.append(content if content else "[File is empty]")
            prompt_lines.append(f"-- End File: {rel_path} --")
        prompt_lines.append("--- End Relevant Project Files Context ---\n")

    # Specific request instructions
    prompt_lines.append("--- Current Request ---")
    # Include user-provided instructions clearly
    if "instructions" in request_data and request_data["instructions"]:
        prompt_lines.append(f"User Instructions: {request_data['instructions']}")
    else:
        prompt_lines.append("User Instructions: [Not provided, infer from context or task]")

    # Add details specific to the task (e.g., filename for generation)
    if "filename" in request_data:
         prompt_lines.append(f"Target Filename (for generation): {request_data['filename']}")
    if "filepath" in request_data:
         prompt_lines.append(f"Target Filepath (for modification): {request_data['filepath']}")

    prompt_lines.append("--- End Current Request ---\n")

    # Final guidance for the LLM
    prompt_lines.append("--- Task Guidance ---")
    prompt_lines.append("Based on the general instructions, file context, and the current request:")
    if "filename" in request_data: # Generation task
         prompt_lines.append(f"Generate the complete content for the file '{request_data['filename']}'.")
    elif "filepath" in request_data: # Modification task
         prompt_lines.append(f"Generate the new, complete content for the file '{request_data['filepath']}' after applying the requested modifications.")
         prompt_lines.append("Ensure you provide the *entire* modified file content, not just the changed parts or a diff.")
    else: # General chat or sync task
         prompt_lines.append("Respond to the user's message or provide the requested summary.")

    prompt_lines.append("Be concise and accurate. If generating code, ensure it is runnable, follows best practices, and is well-commented unless otherwise specified.")
    prompt_lines.append("Output only the raw file content or response, without any extra explanations, introductions, or markdown formatting like ``` unless it's part of the actual file content.")
    prompt_lines.append("--- End Task Guidance ---")


    return "\n".join(prompt_lines)


def allowed_file(filename):
    """Checks if the file extension is allowed for upload (adjust as needed)."""
    # Define allowed extensions (consider security implications)
    ALLOWED_EXTENSIONS = {'txt', 'py', 'md', 'json', 'yaml', 'yml', 'html', 'css', 'js'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_session_data(project_root: str) -> Dict[str, Any]:
    """Loads session data from .llm_session file in the project root."""
    session_file_path = os.path.join(project_root, ".llm_session")
    try:
        if os.path.exists(session_file_path):
            with open(session_file_path, "r", encoding='utf-8') as f:
                data = json.load(f)
                # Basic validation
                if isinstance(data, dict):
                    # Ensure project_root matches if stored (optional safety check)
                    # if 'project_root' in data and os.path.abspath(data['project_root']) != os.path.abspath(project_root):
                    #     logging.warning("Session file project root mismatch. Ignoring stored root.")
                    #     data['project_root'] = project_root
                    return data
                else:
                    logging.warning("Invalid format in .llm_session file. Starting fresh.")
                    return {}
        else:
            return {} # No session file exists
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from session file {session_file_path}: {e}. Starting fresh.")
        return {}
    except Exception as e:
        logging.error(f"Error loading session data from {session_file_path}: {e}")
        return {}

def save_session_data(project_root: str, session_data: Dict[str, Any]) -> None:
    """Saves session data to .llm_session file in the project root."""
    session_file_path = os.path.join(project_root, ".llm_session")
    try:
        # Ensure project_root is stored correctly
        session_data['project_root'] = project_root
        with open(session_file_path, "w", encoding='utf-8') as f:
            json.dump(session_data, f, indent=4)  # Pretty printing
    except Exception as e:
        logging.error(f"Error saving session data to {session_file_path}: {e}")


# --- Flask Session Handling ---

@app.before_request
def before_request():
    """Initializes session variables if not present."""
    # Generate a unique ID for the session if it doesn't exist
    if 'session_id' not in session:
        session['session_id'] = uuid.uuid4().hex
        logging.info(f"New session started with ID: {session['session_id']}")

    # Track last access time (optional, for potential future cleanup)
    session['last_access'] = time.time()
    # Ensure 'pending_modifications' exists
    session.setdefault('pending_modifications', {})


@app.after_request
def after_request(response):
    """Saves session data after each request if project root is set."""
    project_root = session.get('project_root')
    if project_root and os.path.isdir(project_root): # Check if root is valid
        # Gather data to save (excluding potentially large/sensitive items if needed)
        session_data_to_save = {
            'conversation_history': session.get('conversation_history', []),
            'project_root': project_root,
            # Do NOT save pending_modifications here, it's too transient.
            # Only save things that need to persist across server restarts.
        }
        save_session_data(project_root, session_data_to_save)
    return response

# --- Flask Routes ---

@app.route('/set_project_root', methods=['POST'])
def handle_set_project_root():
    """
    Sets or changes the project root for the current session.
    Loads existing session data or initializes a new one.
    """
    data = request.get_json()
    if not data or "project_root" not in data:
        return jsonify({"error": "Missing 'project_root' in request"}), 400

    new_project_root = data["project_root"]
    abs_new_project_root = os.path.abspath(new_project_root)

    if not os.path.isdir(abs_new_project_root):
        return jsonify({"error": f"Invalid directory path: {new_project_root}"}), 400

    # Clear potentially stale pending modifications if root changes
    session.pop('pending_modifications', None)

    # Load session data for the new root
    loaded_data = load_session_data(abs_new_project_root)

    session['project_root'] = abs_new_project_root
    session['conversation_history'] = loaded_data.get('conversation_history', [])
    session['pending_modifications'] = {} # Reset pending modifications

    logging.info(f"Project root set to: {abs_new_project_root} for session {session.get('session_id')}")

    # Save immediately to confirm the new root association
    save_session_data(abs_new_project_root, {
        'conversation_history': session['conversation_history'],
        'project_root': abs_new_project_root
    })

    return jsonify({
        "result": "Project root set successfully",
        "project_root": abs_new_project_root,
        "message": f"Loaded session for {abs_new_project_root}." if loaded_data else f"Initialized new session for {abs_new_project_root}."
    }), 200


@app.route('/upload_file', methods=['POST'])
def handle_upload_file():
    """Handles file uploads to a specific directory within the project root."""
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        try:
            # Sanitize filename (optional but recommended)
            # filename = secure_filename(file.filename) # Requires Werkzeug
            filename = os.path.basename(file.filename) # Basic sanitization

            # Define upload path relative to project root
            upload_dir = os.path.join(project_root, FILE_UPLOAD_DIR)
            os.makedirs(upload_dir, exist_ok=True) # Ensure directory exists

            # Use _get_safe_path to ensure the final path is within the project root's upload dir
            safe_filepath = _get_safe_path(project_root, os.path.join(FILE_UPLOAD_DIR, filename))

            if not safe_filepath or not safe_filepath.startswith(os.path.abspath(upload_dir)):
                 # This check is slightly redundant due to _get_safe_path but adds clarity
                 logging.error(f"Upload path validation failed for {filename}")
                 return jsonify({'error': 'Invalid file path after sanitization'}), 400

            file.save(safe_filepath)
            relative_path = os.path.relpath(safe_filepath, project_root)
            logging.info(f"File '{filename}' uploaded successfully to '{safe_filepath}' (relative: {relative_path})")
            return jsonify({'message': 'File uploaded successfully', 'filepath': relative_path}), 200
        except Exception as e:
            logging.error(f"Error saving uploaded file {file.filename}: {e}")
            return jsonify({'error': 'Failed to save uploaded file'}), 500
    else:
        return jsonify({'error': 'File type not allowed'}), 400


@app.route("/generate", methods=["POST"])
def handle_generate():
    """
    Handles generating a new file based on instructions.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        data = request.get_json()
        if not data: return jsonify({"error": "Missing request data"}), 400
        if "filename" not in data or not data["filename"]: return jsonify({"error": "Missing 'filename'"}), 400
        if "instructions" not in data: return jsonify({"error": "Missing 'instructions'"}), 400

        relative_filename = data["filename"]
        instructions = data["instructions"]

        # Validate the target path
        target_filepath = _get_safe_path(project_root, relative_filename)
        if not target_filepath:
            return jsonify({"error": f"Invalid or unsafe filename: {relative_filename}"}), 400

        # --- Prepare context for LLM ---
        # Read general instructions if they exist
        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = ""
        try:
            if os.path.exists(instruction_file_path):
                 instruction_file_content = read_file(instruction_file_path)
        except IOError as e:
             logging.warning(f"Could not read .llm_instructions file: {e}")
             # Continue without general instructions

        # Include content of relevant files if provided in the request
        relevant_files_content = {}
        # TODO: Add logic here if the 'generate' request should include context from other files
        # file_paths_relative = data.get("relevant_files", [])
        # for rel_path in file_paths_relative:
        #     abs_path = _get_safe_path(project_root, rel_path)
        #     if abs_path and os.path.exists(abs_path):
        #         try:
        #             relevant_files_content[rel_path] = read_file(abs_path)
        #         except IOError as e:
        #             logging.warning(f"Could not read relevant file {rel_path}: {e}")


        # Construct the prompt
        prompt = construct_prompt(instruction_file_content, data, relevant_files_content)

        # --- Call LLM ---
        logging.info(f"Generating content for file: {relative_filename}")
        generated_content = generate_content(prompt) # Pass absolute paths if needed by generate_content

        if generated_content is None: # Check for None explicitly
            # generate_content logs the error, check if it returned a specific error message
            if isinstance(generated_content, str) and generated_content.startswith("Error:"):
                 return jsonify({"error": generated_content}), 500 # Return specific API error
            return jsonify({"error": "Failed to generate content from LLM after retries"}), 500


        # --- Write file and open editor ---
        try:
            write_file(target_filepath, generated_content)
            open_in_editor(target_filepath)
            return jsonify({
                "result": f"File '{relative_filename}' generated and opened in editor.",
                "filepath": relative_filename
             }), 200
        except (IOError, RuntimeError) as e: # Catch errors from write_file or open_in_editor
            logging.error(f"Error writing or opening generated file {relative_filename}: {e}")
            # Attempt to clean up partially created file if write failed mid-way (optional)
            if os.path.exists(target_filepath) and isinstance(e, IOError):
                 try: os.remove(target_filepath)
                 except OSError: pass
            return jsonify({"error": f"Failed to save or open generated file: {e}"}), 500

    except Exception as e:
        error_message = f"Unexpected error in /generate: {e}"
        logging.error(error_message, exc_info=True) # Log full traceback
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route("/modify", methods=["POST"])
def handle_modify():
    """
    Generates modified content for a file, stores it temporarily,
    creates a diff, and opens the diff in the editor.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        data = request.get_json()
        if not data: return jsonify({"error": "Missing request data"}), 400
        if "filepath" not in data or not data["filepath"]: return jsonify({"error": "Missing 'filepath'"}), 400
        if "instructions" not in data: return jsonify({"error": "Missing 'instructions'"}), 400

        relative_filepath = data["filepath"]
        instructions = data["instructions"]

        # Validate the target path
        target_filepath_abs = _get_safe_path(project_root, relative_filepath)
        if not target_filepath_abs or not os.path.isfile(target_filepath_abs):
            return jsonify({"error": f"Invalid or non-existent file: {relative_filepath}"}), 400

        # --- Read original content and prepare context ---
        try:
            original_content = read_file(target_filepath_abs)
        except IOError as e:
            return jsonify({"error": f"Could not read file to modify: {e}"}), 500

        # Read general instructions
        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = ""
        try:
            if os.path.exists(instruction_file_path):
                 instruction_file_content = read_file(instruction_file_path)
        except IOError as e:
             logging.warning(f"Could not read .llm_instructions file: {e}")

        # Context for modification is the file itself
        relevant_files_content = {relative_filepath: original_content}
        # TODO: Add logic if modification should consider other files

        # Construct the prompt
        prompt = construct_prompt(instruction_file_content, data, relevant_files_content)

        # --- Call LLM ---
        logging.info(f"Generating modified content for file: {relative_filepath}")
        modified_content = generate_content(prompt) # Pass absolute paths if needed

        if modified_content is None:
            if isinstance(modified_content, str) and modified_content.startswith("Error:"):
                 return jsonify({"error": modified_content}), 500
            return jsonify({"error": "Failed to generate modified content from LLM after retries"}), 500

        # --- Create Diff and Store Pending Change ---
        diff_file_path = None
        try:
            # Create user-friendly labels for the diff
            original_label = f"{relative_filepath} (Original)"
            modified_label = f"{relative_filepath} (Proposed Changes)"
            diff_file_path = create_diff_file(original_content, modified_content, original_label, modified_label)

            if not diff_file_path:
                # create_diff_file logs the error
                return jsonify({"error": "Failed to create diff file"}), 500

            # Store the proposed modification in the session, keyed by relative path
            # Use a simple dictionary for pending modifications in the session
            session['pending_modifications'][relative_filepath] = modified_content
            session.modified = True # Mark session as modified

            logging.info(f"Stored pending modification for: {relative_filepath}")

            # Open the diff file in the editor
            open_in_editor(diff_file_path)

            return jsonify({
                "result": "Diff created and opened in editor. Review the changes.",
                "filepath": relative_filepath, # Return filepath for confirmation step
                "diff_file_path": diff_file_path # Return for info, but client shouldn't rely on it persisting
            }), 200

        except (RuntimeError, IOError) as e: # Catch errors from open_in_editor or potentially create_diff
             logging.error(f"Error opening diff or storing modification for {relative_filepath}: {e}")
             # Clean up pending modification if storing failed after diff creation
             session['pending_modifications'].pop(relative_filepath, None)
             session.modified = True
             return jsonify({"error": f"Failed to open diff or prepare modification: {e}"}), 500
        finally:
             # Clean up the temporary diff file after the editor is launched (or if an error occurred)
             # Note: This might delete the file before the user finishes viewing it if the editor opens quickly.
             # A more robust solution might involve tracking the editor process or delaying cleanup.
             # For simplicity, we clean up here. The user has seen the diff launch.
             if diff_file_path and os.path.exists(diff_file_path):
                 try:
                     os.remove(diff_file_path)
                     logging.info(f"Cleaned up temporary diff file: {diff_file_path}")
                 except OSError as cleanup_error:
                     logging.error(f"Error cleaning up temporary diff file {diff_file_path}: {cleanup_error}")


    except Exception as e:
        error_message = f"Unexpected error in /modify: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500

@app.route("/confirm_modify", methods=["POST"])
def handle_confirm_modify():
    """
    Applies the pending modification stored in the session to the actual file.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        data = request.get_json()
        if not data or "filepath" not in data:
            return jsonify({"error": "Missing 'filepath' in request"}), 400

        relative_filepath = data["filepath"]

        # Retrieve the pending modification from session
        pending_modifications = session.get('pending_modifications', {})
        if relative_filepath not in pending_modifications:
            return jsonify({"error": f"No pending modification found for file: {relative_filepath}. Please run /modify first."}), 404 # Not Found

        modified_content = pending_modifications[relative_filepath]

        # Validate the target path again before writing
        target_filepath_abs = _get_safe_path(project_root, relative_filepath)
        if not target_filepath_abs or not os.path.isfile(target_filepath_abs):
             # File might have been deleted/moved since /modify was called
             # Clean up pending modification
             session['pending_modifications'].pop(relative_filepath, None)
             session.modified = True
             return jsonify({"error": f"File not found or invalid: {relative_filepath}"}), 404


        # Write the modified content to the file
        try:
            write_file(target_filepath_abs, modified_content)

            # Remove the pending modification from the session after successful write
            session['pending_modifications'].pop(relative_filepath, None)
            session.modified = True
            logging.info(f"Successfully applied modification to: {relative_filepath}")

            return jsonify({"result": f"Changes applied successfully to '{relative_filepath}'."}), 200

        except IOError as e:
            logging.error(f"Failed to write confirmed modification to {relative_filepath}: {e}")
            # Do NOT remove from session if write failed, user might want to retry
            return jsonify({"error": f"Failed to write changes to file: {e}"}), 500

    except Exception as e:
        error_message = f"Unexpected error in /confirm_modify: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500

@app.route("/cancel_modify", methods=["POST"])
def handle_cancel_modify():
    """
    Discards a pending modification stored in the session.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set."}), 400 # Allow cancelling even if root is technically gone

    try:
        data = request.get_json()
        if not data or "filepath" not in data:
            return jsonify({"error": "Missing 'filepath' in request"}), 400

        relative_filepath = data["filepath"]

        # Remove the pending modification from the session
        if 'pending_modifications' in session and relative_filepath in session['pending_modifications']:
            session['pending_modifications'].pop(relative_filepath, None)
            session.modified = True
            logging.info(f"Cancelled pending modification for: {relative_filepath}")
            return jsonify({"result": f"Pending changes for '{relative_filepath}' discarded."}), 200
        else:
            # No pending change was found, which is fine for cancellation
            logging.warning(f"Cancellation requested for {relative_filepath}, but no pending change found.")
            return jsonify({"result": f"No pending changes found for '{relative_filepath}' to cancel."}), 200

    except Exception as e:
        error_message = f"Unexpected error in /cancel_modify: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route("/sync", methods=["POST"])
def handle_sync():
    """
    Provides a summary of the project based on its files.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        # --- Prepare Context ---
        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = ""
        try:
            if os.path.exists(instruction_file_path):
                 instruction_file_content = read_file(instruction_file_path)
        except IOError as e:
             logging.warning(f"Could not read .llm_instructions file for sync: {e}")

        # Get project files (consider limiting for very large projects)
        project_files_relative = get_project_files(project_root)
        if not project_files_relative:
            return jsonify({"result": "Project synced. No relevant files found to summarize."}), 200

        # Read content of files for context (limit size/number if necessary)
        # This could be very large for big projects!
        MAX_SYNC_FILES = 50 # Limit number of files sent for summary
        MAX_FILE_SIZE_BYTES = 100 * 1024 # Limit size per file (100KB)

        relevant_files_content = {}
        files_processed_count = 0
        total_size = 0

        logging.info(f"Syncing project. Found {len(project_files_relative)} files. Max files to process: {MAX_SYNC_FILES}")

        for rel_path in project_files_relative:
            if files_processed_count >= MAX_SYNC_FILES:
                logging.warning(f"Sync limit reached: Stopped processing after {MAX_SYNC_FILES} files.")
                break

            abs_path = _get_safe_path(project_root, rel_path)
            if abs_path and os.path.isfile(abs_path):
                try:
                    file_size = os.path.getsize(abs_path)
                    if file_size > MAX_FILE_SIZE_BYTES:
                        logging.warning(f"Skipping large file during sync: {rel_path} ({file_size} bytes)")
                        relevant_files_content[rel_path] = f"[File content truncated: Size {file_size} bytes exceeds limit]"
                        # Alternatively, read only the beginning of the file
                        # with open(abs_path, "r", encoding='utf-8', errors='ignore') as f:
                        #     relevant_files_content[rel_path] = f.read(MAX_FILE_SIZE_BYTES) + "\n[... File truncated ...]"
                    else:
                        relevant_files_content[rel_path] = read_file(abs_path)
                        total_size += file_size
                    files_processed_count += 1
                except (IOError, OSError) as e:
                    logging.warning(f"Could not read file during sync {rel_path}: {e}")
                    relevant_files_content[rel_path] = "[Error reading file content]"
            # Add a small delay to avoid overwhelming the filesystem or API if reading many files
            # time.sleep(0.01)


        # Construct prompt for summary
        # Pass empty dict for request_data as sync doesn't have specific user instructions here
        prompt_data = {"request_type": "sync"}
        prompt = construct_prompt(instruction_file_content, prompt_data, relevant_files_content)
        prompt += "\nTask: Provide a concise summary of the project based on the provided file context, its purpose, and any potential issues or suggestions."

        # --- Call LLM ---
        logging.info("Requesting project summary from LLM...")
        summary = generate_content(prompt) # Pass absolute paths if needed

        if summary is None:
            if isinstance(summary, str) and summary.startswith("Error:"):
                 return jsonify({"error": summary}), 500
            return jsonify({"error": "Failed to get project summary from LLM"}), 500

        return jsonify({
            "result": "Project synced successfully.",
            "summary": summary,
            "files_analyzed": files_processed_count,
            "total_files": len(project_files_relative)
            }), 200

    except Exception as e:
        error_message = f"Unexpected error in /sync: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route("/get_files", methods=["GET"])
def handle_get_files():
    """
    Returns the list of relative file paths in the project.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        files = get_project_files(project_root)
        # Also include files in the upload directory if it exists within the root
        upload_dir_rel = FILE_UPLOAD_DIR
        upload_dir_abs = os.path.join(project_root, upload_dir_rel)
        if os.path.isdir(upload_dir_abs):
             for item in os.listdir(upload_dir_abs):
                 item_abs = os.path.join(upload_dir_abs, item)
                 if os.path.isfile(item_abs):
                     item_rel = os.path.join(upload_dir_rel, item)
                     if item_rel not in files: # Avoid duplicates if already caught by get_project_files
                         files.append(item_rel)
        return jsonify({"files": sorted(list(set(files)))}), 200 # Ensure unique and sorted
    except Exception as e:
        error_message = f"Error getting project files: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "Failed to retrieve project file list"}), 500

@app.route("/get_file_content", methods=["GET"])
def handle_get_file_content():
    """
    Returns the content of a specific file using a relative path.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    relative_filepath = request.args.get("filepath")
    if not relative_filepath:
        return jsonify({"error": "'filepath' query parameter is required"}), 400

    # Validate the path
    target_filepath_abs = _get_safe_path(project_root, relative_filepath)
    if not target_filepath_abs or not os.path.isfile(target_filepath_abs):
        return jsonify({"error": f"Invalid or non-existent file: {relative_filepath}"}), 404

    try:
        content = read_file(target_filepath_abs)
        return jsonify({"content": content, "filepath": relative_filepath}), 200
    except IOError as e:
        logging.error(f"Error reading file content for {relative_filepath}: {e}")
        return jsonify({"error": f"Could not read file content: {e}"}), 500
    except Exception as e:
        error_message = f"Unexpected error getting file content: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route("/chat", methods=["POST"])
def handle_chat():
    """
    Handles chat requests, maintaining conversation history in the session.
    """
    project_root = session.get('project_root')
    if not project_root:
        return jsonify({"error": "Project root not set. Use /set_project_root first."}), 400

    try:
        data = request.get_json()
        if not data or "message" not in data or not data["message"]:
            return jsonify({"error": "Missing 'message' in request"}), 400

        user_message = data["message"]

        # --- Prepare Context ---
        instruction_file_path = os.path.join(project_root, ".llm_instructions")
        instruction_file_content = ""
        try:
            if os.path.exists(instruction_file_path):
                 instruction_file_content = read_file(instruction_file_path)
        except IOError as e:
             logging.warning(f"Could not read .llm_instructions file for chat: {e}")

        # Get conversation history from session
        # Limit history size to avoid overly large prompts
        MAX_HISTORY_TURNS = 10 # Keep last 10 pairs (user + llm)
        conversation_history = session.get('conversation_history', [])
        limited_history = conversation_history[-(MAX_HISTORY_TURNS * 2):] # Get last N items

        # Construct prompt including history
        prompt_lines = []
        if instruction_file_content:
            prompt_lines.append("--- General Instructions ---")
            prompt_lines.append(instruction_file_content)
            prompt_lines.append("--- End General Instructions ---\n")

        if limited_history:
            prompt_lines.append("--- Recent Conversation History ---")
            # Format history clearly
            for i in range(0, len(limited_history), 2):
                 if i+1 < len(limited_history):
                     prompt_lines.append(f"User: {limited_history[i]}")
                     prompt_lines.append(f"Assistant: {limited_history[i+1]}")
                 else: # Should not happen if history is paired correctly
                     prompt_lines.append(f"User: {limited_history[i]}")
            prompt_lines.append("--- End History ---\n")

        prompt_lines.append("--- Current User Message ---")
        prompt_lines.append(user_message)
        prompt_lines.append("--- End User Message ---")
        prompt_lines.append("\nTask: Respond helpfully to the user's message, considering the instructions and conversation history.")

        prompt = "\n".join(prompt_lines)

        # --- Call LLM ---
        logging.info("Sending chat message to LLM...")
        response_text = generate_content(prompt)

        if response_text is None:
            if isinstance(response_text, str) and response_text.startswith("Error:"):
                 return jsonify({"error": response_text}), 500
            return jsonify({"error": "Failed to get response from LLM"}), 500

        # --- Update History ---
        # Append the actual user message and the LLM response
        conversation_history.append(user_message)
        conversation_history.append(response_text)
        session['conversation_history'] = conversation_history # Save updated history back to session
        session.modified = True # Mark session as modified

        # Note: Session saving happens in after_request

        return jsonify({"response": response_text}), 200

    except Exception as e:
        error_message = f"Unexpected error in /chat: {e}"
        logging.error(error_message, exc_info=True)
        return jsonify({"error": "An internal server error occurred"}), 500


# --- Main Execution ---

def main(initial_project_root: Optional[str] = None):
    """
    Main function to configure and start the Flask app.

    Args:
        initial_project_root: An optional initial project root path provided via CLI.
                              The user will still need to use /set_project_root via the API/UI.
    """
    # API key check is done at the top level now
    # Create the default upload directory relative to the script location initially
    # It will be created inside the project root once set.
    # os.makedirs(FILE_UPLOAD_DIR, exist_ok=True) # Let routes handle dir creation

    logging.info("Starting Gemini Coder Flask server...")
    logging.info("API Key configured.")
    logging.info("Secret key generated for session management.")
    logging.info("CORS enabled for all routes.")
    if initial_project_root:
         logging.warning(f"Initial project root '{initial_project_root}' provided via CLI, but must be set via /set_project_root API call.")
         # You could optionally pre-populate the session here, but the API flow is cleaner.
         # if os.path.isdir(initial_project_root):
         #     session['project_root'] = os.path.abspath(initial_project_root)
         #     # ... load initial session data ...
         # else:
         #     logging.error(f"Invalid initial project root provided via CLI: {initial_project_root}")


    # Use debug=True for development ONLY, False for production
    # use_reloader=False can be helpful during development if auto-reload causes issues
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    # The command-line argument is now just informational.
    # The actual project root MUST be set via the /set_project_root API endpoint.
    cli_project_root = None
    if len(sys.argv) > 1:
        cli_project_root = sys.argv[1]
        print(f"Note: Project root '{cli_project_root}' provided via command line.")
        print("Please use the UI or API (/set_project_root) to set the active project root.")
        # Basic check if the provided path looks like a directory
        if not os.path.isdir(cli_project_root):
             print(f"Warning: The provided path '{cli_project_root}' does not appear to be a valid directory.")


    main(initial_project_root=cli_project_root)
