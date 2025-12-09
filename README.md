# geoDB Blender Add-on

A Blender add-on that integrates with the geoDB API to visualize drill hole data, samples, and perform geological modeling.

For detailed documentation on all features, see the [User Guide](USER_GUIDE.md).

## Features

- **Authentication & Session Management**: Secure login with encrypted token storage
- **Data Import**: Load companies, projects, drill holes, and samples from the geoDB API
- **Drill Hole Visualization**:
  - Assay intervals with color-coded grade ranges
  - Lithology, alteration, and mineralization intervals
  - Customizable tube diameters per interval type
- **Terrain Import**: High-resolution DEM with satellite/topographic textures
- **Drillhole Planning**: Design new holes with azimuth, dip, and length parameters
- **RBF Interpolation**: Create 3D grade models with anisotropic search ellipsoids
- **Simulation Tools**: Generate synthetic drill data for testing (porphyry, vein deposits)

## Installation

1. Download the latest release from the [Releases](https://github.com/aquaterra/geodb-blender-plugin/releases) page
2. In Blender, go to Edit > Preferences > Add-ons > Install
3. Select the downloaded zip file and click "Install Add-on"
4. Enable the add-on by checking the box next to "3D View: geoDB Integration"

## Requirements

- Blender 3.0 or newer
- Internet connection for API access
- geoDB account with API access

## Usage

1. Open the geoDB panel in the 3D View sidebar (press N to show the sidebar)
2. Log in with your geoDB credentials
3. Select a company and project
4. Choose drill holes to visualize
5. Configure visualization options
6. Use the RBF interpolation tools to create surfaces

## Development

### Setup

1. Clone this repository
2. Create a symbolic link from the `geodb_blender` directory to your Blender add-ons directory
3. Enable the add-on in Blender preferences

### Dependencies

The add-on will automatically install required Python packages:
- requests
- cryptography
- numpy

### Structure

- `geodb_blender/`: Main add-on package
  - `api/`: API client and authentication modules
  - `ui/`: User interface components
  - `core/`: Core functionality for data processing and visualization
  - `utils/`: Utility functions and classes

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 2 of the License, or (at your option) any later version.

See [LICENSE](LICENSE) for the full license text.

Copyright © 2025 Aqua Terra Geoscientists.

## Contact

For support or inquiries, contact support@geodb.io