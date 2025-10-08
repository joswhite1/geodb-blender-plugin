# geoDB Blender Add-on

A Blender add-on that integrates with the geoDB API to visualize drill hole data, samples, and perform geological modeling.

## Features

- **Secure Authentication**: Log in to the geoDB API with your credentials
- **Data Visualization**: View drill holes, samples, and geological data in 3D
- **Sample Analysis**: Color-code samples based on assay values, lithology, or alteration
- **RBF Interpolation**: Create interpolated surfaces from sample data
- **Customization**: Configure visualization settings and color schemes

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

Copyright © 2024 Aqua Terra Geoscientists. All rights reserved.

## Contact

For support or inquiries, contact support@geodb.io