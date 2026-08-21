#pragma once

#include <string>

namespace global_reloc
{

struct MapBounds2D
{
  bool valid = false;
  double min_x = 0.0;
  double min_y = 0.0;
  double max_x = 0.0;
  double max_y = 0.0;
  double resolution = 0.05;
};

// Load Nav2 occupancy grid bounds from map yaml + referenced pgm image.
MapBounds2D loadMapBoundsFromYaml(const std::string &yaml_path);

}  // namespace global_reloc
