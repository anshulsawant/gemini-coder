import gradio as gr
import requests
import json
import os

FLASK_SERVER_URL = "http://localhost:5000"  # Or your Flask server URL

def send_message(message, history):
    """Sends a message to the Flask server's /chat endpoint and updates the chat history."""
    try:
        response = requests.post(
            f"{FLASK_SERVER_URL}/chat",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"message": message}),
        )
        response.raise_for_status()
        result = response.json()
        llm_response = result["response"]
        # Update history and return
        history.append([message, llm_response])
        return history, history
    except requests.exceptions.RequestException as e:
        error_message = f"Error sending message: {e}"
        print(error_message)  # Keep the print for console debugging
        return history, history + [[message, error_message]]

def get_project_files():
    """Fetches the list of files from the Flask server's /get_files endpoint."""
    try:
        response = requests.get(f"{FLASK_SERVER_URL}/get_files")
        response.raise_for_status()
        result = response.json()
        return result["files"]
    except requests.exceptions.RequestException as e:
        error_message = f"Error fetching project files: {e}"
        print(error_message)
        return ["Error: Could not retrieve file list"]

def get_file_content(filepath):
    """Fetches the content of a file from the Flask server."""
    try:
        response = requests.get(f"{FLASK_SERVER_URL}/get_file_content?filepath={filepath}")
        response.raise_for_status()
        result = response.json()
        return result["content"]
    except requests.exceptions.RequestException as e:
        error_message = f"Error fetching file content: {e}"
        print(error_message)
        return "Error: Could not retrieve file content"

def display_file_content(filepath):
    """Displays the content of a selected file."""
    content = get_file_content(filepath)
    return content

def handle_generate(filename, instructions):
    """Handles the /generate endpoint call."""
    try:
        response = requests.post(
            f"{FLASK_SERVER_URL}/generate",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"filename": filename, "instructions": instructions}),
        )
        response.raise_for_status()
        result = response.json()
        return result["result"]  # Or appropriate message
    except requests.exceptions.RequestException as e:
        error_message = f"Error generating file: {e}"
        print(error_message)
        return f"Error: {error_message}"

def handle_modify(filepath, instructions):
    """Handles the /modify endpoint call."""
    try:
        response = requests.post(
            f"{FLASK_SERVER_URL}/modify",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"filepath": filepath, "instructions": instructions}),
        )
        response.raise_for_status()
        result = response.json()
        if result["result"] == "Diff created":
            # Display the diff in a new window/tab (simulated here)
            print(f"Opening diff in editor (simulated): {result['diff_file_path']}")
            print(f"Original Content: \n {result['original_content']}")
            print(f"Modified Content: \n {result['modified_content']}")
            return "Diff opened. Please confirm changes to apply." #  feedback to user
        else:
            return result["result"] #  Error from server.
    except requests.exceptions.RequestException as e:
        error_message = f"Error modifying file: {e}"
        print(error_message)
        return f"Error: {error_message}"
    
def handle_apply_changes(filepath, modified_content):
    """Sends the modified content to the server to be written to the file."""
    try:
        response = requests.post(
            f"{FLASK_SERVER_URL}/apply_changes",  #  New endpoint
            headers={"Content-Type": "application/json"},
            data=json.dumps({"filepath": filepath, "modified_content": modified_content}),
        )
        response.raise_for_status()
        result = response.json()
        return result["result"]
    except requests.exceptions.RequestException as e:
        error_message = f"Error applying changes: {e}"
        print(error_message)
        return f"Error: {error_message}"


def create_file_explorer():
    """Creates a Gradio component for exploring project files."""
    files = get_project_files()
    if not files:
        return gr.Markdown("No files found or error retrieving file list.")

    file_display = gr.Markdown("Select a file to view its content.")
    file_dropdown = gr.Dropdown(choices=files, label="Project Files")

    file_dropdown.change(
        fn=display_file_content,
        inputs=file_dropdown,
        outputs=file_display,
    )
    return file_dropdown, file_display # Return both

# Create a Gradio ChatInterface
chat_interface = gr.ChatInterface(
    fn=send_message,
    title="LLM Chat Interface",
    chatbot=gr.Chatbot(
        label="Conversation",
        bubble_colors=["#F0F4C3", "#90EE90"],  # Example color styling
        style="compact"
    ),
    textbox=gr.Textbox(
        placeholder="Type your message here...",
        container=True,
        autofocus=True
    ),
    clear_btn="Clear",
    live_mode=False
)

# Combine ChatInterface and file explorer in a Row
with gr.Blocks() as iface:
    with gr.Row():
        with gr.Column(scale=2):
            chat_interface_out = chat_interface.render() # Keep a reference
        with gr.Column(scale=1):
            file_dropdown, file_content_display = create_file_explorer()

    # Add Generate and Modify buttons and inputs
    with gr.Row():
        generate_filename_input = gr.Textbox(label="New File Name")
        generate_instructions_input = gr.Textbox(label="Generation Instructions")
        generate_button = gr.Button("Generate File")

    with gr.Row():
        modify_file_dropdown = gr.Dropdown(choices=get_project_files(), label="File to Modify")
        modify_instructions_input = gr.Textbox(label="Modification Instructions")
        modify_button = gr.Button("Modify File")
        apply_changes_button = gr.Button("Apply Changes", visible=False) # Initially hidden

    # Connect buttons to functions
    generate_button.click(
        fn=handle_generate,
        inputs=[generate_filename_input, generate_instructions_input],
        outputs=chat_interface_out.chatbot  #  Update the chat output.
    )
    
    # Store the modify result
    modify_result = modify_button.click(
        fn=handle_modify,
        inputs=[modify_file_dropdown, modify_instructions_input],
        outputs=chat_interface_out.chatbot #  Update the chat output.
    )
    
    #show the apply button.
    apply_changes_button.style(display='block')
    
    apply_changes_button.click(
        fn=handle_apply_changes,
        inputs=[modify_file_dropdown, modify_result], # Pass the file path and modified content
        outputs=chat_interface_out.chatbot
    )

if __name__ == "__main__":
    iface.launch()
