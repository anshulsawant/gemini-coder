from setuptools import setup, find_packages
import os

# Function to read the requirements file
def read_requirements(file_path='requirements.txt'):
    """Reads requirements from a file."""
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found. Skipping dependency installation.")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

# Function to read the README file
def read_readme(file_path='README.md'):
    """Reads the README file for long description."""
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found. Long description will be empty.")
        return ""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Warning: Could not read {file_path}. Error: {e}")
        return ""

setup(
    name='gemini-coder',  # Your project's name
    version='0.2.0',      # Update version number
    description='A tool to integrate Google Gemini API into coding workflows via a server and UI.',
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    author='Anshul Sawant',  # Replace with your name
    author_email='your_email@example.com', # Optional: Replace with your email
    url='https://github.com/anshulsawant/gemini-coder',  # Replace with your repository URL
    # find_packages() will discover packages in the current directory
    # If you later move code into a src/ directory, adjust accordingly:
    packages=find_packages('src'),
    package_dir={'': 'src'},
    packages=find_packages(), # Finds 'server.py' and 'app.py' if they were modules, but they are scripts.
                              # This is okay for now, but better structure involves putting code in a package directory.
    py_modules=['server', 'app'], # Explicitly list top-level scripts/modules if not in a package
    install_requires=read_requirements(), # Read dependencies from requirements.txt
    entry_points={
        # Define command-line scripts if desired
        # Example: Make 'gemini-coder-server' run the server main function
        'console_scripts': [
            # 'gemini-coder-server = server:main_cli', # Assumes you create a main_cli() in server.py
            # 'gemini-coder-ui = app:main_cli',     # Assumes you create a main_cli() in app.py
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Code Generators',
        'Topic :: Text Processing :: Linguistic',
        'License :: OSI Approved :: MIT License', # Choose your license
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Operating System :: OS Independent',
        'Environment :: Web Environment',
        'Framework :: Flask',
    ],
    keywords='llm, gemini, ai, developer tools, code generation, gradio, flask',
    python_requires='>=3.9', # Specify minimum Python version
)
