"""
Geometric utility functions for drug discovery.

Provides functions for working with 3D bounding boxes used in docking and
other structure-based drug discovery workflows.
"""


def calculate_box_min_max(box_center, box_dimensions):
    """
    Calculate the minimum and maximum coordinates of a box given its center and dimensions.

    Args:
        box_center (List[float]): Center coordinates of the box [x, y, z]
        box_dimensions (List[float]): Dimensions of the box [length, width, height]

    Returns:
        tuple: A tuple containing:
            - List[float]: Minimum coordinates [x_min, y_min, z_min]
            - List[float]: Maximum coordinates [x_max, y_max, z_max]
    """
    half_dims = [dim / 2 for dim in box_dimensions]
    min_corner = [
        center - half for center, half in zip(box_center, half_dims, strict=False)
    ]
    max_corner = [
        center + half for center, half in zip(box_center, half_dims, strict=False)
    ]
    return min_corner, max_corner


def calculate_box_dimensions(min_coords, max_coords):
    """
    Calculate box dimensions from minimum and maximum coordinates.

    Args:
        min_coords (List[float]): The minimum x, y, z coordinates of the box
        max_coords (List[float]): The maximum x, y, z coordinates of the box

    Returns:
        List[float]: The dimensions of the box [length, width, height]

    Raises:
        ValueError: If either min_coords or max_coords does not have exactly 3 elements
    """
    if len(min_coords) != 3 or len(max_coords) != 3:
        raise ValueError("min_coords and max_coords must each have exactly 3 elements.")

    length = max_coords[0] - min_coords[0]
    width = max_coords[1] - min_coords[1]
    height = max_coords[2] - min_coords[2]

    return [float(length), float(width), float(height)]
