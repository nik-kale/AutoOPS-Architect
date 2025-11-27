# Contributing to AutoOps Architect

Thank you for your interest in contributing to AutoOps Architect! This document provides guidelines and instructions for contributing.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- A GitHub account

### Development Setup

1. **Fork the repository** on GitHub

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/AutoOPS-Architect.git
   cd AutoOPS-Architect
   ```

3. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   # or
   venv\Scripts\activate     # Windows
   ```

4. **Install development dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

5. **Run tests to verify setup**:
   ```bash
   pytest
   ```

## Development Workflow

### Creating a Branch

Create a branch for your work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### Making Changes

1. Make your changes
2. Add/update tests as needed
3. Update documentation if applicable
4. Run tests: `pytest`
5. Run linting: `ruff check src/`
6. Run type checking: `mypy src/autoops_architect`

### Committing

Write clear commit messages:

```
feat: Add support for PagerDuty integration

- Add PagerDutyTool class
- Add tests for incident creation
- Update tools documentation
```

Use conventional commit prefixes:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Test additions/changes
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

### Submitting a Pull Request

1. Push your branch to your fork
2. Open a Pull Request against the main repository
3. Fill out the PR template
4. Wait for review

## Contribution Types

### Adding a New Tool

Tools are a great way to contribute! Here's how:

1. **Create the tool class** in `src/autoops_architect/tools/`:

   ```python
   # src/autoops_architect/tools/my_tool.py
   from autoops_architect.tools.base import Tool, ToolResult

   class MyAwesomeTool(Tool):
       @property
       def tool_id(self) -> str:
           return "my_awesome_tool"

       @property
       def description(self) -> str:
           return "Does something awesome"

       async def execute(self, params, context=None) -> ToolResult:
           # Implementation
           return ToolResult.success({"result": "done"})
   ```

2. **Add tests** in `tests/test_tools.py`:

   ```python
   class TestMyAwesomeTool:
       @pytest.mark.asyncio
       async def test_basic_functionality(self):
           tool = MyAwesomeTool()
           result = await tool.execute({"param": "value"})
           assert result.status == ToolStatus.SUCCESS
   ```

3. **Export in `__init__.py`**

4. **Document** in `docs/tools.md`

### Adding Node Types

1. Add the type to `NodeType` enum in `models/workflow.py`
2. Update the system prompt in `planner/prompts.py`
3. Add documentation in `docs/workflows.md`
4. Add tests

### Adding Memory Backends

1. Create a class extending `MemoryBackend`
2. Implement all required methods
3. Add to `get_memory_backend()` factory
4. Add tests and documentation

### Creating Example Workflows

1. Add goal description in `examples/goals/`
2. Add workflow JSON in `examples/workflows/`
3. Ensure the workflow is valid: `autoops validate examples/workflows/your_workflow.json`

### Improving Documentation

- Fix typos and clarify explanations
- Add more examples
- Improve code comments
- Add diagrams

## Code Style

### Python Style

- Follow PEP 8
- Use type hints everywhere
- Write docstrings for public functions
- Keep functions focused and small

Example:

```python
from typing import Optional

def process_workflow(
    workflow_id: str,
    options: Optional[dict[str, str]] = None,
) -> WorkflowResult:
    """
    Process a workflow by ID.

    Args:
        workflow_id: The unique workflow identifier.
        options: Optional processing options.

    Returns:
        The result of workflow processing.

    Raises:
        WorkflowNotFoundError: If the workflow doesn't exist.
    """
    ...
```

### Testing Style

- Use pytest fixtures for common setup
- Test both success and failure cases
- Use descriptive test names
- Mock external dependencies

```python
class TestMyFeature:
    """Tests for MyFeature."""

    def test_basic_case(self, fixture):
        """Test basic functionality."""
        result = my_function(fixture)
        assert result == expected

    def test_error_handling(self):
        """Test that errors are handled correctly."""
        with pytest.raises(ValueError):
            my_function(invalid_input)
```

## Testing

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=autoops_architect --cov-report=html

# Specific test file
pytest tests/test_models.py

# Specific test
pytest tests/test_models.py::TestGoal::test_goal_creation

# Verbose output
pytest -v
```

### Test Categories

- **Unit tests**: Test individual components in isolation
- **Integration tests**: Test component interactions
- **End-to-end tests**: Test full workflows

## Documentation

### Updating Documentation

1. **Code docstrings**: Update when changing public APIs
2. **README.md**: Update for significant features
3. **docs/**: Update relevant documentation files

### Documentation Style

- Use clear, simple language
- Include code examples
- Add diagrams where helpful
- Keep examples runnable

## Issue Guidelines

### Reporting Bugs

Include:
1. AutoOps Architect version
2. Python version
3. Operating system
4. Steps to reproduce
5. Expected vs actual behavior
6. Error messages/logs

### Feature Requests

Include:
1. Use case description
2. Proposed solution
3. Alternatives considered
4. Willingness to implement

## Code Review Process

1. **Automated checks**: CI must pass
2. **Code review**: At least one maintainer approval
3. **Documentation**: Must be updated if needed
4. **Tests**: Must be added for new features

## Community

### Getting Help

- Open a GitHub issue for bugs
- Start a discussion for questions
- Check existing issues before creating new ones

### Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow

## Recognition

Contributors will be:
- Listed in release notes
- Added to CONTRIBUTORS file
- Thanked in project announcements

Thank you for contributing to AutoOps Architect!
