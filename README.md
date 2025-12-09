# geoDB Blender Plugin

A Blender extension for visualizing and analyzing geological drill hole data from the geoDB API.

## Installation

### From Release (Recommended)

1. Download `geodb_blender.zip` from the [Releases](https://github.com/joswhite1/geodb-blender-plugin/releases) page
2. In Blender, go to **Edit → Preferences → Add-ons**
3. Click **Install from Disk** and select the downloaded zip
4. Enable the add-on

### From Source

1. Clone this repository
2. Zip the `geodb_blender/` folder
3. Install the zip in Blender as above

## Requirements

- Blender 4.2 or newer
- geoDB account

## Documentation

See the [User Guide](geodb_blender/USER_GUIDE.md) for detailed documentation.

## Development

For development setup, create a symbolic link from `geodb_blender/` to your Blender extensions folder:

```
%APPDATA%\Blender Foundation\Blender\<version>\extensions\user_default\geodb_blender
```

## License

GPL-2.0-or-later. See [LICENSE](geodb_blender/LICENSE).
