# DeepOrigin CLI Architecture

## Overview

The DeepOrigin CLI is a Python package that provides a command-line interface and Python client for working with the DeepOrigin platform. It supports drug discovery workflows, data management, and platform interactions.

## Module Organization

### Core Modules

#### `src/` - Main Package Root
- **`__init__.py`** - Package initialization, version management, and DataFrame export
- **`auth.py`** - Authentication handling, token management, and JWT operations
- **`exceptions.py`** - Custom exception classes for the package
- **`feature_flags.py`** - Feature flag management system
- **`warnings.py`** - Custom warning classes
- **`VERSION`** - Version file for the package

#### `src/cli/` - Command Line Interface
- **`__init__.py`** - CLI application setup using Cement framework
- **`config.py`** - Configuration management controllers

**Dependencies:**
- `cement` - CLI framework
- `deeporigin.auth` - Authentication
- `deeporigin.config` - Configuration management
- `deeporigin.exceptions` - Custom exceptions

#### `src/config/` - Configuration Management
- **`__init__.py`** - Configuration module initialization
- **`default.yml`** - Default configuration template

#### `src/data_hub/` - Data Hub API
- **`__init__.py`** - Module initialization
- **`api.py`** - High-level data hub API functions (1,636 lines)
- **`_api.py`** - Low-level API wrapper (248 lines)
- **`dataframe.py`** - DataFrame functionality (436 lines)
- **`filters.py`** - Data filtering utilities (54 lines)

**Dependencies:**
- `deeporigin.utils` - Core utilities
- `deeporigin.exceptions` - Custom exceptions
- `pandas` - Data manipulation

#### `src/drug_discovery/` - Drug Discovery Workflows
- **`__init__.py`** - Module initialization and lazy imports
- **`complex.py`** - Main Complex class for protein-ligand interactions (248 lines)
- **`chemistry.py`** - Chemistry utilities and molecule handling (646 lines)
- **`docking.py`** - Molecular docking functionality (353 lines)
- **`abfe.py`** - Absolute binding free energy calculations (360 lines)
- **`rbfe.py`** - Relative binding free energy calculations (309 lines)
- **`utils.py`** - Drug discovery utilities (281 lines)
- **`constants.py`** - Constants and tool mappings (121 lines)
- **`workflow_step.py`** - Workflow step management (103 lines)

**Submodules:**
- **`structures/`** - Molecular structure classes
  - `entity.py` - Base entity class
  - `ligand.py` - Ligand structure handling
  - `protein.py` - Protein structure handling
  - `pocket.py` - Binding pocket analysis
  - `internal_structures.py` - Internal structure utilities
- **`utilities/`** - Utility functions
- **`external_tools/`** - External tool integrations
- **`molstar_ext/`** - MolStar visualization extensions

**Dependencies:**
- `deeporigin.platform` - Platform API access
- `deeporigin.tools` - Tool execution
- `deeporigin.functions` - Computational functions
- `deeporigin.utils` - Core utilities
- `rdkit` - Chemistry toolkit
- `biotite` - Bioinformatics toolkit



**Dependencies:**
- `do-sdk-platform` - Auto-generated platform SDK
- `deeporigin.auth` - Authentication
- `deeporigin.config` - Configuration

#### `src/tools/` - Tool Execution and Job Management
- **`__init__.py`** - Module initialization
- **`job.py`** - Job management and monitoring (544 lines)
- **`job_viz_functions.py`** - Job visualization functions (251 lines)

**Dependencies:**
- `deeporigin.platform` - Platform API access
- `deeporigin.drug_discovery` - Drug discovery constants
- `jinja2` - Template rendering
- `pandas` - Data manipulation

#### `src/utils/` - Core Utilities
- **`__init__.py`** - Module initialization
- **`core.py`** - Core utility functions (490 lines)
- **`config.py`** - Configuration utilities (56 lines)
- **`constants.py`** - Constants and enums (53 lines)
- **`network.py`** - Network utilities (122 lines)
- **`notebook.py`** - Notebook environment detection (155 lines)

#### `src/functions/` - Computational Functions
- **`docking.py`** - Docking functions
- **`loop_modelling.py`** - Loop modeling functions
- **`molprops.py`** - Molecular property calculations
- **`pocket_finder.py`** - Pocket finding algorithms
- **`rbfe_tools.py`** - RBFE calculation tools
- **`sysprep.py`** - System preparation functions

#### `src/files/` - File Management
- **`files_client.py`** - File client implementation
- **`file_service/`** - Auto-generated file service code

#### `src/templates/` - HTML Templates
- **`job.html`** - Job visualization template
- **`job_jupyter.html`** - Jupyter-specific job template

## Dependency Graph

```
src/
├── cli/                    # CLI interface
│   ├── auth.py            # Authentication
│   └── config/            # Configuration
├── data_hub/              # Data management
│   ├── api.py             # High-level API
│   ├── _api.py            # Low-level API
│   └── dataframe.py       # DataFrame operations
├── drug_discovery/        # Drug discovery workflows
│   ├── complex.py         # Main complex class
│   ├── chemistry.py       # Chemistry utilities
│   ├── docking.py         # Docking calculations
│   ├── abfe.py           # ABFE calculations
│   ├── rbfe.py           # RBFE calculations
│   └── structures/        # Molecular structures
├── platform/              # Platform API access
│   ├── utils.py           # Platform utilities

├── tools/                 # Tool execution
│   ├── job.py             # Job management
│   └── job_viz_functions.py
├── utils/                 # Core utilities
│   ├── core.py            # Core functions
│   ├── config.py          # Config utilities
│   └── constants.py       # Constants
├── functions/             # Computational functions
├── files/                 # File management
└── templates/             # HTML templates
```

## Key Dependencies Between Modules

1. **Authentication Flow:**
   - `auth.py` → `config/` → `platform/utils.py`
   - All API modules depend on authentication

2. **Drug Discovery Workflow:**
   - `drug_discovery/complex.py` → `drug_discovery/*.py`
   - `drug_discovery/` → `platform/` → `tools/`
   - `drug_discovery/` → `functions/`

3. **Data Hub Operations:**
   - `data_hub/api.py` → `data_hub/_api.py`
   - `data_hub/` → `utils/` → `platform/`

4. **Tool Execution:**
   - `tools/job.py` → `platform/tools_api.py`
   - `tools/` → `drug_discovery/constants.py`

## External Dependencies

### Core Dependencies
- `cement` - CLI framework
- `pandas` - Data manipulation
- `beartype` - Runtime type checking
- `requests` - HTTP client
- `pyyaml` - YAML configuration

### Scientific Computing
- `rdkit` - Chemistry toolkit
- `biotite` - Bioinformatics
- `biopython` - Bioinformatics
- `deeporigin-molstar` - Molecular visualization

### Platform SDKs
- `deeporigin-data-sdk` - Data hub SDK
- `do-sdk-platform` - Platform API SDK

## Architecture Patterns

### 1. Layered Architecture
- **Presentation Layer:** `cli/` - Command line interface
- **Business Logic Layer:** `drug_discovery/`, `data_hub/` - Core functionality
- **Data Access Layer:** `platform/`, `files/` - API and file access
- **Infrastructure Layer:** `utils/`, `functions/` - Utilities and computations

### 2. Dependency Injection
- Platform clients are injected into drug discovery classes
- Authentication tokens are managed centrally and injected where needed

### 3. Facade Pattern
- `data_hub/api.py` provides a high-level facade over low-level `_api.py`
- `platform/utils.py` provides a facade over auto-generated SDK code

### 4. Strategy Pattern
- Different visualization functions for different job types in `tools/job_viz_functions.py`
- Different tool execution strategies in `drug_discovery/`

## Code Quality Issues and Suggestions

### 1. **Large Files**
**Issues:**
- `src/data_hub/api.py` (1,636 lines) - Too large, violates single responsibility
- `src/tools/job.py` (544 lines) - Complex job management logic
- `src/drug_discovery/chemistry.py` (646 lines) - Chemistry utilities

**Suggestions:**
- Split `api.py` into domain-specific modules (files, databases, workspaces)
- Extract job visualization logic from `job.py` into separate modules
- Break down `chemistry.py` into focused modules (molecule handling, calculations, etc.)

### 2. **Circular Dependencies**
**Issues:**
- Complex interdependencies between `drug_discovery/`, `platform/`, and `tools/`
- Some modules import from each other creating potential circular imports

**Suggestions:**
- Create clear dependency boundaries
- Use dependency injection to break circular dependencies
- Consider creating an interface layer between modules

### 3. **Mixed Responsibilities**
**Issues:**
- `drug_discovery/complex.py` handles both data management and workflow orchestration
- `tools/job.py` mixes job tracking with visualization

**Suggestions:**
- Separate concerns: data models, business logic, and presentation
- Create dedicated visualization modules
- Extract workflow orchestration into separate classes

### 4. **Inconsistent Error Handling**
**Issues:**
- Some modules use custom exceptions, others use generic exceptions
- Error messages vary in format and detail

**Suggestions:**
- Standardize error handling across all modules
- Create domain-specific exception hierarchies
- Implement consistent error message formatting

### 5. **Configuration Management**
**Issues:**
- Configuration scattered across multiple modules
- Hard-coded values in some places

**Suggestions:**
- Centralize configuration management
- Use environment variables for sensitive data
- Implement configuration validation

### 6. **Testing Coverage**
**Issues:**
- Limited test coverage for complex modules
- Integration tests missing for key workflows

**Suggestions:**
- Add comprehensive unit tests for all modules
- Create integration tests for drug discovery workflows
- Implement property-based testing for data validation

### 7. **Documentation**
**Issues:**
- Some modules lack comprehensive docstrings
- API documentation could be more detailed

**Suggestions:**
- Add comprehensive docstrings to all public APIs
- Create API documentation using tools like Sphinx
- Add usage examples for complex workflows

### 8. **Performance Considerations**
**Issues:**
- Some operations could be optimized (file uploads, data processing)
- Memory usage in large data operations

**Suggestions:**
- Implement streaming for large file operations
- Add caching for frequently accessed data
- Optimize data structures for memory efficiency

## Recommended Refactoring Plan

### Phase 1: Module Decomposition
1. Split `data_hub/api.py` into domain modules
2. Extract visualization logic from `tools/job.py`
3. Break down `drug_discovery/chemistry.py`

### Phase 2: Dependency Management
1. Create clear module boundaries
2. Implement dependency injection patterns
3. Remove circular dependencies

### Phase 3: Error Handling and Configuration
1. Standardize exception handling
2. Centralize configuration management
3. Add comprehensive logging

### Phase 4: Testing and Documentation
1. Add comprehensive test coverage
2. Improve API documentation
3. Add usage examples

### Phase 5: Performance Optimization
1. Optimize file operations
2. Implement caching strategies
3. Add performance monitoring
