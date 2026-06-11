# Change Log

## [v1.0.0] - 6-10-2026

_First App Build_

### Added

- `frontend`
    - `src`
        - `App.jsx` contains all of the main front end code that connects to backend with fastapi
        - `App.css` contains all styling for the app
        - Others contain main window building code
    - `electron`
        - `main.cjs` starts everything and builds from executables
        - `preload.cjs` for context
- `backend`
    - `main.py` runs of the api calls to the front end, configures the stack, and gets it staged
    - `_livestack_utils.py` contains the useful stacking code that actually completes the process