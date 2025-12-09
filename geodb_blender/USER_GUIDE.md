# geoDB Blender Add-on User Guide

This guide provides comprehensive documentation for all features of the geoDB Blender add-on.

## Download & Installation

**GitHub Repository:** [https://github.com/joswhite1/geodb-blender-plugin](https://github.com/joswhite1/geodb-blender-plugin)

**Direct Download:** [geodb_blender.zip (v0.1.0)](https://github.com/joswhite1/geodb-blender-plugin/releases/download/v0.1.0/geodb_blender.zip)

### Installation Steps

1. Download [geodb_blender.zip](https://github.com/joswhite1/geodb-blender-plugin/releases/download/v0.1.0/geodb_blender.zip) from the latest release
2. Open Blender and go to **Edit > Preferences > Add-ons**
3. Click **Install...** (top right)
4. Navigate to the downloaded `geodb_blender.zip` file and click **Install Add-on**
5. Enable the add-on by checking the box next to **3D View: geoDB Integration**
6. The add-on panel will appear in the 3D Viewport sidebar (press `N` to show)

**Requirements:** Blender 3.0+ and a geoDB account with API access.

**Note:** Do not extract the zip file - Blender installs directly from the .zip archive.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [Data Selection](#data-selection)
4. [Drill Hole Visualization](#drill-hole-visualization)
5. [Terrain Import](#terrain-import)
6. [Drillhole Planning](#drillhole-planning)
7. [RBF Interpolation & Modeling](#rbf-interpolation--modeling)
8. [Simulation Tools](#simulation-tools)
9. [Tips & Workflows](#tips--workflows)

---

## Getting Started

### Accessing the Panel

1. Open the 3D Viewport sidebar by pressing `N`
2. Click the **geoDB** tab to access all features

### Dependencies

The add-on requires the following Python packages (installed automatically on first use):
- requests
- cryptography
- numpy
- scipy
- scikit-image

If automatic installation fails, go to **Edit > Preferences > Add-ons > geoDB Integration** and click **Install All Dependencies**.

---

## Authentication

### Logging In

1. Open the geoDB panel in the sidebar
2. Enter your **Email** and **Password**
3. Click **Login**

### Remember Me (Token Storage)

- Enable **Remember Me** to save your session token locally
- You'll be prompted to create an **Encryption Password** to secure the token
- On subsequent sessions, you can unlock your saved token instead of logging in again

### Session Management

- Your login state is validated when opening `.blend` files
- If your session has expired, you'll be prompted to unlock your saved token or log in again
- Click **Logout** to clear your session

---

## Data Selection

### Selecting a Company

1. After logging in, click **Select Company**
2. Choose from the dropdown list of companies you have access to

### Loading Projects

1. Click **Load Projects** to fetch projects for the selected company
2. Projects load asynchronously (UI remains responsive)
3. Select a project from the dropdown

### Active Object Inspector

When you select any geoDB object in the viewport, the inspector panel shows:
- Object type (drill trace, sample, pad, etc.)
- Location coordinates
- Metadata (element values, lithology type, etc.)
- Available actions:
  - **Select Similar**: Select all objects from the same drill hole
  - **Select Drill Trace**: Jump to the trace for a sample's hole

---

## Drill Hole Visualization

### Assay Visualization

Create 3D tube visualizations of assay intervals along drill holes with color-coded grade ranges.

1. In the **Drill Visualization** panel, click **Load Assay Configuration**
2. Select an element (Cu %, Au ppm, etc.) from available configurations
3. Review the color ranges and adjust **diameter overrides** if needed
4. Click **Create Visualization**

**Settings:**
- **Diameter (Ø)**: Tube diameter for each grade range (in meters)
- **Auto-adjust view**: Automatically frame imported data and set optimal viewport settings

### Lithology Visualization

Display lithology intervals as colored tubes along drill holes.

1. Click **Load Lithology Set**
2. Select a lithology classification set
3. Adjust diameters per lithology type if desired
4. Click **Create Visualization**

### Alteration Visualization

Visualize alteration types (potassic, phyllic, argillic, etc.) as colored tubes.

1. Click **Load Alteration Set**
2. Select an alteration set from the project
3. Configure diameter settings
4. Click **Create Visualization**

### Mineralization Visualization

Display mineralization assemblages along drill holes.

1. Click **Load Mineralization Set**
2. Select a mineralization set
3. Adjust diameters as needed
4. Click **Create Visualization**

### Drill Traces

Drill traces (wireframe paths from collar to bottom) are created automatically when visualizing data. They are desurveyed using the minimum curvature method from survey data.

**Settings:**
- **Trace Segments**: Number of segments for trace resolution (default: 100)

### Diameter Overrides

All diameter settings are persisted in your `.blend` file, so your customizations are saved with your project.

---

## Terrain Import

Import high-resolution terrain meshes with optional texture overlays.

### Importing Terrain

1. In the **Terrain** panel, click **Import Terrain**
2. Select a resolution:
   - **Very Low**: ~62,000 vertices (fast)
   - **Low**: ~250,000 vertices
   - **Medium**: ~1,000,000 vertices (detailed)
3. Choose a texture overlay:
   - Satellite imagery
   - Topographic map
   - None
4. Click **OK**

The terrain downloads asynchronously with a progress indicator.

### Changing Texture

To switch the texture on an existing terrain:

1. Select the terrain mesh in the viewport
2. Click **Change Texture**
3. Select a new texture from available options

---

## Drillhole Planning

Design and preview new drill holes before sending them to the field.

### Importing Drill Pads

1. In the **Drillhole Planning** panel, click **Import Pads from API**
2. Pads are created as 3D extruded polygons at their surveyed elevations

### Selecting a Pad

1. Select a drill pad object in the viewport
2. Click **Select Active Pad** to use it as the collar location

### Defining a Planned Hole

Configure the following parameters:

| Parameter | Description | Range |
|-----------|-------------|-------|
| **Hole Name** | Identifier for the planned hole | e.g., PLN-001 |
| **Hole Type** | Drilling method | DD (Diamond), RC, RAB |
| **Azimuth** | Compass direction (0=North, clockwise) | 0-360° |
| **Dip** | Inclination angle (-90=vertical down) | -90 to 0° |
| **Length** | Planned hole depth | 1-2000 m |

### Using the 3D Cursor

Calculate hole parameters automatically from a target point:

1. Position the 3D cursor at your target location (Shift+Right-click)
2. Click **Calculate from Cursor**
3. Azimuth, dip, and length are calculated from the pad center to the cursor

### Preview and Create

- **Preview**: See the planned hole geometry in the viewport
- **Clear Preview**: Remove the preview
- **Create Hole**: Finalize the planned hole as a 3D object

### Manual Elevation Override

If pad elevation data is missing or incorrect:

1. Enable **Use Manual Elevation**
2. Enter the **Collar Elevation** in meters

---

## RBF Interpolation & Modeling

Create 3D interpolated grade volumes from drill hole sample data using Radial Basis Function (RBF) interpolation.

### Running RBF Interpolation

1. Import drill data with assays first
2. Click **RBF Interpolation** in the modeling panel
3. Select the element to interpolate
4. Configure parameters (see below)
5. Click **OK**

### RBF Parameters

| Parameter | Description | Recommended |
|-----------|-------------|-------------|
| **Kernel** | Interpolation function | Thin Plate Spline |
| **Epsilon** | Shape parameter | 1.0 |
| **Smoothing** | Exact (0) vs smoothed interpolation | 0-1 |
| **Grid Resolution** | Points per axis | 50-100 |

### Output Options

- **Point Cloud**: Creates points colored by grade
- **Volume Mesh**: Creates a solid mesh of the grade shell

### Threshold Filtering

- **Min Value**: Exclude grades below this threshold
- **Max Value**: Exclude grades above this threshold
- **Auto-threshold**: Use the cutoff grade from assay configuration

### Distance Limiting

Control how far the interpolation extends from sample points.

**Isotropic Distance Limit:**
- Single radius in all directions
- Auto-calculates based on sample spacing, or set manually

**Anisotropic Search Ellipsoid:**
- Different radii along major, semi-major, and minor axes
- Configure orientation with azimuth, dip, and plunge angles
- **Show Ellipsoid**: Toggle visualization of the search ellipsoid

### Distance Decay

Smoothly diminish grades away from samples toward a background value.

| Parameter | Description |
|-----------|-------------|
| **Decay Distance** | Distance over which grades fade |
| **Background Value** | Target value at maximum distance (usually 0) |
| **Decay Function** | Linear, Smooth S-curve, or Gaussian |

### Ellipsoid Editor

For interactive ellipsoid configuration:

1. Open the **Ellipsoid Editor** panel
2. Create an ellipsoid widget
3. Transform it in the viewport (rotate, scale)
4. Add control points as boundary constraints
5. Apply interpolation with current settings

### Performance Tips

For large datasets (>1000 samples):
- Enable **Local RBF** with nearest neighbors
- Set neighbor count to 50-100
- Use lower grid resolution initially

---

## Simulation Tools

Generate realistic synthetic drill hole data for testing and demonstration.

### Simulating Drill Data

1. Click **Simulate Drill Data**
2. Select a deposit type:
   - **Porphyry Copper-Gold**: Classic porphyry deposit with concentric alteration
   - **Gold-Silver Vein**: Steeply dipping vein system

### General Parameters

| Parameter | Description | Range |
|-----------|-------------|-------|
| **Number of Holes** | Drill holes to generate | 1-100 |
| **Samples per Hole** | Sample intervals per hole | 5-200 |
| **Area Size** | Horizontal extent (meters) | 10-10,000 |
| **Max Depth** | Maximum hole depth | 10-2,000 |
| **Orebody Size** | Diameter of mineralized zone | 10-1,000 |
| **Noise Level** | Random variation in grades | 0-1 |

### Deposit-Specific Settings

**Porphyry Copper-Gold:**
- Cu grade (max %, background %)
- Au grade (max ppm, background ppm)
- Realistic lithology: Quartz Monzonite Porphyry → wall rock
- Realistic alteration: Potassic → Phyllic → Argillic → Propylitic

**Gold-Silver Vein:**
- Au and Ag grades (max and background)
- Vein orientation (strike, dip)
- Vein thickness and length

### Visualization Options

Toggle what gets displayed after simulation:
- Show drill traces
- Show samples
- Show lithology intervals
- Show alteration intervals

### Color Modes

- **Gradient**: Continuous color scale based on grade
- **Discrete**: Color bands based on cutoff ranges

---

## Tips & Workflows

### Typical Workflow: Visualizing Project Data

1. **Login** to geoDB
2. **Select Company** → **Load Projects** → **Select Project**
3. **Load Assay Configuration** → adjust diameters → **Create Visualization**
4. **Import Terrain** with satellite texture for context
5. Use the inspector to examine individual samples

### Typical Workflow: Planning New Holes

1. **Select Project** with existing drill data
2. **Import Pads from API**
3. **Visualize existing assays** to understand mineralization
4. Select a pad → **Select Active Pad**
5. Position 3D cursor at target → **Calculate from Cursor**
6. Adjust parameters → **Preview** → **Create Hole**

### Typical Workflow: Grade Modeling

1. Import drill data with assays
2. **RBF Interpolation** → select element
3. Configure search ellipsoid to match deposit geometry
4. Enable distance decay for realistic grade boundaries
5. Set threshold to cutoff grade
6. Generate volume mesh

### Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Toggle sidebar | `N` |
| Position 3D cursor | `Shift + Right-click` |
| Frame selected | `Numpad .` |
| Frame all | `Home` |
| Orthographic toggle | `Numpad 5` |

### Performance Recommendations

- Use **Very Low** terrain resolution for initial exploration
- Limit drill hole count when testing visualizations
- Enable **Local RBF** for datasets with >500 samples
- Close unnecessary Blender panels to improve UI responsiveness

### Troubleshooting

**Dependencies not installing:**
- Run Blender as administrator (Windows)
- Check console for error messages
- Manually install: `<blender_python> -m pip install requests cryptography numpy scipy scikit-image`

**Login fails:**
- Verify credentials at geodb.io
- Check internet connection
- Try disabling VPN if present

**Terrain won't load:**
- Ensure project has DEM data configured
- Try a lower resolution first
- Check console for API errors

**RBF interpolation crashes:**
- Reduce grid resolution
- Enable Local RBF with fewer neighbors
- Ensure scipy is installed

---

## API Reference

The add-on communicates with the following geoDB API endpoints:

| Feature | Endpoint |
|---------|----------|
| Authentication | `POST /api/v1/auth/login/` |
| Companies | `GET /api/v1/companies/` |
| Projects | `GET /api/v1/companies/{id}/projects/` |
| Drill Collars | `GET /api/v1/projects/{id}/drill_collars/` |
| Surveys | `GET /api/v1/projects/{id}/surveys/` |
| Samples | `GET /api/v1/projects/{id}/samples/` |
| Assay Configs | `GET /api/v1/projects/{id}/assay_range_configurations/` |
| Lithology Sets | `GET /api/v1/projects/{id}/lithology_sets/` |
| Lithologies | `GET /api/v1/projects/{id}/lithologies/` |
| Alteration Sets | `GET /api/v1/projects/{id}/alteration_sets/` |
| Alterations | `GET /api/v1/projects/{id}/alterations/` |
| Mineralization Sets | `GET /api/v1/projects/{id}/mineralization_sets/` |
| Mineralizations | `GET /api/v1/projects/{id}/mineralizations/` |
| Drill Traces | `GET /api/v1/projects/{id}/drill_traces/` |
| Drill Pads | `GET /api/v1/projects/{id}/drill_pads/` |
| Terrain Mesh | `GET /api/v1/projects/{code}/terrain/mesh/` |
| Terrain Textures | `GET /api/v1/projects/{code}/terrain/textures/` |

---

## Support

For support or inquiries, contact support@geodb.io

For bug reports and feature requests, visit the [GitHub Issues](https://github.com/joswhite1/geodb-blender-plugin/issues) page.
