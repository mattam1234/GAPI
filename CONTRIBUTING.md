# Contributing to GAPI

Thank you for your interest in contributing to GAPI! This document provides guidelines and information for contributors.

## Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/GAPI.git
   cd GAPI
   ```

3. Create a virtual environment (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Linux/Mac
   # or
   venv\Scripts\activate  # On Windows
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Try the demo to ensure everything works:
   ```bash
   python3 demo.py
   ```

## Code Style

- Follow PEP 8 Python style guidelines
- Use meaningful variable and function names
- Add docstrings to classes and functions
- Keep functions focused and modular
- Use type hints where appropriate

## Testing Your Changes

1. **Syntax Check**: Ensure your code has no syntax errors
   ```bash
   python3 -m py_compile gapi.py
   ```

2. **Demo Mode**: Test basic functionality without Steam credentials
   ```bash
   python3 demo.py
   ```

3. **Real Testing**: If you have Steam credentials configured, test all modes:
   ```bash
   python3 gapi.py              # Interactive mode
   python3 gapi.py --random     # Quick pick
   python3 gapi.py --stats      # Statistics
   python3 gapi.py --help       # Help
   ```

## Feature Ideas

Here are some ideas for future enhancements:

### High Priority
- [ ] Add filter by game genre/tags
- [ ] Support for multiple Steam accounts
- [ ] Export/import game history
- [ ] Add game recommendations based on play patterns

### Medium Priority
- [ ] Web interface using Flask
- [ ] Integration with other platforms (Epic Games, GOG)
- [ ] Add game reviews from multiple sources
- [ ] Save favorite games list
- [ ] Schedule/reminder for game sessions

### Low Priority
- [ ] GUI using tkinter or PyQt
- [ ] Mobile app companion
- [ ] Social features (share picks with friends)
- [ ] Achievement tracking

## Pull Request Process

1. Create a new branch for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and commit them:
   ```bash
   git add .
   git commit -m "Add feature: description"
   ```

3. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

4. Create a Pull Request on GitHub

5. Ensure your PR:
   - Has a clear description of changes
   - Includes updates to documentation if needed
   - Passes all syntax checks
   - Doesn't introduce security vulnerabilities

## Bug Reports

When reporting bugs, please include:

1. **Description**: Clear description of the bug
2. **Steps to Reproduce**: How to trigger the bug
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**:
   - Python version
   - Operating system
   - GAPI version/commit

## Questions and Support

- Check existing issues before creating new ones
- Use clear, descriptive titles
- Provide as much context as possible

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help create a welcoming environment for all contributors

## License

By contributing to GAPI, you agree that your contributions will be licensed under the MIT License.
