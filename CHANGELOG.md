# Change Log

## [v1.0.1] - 6-11-2026

_Basic Improvements

### Added

- Downsampling images for star finder that speeds time up by as much as 15x
- Faster warping for star alignment
- Parallelized sigma clipping
- Ability to save image after stack is done

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