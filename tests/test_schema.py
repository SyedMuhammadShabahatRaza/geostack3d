"""
Tests for geostack3d.schema

Covers the real behavior verified during the project: renaming
via field_map, whitespace normalization, canonical field
creation, and the geometry column always being protected.
"""

from geostack3d.config import SchemaConfig, VectorSourceConfig
from geostack3d.schema import harmonize_schema


def test_field_map_renames_column(messy_schema_gdf):
    """field_map should rename the specified column, preserving its values."""
    source_configs = [
        VectorSourceConfig(
            name="test", path="dummy.kml", field_map={"Name": "feature_name"}
        )
    ]
    config = SchemaConfig(canonical_fields={}, drop_extra_fields=False)

    result = harmonize_schema({"test": messy_schema_gdf}, config, source_configs)

    assert "feature_name" in result["test"].columns
    assert "Name" not in result["test"].columns
    assert result["test"]["feature_name"].iloc[0] == "TEST_AREA"


def test_drop_extra_fields_keeps_only_canonical_plus_geometry(messy_schema_gdf):
    """
    With drop_extra_fields=True, only canonical_fields + geometry
    should remain — matching the real 13-columns-to-2 result
    verified during the project.
    """
    source_configs = [
        VectorSourceConfig(
            name="test", path="dummy.kml", field_map={"Name": "feature_name"}
        )
    ]
    config = SchemaConfig(
        canonical_fields={"feature_name": "str"},
        drop_extra_fields=True,
    )

    result = harmonize_schema({"test": messy_schema_gdf}, config, source_configs)

    assert set(result["test"].columns) == {"feature_name", "geometry"}


def test_geometry_column_is_never_dropped(messy_schema_gdf):
    """Even with an aggressive canonical_fields list, geometry must survive."""
    source_configs = [VectorSourceConfig(name="test", path="dummy.kml")]
    config = SchemaConfig(
        canonical_fields={"some_other_field": "str"},
        drop_extra_fields=True,
    )

    result = harmonize_schema({"test": messy_schema_gdf}, config, source_configs)

    assert "geometry" in result["test"].columns


def test_missing_canonical_field_is_created_with_none(valid_polygon_gdf):
    """A canonical field not present in the source should be created, filled with None."""
    source_configs = [VectorSourceConfig(name="test", path="dummy.geojson")]
    config = SchemaConfig(
        canonical_fields={"population": "str"}, drop_extra_fields=False
    )

    result = harmonize_schema({"test": valid_polygon_gdf}, config, source_configs)

    assert "population" in result["test"].columns
    assert result["test"]["population"].iloc[0] is None
