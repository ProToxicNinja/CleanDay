# Overview

Plant Breeder Sim is a genetics simulation game that teaches plant breeding concepts through interactive gameplay. Players start with starter seeds from three species (Pea, Tomato, Marigold) and can plant, grow, and breed plants while learning about Mendelian inheritance, polygenic traits, and epistatic interactions. The game features a greenhouse interface where players manage their plants and seed inventory, with a time-tick system for plant growth simulation.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Backend Architecture
- **Framework**: FastAPI for the web application framework, providing fast async support and automatic API documentation
- **Database**: SQLite with WAL mode for simple file-based persistence, eliminating the need for external database setup
- **Session Management**: Signed cookies using itsdangerous for secure player identification without requiring user registration
- **Template Engine**: Jinja2 for server-side HTML rendering with minimal frontend complexity

## Frontend Architecture
- **Rendering**: Server-side rendering with Jinja2 templates, avoiding frontend build complexity
- **Interactivity**: HTMX via CDN for dynamic interactions without JavaScript frameworks
- **Styling**: Bootstrap 5 via CDN for responsive UI components
- **Icons**: Feather Icons for consistent iconography

## Data Model
- **Users**: Simple player identification with auto-generated IDs
- **Seeds**: Seed lots with species, genome data (JSON), quantity, and generation tracking
- **Plants**: Individual plants with genome, age, health, and growth states
- **Genetics**: JSON-encoded genome data supporting multiple inheritance patterns

## Game Systems
- **Genetics Engine**: Modular system supporting three trait types:
  - Mendelian (dominant/recessive)
  - Polygenic (multiple additive alleles)
  - Epistatic (gene interaction effects)
- **Growth Simulation**: Simple tick-based aging with health decay mechanics
- **Phenotype Expression**: Genome-to-appearance conversion for visual plant representation

## Authentication & Sessions
- **Cookieless Design**: No user registration required
- **Automatic Player Creation**: Middleware automatically creates player IDs on first visit
- **Secure Sessions**: Cryptographically signed cookies prevent tampering
- **Starter Pack**: New players automatically receive initial seed inventory

# External Dependencies

## Python Libraries
- **fastapi**: Web framework for API and route handling
- **uvicorn**: ASGI server for running the FastAPI application
- **jinja2**: Template engine for HTML rendering
- **python-multipart**: Form data parsing support
- **pydantic**: Data validation and serialization
- **itsdangerous**: Cryptographic signing for secure cookies

## Frontend Dependencies (CDN)
- **Bootstrap 5**: CSS framework for responsive UI components
- **HTMX**: Dynamic HTML interactions without JavaScript complexity
- **Feather Icons**: SVG icon library for consistent iconography

## Database
- **SQLite**: Embedded database with no external dependencies
- **WAL Mode**: Write-Ahead Logging for better concurrent access

## Static Assets
- Custom CSS for plant card styling and appearance enhancements
- No build process required - all assets served directly