from setuptools import setup, find_packages

setup(
    name='gemini-coder',  # Replace with your project name
    version='0.1.0',
    description='A tool for managing projects with LLMs',
    author='Anshul Sawant',  # Replace with your name
    url='[https://github.com/anshulsawant/gemini-coder](https://github.com/anshulsawant/gemini-coder)',  # Replace with your repository URL
    packages=find_packages(),
    install_requires=[
        'Flask',
        'google-generativeai',
        'flask_cors',
        'gradio',
    ],
    entry_points={
        'console_scripts': [
            'llm-project-manager = app:main',  # Replace app:main if your main function is in a different file or has a different name
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',  # Adjust as appropriate
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Development Tools',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: OS Independent',
    ],
    keywords='llm, gemini, project management, code generation, documentation',
    long_description=open('README.md').read(),  # Make sure this points to the README
    long_description_content_type='text/markdown',
)
