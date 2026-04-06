# GitHub Copilot Instructions for Website Wizard

## Overview
This project is a web application built using Flask, designed to help users create and manage their business websites easily. The architecture is modular, allowing for the addition of features as needed.

## Architecture
- **Main Components**: The application consists of several key components:
  - **Flask Application**: The core of the application, handling routing and rendering templates.
  - **Templates**: HTML files located in the `templates/` directory, defining the structure of the web pages.
  - **Static Files**: CSS and JavaScript files located in the `static/` directory, providing styling and interactivity.

- **Data Flow**: The application uses Flask's routing to handle user requests and render the appropriate templates. Data flows from the user through the routes defined in `app.py` to the templates.

## Developer Workflows
- **Running the Application**: Use the command `python app.py` to start the Flask development server. Ensure you have Flask installed in your environment.
- **Debugging**: The application runs in debug mode by default, allowing for real-time error tracking and code changes.

## Project Conventions
- **File Structure**: Follow the existing structure of `app.py`, `templates/`, and `static/` for adding new features or pages.
- **CSS Styling**: Use the existing classes defined in `main.css` for consistent styling across the application.

## Integration Points
- **External Dependencies**: Ensure that Flask is installed. You can add other dependencies as needed in a `requirements.txt` file.
- **Cross-Component Communication**: Use Flask's routing to manage navigation between different pages and components.

## Examples
- To add a new page, create a new HTML file in the `templates/` directory and define a new route in `app.py`.
- For styling, utilize the existing CSS classes in `main.css` to maintain a consistent look and feel.

## Conclusion
This document serves as a guide for AI coding agents to understand the structure and workflows of the Website Wizard project. For any unclear sections, please provide feedback for further refinement.