# FitsLiveStacker

FitsLiveStacker is a lightweight Windows application for live stacking astrophotography FITS images. The application monitors a selected folder, automatically detects newly saved FITS files, aligns them using star matching, and continuously updates a stacked preview image in real time.

## Features

- Live monitoring of a FITS image directory
- Automatic stacking of existing images when monitoring begins
- Automatic stacking of newly acquired images as they are saved
- Star detection and alignment using Photutils and RANSAC-based image registration
- Rejection of frames with insufficient detected stars
- Real-time preview updates during stacking
- Simple desktop interface built with Electron and React
- FastAPI backend with Python image processing pipeline

## How It Works

1. Select a folder containing FITS images.
2. Click Start Live Stack.
3. Existing FITS files in the folder are stacked automatically.
4. The application continues monitoring the folder for new FITS files.
5. As new images are saved, they are aligned and added to the stack.
6. The preview image updates automatically after each successful frame.

## Supported Formats
- .fit
- .fits

## Technologies Used

### Frontend

- React
- Electron

### Backend

- FastAPI
- Astropy
- Photutils
- OpenCV
- Scikit-Image
- Pillow
- NumPy

## Installation

Run the provided installer and launch FitsLiveStacker from the Start Menu.

## Usage

1. Launch FitsLiveStacker.
2. Click Choose Folder.
3. Select the directory where your capture software saves FITS images.
4. Click Start Live Stack.
5. Monitor stacking progress and preview updates in real time.

## Current Version

Version: 1.0.1

## Future Plans
- Stretch controls
- Histogram display
- Frame quality metrics
- Star count and alignment diagnostics
- Multi-session stacking
- Calibration frame support (flats, bias)

## License

GPL v3.0